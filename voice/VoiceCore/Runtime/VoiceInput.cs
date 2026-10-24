using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;

namespace SpatialModeling.VoiceCore
{
    /// <summary>
    /// Feeds microphone audio to an <see cref="ISpeechRecognizer"/> on its own worker thread, so loading the model and
    /// decoding never stall a frame, and hands the results back. Call its members from the Unity main thread; the
    /// recognizer is created, used and disposed on the worker.
    /// </summary>
    public sealed class VoiceInput : IDisposable
    {
        readonly Func<ISpeechRecognizer> createRecognizer;
        readonly int recognizerRate;
        readonly BlockingCollection<Action> work = new BlockingCollection<Action>();
        readonly ConcurrentQueue<RecognitionResult> results = new ConcurrentQueue<RecognitionResult>();
        readonly ConcurrentQueue<float[]> spare = new ConcurrentQueue<float[]>();
        readonly Thread worker;
        bool paused, talking;
        volatile string error;
        volatile bool ready;

        // Worker thread only.
        ISpeechRecognizer recognizer;
        PcmConverter converter;
        short[] pcm = new short[0];
        bool listening;

        /// <param name="createRecognizer">Makes the recognizer on the worker thread, for example
        /// <c>() =&gt; VoskSpeechRecognizer.Load(modelPath)</c>.</param>
        /// <param name="recognizerRate">The sample rate the recognizer gets; Vosk's small English model wants 16 kHz.</param>
        public VoiceInput(Func<ISpeechRecognizer> createRecognizer, int recognizerRate = 16000)
        {
            this.createRecognizer = createRecognizer ?? throw new ArgumentNullException(nameof(createRecognizer));
            this.recognizerRate = recognizerRate;
            worker = new Thread(Run) { IsBackground = true, Name = "VoiceCore recognizer" };
            worker.Start();
        }

        /// <summary>The recognizer is loaded. Audio written before is dropped.</summary>
        public bool Ready => ready;

        /// <summary>Why voice input doesn't work (for example a missing model or native library), or null.</summary>
        public string Error => error;

        /// <summary>
        /// True while a prompt plays (set it together with <see cref="VoiceSession.SetPromptPlaying"/>): audio is dropped
        /// and the utterance in progress is thrown away, so no result can contain the prompt. Speech after the prompt
        /// still counts if push-to-talk stays down.
        /// </summary>
        public bool Paused
        {
            get => paused;
            set
            {
                if (value && !paused)
                    Post(Discard);
                paused = value;
            }
        }

        /// <summary>The recognizer's grammar (<see cref="VoiceSession.GrammarPhrases"/>), from the next utterance on.</summary>
        public void SetGrammar(IReadOnlyList<string> phrases)
        {
            var copy = new List<string>(phrases);
            Post(() => recognizer?.SetGrammar(copy));
        }

        /// <summary>Push-to-talk pressed: starts an utterance. For an open microphone, start once and never stop:
        /// the recognizer then ends utterances at pauses by itself.</summary>
        public void StartUtterance()
        {
            talking = true;
            Post(() =>
            {
                if (recognizer == null)
                    return;
                converter?.Reset();
                recognizer.Start(recognizerRate);
                listening = true;
            });
        }

        /// <summary>Push-to-talk released: ends the utterance; its result follows in <see cref="TryGetResult"/>.</summary>
        public void StopUtterance()
        {
            talking = false;
            Post(() =>
            {
                if (!listening)
                    return;
                listening = false;
                recognizer.Stop();
            });
        }

        /// <summary>
        /// Microphone samples captured since the last call, as Unity's <c>AudioClip.GetData</c> gives them: floats
        /// from -1 to 1, <paramref name="channels"/> interleaved, at <paramref name="sampleRate"/>. The samples are
        /// copied, so the array can be reused.
        /// </summary>
        public void Write(float[] samples, int count, int sampleRate, int channels = 1)
        {
            if (paused || !talking || !ready || count <= 0)
                return;
            if (!spare.TryDequeue(out float[] copy) || copy.Length < count)
                copy = new float[Math.Max(count, 4096)];
            Array.Copy(samples, copy, count);
            Post(() => Accept(copy, count, sampleRate, channels));
        }

        /// <summary>The next final result, in order. Pass it to <see cref="VoiceSession.Hear"/>.</summary>
        public bool TryGetResult(out RecognitionResult result) => results.TryDequeue(out result);

        /// <summary>Stops the worker and disposes the recognizer.</summary>
        public void Dispose()
        {
            if (work.IsAddingCompleted)
                return;
            work.CompleteAdding();
            worker.Join(TimeSpan.FromSeconds(5));
        }

        /// <summary>For tests: waits until the worker has done everything queued so far.</summary>
        internal bool WaitIdle(TimeSpan timeout)
        {
            var done = new ManualResetEventSlim();
            Post(done.Set);
            return done.Wait(timeout);
        }

        void Post(Action action)
        {
            if (!work.IsAddingCompleted)
                work.Add(action);
        }

        void Discard()
        {
            if (listening)
            {
                converter?.Reset();
                recognizer.Start(recognizerRate); // restarting drops the audio heard so far
            }
        }

        void Accept(float[] samples, int count, int rate, int channels)
        {
            try
            {
                if (!listening)
                    return;
                if (converter == null || converter.InputRate != rate || converter.Channels != channels)
                    converter = new PcmConverter(rate, recognizerRate, channels);
                int max = converter.MaxOutput(count - count % channels);
                if (pcm.Length < max)
                    pcm = new short[max];
                int n = converter.Convert(samples, count - count % channels, pcm);
                recognizer.AcceptAudio(pcm, n);
            }
            finally
            {
                spare.Enqueue(samples);
            }
        }

        void Run()
        {
            try
            {
                recognizer = createRecognizer() ?? throw new InvalidOperationException("No recognizer");
                recognizer.Recognized += results.Enqueue;
                ready = true;
            }
            catch (Exception e)
            {
                error = e.GetType().Name + ": " + e.Message;
            }

            foreach (Action action in work.GetConsumingEnumerable())
            {
                try
                {
                    action();
                }
                catch (Exception e)
                {
                    error = e.GetType().Name + ": " + e.Message;
                    listening = false;
                }
            }
            recognizer?.Dispose();
        }
    }
}

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
    /// <para>Push-to-talk can keep a little audio on either side of the button (opt-in; both are 0 by default):
    /// the pre-roll keeps the last <c>prerollMs</c> of audio while the button is up, and <see cref="StartUtterance"/>
    /// feeds it to the recognizer first, so a word started at the press keeps its onset (it needs <see cref="Write"/>
    /// every frame, not only while the button is down); the post-roll keeps accepting <c>postrollMs</c> of audio after
    /// <see cref="StopUtterance"/>, because the microphone's last frames arrive late. See voice/README.md, "Push-to-talk
    /// pre-roll".</para>
    /// </summary>
    public sealed class VoiceInput : IDisposable
    {
        /// <summary>The pre-roll measured with simulated push-to-talk (voice/README.md).</summary>
        public const int RecommendedPrerollMs = 300;

        /// <summary>The post-roll measured with simulated push-to-talk: releasing 50 ms early no longer loses short
        /// answers like "one", "two" and "three".</summary>
        public const int RecommendedPostrollMs = 150;

        readonly Func<ISpeechRecognizer> createRecognizer;
        readonly int recognizerRate;
        readonly int postrollMs;
        readonly BlockingCollection<Action> work = new BlockingCollection<Action>();
        readonly ConcurrentQueue<RecognitionResult> results = new ConcurrentQueue<RecognitionResult>();
        readonly ConcurrentQueue<NoResultReason> noResults = new ConcurrentQueue<NoResultReason>();
        readonly ConcurrentQueue<float[]> spare = new ConcurrentQueue<float[]>();
        readonly Thread worker;
        bool paused, talking;
        int postrollLeft = -1; // samples still to pass after the release: int.MaxValue until the next Write, -1 when not stopping
        volatile string error;
        volatile bool ready;

        // Worker thread only.
        ISpeechRecognizer recognizer;
        PcmConverter converter;
        short[] pcm = new short[0];
        readonly short[] ring; // the pre-roll, at the recognizer rate; empty without one
        int ringStart, ringCount;
        bool listening;
        bool heard;                 // this utterance gave a result
        NoResultReason? reported;   // the recognizer's IReportsNoResult during Stop

        /// <param name="createRecognizer">Makes the recognizer on the worker thread, for example
        /// <c>() =&gt; VoskSpeechRecognizer.Load(modelPath)</c>.</param>
        /// <param name="recognizerRate">The sample rate the recognizer gets; Vosk's small English model wants 16 kHz.</param>
        /// <param name="prerollMs">Audio from before the press that each utterance starts with, for example
        /// <see cref="RecommendedPrerollMs"/>. 0 keeps none, as before.</param>
        /// <param name="postrollMs">Audio after the release that still belongs to the utterance, for example
        /// <see cref="RecommendedPostrollMs"/>. 0 ends the utterance at the release, as before.</param>
        public VoiceInput(Func<ISpeechRecognizer> createRecognizer, int recognizerRate = 16000, int prerollMs = 0, int postrollMs = 0)
        {
            this.createRecognizer = createRecognizer ?? throw new ArgumentNullException(nameof(createRecognizer));
            this.recognizerRate = recognizerRate;
            this.postrollMs = Math.Max(0, postrollMs);
            ring = new short[(int)((long)recognizerRate * Math.Max(0, prerollMs) / 1000)];
            worker = new Thread(Run) { IsBackground = true, Name = "VoiceCore recognizer" };
            worker.Start();
        }

        /// <summary>The recognizer is loaded. Audio written before is dropped.</summary>
        public bool Ready => ready;

        /// <summary>Why voice input doesn't work (for example a missing model or native library), or null.</summary>
        public string Error => error;

        /// <summary>
        /// True while a prompt plays: audio is dropped and the utterance in progress is thrown away, so no result can
        /// contain the prompt. Results of speech that ended before it still arrive, and speech after it counts if
        /// push-to-talk stays down. (<see cref="VoiceSession.SetPromptPlaying"/> is for recognizers that listen by themselves.)
        /// A prompt during the post-roll ends that utterance with the audio it has, and clears the pre-roll.
        /// </summary>
        public bool Paused
        {
            get => paused;
            set
            {
                if (value && !paused)
                {
                    if (postrollLeft >= 0)
                        FinishStop(); // the rest of the post-roll would be the prompt
                    Post(Discard);
                }
                paused = value;
            }
        }

        /// <summary>The recognizer's grammar (<see cref="VoiceSession.GrammarPhrases"/>), from the next utterance on.</summary>
        public void SetGrammar(IReadOnlyList<string> phrases)
        {
            var copy = new List<string>(phrases);
            Post(() => recognizer?.SetGrammar(copy));
        }

        /// <summary>Push-to-talk pressed: starts an utterance, with the pre-roll if there is one. For an open
        /// microphone, start once and never stop: the recognizer then ends utterances at pauses by itself.</summary>
        public void StartUtterance()
        {
            if (postrollLeft >= 0)
                FinishStop(); // pressed again during the post-roll: the last utterance ends first
            talking = true;
            Post(() =>
            {
                if (recognizer == null)
                    return;
                if (ring.Length == 0)
                    converter?.Reset(); // with a pre-roll the converter runs on one continuous stream
                recognizer.Start(recognizerRate);
                listening = true;
                heard = false;
                FeedPreroll();
            });
        }

        /// <summary>Push-to-talk released: ends the utterance after the post-roll; its result follows in
        /// <see cref="TryGetResult"/>.</summary>
        public void StopUtterance()
        {
            if (!talking)
                return;
            if (postrollMs == 0 || paused)
                FinishStop(); // while a prompt plays the audio is dropped anyway: no post-roll to wait for
            else if (postrollLeft < 0)
                postrollLeft = int.MaxValue; // counted at the next Write, in its rate and channels
        }

        /// <summary>Ends a post-roll now, for an app that stops calling <see cref="Write"/> (the microphone ended).</summary>
        public void FlushStop()
        {
            if (postrollLeft >= 0)
                FinishStop();
        }

        /// <summary>
        /// Microphone samples captured since the last call, as Unity's <c>AudioClip.GetData</c> gives them: floats
        /// from -1 to 1, <paramref name="channels"/> interleaved, at <paramref name="sampleRate"/>. The samples are
        /// copied, so the array can be reused. With a pre-roll, call it every frame, also while push-to-talk is up.
        /// </summary>
        public void Write(float[] samples, int count, int sampleRate, int channels = 1)
        {
            if (paused || !ready || count <= 0 || (!talking && ring.Length == 0))
                return;
            int take = count;
            bool stopAfter = false;
            if (postrollLeft >= 0)
            {
                int frame = Math.Max(1, channels);
                if (postrollLeft == int.MaxValue)
                    postrollLeft = (int)((long)sampleRate * postrollMs / 1000) * frame;
                take = Math.Min(count, postrollLeft - postrollLeft % frame);
                postrollLeft -= take;
                stopAfter = postrollLeft <= 0;
            }
            if (take > 0)
            {
                if (!spare.TryDequeue(out float[] copy) || copy.Length < take)
                    copy = new float[Math.Max(take, 4096)];
                Array.Copy(samples, copy, take);
                Post(() => Accept(copy, take, sampleRate, channels));
            }
            if (stopAfter)
                FinishStop();
        }

        /// <summary>The next final result, in order. Pass it to <see cref="VoiceSession.Hear"/>.</summary>
        public bool TryGetResult(out RecognitionResult result) => results.TryDequeue(out result);

        /// <summary>
        /// A push-to-talk utterance that ended without any result, with the recognizer's reason
        /// (<see cref="IReportsNoResult"/>; <see cref="NoResultReason.Silence"/> when it gives none). Pass it to
        /// <see cref="VoiceSession.NothingRecognized"/> after this frame's <see cref="TryGetResult"/>s. An open microphone
        /// (never stopped) gets none.
        /// </summary>
        public bool TryGetNoResult(out NoResultReason reason) => noResults.TryDequeue(out reason);

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

        void FinishStop()
        {
            talking = false;
            postrollLeft = -1;
            Post(() =>
            {
                if (!listening)
                    return;
                listening = false;
                reported = null;
                recognizer.Stop();
                if (!heard)
                    noResults.Enqueue(reported ?? NoResultReason.Silence);
            });
        }

        void Discard()
        {
            ringCount = 0; // the pre-roll may hold the start of the prompt
            if (listening)
            {
                converter?.Reset();
                recognizer.Start(recognizerRate); // restarting drops the audio heard so far
            }
        }

        /// <summary>Feeds the pre-roll, oldest first, to the utterance that just started.</summary>
        void FeedPreroll()
        {
            if (ringCount == 0)
                return;
            var audio = new short[ringCount];
            for (int i = 0; i < ringCount; i++)
                audio[i] = ring[(ringStart + i) % ring.Length];
            ringCount = 0;
            recognizer.AcceptAudio(audio, audio.Length);
        }

        void Accept(float[] samples, int count, int rate, int channels)
        {
            try
            {
                if (!listening && ring.Length == 0)
                    return;
                if (converter == null || converter.InputRate != rate || converter.Channels != channels)
                {
                    converter = new PcmConverter(rate, recognizerRate, channels);
                    ringCount = 0; // the pre-roll was at another rate
                }
                int max = converter.MaxOutput(count - count % channels);
                if (pcm.Length < max)
                    pcm = new short[max];
                int n = converter.Convert(samples, count - count % channels, pcm);
                if (listening)
                {
                    recognizer.AcceptAudio(pcm, n);
                    return;
                }
                for (int i = 0; i < n; i++) // the button is up: keep only the newest ring.Length samples
                {
                    if (ringCount < ring.Length)
                        ring[(ringStart + ringCount++) % ring.Length] = pcm[i];
                    else
                    {
                        ring[ringStart] = pcm[i];
                        ringStart = (ringStart + 1) % ring.Length;
                    }
                }
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
                recognizer.Recognized += result =>
                {
                    heard = true;
                    results.Enqueue(result);
                };
                if (recognizer is IReportsNoResult reporter)
                    reporter.NoResult += reason => reported = reason;
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

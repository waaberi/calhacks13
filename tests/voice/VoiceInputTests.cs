using System;
using System.Collections.Generic;
using System.Threading;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    public class VoiceInputTests
    {
        static readonly TimeSpan Timeout = TimeSpan.FromSeconds(5);

        /// <summary>Reports, at Stop, how many samples it got since Start and their first value.</summary>
        sealed class CountingRecognizer : ISpeechRecognizer
        {
            public readonly List<string> Calls = new List<string>();
            public int ThreadId = -1;
            public IReadOnlyList<string> Grammar;
            public bool Disposed;
            int samples;
            short first;

            public event Action<RecognitionResult> Recognized;

            public void SetGrammar(IReadOnlyList<string> phrases) => Grammar = phrases;

            public void Start(int sampleRate)
            {
                ThreadId = Environment.CurrentManagedThreadId;
                Calls.Add("start " + sampleRate);
                samples = 0;
            }

            public void AcceptAudio(short[] pcm, int count)
            {
                if (samples == 0 && count > 0)
                    first = pcm[0];
                samples += count;
            }

            public void Stop()
            {
                Calls.Add("stop");
                Recognized?.Invoke(new RecognitionResult(samples + " " + first, 1f));
            }

            public void Dispose() => Disposed = true;
        }

        static float[] Level(float value, int count)
        {
            var samples = new float[count];
            for (int i = 0; i < count; i++)
                samples[i] = value;
            return samples;
        }

        static string Result(VoiceInput input)
        {
            Assert.True(input.WaitIdle(Timeout));
            Assert.True(input.TryGetResult(out RecognitionResult result));
            return result.Text;
        }

        static VoiceInput Ready(CountingRecognizer recognizer)
        {
            var input = new VoiceInput(() => recognizer);
            Assert.True(input.WaitIdle(Timeout));
            Assert.True(input.Ready);
            return input;
        }

        [Fact]
        public void PushToTalkFeedsSixteenKilohertzPcmOnTheWorkerThread()
        {
            var recognizer = new CountingRecognizer();
            using (VoiceInput input = Ready(recognizer))
            {
                input.StartUtterance();
                for (int i = 0; i < 10; i++)
                    input.Write(Level(0.5f, 1600), 1600, 16000);
                input.StopUtterance();
                Assert.Equal("16000 16384", Result(input));
                Assert.NotEqual(Environment.CurrentManagedThreadId, recognizer.ThreadId);
                Assert.Equal(new[] { "start 16000", "stop" }, recognizer.Calls);
            }
            Assert.True(recognizer.Disposed);
        }

        [Fact]
        public void ResamplesTheDeviceRate()
        {
            using (VoiceInput input = Ready(new CountingRecognizer()))
            {
                input.StartUtterance();
                for (int i = 0; i < 50; i++)
                    input.Write(Level(0.25f, 960 * 2), 960 * 2, 48000, 2); // 20 ms stereo frames
                input.StopUtterance();
                string[] parts = Result(input).Split(' ');
                Assert.InRange(int.Parse(parts[0]), 16000 - 40, 16000); // one second, minus the filter's lookahead
            }
        }

        [Fact]
        public void AudioOutsideAnUtteranceIsDropped()
        {
            using (VoiceInput input = Ready(new CountingRecognizer()))
            {
                input.Write(Level(0.5f, 1600), 1600, 16000);
                input.StartUtterance();
                input.Write(Level(0.5f, 800), 800, 16000);
                input.StopUtterance();
                input.Write(Level(0.5f, 1600), 1600, 16000);
                Assert.Equal("800 16384", Result(input));
                Assert.False(input.TryGetResult(out _));
            }
        }

        [Fact]
        public void APromptThrowsAwayTheUtteranceItInterrupts()
        {
            var recognizer = new CountingRecognizer();
            using (VoiceInput input = Ready(recognizer))
            {
                input.StartUtterance();
                input.Write(Level(0.1f, 1600), 1600, 16000);  // before the prompt
                input.Paused = true;
                input.Write(Level(0.9f, 16000), 16000, 16000); // the prompt, heard through the microphone
                input.Paused = false;
                input.Write(Level(0.5f, 3200), 3200, 16000);   // the user, after the prompt
                input.StopUtterance();
                Assert.Equal("3200 16384", Result(input));
                Assert.Equal(new[] { "start 16000", "start 16000", "stop" }, recognizer.Calls);
            }
        }

        [Fact]
        public void GrammarReachesTheRecognizer()
        {
            var recognizer = new CountingRecognizer();
            using (VoiceInput input = Ready(recognizer))
            {
                var session = new VoiceSession();
                session.SetObjects(new[] { new SceneObject("a", "Shaft") });
                input.SetGrammar(session.GrammarPhrases());
                Assert.True(input.WaitIdle(Timeout));
                Assert.Contains("shaft", recognizer.Grammar);
            }
        }

        [Fact]
        public void AFailingRecognizerReportsAnErrorInsteadOfThrowing()
        {
            using (var input = new VoiceInput(() => throw new DllNotFoundException("libvosk")))
            {
                Assert.True(input.WaitIdle(Timeout));
                Assert.False(input.Ready);
                Assert.Equal("DllNotFoundException: libvosk", input.Error);
                input.StartUtterance();
                input.Write(new float[160], 160, 16000);
                input.StopUtterance();
                Assert.True(input.WaitIdle(Timeout));
                Assert.False(input.TryGetResult(out _));
            }
        }

        [Fact]
        public void LoadingDoesNotBlockTheCaller()
        {
            using (var gate = new ManualResetEventSlim())
            using (var input = new VoiceInput(() => { gate.Wait(Timeout); return new CountingRecognizer(); }))
            {
                Assert.False(input.Ready);
                input.Write(new float[160], 160, 16000); // dropped while loading
                gate.Set();
                Assert.True(input.WaitIdle(Timeout));
                Assert.True(input.Ready);
            }
        }
    }
}

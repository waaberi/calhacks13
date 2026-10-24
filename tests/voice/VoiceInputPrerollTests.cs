using System;
using System.Collections.Generic;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>VoiceInput's opt-in push-to-talk pre-roll and post-roll. VoiceInputTests covers the defaults (both 0).</summary>
    public class VoiceInputPrerollTests
    {
        static readonly TimeSpan Timeout = TimeSpan.FromSeconds(5);

        /// <summary>Reports, at Stop, how many samples it got since Start and their first value.</summary>
        sealed class CountingRecognizer : ISpeechRecognizer
        {
            public readonly List<string> Calls = new List<string>();
            public bool FailNextAudio;
            int samples;
            short first;

            public event Action<RecognitionResult> Recognized;

            public void SetGrammar(IReadOnlyList<string> phrases) { }

            public void Start(int sampleRate)
            {
                Calls.Add("start");
                samples = 0;
            }

            public void AcceptAudio(short[] pcm, int count)
            {
                if (FailNextAudio)
                {
                    FailNextAudio = false;
                    throw new InvalidOperationException("decoder failed");
                }
                if (samples == 0 && count > 0)
                    first = pcm[0];
                samples += count;
            }

            public void Stop()
            {
                Calls.Add("stop");
                Recognized?.Invoke(new RecognitionResult(samples + " " + first, 1f));
            }

            public void Dispose() { }
        }

        static float[] Level(float value, int count)
        {
            var samples = new float[count];
            for (int i = 0; i < count; i++)
                samples[i] = value;
            return samples;
        }

        static VoiceInput Ready(CountingRecognizer recognizer, int prerollMs, int postrollMs)
        {
            var input = new VoiceInput(() => recognizer, 16000, prerollMs, postrollMs);
            Assert.True(input.WaitIdle(Timeout));
            Assert.True(input.Ready);
            return input;
        }

        static string Result(VoiceInput input)
        {
            Assert.True(input.WaitIdle(Timeout));
            Assert.True(input.TryGetResult(out RecognitionResult result));
            return result.Text;
        }

        [Fact]
        public void TheLast300MillisecondsBeforeThePressAreHeard()
        {
            using (VoiceInput input = Ready(new CountingRecognizer(), 300, 0))
            {
                input.Write(Level(0.1f, 16000), 16000, 16000); // 1 s of room before the press
                input.Write(Level(0.25f, 1600), 1600, 16000);   // the 100 ms just before it
                input.StartUtterance();
                input.Write(Level(0.5f, 800), 800, 16000);
                input.StopUtterance();
                // 4800 samples of pre-roll (3200 of the room, then the 1600 just before the press), then the 800 spoken.
                Assert.Equal("5600 3277", Result(input));
            }
        }

        [Fact]
        public void PostRollKeepsListeningAfterTheRelease()
        {
            var recognizer = new CountingRecognizer();
            using (VoiceInput input = Ready(recognizer, 0, 150))
            {
                input.StartUtterance();
                input.Write(Level(0.5f, 800), 800, 16000);
                input.StopUtterance();
                Assert.True(input.WaitIdle(Timeout));
                Assert.False(input.TryGetResult(out _)); // still listening
                input.Write(Level(0.5f, 1600), 1600, 16000);
                input.Write(Level(0.5f, 1600), 1600, 16000); // 2400 samples are 150 ms: it stops here
                input.Write(Level(0.5f, 1600), 1600, 16000); // dropped
                Assert.Equal("3200 16384", Result(input));
                Assert.Equal(new[] { "start", "stop" }, recognizer.Calls);
            }
        }

        [Fact]
        public void APromptClearsThePreRoll()
        {
            using (VoiceInput input = Ready(new CountingRecognizer(), 300, 0))
            {
                input.Write(Level(0.9f, 4800), 4800, 16000);
                input.Paused = true;
                input.Write(Level(0.9f, 4800), 4800, 16000); // the prompt
                input.Paused = false;
                input.Write(Level(0.2f, 800), 800, 16000);
                input.StartUtterance();
                input.Write(Level(0.5f, 800), 800, 16000);
                input.StopUtterance();
                Assert.Equal("1600 6553", Result(input)); // only the 800 after the prompt, then the 800 spoken
            }
        }

        [Fact]
        public void APromptDuringThePostRollEndsTheUtteranceWithWhatItHas()
        {
            var recognizer = new CountingRecognizer();
            using (VoiceInput input = Ready(recognizer, 0, 150))
            {
                input.StartUtterance();
                input.Write(Level(0.5f, 800), 800, 16000);
                input.StopUtterance();
                input.Write(Level(0.5f, 800), 800, 16000);
                input.Paused = true;                          // "Done." for the last command starts playing
                input.Write(Level(0.9f, 1600), 1600, 16000);  // the prompt: never heard
                Assert.Equal("1600 16384", Result(input));
                Assert.Equal(new[] { "start", "stop" }, recognizer.Calls);
            }
        }

        [Fact]
        public void ReleasingDuringAPromptEndsTheUtteranceAtOnce()
        {
            var recognizer = new CountingRecognizer();
            using (VoiceInput input = Ready(recognizer, 0, 150))
            {
                input.StartUtterance();
                input.Paused = true;   // a prompt starts while the button is down
                input.StopUtterance(); // and the button goes up before it ends
                Assert.Equal("0 0", Result(input));
                input.Paused = false;
                input.Write(Level(0.5f, 4800), 4800, 16000); // speech after the prompt is a new utterance's, not this one's
                Assert.True(input.WaitIdle(Timeout));
                Assert.False(input.TryGetResult(out _));
                Assert.Equal(new[] { "start", "start", "stop" }, recognizer.Calls); // Discard restarts it
            }
        }

        [Fact]
        public void PressingAgainDuringThePostRollEndsTheFirstUtterance()
        {
            var recognizer = new CountingRecognizer();
            using (VoiceInput input = Ready(recognizer, 300, 150))
            {
                input.StartUtterance();
                input.Write(Level(0.5f, 800), 800, 16000);
                input.StopUtterance();
                input.StartUtterance();
                input.Write(Level(0.5f, 800), 800, 16000);
                input.StopUtterance();
                input.FlushStop();
                Assert.Equal("800 16384", Result(input));
                Assert.Equal("800 16384", Result(input));
                Assert.Equal(new[] { "start", "stop", "start", "stop" }, recognizer.Calls);
            }
        }

        [Fact]
        public void A48KilohertzStereoMicrophoneFillsThePreRollAt16Kilohertz()
        {
            using (VoiceInput input = Ready(new CountingRecognizer(), 300, 0))
            {
                for (int i = 0; i < 50; i++)
                    input.Write(Level(0.25f, 960 * 2), 960 * 2, 48000, 2); // 1 s of 20 ms stereo frames
                input.StartUtterance();
                input.StopUtterance();
                Assert.Equal(4800, int.Parse(Result(input).Split(' ')[0]));
            }
        }

        [Fact]
        public void WithoutPreRollAudioAfterAWorkerErrorIsStillDropped()
        {
            // The prototype indexed its empty pre-roll ring here and replaced the error with an IndexOutOfRangeException.
            var recognizer = new CountingRecognizer { FailNextAudio = true };
            using (VoiceInput input = Ready(recognizer, 0, 0))
            {
                input.StartUtterance();
                input.Write(Level(0.5f, 800), 800, 16000); // the decoder fails: the worker stops listening
                input.Write(Level(0.5f, 800), 800, 16000); // still talking, but nobody listens
                Assert.True(input.WaitIdle(Timeout));
                Assert.Equal("InvalidOperationException: decoder failed", input.Error);
                input.StopUtterance();
                Assert.True(input.WaitIdle(Timeout));
                Assert.False(input.TryGetResult(out _));
            }
        }

        [Fact]
        public void TheRecommendedValuesAreTheMeasuredOnes()
        {
            Assert.Equal(300, VoiceInput.RecommendedPrerollMs);
            Assert.Equal(150, VoiceInput.RecommendedPostrollMs);
        }
    }
}

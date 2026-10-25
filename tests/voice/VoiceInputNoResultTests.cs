using System;
using System.Collections.Generic;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>VoiceInput reports a push-to-talk utterance that ended without a result (VoiceInput.TryGetNoResult).</summary>
    public class VoiceInputNoResultTests
    {
        static readonly TimeSpan Timeout = TimeSpan.FromSeconds(5);

        /// <summary>Raises the next queued outcome at Stop: text for a result, or a NoResult reason.</summary>
        sealed class ScriptedRecognizer : ISpeechRecognizer, IReportsNoResult
        {
            public readonly Queue<object> Outcomes = new Queue<object>();
            public bool RaiseMidUtterance;

            public event Action<RecognitionResult> Recognized;
            public event Action<NoResultReason> NoResult;

            public void SetGrammar(IReadOnlyList<string> phrases) { }
            public void Start(int sampleRate) { }

            public void AcceptAudio(short[] samples, int count)
            {
                if (RaiseMidUtterance)
                {
                    RaiseMidUtterance = false;
                    Recognized?.Invoke(new RecognitionResult("undo", 1f)); // an open-mic style end of utterance
                }
            }

            public void Stop()
            {
                if (Outcomes.Count == 0)
                    return;
                object next = Outcomes.Dequeue();
                if (next is string text)
                    Recognized?.Invoke(new RecognitionResult(text, 1f));
                else
                    NoResult?.Invoke((NoResultReason)next);
            }

            public void Dispose() { }
        }

        /// <summary>A recognizer without IReportsNoResult that never hears anything.</summary>
        sealed class DeafRecognizer : ISpeechRecognizer
        {
            public event Action<RecognitionResult> Recognized { add { } remove { } }
            public void SetGrammar(IReadOnlyList<string> phrases) { }
            public void Start(int sampleRate) { }
            public void AcceptAudio(short[] samples, int count) { }
            public void Stop() { }
            public void Dispose() { }
        }

        static VoiceInput Ready(ISpeechRecognizer recognizer, int postrollMs = 0)
        {
            var input = new VoiceInput(() => recognizer, 16000, 0, postrollMs);
            Assert.True(input.WaitIdle(Timeout));
            Assert.True(input.Ready);
            return input;
        }

        static void Press(VoiceInput input)
        {
            input.StartUtterance();
            input.Write(new float[320], 320, 16000);
            input.StopUtterance();
            Assert.True(input.WaitIdle(Timeout));
        }

        [Fact]
        public void APressWithoutAResultIsSilenceByDefault()
        {
            using (VoiceInput input = Ready(new DeafRecognizer()))
            {
                Press(input);
                Assert.False(input.TryGetResult(out _));
                Assert.True(input.TryGetNoResult(out NoResultReason reason));
                Assert.Equal(NoResultReason.Silence, reason);
                Assert.False(input.TryGetNoResult(out _)); // once per press
            }
        }

        [Fact]
        public void TheRecognizersReasonIsPassedOn()
        {
            var recognizer = new ScriptedRecognizer();
            recognizer.Outcomes.Enqueue(NoResultReason.NotUnderstood);
            recognizer.Outcomes.Enqueue(NoResultReason.Silence);
            using (VoiceInput input = Ready(recognizer))
            {
                Press(input);
                Press(input);
                Assert.True(input.TryGetNoResult(out NoResultReason first));
                Assert.Equal(NoResultReason.NotUnderstood, first);
                Assert.True(input.TryGetNoResult(out NoResultReason second));
                Assert.Equal(NoResultReason.Silence, second);
            }
        }

        [Fact]
        public void APressWithAResultHasNoNoResult()
        {
            var recognizer = new ScriptedRecognizer();
            recognizer.Outcomes.Enqueue("add a cube");
            using (VoiceInput input = Ready(recognizer))
            {
                Press(input);
                Assert.True(input.TryGetResult(out RecognitionResult result));
                Assert.Equal("add a cube", result.Text);
                Assert.False(input.TryGetNoResult(out _));
            }
        }

        [Fact]
        public void AResultBeforeTheReleaseCountsForThePress()
        {
            var recognizer = new ScriptedRecognizer { RaiseMidUtterance = true };
            using (VoiceInput input = Ready(recognizer))
            {
                Press(input);
                Assert.True(input.TryGetResult(out _));
                Assert.False(input.TryGetNoResult(out _));
            }
        }

        [Fact]
        public void WithAPostrollTheNoResultFollowsTheEndOfThePostroll()
        {
            using (VoiceInput input = Ready(new DeafRecognizer(), 150))
            {
                input.StartUtterance();
                input.Write(new float[320], 320, 16000);
                input.StopUtterance();
                Assert.True(input.WaitIdle(Timeout));
                Assert.False(input.TryGetNoResult(out _)); // still in the post-roll
                input.Write(new float[4000], 4000, 16000);
                Assert.True(input.WaitIdle(Timeout));
                Assert.True(input.TryGetNoResult(out NoResultReason reason));
                Assert.Equal(NoResultReason.Silence, reason);
            }
        }

        [Fact]
        public void ARecognizerThatNeverStartedReportsNothing()
        {
            using (VoiceInput input = Ready(new DeafRecognizer()))
            {
                input.StopUtterance(); // a release without a press
                Assert.True(input.WaitIdle(Timeout));
                Assert.False(input.TryGetNoResult(out _));
            }
        }
    }
}

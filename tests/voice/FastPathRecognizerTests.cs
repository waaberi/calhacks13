using System;
using System.Collections.Generic;
using System.Linq;
using SpatialModeling.VoiceCore.Whisper;
using Xunit;

namespace SpatialModeling.VoiceCore.Tests
{
    /// <summary>Vosk first, Whisper when Vosk isn't sure, Vosk again when Whisper fails (fake recognizers).</summary>
    public class FastPathRecognizerTests
    {
        sealed class Fake : IFallibleRecognizer, IReportsNoResult
        {
            public readonly List<RecognitionResult> OnStop = new List<RecognitionResult>();
            public int Starts, Stops, Samples;
            public bool Fail, Disposed;
            public IReadOnlyList<string> Grammar;

            /// <summary>Raised at Stop when <see cref="OnStop"/> is empty; null raises nothing.</summary>
            public NoResultReason? Reason;

            public event Action<RecognitionResult> Recognized;
            public event Action<NoResultReason> NoResult;
            public bool LastStopFailed { get; private set; }
            public string LastError => LastStopFailed ? "IOException: down" : null;

            public void SetGrammar(IReadOnlyList<string> phrases) => Grammar = phrases;
            public void Start(int sampleRate) => Starts++;
            public void AcceptAudio(short[] samples, int count) => Samples += count;

            public void Stop()
            {
                Stops++;
                LastStopFailed = Fail;
                if (!Fail)
                    foreach (RecognitionResult r in OnStop)
                        Recognized?.Invoke(r);
                if (!Fail && OnStop.Count == 0 && Reason.HasValue)
                    NoResult?.Invoke(Reason.Value);
            }

            public void Dispose() => Disposed = true;
        }

        static readonly string[] Grammar = { "add a cube", "undo", "two", "rotate", "this", "[unk]" };

        static (FastPathRecognizer hybrid, Fake vosk, Fake whisper, List<RecognitionResult> heard) Make()
        {
            var vosk = new Fake();
            var whisper = new Fake();
            var hybrid = new FastPathRecognizer(vosk, whisper);
            var heard = new List<RecognitionResult>();
            hybrid.Recognized += heard.Add;
            hybrid.SetGrammar(Grammar);
            return (hybrid, vosk, whisper, heard);
        }

        static void Utter(FastPathRecognizer hybrid)
        {
            hybrid.Start(16000);
            hybrid.AcceptAudio(new short[320], 320);
            hybrid.Stop();
        }

        [Fact]
        public void OneWholePhraseAtHighConfidenceSkipsWhisper()
        {
            var (hybrid, vosk, whisper, heard) = Make();
            vosk.OnStop.Add(new RecognitionResult("add a cube", 0.95f));
            whisper.OnStop.Add(new RecognitionResult("undo", 1f));
            Utter(hybrid);
            Assert.Equal(new[] { "add a cube" }, heard.Select(r => r.Text));
            Assert.Equal(0, whisper.Stops);
            Assert.Equal(FastPathOutcome.Fast, hybrid.LastOutcome);
        }

        [Theory]
        [InlineData("rotate this", 1f)] // several grammar entries, not one phrase
        [InlineData("two", 0.5f)]       // one phrase, but Vosk isn't sure ("to" or "two")
        [InlineData("[unk]", 1f)]       // out of grammar
        public void OtherwiseWhisperAnswers(string voskText, float voskConfidence)
        {
            var (hybrid, vosk, whisper, heard) = Make();
            vosk.OnStop.Add(new RecognitionResult(voskText, voskConfidence));
            whisper.OnStop.Add(new RecognitionResult("rotate this", 1f));
            Utter(hybrid);
            Assert.Equal(new[] { "rotate this" }, heard.Select(r => r.Text));
            Assert.Equal(FastPathOutcome.Slow, hybrid.LastOutcome);
        }

        [Fact]
        public void SeveralVoskResultsGoToWhisper()
        {
            var (hybrid, vosk, whisper, heard) = Make();
            vosk.OnStop.Add(new RecognitionResult("undo", 1f));
            vosk.OnStop.Add(new RecognitionResult("undo", 1f));
            whisper.OnStop.Add(new RecognitionResult("undo", 0.9f));
            Utter(hybrid);
            Assert.Single(heard);
            Assert.Equal(1, whisper.Stops);
        }

        [Fact]
        public void WhisperHearingNothingRejectsTheUtterance()
        {
            var (hybrid, vosk, _, heard) = Make();
            vosk.OnStop.Add(new RecognitionResult("this", 0.6f)); // chatter Vosk forced onto grammar words
            Utter(hybrid);
            Assert.Empty(heard);
            Assert.Equal(FastPathOutcome.Slow, hybrid.LastOutcome);
        }

        [Fact]
        public void WhisperHearingNoCommandIsPassedOnAsItsReason()
        {
            var (hybrid, vosk, whisper, heard) = Make();
            var reasons = new List<NoResultReason>();
            hybrid.NoResult += reasons.Add;
            whisper.Reason = NoResultReason.NotUnderstood;

            vosk.OnStop.Add(new RecognitionResult("this", 0.6f)); // chatter: Whisper snapped it onto nothing
            Utter(hybrid);
            Assert.Empty(heard);
            Assert.Equal(new[] { NoResultReason.NotUnderstood }, reasons);

            vosk.OnStop.Clear();
            vosk.OnStop.Add(new RecognitionResult("add a cube", 0.95f)); // the fast path: Whisper isn't asked
            Utter(hybrid);
            Assert.Equal(new[] { "add a cube" }, heard.Select(r => r.Text));
            Assert.Single(reasons);

            vosk.OnStop.Clear();
            vosk.OnStop.Add(new RecognitionResult("this", 0.6f));
            whisper.Fail = true; // Whisper failed and Vosk's result goes out: no reason
            Utter(hybrid);
            Assert.Equal(new[] { "add a cube", "this" }, heard.Select(r => r.Text));
            Assert.Equal(FastPathOutcome.SlowFailed, hybrid.LastOutcome);
            Assert.Single(reasons);
        }

        [Fact]
        public void WhenWhisperFailsVoskResultsGoOutAsBefore()
        {
            var (hybrid, vosk, whisper, heard) = Make();
            vosk.OnStop.Add(new RecognitionResult("rotate this", 0.7f));
            vosk.OnStop.Add(new RecognitionResult("undo", 0.6f));
            whisper.Fail = true;
            Utter(hybrid);
            Assert.Equal(new[] { "rotate this", "undo" }, heard.Select(r => r.Text));
            Assert.Equal(FastPathOutcome.SlowFailed, hybrid.LastOutcome);
        }

        [Fact]
        public void BothGetTheGrammarAndTheAudioAndAreDisposed()
        {
            var (hybrid, vosk, whisper, _) = Make();
            Utter(hybrid);
            Assert.Same(Grammar, vosk.Grammar);
            Assert.Same(Grammar, whisper.Grammar);
            Assert.Equal(320, vosk.Samples);
            Assert.Equal(320, whisper.Samples);
            hybrid.Dispose();
            Assert.True(vosk.Disposed && whisper.Disposed);
        }

        [Fact]
        public void ResultsDontLeakIntoTheNextUtterance()
        {
            var (hybrid, vosk, whisper, heard) = Make();
            vosk.OnStop.Add(new RecognitionResult("add a cube", 1f));
            Utter(hybrid);
            vosk.OnStop.Clear();
            Utter(hybrid);
            Assert.Single(heard);
            Assert.Equal(1, whisper.Stops); // the second, empty utterance went to Whisper, which heard nothing
        }
    }
}

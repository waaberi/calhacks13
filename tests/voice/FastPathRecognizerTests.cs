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

        static readonly VoiceCandidate[] TwoCandidates =
        {
            new VoiceCandidate(1, "Array", "object.modifier_add", needsTarget: true),
            new VoiceCandidate(2, "duplicate", "object.duplicate", needsTarget: true),
        };

        [Fact]
        public void WhileAskingVoskHearsTheAnswersAndWhisperTheAnswersAndTheFullGrammar()
        {
            var (hybrid, vosk, whisper, _) = Make();
            List<string> answers = ChoiceWords.Grammar(TwoCandidates); // VoiceSession.GrammarPhrases() while asking
            Assert.True(ChoiceWords.IsGrammar(answers));

            hybrid.SetGrammar(answers);
            Assert.Same(answers, vosk.Grammar);
            Assert.Equal(answers.Take(answers.Count - 1), whisper.Grammar.Take(answers.Count - 1)); // the answers first
            Assert.Equal(Grammar.Where(p => p != "[unk]" && !answers.Contains(p)), // then the full grammar's other phrases
                whisper.Grammar.Skip(answers.Count - 1).Take(whisper.Grammar.Count - answers.Count));
            Assert.Equal("[unk]", whisper.Grammar.Last());
            Assert.Single(whisper.Grammar, "[unk]");
            Assert.Contains("add a cube", whisper.Grammar);
            Assert.Same(whisper.Grammar, hybrid.SlowGrammar);

            hybrid.SetGrammar(Grammar); // the question ended: one grammar again
            Assert.Same(Grammar, vosk.Grammar);
            Assert.Same(Grammar, whisper.Grammar);
        }

        [Fact]
        public void WhileAskingVoskIsSureOnlyOfAnAnswer()
        {
            var (hybrid, vosk, whisper, heard) = Make();
            hybrid.SetGrammar(ChoiceWords.Grammar(TwoCandidates));
            vosk.OnStop.Add(new RecognitionResult("add a cube", 1f)); // in Whisper's grammar, not in Vosk's
            whisper.OnStop.Add(new RecognitionResult("add a cube", 1f));
            Utter(hybrid);
            Assert.Equal(FastPathOutcome.Slow, hybrid.LastOutcome);

            vosk.OnStop.Clear();
            vosk.OnStop.Add(new RecognitionResult("the second one", 0.95f));
            Utter(hybrid);
            Assert.Equal(FastPathOutcome.Fast, hybrid.LastOutcome);
            Assert.Equal(new[] { "add a cube", "the second one" }, heard.Select(r => r.Text));
        }

        [Fact]
        public void AQuestionBeforeAnyFullGrammarGivesWhisperTheAnswersAlone()
        {
            var vosk = new Fake();
            var whisper = new Fake();
            var hybrid = new FastPathRecognizer(vosk, whisper);
            List<string> answers = ChoiceWords.Grammar(TwoCandidates);
            hybrid.SetGrammar(answers);
            Assert.Same(answers, vosk.Grammar);
            Assert.Same(answers, whisper.Grammar);
        }

        [Theory]
        [InlineData(new[] { "one", "two", "cancel", "never mind", "[unk]" }, true)]
        [InlineData(new[] { "one", "first", "option one", "number one", "the first one", "cancel", "never mind", "[unk]" }, true)]
        [InlineData(new[] { "add a cube", "one", "two", "cancel", "[unk]" }, false)] // a full grammar has commands
        [InlineData(new[] { "one", "two", "[unk]" }, false)]                         // a question's always has cancel
        [InlineData(new string[0], false)]
        public void AQuestionsGrammarIsOnlyAnswersAndCancel(string[] phrases, bool isQuestion) =>
            Assert.Equal(isQuestion, ChoiceWords.IsGrammar(phrases));

        [Fact]
        public void TheSessionsGrammarsAreToldApart()
        {
            var session = new VoiceSession(new VoiceSessionOptions { AskHost = true }, () => DateTime.UtcNow);
            session.SetObjects(new[] { new SceneObject("id-cube", "Cube") });
            session.SetHostGrammar(new[] { "make it thicker", "shade smooth" });
            Assert.False(ChoiceWords.IsGrammar(session.GrammarPhrases()));
            Assert.False(ChoiceWords.IsGrammar(new VoiceSession().GrammarPhrases())); // VoiceCore's words alone
            Assert.False(ChoiceWords.IsGrammar(null));
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

        // ---------- a weak "add" at the start, a phrase and a count ----------

        static readonly string[] AddGrammar =
        {
            "add a monkey", "add a mirror modifier", "add a donut", "add an array", "add a camera", "five copies", "delete it",
            "undo", "it", "a", "[unk]",
        };

        /// <summary>"word:confidence:start:end" for each word, as Vosk gives them.</summary>
        static RecognitionResult Vosk(params string[] words)
        {
            var parsed = words.Select(w => w.Split(':')).Select(p => new RecognizedWord(p[0], float.Parse(p[1],
                System.Globalization.CultureInfo.InvariantCulture), float.Parse(p[2], System.Globalization.CultureInfo.InvariantCulture),
                float.Parse(p[3], System.Globalization.CultureInfo.InvariantCulture))).ToList();
            return new RecognitionResult(string.Join(" ", parsed.Select(w => w.Word)), parsed.Min(w => w.Confidence), parsed);
        }

        /// <summary>Silence, then a tone (speech) from <paramref name="from"/> to <paramref name="to"/> seconds, then silence.</summary>
        static void Speak(FastPathRecognizer hybrid, double from, double to, double length = 1.2)
        {
            var audio = new short[(int)(16000 * length)];
            for (int i = (int)(16000 * from); i < (int)(16000 * to); i++)
                audio[i] = (short)(3000 * Math.Sin(2 * Math.PI * 200 * i / 16000.0));
            hybrid.Start(16000);
            for (int at = 0; at < audio.Length; at += 320) // 20 ms at a time, like VoiceInput
                hybrid.AcceptAudio(audio.Skip(at).Take(320).ToArray(), Math.Min(320, audio.Length - at));
            hybrid.Stop();
        }

        [Theory]
        [InlineData("add a monkey", "add a monkey", "add:0.83:0.30:0.45", "a:1:0.45:0.50", "monkey:1:0.50:0.90")]
        [InlineData("add a mirror modifier", "it a mirror modifier", "it:0.76:0.30:0.40", "a:1:0.40:0.45", "mirror:1:0.45:0.70", "modifier:1:0.70:0.90")]
        [InlineData("add a donut", "a donut", "a:0.72:0.30:0.36", "donut:1:0.36:0.90")] // the start of "add" was lost
        [InlineData("add an array", "an array", "an:0.57:0.32:0.38", "array:0.95:0.38:0.88")]
        [InlineData("add an array five copies", "it an array five copies", "it:0.5:0.30:0.40", "an:1:0.40:0.45",
            "array:1:0.45:0.65", "five:1:0.65:0.75", "copies:1:0.75:0.90")]
        public void AWeakAddAtTheStartStillTakesTheFastPath(string expected, string voskText, params string[] words)
        {
            var vosk = new Fake();
            var whisper = new Fake();
            var hybrid = new FastPathRecognizer(vosk, whisper);
            var heard = new List<RecognitionResult>();
            hybrid.Recognized += heard.Add;
            hybrid.SetGrammar(AddGrammar);
            vosk.OnStop.Add(Vosk(words));
            Assert.Equal(voskText, vosk.OnStop[0].Text);
            Speak(hybrid, 0.30, 0.90);
            Assert.Equal(FastPathOutcome.Fast, hybrid.LastOutcome);
            Assert.Equal(0, whisper.Stops);
            RecognitionResult result = Assert.Single(heard);
            Assert.Equal(expected, result.Text);
            Assert.InRange(result.Confidence, 0.9f, 1f); // the sure words' confidence: it runs
            Assert.Equal(voskText, hybrid.LastRestoredFrom);
        }

        [Theory]
        [InlineData("add:1:0.30:0.45", "a:1:0.45:0.50", "monkey:0.6:0.50:0.90")]  // the weak word isn't the first
        [InlineData("delete:0.8:0.30:0.60", "it:1:0.60:0.90")]                    // a weak verb that isn't "add"
        [InlineData("it:0.7:0.30:0.50", "undo:1:0.50:0.90")]                      // "add undo" is no phrase
        [InlineData("a:0.7:0.30:0.40", "[unk]:1:0.40:0.90")]                      // nothing sure after it
        [InlineData("a:0.8:0.30:0.40", "it:0.85:0.40:0.90")]                      // two weak words
        public void OnlyAWeakAddIsRestored(params string[] words)
        {
            var vosk = new Fake();
            var whisper = new Fake();
            var hybrid = new FastPathRecognizer(vosk, whisper);
            hybrid.SetGrammar(AddGrammar);
            vosk.OnStop.Add(Vosk(words));
            Speak(hybrid, 0.30, 0.90);
            Assert.Equal(FastPathOutcome.Slow, hybrid.LastOutcome);
            Assert.Equal(1, whisper.Stops);
            Assert.Null(hybrid.LastRestoredFrom);
        }

        [Fact]
        public void ChatterEndingInAnAddPhraseGoesToWhisper()
        {
            // SLURP "will it be raining tomorrow", which Vosk heard as "a camera" at the end of 1.6 s of speech.
            var vosk = new Fake();
            var whisper = new Fake();
            var hybrid = new FastPathRecognizer(vosk, whisper);
            hybrid.SetGrammar(AddGrammar);
            vosk.OnStop.Add(Vosk("a:0.78:0.99:1.17", "camera:1:1.20:1.68"));
            Speak(hybrid, 0.30, 1.86, length: 2.1);
            Assert.Equal(FastPathOutcome.Slow, hybrid.LastOutcome);

            vosk.OnStop.Clear(); // the same words, when they are all that was said
            vosk.OnStop.Add(Vosk("a:0.78:0.30:0.40", "camera:1:0.40:0.90"));
            Speak(hybrid, 0.30, 0.90);
            Assert.Equal(FastPathOutcome.Fast, hybrid.LastOutcome);
        }

        [Fact]
        public void WithoutWordTimesOrSpeechNothingIsRestored()
        {
            var speech = ((float)0.3, (float)0.9);
            var phrases = new HashSet<string>(AddGrammar);
            Assert.Null(FastPathRecognizer.RestoreLeadingAdd(new RecognitionResult("a donut", 0.72f), phrases, 0.9f, speech));
            Assert.Null(FastPathRecognizer.RestoreLeadingAdd(Vosk("a:0.72:0.30:0.36", "donut:1:0.36:0.90"), phrases, 0.9f, null));
            Assert.NotNull(FastPathRecognizer.RestoreLeadingAdd(Vosk("a:0.72:0.30:0.36", "donut:1:0.36:0.90"), phrases, 0.9f, speech));
            Assert.Null(FastPathRecognizer.RestoreLeadingAdd(Vosk("a:0.72:-1:-1", "donut:1:-1:-1"), phrases, 0.9f, speech));
        }

        [Theory]
        [InlineData("add an array five copies", true)] // "add an array" + "five copies": Vosk chains phrases
        [InlineData("add an array", true)]
        [InlineData("five copies", true)]
        [InlineData("add an array undo", false)]       // only a count may follow
        [InlineData("undo five copies", false)]        // a one-word phrase and a count: too easy for chatter
        [InlineData("five copies five copies", false)]
        [InlineData("", false)]
        public void APhraseAndACountMayTakeTheFastPath(string text, bool fast) =>
            Assert.Equal(fast, FastPathRecognizer.IsFastText(text, new HashSet<string>(AddGrammar)));
    }
}

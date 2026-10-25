using System;
using System.Collections.Generic;

namespace SpatialModeling.VoiceCore.Whisper
{
    /// <summary>
    /// Vosk first, Whisper when Vosk isn't sure. Both get the audio. On release, if the fast recognizer's result is
    /// exactly one grammar phrase (no "[unk]"), or a phrase and a count (<see cref="IsFastText"/>), with confidence of
    /// at least <c>minFastConfidence</c>, it is used at Vosk's speed (about 10 ms). Otherwise the slow recognizer decodes the utterance and its result is used, even
    /// when it hears nothing: that is what rejects chatter. Only if the slow one fails (server down, timeout) do the
    /// fast results go out as they are, which is VoiceCore's behaviour without Whisper.
    /// Measured on the TTS corpus with Vosk G2 and whisper tiny.en (voice-asr-alternatives study): 196/250 commands
    /// top-1 vs 151 for Vosk alone, 0/20 and 0/48 chatter accepted, and 65% of utterances on the fast path.
    /// Needs push-to-talk: results come out at <see cref="Stop"/>, so with an open microphone (Start once, never
    /// Stop) use Vosk alone. While VoiceSession asks "which one?", Vosk listens for the answers only and Whisper for
    /// the answers and every command (see <see cref="SetGrammar"/>).
    /// An utterance without a result raises <see cref="NoResult"/> (<see cref="IReportsNoResult"/>):
    /// <see cref="NoResultReason.Silence"/> for no speech (Whisper's speech gate dropped a silent press, or Whisper
    /// wrote a silence hallucination such as "you" that Vosk didn't back up: <see cref="FastPathOutcome.Silence"/>),
    /// and the slow recognizer's reason otherwise: <see cref="NoResultReason.NotUnderstood"/> when Whisper's
    /// transcript snapped onto no phrase. Nothing when Whisper failed and Vosk heard nothing either.
    /// <para><b>A weak "add".</b> Vosk's small model often hears the start of "add" weakly: "add a monkey" with "add"
    /// at 0.83, "it a mirror modifier", or "a donut" when the start was cut off. The result's confidence is its
    /// weakest word, so these went to Whisper (0.6-1.2 s instead of 0.2 s). <see cref="RestoreLeadingAdd"/> takes them
    /// on the fast path as the "add" phrase when every other word is sure and Vosk's words cover the speech, so
    /// nothing else was said (chatter ending in "a camera" doesn't).</para>
    /// </summary>
    public sealed class FastPathRecognizer : ISpeechRecognizer, IReportsNoResult
    {
        /// <summary>The measured fast-path gate.</summary>
        public const float DefaultMinFastConfidence = 0.9f;

        /// <summary>
        /// For <see cref="RestoreLeadingAdd"/>: the share of the speech (first to last loud frame) that Vosk's words
        /// must span. Measured with Vosk and the host grammar: the "add" phrases it restores span 0.77-1.18 of it
        /// (cut-off starts, far microphone, phone band and clean TTS), and the one chatter clip it would take otherwise
        /// (SLURP "will it be raining tomorrow" heard as "a camera") 0.44.
        /// </summary>
        public const float MinWordCoverage = 0.7f;

        /// <summary>What Vosk writes for a weak "add": replaced by "add" ("it a mirror modifier").</summary>
        static readonly HashSet<string> AddHeardAs = new HashSet<string>(StringComparer.Ordinal) { "it", "a", "an", "at", "and" };

        /// <summary>What Vosk keeps of "add a" when the start of "add" is lost: "add" goes in front ("a donut").</summary>
        static readonly HashSet<string> AddLostBefore = new HashSet<string>(StringComparer.Ordinal) { "a", "an" };

        const int FrameMs = 30;

        readonly ISpeechRecognizer fast;
        readonly ISpeechRecognizer slow;
        readonly float minFastConfidence;
        readonly List<RecognitionResult> fastResults = new List<RecognitionResult>();
        readonly List<RecognitionResult> slowResults = new List<RecognitionResult>();
        readonly List<float> frameRms = new List<float>(); // this utterance's 30 ms frames, for the word coverage
        HashSet<string> phrases = new HashSet<string>(StringComparer.Ordinal);
        NoResultReason? slowReason; // the slow recognizer's NoResult during this Stop
        IReadOnlyList<string> fullGrammar; // the last grammar that wasn't a question's
        int rate = 16000;
        double frameEnergy;
        int frameFill;

        public FastPathRecognizer(ISpeechRecognizer fast, ISpeechRecognizer slow, float minFastConfidence = DefaultMinFastConfidence)
        {
            this.fast = fast ?? throw new ArgumentNullException(nameof(fast));
            this.slow = slow ?? throw new ArgumentNullException(nameof(slow));
            this.minFastConfidence = minFastConfidence;
            fast.Recognized += fastResults.Add;
            slow.Recognized += slowResults.Add;
            if (slow is IReportsNoResult reporter)
                reporter.NoResult += reason => slowReason = reason; // passed on, or overruled, in Stop
            if (slow is WhisperServerRecognizer whisper)
                whisper.DropSilenceHallucinations = false; // dropped in Stop, unless Vosk heard speech too
        }

        public event Action<RecognitionResult> Recognized;

        /// <summary>Raised from <see cref="Stop"/> when it raises no result; see the class summary.</summary>
        public event Action<NoResultReason> NoResult;

        /// <summary>Vosk, for logs and measurements.</summary>
        public ISpeechRecognizer Fast => fast;

        /// <summary>Whisper, for logs and measurements.</summary>
        public ISpeechRecognizer Slow => slow;

        /// <summary>Which recognizer answered the last utterance.</summary>
        public FastPathOutcome LastOutcome { get; private set; }

        /// <summary>The grammar the slow recognizer snaps onto (see <see cref="SetGrammar"/>), for logs and tests.</summary>
        public IReadOnlyList<string> SlowGrammar { get; private set; }

        /// <summary>
        /// Two grammars while <see cref="VoiceSession"/> asks "which one?". The adapter passes
        /// <see cref="VoiceSession.GrammarPhrases"/> as always; while a question is open that is only the answers, cancel
        /// and "[unk]". Vosk keeps exactly that (on TTS 20/20 answers at 0.9, against 14/20 with the full grammar
        /// merged in). Whisper gets the answers followed by the last full grammar seen here, so a new command said
        /// during the question ("make it thicker") snaps onto that command and reaches <see cref="VoiceSession.Hear"/>,
        /// which dismisses the question and handles it, instead of becoming a press without a result. An answer is
        /// still exact for Whisper ("two", "the second one"), and Vosk's sure answer still skips Whisper. The full
        /// grammar is the last grammar that wasn't a question's (<see cref="ChoiceWords.IsGrammar"/>): a full grammar
        /// that changed during the question arrives when it ends. Before any full grammar Whisper gets the answers alone.
        /// </summary>
        public void SetGrammar(IReadOnlyList<string> grammar)
        {
            IReadOnlyList<string> forSlow = grammar;
            if (!ChoiceWords.IsGrammar(grammar))
                fullGrammar = grammar;
            else if (fullGrammar != null)
                forSlow = AnswersThenFull(grammar, fullGrammar);
            fast.SetGrammar(grammar);
            slow.SetGrammar(forSlow);
            SlowGrammar = forSlow;
            phrases = new HashSet<string>(grammar ?? Array.Empty<string>(), StringComparer.Ordinal);
            phrases.Remove(Vocabulary.Unknown);
        }

        /// <summary>The answers first (so their words lead Whisper's prompt), then the full grammar's other phrases,
        /// then "[unk]" once.</summary>
        static List<string> AnswersThenFull(IReadOnlyList<string> answers, IReadOnlyList<string> full)
        {
            var seen = new HashSet<string>(StringComparer.Ordinal) { Vocabulary.Unknown };
            var both = new List<string>(answers.Count + full.Count);
            foreach (string phrase in answers)
                if (seen.Add(phrase))
                    both.Add(phrase);
            foreach (string phrase in full)
                if (seen.Add(phrase))
                    both.Add(phrase);
            both.Add(Vocabulary.Unknown);
            return both;
        }

        /// <summary>What Vosk wrote when the last utterance went out as a restored "add" phrase
        /// (<see cref="RestoreLeadingAdd"/>), for logs; otherwise null.</summary>
        public string LastRestoredFrom { get; private set; }

        public void Start(int sampleRate)
        {
            fastResults.Clear();
            slowResults.Clear();
            frameRms.Clear();
            frameEnergy = 0;
            frameFill = 0;
            rate = sampleRate;
            fast.Start(sampleRate);
            slow.Start(sampleRate);
        }

        public void AcceptAudio(short[] samples, int count)
        {
            fast.AcceptAudio(samples, count);
            slow.AcceptAudio(samples, count);
            int frame = Math.Max(1, rate * FrameMs / 1000);
            for (int i = 0; i < count; i++)
            {
                frameEnergy += (double)samples[i] * samples[i];
                if (++frameFill == frame)
                {
                    frameRms.Add((float)Math.Sqrt(frameEnergy / frame));
                    frameEnergy = 0;
                    frameFill = 0;
                }
            }
        }

        public void Stop()
        {
            LastRestoredFrom = null;
            fast.Stop();
            if (fastResults.Count == 1 && IsFastText(fastResults[0].Text, phrases) && fastResults[0].Confidence >= minFastConfidence)
            {
                LastOutcome = FastPathOutcome.Fast;
                slow.Start(rate); // drops the slow recognizer's buffered audio unheard
                Raise(fastResults);
                return;
            }
            RecognitionResult? restored = fastResults.Count == 1
                ? RestoreLeadingAdd(fastResults[0], phrases, minFastConfidence, SpeechSpan())
                : null;
            if (restored.HasValue)
            {
                LastOutcome = FastPathOutcome.Fast;
                LastRestoredFrom = fastResults[0].Text;
                slow.Start(rate);
                fastResults[0] = restored.Value;
                Raise(fastResults);
                return;
            }

            slowReason = null;
            slow.Stop();
            if (slow is IFallibleRecognizer fallible && fallible.LastStopFailed)
            {
                LastOutcome = FastPathOutcome.SlowFailed;
                Raise(fastResults); // none: nothing to report, it may have been noise
                return;
            }
            if (slow is WhisperServerRecognizer whisper &&
                (whisper.LastWasSilence || (whisper.LastWasHallucination && fastResults.Count == 0)))
            {
                LastOutcome = FastPathOutcome.Silence; // an accidental press: say nothing
                slowResults.Clear();
                Raise(slowResults, NoResultReason.Silence);
                return;
            }
            LastOutcome = FastPathOutcome.Slow;
            Raise(slowResults, slowReason);
        }

        public void Dispose()
        {
            fast.Dispose();
            slow.Dispose();
        }

        /// <summary>
        /// A Vosk result whose only unsure word is a weak "add" at the start, as the "add" phrase it stands for, or null.
        /// Every other word must be at least <paramref name="minConfidence"/>, there is no "[unk]", and the first word is
        /// below it and is one of:
        /// <list type="bullet">
        /// <item>"add" itself, when the whole text is a grammar phrase ("add a monkey", add 0.83);</item>
        /// <item>"it", "a", "an", "at" or "and" standing for "add" ("it a mirror modifier" gives "add a mirror modifier");</item>
        /// <item>"a" or "an" after a lost "add" ("a donut" gives "add a donut").</item>
        /// </list>
        /// The result must be one grammar phrase of <paramref name="phrases"/>, and Vosk's words must span at least
        /// <see cref="MinWordCoverage"/> of <paramref name="speech"/> (first to last loud moment, in seconds from the
        /// utterance start), so nothing else was said. Without word times or speech it is null. The confidence is the
        /// lowest of the sure words.
        /// </summary>
        public static RecognitionResult? RestoreLeadingAdd(RecognitionResult vosk, ISet<string> phrases, float minConfidence,
            (float start, float end)? speech)
        {
            IReadOnlyList<RecognizedWord> words = vosk.Words;
            if (words == null || words.Count < 2 || !speech.HasValue || words[0].Confidence >= minConfidence)
                return null;
            var rest = new List<string>(words.Count - 1);
            float sure = 1f;
            for (int i = 1; i < words.Count; i++)
            {
                if (words[i].Confidence < minConfidence || words[i].Word == Vocabulary.Unknown)
                    return null;
                sure = Math.Min(sure, words[i].Confidence);
                rest.Add(words[i].Word);
            }
            string first = words[0].Word, others = string.Join(" ", rest), text = first + " " + others;
            string phrase =
                first == "add" && IsFastText(text, phrases) ? text :
                AddHeardAs.Contains(first) && IsFastText("add " + others, phrases) ? "add " + others :
                AddLostBefore.Contains(first) && IsFastText("add " + text, phrases) ? "add " + text :
                null;
            if (phrase == null)
                return null;
            (float start, float end) = speech.Value;
            float spoken = end - start, said = words[words.Count - 1].End - words[0].Start;
            if (words[0].Start < 0 || spoken <= 0 || said < MinWordCoverage * spoken)
                return null;
            return new RecognitionResult(phrase, sure);
        }

        /// <summary>
        /// What the fast path may answer with: one grammar phrase, or a phrase of two or more words followed by a count
        /// phrase of the grammar ("add an array" + "five copies", "subdivide it" + "level two"): Vosk chains phrases,
        /// and "add an array five copies" is two of them. Measured on 1,552 clips (TTS, degraded TTS, 320 SLURP and 48
        /// TTS chatter): 6 more commands on the fast path, all right, and no chatter.
        /// </summary>
        public static bool IsFastText(string text, ISet<string> phrases)
        {
            if (string.IsNullOrEmpty(text))
                return false;
            if (phrases.Contains(text))
                return true;
            string[] words = text.Split(' ');
            for (int split = 2; split < words.Length; split++)
            {
                string head = string.Join(" ", words, 0, split), tail = string.Join(" ", words, split, words.Length - split);
                if (IsCount(tail) && !IsCount(head) && phrases.Contains(head) && phrases.Contains(tail))
                    return true;
            }
            return false;
        }

        /// <summary>"five copies", "two times", "level two".</summary>
        static bool IsCount(string phrase)
        {
            string[] words = phrase.Split(' ');
            return words.Length == 2 && (words[1] == "copies" || words[1] == "times" || words[0] == "level");
        }

        /// <summary>
        /// The first and last 30 ms frame of this utterance that are speech, in seconds: at least the speech gate's
        /// <see cref="WhisperServerRecognizer.DefaultMinSpeechRms"/> and within 20 dB of the loudest frame (so steady
        /// room noise doesn't count). Null for silence.
        /// </summary>
        (float start, float end)? SpeechSpan()
        {
            float loudest = 0f;
            foreach (float rms in frameRms)
                loudest = Math.Max(loudest, rms);
            float threshold = Math.Max(WhisperServerRecognizer.DefaultMinSpeechRms, loudest / 10f);
            int first = frameRms.FindIndex(rms => rms >= threshold), last = frameRms.FindLastIndex(rms => rms >= threshold);
            if (first < 0)
                return null;
            return (first * FrameMs / 1000f, (last + 1) * FrameMs / 1000f);
        }

        /// <summary>Raises <paramref name="results"/>, or if there are none, <see cref="NoResult"/> with
        /// <paramref name="otherwise"/> (nothing for null).</summary>
        void Raise(List<RecognitionResult> results, NoResultReason? otherwise = null)
        {
            var copy = new List<RecognitionResult>(results);
            fastResults.Clear();
            slowResults.Clear();
            slowReason = null;
            if (copy.Count == 0 && otherwise.HasValue)
                NoResult?.Invoke(otherwise.Value);
            foreach (RecognitionResult result in copy)
                Recognized?.Invoke(result);
        }
    }

    public enum FastPathOutcome
    {
        /// <summary>No utterance yet.</summary>
        None,

        /// <summary>The fast recognizer heard one whole grammar phrase and answered.</summary>
        Fast,

        /// <summary>The slow recognizer answered (for chatter with no result, and its reason:
        /// <see cref="NoResultReason.NotUnderstood"/>).</summary>
        Slow,

        /// <summary>The slow recognizer failed; the fast recognizer's results went out instead.</summary>
        SlowFailed,

        /// <summary>No speech: too quiet for Whisper, or a silence hallucination Vosk didn't back up. No result went out,
        /// only <see cref="NoResultReason.Silence"/>.</summary>
        Silence,
    }
}

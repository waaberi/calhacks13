using System;
using System.Collections.Generic;

namespace SpatialModeling.VoiceCore.Whisper
{
    /// <summary>
    /// Vosk first, Whisper when Vosk isn't sure. Both get the audio. On release, if the fast recognizer's result is
    /// exactly one grammar phrase (no "[unk]") with confidence of at least <c>minFastConfidence</c>, it is used at
    /// Vosk's speed (about 10 ms). Otherwise the slow recognizer decodes the utterance and its result is used, even
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
    /// </summary>
    public sealed class FastPathRecognizer : ISpeechRecognizer, IReportsNoResult
    {
        /// <summary>The measured fast-path gate.</summary>
        public const float DefaultMinFastConfidence = 0.9f;

        readonly ISpeechRecognizer fast;
        readonly ISpeechRecognizer slow;
        readonly float minFastConfidence;
        readonly List<RecognitionResult> fastResults = new List<RecognitionResult>();
        readonly List<RecognitionResult> slowResults = new List<RecognitionResult>();
        HashSet<string> phrases = new HashSet<string>(StringComparer.Ordinal);
        NoResultReason? slowReason; // the slow recognizer's NoResult during this Stop
        IReadOnlyList<string> fullGrammar; // the last grammar that wasn't a question's
        int rate = 16000;

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

        public void Start(int sampleRate)
        {
            fastResults.Clear();
            slowResults.Clear();
            rate = sampleRate;
            fast.Start(sampleRate);
            slow.Start(sampleRate);
        }

        public void AcceptAudio(short[] samples, int count)
        {
            fast.AcceptAudio(samples, count);
            slow.AcceptAudio(samples, count);
        }

        public void Stop()
        {
            fast.Stop();
            if (fastResults.Count == 1 && phrases.Contains(fastResults[0].Text) && fastResults[0].Confidence >= minFastConfidence)
            {
                LastOutcome = FastPathOutcome.Fast;
                slow.Start(rate); // drops the slow recognizer's buffered audio unheard
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

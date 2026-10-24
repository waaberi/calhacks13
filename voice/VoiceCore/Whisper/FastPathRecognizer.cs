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
    /// </summary>
    public sealed class FastPathRecognizer : ISpeechRecognizer
    {
        /// <summary>The measured fast-path gate.</summary>
        public const float DefaultMinFastConfidence = 0.9f;

        readonly ISpeechRecognizer fast;
        readonly ISpeechRecognizer slow;
        readonly float minFastConfidence;
        readonly List<RecognitionResult> fastResults = new List<RecognitionResult>();
        readonly List<RecognitionResult> slowResults = new List<RecognitionResult>();
        HashSet<string> phrases = new HashSet<string>(StringComparer.Ordinal);
        int rate = 16000;

        public FastPathRecognizer(ISpeechRecognizer fast, ISpeechRecognizer slow, float minFastConfidence = DefaultMinFastConfidence)
        {
            this.fast = fast ?? throw new ArgumentNullException(nameof(fast));
            this.slow = slow ?? throw new ArgumentNullException(nameof(slow));
            this.minFastConfidence = minFastConfidence;
            fast.Recognized += fastResults.Add;
            slow.Recognized += slowResults.Add;
        }

        public event Action<RecognitionResult> Recognized;

        /// <summary>Vosk, for logs and measurements.</summary>
        public ISpeechRecognizer Fast => fast;

        /// <summary>Whisper, for logs and measurements.</summary>
        public ISpeechRecognizer Slow => slow;

        /// <summary>Which recognizer answered the last utterance.</summary>
        public FastPathOutcome LastOutcome { get; private set; }

        public void SetGrammar(IReadOnlyList<string> grammar)
        {
            fast.SetGrammar(grammar);
            slow.SetGrammar(grammar);
            phrases = new HashSet<string>(grammar ?? Array.Empty<string>(), StringComparer.Ordinal);
            phrases.Remove("[unk]");
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

            slow.Stop();
            if (slow is IFallibleRecognizer fallible && fallible.LastStopFailed)
            {
                LastOutcome = FastPathOutcome.SlowFailed;
                Raise(fastResults);
                return;
            }
            LastOutcome = FastPathOutcome.Slow;
            Raise(slowResults);
        }

        public void Dispose()
        {
            fast.Dispose();
            slow.Dispose();
        }

        void Raise(List<RecognitionResult> results)
        {
            var copy = new List<RecognitionResult>(results);
            fastResults.Clear();
            slowResults.Clear();
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

        /// <summary>The slow recognizer answered (possibly with nothing, for chatter).</summary>
        Slow,

        /// <summary>The slow recognizer failed; the fast recognizer's results went out instead.</summary>
        SlowFailed,
    }
}

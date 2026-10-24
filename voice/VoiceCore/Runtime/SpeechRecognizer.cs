using System;
using System.Collections.Generic;

namespace SpatialModeling.VoiceCore
{
    /// <summary>One final recognized utterance.</summary>
    public readonly struct RecognitionResult
    {
        public RecognitionResult(string text, float confidence)
        {
            Text = text ?? "";
            Confidence = confidence;
        }

        public string Text { get; }

        /// <summary>0 to 1. Results below <see cref="VoiceSessionOptions.MinConfidence"/> never produce a command.</summary>
        public float Confidence { get; }

        public override string ToString() => Text + " (" + Confidence.ToString("0.00") + ")";
    }

    /// <summary>Why a push-to-talk utterance ended without any <see cref="RecognitionResult"/>
    /// (<see cref="VoiceInput.TryGetNoResult"/>, then <see cref="VoiceSession.NothingRecognized"/>).</summary>
    public enum NoResultReason
    {
        /// <summary>Nothing to hear: silence or noise, such as an accidental press. Never spoken; the UI may show a short
        /// "Didn't catch that". The default for a recognizer without <see cref="IReportsNoResult"/>.</summary>
        Silence,

        /// <summary>Speech the recognizer couldn't turn into any phrase (Whisper's transcript snapped onto none). The
        /// session says <see cref="Prompt.LowConfidence"/> ("Sorry, I didn't catch that.").</summary>
        NotUnderstood,
    }

    /// <summary>
    /// Optional for an <see cref="ISpeechRecognizer"/>: says why <see cref="ISpeechRecognizer.Stop"/> raised no
    /// <see cref="ISpeechRecognizer.Recognized"/>. Raise <see cref="NoResult"/> from <c>Stop</c>, at most once per
    /// utterance and only when it raises no result. Only what can't be silence should be
    /// <see cref="NoResultReason.NotUnderstood"/>: a silent press must not speak (drop Whisper's silence hallucinations
    /// such as "you" as <see cref="NoResultReason.Silence"/>). <see cref="VoiceInput"/> reports every utterance without a
    /// result, as Silence when the recognizer doesn't say otherwise.
    /// </summary>
    public interface IReportsNoResult
    {
        event Action<NoResultReason> NoResult;
    }

    /// <summary>
    /// A speech recognizer behind VoiceCore. The Vosk implementation takes PCM from the Unity microphone;
    /// a recognizer that captures audio itself (Windows speech) ignores <see cref="AcceptAudio"/>.
    /// Raise <see cref="Recognized"/> once per final utterance, never for partial results.
    /// It may be raised on a worker thread: hand results to the main thread before calling
    /// <see cref="VoiceSession.Hear"/>.
    /// </summary>
    public interface ISpeechRecognizer : IDisposable
    {
        event Action<RecognitionResult> Recognized;

        /// <summary>Restricts recognition to these words or phrases (<see cref="VoiceSession.GrammarPhrases"/>).
        /// Takes effect at the next <see cref="Start"/>.</summary>
        void SetGrammar(IReadOnlyList<string> phrases);

        /// <summary>Starts an utterance, e.g. when push-to-talk is pressed.</summary>
        void Start(int sampleRate);

        /// <summary>Feeds 16-bit mono PCM samples captured since the last call.</summary>
        void AcceptAudio(short[] samples, int count);

        /// <summary>Ends the utterance, e.g. when push-to-talk is released, and raises the final result if any. Raise
        /// nothing for silence (see <see cref="IReportsNoResult"/> to tell speech that matched nothing apart).</summary>
        void Stop();
    }

    /// <summary>Vosk's JSON formats, kept here so they are tested without the native library.</summary>
    public static class VoskJson
    {
        /// <summary>The grammar argument for <c>new VoskRecognizer(model, rate, grammar)</c>: a JSON array of phrases.</summary>
        public static string Grammar(IEnumerable<string> phrases)
        {
            var parts = new List<string>();
            foreach (string phrase in phrases)
                parts.Add("\"" + phrase.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"");
            return "[" + string.Join(",", parts) + "]";
        }

        /// <summary>
        /// Reads a <c>Result()</c> or <c>FinalResult()</c> JSON. Confidence is the lowest word confidence, so call
        /// <c>SetWords(true)</c> on the recognizer; without word confidences a non-empty result gets 0.
        /// </summary>
        public static RecognitionResult ParseResult(string json)
        {
            string text = StringValue(json, "\"text\"") ?? "";
            float confidence = 0f;
            bool any = false;
            int at = 0;
            while ((at = json.IndexOf("\"conf\"", at, StringComparison.Ordinal)) >= 0)
            {
                at += 6;
                int start = json.IndexOf(':', at) + 1;
                int end = start;
                while (end < json.Length && "0123456789.eE+- ".IndexOf(json[end]) >= 0)
                    end++;
                if (float.TryParse(json.Substring(start, end - start).Trim(), System.Globalization.NumberStyles.Float,
                        System.Globalization.CultureInfo.InvariantCulture, out float conf))
                {
                    confidence = any ? Math.Min(confidence, conf) : conf;
                    any = true;
                }
            }
            return new RecognitionResult(text, confidence);
        }

        static string StringValue(string json, string key)
        {
            int at = json.IndexOf(key, StringComparison.Ordinal);
            int colon = at < 0 ? -1 : json.IndexOf(':', at + key.Length);
            int open = colon < 0 ? -1 : json.IndexOf('"', colon + 1);
            int close = open < 0 ? -1 : json.IndexOf('"', open + 1);
            return close < 0 ? null : json.Substring(open + 1, close - open - 1);
        }
    }
}

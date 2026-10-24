using System;
using System.Collections.Generic;

namespace SpatialModeling.VoiceCore
{
    /// <summary>One final recognized utterance.</summary>
    public readonly struct RecognitionResult
    {
        public RecognitionResult(string text, float confidence) : this(text, confidence, null)
        {
        }

        /// <param name="words">Each word with its own confidence, in order, when the recognizer gives them (Vosk).</param>
        public RecognitionResult(string text, float confidence, IReadOnlyList<RecognizedWord> words)
        {
            Text = text ?? "";
            Confidence = confidence;
            Words = words;
        }

        public string Text { get; }

        /// <summary>0 to 1. Results below <see cref="VoiceSessionOptions.MinConfidence"/> never produce a command.</summary>
        public float Confidence { get; }

        /// <summary>The words of <see cref="Text"/> with their confidences (Vosk's lowest is <see cref="Confidence"/>),
        /// or null when the recognizer doesn't give them.</summary>
        public IReadOnlyList<RecognizedWord> Words { get; }

        public override string ToString() => Text + " (" + Confidence.ToString("0.00") + ")";
    }

    /// <summary>One word of a <see cref="RecognitionResult"/>, the recognizer's confidence in it and when it was said.</summary>
    public readonly struct RecognizedWord
    {
        /// <param name="start">Seconds from the start of the utterance (<see cref="ISpeechRecognizer.Start"/>), or -1.</param>
        /// <param name="end">Seconds from the start of the utterance, or -1.</param>
        public RecognizedWord(string word, float confidence, float start = -1f, float end = -1f)
        {
            Word = word ?? "";
            Confidence = confidence;
            Start = start;
            End = end;
        }

        public string Word { get; }

        public float Confidence { get; }

        /// <summary>When the word began, in seconds from the start of the utterance; -1 if unknown.</summary>
        public float Start { get; }

        /// <summary>When the word ended, in seconds from the start of the utterance; -1 if unknown.</summary>
        public float End { get; }

        public override string ToString() => Word + " (" + Confidence.ToString("0.00") + ")";
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
        /// <c>SetWords(true)</c> on the recognizer; without word confidences a non-empty result gets 0. With them,
        /// <see cref="RecognitionResult.Words"/> has each word and its confidence.
        /// </summary>
        public static RecognitionResult ParseResult(string json)
        {
            string text = StringValue(json, "\"text\"") ?? "";
            float confidence = 0f;
            var confidences = new List<float>();
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
                    confidence = confidences.Count > 0 ? Math.Min(confidence, conf) : conf;
                    confidences.Add(conf);
                }
            }
            List<RecognizedWord> words = Words(json);
            bool aligned = words != null && words.Count == confidences.Count;
            return new RecognitionResult(text, confidence, aligned ? words : null);
        }

        /// <summary>The objects of the "result" array (conf, start, end, word), or null without one.</summary>
        static List<RecognizedWord> Words(string json)
        {
            int at = json.IndexOf("\"result\"", StringComparison.Ordinal);
            int open = at < 0 ? -1 : json.IndexOf('[', at);
            int close = open < 0 ? -1 : json.IndexOf(']', open);
            if (close < 0)
                return null;
            var words = new List<RecognizedWord>();
            int from = open;
            while (true)
            {
                int begin = json.IndexOf('{', from);
                if (begin < 0 || begin > close)
                    break;
                int end = json.IndexOf('}', begin);
                if (end < 0)
                    return null;
                string item = json.Substring(begin, end - begin + 1);
                string word = StringValue(item, "\"word\"");
                if (word == null)
                    return null;
                words.Add(new RecognizedWord(word, Number(item, "\"conf\"") ?? 0f, Number(item, "\"start\"") ?? -1f,
                    Number(item, "\"end\"") ?? -1f));
                from = end + 1;
            }
            return words.Count > 0 ? words : null;
        }

        static float? Number(string json, string key)
        {
            int at = json.IndexOf(key, StringComparison.Ordinal);
            if (at < 0)
                return null;
            int start = json.IndexOf(':', at + key.Length) + 1;
            int end = start;
            while (end < json.Length && "0123456789.eE+- ".IndexOf(json[end]) >= 0)
                end++;
            return float.TryParse(json.Substring(start, end - start).Trim(), System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out float value) ? value : (float?)null;
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

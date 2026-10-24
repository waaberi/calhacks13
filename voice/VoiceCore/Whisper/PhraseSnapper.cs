using System;
using System.Collections.Generic;

namespace SpatialModeling.VoiceCore.Whisper
{
    /// <summary>What <see cref="PhraseSnapper.Snap"/> made of a transcript.</summary>
    public readonly struct SnapResult
    {
        public SnapResult(string text, float similarity, bool accepted, bool wordForWord)
        {
            Text = text ?? "";
            Similarity = similarity;
            Accepted = accepted;
            WordForWord = wordForWord;
        }

        /// <summary>The transcript in grammar phrases, for example "add a cone" for "At a cone.".</summary>
        public string Text { get; }

        /// <summary>0 to 1: how much of the transcript the grammar phrases cover (1 means word for word).</summary>
        public float Similarity { get; }

        /// <summary>Similarity reached the snapper's threshold; otherwise the utterance is treated as chatter.</summary>
        public bool Accepted { get; }

        /// <summary>
        /// Every word of <see cref="Text"/> is one the recognizer wrote, in its order: at most some words were left
        /// out ("rotate it ninety degrees quickly"). False when the snap replaced words ("devil" to "bevel"): a guess.
        /// </summary>
        public bool WordForWord { get; }

        public override string ToString() => Text + " (" + Similarity.ToString("0.00") + (Accepted ? ")" : ", rejected)");
    }

    /// <summary>
    /// Maps a free-form transcript (Whisper writes "At a cone.", "Devil the edges.", "Rotate it 90°.") onto the
    /// recognizer grammar, the way Vosk's grammar mode would have heard it, or rejects it as chatter.
    /// Two readings are compared and the closer one wins:
    /// <list type="bullet">
    /// <item><b>Whole phrase:</b> the single grammar phrase with the highest character similarity
    /// 2·LCS/(|a|+|b|) to the whole transcript ("devil the edges" gives "bevel the edges").</item>
    /// <item><b>Phrase sequence:</b> the transcript split into consecutive grammar phrases, as Vosk chains them,
    /// each matched exactly or at a similarity of at least <see cref="MinSegmentSimilarity"/>; words that match
    /// nothing are dropped and count against the similarity. This keeps VoiceCore's word grammar working:
    /// "rotate this object ninety degrees" is five grammar words, not one phrase.</item>
    /// </list>
    /// Measured on the 290-clip TTS corpus with whole phrases only (voice-asr-alternatives study): at the 0.65
    /// threshold whisper tiny.en got 190/250 commands top-1 and accepted 0 of 68 chatter clips; the best chatter
    /// similarity was 0.55. Text is compared with the parser's own tokenizer, so digits, "°", "%" and "mm" become the
    /// grammar's words.
    /// </summary>
    public sealed class PhraseSnapper
    {
        /// <summary>The measured threshold: chatter peaked at 0.55; at 0.6 two chatter sentences got through.</summary>
        public const float DefaultThreshold = 0.65f;

        /// <summary>A part of the transcript may stand for a grammar phrase it isn't spelled like only this closely.</summary>
        public const float MinSegmentSimilarity = 0.8f;

        readonly List<string> phrases = new List<string>();
        readonly HashSet<string> exact = new HashSet<string>(StringComparer.Ordinal);
        readonly int longestPhraseWords;
        int[] lcsRows = new int[64];

        public PhraseSnapper(IEnumerable<string> grammarPhrases, float threshold = DefaultThreshold)
        {
            Threshold = threshold;
            foreach (string phrase in grammarPhrases ?? Array.Empty<string>())
            {
                string normalized = Normalize(phrase);
                if (normalized.Length == 0 || !exact.Add(normalized))
                    continue;
                phrases.Add(normalized);
                longestPhraseWords = Math.Max(longestPhraseWords, normalized.Split(' ').Length);
            }
        }

        /// <summary>Similarity a result needs to be accepted.</summary>
        public float Threshold { get; }

        /// <summary>Distinct grammar phrases, without "[unk]".</summary>
        public int Count => phrases.Count;

        /// <summary>The grammar phrases closest to <paramref name="transcript"/>; empty and not accepted for silence.</summary>
        public SnapResult Snap(string transcript)
        {
            string text = WithoutRepeats(Normalize(transcript));
            if (text.Length == 0 || phrases.Count == 0)
                return new SnapResult("", 0f, false, false);
            if (exact.Contains(text))
                return new SnapResult(text, 1f, true, true);

            (string whole, float wholeSimilarity) = ClosestPhrase(text, 0f);
            (string sequence, float sequenceSimilarity) = Sequence(text);
            bool useSequence = sequenceSimilarity > wholeSimilarity;
            string best = useSequence ? sequence : whole;
            float similarity = useSequence ? sequenceSimilarity : wholeSimilarity;
            return new SnapResult(best, similarity, best.Length > 0 && similarity >= Threshold, IsSubsequence(best, text));
        }

        /// <summary>The words of <paramref name="part"/> appear in <paramref name="text"/> in the same order.</summary>
        static bool IsSubsequence(string part, string text)
        {
            if (part.Length == 0)
                return false;
            string[] words = text.Split(' ');
            int at = 0;
            foreach (string word in part.Split(' '))
            {
                while (at < words.Length && words[at] != word)
                    at++;
                if (at++ >= words.Length)
                    return false;
            }
            return true;
        }

        /// <summary>
        /// Lower case words as the parser reads them (<see cref="Vocabulary.Words"/>): "Rotate it 90°." gives
        /// "rotate it ninety degrees". Punctuation and "[unk]" are dropped.
        /// </summary>
        public static string Normalize(string text)
        {
            var words = new List<string>();
            foreach (string word in Vocabulary.Words(text))
            {
                string bare = word.Replace("'", "");
                if (word != Vocabulary.Unknown && bare.Length > 0)
                    words.Add(bare);
            }
            return string.Join(" ", words);
        }

        /// <summary>
        /// "left left left" becomes "left": on short clips Whisper often repeats the word. Measured on 1,008 real
        /// Speech Commands clips (realvoice-public study), collapsing repeats took tiny.en from 884 to 908 right.
        /// </summary>
        public static string WithoutRepeats(string normalized)
        {
            string[] words = normalized.Split(' ');
            var kept = new List<string>(words.Length);
            foreach (string word in words)
                if (kept.Count == 0 || kept[kept.Count - 1] != word)
                    kept.Add(word);
            return string.Join(" ", kept);
        }

        /// <summary>The whole-phrase reading of normalized text (for tests and measurements).</summary>
        internal (string phrase, float similarity) Whole(string normalized) => ClosestPhrase(normalized, 0f);

        /// <summary>The phrase-sequence reading of normalized text (for tests and measurements).</summary>
        internal (string text, float similarity) Sequence(string normalized) =>
            normalized.Length == 0 ? ("", 0f) : Sequence(normalized.Split(' '));

        /// <summary>The phrase most similar to <paramref name="text"/>, if one beats <paramref name="atLeast"/>.</summary>
        (string phrase, float similarity) ClosestPhrase(string text, float atLeast)
        {
            string best = "";
            float bestSimilarity = atLeast;
            foreach (string phrase in phrases)
            {
                if (2f * Math.Min(text.Length, phrase.Length) / (text.Length + phrase.Length) <= bestSimilarity)
                    continue; // the length difference alone rules it out
                float similarity = 2f * Lcs(text, phrase) / (text.Length + phrase.Length);
                if (similarity > bestSimilarity)
                {
                    bestSimilarity = similarity;
                    best = phrase;
                }
            }
            return best.Length == 0 ? ("", 0f) : (best, bestSimilarity);
        }

        /// <summary>
        /// The best split of the words into grammar phrases (dynamic programming over word positions). Score: letters
        /// covered, each phrase weighted by its similarity to its words; a dropped word covers nothing. Ties go to
        /// fewer, longer phrases.
        /// </summary>
        (string text, float similarity) Sequence(string[] words)
        {
            int n = words.Length;
            var score = new float[n + 1];
            var parts = new int[n + 1];
            var from = new int[n + 1];
            var chosen = new string[n + 1];
            for (int i = 1; i <= n; i++)
                score[i] = float.NegativeInfinity;

            int letters = 0;
            foreach (string word in words)
                letters += word.Length;

            for (int i = 0; i < n; i++)
            {
                if (float.IsNegativeInfinity(score[i]))
                    continue;
                Offer(i + 1, score[i], parts[i], i, null); // drop words[i]
                string segment = "";
                int segmentLetters = 0;
                for (int j = i; j < n && j - i < longestPhraseWords; j++)
                {
                    segment = j == i ? words[j] : segment + " " + words[j];
                    segmentLetters += words[j].Length;
                    if (exact.Contains(segment))
                    {
                        Offer(j + 1, score[i] + segmentLetters, parts[i] + 1, i, segment);
                        continue;
                    }
                    (string phrase, float similarity) = ClosestPhrase(segment, MinSegmentSimilarity - 1e-6f);
                    if (phrase.Length > 0)
                        Offer(j + 1, score[i] + similarity * segmentLetters, parts[i] + 1, i, phrase);
                }
            }

            var picked = new List<string>();
            for (int at = n; at > 0; at = from[at])
                if (chosen[at] != null)
                    picked.Add(chosen[at]);
            picked.Reverse();
            return picked.Count == 0 || letters == 0 ? ("", 0f) : (string.Join(" ", picked), score[n] / letters);

            void Offer(int to, float value, int count, int start, string phrase)
            {
                bool better = value > score[to] + 1e-4f || (value >= score[to] - 1e-4f && count < parts[to]);
                if (!better)
                    return;
                score[to] = value;
                parts[to] = count;
                from[to] = start;
                chosen[to] = phrase;
            }
        }

        /// <summary>Length of the longest common subsequence, in two reused rows.</summary>
        int Lcs(string a, string b)
        {
            int width = b.Length + 1;
            if (lcsRows.Length < 2 * width)
                lcsRows = new int[2 * width];
            int previous = 0, current = width;
            Array.Clear(lcsRows, 0, 2 * width);
            for (int i = 0; i < a.Length; i++)
            {
                lcsRows[current] = 0;
                for (int j = 0; j < b.Length; j++)
                    lcsRows[current + j + 1] = a[i] == b[j]
                        ? lcsRows[previous + j] + 1
                        : Math.Max(lcsRows[previous + j + 1], lcsRows[current + j]);
                int swap = previous;
                previous = current;
                current = swap;
            }
            return lcsRows[previous + b.Length];
        }
    }
}

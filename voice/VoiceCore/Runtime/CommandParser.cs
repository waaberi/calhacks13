using System.Collections.Generic;

namespace SpatialModeling.VoiceCore
{
    internal enum TargetRef
    {
        /// <summary>No target words.</summary>
        None,
        /// <summary>"this", "it": resolve from selection, pointer or the only object.</summary>
        Context,
        Named,
        /// <summary>Several objects match the spoken name.</summary>
        Ambiguous,
        /// <summary>Words that look like a name but match no object.</summary>
        Unknown,
    }

    /// <summary>What one utterance says. Every field is optional; the session decides what is missing.</summary>
    internal sealed class ParsedUtterance
    {
        public CommandKind? Verb;
        public Shape? Shape;
        public Axis? Axis;
        public double? Number;
        public SpokenUnit? Unit;
        public bool Negative;
        public TargetRef Target;
        public SceneObject Named;

        /// <summary>Words outside the vocabulary (including Vosk's "[unk]"), ignoring any before the verb.</summary>
        public bool HasUnknownWords;
    }

    /// <summary>
    /// Turns recognized text into a <see cref="ParsedUtterance"/>. Slots can appear in any order: "rotate this
    /// ninety degrees around z" and "rotate around z by ninety degrees" mean the same.
    /// </summary>
    internal static class CommandParser
    {
        /// <param name="pendingKind">The pending command's kind; decides how a fragment such as "cube" is read.</param>
        public static ParsedUtterance Parse(string text, IReadOnlyList<SceneObject> objects, CommandKind? pendingKind = null)
        {
            List<string> words = Vocabulary.Words(text);
            var parsed = new ParsedUtterance();
            var used = new bool[words.Count];

            int verbAt = words.FindIndex(w => Vocabulary.Verbs.ContainsKey(w));
            if (verbAt >= 0)
            {
                parsed.Verb = Vocabulary.Verbs[words[verbAt]];
                for (int i = 0; i <= verbAt; i++)
                    used[i] = true; // Words before the verb ("okay", "[unk]") are preamble.
            }

            CommandKind? kind = parsed.Verb ?? pendingKind;
            bool targetable = kind.HasValue && Vocabulary.IsTargetable(kind.Value);
            if (targetable)
                MatchName(words, used, objects, parsed);

            bool deictic = false, nameLike = false;
            int negations = 0;
            for (int i = 0; i < words.Count; i++)
            {
                if (used[i])
                    continue;
                string w = words[i];
                int start = i;
                if (Vocabulary.Deictic.Contains(w))
                {
                    deictic = true;
                    if ((w == "this" || w == "that") && At(words, i + 1) == "one" && !ContinuesNumber(At(words, i + 2)))
                        i++; // "this one", but not "this one point five meters"
                }
                else if (Vocabulary.Shapes.TryGetValue(w, out Shape shape))
                {
                    if (targetable)
                        nameLike = true; // "rotate the cube" with no object called cube
                    else
                        parsed.Shape = parsed.Shape ?? shape;
                }
                else if (Vocabulary.Axes.TryGetValue(w, out Axis axis))
                    parsed.Axis = parsed.Axis ?? axis;
                else if (Vocabulary.Negations.Contains(w))
                    negations++;
                else if (Vocabulary.Directions.TryGetValue(w, out int direction))
                {
                    if (kind == CommandKind.Move)
                    {
                        parsed.Axis = parsed.Axis ?? Axis.Z;
                        if (direction < 0)
                            negations++;
                    }
                }
                else if (NumberWords.TryRead(words, ref i, out double number))
                {
                    if (!parsed.Number.HasValue)
                    {
                        parsed.Number = number;
                        if (i < words.Count && Vocabulary.Units.TryGetValue(words[i], out SpokenUnit numberUnit))
                            parsed.Unit = numberUnit;
                    }
                    if (i < words.Count && Vocabulary.Units.ContainsKey(words[i]))
                        i++;
                    i--; // TryRead moved past the number; the loop adds one.
                }
                else if (Vocabulary.Units.TryGetValue(w, out SpokenUnit unit))
                    parsed.Unit = parsed.Unit ?? unit;
                else if (!Vocabulary.Fillers.Contains(w) && !Vocabulary.Verbs.ContainsKey(w) && !IsNumberWord(w))
                {
                    parsed.HasUnknownWords = true;
                    nameLike = true;
                }

                for (int k = start; k <= i && k < used.Length; k++)
                    used[k] = true;
            }

            parsed.Negative = negations % 2 == 1;
            if (parsed.Target == TargetRef.None && targetable)
                parsed.Target = deictic ? TargetRef.Context : nameLike ? TargetRef.Unknown : TargetRef.None;
            return parsed;
        }

        static string At(List<string> words, int i) => i < words.Count ? words[i] : null;

        static bool ContinuesNumber(string next) =>
            next == "point" || next == "hundred" || (next != null && Vocabulary.Units.ContainsKey(next));

        static bool IsNumberWord(string w)
        {
            foreach (string n in NumberWords.All)
                if (n == w)
                    return true;
            return false;
        }

        /// <summary>
        /// Finds the object whose spoken name appears in the words. A full name ("cube one" for Cube.001) beats its
        /// base name ("cube"), and longer names beat shorter ones. Ties are ambiguous.
        /// </summary>
        static void MatchName(List<string> words, bool[] used, IReadOnlyList<SceneObject> objects, ParsedUtterance parsed)
        {
            int bestScore = 0, bestAt = -1, bestLength = 0, matches = 0;
            SceneObject best = null;
            foreach (SceneObject obj in objects)
            {
                List<string> full = Vocabulary.Words(obj.Name);
                string baseName = BaseName(obj.Name);
                List<string> partial = baseName == null ? null : Vocabulary.Words(baseName);
                int at = Find(words, used, full);
                int score = at >= 0 ? full.Count * 2 + 1 : 0;
                int length = full.Count;
                if (at < 0 && partial != null && (at = Find(words, used, partial)) >= 0)
                {
                    score = partial.Count * 2;
                    length = partial.Count;
                }
                if (score == 0 || score < bestScore)
                    continue;
                if (score > bestScore)
                {
                    bestScore = score;
                    bestAt = at;
                    bestLength = length;
                    best = obj;
                    matches = 0;
                }
                matches++;
            }
            if (best == null)
                return;
            for (int i = bestAt; i < bestAt + bestLength; i++)
                used[i] = true;
            if (matches == 1)
            {
                parsed.Target = TargetRef.Named;
                parsed.Named = best;
            }
            else
                parsed.Target = TargetRef.Ambiguous;
        }

        /// <summary>"Cube.001" gives "Cube"; null when the name has no trailing number.</summary>
        static string BaseName(string name)
        {
            int end = name.Length;
            while (end > 0 && char.IsDigit(name[end - 1]))
                end--;
            if (end == name.Length)
                return null;
            while (end > 0 && " ._-".IndexOf(name[end - 1]) >= 0)
                end--;
            return end == 0 ? null : name.Substring(0, end);
        }

        static int Find(List<string> words, bool[] used, List<string> name)
        {
            if (name.Count == 0)
                return -1;
            for (int start = 0; start + name.Count <= words.Count; start++)
            {
                int k = 0;
                while (k < name.Count && !used[start + k] && words[start + k] == name[k])
                    k++;
                if (k == name.Count)
                    return start;
            }
            return -1;
        }
    }
}

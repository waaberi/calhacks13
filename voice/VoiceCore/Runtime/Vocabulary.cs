using System.Collections.Generic;
using System.Text;

namespace SpatialModeling.VoiceCore
{
    /// <summary>
    /// Every word VoiceCore understands. The parser looks words up here and <see cref="GrammarPhrases"/>
    /// builds the recognizer grammar from the same tables, so the grammar and the parser can't drift apart.
    /// </summary>
    internal static class Vocabulary
    {
        public static readonly Dictionary<string, CommandKind> Verbs = new Dictionary<string, CommandKind>
        {
            { "add", CommandKind.AddShape }, { "create", CommandKind.AddShape },
            { "select", CommandKind.Select },
            { "move", CommandKind.Move },
            { "rotate", CommandKind.Rotate }, { "turn", CommandKind.Rotate },
            { "scale", CommandKind.Scale },
            { "delete", CommandKind.Delete }, { "remove", CommandKind.Delete },
            { "undo", CommandKind.Undo },
            { "redo", CommandKind.Redo },
            { "cancel", CommandKind.Cancel },
            { "apply", CommandKind.Apply },
        };

        public static readonly Dictionary<string, Shape> Shapes = new Dictionary<string, Shape>
        {
            { "cube", Shape.Cube }, { "sphere", Shape.Sphere }, { "cylinder", Shape.Cylinder },
        };

        public static readonly Dictionary<string, Axis> Axes = new Dictionary<string, Axis>
        {
            { "x", Axis.X }, { "y", Axis.Y }, { "z", Axis.Z },
        };

        public static readonly Dictionary<string, SpokenUnit> Units = new Dictionary<string, SpokenUnit>
        {
            { "millimeter", SpokenUnit.Millimeters }, { "millimeters", SpokenUnit.Millimeters },
            { "centimeter", SpokenUnit.Centimeters }, { "centimeters", SpokenUnit.Centimeters },
            { "meter", SpokenUnit.Meters }, { "meters", SpokenUnit.Meters },
            { "degree", SpokenUnit.Degrees }, { "degrees", SpokenUnit.Degrees },
            { "percent", SpokenUnit.Percent },
            { "times", SpokenUnit.Times },
        };

        /// <summary>Move only: up is +Z, down is -Z (Blender is Z up).</summary>
        public static readonly Dictionary<string, int> Directions = new Dictionary<string, int> { { "up", 1 }, { "down", -1 } };

        public static readonly HashSet<string> Negations = new HashSet<string> { "minus", "negative" };

        /// <summary>"This object": resolved from selection, pointer or the only object.</summary>
        public static readonly HashSet<string> Deictic = new HashSet<string> { "this", "that", "it", "selected" };

        public static readonly HashSet<string> Fillers = new HashSet<string>
        {
            "the", "a", "an", "object", "by", "to", "along", "around", "about", "on", "in", "axis", "please", "and",
        };

        /// <summary>Spellings from free-text recognizers (Windows dictation). Not in the grammar.</summary>
        public static readonly Dictionary<string, string> Aliases = new Dictionary<string, string>
        {
            { "mm", "millimeters" }, { "cm", "centimeters" }, { "m", "meters" }, { "deg", "degrees" },
            { "millimetre", "millimeter" }, { "millimetres", "millimeters" },
            { "centimetre", "centimeter" }, { "centimetres", "centimeters" },
            { "metre", "meter" }, { "metres", "meters" },
        };

        /// <summary>Out-of-grammar speech, as Vosk reports it.</summary>
        public const string Unknown = "[unk]";

        public static bool IsTargetable(CommandKind kind) =>
            kind == CommandKind.Select || kind == CommandKind.Move || kind == CommandKind.Rotate ||
            kind == CommandKind.Scale || kind == CommandKind.Delete;

        /// <summary>All command words, the words of the given object names, and "[unk]".</summary>
        public static List<string> GrammarPhrases(IEnumerable<string> objectNames)
        {
            var words = new SortedSet<string>(System.StringComparer.Ordinal);
            words.UnionWith(Verbs.Keys);
            words.UnionWith(Shapes.Keys);
            words.UnionWith(Axes.Keys);
            words.UnionWith(Units.Keys);
            words.UnionWith(Directions.Keys);
            words.UnionWith(Negations);
            words.UnionWith(Deictic);
            words.UnionWith(Fillers);
            words.UnionWith(NumberWords.All);
            foreach (string name in objectNames)
                words.UnionWith(Words(name));
            words.Remove(Unknown);
            var phrases = new List<string>(words) { Unknown };
            return phrases;
        }

        /// <summary>
        /// Splits text into lower-case words: "Rotate Cube.001 by 90°" gives rotate, cube, one, by, ninety, degrees.
        /// Digits become number words and camelCase is split, so object names and free text tokenize the same way.
        /// </summary>
        public static List<string> Words(string text)
        {
            var words = new List<string>();
            var current = new StringBuilder();
            bool digits = false;

            void Flush()
            {
                if (current.Length == 0)
                    return;
                string word = current.ToString();
                current.Clear();
                if (digits)
                    words.AddRange(NumberWords.FromDigits(word));
                else
                    words.Add(Aliases.TryGetValue(word, out string alias) ? alias : word);
            }

            text = text ?? "";
            for (int i = 0; i < text.Length; i++)
            {
                char c = text[i];
                if (c == '[' && string.CompareOrdinal(text, i, Unknown, 0, Unknown.Length) == 0)
                {
                    Flush();
                    words.Add(Unknown);
                    i += Unknown.Length - 1;
                }
                else if (char.IsLetter(c) || (c == '\'' && current.Length > 0 && !digits))
                {
                    bool camel = char.IsUpper(c) && i > 0 && char.IsLower(text[i - 1]);
                    if (digits || camel)
                        Flush();
                    digits = false;
                    current.Append(char.ToLowerInvariant(c));
                }
                else if (char.IsDigit(c) || (c == '.' && digits && i + 1 < text.Length && char.IsDigit(text[i + 1])))
                {
                    if (!digits)
                        Flush();
                    if (current.Length == 0 && i > 0 && text[i - 1] == '-' && (i == 1 || !char.IsLetterOrDigit(text[i - 2])))
                        words.Add("minus");
                    digits = true;
                    current.Append(c);
                }
                else
                {
                    Flush();
                    if (c == '%')
                        words.Add("percent");
                    else if (c == '°')
                        words.Add("degrees");
                }
            }
            Flush();
            return words;
        }
    }
}

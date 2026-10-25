using System;
using System.Collections.Generic;

namespace SpatialModeling
{
    // Keep every detail available without an unbounded head-locked text sheet.
    public static class VoiceDialogPages
    {
        public static string[] Build(string content, int columns = 64, int rows = 9)
        {
            if (columns < 1 || rows < 1) throw new ArgumentOutOfRangeException();
            var lines = new List<string>();
            foreach (string raw in (content ?? "").Replace("\r", "").Split('\n'))
            {
                string line = raw;
                while (line.Length > columns)
                {
                    int split = line.LastIndexOf(' ', columns, columns);
                    if (split <= 0) split = columns;
                    lines.Add(line.Substring(0, split));
                    line = line.Substring(split).TrimStart(' ');
                }
                lines.Add(line);
            }
            var pages = new List<string>();
            for (int i = 0; i < lines.Count; i += rows)
                pages.Add(string.Join("\n", lines.GetRange(i, Math.Min(rows, lines.Count - i))));
            return pages.ToArray();
        }

        // Whole utterances only: never discard an additional clause or dimension.
        public static string BasicCreation(string utterance)
        {
            var match = System.Text.RegularExpressions.Regex.Match(utterance ?? "",
                @"^\s*(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?:add|create|make)\s+(?:(?:a|an|another)\s+)?(cube|sphere|cylinder)(?:\s+(?:to|in)\s+(?:the|my|this)\s+scene)?(?:\s+(?:for\s+me|please))?\s*[.!?]*\s*$",
                System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            return match.Success ? "add a " + match.Groups[1].Value.ToLowerInvariant() : null;
        }
    }
}

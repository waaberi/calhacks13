using System.Collections.Generic;

namespace SpatialModeling.VoiceCore
{
    /// <summary>
    /// Spoken numbers from zero to 999.999: "ninety", "forty five", "one hundred and eighty", "one point five",
    /// "zero point two five". Larger numbers are not understood. "One eighty" is deliberately two numbers:
    /// recognizers hear "to fifty" as "two fifty", so the parser treats adjacent numbers as ambiguous.
    /// </summary>
    internal static class NumberWords
    {
        static readonly string[] Small =
        {
            "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
            "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
        };

        static readonly string[] Tens = { null, null, "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety" };

        public static IEnumerable<string> All
        {
            get
            {
                foreach (string word in Small)
                    yield return word;
                for (int i = 2; i < Tens.Length; i++)
                    yield return Tens[i];
                yield return "hundred";
                yield return "point";
            }
        }

        /// <summary>0 to 999 as words, e.g. 123 is "one hundred twenty three".</summary>
        public static string ToWords(int n)
        {
            if (n < 20)
                return Small[n];
            if (n < 100)
                return Tens[n / 10] + (n % 10 == 0 ? "" : " " + Small[n % 10]);
            return Small[n / 100] + " hundred" + (n % 100 == 0 ? "" : " " + ToWords(n % 100));
        }

        /// <summary>"90" is ninety, "1.5" is one point five, "001" is one; above 999 the digits are spelled out.</summary>
        public static IEnumerable<string> FromDigits(string digits)
        {
            int dot = digits.IndexOf('.');
            string whole = dot < 0 ? digits : digits.Substring(0, dot);
            string trimmed = whole.TrimStart('0');
            var words = new List<string>();
            if (trimmed.Length <= 3)
                words.AddRange(ToWords(trimmed.Length == 0 ? 0 : int.Parse(trimmed)).Split(' '));
            else
                foreach (char c in whole)
                    words.Add(Small[c - '0']);
            if (dot >= 0)
            {
                words.Add("point");
                for (int i = dot + 1; i < digits.Length; i++)
                    words.Add(Small[digits[i] - '0']);
            }
            return words;
        }

        /// <summary>Reads a number starting at <paramref name="i"/> and moves <paramref name="i"/> past it. A number whose
        /// end was misheard ("one hundred and a") is read as NaN.</summary>
        public static bool TryRead(IReadOnlyList<string> w, ref int i, out double value)
        {
            int j = i;
            int whole = 0;
            bool any = false;
            int hundreds = SmallValue(At(w, j));
            if (hundreds >= 1 && hundreds <= 9 && At(w, j + 1) == "hundred")
            {
                j += 2;
                whole = hundreds * 100;
                any = true;
                int k = At(w, j) == "and" ? j + 1 : j;
                if (ReadBelowHundred(w, ref k, out int rest))
                {
                    whole += rest;
                    j = k;
                }
                else if (k > j)
                {
                    value = double.NaN; // "one hundred and a degrees": the rest of the number was misheard
                    i = k;
                    return true;
                }

            }
            else if (ReadBelowHundred(w, ref j, out int below))
            {
                whole = below;
                any = true;
            }

            double fraction = 0;
            if (At(w, j) == "point")
            {
                int k = j + 1;
                double scale = 0.1;
                int digit;
                while (k - j <= 3 && (digit = SmallValue(At(w, k))) >= 0 && digit <= 9)
                {
                    fraction += digit * scale;
                    scale /= 10;
                    k++;
                }
                if (k == j + 1 && ReadBelowHundred(w, ref k, out int f))
                    fraction = f / (f < 10 ? 10.0 : 100.0); // "point twenty five"
                if (k > j + 1)
                {
                    j = k;
                    any = true;
                }
            }

            value = whole + fraction;
            if (any)
                i = j;
            return any;
        }

        static bool ReadBelowHundred(IReadOnlyList<string> w, ref int j, out int value)
        {
            int tens = TensValue(At(w, j));
            if (tens > 0)
            {
                j++;
                int ones = SmallValue(At(w, j));
                if (ones >= 1 && ones <= 9)
                {
                    tens += ones;
                    j++;
                }
                value = tens;
                return true;
            }
            value = SmallValue(At(w, j));
            if (value < 0)
                return false;
            j++;
            return true;
        }

        static string At(IReadOnlyList<string> w, int i) => i < w.Count ? w[i] : null;

        static int SmallValue(string word) => word == null ? -1 : System.Array.IndexOf(Small, word);

        static int TensValue(string word)
        {
            int i = word == null ? -1 : System.Array.IndexOf(Tens, word);
            return i < 2 ? 0 : i * 10;
        }
    }
}

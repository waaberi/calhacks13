using System.Text.RegularExpressions;

namespace SpatialModeling.VoiceCore
{
    // Only a caller with a live missing-axis slot may use this answer. Never
    // globally rewrite "why", object names, numeric amounts or compound tails.
    public static class AxisClarification
    {
        const string AxisWord = @"(?:x|y|z|ex|why|zee|zed)";
        const string AxisPhrase = @"(?:the\s+)?(?:(?:negative|minus)\s+)?" + AxisWord + @"(?:\s+axis)?";
        public static string Normalize(string text)
        {
            string value=Regex.Replace((text??"").Trim().ToLowerInvariant(),@"[.,!?]", " ");
            value=Regex.Replace(value,@"\s+"," ").Trim();
            // An explicit self-correction chooses its final axis. Two axes
            // without a correction stay ambiguous; no suffix is discarded.
            var correction=Regex.Match(value,@"^(?:"+AxisPhrase+@"\s+)?(?:no\s+i\s+mean|i\s+mean|sorry|actually|rather)\s+(?<answer>"+AxisPhrase+@")$");
            if(correction.Success)value=correction.Groups["answer"].Value;
            if(!Regex.IsMatch(value,@"^"+AxisPhrase+@"$"))return null;
            string axis=Regex.Match(value,AxisWord+@"(?=\s+axis$|$)").Value;
            if(axis=="why")axis="y";else if(axis=="ex")axis="x";else if(axis=="zee"||axis=="zed")axis="z";
            return (Regex.IsMatch(value,@"\b(negative|minus)\b")?"negative ":"")+axis;
        }
    }
}

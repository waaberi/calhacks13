using System;
using System.Text.RegularExpressions;

namespace SpatialModeling.VoiceCore
{
    public sealed partial class VoiceSession
    {
        bool compositionEnabled;
        string compositionToken;
        string compositionMissing;
        DateTime compositionExpires;
        public string CompositionQuestion { get; private set; }
        public DateTime CompositionExpiresAt => compositionExpires;

        // Explicit capability negotiation: an older host never receives new compound syntax.
        public void EnableComposition(bool enabled) { compositionEnabled = enabled; if (!enabled) ClearComposition(); }

        public static bool IsCompositionRequest(string text)
        {
            string t = text ?? "";
            return Regex.IsMatch(t, @"\bthen\b|;|\band\s+(?:add|create|move|rotate|turn|scale|select|delete|remove|colour|color|paint|duplicate|reset|set|shade|subdivide|bevel|mirror|solidify|decimate|triangulate|weld|convert|apply|make|smooth|separate|flip|merge|recalculate|round|undo|redo|cancel|save)\b", RegexOptions.IgnoreCase)
                || Regex.IsMatch(t, @"\b(colou?r|paint|lighter|darker|lighten|darken|duplicate|reset|width|height|depth|wide|tall|deep)\b", RegexOptions.IgnoreCase)
                || Regex.IsMatch(t, @"\bscale\b.*\b(down|up|negative|minus|x|y|z|half|double|twice)\b", RegexOptions.IgnoreCase)
                || Regex.IsMatch(t, @"\bscale\b.*-\s*\d", RegexOptions.IgnoreCase)
                || Regex.IsMatch(t, @"\b(add|create)\b.*\b(along|at|from)\b", RegexOptions.IgnoreCase);
        }

        void ClearComposition()
        {
            compositionToken = compositionMissing = CompositionQuestion = null;
        }

        void CancelComposition(Turn turn, Prompt why)
        {
            if (compositionToken == null) return;
            ClearComposition();
            resolving = null;
            turn.Prompts.Add(why);
        }

        bool HearComposition(RecognitionResult result, Turn turn)
        {
            string text = string.Join(" ", Vocabulary.Words(result.Text));
            if (text == "cancel" || text == "never mind" || text == "cancel that")
            {
                if (compositionToken == null) return false;
                CancelComposition(turn, Prompt.Cancelled);
                // Still emit Cancel so the adapter also drops a waiting destructive confirmation.
                HearHere(new RecognitionResult("cancel", 1), turn);
                return true;
            }
            if (!compositionEnabled || (compositionToken == null && !IsCompositionRequest(result.Text))) return false;
            if (result.Confidence < options.MinConfidence)
            {
                turn.Prompts.Add(Prompt.LowConfidence);
                return true;
            }
            // A fresh editing utterance replaces the unfinished chain; a field answer resumes it.
            if (compositionToken != null && Regex.IsMatch(text, @"^(add|create|move|rotate|turn|scale|delete|remove|colour|color|duplicate|reset|set|shade|subdivide|bevel)\b"))
                CancelComposition(turn, Prompt.ReplacedPending);
            EndChoice(turn);
            pending = null;
            AskHost(result, turn);
            return true;
        }

        void ResumeCompositionTarget(Turn turn, bool pointer = false)
        {
            if (compositionToken == null || compositionMissing != "target" || resolving != null) return;
            SceneObject target = pointer ? Find(pointerId) : SingleSelected();
            if (target == null || (pointer && clock() - pointerSince < options.PointerDwell)) return;
            AskHost(new RecognitionResult("selected", 1), turn);
        }

        bool AnswerComposition(VoiceCandidates answer, Turn turn)
        {
            if (answer.Decision == VoiceDecision.Clarify)
            {
                resolving = null;
                compositionToken = answer.Resolution;
                compositionMissing = answer.Missing;
                compositionExpires = clock() + TimeSpan.FromSeconds(Math.Min(30, answer.ExpiresIn));
                CompositionQuestion = answer.Reason;
                turn.Asked = true;
                turn.Prompts.Add(answer.Missing == "target" ? Prompt.AskTarget : answer.Missing == "axis" ? Prompt.AskAxis
                    : answer.Missing == "distance" ? Prompt.AskDistance : answer.Missing == "unit" ? Prompt.AskUnit
                    : answer.Missing == "angle" || answer.Missing == "angle_unit" ? Prompt.AskAngle
                    : answer.Missing == "factor" ? Prompt.AskFactor : Prompt.AskDetails);
                return true;
            }
            // A rejection of a composition MUST NOT fall back to a partial core command.
            if (compositionToken != null || IsCompositionRequest(resolving.Result.Text))
            {
                ClearComposition();
                if (answer.Decision == VoiceDecision.Reject)
                {
                    resolving = null;
                    turn.Prompts.Add(Prompt.Failed);
                    return true;
                }
            }
            return false;
        }
    }
}

using System;
using System.Text.RegularExpressions;

namespace SpatialModeling.VoiceCore
{
    public enum VoiceRoute { Core, Gemini }
    public static class VoiceRouting
    {
        public static bool IsControl(string text)
        {
            string bounded=Regex.Replace((text??"").Trim(),@"[.!?]+$","").Trim();
            if(Regex.IsMatch(bounded,@"^(never\s+mind|save(?:\s+(?:the\s+)?(?:file|project))?)$",RegexOptions.IgnoreCase))return true;
            var probe=new VoiceSession(new VoiceSessionOptions { AskHost=false },()=>DateTime.UtcNow);
            var turn=probe.Hear(new RecognitionResult(bounded,1));
            var kind=turn.Command?.Kind??probe.Pending?.Command.Kind;
            return kind==CommandKind.Undo||kind==CommandKind.Redo||kind==CommandKind.Cancel
                ||(kind==CommandKind.Select&&!VoiceSession.IsCompositionRequest(bounded));
        }
        public static VoiceRoute Decide(string text, bool aiEnabled, bool aiAvailable, bool coreDialogue)
            => !aiEnabled||!aiAvailable||IsControl(text)||(coreDialogue&&IsSimpleFieldAnswer(text)) ? VoiceRoute.Core : VoiceRoute.Gemini;
        public static VoiceRoute Decide(string text,bool aiEnabled,bool aiAvailable,VoiceSession session)
            => !aiEnabled||!aiAvailable||IsControl(text)||session?.IsDialogueAnswer(text)==true ? VoiceRoute.Core : VoiceRoute.Gemini;
        static bool IsSimpleFieldAnswer(string text)
        {
            if(AxisClarification.Normalize(text)!=null||AxisClarification.IsAmbiguousAnswer(text))return true;
            var parsed=CommandParser.Parse(text,Array.Empty<SceneObject>());
            return !parsed.Verb.HasValue&&!parsed.HasUnknownWords&&!parsed.ConflictingVerbs
                &&(parsed.Number.HasValue||parsed.Unit.HasValue||parsed.Axis.HasValue||parsed.Shape.HasValue);
        }
    }
}

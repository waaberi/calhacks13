using System;
using System.Linq;
using SpatialModeling.VoiceCore;
using UnityEngine;

public static class VoiceCompositionChecks
{
    const string A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    static void Check(bool value, string detail) { if (!value) throw new Exception("VOICE_COMPOSITION: " + detail); }

    public static void Run()
    {
        DateTime now = DateTime.UtcNow;
        var s = new VoiceSession(new VoiceSessionOptions { AskHost = true }, () => now);
        s.SetObjects(new[] { new SceneObject(A, "Cube"), new SceneObject(B, "Sphere") });
        s.EnableComposition(true);
        string text = "add a cube then move it twenty centimeters along x then scale it down fifty percent";
        VoiceTurn t = s.Hear(new RecognitionResult(text, 1));
        Check(t.Command == null && t.Resolve?.Text == text, "whole chain goes to host, never partial Add");
        s.ResolveSent(t.Resolve, "request1");
        t = s.HostAnswered("request1", new VoiceCandidates(A, VoiceDecision.Clarify, "Step 2: select an object", 30, null, "target"));
        Check(s.CompositionQuestion != null && t.Prompts.Contains(Prompt.AskTarget), "missing target retained visibly");
        t = s.SetSelection(new[] { B });
        Check(t.Resolve?.Continuation == A && t.Resolve.TargetId == B, "controller selection resumes full plan with same token");
        s.ResolveSent(t.Resolve, "request2");
        t = s.HostAnswered("request2", new VoiceCandidates(B, VoiceDecision.Clarify, "Step 2: which axis", 30, null, "axis"));
        Check(t.Prompts.Contains(Prompt.AskAxis), "axis prompt");
        t = s.Hear(new RecognitionResult("x", 1));
        Check(t.Resolve?.Continuation == B && t.Command == null, "axis fragment resumes sequence, not standalone action");
        s.ResolveSent(t.Resolve, "request3");
        t = s.HostAnswered("request3", new VoiceCandidates(A, VoiceDecision.Run, null, 30,
            new[] { new VoiceCandidate(1, "Sequence", "voice.sequence", true, false, B) }));
        Check(t.Command?.Kind == CommandKind.Run && t.Command.TargetId == B && s.CompositionQuestion == null,
            "single resolved native request and exact host-bound target");

        t = s.Hear(new RecognitionResult("move it then delete it", 1));
        s.ResolveSent(t.Resolve, "delete");
        t = s.HostAnswered("delete", new VoiceCandidates(A, VoiceDecision.Run, null, 30,
            new[] { new VoiceCandidate(1, "Move Sphere; delete Sphere", "voice.sequence", true, true, B) }));
        Check(t.Command.RequiresConfirmation, "destructive sequence uses controller confirmation");

        foreach (string why in new[] { "cancel", "disconnect", "document", "timeout" })
        {
            s.EnableComposition(true);
            t = s.Hear(new RecognitionResult("colour it", 1)); s.ResolveSent(t.Resolve, why);
            s.HostAnswered(why, new VoiceCandidates(A, VoiceDecision.Clarify, "Which colour", 30, null, "colour"));
            if (why == "cancel") s.Cancel();
            else if (why == "disconnect") s.ConnectionLost();
            else if (why == "document") s.DocumentChanged();
            else { now = now.AddSeconds(31); s.Tick(); }
            Check(s.CompositionQuestion == null, "pending sequence invalidates on " + why);
        }
        s.EnableComposition(true);
        t = s.Hear(new RecognitionResult("add cube then teleport it", 1)); s.ResolveSent(t.Resolve, "bad");
        t = s.HostAnswered("bad", new VoiceCandidates(A, VoiceDecision.Reject, "Unsupported tail", 30, null));
        Check(t.Command == null && t.Resolve == null, "host rejection never falls back to partial Add");
        t = s.Hear(new RecognitionResult("add cube then colour it red", .1f));
        Check(t.Command == null && t.Resolve == null && t.Prompts.Contains(Prompt.LowConfidence), "low confidence cannot run chain");
        Check(VoiceCandidates.FromJson("{\"resolution\":\"" + A + "\",\"decision\":\"clarify\",\"reason\":\"Which colour\",\"expires_in\":30,\"missing\":\"colour\",\"candidates\":[]}").Missing == "colour", "wire clarification parser");
        var decodedResult = typeof(SpatialModeling.HostScene).Assembly.GetType("SpatialModeling.HostLink")
            .GetMethod("DecodeResult",System.Reflection.BindingFlags.Static|System.Reflection.BindingFlags.NonPublic)
            .Invoke(null,new object[]{Newtonsoft.Json.Linq.JObject.Parse("{\"op\":\"voice.run\",\"outcome\":\"applied\",\"selection\":{\"id\":\""+B+"\"}}"),"receipt"});
        Check((bool)decodedResult.GetType().GetField("SelectionSpecified").GetValue(decodedResult)
            && (string)decodedResult.GetType().GetField("SelectedId").GetValue(decodedResult)==B,"actual receipt decoder retains final selection");
        foreach (Prompt prompt in new[] { Prompt.AskDetails, Prompt.ConfirmSequence })
            Check(Resources.Load<AudioClip>(prompt.ClipResource) != null, "packaged audible prompt " + prompt.Id);
        Debug.Log("VOICE_COMPOSITION_CHECK PASS ordered host routing/selection continuation/axis memory/one native command/confirmation/cancel/expiry/document/disconnect/no partial fallback/audio");
    }

    public static void Windows()
    {
        Run();
        VoiceSelectionChecks.Windows();
        Debug.Log("VOICE_COMPOSITION_BUILD_RESULT Succeeded errors=0 cumulative_selection_P2_P1=True");
    }
}

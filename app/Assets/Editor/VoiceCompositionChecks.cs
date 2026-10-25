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
        t = s.Hear(new RecognitionResult("add cube and teleport it", 1));
        Check(t.Command == null && t.Resolve?.Composition == true && t.Resolve.Text == "add cube and teleport it",
            "unknown and-tail stays whole and opts into composition");
        s.ResolveSent(t.Resolve, "and-tail");
        t = s.HostAnswered("and-tail", new VoiceCandidates(A, VoiceDecision.Reject, "Unsupported tail", 30, null));
        Check(t.Command == null && t.Resolve == null, "unknown and-tail cannot become an executable prefix");
        t = s.Hear(new RecognitionResult("apply rotation and scale", 1));
        Check(t.Resolve?.Composition == true, "native semantic and phrase reaches the complete host planner");
        s.Cancel();
        Check(VoiceCandidates.FromJson("{\"resolution\":\"" + A + "\",\"decision\":\"clarify\",\"reason\":\"Which colour\",\"expires_in\":30,\"missing\":\"colour\",\"candidates\":[]}").Missing == "colour", "wire clarification parser");
        var decodedResult = typeof(SpatialModeling.HostScene).Assembly.GetType("SpatialModeling.HostLink")
            .GetMethod("DecodeResult",System.Reflection.BindingFlags.Static|System.Reflection.BindingFlags.NonPublic)
            .Invoke(null,new object[]{Newtonsoft.Json.Linq.JObject.Parse("{\"op\":\"voice.run\",\"outcome\":\"applied\",\"selection\":{\"id\":\""+B+"\"}}"),"receipt"});
        Check((bool)decodedResult.GetType().GetField("SelectionSpecified").GetValue(decodedResult)
            && (string)decodedResult.GetType().GetField("SelectedId").GetValue(decodedResult)==B,"actual receipt decoder retains final selection");
        foreach (Prompt prompt in new[] { Prompt.AskDetails, Prompt.ConfirmSequence })
            Check(Resources.Load<AudioClip>(prompt.ClipResource) != null, "packaged audible prompt " + prompt.Id);
        NativeResolveHandoff();
        ActualVoiceCancelDirectDraft();
        Debug.Log("VOICE_COMPOSITION_CHECK PASS ordered host routing/selection continuation/axis memory/one native command/confirmation/cancel/expiry/document/disconnect/no partial fallback/audio");
    }

    static void ActualVoiceCancelDirectDraft()
    {
        const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
        var fixtureType = typeof(DirectModelEditingChecks).GetNestedType("Fixture", System.Reflection.BindingFlags.NonPublic);
        var current = typeof(SpatialModeling.PreviewInteraction).GetProperty("Current").GetSetMethod(true);
        var previous = SpatialModeling.PreviewInteraction.Current;
        foreach (string stage in new[] { "local", "direct-handoff", "voice-handoff" })
        {
            var fixture = (IDisposable)Activator.CreateInstance(fixtureType, new object[] { "builtin.move", "OBJECT" });
            try
            {
                var host = (SpatialModeling.HostScene)fixtureType.GetField("Host").GetValue(fixture);
                var preview = (SpatialModeling.PreviewInteraction)fixtureType.GetField("Preview").GetValue(fixture);
                var direct = (SpatialModeling.DirectModelEditing)fixtureType.GetField("Direct").GetValue(fixture);
                var sent = (System.Collections.Generic.List<Newtonsoft.Json.Linq.JObject>)fixtureType.GetField("Sent").GetValue(fixture);
                current.Invoke(null, new object[] { preview });
                var voice = host.gameObject.AddComponent<SpatialModeling.VoiceUiAdapter>();
                typeof(SpatialModeling.VoiceUiAdapter).GetField("session", flags).SetValue(voice, new VoiceSession());
                int voiceExecutions = 0;
                if (stage == "voice-handoff") preview.HandoffNativeCommand(() => voiceExecutions++, _ => { });
                else
                {
                    if (stage == "direct-handoff") fixtureType.GetMethod("State").Invoke(fixture, new object[] { true });
                    fixtureType.GetMethod("Route").Invoke(fixture, new object[] { true, 0f, false });
                    fixtureType.GetMethod("Route").Invoke(fixture, new object[] { true, .04f, false });
                    Check(direct.Gesturing, "actual voice-cancel fixture has a direct gesture " + stage);
                }
                typeof(SpatialModeling.VoiceUiAdapter).GetMethod("CancelPressed", flags).Invoke(voice, null);
                Check(!direct.Gesturing, "production voice/Escape CancelPressed cancels local direct gesture " + stage);
                bool pending = typeof(SpatialModeling.PreviewInteraction).GetField("pendingNativeCommand", flags).GetValue(preview) != null;
                Check(pending == (stage == "voice-handoff"), "voice cancel removes only the direct-owned pending callback " + stage);
                if (stage != "local")
                    Check((bool)typeof(SpatialModeling.PreviewInteraction).GetField("endAfterRelease", flags).GetValue(preview),
                        "cancel retains ordered native input cleanup " + stage);
                typeof(SpatialModeling.PreviewInteraction).GetField("endAfterRelease", flags).SetValue(preview, false);
                fixtureType.GetMethod("State").Invoke(fixture, new object[] { false });
                typeof(SpatialModeling.PreviewInteraction).GetMethod("FlushNativeCommand", flags).Invoke(preview, null);
                fixtureType.GetMethod("Route").Invoke(fixture, new object[] { false, .04f, false });
                Check(!sent.Any(m => (string)m["type"] == "command" || (string)m["type"] == "lease.acquire"),
                    "late release/ACK after voice cancellation never submits a direct edit " + stage);
                Check(voiceExecutions == (stage == "voice-handoff" ? 1 : 0), "unrelated pending voice owner is preserved " + stage);
            }
            finally { current.Invoke(null, new object[] { previous }); fixture.Dispose(); }
        }
        Debug.Log("VOICE_DIRECT_CANCEL_CHECK PASS actual VoiceUiAdapter.CancelPressed/local-direct/queued-direct/late-release+ACK/no-mutation/cleanup+other-owner preserved");
    }

    // Exercise SendVoice itself against a private in-process loopback transport.
    // The existing common-UI fixture supplies the real native owner/ACK/state
    // lifecycle; no headset, interactive Blender, helper or OS input is used.
    static void NativeResolveHandoff()
    {
        const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
        var fixtureType = typeof(P25CommonUiChecks).GetNestedType("Fixture", System.Reflection.BindingFlags.NonPublic);
        foreach (string change in new[] { "none", "generation", "document" })
        {
            var fixture = (IDisposable)Activator.CreateInstance(fixtureType);
            var host = (SpatialModeling.HostScene)fixtureType.GetField("Host").GetValue(fixture);
            var preview = (SpatialModeling.PreviewInteraction)fixtureType.GetField("Preview").GetValue(fixture);
            var listener = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
            listener.Start();
            using var sender = new System.Net.Sockets.TcpClient();
            sender.Connect((System.Net.IPEndPoint)listener.LocalEndpoint);
            using var receiver = listener.AcceptTcpClient();
            listener.Stop();
            try
            {
                var linkType = typeof(SpatialModeling.HostScene).Assembly.GetType("SpatialModeling.HostLink");
                var link = System.Runtime.Serialization.FormatterServices.GetUninitializedObject(linkType);
                linkType.GetField("stream", flags).SetValue(link, sender.GetStream());
                linkType.GetField("writeLock", flags).SetValue(link, new object());
                typeof(SpatialModeling.HostScene).GetField("link", flags).SetValue(host, link);
                foreach (string field in new[] { "welcomed", "canEdit", "connected" })
                    typeof(SpatialModeling.HostScene).GetField(field, flags).SetValue(host, true);
                foreach (var identity in new[] { ("sessionId", "session"), ("hostEpoch", "host"),
                    ("welcomeDocumentId", "doc"), ("welcomeOpenEpoch", "open"), ("actorId", "actor") })
                    typeof(SpatialModeling.HostScene).GetField(identity.Item1, flags).SetValue(host, identity.Item2);
                var generations = (System.Collections.Generic.Dictionary<string,long>)typeof(SpatialModeling.HostScene).GetField("generations", flags).GetValue(host);
                generations[A] = 3;
                fixtureType.GetMethod("NativeReady").Invoke(fixture, new object[] { "OBJECT" });
                int failures = 0; host.RequestFailed += (re, code) => failures++;
                var payload = Newtonsoft.Json.Linq.JObject.Parse("{\"text\":\"colour it blue\",\"confidence\":1,\"composition\":true,\"target\":{\"id\":\""+A+"\",\"generation\":3}}");
                string id = host.SendVoice("voice.resolve", payload);
                Check(id != null && !receiver.GetStream().DataAvailable, "voice resolver waits for acknowledged release " + change);
                payload["text"] = "delete it"; // The queued intent must be immutable.
                typeof(SpatialModeling.PreviewInteraction).GetField("endAfterRelease", flags).SetValue(preview, false);
                typeof(SpatialModeling.PreviewInteraction).GetMethod("FlushNativeCommand", flags).Invoke(preview, null);
                Check(!receiver.GetStream().DataAvailable, "local release alone cannot resolve a voice plan " + change);
                if (change == "generation") generations[A] = 4;
                if (change == "document") typeof(SpatialModeling.HostScene).GetField("welcomeOpenEpoch", flags).SetValue(host, "changed");
                fixtureType.GetMethod("Fresh").Invoke(fixture, null);
                typeof(SpatialModeling.PreviewInteraction).GetMethod("FlushNativeCommand", flags).Invoke(preview, null);
                typeof(SpatialModeling.PreviewInteraction).GetMethod("FlushNativeCommand", flags).Invoke(preview, null);
                if (change == "none")
                {
                    Check(System.Threading.SpinWait.SpinUntil(() => receiver.GetStream().DataAvailable, 1000), "fresh released owner sends one resolve");
                    using var reader = new System.IO.StreamReader(receiver.GetStream());
                    var sent = Newtonsoft.Json.Linq.JObject.Parse(reader.ReadLine());
                    Check((string)sent["id"] == id && (string)sent["type"] == "voice.resolve"
                        && (string)sent["payload"]["text"] == "colour it blue" && failures == 0,
                        "production resolver retains stable request ID and frozen complete intent");
                    Check(!receiver.GetStream().DataAvailable, "voice resolve handoff is single-use");
                }
                else Check(failures == 1 && !receiver.GetStream().DataAvailable, "changed context refuses plan without sending " + change);
            }
            finally
            {
                typeof(SpatialModeling.HostScene).GetField("link", flags).SetValue(host, null);
                fixture.Dispose();
            }
        }
        Debug.Log("VOICE_RESOLVE_HANDOFF_CHECK PASS actual SendVoice/ACK+fresh-owner barrier/frozen whole intent/single send/session+generation refusal");
    }

    public static void Windows()
    {
        Run();
        VoiceSelectionChecks.Windows();
        Debug.Log("VOICE_COMPOSITION_BUILD_RESULT Succeeded errors=0 cumulative_selection_P2_P1=True");
    }
}

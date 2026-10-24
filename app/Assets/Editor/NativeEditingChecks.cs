using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using SpatialModeling;

// This same state machine runs in the Player and in the standalone regression runner.
public static class NativeEditingChecks
{
    const string Target = "11111111111111111111111111111111";
    static void Check(bool ok, string message) { if (!ok) throw new Exception("P3 native menu: " + message); }
    static JObject Message(string type, JObject p, string re = null) { var m = NativeEditSession.Envelope(type, p); if (re != null) m["re"] = re; return m; }
    static JObject Document(long revision = 1) => new JObject { ["id"] = "22222222222222222222222222222222", ["open_epoch"] = "33333333333333333333333333333333", ["revision"] = revision, ["dirty"] = false };
    static NativeEditSession Ready(List<JObject> sent)
    {
        var s = new NativeEditSession { Send = m => sent.Add((JObject)m.DeepClone()) };
        s.Receive(Message("welcome", new JObject { ["session_id"] = "44444444444444444444444444444444", ["host_epoch"] = "55555555555555555555555555555555", ["actor_id"] = "66666666666666666666666666666666", ["can_edit"] = true, ["document"] = Document() }));
        Snapshot(s);
        s.Select(Target);
        return s;
    }
    static void Snapshot(NativeEditSession s, long generation = 1)
    {
        s.Receive(Message("scene.snapshot", new JObject { ["document"] = Document(generation), ["objects"] = new JArray(new JObject { ["id"] = Target, ["name"] = "Native cube", ["generation"] = generation }), ["sketches"] = new JArray() }));
    }
    static void Grant(NativeEditSession s, List<JObject> sent)
    { s.Receive(Message("lease.granted", new JObject { ["lease"] = new JObject { ["lease_id"] = "77777777777777777777777777777777" } }, (string)sent[sent.Count - 1]["id"])); }
    public static void Run()
    {
        var sent = new List<JObject>(); var s = Ready(sent);
        Check(s.Ready && !s.SketchAvailable, "Sketch must stay disabled without real host capability");
        s.BeginDraft("object.move", new JObject { ["by"] = new JArray(0.01, 0, 0) }, true);
        Check(sent.Count == 0, "Local drafts must not lock or mutate Blender");
        s.Cancel(); Check(sent.Count == 0 && s.Draft == null, "Cancel draft is entirely local");
        s.BeginDraft("object.move", new JObject { ["by"] = new JArray(0.01, 0, 0) }, true);
        Snapshot(s, 2); // Native changed while the numeric draft stayed open.
        s.Apply(); Check((string)sent[0]["type"] == "lease.acquire", "Permission must precede native mutation");
        Grant(s, sent);
        var command = sent[1];
        Check((string)command["type"] == "command" && (long)command["payload"]["target"]["generation"] == 1, "A stale numeric draft must never silently target a newer generation");
        Check(Math.Abs((double)command["payload"]["args"]["by"][0] - 0.01) < 1e-9, "10mm must send 0.01 native meters");
        // A full native snapshot can precede result; it must not lose the pending request.
        Snapshot(s, 3);
        Check(s.Busy, "A scene snapshot before result is not native receipt confirmation");
        s.Receive(Message("result", new JObject { ["request_id"] = command["id"], ["outcome"] = "rejected", ["error"] = new JObject { ["code"] = "stale_revision", ["message"] = "Target changed; select it again" } }));
        Check(s.Notice == "Target changed; select it again" && !s.Busy, "Show native rejection without claiming success");
        Check((string)sent[2]["type"] == "lease.release" && (string)sent[2]["payload"]["lease_id"] != null && ((JObject)sent[2]["payload"]).Count == 1, "Release must match exact contract");
        sent.Clear(); s = Ready(sent);
        s.BeginDraft("object.delete", new JObject(), true); s.Apply(); s.Cancel(); Grant(s, sent);
        Check(sent.Count == 2 && (string)sent[1]["type"] == "lease.release", "Cancel while lease is in flight must release without sending a delete");
        sent.Clear(); s = Ready(sent); s.BeginDraft("object.delete", new JObject(), true); s.Apply();
        s.Timeout(); Grant(s, sent);
        Check(sent.Count == 2 && (string)sent[1]["type"] == "lease.release" && s.OutcomeUnknown, "A late permission after timeout must release without native mutation");
        sent.Clear(); s = Ready(sent); s.BeginDraft("object.delete", new JObject(), true); s.Apply();
        var lateRequest = (string)sent[0]["id"]; s.Timeout(); Snapshot(s);
        s.Receive(Message("lease.granted", new JObject { ["lease"] = new JObject { ["lease_id"] = "77777777777777777777777777777777" } }, lateRequest));
        Check(sent.Count == 2 && (string)sent[1]["type"] == "lease.release", "Snapshot recovery must not revive a timed-out pending command");
        sent.Clear(); s = Ready(sent); s.SceneCurrent = false;
        Check(!s.BeginDraft("object.delete", new JObject(), true) && sent.Count == 0, "Rejected or incomplete rendered scenes must never admit native mutation");
        sent.Clear(); s = Ready(sent); s.BeginDraft("object.rotate", new JObject { ["by"] = new JObject { ["axis"] = "Z", ["angle"] = Math.PI / 2 } }, true); s.Apply(); Grant(s, sent);
        var id = (string)sent[1]["id"];
        s.Receive(Message("result", new JObject { ["request_id"] = "other", ["outcome"] = "applied" }));
        Check(s.Busy, "Unrelated receipts must not complete our command");
        s.Timeout(); Check(s.OutcomeUnknown && !s.Ready && !s.Apply() && sent.Count == 2, "Timeout must stop edits without retry or early lease release during execution");
        s.Disconnect("test"); Snapshot(s); // Fresh reconnect will normally supply welcome first.
        Check(s.Ready && !s.OutcomeUnknown, "A fresh authoritative snapshot recovers unknown state");
        sent.Clear(); s = Ready(sent);
        s.Receive(Message("session.update", new JObject { ["participants"] = new JArray(), ["leases"] = new JArray(new JObject { ["mode"] = "shared", ["owner"] = new JObject { ["actor_id"] = "other", ["name"] = "Actual participant" }, ["targets"] = new JArray(Target) }) }));
        s.BeginDraft("object.delete", new JObject(), true);
        Check(!s.Apply() && sent.Count == 0 && s.Notice.Contains("Actual participant"), "Known conflicts must show actual owner and send no write");
        s.Select(Target); Check(s.SelectedId == Target && sent.Count == 0, "Selection must remain lock-free during conflicts");
        sent.Clear(); s = Ready(sent);
        Check(!s.BeginDraft("sketch.constrain", new JObject(), true) && sent.Count == 0, "Sketch tools must not target a generic object");
        string sketchId = "99999999999999999999999999999999";
        s.Sketches[sketchId] = new JObject { ["id"] = sketchId, ["name"] = "Native sketch", ["generation"] = 7 };
        s.Select(sketchId);
        Check(!s.BeginDraft("object.delete", new JObject(), true) && sent.Count == 0, "Generic object tools must not mutate a hidden sketch carrier");
        Check(s.BeginDraft("sketch.constrain", new JObject(), true) && (long)s.Draft["target"]["generation"] == 7,
            "Sketch drafts must capture the selected sketch generation");
    }
}

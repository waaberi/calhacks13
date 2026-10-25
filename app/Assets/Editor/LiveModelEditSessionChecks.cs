using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEngine;

// Exercises the actual client transport state machine without native input,
// network, a Player, Blender, or scene mutation.
public static class LiveModelEditSessionChecks
{
    static void Check(bool value, string message)
    { if (!value) throw new Exception("LIVE_MODEL_SESSION: " + message); }
    public static void Run()
    {
        OrderedUpdatesAndCommit(); Cancellation(); TimeoutAndOwnership();
        Debug.Log("LIVE_MODEL_SESSION_CHECK PASS lease/begin/cumulative-ACK/coalescing/one-commit/selection/early-cancel/no-replay/timeout/actor-echo");
    }
    static void OrderedUpdatesAndCommit()
    {
        var f = new Fixture(); f.Begin();
        Check(f.Parent.Busy && f.Live.Busy, "owned live flow excludes native/voice drafts immediately");
        f.Live.Update(new JObject { ["amount"] = 1 }); f.Grant(); f.Active();
        var first = f.Last("live.edit.update");
        f.Live.Update(new JObject { ["amount"] = 2 }); f.Live.Update(new JObject { ["amount"] = 3 });
        Check(f.Sent.Count(m => (string)m["type"] == "live.edit.update") == 1, "updates wait for the preceding native acknowledgment");
        f.State("updated", 1, (string)first["id"]);
        var second = f.Last("live.edit.update");
        Check((int)second["payload"]["parameters"]["amount"] == 3 && (int)second["payload"]["sequence"] == 2, "only newest cumulative parameters survive coalescing");
        f.Live.Commit(); Check(!f.Sent.Any(m => (string)m["type"] == "live.edit.commit"), "release waits for final update acknowledgment");
        f.State("updated", 2, (string)second["id"]);
        var commit = f.Last("live.edit.commit");
        Check((long)commit["payload"]["sequence"] == 2, "one final commit names last acknowledged native preview");
        f.State("committed", 2, (string)commit["id"]);
        Check(!f.Live.Busy && !f.Parent.Busy && (string)f.Live.AppliedSelection["id"] == Fixture.ObjectId, "actual terminal state releases busy ownership and publishes native selection");
        Check(f.Sent.Count(m => (string)m["type"] == "live.edit.commit") == 1 && f.Sent.Any(m => (string)m["type"] == "lease.release"), "one commit and ordinary lease release");
    }
    static void Cancellation()
    {
        var f = new Fixture(); f.Begin(); f.Live.Cancel("Released before permission"); f.Grant();
        Check(!f.Live.Busy && !f.Sent.Any(m => (string)m["type"] == "live.edit.begin"), "released gesture cannot replay after late permission");
        f = new Fixture(); f.Begin(); f.Grant(); f.Live.Cancel("Released before native begin acknowledgment"); f.Active();
        Check(!f.Sent.Any(m => (string)m["type"] == "live.edit.update") && f.Sent.Any(m => (string)m["type"] == "live.edit.cancel"), "late begin acknowledgment produces cleanup, never geometry replay");
        var cancel = f.Last("live.edit.cancel"); f.State("cancelled", 0, (string)cancel["id"]);
        Check(!f.Live.Busy && f.Live.Phase == "cancelled", "Cancel waits for actual native restoration");
    }
    static void TimeoutAndOwnership()
    {
        var f = new Fixture(); f.Begin(); f.Grant(); f.Active();
        f.Live.Update(new JObject { ["amount"] = 1 });
        f.Live.Timeout();
        Check(f.Live.Busy && f.Live.OutcomeUnknown && f.Sent.Any(m => (string)m["type"] == "live.edit.cancel"), "missing update acknowledgment requests ordered native rollback without falsely claiming completion");
        var cancel = f.Last("live.edit.cancel"); f.State("cancelled", 1, (string)cancel["id"]);
        Check(!f.Live.Busy && f.Live.OutcomeUnknown, "timeout requires a fresh scene even after native cleanup");
        f.Live.Receive(new JObject { ["type"] = "scene.snapshot", ["payload"] = new JObject() });
        Check(!f.Live.OutcomeUnknown, "fresh snapshot releases uncertain-outcome fence");
        f = new Fixture(); f.Begin(); f.Grant(); f.Active();
        var echo = new JObject { ["type"] = "scene.update", ["payload"] = new JObject { ["live_edit"] = new JObject { ["id"] = Fixture.EditId, ["actor_id"] = "actor", ["sequence"] = 1 } } };
        Check(f.Live.OwnsEcho(echo), "own server-issued live session identifies expected scene generations");
        echo["payload"]["live_edit"]["id"] = "foreign";
        Check(!f.Live.OwnsEcho(echo), "unrelated live echo cannot impersonate this native gesture");
        f.Live.Disconnect("Isolated disconnect");
        Check(!f.Live.Busy && !f.Parent.Busy && f.Live.OutcomeUnknown, "disconnect relinquishes local owner while server handles native rollback");
    }
    sealed class Fixture
    {
        public const string ObjectId = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", EditId = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        public readonly NativeEditSession Parent = new NativeEditSession();
        public readonly LiveModelEditSession Live = new LiveModelEditSession();
        public readonly List<JObject> Sent = new List<JObject>();
        public Fixture()
        {
            Parent.Send = message => Sent.Add((JObject)message.DeepClone());
            Parent.Receive(new JObject { ["type"] = "welcome", ["payload"] = new JObject {
                ["session_id"] = "session", ["host_epoch"] = "host", ["actor_id"] = "actor", ["can_edit"] = true,
                ["document"] = Document(), ["capabilities"] = new JObject { ["live_edit"] = true } } });
            Parent.Receive(new JObject { ["type"] = "scene.snapshot", ["payload"] = new JObject {
                ["document"] = Document(), ["objects"] = new JArray(new JObject { ["id"] = ObjectId, ["generation"] = 2, ["name"] = "Native target" }) } });
            Live.Configure(Parent);
        }
        static JObject Document() => new JObject { ["id"] = "doc", ["open_epoch"] = "open", ["revision"] = 2 };
        public void Begin() => Check(Live.Begin(new JObject { ["tool"] = "object.move", ["target_id"] = ObjectId },
            new JArray(new JObject { ["id"] = ObjectId, ["generation"] = 2 })), "current target begins native live ownership");
        public JObject Last(string type) => Sent.Last(message => (string)message["type"] == type);
        public void Grant() => Live.Receive(new JObject { ["type"] = "lease.granted", ["re"] = Last("lease.acquire")["id"],
            ["payload"] = new JObject { ["lease"] = new JObject { ["lease_id"] = "lease" } } });
        public void Active() => State("active", 0, (string)Last("live.edit.begin")["id"]);
        public void State(string phase, long sequence, string re)
        {
            var state = Parent.RequestIdentity; state["edit_session_id"] = EditId; state["phase"] = phase;
            state["sequence"] = sequence; state["revision"] = 2 + sequence;
            state["generations"] = new JObject { [ObjectId] = 2 + sequence };
            state["selection"] = new JObject { ["id"] = ObjectId }; state["notice"] = "Native live state " + phase;
            Live.Receive(new JObject { ["type"] = "live.edit.state", ["re"] = re, ["payload"] = state });
        }
    }
}

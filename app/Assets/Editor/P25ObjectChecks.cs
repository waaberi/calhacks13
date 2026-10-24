using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using SpatialModeling;

// Pure managed checks: no Unity objects, native input, network or Blender process.
public static class P25ObjectChecks
{
    const string A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const string B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const string Sketch = "cccccccccccccccccccccccccccccccc";
    const string Created = "dddddddddddddddddddddddddddddddd";
    const string Document = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
    const string Epoch = "ffffffffffffffffffffffffffffffff";

    static void Check(bool ok, string reason)
    { if (!ok) throw new Exception("P2.5 object tools: " + reason); }

    static JObject Object(string id, string name, long generation = 3) =>
        new JObject { ["id"] = id, ["name"] = name, ["generation"] = generation };

    static JObject Doc(string id = Document, string open = Epoch, long revision = 1) =>
        new JObject { ["id"] = id, ["open_epoch"] = open, ["revision"] = revision,
            ["units"] = new JObject { ["scale_length"] = .001, ["length_unit"] = "MILLIMETERS" } };

    static JObject Welcome(string document = Document, string open = Epoch) =>
        new JObject { ["session_id"] = Guid.NewGuid().ToString("N"), ["host_epoch"] = Guid.NewGuid().ToString("N"),
            ["actor_id"] = Guid.NewGuid().ToString("N"), ["can_edit"] = true,
            ["document"] = Doc(document, open), ["capabilities"] = new JObject { ["sketch"] = false } };

    static NativeEditSession Ready(out List<JObject> sent)
    {
        var session = new NativeEditSession();
        var messages = new List<JObject>(); session.Send = msg => messages.Add((JObject)msg.DeepClone());
        session.Receive(NativeEditSession.Envelope("welcome", Welcome()));
        session.Receive(NativeEditSession.Envelope("scene.snapshot", new JObject { ["document"] = Doc(),
            ["objects"] = new JArray(Object(B, "Beta"), Object(A, "Alpha")),
            ["sketches"] = new JArray(Object(Sketch, "Old sketch")) }));
        session.Select(Sketch);
        sent = messages; return session;
    }

    static JObject Deliver(NativeEditSession session, NativeObjectTools tools, string type, JObject payload, string re = null)
    {
        var message = NativeEditSession.Envelope(type, payload);
        if (re != null) message["re"] = re;
        session.Receive(message); tools.Observe(message); return message;
    }

    static JObject Receipt(string request, string op = "object.add", string outcome = "applied", string created = Created) =>
        new JObject { ["request_id"] = request, ["op"] = op, ["outcome"] = outcome,
            ["created"] = new JArray(created), ["summary"] = "Native receipt" };

    static string SubmitCreate(NativeEditSession session, NativeObjectTools tools, List<JObject> sent)
    {
        Check(tools.Stage("add.cube"), "create draft is supported");
        Check(session.Apply(), "existing session applies the draft");
        string acquire = (string)sent[sent.Count - 1]["id"];
        Deliver(session, tools, "lease.granted", new JObject { ["lease"] = new JObject {
            ["lease_id"] = Guid.NewGuid().ToString("N") } }, acquire);
        Check((string)sent[sent.Count - 1]["type"] == "command", "shared session sends only after its lease grant");
        return session.LastSubmittedId;
    }

    public static void Run(Action<string> report)
    {
        SelectionAndRemoval(); UnitsAndActions(); CreationReceipts(); ResetAndConflicts();
        report("P25_OBJECT_TOOLS_CHECK PASS explicit-object/removed-target/delayed-own-create/unrelated-receipt/session-reset/metres/radians/uniform-scale/draft-only/shared-permission; no native GUI or OS input");
    }

    static void SelectionAndRemoval()
    {
        var session = Ready(out var sent);
        using (var tools = new NativeObjectTools(session))
        {
            Check(tools.TargetId == "" && !tools.Stage("move.x+"), "an old selected sketch cannot become an implicit object target");
            Check(tools.SelectRelative(1) && tools.TargetId == A && tools.TargetLabel == "Alpha", "explicit next selects the first name-sorted native object");
            Check(tools.SelectRelative(1) && tools.TargetId == B, "next advances to the second object");
            Check(tools.SelectRelative(1) && tools.TargetId == A, "next wraps deterministically");
            Check(tools.SelectRelative(-1) && tools.TargetId == B, "previous wraps deterministically");
            Check(!tools.SelectRelative(0), "no-op direction cannot invent a selection");
            Deliver(session, tools, "scene.update", new JObject { ["document"] = Doc(revision: 2), ["removed"] = new JArray(B) });
            Check(tools.TargetId == B && !tools.Stage("delete"), "removed explicit UUID is preserved and cannot fall back to another object");
            Deliver(session, tools, "scene.update", new JObject { ["objects"] = new JArray(Object(B, "Restored Beta")) });
            Check(!tools.Stage("move.z+"), "a removed UUID reappearing does not silently re-arm editing");
            Check(tools.SelectRelative(1) && tools.TargetId == A && tools.Stage("move.x+"), "an explicit fresh selection restores object editing");
            Check((string)session.Draft["target"]?["id"] == A, "draft captures only the chosen current target");
            Check(sent.Count == 0, "selection and staging never send or acquire permissions");
        }
    }

    static void UnitsAndActions()
    {
        var session = Ready(out var sent);
        using (var tools = new NativeObjectTools(session))
        {
            tools.SelectRelative(1);
            foreach (string axis in new[] { "x", "y", "z" }) foreach (string sign in new[] { "+", "-" })
            {
                Check(tools.Stage("move." + axis + sign), "all signed native-axis move actions stage");
                var by = (JArray)session.Draft["args"]["by"];
                int index = "xyz".IndexOf(axis, StringComparison.Ordinal);
                for (int i = 0; i < 3; i++) Check(Math.Abs((double)by[i] - (i == index ? (sign == "+" ? .01 : -.01) : 0)) < 1e-12,
                    "world metres are not multiplied by Blender display unit scale or Unity axes");
                Check(tools.Stage("turn." + axis + sign), "all signed native-axis rotations stage");
                Check((string)session.Draft["args"]["by"]["axis"] == axis.ToUpperInvariant(), "rotation names the native world axis");
                Check(Math.Abs((double)session.Draft["args"]["by"]["angle"] - (sign == "+" ? 1 : -1) * Math.PI / 4) < 1e-12,
                    "45 degree turn is encoded in native radians");
            }
            Check(tools.Stage("scale.up"), "uniform scale-up stages");
            foreach (var factor in (JArray)session.Draft["args"]["by"]) Check(Math.Abs((double)factor - 1.1) < 1e-12, "scale-up is 1.1 on every native axis");
            Check(tools.Stage("scale.down"), "uniform scale-down stages");
            foreach (var factor in (JArray)session.Draft["args"]["by"]) Check(Math.Abs((double)factor - 1 / 1.1) < 1e-12, "scale-down is the reciprocal on every axis");
            Check(tools.Stage("delete") && !((JObject)session.Draft["args"]).HasValues, "delete stages empty arguments with explicit generation");
            foreach (string primitive in new[] { "cube", "sphere", "cylinder" })
            {
                Check(tools.Stage("add." + primitive), "supported primitive stages without a selected target");
                Check(session.Draft["target"] == null && (string)session.Draft["args"]["primitive"] == primitive, "add uses the shared targetless object.add command");
                foreach (var value in (JArray)session.Draft["args"]["location"]) Check((double)value == 0, "primitive is located at native world origin");
                foreach (var value in (JArray)session.Draft["args"]["dimensions"]) Check((double)value == .05, "size is 50mm bounding extent; cylinder diameter equals depth");
            }
            double move = tools.MoveStepMeters, size = tools.PrimitiveSizeMeters; int turn = tools.TurnDegrees;
            for (int i = 0; i < 3; i++) { tools.CycleMoveStep(); tools.CycleTurnDegrees(); tools.CyclePrimitiveSize(); }
            Check(tools.MoveStepMeters == move && tools.TurnDegrees == turn && tools.PrimitiveSizeMeters == size, "all three step lists wrap");
            tools.CycleMoveStep(); tools.CycleTurnDegrees(); tools.CyclePrimitiveSize();
            Check(tools.MoveStepMeters == .1 && tools.TurnDegrees == 90 && tools.PrimitiveSizeMeters == .1, "cycles expose the stated next steps");
            Check(!tools.Stage("move.w+") && !tools.Stage("turn.x++") && !tools.Stage("history.undo"), "unknown actions cannot create a new authority/history path");
            Check(sent.Count == 0, "every button above produced drafts only");
        }
    }

    static void CreationReceipts()
    {
        var session = Ready(out var sent);
        using (var tools = new NativeObjectTools(session))
        {
            tools.SelectRelative(1);
            string id = SubmitCreate(session, tools, sent);
            Deliver(session, tools, "result", Receipt(Guid.NewGuid().ToString("N")));
            Check(tools.TargetId == A, "an unrelated receipt cannot retarget the controller");
            Deliver(session, tools, "result", Receipt(id, outcome: "pending"));
            Check(tools.TargetId == A, "pending creation is not a created-object receipt");
            Deliver(session, tools, "result", Receipt(id));
            Check(tools.TargetId == Created && !tools.Stage("move.y+"), "own applied UUID latches before its scene record without fallback");
            Deliver(session, tools, "scene.update", new JObject { ["objects"] = new JArray(Object(Created, "Created cube", 9)) });
            Check(tools.Stage("move.y+") && (string)session.Draft["target"]["id"] == Created && (long)session.Draft["target"]["generation"] == 9,
                "the delayed exact record unlocks editing with its real generation");
            tools.Reset();
            Check(tools.TargetId == "", "explicit reset clears only local target/correlation");
            // An object.add from another UI is a real session receipt, but this
            // controller did not stage it and must not adopt its created target.
            Check(tools.Stage("add.sphere"), "an unapplied own add draft can be replaced by another UI");
            Check(session.BeginDraft("object.add", new JObject { ["primitive"] = "cube", ["location"] = new JArray(0, 0, 0),
                ["dimensions"] = new JArray(.1, .1, .1) }, false) && session.Apply(), "another UI can use the same native session");
            string acquire = (string)sent[sent.Count - 1]["id"];
            Deliver(session, tools, "lease.granted", new JObject { ["lease"] = new JObject { ["lease_id"] = Guid.NewGuid().ToString("N") } }, acquire);
            Deliver(session, tools, "result", Receipt(session.LastSubmittedId));
            Check(tools.TargetId == "", "even another UI's accepted object.add receipt cannot retarget this controller");
        }
        session = Ready(out sent);
        using (var tools = new NativeObjectTools(session))
        {
            string id = SubmitCreate(session, tools, sent);
            Deliver(session, tools, "result", Receipt(id));
            Deliver(session, tools, "scene.update", new JObject { ["removed"] = new JArray(Created) });
            Deliver(session, tools, "scene.update", new JObject { ["objects"] = new JArray(Object(Created, "Restored created object")) });
            Check(tools.TargetId == Created && !tools.Stage("delete"),
                "an authoritative removal before the first created-object record still requires explicit reselection");
        }
    }

    static void ResetAndConflicts()
    {
        var session = Ready(out var sent);
        using (var tools = new NativeObjectTools(session))
        {
            tools.SelectRelative(1);
            Deliver(session, tools, "session.update", new JObject { ["leases"] = new JArray(new JObject {
                ["mode"] = "exclusive", ["targets"] = new JArray(), ["owner"] = new JObject { ["actor_id"] = "other", ["name"] = "Other editor" } }) });
            Check(tools.Stage("move.x+"), "conflicting ownership still allows inspection/draft staging");
            Check(!session.Apply() && sent.Count == 0, "only the shared session enforces conflicting permission without a command send");
            Deliver(session, tools, "welcome", Welcome());
            Check(tools.TargetId == "" && !tools.Stage("move.x+"), "welcome clears targets despite old dictionaries awaiting snapshot");
            Deliver(session, tools, "scene.snapshot", new JObject { ["document"] = session.Document.DeepClone(), ["objects"] = new JArray(Object(A, "Alpha")) });
            tools.SelectRelative(1);
            session.Disconnect("test disconnect");
            Check(tools.TargetId == "", "direct session disconnect clears the local target before another raw message");
        }
        session = Ready(out sent);
        using (var tools = new NativeObjectTools(session))
        {
            tools.SelectRelative(1);
            Deliver(session, tools, "scene.update", new JObject { ["document"] = Doc(Guid.NewGuid().ToString("N")) });
            Check(tools.TargetId == "" && !tools.Stage("delete"), "document/open epoch mismatch clears the local object target");
        }
    }
}

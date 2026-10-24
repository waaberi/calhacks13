using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using SpatialModeling;

// Runs against the actual compiled implementation. No Unity initialization,
// desktop input, sockets, Blender, Player or XR runtime is used.
public static class ManagedChecks
{
    static string root;
    const string SketchId = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    static void Check(bool value, string why)
    {
        if (!value) throw new Exception("P25_MANAGED: " + why);
    }

    static NativeEditSession Session(out List<JObject> sent)
    {
        var session = new NativeEditSession();
        var output = new List<JObject>();
        sent = output;
        session.Send = value => output.Add((JObject)value.DeepClone());
        Check(!session.BeginDraft("sketch.create", new JObject(), false), "no edit before welcome/snapshot");
        var welcome = JObject.Parse(File.ReadAllText(Path.Combine(root, "contracts/examples/welcome.json")));
        welcome["payload"]["capabilities"] = new JObject { ["sketch"] = true };
        session.Receive(welcome);
        Snapshot(session);
        return session;
    }

    static void Snapshot(NativeEditSession session)
    {
        var snapshot = JObject.Parse(File.ReadAllText(Path.Combine(root, "contracts/examples/scene.snapshot.json")));
        snapshot["payload"]["sketches"] = new JArray(new JObject {
            ["id"] = SketchId, ["name"] = "Native sketch", ["generation"] = 7,
            ["entities"] = new JArray(), ["constraints"] = new JArray()
        });
        session.Receive(snapshot);
        session.Select(SketchId);
    }

    static bool Draft(NativeEditSession session) => session.BeginDraft("sketch.add_line",
        new JObject { ["start"] = new JArray(0, 0), ["end"] = new JArray(.1, .06) }, true);

    static void Grant(NativeEditSession session, string request) => session.Receive(new JObject {
        ["type"] = "lease.granted", ["re"] = request,
        ["payload"] = new JObject { ["lease"] = new JObject { ["lease_id"] = "test-permission" } }
    });

    static void SessionChecks()
    {
        var session = Session(out var sent);
        session.SceneCurrent = false;
        Check(!Draft(session) && sent.Count == 0, "stale rendered scene prevents drafting or wire mutation");
        session.SceneCurrent = true;
        Check(Draft(session) && sent.Count == 0, "controller draft alone never emits a command");
        session.Cancel();
        Check(sent.Count == 0 && session.Draft == null, "draft cancel does not touch native history");
        Check(Draft(session) && session.Apply(), "valid draft requests native permission");
        Check(sent.Count == 1 && (string)sent[0]["type"] == "lease.acquire", "lease is obtained before mutation");
        Grant(session, "unrelated-reply");
        Check(!sent.Any(m => (string)m["type"] == "command"), "unrelated lease cannot authorize a command");
        var acquireId = (string)sent[0]["id"];
        var generation = (int)session.Draft["target"]["generation"];
        var revision = (long)session.Draft["base_revision"];
        // A native update during permission acquisition must not silently retarget the intent.
        session.Sketches[SketchId]["generation"] = 99;
        session.Document["revision"] = 999;
        Grant(session, acquireId);
        var command = sent.Single(m => (string)m["type"] == "command");
        Check((int)command["payload"]["target"]["generation"] == generation
            && (long)command["payload"]["base_revision"] == revision,
            "native command preserves original draft generation and revision for host validation");
        Check((string)command["payload"]["lease"] == "test-permission", "command carries granted permission");
        Check(session.Sketches[SketchId]["entities"].Count() == 0, "no optimistic native geometry before receipt");
        int beforeCancel = sent.Count;
        session.Cancel();
        Check(sent.Count == beforeCancel && session.Busy, "cancel cannot pretend to roll back an executing native transaction");
        session.Timeout();
        Check(session.OutcomeUnknown && !Draft(session), "missing native receipt freezes further edits");
        Check(sent.Count == beforeCancel, "timeout never blindly retries a native command");
        session.Receive(new JObject { ["type"] = "result", ["payload"] = new JObject {
            ["request_id"] = (string)command["id"], ["outcome"] = "applied", ["summary"] = "Line created" } });
        Check(sent.Count(m => (string)m["type"] == "command") == 1
            && sent.Any(m => (string)m["type"] == "lease.release"), "late receipt releases permission without repeating mutation");
        Check(!Draft(session), "late receipt alone does not replace required fresh snapshot");
        Snapshot(session);
        Check(Draft(session), "fresh authoritative snapshot recovers unknown outcome");

        session = Session(out sent);
        Check(Draft(session) && session.Apply(), "cancel acquisition setup");
        acquireId = (string)sent[0]["id"];
        session.Cancel();
        Grant(session, acquireId);
        Check(!sent.Any(m => (string)m["type"] == "command")
            && sent.Any(m => (string)m["type"] == "lease.release"), "cancelled acquisition releases late grant without native mutation");

        session = Session(out sent);
        Check(Draft(session) && session.Apply(), "stale acquisition setup");
        acquireId = (string)sent[0]["id"];
        session.SceneCurrent = false;
        Grant(session, acquireId);
        Check(!sent.Any(m => (string)m["type"] == "command")
            && sent.Any(m => (string)m["type"] == "lease.release"), "tracking/scene loss before grant prevents mutation");

        session = Session(out sent);
        session.Receive(new JObject { ["type"] = "session.update", ["payload"] = new JObject {
            ["leases"] = new JArray(new JObject { ["mode"] = "exclusive",
                ["owner"] = new JObject { ["actor_id"] = "another-editor", ["name"] = "Other editor" } }) } });
        Check(Draft(session) && !session.Apply() && sent.Count == 0,
            "other editor's exclusive permission blocks commands before acquisition");
        Console.WriteLine("P25_NATIVE_SESSION_CHECK PASS draft/lease/receipt/cancel/stale/unknown/recovery/ownership; native execution not exercised");
    }

    public static int Main(string[] args)
    {
        try
        {
            root = Path.GetFullPath(args[0]);
            P25Checks.RunMapping(Console.WriteLine);
            P25Checks.RunTransport(Console.WriteLine);
            P25Checks.RunInputProtocol(Console.WriteLine);
            P25Checks.RunTargets(Console.WriteLine);
            SessionChecks();
            Console.WriteLine("P25_MANAGED_CHECKS PASS actual compiled implementation; runtime acceptance=False");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}

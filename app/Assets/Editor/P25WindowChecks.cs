using System;
using Newtonsoft.Json.Linq;
using SpatialModeling;

// Pure identity/authority checks. No Unity objects, sockets or desktop APIs.
public static class P25WindowChecks
{
    static void Check(bool ok, string why) { if (!ok) throw new Exception("P25_WINDOW: " + why); }
    public static JObject Document() => new JObject { ["id"] = "doc", ["open_epoch"] = "open", ["revision"] = 7 };
    public static void Handshake(NativeEditSession session, string connection = "native-session", bool editable = true)
    {
        session.Receive(NativeEditSession.Envelope("welcome", new JObject {
            ["session_id"] = connection, ["host_epoch"] = "host", ["actor_id"] = "actor", ["can_edit"] = editable,
            ["document"] = Document(), ["capabilities"] = new JObject { ["sketch"] = false } }));
        session.Receive(NativeEditSession.Envelope("scene.snapshot", new JObject { ["document"] = Document(),
            ["objects"] = new JArray(), ["sketches"] = new JArray() }));
    }
    public static JObject Window(long hwnd = 100, long pid = 42, string title = "Blender", string kind = "blender") => new JObject {
        ["hwnd"] = hwnd, ["pid"] = pid, ["title"] = title, ["kind"] = kind,
        ["window_class"] = kind == "blender" ? "GHOST_WindowClass" : "#32770",
        ["owner_hwnd"] = hwnd == 100 ? 0 : 100, ["parent_hwnd"] = 0, ["menu_owner_hwnd"] = 0,
        ["blender_hwnd"] = 100, ["blender_pid"] = 42, ["blender_process_started"] = 111,
        ["input_process_started"] = pid == 42 ? 111 : 222
    };
    public static JObject Helper(string session = "helper-A", long hwnd = 100, long pid = 42, long generation = 7) => new JObject {
        ["enabled"] = true, ["ready"] = true, ["focused"] = true, ["release_error"] = false,
        ["session"] = session, ["token"] = "fixture-token", ["next_seq"] = 1, ["helper_pid"] = 9000,
        ["capture_instance"] = "capture-instance", ["window_scope"] = "explicit-picker-scope",
        ["capture_generation"] = generation, ["capture_geometry"] = "geometry-" + hwnd, ["reason"] = "",
        ["selection"] = Window(hwnd, pid, hwnd == 100 ? "Blender" : "File dialog", hwnd == 100 ? "blender" : "dialog"),
        ["geometry"] = new JObject { ["blender_process_started"] = 111 },
        ["image"] = new JObject { ["width"] = 800, ["height"] = 600 }, ["frame"] = generation,
        ["windows"] = new JArray(Window(), Window(200, 84, "File dialog", "dialog"), Window(201, 84, "Nested dialog", "dialog"))
    };
    public static JObject Native(NativeEditSession session)
    {
        var state = session.RequestIdentity;
        state["process_id"] = 42; state["input_allowed"] = true; state["ui_session_id"] = "native-ui-token";
        state["ui_owner"] = new JObject { ["actor_id"] = session.ActorId };
        state["ui_ending"] = false; state["mode"] = "OBJECT"; state["modal_active"] = false; state["available"] = false;
        return state;
    }

    public static void Run(Action<string> report)
    {
        Families(); Authority(); Protocol();
        report("P25_WINDOW_CHECK PASS rooted cross-process dialogs/family+helper lifetime/confirmed lease authority/session+document revocation/strict consumed geometry; no native capture or OS input");
    }
    static void Families()
    {
        var root = Helper(); var dialog = Helper("helper-B", 200, 84, 8);
        Check(PreviewWindowState.RootPid(dialog) == 42 && PreviewWindowState.RootStamp(dialog) == 111,
            "broker target PID is distinct from confirmed Blender root PID and lifetime");
        Check(PreviewWindowState.CanContinue(root, dialog, 42), "trusted family can change target HWND, target PID, capture generation and helper input session");
        var waiting = (JObject)dialog.DeepClone(); waiting["ready"] = false; waiting["focused"] = false; waiting["reason"] = "capture_unavailable";
        Check(PreviewWindowState.CanContinue(root, waiting, 42), "frame wait preserves reservation identity without admitting raw input");
        foreach (string change in new[] { "scope", "capture", "token", "pid", "stamp", "disabled", "release" })
        {
            var bad = (JObject)dialog.DeepClone();
            if (change == "scope") bad["window_scope"] = "other-picker";
            if (change == "capture") bad["capture_instance"] = "restarted-helper";
            if (change == "token") bad["token"] = "changed-token";
            if (change == "pid") bad["selection"]["blender_pid"] = 99;
            if (change == "stamp") bad["selection"]["blender_process_started"] = 112;
            if (change == "disabled") bad["enabled"] = false;
            if (change == "release") bad["release_error"] = true;
            Check(!PreviewWindowState.CanContinue(root, bad, 42), "family continuation refuses " + change);
        }
        var legacy = Helper(); ((JObject)legacy["selection"]).Remove("blender_pid"); ((JObject)legacy["selection"]).Remove("blender_process_started"); legacy.Remove("geometry"); legacy.Remove("window_scope");
        Check(PreviewWindowState.RootPid(legacy) == 42 && !PreviewWindowState.CanContinue(legacy, legacy, 42), "legacy PID fallback does not manufacture stamped continuity");
        Check(PreviewWindowState.RootPid(null) == 0 && PreviewWindowState.RootStamp(null) == 0
            && !PreviewWindowState.CanContinue(root, dialog, 0), "missing identity never authorizes continuation");
    }
    static void Authority()
    {
        var session = new NativeEditSession(); Handshake(session);
        var native = Native(session); var helper = Helper(); var original = (JObject)helper.DeepClone();
        var authority = new NativePreviewAuthority();
        Check(!authority.Matches(session, native, helper), "fresh helper identity alone is not a confirmed native grant");
        Check(authority.Capture(session, native, helper) && authority.ProcessId == 42, "only owned current native grant and verified helper root seed authority");
        helper["window_scope"] = "caller-mutated";
        Check(authority.Matches(session, native, original), "captured helper identity is defensively cloned");
        Check(authority.Matches(session, native, Helper("helper-B", 200, 84, 8)), "latched native reservation admits authenticated brokered dialog identity");
        foreach (string change in new[] { "allowed", "ending", "owner", "token", "pid", "document", "host" })
        {
            var bad = (JObject)native.DeepClone();
            if (change == "allowed") bad["input_allowed"] = false;
            if (change == "ending") bad["ui_ending"] = true;
            if (change == "owner") bad["ui_owner"] = new JObject { ["actor_id"] = "other" };
            if (change == "token") bad["ui_session_id"] = "other-native-token";
            if (change == "pid") bad["process_id"] = 99;
            if (change == "document") bad["document_id"] = "other-document";
            if (change == "host") bad["host_epoch"] = "other-host";
            Check(!authority.Matches(session, bad, original), "native authority revocation cannot be hidden by helper identity " + change);
        }
        session.SceneCurrent = false; Check(!authority.Matches(session, native, original), "stale accepted scene invalidates retained permission"); session.SceneCurrent = true;
        var notReady = (JObject)original.DeepClone(); notReady["ready"] = false;
        Check(!authority.Capture(session, native, notReady) && authority.ProcessId == 0 && !authority.Matches(session, native, original), "failed recapture clears previous authority");
        Check(authority.Capture(session, native, original), "fresh authority can be captured again");
        Handshake(session, "new-native-session"); Check(!authority.Matches(session, Native(session), original), "native connection identity change cannot retain old permission");
        var readonlySession = new NativeEditSession(); Handshake(readonlySession, editable: false);
        Check(!authority.Capture(readonlySession, Native(readonlySession), original), "read-only participant cannot capture raw UI permission");
        Handshake(session); Check(authority.Capture(session, Native(session), original), "editable native handshake can capture permission");
        session.Disconnect("fixture"); Check(!authority.Matches(session, native, original), "disconnect revokes the latch without waiting for tool telemetry");
        authority.Clear(); Check(authority.ProcessId == 0, "explicit clear removes remembered native process");
    }
    static void Protocol()
    {
        Check(PreviewInputProtocol.TryState(Helper().ToString(), out _), "full rooted helper state decodes");
        foreach (JToken badGeometry in new JToken[] { new JArray(), new JValue("bad"), new JObject { ["blender_process_started"] = "bad" }, new JObject { ["blender_process_started"] = true }, new JObject { ["blender_process_started"] = 0 } })
        {
            var bad = Helper(); bad["geometry"] = badGeometry;
            Check(!PreviewInputProtocol.TryState(bad.ToString(), out _), "consumed root geometry fallback must have strict JSON types");
        }
        var fallback = Helper(); ((JObject)fallback["selection"]).Remove("blender_process_started");
        Check(PreviewInputProtocol.TryState(fallback.ToString(), out var parsed) && PreviewWindowState.RootStamp(parsed) == 111, "validated geometry fallback supplies root lifetime");
        var malformed = Helper(); malformed["selection"]["blender_pid"] = true;
        Check(!PreviewInputProtocol.TryState(malformed.ToString(), out _), "root PID is an integer, never boolean");
        Check(PreviewInputProtocol.TryState("{\"enabled\":false,\"ready\":false,\"reason\":\"input_disabled\"}", out _), "capture-only default remains compatible and authority-free");
    }
}

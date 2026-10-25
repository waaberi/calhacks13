using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Threading;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEditor;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR;

// Actual chooser, state admission and HTTP coroutines with inactive owners.
// No OnEnable, native windows, desktop input, Player, InputSystem device or XR.
public static class P25WindowUiChecks
{
    static readonly BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static object Get(object target, string name) => target.GetType().GetField(name, Private).GetValue(target);
    static void Set(object target, string name, object value) => target.GetType().GetField(name, Private).SetValue(target, value);
    static object Invoke(object target, string name, params object[] args) => target.GetType().GetMethod(name, Private).Invoke(target, args);
    static void Property(object target, string name, object value) => target.GetType().GetProperty(name).GetSetMethod(true).Invoke(target, new[] { value });
    static void Check(bool ok, string why) { if (!ok) throw new Exception("P25_WINDOW_UI: " + why); }
    public static void Run()
    {
        Chooser(); SelectionSequence(); Handoff(); Revocation(); InputIndicator(); ControllerControls(); WorkspaceRouting();
        Debug.Log("P25_WINDOW_UI_CHECK PASS actual chooser/pages/stale-choice/bounded-refresh/no-image-recovery/current-sequence/stamped-handoff/lease-retention/typed-staleness/mode-exit/overlay; actual OS popup capture unverified");
    }

    static void ControllerControls()
    {
        using var f = new Fixture();
        var keyboardButton = f.Button("Keyboard");
        var buttonPoint = keyboardButton.transform.position;
        var buttonRay = new Ray(buttonPoint - Vector3.forward * 2, Vector3.forward);
        f.Preview.RouteControllerHand(XRNode.RightHand, buttonRay, false, false, Vector2.zero, 3, out _, false);
        Check(f.Preview.RouteControllerHand(XRNode.RightHand, buttonRay, true, false, Vector2.zero, 3, out _, false)
            && (bool)Get(f.Preview, "keyboardShown") && keyboardButton.GetComponentInChildren<Text>().text.Contains("ON")
            && keyboardButton.GetComponent<GlassControl>().PressActive && keyboardButton.GetComponent<GlassControl>().Selected, "actual trigger ray opens keyboard and visibly acknowledges press plus persistent ON state");
        f.Preview.RouteControllerHand(XRNode.RightHand, buttonRay, true, false, Vector2.zero, 3, out _, false);
        Check((bool)Get(f.Preview, "keyboardShown"), "held trigger never repeatedly toggles a control");
        f.Preview.RouteControllerHand(XRNode.RightHand, buttonRay, false, false, Vector2.zero, 3, out _, false);
        f.Click("Keyboard"); f.Tick(); f.Events.Clear();
        Check(!(bool)Get(f.Preview, "keyboardShown"), "second fresh click closes keyboard");
        var ray = new Ray(f.Image.transform.position - Vector3.forward * 2, Vector3.forward);
        void Route(bool trigger, bool grip, bool stick, Vector2 axis) => f.Preview.RouteControllerHand(XRNode.RightHand, ray, trigger, grip, axis, 3, out _, stick);
        Route(false, false, false, Vector2.zero); Route(true, false, false, Vector2.zero); Route(false, false, false, Vector2.zero);
        Check(f.Events.Any(e => (string)e["type"] == "button" && (string)e["button"] == "left" && (string)e["action"] == "down")
            && f.Events.Any(e => (string)e["button"] == "left" && (string)e["action"] == "up"), "front trigger maps to left down/up through real RawImage ray routing");
        f.Events.Clear();
        Check(!f.Preview.RouteControllerHand(XRNode.RightHand, ray, false, true, Vector2.zero, 3, out _, false) && f.Events.Count == 0,
            "unlocked side grip remains P2 arrangement input");
        Route(false, false, false, Vector2.zero);
        var position = f.Screen.Placement.position; var rotation = f.Screen.Placement.rotation;
        f.Click("Lock screen position");
        Check(f.Screen.PositionLocked && !BlenderScreen.CanGrabScreen(true) && BlenderScreen.CanGrabScreen(false)
            && f.Screen.Placement.position == position && f.Screen.Placement.rotation == rotation,
            "explicit lock disables screen grabbing without writing its pose; default unlocked movement remains available");
        Check(f.Preview.RouteControllerHand(XRNode.RightHand, ray, false, true, Vector2.zero, 3, out _, false),
            "locked side-grip native route is consumed before WorkspaceInteraction can start a screen grab");
        Route(false, false, false, Vector2.zero);
        Check(f.Events.Any(e => (string)e["button"] == "right" && (string)e["action"] == "down")
            && f.Events.Any(e => (string)e["button"] == "right" && (string)e["action"] == "up"), "locked side grip maps to right down/up");
        f.Events.Clear(); Route(false, false, true, Vector2.right); Route(false, false, true, Vector2.up); Route(false, false, false, Vector2.zero);
        Check(f.Events.Any(e => (string)e["key"] == "SHIFT" && (string)e["action"] == "down")
            && f.Events.Any(e => (string)e["button"] == "middle" && (string)e["action"] == "down")
            && f.Events.Any(e => (string)e["button"] == "middle" && (string)e["action"] == "up")
            && f.Events.Any(e => (string)e["key"] == "SHIFT" && (string)e["action"] == "up")
            && !f.Events.Any(e => (string)e["type"] == "scroll"), "hold-stick pan balances temporary Shift/middle and cannot also send zoom scroll");
        f.Events.Clear(); Set(f.Preview, "nextScroll", 0f); Route(false, false, false, Vector2.up);
        Check(f.Events.Any(e => (string)e["type"] == "scroll"), "stick tilt sends wheel only while pointing at Blender");
        f.Events.Clear(); Route(false, false, true, Vector2.zero); f.Preview.TrackingLost(XRNode.RightHand); f.Tick();
        Check(f.Events.Any(e => (string)e["type"] == "release") && !(bool)Get(f.Preview, "mouseHeld") && !(bool)Get(f.Preview, "panShift")
            && (bool)Get(f.Preview, "endAfterRelease") && f.Sent.Count == 0, "tracking interruption releases temporary pan input and retains native lease through cleanup ACK");
        Debug.Log("P225_CONTROLLER_UI_CHECK PASS actual_ray_button_feedback_toggle_edges_lock_pose_front_left_side_right_stick_pan_scroll_tracking_cleanup");
    }

    static void WorkspaceRouting()
    {
        using var f = new Fixture();
        Set(f.Host, "root", f.Host.transform);
        var interaction = f.Host.gameObject.AddComponent<WorkspaceInteraction>();
        Set(interaction, "scene", f.Host); Set(interaction, "screen", f.Screen);
        var handType = typeof(WorkspaceInteraction).GetNestedType("Hand", BindingFlags.NonPublic);
        var hand = Activator.CreateInstance(handType, true);
        handType.GetField("node").SetValue(hand, XRNode.RightHand);
        handType.GetField("armed").SetValue(hand, true);
        var ray = new Ray(f.Image.transform.position - Vector3.forward * 2, Vector3.forward);
        var route = typeof(WorkspaceInteraction).GetMethod("RouteHand", Private);
        void Route(bool grip, bool trigger) => route.Invoke(interaction, new object[] { hand, null,
            new Pose(ray.origin, Quaternion.identity), ray, grip, trigger, grip, trigger, Vector2.up, false });
        f.Click("Lock screen position"); f.Events.Clear();
        handType.GetField("target").SetValue(hand, f.Host.transform);
        Route(true, true);
        Check(f.Events.Count == 0 && !f.Sent.Any(m => (string)m["type"] == "command"),
            "holding a workspace object over the locked image cannot also right-click or drag Blender");
        handType.GetField("target").SetValue(hand, null);
        handType.GetField("stickDown").SetValue(hand, true);
        Route(false, false);
        Check(f.Events.Any(e => (string)e["button"] == "middle" && (string)e["action"] == "down")
            && f.Events.Any(e => (string)e["key"] == "SHIFT" && (string)e["action"] == "down")
            && !f.Events.Any(e => (string)e["type"] == "scroll"),
            "production workspace routing forwards held stick state for pan without wheel events");
        handType.GetField("stickDown").SetValue(hand, false); Route(false, false);
        Check(f.Events.Any(e => (string)e["button"] == "middle" && (string)e["action"] == "up")
            && f.Events.Any(e => (string)e["key"] == "SHIFT" && (string)e["action"] == "up"),
            "production workspace routing balances pan releases");
        Debug.Log("P225_P3_ROUTING_CHECK PASS workspace_hold_excludes_native_click actual_stick_state balanced_pan no_wheel");
    }

    static void InputIndicator()
    {
        using var f = new Fixture();
        var button = f.Button("Focus Blender");
        string Label() => button.GetComponentInChildren<Text>().text;
        void Refresh() => Invoke(f.Preview, "RefreshInputIndicator");
        Refresh();
        Check(Label() == "Input ON · turn off" && button.GetComponent<Image>().color.g > button.GetComponent<Image>().color.r,
            "actual toggle is green and ON only after complete admission");
        f.State["focused"] = false; Refresh();
        Check(Label() == "Enabling… · cancel", "requested input cannot look ON without desktop focus");
        f.State["focused"] = true; Property(f.Screen, "DisplayedCaptureGeometry", "stale-geometry"); Refresh();
        Check(Label() == "Enabling… · cancel", "focused input cannot look ON with a mismatched displayed frame");
        f.Frame(f.State); Set(f.Preview, "inputEnabled", false); Set(f.Preview, "focusRequested", true); Refresh();
        Check(Label() == "Enabling… · cancel", "permission request is visibly pending");
        Set(f.Preview, "focusRequested", false); Set(f.Preview, "lastInputFailure", "test denied"); Refresh();
        Check(Label() == "Input blocked · retry" && button.GetComponent<Image>().color.r > button.GetComponent<Image>().color.g,
            "blocked activation remains visibly distinct from OFF and ON");
        Set(f.Preview, "lastInputFailure", ""); Refresh();
        Check(Label() == "Input OFF · enable", "idle mode shows OFF");
        Set(f.Preview, "inputEnabled", true); f.Click("Focus Blender");
        Check(Label() == "Releasing input…" && !button.interactable && (bool)Get(f.Preview, "endAfterRelease")
            && f.Sent.Count == 0, "clicking ON toggles off while retaining the native lease through release acknowledgement");
    }

    sealed class Fixture : IDisposable
    {
        readonly GameObject owner, display;
        readonly PreviewInteraction previousCurrent;
        public readonly HostScene Host;
        public readonly BlenderScreen Screen;
        public readonly RawImage Image;
        public readonly PreviewSpatialDrawing Drawing;
        public readonly PreviewInteraction Preview;
        public readonly List<JObject> Sent = new List<JObject>();
        public NativeEditSession Session => Drawing.Session;
        public Queue<JObject> Events => (Queue<JObject>)Get(Preview, "events");
        public NativePreviewAuthority Authority => (NativePreviewAuthority)Get(Preview, "windowAuthority");
        public PreviewInputTransportState Transport => (PreviewInputTransportState)Get(Preview, "transport");
        public JObject State => (JObject)Get(Preview, "state");
        public List<Button> Buttons => (List<Button>)Get(Preview, "buttons");
        public List<Button> WindowButtons => (List<Button>)Get(Preview, "windowButtons");
        public RectTransform Panel => (RectTransform)Get(Preview, "windowPanel");
        public Fixture(JObject initial = null)
        {
            previousCurrent = PreviewInteraction.Current;
            owner = new GameObject("P25 inactive window UI fixture"); owner.SetActive(false);
            Host = owner.AddComponent<HostScene>(); SetHost(true); Set(Host, "placed", true);
            Screen = owner.AddComponent<BlenderScreen>(); Drawing = owner.AddComponent<PreviewSpatialDrawing>(); Drawing.Initialize(Host);
            P25WindowChecks.Handshake(Session); Session.Send = message => Sent.Add((JObject)message.DeepClone());
            Preview = owner.AddComponent<PreviewInteraction>(); Property(Preview, "Drawing", Drawing);
            typeof(PreviewInteraction).GetProperty("Current").GetSetMethod(true).Invoke(null, new object[] { Preview });
            Set(Preview, "scene", Host); Set(Preview, "screen", Screen); Set(Preview, "nextHeartbeat", float.PositiveInfinity);
            display = new GameObject("P25 actual window chooser canvas", typeof(RectTransform), typeof(Canvas));
            display.GetComponent<Canvas>().renderMode = RenderMode.WorldSpace;
            display.transform.position = Vector3.forward * 2; display.transform.localScale = Vector3.one * .001f;
            var imageObject = new GameObject("P25 previous window image", typeof(RectTransform), typeof(RawImage)); imageObject.transform.SetParent(display.transform, false);
            Image = imageObject.GetComponent<RawImage>(); Image.rectTransform.sizeDelta = new Vector2(1800, 1100);
            Set(Screen, "canvasObject", display); Set(Screen, "image", Image);
            var unowned = P25WindowChecks.Native(Session); unowned["input_allowed"] = false; unowned["ui_owner"] = null; unowned["ui_session_id"] = "";
            Drawing.SetNativeState(unowned); Apply(initial ?? P25WindowChecks.Helper());
            Drawing.SetNativeState(P25WindowChecks.Native(Session));
            Check(Drawing.IsNativeUiOwned && Authority.Capture(Session, Drawing.NativeState, State), "fixture captures actual confirmed fresh lease authority before telemetry ages");
            Frame(State); Set(Preview, "inputEnabled", true); Set(Preview, "ownedCaptureInstance", (string)State["capture_instance"]);
            Invoke(Preview, "BuildControls"); Check((bool)Invoke(Preview, "Ready"), "fixture satisfies actual rooted frame/owner admission");
        }
        public void SetHost(bool current) => Set(Host, "status", Enum.Parse(typeof(HostScene).GetNestedType("Status", BindingFlags.NonPublic), current ? "Connected" : "Disconnected"));
        public void Apply(JObject state) => Invoke(Preview, "ApplyInputState", state);
        public void Frame(JObject state)
        {
            Property(Screen, "DisplayedCaptureInstance", (string)state["capture_instance"]);
            Property(Screen, "DisplayedSelectionGeneration", (long)state["capture_generation"]);
            Property(Screen, "DisplayedCaptureGeometry", (string)state["capture_geometry"]); Image.enabled = true;
        }
        public void Stale() => Set(Drawing, "stateAt", float.NegativeInfinity);
        public void Tick() => Invoke(Preview, "Update");
        public Button Button(string name) => Buttons.Single(button => button.name == name);
        public void Click(string name) => Button(name).onClick.Invoke();
        public void Open() { Click("Windows / dialogs"); Tick(); Check(Panel.gameObject.activeInHierarchy, "actual windows button opens chooser"); }
        public void Dirty()
        {
            Events.Enqueue(new JObject { ["type"] = "key", ["key"] = "G", ["action"] = "press" });
            Set(Preview, "mouseHeld", true); ((HashSet<string>)Get(Preview, "modifiers")).Add("CTRL");
            Set(Preview, "editorPointSet", true); Set(Preview, "pendingPointer", new JObject { ["type"] = "pointer", ["x"] = .5, ["y"] = .5 });
        }
        public void Cleared()
        {
            Check(Events.Count == 0 && !(bool)Get(Preview, "mouseHeld") && ((HashSet<string>)Get(Preview, "modifiers")).Count == 0
                && !(bool)Get(Preview, "editorPointSet") && Get(Preview, "pendingPointer") == null && (bool)Get(Preview, "triggerWasDown"),
                "handoff discards old operations, held state and editor anchor; trigger must release before another press");
        }
        public void Dispose()
        {
            Drawing.Numeric.Dispose(); Drawing.ObjectTools.Dispose();
            typeof(PreviewInteraction).GetProperty("Current").GetSetMethod(true).Invoke(null, new object[] { previousCurrent });
            UnityEngine.Object.DestroyImmediate(display); UnityEngine.Object.DestroyImmediate(owner);
        }
    }

    static void Chooser()
    {
        using var f = new Fixture();
        var list = new JArray(); list.Add(P25WindowChecks.Window());
        for (int i = 0; i < 8; i++) list.Add(P25WindowChecks.Window(200 + i, 84, i == 0 ? "<b>Same title</b>" : "Same title", "dialog"));
        f.State["windows"] = list; f.Image.enabled = false; f.Open();
        Check(f.Panel.gameObject.activeInHierarchy && f.WindowButtons.Count == 6 && PreviewInteraction.BlocksDesktopShortcuts,
            "recovery chooser remains reachable without image and blocks desktop shortcuts");
        Check(!f.Button("Window 200").GetComponentInChildren<Text>().supportRichText
            && f.Button("Window 200").GetComponentInChildren<Text>().text.Contains("<b>Same title</b>"), "actual window titles remain literal text");
        int controls = f.Buttons.Count - f.WindowButtons.Count;
        f.Click("Next windows"); Check(f.WindowButtons.Count == 3 && (int)Get(f.Preview, "windowPage") == 1, "next window page exposes remaining explicit HWND choices");
        f.Click("Previous windows"); Check(f.WindowButtons.Count == 6 && (int)Get(f.Preview, "windowPage") == 0, "previous window page returns to first six");
        var staleClick = f.Button("Window 200").onClick;
        for (int i = 0; i < 12; i++)
        {
            f.State["windows"] = new JArray(((JArray)f.State["windows"]).Reverse().Select(value => value.DeepClone()));
            Invoke(f.Preview, "RefreshWindows");
            Check(f.WindowButtons.Count == 6 && f.Buttons.Count == controls + 6, "repeated window list refresh prunes old tracked buttons");
        }
        f.State["windows"] = new JArray(P25WindowChecks.Window()); Invoke(f.Preview, "RefreshWindows");
        f.Events.Clear(); staleClick.Invoke(); Check(f.Events.Count == 0, "late stale chooser callback revalidates current list instead of selecting a removed dialog");
        var gap = f.Panel.TransformPoint(new Vector3(0, -210, 0)); var ray = new Ray(new Vector3(gap.x, gap.y, 0), Vector3.forward);
        Check(f.Preview.RouteHand(XRNode.RightHand, ray, false, false, Vector2.zero, 3, out var distance)
            && Math.Abs(distance - f.Panel.position.z) < .00001 && f.Events.Count == 0, "chooser gap consumes ray without video or click-through");
        Check(!f.Preview.RouteHand(XRNode.RightHand, ray, false, false, Vector2.zero, 1, out _), "nearer arrangement target occludes chooser");
        Check(!f.Preview.RouteHand(XRNode.RightHand, ray, false, true, Vector2.zero, 3, out _)
            && !f.Preview.RouteHand(XRNode.LeftHand, ray, false, false, Vector2.zero, 3, out _), "grip and other hand keep existing routes");
        f.Click("Close windows"); f.Tick(); Check(!f.Panel.gameObject.activeInHierarchy, "actual chooser close hides the overlay");
    }
    static void SelectionSequence()
    {
        using (var f = new Fixture())
        {
            f.Transport.TakeSequence(); f.Transport.TakeSequence(); Check(f.Transport.NextSequence == 3 && (long)f.State["next_seq"] == 1, "fixture has advanced authoritative transport beyond cached GET");
            f.Open(); f.Click("Window 200");
            Check(f.Transport.Synchronized && f.Transport.NextSequence == 3 && f.Events.Count == 1
                && (string)f.Events.Peek()["type"] == "select_window" && (long)f.Events.Peek()["hwnd"] == 200,
                "actual brokered-dialog button retains the live next sequence, never cached state.next_seq");
            Check((bool)Get(f.Preview, "windowResuming") && (long)Get(f.Preview, "awaitedWindow") == 200, "explicit choice records exact expected HWND");
        }
        using (var f = new Fixture(P25WindowChecks.Helper("helper-A", 200, 84)))
        {
            f.Open(); f.Click("Back to Blender"); Check(f.Events.Count == 1 && (long)f.Events.Peek()["hwnd"] == 100, "Back to Blender chooses verified root handle from brokered dialog");
        }
        using (var f = new Fixture())
        {
            var foreign = P25WindowChecks.Window(900, 99); foreign["blender_pid"] = 99;
            ((JArray)f.State["windows"]).Add(foreign); f.Open(); f.Click("Window 900"); Check(f.Events.Count == 0, "foreign-root chooser item cannot enqueue a native selection");
        }
        using (var f = new Fixture())
        {
            f.State["focused"] = false; f.Open(); f.Click("Window 100");
            Check(f.Events.Count == 1 && (string)f.Events.Peek()["type"] == "select_window" && (long)f.Events.Peek()["hwnd"] == 100,
                "choosing the current unfocused root invokes real selection/focus recovery rather than closing as a no-op");
        }
    }
    static void Handoff()
    {
        using var f = new Fixture(); f.Stale();
        Check(!f.Drawing.NativeStateCurrent && (bool)Invoke(f.Preview, "Ready"), "confirmed raw UI reservation survives only tool telemetry age on same verified root");
        f.Click("Enter"); Check(f.Events.Count == 1 && (string)f.Events.Peek()["key"] == "ENTER", "actual Enter can finish same-window file browser while tool telemetry is stale");
        f.Events.Clear();
        f.Click("Keyboard"); f.Tick();
        foreach (string key in new[] { "C", "V" })
        {
            f.Click("CTRL"); f.Click(key.ToLowerInvariant()); f.Click("CTRL"); var chord = f.Events.ToArray();
            Check(chord.Length == 3 && (string)chord[0]["key"] == "CTRL" && (string)chord[0]["action"] == "down"
                && (string)chord[1]["key"] == key && (string)chord[1]["action"] == "press"
                && (string)chord[2]["key"] == "CTRL" && (string)chord[2]["action"] == "up",
                "actual clipboard control remains a balanced raw chord in stale-tool dialog context " + key);
            f.Events.Clear();
        }
        Check(!f.Drawing.ApplyObjectAction("add.cube") && !f.Drawing.LoadNumeric("add.cube") && !f.Drawing.TryAim(new Ray(Vector3.zero, Vector3.forward), out _)
            && f.Sent.Count == 0, "latched raw authority does not grant typed model/numeric/spatial admission");
        f.Dirty(); var dialog = P25WindowChecks.Helper("helper-B", 200, 84, 8); f.Apply(dialog); f.Cleared();
        Check((bool)Get(f.Preview, "windowResuming") && !(bool)Get(f.Preview, "inputEnabled") && !(bool)Get(f.Preview, "endAfterRelease")
            && f.Authority.ProcessId == 42, "same rooted dialog change retains native reservation without enabling old image input");
        f.Tick(); Check(f.Events.Count == 0, "old displayed generation cannot admit cleanup/resume for new dialog");
        f.Frame(dialog); f.Tick(); Check(f.Events.Count == 1 && (string)f.Events.Peek()["type"] == "release" && !(bool)Get(f.Preview, "inputEnabled"),
            "matching new displayed frame only queues cleanup; exact HTTP acknowledgement remains required");
    }
    static void Revocation()
    {
        foreach (string change in new[] { "scope", "capture", "token", "birth", "root", "release" })
        {
            using var f = new Fixture(); f.Stale(); var bad = P25WindowChecks.Helper("helper-B", 200, 84, 8);
            if (change == "scope") bad["window_scope"] = "other";
            if (change == "capture") bad["capture_instance"] = "restarted";
            if (change == "token") bad["token"] = "other";
            if (change == "birth") bad["selection"]["blender_process_started"] = 112;
            if (change == "root") bad["selection"]["blender_pid"] = 99;
            if (change == "release") bad["release_error"] = true;
            f.Apply(bad);
            Check((bool)Get(f.Preview, "endAfterRelease") && !((bool)Get(f.Preview, "inputEnabled")) && f.Authority.ProcessId == 0,
                "untrusted helper handoff invalidates authority and requires full cleanup " + change);
        }
        using (var f = new Fixture())
        {
            f.Stale(); f.SetHost(false); Check(f.Session.SceneCurrent && !(bool)Invoke(f.Preview, "Ready"), "raw latch checks accepted host scene directly before Drawing.Update can catch up");
            f.Tick(); f.SetHost(true); Check(f.Authority.ProcessId == 0 && !(bool)Invoke(f.Preview, "Ready"), "disconnect/suspend cannot revive authority merely when host status returns");
        }
        foreach (string button in new[] { "Draw in VR" })
        {
            using var f = new Fixture(); f.Stale(); Invoke(f.Preview, "AwaitWindowState", "fixture handoff"); f.Click(button);
            Check((bool)Get(f.Preview, "endAfterRelease") && !(bool)Get(f.Preview, "windowResuming") && f.Authority.ProcessId == 0,
                "mode exit from stale-tool dialog handoff requests ordered native cleanup " + button);
        }
        using (var f = new Fixture())
        {
            Set(f.Preview, "awaitedWindow", 999L); Invoke(f.Preview, "AwaitWindowState", "new automatic handoff");
            Check((long)Get(f.Preview, "awaitedWindow") == 0, "new automatic handoff cannot inherit failed explicit choice HWND");
        }
    }

    // -batchmode -nographics -executeMethod P25WindowUiChecks.RunHttp (no -quit).
    static readonly Stack<IEnumerator> routines = new Stack<IEnumerator>();
    static readonly JArray cases = new JArray();
    static object waiting;
    static double deadline;
    static string output, previousPort;
    public static void RunHttp()
    {
        output = Environment.GetEnvironmentVariable("CALHACKS_P25_WINDOW_HTTP_RESULTS");
        Check(!string.IsNullOrEmpty(output) && Path.IsPathRooted(output) && !File.Exists(output), "supply new absolute window HTTP results path");
        for (var dir = new DirectoryInfo(Path.GetDirectoryName(output)); dir != null; dir = dir.Parent)
            Check(!File.Exists(Path.Combine(dir.FullName, ".git")) && !Directory.Exists(Path.Combine(dir.FullName, ".git"))
                && !dir.Name.StartsWith("OneDrive", StringComparison.OrdinalIgnoreCase), "window HTTP evidence remains outside Git and OneDrive");
        Check(routines.Count == 0, "one window HTTP suite at a time"); cases.Clear(); waiting = null;
        previousPort = Environment.GetEnvironmentVariable("CALHACKS_CAPTURE_PORT"); deadline = EditorApplication.timeSinceStartup + 60;
        routines.Push(HttpSuite()); EditorApplication.update += TickHttp;
    }
    static IEnumerator HttpSuite()
    {
        yield return HttpHandoff(true); yield return HttpHandoff(false);
        yield return HttpChoice(false); yield return HttpChoice(true); yield return HttpChoice(false, 100);
        yield return HttpFocusDenied(); yield return HttpBusy();
    }
    static void TickHttp()
    {
        try
        {
            Check(EditorApplication.timeSinceStartup < deadline, "bounded window HTTP suite timed out");
            if (waiting is AsyncOperation operation && !operation.isDone) return;
            if (waiting is CustomYieldInstruction custom && custom.keepWaiting) return;
            waiting = null;
            if (routines.Count == 0) { FinishHttp(null); return; }
            var routine = routines.Peek();
            if (!routine.MoveNext()) { (routines.Pop() as IDisposable)?.Dispose(); return; }
            if (routine.Current is IEnumerator nested && !(nested is CustomYieldInstruction)) routines.Push(nested); else waiting = routine.Current;
        }
        catch (Exception error) { FinishHttp(error); }
    }
    static void FinishHttp(Exception error)
    {
        EditorApplication.update -= TickHttp;
        while (routines.Count > 0) { try { (routines.Pop() as IDisposable)?.Dispose(); } catch (Exception cleanup) { if (error == null) error = cleanup; } }
        Environment.SetEnvironmentVariable("CALHACKS_CAPTURE_PORT", previousPort);
        File.WriteAllText(output, new JObject { ["passed"] = error == null, ["cases"] = cases,
            ["transport"] = "actual ReadState/ApplyInputState/SendEvents UnityWebRequest; synthetic root/dialog/frame records only",
            ["actual_os_popup_capture_verified"] = false, ["native_or_player_launched"] = false, ["desktop_input_injected"] = false,
            ["physical_acceptance"] = false, ["error"] = error?.ToString() }.ToString());
        if (error == null) Debug.Log("P25_WINDOW_HTTP_CHECK PASS cases=5 trusted root/dialog/nested/parent/root, chooser current sequence/current-window recovery/focus refusal and invalid ACK ordered cleanup; actual OS popup capture unverified");
        else Debug.LogError(error);
        EditorApplication.Exit(error == null ? 0 : 1);
    }
    static IEnumerator Drive(IEnumerator actual, Func<bool> done)
    {
        double until = EditorApplication.timeSinceStartup + 10;
        try
        {
            while (!done()) { Check(EditorApplication.timeSinceStartup < until && actual.MoveNext(), "production window coroutine reaches its bounded checkpoint"); yield return actual.Current; }
        }
        finally { (actual as IDisposable)?.Dispose(); }
    }
    static IEnumerator HttpHandoff(bool valid)
    {
        using var server = new FakeServer(valid); Environment.SetEnvironmentVariable("CALHACKS_CAPTURE_PORT", server.Port.ToString());
        using var f = new Fixture(); f.Stale();
        long[] targets = valid ? new long[] { 200, 201, 200, 100 } : new long[] { 200 };
        for (int index = 0; index < targets.Length; index++)
        {
            long hwnd = targets[index]; var next = P25WindowChecks.Helper("helper-" + (index + 1), hwnd, hwnd == 100 ? 42 : 84, 8 + index);
            server.State(next); f.Dirty();
            yield return Drive((IEnumerator)Invoke(f.Preview, "ReadState"), () => (string)Get(f.Preview, "session") == (string)next["session"] && !(bool)Get(f.Preview, "readingState"));
            f.Cleared(); f.Tick(); Check(f.Events.Count == 0 && !(bool)Get(f.Preview, "inputEnabled"), "actual reader waits for displayed dialog frame instead of replaying old input");
            f.Frame(next); f.Tick(); Check(f.Events.Count == 1 && (string)f.Events.Peek()["type"] == "release", "only fresh-frame cleanup is queued before resume");
            int beforePosts = server.Posts;
            yield return Drive((IEnumerator)Invoke(f.Preview, "SendEvents"), () => server.Posts > beforePosts && !(bool)Get(f.Preview, "sendingEvent"));
            Check(server.Error == null && server.Kinds.All(kind => kind == "release") && f.Sent.Count == 0, "only idempotent cleanup reaches fake HTTP; native reservation is not ended or reacquired");
            if (valid) Check((bool)Get(f.Preview, "inputEnabled") && !(bool)Get(f.Preview, "windowResuming") && f.Authority.ProcessId == 42,
                "real exact release ACK resumes raw input on the new family frame");
            else
            {
                Check(!(bool)Get(f.Preview, "inputEnabled") && (bool)Get(f.Preview, "endAfterRelease") && f.Authority.ProcessId == 0,
                    "HTTP200 without exact ACK cannot resume a window handoff and retains ordered cleanup owner");
                Check(f.Sent.Count == 0, "invalid window-release ACK cannot end native reservation early");
                yield return Drive((IEnumerator)Invoke(f.Preview, "ReadState"), () => f.Transport.Synchronized && !(bool)Get(f.Preview, "readingState"));
                server.Acknowledge(true); f.Tick();
                Check(f.Events.Count == 1 && (string)f.Events.Peek()["type"] == "release" && f.Sent.Count == 0, "fresh authoritative GET schedules only cleanup before native UI end");
                int cleanupPosts = server.Posts;
                yield return Drive((IEnumerator)Invoke(f.Preview, "SendEvents"), () => server.Posts > cleanupPosts && !(bool)Get(f.Preview, "sendingEvent"));
                Check(f.Sent.Count == 1 && (string)f.Sent[0]["type"] == "preview.ui.end" && !(bool)Get(f.Preview, "inputEnabled")
                    && f.Drawing.NativeUiTransitionPending, "only a later exact release ACK ends native reservation; dialog input remains disabled");
            }
        }
        cases.Add(new JObject { ["name"] = valid ? "root_dialog_nested_parent_root" : "invalid_release_ack_blocks_handoff", ["transitions"] = targets.Length, ["passed"] = true });
    }
    static IEnumerator HttpChoice(bool failFocus, long hwnd = 200)
    {
        using var server = new FakeServer(true, failFocus); Environment.SetEnvironmentVariable("CALHACKS_CAPTURE_PORT", server.Port.ToString());
        using var f = new Fixture(); f.Stale(); f.Transport.TakeSequence(); f.Transport.TakeSequence();
        if (hwnd == 100) f.State["focused"] = false;
        var old = (JObject)f.State.DeepClone(); old["next_seq"] = 3; server.State(old);
        var dialog = P25WindowChecks.Helper("chosen-dialog", hwnd, hwnd == 100 ? 42 : 84, 8);
        if (!failFocus) server.Selects(dialog);
        f.Open(); f.Click("Window " + hwnd);
        yield return Drive((IEnumerator)Invoke(f.Preview, "SendEvents"), () => server.Posts == 1 && !(bool)Get(f.Preview, "sendingEvent"));
        Check(server.Error == null && server.Requests.TryPeek(out var selection) && (string)selection["type"] == "select_window"
            && (long)selection["seq"] == 3 && (long)selection["hwnd"] == hwnd && (string)selection["session"] == "helper-A", "actual chooser POST uses live old helper sequence rather than cached GET");
        Check(!(bool)Get(f.Preview, "inputEnabled") && f.Sent.Count == 0, "selection acknowledgement cannot itself admit input or end/reacquire native lease");
        if (failFocus)
        {
            Check(!f.Transport.Synchronized && (bool)Get(f.Preview, "windowResuming"), "failed native focus has unknown barrier and no blind selection retry");
            yield return Drive((IEnumerator)Invoke(f.Preview, "ReadState"), () => f.Transport.Synchronized && !(bool)Get(f.Preview, "readingState"));
            f.Tick();
            Check(f.Transport.NextSequence == 4 && f.Events.Count == 0 && server.Posts == 1 && !(bool)Get(f.Preview, "inputEnabled"),
                "authoritative GET resolves consumed failed selection without resuming wrong root window or replaying action");
        }
        else
        {
            yield return Drive((IEnumerator)Invoke(f.Preview, "ReadState"), () => (string)Get(f.Preview, "session") == "chosen-dialog" && !(bool)Get(f.Preview, "readingState"));
            f.Tick(); Check(f.Events.Count == 0, "chosen dialog still waits for matching new pixels");
            f.Frame(dialog); f.Tick();
            yield return Drive((IEnumerator)Invoke(f.Preview, "SendEvents"), () => server.Posts == 2 && !(bool)Get(f.Preview, "sendingEvent"));
            Check(server.Error == null && server.Kinds.SequenceEqual(new[] { "select_window", "release" })
                && (bool)Get(f.Preview, "inputEnabled") && !(bool)Get(f.Preview, "windowResuming"),
                "actual chooser completes new-session/frame cleanup before resuming focused dialog input");
        }
        cases.Add(new JObject { ["name"] = failFocus ? "explicit_choice_focus_refused_no_replay" : hwnd == 100 ? "explicit_current_unfocused_window_recovery"
            : "explicit_choice_current_sequence_then_frame_ack", ["passed"] = true });
    }
    static IEnumerator HttpFocusDenied()
    {
        using var server = new FakeServer(true, true);
        Environment.SetEnvironmentVariable("CALHACKS_CAPTURE_PORT", server.Port.ToString());
        using var f = new Fixture();
        f.State["focused"] = false; server.State(f.State);
        f.Events.Enqueue(new JObject { ["type"] = "focus" });
        yield return Drive((IEnumerator)Invoke(f.Preview, "SendEvents"), () => server.Posts == 1 && !(bool)Get(f.Preview, "sendingEvent"));
        Check(!(bool)Get(f.Preview, "windowResuming") && !(bool)Get(f.Preview, "inputEnabled")
            && (bool)Get(f.Preview, "endAfterRelease") && f.Sent.Count == 0,
            "focus denial stops admission and preserves native ownership until release ACK; it is not a dialog transition");
        Check(f.Preview.Notice.Contains("Windows did not activate Blender"), "foreground denial explains the actual failure");
        yield return Drive((IEnumerator)Invoke(f.Preview, "ReadState"), () => f.Transport.Synchronized && !(bool)Get(f.Preview, "readingState"));
        Check(f.Preview.Notice.Contains("Windows did not activate Blender") && server.Posts == 1,
            "later helper GET cannot overwrite the focus error with generic frame-waiting text or retry focus");
        f.Tick();
        Check(f.Events.Count == 1 && (string)f.Events.Peek()["type"] == "release", "only cleanup is queued after focus failure");
        yield return Drive((IEnumerator)Invoke(f.Preview, "SendEvents"), () => server.Posts == 2 && !(bool)Get(f.Preview, "sendingEvent"));
        Check(server.Kinds.SequenceEqual(new[] { "focus", "release" }) && f.Sent.Count == 1
            && (string)f.Sent[0]["type"] == "preview.ui.end", "exact release ACK precedes native session end with no input replay");
        cases.Add(new JObject { ["name"] = "focus_denial_keeps_actionable_error_and_orders_cleanup", ["passed"] = true });
    }

    static IEnumerator HttpBusy()
    {
        using var server = new FakeServer(true, busyOnce: true);
        Environment.SetEnvironmentVariable("CALHACKS_CAPTURE_PORT", server.Port.ToString());
        using var f = new Fixture(); server.State(f.State);
        f.Events.Enqueue(new JObject { ["type"] = "pointer", ["x"] = .5, ["y"] = .5 });
        f.Events.Enqueue(new JObject { ["type"] = "key", ["key"] = "G", ["action"] = "press" });
        yield return Drive((IEnumerator)Invoke(f.Preview, "SendEvents"), () => server.Posts == 1 && !(bool)Get(f.Preview, "sendingEvent"));
        Check((bool)Get(f.Preview, "windowResuming") && !(bool)Get(f.Preview, "inputEnabled") && !f.Transport.Synchronized
            && f.Events.Count == 0 && f.Sent.Count == 0, "busy collision discards the entire old gesture without ending native authority or replaying queued input");
        f.Tick(); Check(f.Events.Count == 0, "busy recovery cannot queue release before authoritative sequence resynchronization");
        yield return Drive((IEnumerator)Invoke(f.Preview, "ReadState"), () => f.Transport.Synchronized && !(bool)Get(f.Preview, "readingState"));
        f.Tick();
        Check(f.Events.Count == 1 && (string)f.Events.Peek()["type"] == "release" && !(bool)Get(f.Preview, "inputEnabled"),
            "same-session busy recovery requires exact release acknowledgement before input resumes");
        yield return Drive((IEnumerator)Invoke(f.Preview, "SendEvents"), () => server.Posts == 2 && !(bool)Get(f.Preview, "sendingEvent"));
        var requests = server.Requests.ToArray();
        Check(server.Error == null && server.Kinds.SequenceEqual(new[] { "pointer", "release" })
            && (long)requests[0]["seq"] == 1 && (long)requests[1]["seq"] == 1 && f.Transport.NextSequence == 2
            && (bool)Get(f.Preview, "inputEnabled") && !(bool)Get(f.Preview, "windowResuming")
            && (bool)Get(f.Preview, "triggerWasDown") && f.Sent.Count == 0,
            "busy consumed no action or sequence: only cleanup uses the resynced sequence; a new trigger gesture is required");
        cases.Add(new JObject { ["name"] = "busy_collision_same_session_release_ack_no_action_replay", ["passed"] = true });
    }

    sealed class FakeServer : IDisposable
    {
        readonly TcpListener listener;
        readonly Thread worker;
        volatile bool valid;
        readonly bool failFocus;
        bool busyOnce;
        readonly object stateLock = new object();
        JObject state, selectedState;
        volatile bool stopped;
        int posts;
        public int Port { get; }
        public int Posts => Volatile.Read(ref posts);
        public string Error;
        public readonly System.Collections.Concurrent.ConcurrentQueue<string> Kinds = new System.Collections.Concurrent.ConcurrentQueue<string>();
        public readonly System.Collections.Concurrent.ConcurrentQueue<JObject> Requests = new System.Collections.Concurrent.ConcurrentQueue<JObject>();
        public void State(JObject value) { lock (stateLock) state = (JObject)value.DeepClone(); }
        public void Selects(JObject value) { lock (stateLock) selectedState = (JObject)value.DeepClone(); }
        public void Acknowledge(bool value) { valid = value; }
        public FakeServer(bool valid, bool failFocus = false, bool busyOnce = false)
        {
            this.valid = valid; this.failFocus = failFocus; this.busyOnce = busyOnce; listener = new TcpListener(IPAddress.Loopback, 0); listener.Start(); Port = ((IPEndPoint)listener.LocalEndpoint).Port;
            worker = new Thread(Serve) { IsBackground = true }; worker.Start();
        }
        void Serve()
        {
            while (!stopped)
            {
                try
                {
                    using var client = listener.AcceptTcpClient(); client.ReceiveTimeout = client.SendTimeout = 2000;
                    using var stream = client.GetStream(); var header = new List<byte>();
                    while (header.Count < 32768)
                    {
                        int next = stream.ReadByte(); if (next < 0) throw new EndOfStreamException(); header.Add((byte)next); int n = header.Count;
                        if (n >= 4 && header[n - 4] == 13 && header[n - 3] == 10 && header[n - 2] == 13 && header[n - 1] == 10) break;
                    }
                    string[] lines = Encoding.ASCII.GetString(header.ToArray()).Split(new[] { "\r\n" }, StringSplitOptions.None);
                    bool post = lines[0].StartsWith("POST /input ", StringComparison.Ordinal); int size = 0;
                    foreach (string line in lines) if (line.StartsWith("Content-Length:", StringComparison.OrdinalIgnoreCase)) size = int.Parse(line.Substring(15).Trim());
                    Check(size >= 0 && size <= 65536, "bounded fake HTTP body"); var bytes = new byte[size]; int at = 0;
                    while (at < size) { int read = stream.Read(bytes, at, size - at); if (read == 0) throw new EndOfStreamException(); at += read; }
                    string response; bool rejected = false, busy = false;
                    lock (stateLock)
                    {
                        Check(state != null, "fixture has a prepared helper state");
                        if (!post) { Check(lines[0].StartsWith("GET /input/state ", StringComparison.Ordinal), "only helper state GET is allowed"); response = state.ToString(); }
                        else
                        {
                            var request = JObject.Parse(Encoding.UTF8.GetString(bytes)); Kinds.Enqueue((string)request["type"]); Requests.Enqueue((JObject)request.DeepClone());
                            Check((string)request["session"] == (string)state["session"] && (long)request["seq"] == (long)state["next_seq"], "handoff uses authoritative new helper session and sequence");
                            busy = busyOnce; busyOnce = false;
                            if (!busy) state["next_seq"] = (long)state["next_seq"] + 1;
                            Interlocked.Increment(ref posts);
                            rejected = failFocus && ((string)request["type"] == "select_window" || (string)request["type"] == "focus");
                            response = busy ? "{\"reason\":\"input_busy\"}" : rejected ? "{\"reason\":\"foreground_activation_denied\"}"
                                : valid ? new JObject { ["ok"] = true, ["seq"] = request["seq"] }.ToString() : "{}";
                            if (!rejected && (string)request["type"] == "select_window" && selectedState != null) state = (JObject)selectedState.DeepClone();
                        }
                    }
                    byte[] body = Encoding.UTF8.GetBytes(response); byte[] prefix = Encoding.ASCII.GetBytes("HTTP/1.1 " + (busy ? "429 Too Many Requests" : rejected ? "409 Conflict" : "200 OK") + "\r\nContent-Type: application/json\r\nContent-Length: " + body.Length + "\r\nConnection: close\r\n\r\n");
                    stream.Write(prefix, 0, prefix.Length); stream.Write(body, 0, body.Length); stream.Flush();
                }
                catch (Exception error) { if (!stopped) { Error = error.ToString(); return; } }
            }
        }
        public void Dispose() { stopped = true; listener.Stop(); worker.Join(1000); }
    }
}

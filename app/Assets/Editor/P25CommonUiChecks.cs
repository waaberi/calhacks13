using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR;

// Actual VR button callbacks and queue/session integration on inactive owners.
// No InputField, EventSystem, InputSystem device, OS input, socket, Player or XR.
public static class P25CommonUiChecks
{
    const string A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    static readonly BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static object Get(object target, string name) => target.GetType().GetField(name, Private).GetValue(target);
    static void Set(object target, string name, object value) => target.GetType().GetField(name, Private).SetValue(target, value);
    static object Invoke(object target, string name, params object[] args) => target.GetType().GetMethod(name, Private).Invoke(target, args);
    static void Property(object target, string name, object value) => target.GetType().GetProperty(name).GetSetMethod(true).Invoke(target, new[] { value });
    static void Check(bool ok, string why) { if (!ok) throw new Exception("P25_COMMON_UI: " + why); }
    static void Near(double actual, double expected, string why) => Check(Math.Abs(actual - expected) < 1e-9, why);

    public static void Run()
    {
        NumericButtons(); NumericInvalidation(); ShortcutButtons(); ShortcutContext(); AnchorAdmission(); ShortcutIsolation(); KeyboardAndOcclusion();
        Debug.Log("P25_COMMON_UI_CHECK PASS actual numeric-keypad/8-mode-apply/frozen-draft/31-shortcuts/29-full-keys/pages/editor-anchor/modifier-restoration/atomic-overflow/overlay/desktop-ownership; no native/VR acceptance");
    }

    public static void RunNativeOnly()
    {
        using (var f = new Fixture())
        {
            var names = ((List<Button>)Get(f.Preview, "buttons")).Select(b => b.name).ToArray();
            foreach (string retired in new[] { "Model tools", "Preview tools", "Line", "Circle", "Rectangle", "New XY sketch", "New XZ sketch", "New YZ sketch", "Undo", "Redo", "Save", "Other hand" })
                Check(!names.Contains(retired), "retired editing control is not constructed: " + retired);
            Check(f.Panel("modelToolsPanel") == null && f.Panel("numberPanel") == null && f.Panel("shortcutPanel") == null,
                "no hidden-but-reachable alternate editing canvas");
            f.NativeReady(); f.Anchor();
            f.Click("Full keyboard"); f.Tick();
            foreach (string key in PreviewShortcutCatalog.FullKeyboardKeys)
            {
                f.Events.Clear(); f.Click("Full " + key);
                Check(f.Events.Count == 1 && JToken.DeepEquals(f.Events.Peek(), Key(key, "press")), "generic keyboard still routes " + key);
            }
            f.Preview.TrackingLost(f.Preview.PrimaryHand);
            Check(!(bool)Get(f.Preview, "inputEnabled") && (bool)Get(f.Preview, "endAfterRelease"), "held input ends through existing release barrier");
        }
        foreach (string changed in new[] { "native_tool", "sketch_id", "mode", "unsupported_options", "editing_mode", "units", "generation", "modal_active", "removed" })
        {
            using var f = new Fixture();
            Set(f.Host, "root", f.Host.transform);
            f.Session.Sketches[A] = new JObject { ["id"] = A, ["generation"] = 3,
                ["plane"] = new JObject { ["location"] = new JArray(0,0,0), ["rotation"] = new JArray(1,0,0,0) },
                ["entities"] = new JArray(), ["constraints"] = new JArray() };
            var state = f.Native(); state["available"] = true; state["sketch_id"] = A;
            state["native_tool"] = "sketcher.slvs_add_line2d"; state["tool"] = "line";
            state["editing_mode"] = "shared"; state["unsupported_options"] = new JArray();
            f.Drawing.SetNativeState(state); f.Drawing.SetEnabled(true);
            Check(f.Drawing.Session.Mode == "shared", "mode comes from Blender");
            var ray = new Ray(new Vector3(0, 1, 0), Vector3.down);
            Check(f.Drawing.Press(ray) && f.Drawing.HasDraft, "native line tool starts a direct gesture");
            switch (changed)
            {
                case "native_tool": state["native_tool"] = "unsupported"; break;
                case "sketch_id": state["sketch_id"] = ""; break;
                case "mode": state["mode"] = "EDIT_MESH"; break;
                case "unsupported_options": state["unsupported_options"] = new JArray("Continuous Draw"); break;
                case "editing_mode": state["editing_mode"] = "exclusive"; break;
                case "units": f.Session.Document["units"] = new JObject { ["scale_length"] = .001 }; break;
                case "generation": f.Session.Sketches[A]["generation"] = 4; break;
                case "modal_active": state["modal_active"] = true; break;
                case "removed": f.Session.Sketches.Remove(A); break;
            }
            f.Drawing.SetNativeState(state);
            Check(!f.Drawing.HasDraft && f.Sent.Count == 0, "context change cancels without command: " + changed);
            if (changed == "sketch_id" || changed == "removed")
                Check(!f.Drawing.Press(ray), "native target loss cannot fall back to the old local selection");
        }
        foreach (string tool in new[] { "line", "circle", "rectangle" })
        foreach (bool invalidate in new[] { false, true })
        {
            using var f = new Fixture(); Set(f.Host, "root", f.Host.transform); Property(f.Session, "SketchAvailable", true);
            f.Session.Sketches[A] = new JObject { ["id"] = A, ["generation"] = 3,
                ["plane"] = new JObject { ["location"] = new JArray(0,0,0), ["rotation"] = new JArray(1,0,0,0) },
                ["entities"] = new JArray(), ["constraints"] = new JArray() };
            var state = f.Native(); state["available"] = true; state["sketch_id"] = A;
            state["native_tool"] = "sketcher.native_" + tool; state["tool"] = tool; state["editing_mode"] = "shared";
            f.Drawing.SetNativeState(state); f.Drawing.SetEnabled(true);
            Check(f.Drawing.Press(new Ray(new Vector3(0,1,0), Vector3.down)), "first native-context point " + tool);
            Check(f.Drawing.Press(new Ray(new Vector3(.1f,1,.06f), Vector3.down)), "second native-context point " + tool);
            var acquire = f.Sent.Single(m => (string)m["type"] == "lease.acquire");
            Check((string)acquire["payload"]["mode"] == "shared" && (string)acquire["payload"]["targets"][0] == A,
                "native Shared choice reserves exactly the whole sketch " + tool);
            if (invalidate) { state["native_tool"] = "another native tool"; f.Drawing.SetNativeState(state); }
            f.Receive("lease.granted", new JObject { ["lease"] = new JObject { ["lease_id"] = "lease", ["mode"] = "shared", ["targets"] = new JArray(A) } }, (string)acquire["id"]);
            if (invalidate)
                Check(!f.Sent.Any(m => (string)m["type"] == "command") && f.Sent.Any(m => (string)m["type"] == "lease.release"),
                    "late grant after native context change releases without mutation " + tool);
            else
                Check(f.Sent.Any(m => (string)m["type"] == "command" && (string)m["payload"]["op"] == "sketch.add_" + tool
                    && (string)m["payload"]["target"]["id"] == A && (long)m["payload"]["target"]["generation"] == 3),
                    "actual direct gesture uses native UUID/generation and typed command " + tool);
        }
        Debug.Log("P3_BLENDER_ONLY_CHECK PASS no alternate editing menus; generic keyboard/release barrier; native tool/mode/sketch/options/units/generation/modal/removal invalidation; no GUI/headset acceptance");
    }

    sealed class Fixture : IDisposable
    {
        readonly GameObject owner, display;
        readonly PreviewInteraction previousCurrent;
        public readonly HostScene Host;
        public readonly BlenderScreen Screen;
        public readonly PreviewSpatialDrawing Drawing;
        public readonly PreviewInteraction Preview;
        public readonly List<JObject> Sent = new List<JObject>();
        public NativeEditSession Session => Drawing.Session;
        public Queue<JObject> Events => (Queue<JObject>)Get(Preview, "events");
        public HashSet<string> Modifiers => (HashSet<string>)Get(Preview, "modifiers");
        public Fixture()
        {
            previousCurrent = PreviewInteraction.Current;
            owner = new GameObject("P25 inactive common UI fixture"); owner.SetActive(false);
            Host = owner.AddComponent<HostScene>();
            Set(Host, "status", Enum.Parse(typeof(HostScene).GetNestedType("Status", BindingFlags.NonPublic), "Connected")); Set(Host, "placed", true);
            Screen = owner.AddComponent<BlenderScreen>(); Drawing = owner.AddComponent<PreviewSpatialDrawing>(); Drawing.Initialize(Host);
            Session.Send = message => Sent.Add((JObject)message.DeepClone());
            Preview = owner.AddComponent<PreviewInteraction>(); Property(Preview, "Drawing", Drawing);
            typeof(PreviewInteraction).GetProperty("Current").GetSetMethod(true).Invoke(null, new object[] { Preview });
            Set(Preview, "scene", Host); Set(Preview, "screen", Screen); Set(Preview, "nextHeartbeat", float.PositiveInfinity);
            display = new GameObject("P25 actual common control canvas", typeof(RectTransform), typeof(Canvas));
            display.GetComponent<Canvas>().renderMode = RenderMode.WorldSpace;
            display.transform.position = Vector3.forward * 2; display.transform.localScale = Vector3.one * .001f;
            var imageObject = new GameObject("P25 actual editor image", typeof(RectTransform), typeof(RawImage)); imageObject.transform.SetParent(display.transform, false);
            imageObject.GetComponent<RectTransform>().sizeDelta = new Vector2(1800, 1100);
            Set(Screen, "canvasObject", display); Set(Screen, "image", imageObject.GetComponent<RawImage>());
            Handshake("session"); Fresh(); Invoke(Preview, "BuildControls");
        }
        public JObject Document(long revision = 7) => new JObject { ["id"] = "doc", ["open_epoch"] = "open", ["revision"] = revision };
        public JObject Record(string id = A, long generation = 3) => new JObject { ["id"] = id,
            ["name"] = id == A ? "Alpha" : "Beta", ["generation"] = generation,
            ["transform"] = new JObject { ["location"] = new JArray(.0125, -.02, .03),
                ["scale"] = new JArray(1.25, .5, 2), ["rotation"] = new JArray(1, 0, 0, 0) } };
        public void Handshake(string session)
        {
            Receive("welcome", new JObject { ["session_id"] = session, ["host_epoch"] = "host", ["actor_id"] = "actor",
                ["can_edit"] = true, ["document"] = Document(), ["capabilities"] = new JObject { ["sketch"] = false } });
            Receive("scene.snapshot", new JObject { ["document"] = Document(), ["objects"] = new JArray(Record(), Record(B)), ["sketches"] = new JArray() });
        }
        public JObject Native(bool ui = false, string mode = "OBJECT")
        {
            var value = Session.RequestIdentity; value["mode"] = mode; value["modal_active"] = false;
            value["ui_owner"] = ui ? new JObject { ["actor_id"] = "actor" } : null;
            value["ui_session_id"] = ui ? "ui-session" : null; value["ui_ending"] = false;
            value["input_allowed"] = ui; value["process_id"] = 42; value["available"] = false;
            return value;
        }
        public void Fresh() => Drawing.SetNativeState(Native());
        public void Tick() => Invoke(Preview, "Update");
        public Button Button(string name) => ((List<Button>)Get(Preview, "buttons")).Single(button => button.name == name);
        public void Click(string name) => Button(name).onClick.Invoke();
        public RectTransform Panel(string name) => (RectTransform)Get(Preview, name);
        public void Model()
        {
            Click("Model tools"); Tick(); Tick(); Click("Next object");
            Check(Drawing.ObjectToolsEnabled && Drawing.ObjectTools.TargetId == A, "actual model menu explicitly selects Alpha");
        }
        public void Numbers(string label)
        {
            Click(label); Tick();
            Check(Panel("numberPanel").gameObject.activeInHierarchy && Drawing.Numeric.IsCurrent, "actual numeric opener loads a local button keypad " + label);
        }
        public void Type(int axis, string value)
        {
            Click("Number " + "XYZ"[axis]); Click("Number clear");
            foreach (char c in value) Click("Number " + (c == '-' ? "sign" : c.ToString()));
        }
        public void NativeReady(string mode = "OBJECT")
        {
            Drawing.SetNativeState(Native(true, mode));
            Set(Preview, "inputEnabled", true); Set(Preview, "session", "helper"); Set(Preview, "token", "fixture-token");
            Set(Preview, "state", new JObject { ["ready"] = true, ["focused"] = true, ["release_error"] = false,
                ["capture_instance"] = "capture", ["capture_generation"] = 7, ["capture_geometry"] = "geometry",
                ["selection"] = new JObject { ["pid"] = 42, ["hwnd"] = 100 } });
            Property(Screen, "DisplayedCaptureInstance", "capture"); Property(Screen, "DisplayedSelectionGeneration", 7L); Property(Screen, "DisplayedCaptureGeometry", "geometry");
            Check((bool)Invoke(Preview, "Ready"), "fixture meets real frame/native owner/focus admission without focusing a window");
        }
        public void Anchor()
        {
            var point = new Vector2(.2f, .3f);
            var world = new Vector3((point.x - .5f) * 1.8f, (.5f - point.y) * 1.1f, 0);
            var ray = new Ray(world, Vector3.forward);
            Preview.RouteHand(XRNode.RightHand, ray, false, false, Vector2.zero, 3, out _);
            Check(Preview.RouteHand(XRNode.RightHand, ray, true, false, Vector2.zero, 3, out _), "actual image press is routed before remembering an editor");
            Preview.RouteHand(XRNode.RightHand, ray, false, false, Vector2.zero, 3, out _);
            Check((bool)Get(Preview, "editorPointSet"), "actual image press records editor identity and coordinates");
            var remembered = (Vector2)Get(Preview, "editorPoint");
            Check(Vector2.Distance(remembered, point) < .00001f, "remembered editor coordinates come from the actual float RawImage ray mapping");
            Events.Clear();
        }
        public void Tools() { Click("Preview tools"); Tick(); Check(Panel("shortcutPanel").gameObject.activeInHierarchy, "focused Preview tools button opens its panel"); Events.Clear(); }
        public void Receive(string type, JObject payload, string re = null)
        {
            var message = NativeEditSession.Envelope(type, payload); if (re != null) message["re"] = re;
            var assembly = typeof(HostScene).Assembly; var kind = Enum.Parse(assembly.GetType("SpatialModeling.HostEventKind"), "Message");
            var evt = Activator.CreateInstance(assembly.GetType("SpatialModeling.HostEvent"), new[] { kind });
            evt.GetType().GetField("RawMessage").SetValue(evt, message); Invoke(Drawing, "Receive", evt);
        }
        public void Dispose()
        {
            Drawing.Numeric.Dispose(); Drawing.ObjectTools.Dispose();
            typeof(PreviewInteraction).GetProperty("Current").GetSetMethod(true).Invoke(null, new object[] { previousCurrent });
            UnityEngine.Object.DestroyImmediate(display); UnityEngine.Object.DestroyImmediate(owner);
        }
    }

    static void NumericButtons()
    {
        string[] labels = { "Exact move", "Set position", "Set rotation", "Scale factors", "Set scale", "Cube dimensions", "Sphere dimensions", "Cylinder dimensions" };
        string[] modes = { "move", "position", "rotation", "scale.by", "scale.to", "add.cube", "add.sphere", "add.cylinder" };
        for (int mode = 0; mode < labels.Length; mode++)
        {
            using var f = new Fixture(); f.Model(); f.Numbers(labels[mode]);
            Check(f.Drawing.Numeric.Mode == modes[mode] && f.Sent.Count == 0 && PreviewInteraction.BlocksDesktopShortcuts,
                "numeric opener names match mode, own desktop shortcuts, and send nothing before Apply");
            if (mode == 1) Check(f.Drawing.Numeric.Value(0) == "12.5" && f.Drawing.Numeric.Value(1) == "-20", "position prefill uses current native metres displayed as mm");
            if (mode == 4) Check(f.Drawing.Numeric.Value(0) == "1.25" && f.Drawing.Numeric.Value(1) == "0.5", "absolute scale prefill preserves native current axes");
            string[] values = mode == 2 ? new[] { "90", "0", "0" } : mode == 3 || mode == 4 ? new[] { "1.25", "0.5", "2" }
                : mode >= 5 ? new[] { "25", "35", "45" } : new[] { "12.5", "-20", "30" };
            for (int axis = 0; axis < 3; axis++) f.Type(axis, values[axis]);
            f.Tick();
            Check(f.Drawing.Numeric.Value(0) == values[0] && f.Drawing.Numeric.Value(1) == values[1]
                && f.Drawing.Numeric.Value(2) == values[2] && f.Sent.Count == 0, "actual axis/digit/sign/decimal callbacks preserve text across refresh without transmission");
            f.Click("Apply numbers");
            Check(f.Sent.Count == 1 && (string)f.Sent[0]["type"] == "lease.acquire" && !f.Drawing.Numeric.IsCurrent,
                "numeric Apply requests existing permission and consumes its local draft immediately");
            string acquire = (string)f.Sent[0]["id"];
            f.Receive("lease.granted", new JObject { ["lease"] = new JObject { ["lease_id"] = "numbers-lease" } }, acquire);
            var command = f.Sent.Single(message => (string)message["type"] == "command"); var payload = command["payload"];
            Check(mode >= 5 ? payload["target"] == null : (string)payload["target"]?["id"] == A && (long?)payload["target"]?["generation"] == 3,
                "actual numeric command preserves explicit UUID/generation or intentional primitive creation");
            string expectedOp = mode >= 5 ? "object.add" : mode <= 1 ? "object.move" : mode == 2 ? "object.rotate" : "object.scale";
            Check((string)payload["op"] == expectedOp, "numeric button maps to its typed operation");
            var args = payload["args"];
            if (mode == 2)
            {
                var q = args["to"].Values<double>().ToArray();
                Near(q[0], Math.Sqrt(.5), "rotation w"); Near(q[1], Math.Sqrt(.5), "rotation x"); Near(q[2], 0, "rotation y"); Near(q[3], 0, "rotation z");
            }
            else
            {
                string field = mode >= 5 ? "dimensions" : mode == 0 || mode == 3 ? "by" : "to";
                double[] expected = mode >= 5 ? new[] { .025, .035, .045 } : mode == 3 || mode == 4 ? new[] { 1.25, .5, 2 } : new[] { .0125, -.02, .03 };
                var actual = args[field].Values<double>().ToArray(); for (int axis = 0; axis < 3; axis++) Near(actual[axis], expected[axis], "typed numeric axis value");
                if (mode >= 5) Check((string)args["primitive"] == modes[mode].Substring(4), "dimension opener chooses exact primitive");
            }
            f.Receive("result", new JObject { ["request_id"] = command["id"], ["op"] = expectedOp, ["outcome"] = "applied", ["created"] = new JArray() });
            f.Sent.Clear(); f.Click("Apply numbers"); Check(f.Sent.Count == 0, "consumed numeric draft cannot apply twice after receipt");
            f.Click("Reload numbers"); Check(f.Drawing.Numeric.IsCurrent && f.Sent.Count == 0, "explicit numeric reload creates a fresh local draft only");
            f.Click("Close numbers"); f.Tick(); Check(!f.Drawing.Numeric.IsCurrent && !PreviewInteraction.BlocksDesktopShortcuts, "close invalidates local values and releases local desktop ownership");
        }
        using (var f = new Fixture())
        {
            f.Model(); f.Numbers("Exact move"); f.Click("Number X"); f.Click("Number clear"); f.Click("Number 1"); f.Click("Number 2"); f.Click("Number back");
            Check(f.Drawing.Numeric.Value(0) == "1", "backspace button removes one local digit");
            f.Click("Number clear"); f.Click("Apply numbers"); Check(f.Sent.Count == 0, "empty visible numeric axis cannot reach native permission");
        }
        using (var f = new Fixture())
        {
            f.Model(); var record = f.Record(); record["transform"]["rotation"] = new JArray(Math.Sqrt(.5), 0, 0, Math.Sqrt(.5));
            f.Receive("scene.update", new JObject { ["objects"] = new JArray(record) }); f.Fresh(); f.Numbers("Set rotation");
            Check(f.Drawing.Numeric.Value(0) == "0" && f.Drawing.Numeric.Value(1) == "0" && f.Drawing.Numeric.Value(2) == "90",
                "actual Set rotation opener preserves the current quarter-turn around native Z in untouched numeric fields");
        }
    }

    static void NumericInvalidation()
    {
        foreach (string loss in new[] { "revision", "generation", "removed", "target", "native", "session" })
        {
            using var f = new Fixture(); f.Model(); f.Numbers("Exact move"); f.Type(0, "17");
            if (loss == "revision") f.Receive("scene.update", new JObject { ["document"] = f.Document(8) });
            if (loss == "generation") f.Receive("scene.update", new JObject { ["objects"] = new JArray(f.Record(generation: 4)) });
            if (loss == "removed") f.Receive("scene.update", new JObject { ["removed"] = new JArray(A) });
            if (loss == "target") f.Drawing.ObjectTools.SelectRelative(1);
            if (loss == "native") { var state = f.Native(); state["mode"] = "EDIT_MESH"; f.Drawing.SetNativeState(state); f.Fresh(); }
            if (loss == "session") { f.Handshake("new-session"); f.Fresh(); }
            f.Click("Apply numbers");
            Check(!f.Drawing.Numeric.IsCurrent && f.Sent.Count == 0, "visible numeric Apply refuses invalidated original context without fallback " + loss);
        }
    }

    static void ShortcutButtons()
    {
        using var f = new Fixture(); f.NativeReady(); f.Anchor(); f.Tools();
        for (int i = 0; i < PreviewShortcutCatalog.All.Count; i++)
        {
            var item = PreviewShortcutCatalog.All[i];
            if ((int)Get(f.Preview, "shortcutPage") != i / 21) f.Click("Next tools");
            f.NativeReady(item.Id.StartsWith("mesh.", StringComparison.Ordinal) ? "EDIT_MESH" : "OBJECT");
            var button = f.Button("Shortcut " + item.Id); Check(button.gameObject.activeInHierarchy, "shortcut page exposes actual control " + item.Id);
            f.Events.Clear(); f.Click(button.name);
            var actual = f.Events.ToArray(); int offset = item.RequiresEditorContext ? 1 : 0;
            var expected = item.BuildEvents();
            Check(actual.Length == expected.Count + offset, "actual shortcut emits only expected position/chord " + item.Id);
            if (offset == 1) Check((string)actual[0]["type"] == "pointer" && Math.Abs((double)actual[0]["x"] - .2) < .00001
                && Math.Abs((double)actual[0]["y"] - .3) < .00001, "actual float-mapped editor target is positioned before chord");
            for (int e = 0; e < expected.Count; e++) Check(JToken.DeepEquals(actual[e + offset], expected[e]), "actual shortcut button selects its exact catalog intent " + item.Id);
            Check(f.Sent.Count == 0, "preview shortcut never bypasses helper input with a typed native mutation");
        }
        f.Click("Previous tools"); Check((int)Get(f.Preview, "shortcutPage") == 0, "actual Previous tools wraps to first page");
        var modal = f.Native(true); modal["modal_active"] = true; f.Drawing.SetNativeState(modal); Set(f.Preview, "editorPointSet", false);
        f.Events.Clear(); f.Click("Preview Escape"); f.Click("Preview Enter");
        Check(f.Events.Count == 2 && (string)f.Events.ElementAt(0)["key"] == "ESC" && (string)f.Events.ElementAt(1)["key"] == "ENTER",
            "permanent cancel/confirm controls remain available during a native modal without editor anchor");
        f.Click("Close preview tools"); f.Tick(); Check(!f.Panel("shortcutPanel").gameObject.activeInHierarchy, "actual close hides shortcut pages");
    }

    static void ShortcutContext()
    {
        foreach (string loss in new[] { "anchor", "instance", "generation", "geometry", "identity", "stale", "modal", "mesh_mode" })
        {
            using var f = new Fixture(); f.NativeReady(); if (loss != "anchor") f.Anchor(); f.Tools();
            var state = (JObject)Get(f.Preview, "state");
            if (loss == "instance") { state["capture_instance"] = "other"; Property(f.Screen, "DisplayedCaptureInstance", "other"); }
            if (loss == "generation") { state["capture_generation"] = 8; Property(f.Screen, "DisplayedSelectionGeneration", 8L); }
            if (loss == "geometry") { state["capture_geometry"] = "other"; Property(f.Screen, "DisplayedCaptureGeometry", "other"); }
            if (loss == "identity") { f.Handshake("new-session"); f.NativeReady(); }
            if (loss == "stale") Set(f.Drawing, "stateAt", float.NegativeInfinity);
            if (loss == "modal") { var value = f.Native(true); value["modal_active"] = true; f.Drawing.SetNativeState(value); }
            f.Click(loss == "mesh_mode" ? "Shortcut mesh.extrude" : "Shortcut transform.move");
            Check(f.Events.Count == 0 && f.Sent.Count == 0, "actual shortcut refuses unavailable context " + loss);
        }
    }

    static JObject Key(string key, string action) => new JObject { ["type"] = "key", ["key"] = key, ["action"] = action };
    static void AnchorAdmission()
    {
        foreach (string kind in new[] { "hover", "right", "middle" })
        {
            using var f = new Fixture(); f.NativeReady();
            if (kind != "hover") f.Click("Mouse " + kind);
            var ray = new Ray(new Vector3(-.54f, .22f, 0), Vector3.forward);
            f.Preview.RouteHand(XRNode.RightHand, ray, false, false, Vector2.zero, 3, out _);
            if (kind != "hover")
            {
                f.Preview.RouteHand(XRNode.RightHand, ray, true, false, Vector2.zero, 3, out _);
                f.Preview.RouteHand(XRNode.RightHand, ray, false, false, Vector2.zero, 3, out _);
            }
            Check(!(bool)Get(f.Preview, "editorPointSet"), "only an explicit left image press establishes editor context, not " + kind);
            f.Events.Clear(); f.Tools(); f.Click("Shortcut transform.move");
            Check(f.Events.Count == 0, "non-left editor gesture cannot arm a later common operation");
        }
    }
    static void ShortcutIsolation()
    {
        using (var f = new Fixture())
        {
            f.NativeReady(); f.Anchor(); f.Tools(); f.Modifiers.Add("ALT"); f.Modifiers.Add("CTRL"); Set(f.Preview, "mouseHeld", true);
            Set(f.Preview, "pendingPointer", new JObject { ["type"] = "pointer", ["x"] = .9, ["y"] = .9 });
            f.Click("Shortcut object.duplicate"); var actual = f.Events.ToArray();
            Check(actual.Length == 9 && (string)actual[0]["type"] == "button" && (string)actual[0]["action"] == "up", "shortcut lifts the held mouse before isolated chord");
            Check(JToken.DeepEquals(actual[1], Key("ALT", "up")) && JToken.DeepEquals(actual[2], Key("CTRL", "up"))
                && (string)actual[3]["type"] == "pointer" && JToken.DeepEquals(actual[4], Key("SHIFT", "down"))
                && JToken.DeepEquals(actual[5], Key("D", "press")) && JToken.DeepEquals(actual[6], Key("SHIFT", "up"))
                && JToken.DeepEquals(actual[7], Key("ALT", "down")) && JToken.DeepEquals(actual[8], Key("CTRL", "down")),
                "actual shortcut isolates owned modifiers, positions editor, emits chord, restores exact held state");
            Check(f.Modifiers.SetEquals(new[] { "ALT", "CTRL" }) && !(bool)Get(f.Preview, "mouseHeld") && Get(f.Preview, "pendingPointer") == null,
                "local held modifier state survives shortcut and stale pending pointer is discarded");
        }
        foreach (int queued in new[] { 55, 56 })
        {
            using var f = new Fixture(); f.NativeReady(); f.Anchor(); f.Tools(); f.Modifiers.Add("ALT"); f.Modifiers.Add("CTRL"); Set(f.Preview, "mouseHeld", true);
            for (int i = 0; i < queued; i++) f.Events.Enqueue(new JObject { ["type"] = "heartbeat" });
            f.Click("Shortcut object.duplicate");
            if (queued == 55) Check(f.Events.Count == 64 && f.Modifiers.Count == 2, "entire chord fits exact queue boundary");
            else
            {
                Check(f.Events.Count == 0 && (bool)Get(f.Preview, "endAfterRelease") && f.Modifiers.Count == 0,
                    "over-capacity shortcut emits no partial chord or modifier restoration and requires cleanup");
                f.Tick(); Check(f.Events.Count == 1 && (string)f.Events.Peek()["type"] == "release", "only cleanup can follow atomic shortcut refusal");
            }
        }
    }

    static void Gap(Fixture f, string field)
    {
        var panel = f.Panel(field); var point = panel.TransformPoint(new Vector3(0, -140, 0));
        var ray = new Ray(new Vector3(point.x, point.y, 0), Vector3.forward);
        f.Events.Clear();
        Check(f.Preview.RouteHand(XRNode.RightHand, ray, false, false, Vector2.zero, 3, out var distance)
            && Math.Abs(distance - panel.position.z) < .00001 && f.Events.Count == 0, "actual common overlay gap consumes image input " + field);
        Check(!f.Preview.RouteHand(XRNode.RightHand, ray, false, false, Vector2.zero, 1, out _), "nearer placement target occludes common overlay");
        Check(!f.Preview.RouteHand(XRNode.RightHand, ray, false, true, Vector2.zero, 3, out _), "grip remains arrangement input on common overlay");
        Check(!f.Preview.RouteHand(XRNode.LeftHand, ray, true, false, Vector2.zero, 3, out _), "unselected hand cannot activate common controls");
    }
    static void KeyboardAndOcclusion()
    {
        using (var f = new Fixture())
        {
            f.Model(); f.Numbers("Exact move"); Gap(f, "numberPanel");
            var axis = f.Button("Number Y").transform.position; var ray = new Ray(new Vector3(axis.x, axis.y, 0), Vector3.forward);
            f.Preview.RouteHand(XRNode.RightHand, ray, false, false, Vector2.zero, 3, out _);
            Check(f.Preview.RouteHand(XRNode.RightHand, ray, true, false, Vector2.zero, 3, out _) && f.Drawing.Numeric.Axis == 1 && f.Events.Count == 0,
                "actual ray selects numeric axis locally rather than clicking Blender underneath");
        }
        using (var f = new Fixture())
        {
            f.NativeReady(); f.Anchor(); f.Tools(); Gap(f, "shortcutPanel");
            f.Click("Full keyboard"); f.Tick();
            Check(f.Panel("keyboard").gameObject.activeInHierarchy && !f.Button("q").gameObject.activeInHierarchy, "full keyboard opens its own reachable page");
            foreach (string key in PreviewShortcutCatalog.FullKeyboardKeys)
            {
                f.Events.Clear(); Check(f.Button("Full " + key).gameObject.activeInHierarchy, "full key is visible " + key); f.Click("Full " + key);
                Check(f.Events.Count == 1 && JToken.DeepEquals(f.Events.Peek(), Key(key, "press")), "actual full keyboard key emits exact helper name " + key);
            }
            f.Events.Clear(); Gap(f, "keyboard");
            f.Click("Letters"); Check(f.Button("q").gameObject.activeInHierarchy && !f.Button("Full F1").gameObject.activeInHierarchy, "Letters switches to basic keyboard");
            f.Click("More keys"); Check(f.Button("Full F1").gameObject.activeInHierarchy && !f.Button("q").gameObject.activeInHierarchy, "More keys restores full page");
            Set(f.Preview, "inputEnabled", false); f.Events.Clear(); f.Click("Full F1"); Check(f.Events.Count == 0, "full keyboard cannot bypass disabled native input");
            f.Click("Close full keyboard"); f.Tick(); Check(!f.Panel("keyboard").gameObject.activeInHierarchy, "close full keyboard hides it");
        }
    }
}

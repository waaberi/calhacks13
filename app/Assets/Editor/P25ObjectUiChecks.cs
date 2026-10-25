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

// Real button callbacks and bridge/session paths on inactive components. No
// OnEnable, native process, desktop input, Player, InputSystem devices or XR.
public static class P25ObjectUiChecks
{
    const string A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    static readonly BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static object Get(object target, string name) => target.GetType().GetField(name, Private).GetValue(target);
    static void Set(object target, string name, object value) => target.GetType().GetField(name, Private).SetValue(target, value);
    static object Invoke(object target, string name, params object[] args) => target.GetType().GetMethod(name, Private).Invoke(target, args);
    static void Check(bool ok, string reason) { if (!ok) throw new Exception("P25_OBJECT_UI: " + reason); }

    public static void Run()
    {
        Buttons(); ContextAdmission(); LateGrants(); Occlusion(); ReleaseBarrier();
        Debug.Log("P25_OBJECT_UI_CHECK PASS actual onClick/all-object-actions/history/explicit-target/context/late-grant/overlay-gap/disabled/nearest/grip/release-barrier; native runtime acceptance=False");
    }

    sealed class Fixture : IDisposable
    {
        readonly GameObject owner;
        public readonly GameObject Display;
        public readonly HostScene Host;
        public readonly BlenderScreen Screen;
        public readonly PreviewSpatialDrawing Drawing;
        public readonly PreviewInteraction Preview;
        public readonly List<JObject> Sent = new List<JObject>();
        public NativeEditSession Session => Drawing.Session;
        public RectTransform Panel => (RectTransform)Get(Preview, "modelToolsPanel");
        public Queue<JObject> Events => (Queue<JObject>)Get(Preview, "events");
        public Fixture()
        {
            owner = new GameObject("P25 inactive object UI fixture"); owner.SetActive(false);
            Host = owner.AddComponent<HostScene>();
            Set(Host, "status", Enum.Parse(typeof(HostScene).GetNestedType("Status", BindingFlags.NonPublic), "Connected"));
            Set(Host, "placed", true);
            Screen = owner.AddComponent<BlenderScreen>();
            Drawing = owner.AddComponent<PreviewSpatialDrawing>(); Drawing.Initialize(Host);
            Drawing.Session.Send = message => Sent.Add((JObject)message.DeepClone());
            Preview = owner.AddComponent<PreviewInteraction>();
            typeof(PreviewInteraction).GetProperty("Drawing").GetSetMethod(true).Invoke(Preview, new object[] { Drawing });
            Set(Preview, "scene", Host); Set(Preview, "screen", Screen);
            Display = new GameObject("P25 isolated actual controls canvas", typeof(RectTransform), typeof(Canvas));
            Display.GetComponent<Canvas>().renderMode = RenderMode.WorldSpace;
            Display.transform.position = Vector3.forward * 2;
            Display.transform.localScale = Vector3.one * .001f;
            var imageObject = new GameObject("P25 preview behind controls", typeof(RectTransform), typeof(RawImage));
            imageObject.transform.SetParent(Display.transform, false);
            var image = imageObject.GetComponent<RawImage>(); image.rectTransform.sizeDelta = new Vector2(1800, 1100);
            Set(Screen, "canvasObject", Display); Set(Screen, "image", image);
            var document = new JObject { ["id"] = "doc", ["open_epoch"] = "open", ["revision"] = 7 };
            Session.Receive(NativeEditSession.Envelope("welcome", new JObject {
                ["session_id"] = "session", ["host_epoch"] = "host", ["actor_id"] = "actor",
                ["can_edit"] = true, ["document"] = document, ["capabilities"] = new JObject { ["sketch"] = false } }));
            Session.Receive(NativeEditSession.Envelope("scene.snapshot", new JObject { ["document"] = document.DeepClone(),
                ["objects"] = new JArray(new JObject { ["id"] = B, ["name"] = "Beta", ["generation"] = 11 },
                    new JObject { ["id"] = A, ["name"] = "Alpha", ["generation"] = 3 }), ["sketches"] = new JArray() }));
            Fresh(); Invoke(Preview, "BuildControls");
        }
        public JObject State()
        {
            var value = Session.RequestIdentity;
            value["mode"] = "OBJECT"; value["modal_active"] = false;
            value["ui_owner"] = null; value["ui_session_id"] = null; value["ui_ending"] = false;
            value["input_allowed"] = false; value["process_id"] = 42;
            value["available"] = false; // Model tools do not depend on CAD Sketcher.
            return value;
        }
        public void Fresh() => Drawing.SetNativeState(State());
        public void Tick() => Invoke(Preview, "Update");
        public Button Button(string label) => ((List<Button>)Get(Preview, "buttons")).Single(button => button.name == label);
        public void Click(string label) => Button(label).onClick.Invoke();
        public void Open()
        {
            Click("Model tools"); Tick(); Tick();
            Check(Drawing.ObjectToolsEnabled && Panel.gameObject.activeInHierarchy, "actual Model tools button opens its overlay");
        }
        public void Target() { Click("Next object"); Check(Drawing.ObjectTools.TargetId == A, "explicit object button chooses Alpha UUID"); }
        public void Receive(string type, JObject payload, string re = null)
        {
            var message = NativeEditSession.Envelope(type, payload); if (re != null) message["re"] = re;
            var assembly = typeof(HostScene).Assembly;
            var kind = Enum.Parse(assembly.GetType("SpatialModeling.HostEventKind"), "Message");
            var evt = Activator.CreateInstance(assembly.GetType("SpatialModeling.HostEvent"), new[] { kind });
            evt.GetType().GetField("RawMessage").SetValue(evt, message);
            Invoke(Drawing, "Receive", evt);
        }
        public void Grant(string request) => Receive("lease.granted", new JObject {
            ["lease"] = new JObject { ["lease_id"] = "fixture-lease" } }, request);
        public void Dispose()
        {
            Drawing.ObjectTools.Dispose(); // Inactive fixture OnDestroy is not guaranteed by Unity.
            UnityEngine.Object.DestroyImmediate(Display);
            UnityEngine.Object.DestroyImmediate(owner);
        }
    }

    static void Submit(Fixture f, string label, string op, Action<JObject> inspect = null, bool targeted = false)
    {
        f.Sent.Clear(); f.Fresh(); f.Click(label);
        Check(f.Sent.Count == 1 && (string)f.Sent[0]["type"] == "lease.acquire", label + " requests permission before any command");
        f.Grant((string)f.Sent[0]["id"]);
        var command = f.Sent.Single(message => (string)message["type"] == "command");
        var payload = (JObject)command["payload"];
        Check((string)payload["op"] == op, label + " is wired to " + op);
        Check(targeted ? (string)payload["target"]?["id"] == A && (long?)payload["target"]?["generation"] == 3
            : payload["target"] == null, label + " preserves explicit target UUID/generation or intentional targetless operation");
        inspect?.Invoke((JObject)payload["args"]);
        f.Receive("result", new JObject { ["request_id"] = command["id"], ["op"] = op,
            ["outcome"] = "applied", ["created"] = new JArray() });
        Check(!f.Session.Busy, label + " completes only through matching session receipt");
        Check(!f.Drawing.StatusText.Contains("Waiting for Blender to confirm the model edit"),
            label + " replaces its pending status after the matching native receipt");
    }

    static void Buttons()
    {
        using var f = new Fixture(); f.Open();
        f.Click("Move X +"); f.Click("Delete target");
        Check(f.Sent.Count == 0 && f.Session.Draft == null, "targeted buttons cannot use an implicit object");
        f.Target(); f.Click("Previous object"); Check(f.Drawing.ObjectTools.TargetId == B, "previous object wraps");
        f.Click("Next object"); Check(f.Drawing.ObjectTools.TargetId == A, "next object wraps back to Alpha");
        f.Click("Move step"); f.Click("Turn step"); f.Click("Primitive size");
        Check(f.Drawing.ObjectTools.MoveStepMeters == .1 && f.Drawing.ObjectTools.TurnDegrees == 90
            && f.Drawing.ObjectTools.PrimitiveSizeMeters == .1 && f.Sent.Count == 0, "step buttons adjust local configuration only");
        Check(f.Button("Move step").GetComponentInChildren<Text>().text.Contains("100 mm")
            && f.Button("Turn step").GetComponentInChildren<Text>().text.Contains("90 deg"), "step labels show selected native units");
        foreach (string primitive in new[] { "cube", "sphere", "cylinder" })
            Submit(f, "Add " + primitive, "object.add", args => Check((string)args["primitive"] == primitive
                && args["dimensions"].Values<double>().All(value => Math.Abs(value - .1) < 1e-9), "actual add button passes primitive and native metre size"));
        for (int axis = 0; axis < 3; axis++) foreach (int sign in new[] { -1, 1 })
        {
            int selectedAxis = axis, selectedSign = sign; string suffix = sign < 0 ? " -" : " +";
            Submit(f, "Move " + "XYZ"[axis] + suffix, "object.move", args => {
                var by = args["by"].Values<double>().ToArray();
                Check(by.Length == 3 && by.Where((value, index) => Math.Abs(value - (index == selectedAxis ? selectedSign * .1 : 0)) > 1e-9).Count() == 0,
                    "actual axis/sign move button uses native world XYZ"); }, true);
            Submit(f, "Turn " + "XYZ"[axis] + suffix, "object.rotate", args => Check((string)args["by"]?["axis"] == "XYZ"[selectedAxis].ToString()
                && Math.Abs((double)args["by"]["angle"] - selectedSign * Math.PI / 2) < 1e-9, "actual turn axis/sign is radians"), true);
        }
        Submit(f, "Scale down", "object.scale", args => Check(args["by"].Values<double>().All(value => Math.Abs(value - 1 / 1.1) < 1e-9), "scale down is uniform"), true);
        Submit(f, "Scale up", "object.scale", args => Check(args["by"].Values<double>().All(value => Math.Abs(value - 1.1) < 1e-9), "scale up is uniform"), true);
        Submit(f, "Delete target", "object.delete", targeted: true);
        Submit(f, "Model Undo", "history.undo"); Submit(f, "Model Redo", "history.redo"); Submit(f, "Model Save", "document.save");
        f.Sent.Clear(); f.Click("Move X +"); string acquire = (string)f.Sent[0]["id"];
        f.Click("Cancel pending"); f.Grant(acquire);
        Check(!f.Sent.Any(message => (string)message["type"] == "command")
            && f.Sent.Any(message => (string)message["type"] == "lease.release"), "actual cancel button releases a late permission without mutation");
        f.Click("Close model tools"); f.Tick();
        Check(!f.Drawing.ObjectToolsEnabled && !f.Panel.gameObject.activeInHierarchy, "actual close button disables and hides Model tools");
    }

    static void ContextAdmission()
    {
        string[] contexts = { "stale", "scene", "placement", "edit", "modal", "owner", "token", "ending", "transition", "readonly" };
        foreach (string context in contexts)
        {
            using var f = new Fixture(); f.Open(); f.Target();
            var state = f.State();
            if (context == "stale") Set(f.Drawing, "stateAt", float.NegativeInfinity);
            if (context == "scene") f.Session.SceneCurrent = false;
            if (context == "placement") Set(f.Host, "placed", false);
            if (context == "edit") state["mode"] = "EDIT_MESH";
            if (context == "modal") state["modal_active"] = true;
            if (context == "owner") state["ui_owner"] = new JObject { ["actor_id"] = "actor" };
            if (context == "token") state["ui_session_id"] = "not-ended";
            if (context == "ending") state["ui_ending"] = true;
            if (context == "transition") Set(f.Drawing, "endId", "not-acknowledged");
            if (context == "readonly") typeof(NativeEditSession).GetProperty("CanEdit").GetSetMethod(true).Invoke(f.Session, new object[] { false });
            if (context != "stale") f.Drawing.SetNativeState(state);
            f.Click("Move X +"); f.Click("Add cube"); f.Click("Model Undo");
            Check(f.Sent.Count == 0 && f.Session.Draft == null, "actual targeted/create/history buttons refuse unsafe context " + context);
        }
    }

    static void LateGrants()
    {
        foreach (string context in new[] { "stale", "modal", "edit", "owner", "wrong_identity_then_recover", "scene_then_recover" })
        {
            using var f = new Fixture(); f.Open(); f.Target(); f.Click("Move X +");
            string acquire = (string)f.Sent.Single()["id"];
            var state = f.State();
            if (context == "stale") Set(f.Drawing, "stateAt", float.NegativeInfinity);
            else if (context == "scene_then_recover")
            {
                var statusType = typeof(HostScene).GetNestedType("Status", BindingFlags.NonPublic);
                Set(f.Host, "status", Enum.Parse(statusType, "Disconnected")); Invoke(f.Drawing, "Update");
                Check(f.Session.Draft == null, "actual bridge update cancels object acquisition when accepted host scene becomes stale");
                Set(f.Host, "status", Enum.Parse(statusType, "Connected")); f.Fresh();
            }
            else
            {
                if (context == "modal") state["modal_active"] = true;
                if (context == "edit") state["mode"] = "EDIT_MESH";
                if (context == "owner") state["ui_owner"] = new JObject { ["actor_id"] = "other" };
                if (context == "wrong_identity_then_recover") state["host_epoch"] = "another-host";
                f.Drawing.SetNativeState(state);
                Check(f.Session.Draft == null, "native context loss immediately cancels pending object draft " + context);
                if (context == "wrong_identity_then_recover") f.Fresh();
            }
            f.Grant(acquire);
            Check(!f.Sent.Any(message => (string)message["type"] == "command")
                && f.Sent.Any(message => (string)message["type"] == "lease.release"), "late grant cannot resurrect cancelled/unsafe object edit " + context);
        }
    }

    static void Occlusion()
    {
        using var f = new Fixture(); f.Open(); f.Target();
        var model = f.Panel;
        var gap = model.TransformPoint(new Vector3(0, -140, 0));
        var ray = new Ray(new Vector3(gap.x, gap.y, 0), Vector3.forward);
        Check(f.Preview.RouteHand(XRNode.RightHand, ray, true, false, Vector2.zero, 3, out var d)
            && Math.Abs(d - model.position.z) < .00001 && !f.Preview.CapturesScroll && f.Sent.Count == 0 && f.Events.Count == 0,
            "actual overlay gap consumes aim before image or spatial fallback");
        var main = (RectTransform)Get(f.Preview, "panel");
        var mainGap = main.TransformPoint(new Vector3(0, -140, 0));
        var mainRay = new Ray(new Vector3(mainGap.x, mainGap.y, 0), Vector3.forward);
        Check(f.Preview.RouteHand(XRNode.RightHand, mainRay, false, false, Vector2.zero, 3, out d)
            && Math.Abs(d - main.position.z) < .00001 && f.Sent.Count == 0, "main control panel gap also consumes aim before arrangement fallback");
        Check(!f.Preview.RouteHand(XRNode.RightHand, ray, false, false, Vector2.zero, 1, out _), "nearer arrangement target occludes overlay and image");
        Check(!f.Preview.RouteHand(XRNode.RightHand, ray, true, true, Vector2.zero, 3, out _), "grip stays with arrangement");
        Check(!f.Preview.RouteHand(XRNode.LeftHand, ray, true, false, Vector2.zero, 3, out _), "other hand cannot trigger model palette");
        var button = f.Button("Move X +"); button.interactable = false;
        var point = button.transform.position; ray = new Ray(new Vector3(point.x, point.y, 0), Vector3.forward);
        f.Preview.RouteHand(XRNode.RightHand, ray, false, false, Vector2.zero, 3, out _);
        Check(f.Preview.RouteHand(XRNode.RightHand, ray, true, false, Vector2.zero, 3, out _) && f.Sent.Count == 0,
            "disabled actual button absorbs the hit without invoking a command");
        button.interactable = true;
        f.Preview.RouteHand(XRNode.RightHand, ray, false, false, Vector2.zero, 3, out _);
        Check(f.Preview.RouteHand(XRNode.RightHand, ray, true, false, Vector2.zero, 3, out _)
            && f.Sent.Count == 1 && (string)f.Sent[0]["type"] == "lease.acquire", "real routed trigger invokes enabled model button once");
    }

    static void SeedHeld(Fixture f)
    {
        var state = f.State(); state["input_allowed"] = true; state["ui_session_id"] = "held-ui-session";
        state["ui_owner"] = new JObject { ["actor_id"] = "actor" }; f.Drawing.SetNativeState(state);
        Set(f.Preview, "inputEnabled", true); Set(f.Preview, "mouseHeld", true);
        ((HashSet<string>)Get(f.Preview, "modifiers")).Add("CTRL");
        Set(f.Preview, "session", "helper"); Set(f.Preview, "token", "fixture-token");
        Set(f.Preview, "ownedCaptureInstance", "fixture-instance");
        Set(f.Preview, "state", new JObject { ["capture_instance"] = "fixture-instance" });
        ((PreviewInputTransportState)Get(f.Preview, "transport")).Observe("helper", 1);
    }

    static void ReleaseBarrier()
    {
        using var f = new Fixture(); SeedHeld(f); f.Click("Model tools"); f.Tick();
        Check((bool)Get(f.Preview, "endAfterRelease") && !(bool)Get(f.Preview, "mouseHeld")
            && ((HashSet<string>)Get(f.Preview, "modifiers")).Count == 0 && f.Events.Count == 1
            && (string)f.Events.Peek()["type"] == "release", "Model tools queues held synthetic cleanup before native UI end");
        Check(!f.Drawing.ObjectToolsEnabled && f.Sent.Count == 0, "pending input release cannot enable tools or end native reservation early");
        f.Fresh(); f.Tick();
        Check(!f.Drawing.ObjectToolsEnabled && (bool)Get(f.Preview, "endAfterRelease"), "telemetry clearing alone cannot replace helper release acknowledgement");
    }

    // Separate bounded async Editor entry for the actual HTTP release boundary.
    // -batchmode -nographics -executeMethod P25ObjectUiChecks.RunReleaseHttp (no -quit).
    static readonly Stack<IEnumerator> routines = new Stack<IEnumerator>();
    static object waiting;
    static string output, previousPort;
    static double deadline;
    static readonly JArray httpCases = new JArray();
    public static void RunReleaseHttp()
    {
        output = Environment.GetEnvironmentVariable("CALHACKS_P25_OBJECT_HTTP_RESULTS");
        Check(!string.IsNullOrEmpty(output) && Path.IsPathRooted(output) && !File.Exists(output), "provide new absolute external object HTTP results path");
        for (var dir = new DirectoryInfo(Path.GetDirectoryName(output)); dir != null; dir = dir.Parent)
            Check(!File.Exists(Path.Combine(dir.FullName, ".git")) && !Directory.Exists(Path.Combine(dir.FullName, ".git"))
                && !dir.Name.StartsWith("OneDrive", StringComparison.OrdinalIgnoreCase), "object HTTP evidence stays outside repository and OneDrive");
        Check(routines.Count == 0, "only one object HTTP suite may own this Editor");
        httpCases.Clear(); waiting = null;
        previousPort = Environment.GetEnvironmentVariable("CALHACKS_CAPTURE_PORT");
        deadline = EditorApplication.timeSinceStartup + 45; routines.Push(HttpSuite());
        EditorApplication.update += TickHttp;
    }
    static IEnumerator HttpSuite() { yield return HttpTransition(false); yield return HttpTransition(true); }
    static void TickHttp()
    {
        try
        {
            Check(EditorApplication.timeSinceStartup < deadline, "object HTTP suite timed out");
            if (waiting is AsyncOperation operation && !operation.isDone) return;
            if (waiting is CustomYieldInstruction custom && custom.keepWaiting) return;
            waiting = null;
            if (routines.Count == 0) { FinishHttp(null); return; }
            var routine = routines.Peek();
            if (!routine.MoveNext()) { (routines.Pop() as IDisposable)?.Dispose(); return; }
            if (routine.Current is IEnumerator nested && !(nested is CustomYieldInstruction)) routines.Push(nested);
            else waiting = routine.Current;
        }
        catch (Exception error) { FinishHttp(error); }
    }
    static void FinishHttp(Exception error)
    {
        EditorApplication.update -= TickHttp;
        while (routines.Count != 0) (routines.Pop() as IDisposable)?.Dispose();
        Environment.SetEnvironmentVariable("CALHACKS_CAPTURE_PORT", previousPort);
        File.WriteAllText(output, new JObject { ["passed"] = error == null, ["cases"] = httpCases,
            ["transport"] = "actual Draw in VR onClick + SendEvents UnityWebRequest + correlated native UI end fixture",
            ["native_or_player_launched"] = false, ["desktop_input_injected"] = false, ["physical_acceptance"] = false,
            ["error"] = error?.ToString() }.ToString());
        if (error != null) Debug.LogError(error);
        else Debug.Log("P25_OBJECT_HTTP_CHECK PASS cases=2 actual release ACK -> native UI end -> direct drawing; native/VR acceptance=False");
        EditorApplication.Exit(error == null ? 0 : 1);
    }
    static IEnumerator HttpTransition(bool good)
    {
        using var server = new ReleaseServer(good);
        Environment.SetEnvironmentVariable("CALHACKS_CAPTURE_PORT", server.Port.ToString());
        using var f = new Fixture(); SeedHeld(f); f.Click("Draw in VR"); f.Tick();
        var sender = (IEnumerator)Invoke(f.Preview, "SendEvents");
        double until = EditorApplication.timeSinceStartup + 10;
        try
        {
            while (server.Posts == 0 || (bool)Get(f.Preview, "sendingEvent"))
            {
                Check(EditorApplication.timeSinceStartup < until && sender.MoveNext(), "actual release sender must reach bounded acknowledgement");
                yield return sender.Current;
            }
        }
        finally { (sender as IDisposable)?.Dispose(); }
        Check(server.Error == null && server.Posts == 1 && server.Kind == "release", "only the real idempotent cleanup POST reaches fake loopback");
        Check(!f.Drawing.EnabledForInput, "tools remain disabled at helper response boundary");
        if (!good)
        {
            Check((bool)Get(f.Preview, "endAfterRelease") && f.Sent.Count == 0, "HTTP200 without exact ACK cannot end native UI reservation");
            f.Fresh(); f.Tick(); Check(!f.Drawing.EnabledForInput, "fresh ended telemetry cannot override missing helper ACK");
        }
        else
        {
            var end = f.Sent.Single(message => (string)message["type"] == "preview.ui.end");
            Check(!(bool)Get(f.Preview, "endAfterRelease") && f.Drawing.NativeUiTransitionPending, "real valid release ACK emits native UI end and waits for its correlated acknowledgement");
            f.Tick(); Check(!f.Drawing.EnabledForInput, "native end request alone cannot enable direct drawing");
            f.Receive("preview.ui.ended", f.State(), (string)end["id"]); f.Tick(); f.Tick();
            Check(f.Drawing.EnabledForInput && !f.Drawing.NativeUiTransitionPending,
                "only helper ACK plus actual matching native UI ended response enables direct drawing");
        }
        httpCases.Add(new JObject { ["name"] = good ? "valid_release_waits_native_end" : "invalid_release_keeps_tools_blocked", ["passed"] = true });
    }

    sealed class ReleaseServer : IDisposable
    {
        readonly TcpListener listener;
        readonly Thread worker;
        volatile bool stopped;
        int posts;
        public int Posts => Volatile.Read(ref posts);
        public string Error, Kind;
        public int Port { get; }
        public ReleaseServer(bool good)
        {
            listener = new TcpListener(IPAddress.Loopback, 0); listener.Start(); Port = ((IPEndPoint)listener.LocalEndpoint).Port;
            worker = new Thread(() => Serve(good)) { IsBackground = true }; worker.Start();
        }
        void Serve(bool good)
        {
            try
            {
                using var client = listener.AcceptTcpClient(); client.ReceiveTimeout = client.SendTimeout = 2000;
                using var stream = client.GetStream(); var header = new List<byte>();
                while (header.Count < 32768)
                {
                    int next = stream.ReadByte(); if (next < 0) throw new EndOfStreamException(); header.Add((byte)next);
                    int n = header.Count; if (n >= 4 && header[n - 4] == 13 && header[n - 3] == 10 && header[n - 2] == 13 && header[n - 1] == 10) break;
                }
                string text = Encoding.ASCII.GetString(header.ToArray()); Check(text.StartsWith("POST /input "), "release fixture receives input POST");
                int size = int.Parse(text.Split(new[] { "\r\n" }, StringSplitOptions.None).Single(line => line.StartsWith("Content-Length:", StringComparison.OrdinalIgnoreCase)).Substring(15).Trim());
                Check(size > 0 && size < 65536, "bounded fixture body"); var bytes = new byte[size]; int at = 0;
                while (at < size) { int read = stream.Read(bytes, at, size - at); if (read == 0) throw new EndOfStreamException(); at += read; }
                var request = JObject.Parse(Encoding.UTF8.GetString(bytes)); Kind = (string)request["type"]; Interlocked.Increment(ref posts);
                byte[] body = Encoding.UTF8.GetBytes(good ? new JObject { ["ok"] = true, ["seq"] = request["seq"] }.ToString() : "{}");
                byte[] prefix = Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + body.Length + "\r\nConnection: close\r\n\r\n");
                stream.Write(prefix, 0, prefix.Length); stream.Write(body, 0, body.Length); stream.Flush();
            }
            catch (Exception error) { if (!stopped) Error = error.ToString(); }
        }
        public void Dispose() { stopped = true; listener.Stop(); worker.Join(1000); }
    }
}

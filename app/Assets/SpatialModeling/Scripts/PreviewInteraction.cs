using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using System.Runtime.InteropServices;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using UnityEngine.XR;

namespace SpatialModeling
{
    // Optional P2.5 adapter. It consumes the existing stabilized ray; never writes
    // table/panel poses, capture settings, native geometry or history itself.
    public sealed class PreviewInteraction : MonoBehaviour
    {
        public static PreviewInteraction Current { get; private set; }
        public static bool BlocksDesktopShortcuts => Current != null && (Current.inputEnabled || Current.focusRequested || Current.endAfterRelease
            || (Current.Drawing != null && Current.Drawing.IsNativeUiOwned));
        public static bool Requested => Environment.GetEnvironmentVariable("CALHACKS_P25") == "1"
            || Array.IndexOf(Environment.GetCommandLineArgs(), "--p25") >= 0;
        public bool CapturesScroll { get; private set; }
        public XRNode PrimaryHand { get; private set; } = XRNode.RightHand;
        public string Notice { get; private set; } = "Focus Blender to enable native preview input";
        public PreviewSpatialDrawing Drawing { get; private set; }
        BlenderScreen screen;
        HostScene scene;
        RectTransform panel, keyboard;
        Text feedback;
        readonly List<Button> buttons = new List<Button>();
        readonly Queue<JObject> events = new Queue<JObject>();
        JObject state;
        JObject pendingPointer;
        string session = "", token = "", mouseButton = "left";
        readonly PreviewInputTransportState transport = new PreviewInputTransportState();
        bool readingState, sendingEvent;
        bool inputEnabled, triggerWasDown, mouseHeld, keyboardShown, shiftText;
        bool focusRequested, endAfterRelease, releaseQueued, spatialRequested;
        readonly HashSet<string> modifiers = new HashSet<string>();
        float nextPointer, nextScroll, nextHeartbeat;
        Vector2 lastPoint;
        string ownedCaptureInstance = "";
        [DllImport("user32.dll")]
        static extern bool AllowSetForegroundWindow(uint processId);

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            if (Requested && FindFirstObjectByType<HostScene>() != null && FindFirstObjectByType<PreviewInteraction>() == null)
                new GameObject("P2.5 preview interaction").AddComponent<PreviewInteraction>();
        }

        void OnEnable()
        {
            if (!Requested) { enabled = false; return; }
            Current = this;
            scene = FindFirstObjectByType<HostScene>();
            Drawing = GetComponent<PreviewSpatialDrawing>() ?? gameObject.AddComponent<PreviewSpatialDrawing>();
            Drawing.Initialize(scene, scene != null ? scene.ObjectDisplayMaterial : null);
            OVRManager.HMDUnmounted += Suspend;
            OVRManager.VrFocusLost += Suspend;
            StartCoroutine(ReadState());
            StartCoroutine(SendEvents());
        }

        void OnDisable()
        {
            // Server watchdog is the final cleanup if this object's coroutine is
            // destroyed during a held gesture or an HTTP failure.
            Suspend();
            OVRManager.HMDUnmounted -= Suspend;
            OVRManager.VrFocusLost -= Suspend;
            StopAllCoroutines();
            if (endAfterRelease && Drawing != null)
            {
                var drawing = Drawing;
                var link = scene != null ? scene.Link : null;
                var identity = drawing.Session.RequestIdentity;
                string uiToken = (string)drawing.NativeState["ui_session_id"];
                new GameObject("P2.5 pending input release").AddComponent<PreviewInputCleanup>().Begin(
                    BlenderScreen.CaptureBaseUrl, ownedCaptureInstance, () =>
                    {
                        if (drawing != null) drawing.EndNativeUi();
                        else if (identity != null && !string.IsNullOrEmpty(uiToken))
                        {
                            identity["ui_session_id"] = uiToken;
                            link?.SendEnvelope(NativeEditSession.Envelope("preview.ui.end", identity));
                        }
                        else link?.Reconnect(); // resolve a possible late begin grant after component destruction
                    });
            }
            if (Current == this) Current = null;
            if (panel != null) Destroy(panel.gameObject);
            if (keyboard != null) Destroy(keyboard.gameObject);
        }

        void Update()
        {
            if (screen == null) screen = FindFirstObjectByType<BlenderScreen>();
            if (screen != null && screen.Placement != null && panel == null) BuildControls();
            bool shown = screen != null && screen.Visible && screen.HasImage && screen.Placement.gameObject.activeInHierarchy;
            if (panel != null) panel.gameObject.SetActive(shown);
            if (keyboard != null) keyboard.gameObject.SetActive(shown && keyboardShown);
            if (!shown || scene == null || !scene.IsCurrent) Suspend();
            if (focusRequested && !endAfterRelease && Drawing != null && Drawing.IsNativeUiOwned)
            {
                if (MatchesNativeHost())
                {
                    focusRequested = false; inputEnabled = true;
                    ownedCaptureInstance = (string)state["capture_instance"] ?? "";
                    // Cooperatively pass our foreground privilege, if we have
                    // it. Never attach input queues or alter Windows settings.
                    if ((Application.platform == RuntimePlatform.WindowsPlayer || Application.platform == RuntimePlatform.WindowsEditor)
                        && (long?)state?["helper_pid"] > 0)
                        AllowSetForegroundWindow((uint)(long)state["helper_pid"]);
                    Enqueue(new JObject { ["type"] = "focus" });
                }
                else Notice = "Capture must select a window from the connected Blender host";
            }
            if (spatialRequested && !endAfterRelease && Drawing != null && !Drawing.IsNativeUiOwned)
            { spatialRequested = false; Drawing.SetEnabled(true); }
            if (endAfterRelease && !releaseQueued && session.Length != 0 && token.Length != 0)
            { Enqueue(new JObject { ["type"] = "release" }); releaseQueued = true; }
            if (inputEnabled && Time.unscaledTime >= nextHeartbeat)
            { nextHeartbeat = Time.unscaledTime + .25f; Enqueue(new JObject { ["type"] = "heartbeat" }); }
            if (feedback != null)
                feedback.text = "P2.5 · " + (inputEnabled ? "Native UI" : "Native UI off") + " · Mouse: " + mouseButton
                    + " · " + (PrimaryHand == XRNode.RightHand ? "Right" : "Left") + " pointer\n" + Notice
                    + "\n" + (Drawing != null ? Drawing.StatusText : "Waiting for spatial bridge");
        }

        public void TrackingLost(XRNode hand)
        { if (hand == PrimaryHand) { Suspend(); triggerWasDown = false; } }

        public void Suspend()
        {
            ReleaseNative();
            if (inputEnabled || focusRequested || (Drawing != null && Drawing.IsNativeUiOwned)) RequestEndNativeUi();
            inputEnabled = false;
            focusRequested = false;
            CapturesScroll = false;
            if (Drawing != null) { Drawing.Cancel(); Drawing.SetEnabled(false); }
        }

        public bool RouteHand(XRNode hand, Ray ray, bool trigger, bool grip, Vector2 axis, float nearest, out float distance)
        {
            distance = 0;
            if (hand != PrimaryHand) return false;
            bool pressed = trigger && !triggerWasDown;
            bool released = !trigger && triggerWasDown;
            triggerWasDown = trigger;
            CapturesScroll = false;
            if (grip) { ReleaseNative(); Drawing?.Cancel(); return false; }
            Button hit = null; float uiDistance = float.PositiveInfinity;
            foreach (var button in buttons)
            {
                if (button == null || !button.gameObject.activeInHierarchy) continue;
                var rect = button.GetComponent<RectTransform>();
                if (!Hit(rect, ray, out var d) || d > nearest || d >= uiDistance) continue;
                uiDistance = d; hit = button;
            }
            if (hit != null)
            {
                ReleasePointer(); distance = uiDistance;
                if (pressed) hit.onClick.Invoke();
                return true;
            }
            if (keyboard != null && keyboard.gameObject.activeInHierarchy && Hit(keyboard, ray, out var keyboardDistance)
                && keyboardDistance <= nearest)
            { ReleasePointer(); distance = keyboardDistance; return true; }
            if (screen != null && screen.TryPreviewPoint(ray, out var point, out var imageDistance) && imageDistance <= nearest)
            {
                distance = imageDistance;
                if (PreviewInputMapping.CanRoute(inputEnabled, Ready(), true, false, true))
                {
                    CapturesScroll = true; lastPoint = point;
                    if (Time.unscaledTime >= nextPointer)
                    { nextPointer = Time.unscaledTime + .025f; pendingPointer = At("pointer", point); }
                    if (pressed)
                    {
                        FlushPointer();
                        var e = At("button", point); e["button"] = mouseButton; e["action"] = "down";
                        Enqueue(e); mouseHeld = true;
                    }
                    if (released && mouseHeld)
                    { var e = At("button", point); e["button"] = mouseButton; e["action"] = "up"; Enqueue(e); mouseHeld = false; }
                    if (axis.sqrMagnitude > .16f && Time.unscaledTime >= nextScroll)
                    {
                        nextScroll = Time.unscaledTime + .16f;
                        var e = At("scroll", point); e["dx"] = Mathf.Abs(axis.x) > .5f ? Mathf.Sign(axis.x) : 0;
                        e["dy"] = Mathf.Abs(axis.y) > .5f ? Mathf.Sign(axis.y) : 0; Enqueue(e);
                    }
                }
                else ReleaseNative();
                // The image is a native-input target even when admission is refused.
                // Never let the same trigger become an object/table edit.
                return true;
            }
            ReleasePointer();
            if (Drawing != null && Drawing.TryAim(ray, out var drawPoint))
            {
                float d = Vector3.Distance(ray.origin, drawPoint);
                if (d <= nearest) { distance = d; if (pressed) Drawing.Press(ray); return true; }
            }
            return false;
        }

        static bool Hit(RectTransform rect, Ray ray, out float d)
        {
            d = 0;
            return rect != null && new Plane(rect.forward, rect.position).Raycast(ray, out d) && d > 0 && d <= 4
                && rect.rect.Contains((Vector2)rect.InverseTransformPoint(ray.GetPoint(d)));
        }

        bool MatchesNativeHost() => state != null && Drawing != null && Drawing.NativeProcessId > 0
            && (long?)state["selection"]?["pid"] == Drawing.NativeProcessId;
        bool Ready() => state != null && (bool?)state["ready"] == true && (bool?)state["focused"] == true
            && MatchesNativeHost() && Drawing.IsNativeUiOwned && screen != null
            && PreviewInputMapping.FrameMatches(screen.DisplayedCaptureInstance, screen.DisplayedSelectionGeneration,
                (string)state["capture_instance"], (long?)state["capture_generation"] ?? -1)
            && !string.IsNullOrEmpty(screen.DisplayedCaptureGeometry)
            && screen.DisplayedCaptureGeometry == (string)state["capture_geometry"];
        void FocusNativeUi()
        {
            if (endAfterRelease) { Notice = "Waiting for native input cleanup before focusing again"; return; }
            if (state == null || (bool?)state["enabled"] != true || session.Length == 0)
            { Notice = "Start the P2.5 helper with input enabled and select the connected Blender window"; return; }
            Drawing.Cancel(); Drawing.SetEnabled(false);
            focusRequested = true; spatialRequested = false;
            Drawing.BeginNativeUi();
            Notice = "Waiting for native UI editing permission";
        }
        void RequestEndNativeUi()
        {
            inputEnabled = focusRequested = false;
            if (endAfterRelease) return;
            events.Clear(); pendingPointer = null; mouseHeld = false; modifiers.Clear();
            endAfterRelease = true; releaseQueued = false;
            // release is idempotent cleanup, never a replay of a model operation.
            // Keep the native lease until the helper confirms all held input up.
        }
        void BeginSpatial()
        {
            if (Drawing.NativeModalActive)
            { Notice = "Finish the native operation with Enter or Escape before switching to VR drawing"; return; }
            inputEnabled = focusRequested = false;
            if (Drawing.IsNativeUiOwned) RequestEndNativeUi();
            spatialRequested = true;
        }
        static JObject At(string type, Vector2 p) => new JObject { ["type"] = type, ["x"] = p.x, ["y"] = p.y };
        void FlushPointer() { if (pendingPointer != null) { Enqueue(pendingPointer); pendingPointer = null; } }
        void Enqueue(JObject e)
        {
            if (session.Length == 0 || token.Length == 0) return;
            if (events.Count >= 64)
            {
                events.Clear(); pendingPointer = null; inputEnabled = mouseHeld = false; modifiers.Clear();
                Notice = "Input backlog cancelled; focus Blender again";
                RequestEndNativeUi(); return;
            }
            events.Enqueue(e);
        }
        void ReleaseNative()
        {
            pendingPointer = null;
            if (mouseHeld || modifiers.Count != 0)
            { Enqueue(new JObject { ["type"] = "release" }); mouseHeld = false; modifiers.Clear(); }
        }
        void ReleasePointer()
        {
            pendingPointer = null;
            if (!mouseHeld) return;
            var e = At("button", lastPoint); e["button"] = mouseButton; e["action"] = "up";
            Enqueue(e); mouseHeld = false;
        }
        void Key(string key)
        {
            if (!inputEnabled || !Ready()) { Notice = "Focus Blender before using the keyboard"; return; }
            Enqueue(new JObject { ["type"] = "key", ["key"] = key, ["action"] = "press" });
        }
        void Character(string text)
        {
            if (!inputEnabled || !Ready()) { Notice = "Focus Blender before typing"; return; }
            if (modifiers.Count != 0)
            {
                string key = text.ToUpperInvariant();
                switch (text)
                {
                    case "-": key = "MINUS"; break;
                    case "=": case "+": key = "EQUALS"; break;
                    case "[": key = "LEFTBRACKET"; break;
                    case "]": key = "RIGHTBRACKET"; break;
                    case ";": key = "SEMICOLON"; break;
                    case "'": key = "QUOTE"; break;
                    case "\\": key = "BACKSLASH"; break;
                    case ",": key = "COMMA"; break;
                    case ".": key = "PERIOD"; break;
                    case "/": key = "SLASH"; break;
                    case "`": key = "GRAVE"; break;
                }
                bool temporaryShift = text == "+" && !modifiers.Contains("SHIFT");
                if (temporaryShift) Enqueue(new JObject { ["type"] = "key", ["key"] = "SHIFT", ["action"] = "down" });
                Key(key);
                if (temporaryShift) Enqueue(new JObject { ["type"] = "key", ["key"] = "SHIFT", ["action"] = "up" });
            }
            else Enqueue(new JObject { ["type"] = "text", ["text"] = shiftText ? text.ToUpperInvariant() : text });
        }
        void Modifier(string key)
        {
            if (!inputEnabled || !Ready()) return;
            bool down = !modifiers.Contains(key);
            if (down) modifiers.Add(key); else modifiers.Remove(key);
            Enqueue(new JObject { ["type"] = "key", ["key"] = key, ["action"] = down ? "down" : "up" });
            Notice = "Held modifiers: " + string.Join(" + ", modifiers);
        }
        void Shortcut(string key, bool shift = false)
        {
            if (!inputEnabled || !Ready()) return;
            bool ctrl = modifiers.Contains("CTRL"), sh = modifiers.Contains("SHIFT"), alt = modifiers.Contains("ALT");
            if (alt) Enqueue(new JObject { ["type"] = "key", ["key"] = "ALT", ["action"] = "up" });
            if (!shift && sh) Enqueue(new JObject { ["type"] = "key", ["key"] = "SHIFT", ["action"] = "up" });
            if (!ctrl) Enqueue(new JObject { ["type"] = "key", ["key"] = "CTRL", ["action"] = "down" });
            if (shift && !sh) Enqueue(new JObject { ["type"] = "key", ["key"] = "SHIFT", ["action"] = "down" });
            Key(key);
            if (shift && !sh) Enqueue(new JObject { ["type"] = "key", ["key"] = "SHIFT", ["action"] = "up" });
            if (!ctrl) Enqueue(new JObject { ["type"] = "key", ["key"] = "CTRL", ["action"] = "up" });
            if (!shift && sh) Enqueue(new JObject { ["type"] = "key", ["key"] = "SHIFT", ["action"] = "down" });
            if (alt) Enqueue(new JObject { ["type"] = "key", ["key"] = "ALT", ["action"] = "down" });
        }

        IEnumerator ReadState()
        {
            while (true)
            {
                if (sendingEvent) { yield return null; continue; }
                string url = BlenderScreen.CaptureBaseUrl;
                if (url != null)
                {
                    readingState = true;
                    using (var request = UnityWebRequest.Get(url + "/input/state"))
                    {
                        request.timeout = 2; yield return request.SendWebRequest();
                        if (request.result == UnityWebRequest.Result.Success)
                        {
                            JObject fresh = null;
                            try { fresh = JObject.Parse(request.downloadHandler.text); }
                            catch (Exception) { FailTransport("Input helper returned invalid state"); }
                            if (fresh != null)
                            {
                                string nextSession = (string)fresh["session"] ?? "";
                                if (session != nextSession)
                                {
                                    bool wasActive = inputEnabled || focusRequested || (Drawing != null && Drawing.IsNativeUiOwned);
                                    events.Clear(); pendingPointer = null; mouseHeld = inputEnabled = false; modifiers.Clear();
                                    releaseQueued = false;
                                    session = nextSession;
                                    Drawing?.Cancel();
                                    if (wasActive) RequestEndNativeUi();
                                }
                                state = fresh; token = (string)fresh["token"] ?? "";
                                if (session.Length != 0 && token.Length != 0 && (long?)fresh["next_seq"] >= 1)
                                    transport.Observe(session, (long)fresh["next_seq"]);
                                else transport.Unknown();
                                if ((bool?)fresh["enabled"] != true) Notice = "Start this feature's helper with --enable-input";
                                else if (!Ready())
                                {
                                    ReleaseNative();
                                    string why = (string)fresh["reason"];
                                    Notice = !MatchesNativeHost() ? "Capture must select the connected Blender host"
                                        : !Drawing.IsNativeUiOwned ? "Use Focus Blender to begin native preview interaction"
                                        : !string.IsNullOrEmpty(why) ? why : "Waiting for the selected window's displayed frame and focus";
                                }
                            }
                        }
                        else FailTransport("P2.5 input helper unavailable");
                    }
                    readingState = false;
                }
                yield return new WaitForSecondsRealtime(.5f);
            }
        }

        IEnumerator SendEvents()
        {
            while (true)
            {
                if (events.Count == 0 && pendingPointer != null) FlushPointer();
                if (events.Count == 0 || BlenderScreen.CaptureBaseUrl == null || readingState || !transport.Synchronized)
                { yield return null; continue; }
                var e = events.Dequeue(); string sentSession = session;
                string kind = (string)e["type"];
                if (kind != "release" && kind != "select_window" && !(kind == "focus" ? Drawing.IsNativeUiOwned && MatchesNativeHost() : Ready()))
                { FailTransport("Input context changed; pending actions cancelled"); continue; }
                e["session"] = sentSession; e["token"] = token; e["seq"] = transport.TakeSequence();
                sendingEvent = true;
                using (var request = new UnityWebRequest(BlenderScreen.CaptureBaseUrl + "/input", "POST"))
                {
                    request.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(e.ToString(Newtonsoft.Json.Formatting.None)));
                    request.downloadHandler = new DownloadHandlerBuffer();
                    request.SetRequestHeader("Content-Type", "application/json"); request.timeout = 2;
                    yield return request.SendWebRequest();
                    if (session != sentSession) { sendingEvent = false; continue; }
                    if (request.result != UnityWebRequest.Result.Success)
                    {
                        FailTransport("Input stopped: " + request.responseCode + ". Refresh/focus; the action was not retried.");
                    }
                    else if ((string)e["type"] == "release" && endAfterRelease)
                    {
                        if (ownedCaptureInstance.Length != 0 && ownedCaptureInstance != (string)state?["capture_instance"])
                        { Notice = "Input helper restarted; release status is unknown. Check native input and reconnect."; releaseQueued = true; }
                        else
                        { releaseQueued = endAfterRelease = false; ownedCaptureInstance = ""; Drawing.EndNativeUi(); Notice = "Native UI input released"; }
                    }
                    else if ((string)e["type"] == "focus")
                    {
                        // The helper acknowledged exact-window foreground after
                        // verification. A later event still rechecks it natively.
                        if (state != null) state["focused"] = true;
                        Notice = "Blender focused · trigger: mouse · stick: scroll · grip: move preview";
                    }
                }
                sendingEvent = false;
            }
        }

        void FailTransport(string reason)
        {
            bool needsCleanup = inputEnabled || focusRequested || endAfterRelease || (Drawing != null && Drawing.IsNativeUiOwned);
            transport.Unknown(); state = null; events.Clear(); pendingPointer = null;
            inputEnabled = focusRequested = mouseHeld = false; modifiers.Clear();
            releaseQueued = false;
            if (needsCleanup) RequestEndNativeUi();
            Notice = reason;
        }

        void BuildControls()
        {
            panel = MakePanel("P2.5 controls", new Vector2(0, -1120), new Vector2(1840, 540));
            AddButton(panel, "Focus Blender", 0, 0, FocusNativeUi);
            AddButton(panel, "Disable input", 1, 0, Suspend);
            AddButton(panel, "Keyboard", 2, 0, () => keyboardShown = !keyboardShown);
            AddButton(panel, "Mouse left", 3, 0, () => { ReleaseNative(); mouseButton = "left"; });
            AddButton(panel, "Mouse right", 4, 0, () => { ReleaseNative(); mouseButton = "right"; });
            AddButton(panel, "Mouse middle", 5, 0, () => { ReleaseNative(); mouseButton = "middle"; });
            AddButton(panel, "Other hand", 6, 0, () => { Suspend(); PrimaryHand = PrimaryHand == XRNode.RightHand ? XRNode.LeftHand : XRNode.RightHand; triggerWasDown = true; });
            AddButton(panel, "Escape / cancel", 0, 1, () => { Drawing.Cancel(); Key("ESC"); });
            AddButton(panel, "Enter", 1, 1, () => Key("ENTER"));
            AddButton(panel, "Undo", 2, 1, () => { if (Drawing.EnabledForInput) Drawing.Undo(); else Shortcut("Z"); });
            AddButton(panel, "Redo", 3, 1, () => { if (Drawing.EnabledForInput) Drawing.Redo(); else Shortcut("Z", true); });
            AddButton(panel, "Save", 4, 1, () => { if (Drawing.EnabledForInput) Drawing.Save(); else Shortcut("S"); });
            AddButton(panel, "Search F3", 5, 1, () => Key("F3"));
            AddButton(panel, "Next window", 6, 1, NextWindow);
            AddButton(panel, "Draw in VR", 0, 2, BeginSpatial);
            AddButton(panel, "Line", 1, 2, () => Drawing.SelectTool("line"));
            AddButton(panel, "Rectangle", 2, 2, () => Drawing.SelectTool("rectangle"));
            AddButton(panel, "Circle", 3, 2, () => Drawing.SelectTool("circle"));
            AddButton(panel, "New XY sketch", 4, 2, () => Drawing.CreateSketch("XY"));
            AddButton(panel, "New XZ sketch", 5, 2, () => Drawing.CreateSketch("XZ"));
            AddButton(panel, "New YZ sketch", 6, 2, () => Drawing.CreateSketch("YZ"));
            feedback = MakeText(panel, new Vector2(0, -155), new Vector2(1780, 160), "", 25);
            // A temporary keyboard overlays the lower preview while typing. It
            // must not be placed metres below the screen (possibly below floor).
            keyboard = MakePanel("P2.5 keyboard", new Vector2(0, -200), new Vector2(1840, 560));
            keyboard.localPosition += Vector3.back * 8f;
            string[] rows = { "1234567890-+=", "qwertyuiop[]", "asdfghjkl;'\\", "zxcvbnm,./`" };
            for (int row = 0; row < rows.Length; row++) for (int col = 0; col < rows[row].Length; col++)
            {
                string c = rows[row][col].ToString();
                AddButton(keyboard, c, col, row, () => Character(c), 145, 12);
            }
            string[] names = { "CTRL", "SHIFT", "ALT", "TAB", "BACKSPACE", "ENTER", "SPACE", "DELETE", "LEFT", "RIGHT", "UP", "DOWN" };
            for (int i = 0; i < names.Length; i++)
            {
                string key = names[i]; AddButton(keyboard, key, i, 4, () =>
                { if (key == "CTRL" || key == "ALT" || key == "SHIFT") Modifier(key); else Key(key); }, 145, 12);
            }
            AddButton(keyboard, "Caps", 0, 5, () => shiftText = !shiftText, 145, 12);
            AddButton(keyboard, "Close", 1, 5, () => keyboardShown = false, 145, 12);
            AddButton(keyboard, "Double click", 2, 5, () =>
            {
                if (!inputEnabled || !Ready()) return;
                var e = At("button", lastPoint); e["button"] = "left"; e["action"] = "double_click"; Enqueue(e);
            }, 145, 12);
            AddButton(keyboard, "Home", 3, 5, () => Key("HOME"), 145, 12);
            AddButton(keyboard, "End", 4, 5, () => Key("END"), 145, 12);
            string[] extraKeys = { "DECIMAL", "NUMPAD0", "NUMPAD1", "NUMPAD3", "NUMPAD7", "PAGEUP", "PAGEDOWN" };
            for (int i = 0; i < extraKeys.Length; i++)
            { string key = extraKeys[i]; AddButton(keyboard, key, i + 5, 5, () => Key(key), 145, 12); }
            keyboard.gameObject.SetActive(false);
        }

        void NextWindow()
        {
            ReleaseNative();
            var windows = state?["windows"] as JArray;
            if (windows == null || windows.Count == 0) { Notice = "No other Blender windows available"; return; }
            long current = (long?)state?["selection"]?["hwnd"] ?? 0; int at = -1;
            for (int i = 0; i < windows.Count; i++) if ((long?)windows[i]["hwnd"] == current) at = i;
            var next = windows[(at + 1) % windows.Count];
            inputEnabled = false; Enqueue(new JObject { ["type"] = "select_window", ["hwnd"] = next["hwnd"] });
            Notice = "Selected next Blender window; focus it explicitly to interact";
        }
        RectTransform MakePanel(string name, Vector2 position, Vector2 size)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Image));
            var rect = go.GetComponent<RectTransform>(); rect.SetParent(screen.Placement, false);
            rect.anchoredPosition = position; rect.sizeDelta = size;
            go.GetComponent<Image>().color = new Color(.015f, .035f, .06f, .98f);
            return rect;
        }
        void AddButton(RectTransform parent, string label, int col, int row, Action action, float width = 250, int columns = 7)
        {
            var go = new GameObject(label, typeof(RectTransform), typeof(Image), typeof(Button));
            var rect = go.GetComponent<RectTransform>(); rect.SetParent(parent, false);
            rect.sizeDelta = new Vector2(width - 8, 64);
            rect.anchoredPosition = new Vector2((col - (columns - 1) * .5f) * width, parent.rect.height * .5f - 48 - row * 72);
            go.GetComponent<Image>().color = new Color(.08f, .24f, .34f, 1);
            var button = go.GetComponent<Button>(); button.onClick.AddListener(() => action()); buttons.Add(button);
            MakeText(rect, Vector2.zero, rect.sizeDelta, label, columns == 12 ? 22 : 25);
        }
        static Text MakeText(Transform parent, Vector2 position, Vector2 size, string value, int fontSize)
        {
            var go = new GameObject("Label", typeof(RectTransform), typeof(Text));
            var rect = go.GetComponent<RectTransform>(); rect.SetParent(parent, false); rect.anchoredPosition = position; rect.sizeDelta = size;
            var t = go.GetComponent<Text>(); t.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            t.fontSize = fontSize; t.alignment = TextAnchor.MiddleCenter; t.color = Color.white; t.text = value; t.raycastTarget = false;
            return t;
        }
    }
}

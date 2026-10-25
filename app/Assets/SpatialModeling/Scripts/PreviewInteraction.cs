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
            || Current.numbersShown || Current.windowsShown || Current.windowResuming || Current.NativeInputOwned);
        public static bool Requested => Environment.GetEnvironmentVariable("CALHACKS_P25") == "1"
            || Array.IndexOf(Environment.GetCommandLineArgs(), "--p25") >= 0;
        public bool CapturesScroll { get; private set; }
        public bool OwnsControllerButtons => inputEnabled || focusRequested || windowResuming || endAfterRelease || NativeInputOwned;
        const string PointerHandPreference = "SpatialModeling.PreviewPointerLeft";
        public XRNode PrimaryHand { get; private set; } = XRNode.RightHand;
        public void SetPointerHand(XRNode hand)
        {
            if (hand != XRNode.LeftHand && hand != XRNode.RightHand) return;
            Suspend(); PrimaryHand = hand; triggerWasDown = true;
            PlayerPrefs.SetInt(PointerHandPreference, hand == XRNode.LeftHand ? 1 : 0); PlayerPrefs.Save();
        }
        public string Notice { get; private set; } = "Focus Blender to enable native preview input";
        public PreviewSpatialDrawing Drawing { get; private set; }
        BlenderScreen screen;
        HostScene scene;
        RectTransform panel, keyboard, modelToolsPanel;
        RectTransform shortcutPanel, numberPanel, windowPanel, mouseOptionsPanel;
        readonly List<Button> basicKeys = new List<Button>(), fullKeys = new List<Button>(), shortcutButtons = new List<Button>();
        readonly List<Button> numberFields = new List<Button>();
        readonly List<Button> windowButtons = new List<Button>();
        readonly NativePreviewAuthority windowAuthority = new NativePreviewAuthority();
        Text windowFeedback;
        string windowListSignature = "", windowAwaitSession = "";
        bool windowsShown, windowResuming, windowReleaseQueued, inputResync;
        int windowPage;
        long awaitedWindow;
        float windowResumeUntil;
        Text numberFeedback, shortcutFeedback;
        Text feedback, objectTargetText, actionFeedback;
        bool questControls = true, mouseOptionsShown, sideWasDown, stickWasDown, panShift;
        string heldMouseButton = "left", lastControlAction = "";
        Vector2 panPoint;
        Button pulsedButton;
        float pulseUntil;
        Button moveStepButton, turnStepButton, primitiveSizeButton, focusButton;
        readonly List<Button> buttons = new List<Button>();
        readonly Queue<JObject> events = new Queue<JObject>();
        JObject state;
        JObject pendingPointer;
        string session = "", token = "", mouseButton = "left";
        readonly PreviewInputTransportState transport = new PreviewInputTransportState();
        bool readingState, sendingEvent;
        bool inputEnabled, triggerWasDown, mouseHeld, keyboardShown, shiftText;
        bool focusRequested, endAfterRelease, releaseQueued, spatialRequested, objectsRequested, modelToolsShown;
        string lastInputFailure = "", lastLoggedNotice = "", lastLoggedGates = "";
        bool numbersShown, shortcutsShown, fullKeyboard, editorPointSet;
        int shortcutPage;
        Vector2 editorPoint;
        string editorInstance, editorGeometry, editorIdentity;
        long editorGeneration;
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
            PrimaryHand = PlayerPrefs.GetInt(PointerHandPreference, 0) == 1 ? XRNode.LeftHand : XRNode.RightHand;
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
            if (modelToolsPanel != null) Destroy(modelToolsPanel.gameObject);
            if (shortcutPanel != null) Destroy(shortcutPanel.gameObject);
            if (numberPanel != null) Destroy(numberPanel.gameObject);
            if (windowPanel != null) Destroy(windowPanel.gameObject);
            if (mouseOptionsPanel != null) Destroy(mouseOptionsPanel.gameObject);
        }

        void Update()
        {
            if (screen == null) screen = FindFirstObjectByType<BlenderScreen>();
            if (screen != null && screen.Placement != null && panel == null) BuildControls();
            // Recovery controls remain reachable if a dialog closes or capture
            // is temporarily unavailable. Fresh image identity still gates input.
            bool shown = screen != null && screen.Visible && screen.Placement != null && screen.Placement.gameObject.activeInHierarchy;
            if (panel != null) panel.gameObject.SetActive(shown);
            if (keyboard != null) keyboard.gameObject.SetActive(shown && keyboardShown);
            if (modelToolsPanel != null) modelToolsPanel.gameObject.SetActive(shown && modelToolsShown);
            if (shortcutPanel != null) shortcutPanel.gameObject.SetActive(shown && shortcutsShown);
            if (numberPanel != null) numberPanel.gameObject.SetActive(shown && numbersShown);
            if (windowPanel != null) windowPanel.gameObject.SetActive(shown && windowsShown);
            if (mouseOptionsPanel != null) mouseOptionsPanel.gameObject.SetActive(shown && mouseOptionsShown);
            if (!shown || scene == null || !scene.IsCurrent) Suspend();
            if (focusRequested && !endAfterRelease && Drawing != null && Drawing.IsNativeUiOwned)
            {
                if (MatchesNativeHost())
                {
                    focusRequested = false; inputEnabled = true;
                    ownedCaptureInstance = (string)state["capture_instance"] ?? "";
                    if (Drawing.IsNativeUiOwned) windowAuthority.Capture(Drawing.Session, Drawing.NativeState, state);
                    // Cooperatively pass our foreground privilege, if we have
                    // it. Never attach input queues or alter Windows settings.
                    if ((Application.platform == RuntimePlatform.WindowsPlayer || Application.platform == RuntimePlatform.WindowsEditor)
                        && (long?)state?["helper_pid"] > 0)
                        AllowSetForegroundWindow((uint)(long)state["helper_pid"]);
                    Enqueue(new JObject { ["type"] = "focus" });
                }
                else Notice = "Capture must select a window from the connected Blender host";
            }
            if (windowResuming && !endAfterRelease)
            {
                bool newWindowState = (awaitedWindow == 0 || (long?)state?["selection"]?["hwnd"] == awaitedWindow)
                    && ((string)state?["session"] != windowAwaitSession || inputResync) && transport.Synchronized;
                if (!NativeInputOwned || Time.unscaledTime > windowResumeUntil) RequestEndNativeUi();
                else if (newWindowState && Ready() && !windowReleaseQueued)
                {
                    Enqueue(new JObject { ["type"] = "release" }); windowReleaseQueued = true;
                    Notice = "New Blender window ready; confirming old input cleanup";
                }
            }
            if (spatialRequested && !endAfterRelease && Drawing != null && !Drawing.IsNativeUiOwned && !Drawing.NativeUiTransitionPending)
            { spatialRequested = false; modelToolsShown = false; Drawing.SetEnabled(true); }
            if (objectsRequested && !endAfterRelease && Drawing != null && !Drawing.IsNativeUiOwned && !Drawing.NativeUiTransitionPending)
            {
                if (Drawing.SetObjectToolsEnabled(true))
                { objectsRequested = false; modelToolsShown = true; keyboardShown = false; }
            }
            if (endAfterRelease && !releaseQueued && session.Length != 0 && token.Length != 0)
            { Enqueue(new JObject { ["type"] = "release" }); releaseQueued = true; }
            if (inputEnabled && Time.unscaledTime >= nextHeartbeat)
            { nextHeartbeat = Time.unscaledTime + .25f; Enqueue(new JObject { ["type"] = "heartbeat" }); }
            RefreshInputIndicator();
            if (feedback != null)
                feedback.text = "Blender input: " + InputMode + (questControls ? " Â· Quest controls" : " Â· Mouse mode: " + mouseButton)
                    + " Â· " + (PrimaryHand == XRNode.RightHand ? "Right" : "Left") + " pointer\n" + Notice
                    + "\n" + (Drawing != null ? Drawing.StatusText : "Waiting for spatial bridge");
            if (Notice != lastLoggedNotice)
            { lastLoggedNotice = Notice; Debug.Log("P25_INPUT_NOTICE " + Notice); }
            string gates = "requested=" + (focusRequested || inputEnabled || windowResuming) + " owned=" + NativeInputOwned
                + " helperReady=" + ((bool?)state?["ready"] == true) + " focused=" + ((bool?)state?["focused"] == true)
                + " host=" + MatchesNativeHost() + " image=" + (screen != null && screen.HasImage)
                + " frame=" + (screen != null && state != null && PreviewInputMapping.FrameMatches(screen.DisplayedCaptureInstance,
                    screen.DisplayedSelectionGeneration, (string)state["capture_instance"], (long?)state["capture_generation"] ?? -1))
                + " geometry=" + (screen != null && !string.IsNullOrEmpty(screen.DisplayedCaptureGeometry)
                    && screen.DisplayedCaptureGeometry == (string)state?["capture_geometry"])
                + " releaseError=" + ((bool?)state?["release_error"] != false) + " cleanup=" + endAfterRelease;
            if (gates != lastLoggedGates) { lastLoggedGates = gates; Debug.Log("P25_INPUT_GATES " + gates); }
            if (modelToolsShown) RefreshObjectLabels();
            if (numbersShown) RefreshNumbers();
            if (windowsShown) RefreshWindows();
            RefreshControlFeedback();
            if (shortcutsShown && shortcutFeedback != null) shortcutFeedback.text = "Page " + (shortcutPage + 1) + " / 2 Â· click the intended Blender editor before using these shortcuts\n" + Notice;
        }

        public void TrackingLost(XRNode hand)
        { if (hand == PrimaryHand) { Suspend(); triggerWasDown = false; } }

        public void Suspend()
        {
            ReleaseNative();
            if (inputEnabled || focusRequested || windowResuming || NativeInputOwned) RequestEndNativeUi();
            windowAuthority.Clear(); windowResuming = windowReleaseQueued = inputResync = windowsShown = false;
            inputEnabled = false;
            focusRequested = false;
            objectsRequested = spatialRequested = modelToolsShown = false;
            numbersShown = shortcutsShown = editorPointSet = false;
            mouseOptionsShown = false;
            Drawing?.Numeric.Invalidate();
            CapturesScroll = false;
            if (Drawing != null) { Drawing.Cancel(); Drawing.SetEnabled(false); Drawing.SetObjectToolsEnabled(false); }
        }

        public bool RouteHand(XRNode hand, Ray ray, bool trigger, bool grip, Vector2 axis, float nearest, out float distance)
            => RoutePointer(hand, ray, trigger, grip, axis, nearest, out distance, false, false);
        public bool RouteControllerHand(XRNode hand, Ray ray, bool trigger, bool grip, Vector2 axis, float nearest, out float distance, bool stick)
            => RoutePointer(hand, ray, trigger, grip, axis, nearest, out distance, true, stick);
        bool RoutePointer(XRNode hand, Ray ray, bool trigger, bool grip, Vector2 axis, float nearest, out float distance, bool controller, bool stick)
        {
            distance = 0;
            if (hand != PrimaryHand) return false;
            bool pressed = trigger && !triggerWasDown;
            bool released = !trigger && triggerWasDown;
            triggerWasDown = trigger;
            bool sidePressed = grip && !sideWasDown, stickPressed = stick && !stickWasDown;
            sideWasDown = grip; stickWasDown = stick;
            CapturesScroll = false;
            bool sideMouse = controller && questControls && screen != null && screen.PositionLocked
                && screen.TryPreviewPoint(ray, out _, out var sideDistance) && sideDistance <= nearest;
            if (grip && !sideMouse) { ReleaseNative(); Drawing?.Cancel(); return false; }
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
                if (!grip && pressed && hit.IsInteractable()) hit.onClick.Invoke();
                return true;
            }
            if (keyboard != null && keyboard.gameObject.activeInHierarchy && Hit(keyboard, ray, out var keyboardDistance)
                && keyboardDistance <= nearest)
            { ReleasePointer(); distance = keyboardDistance; return true; }
            if (modelToolsPanel != null && modelToolsPanel.gameObject.activeInHierarchy && Hit(modelToolsPanel, ray, out var modelDistance)
                && modelDistance <= nearest)
            { ReleasePointer(); distance = modelDistance; return true; }
            foreach (var overlay in new[] { shortcutPanel, numberPanel, windowPanel, mouseOptionsPanel })
                if (overlay != null && overlay.gameObject.activeInHierarchy && Hit(overlay, ray, out var overlayDistance) && overlayDistance <= nearest)
                { ReleasePointer(); distance = overlayDistance; return true; }
            if (panel != null && panel.gameObject.activeInHierarchy && Hit(panel, ray, out var panelDistance) && panelDistance <= nearest)
            { ReleasePointer(); distance = panelDistance; return true; }
            if (screen != null && screen.TryPreviewPoint(ray, out var point, out var imageDistance) && imageDistance <= nearest)
            {
                distance = imageDistance;
                if (PreviewInputMapping.CanRoute(inputEnabled, Ready(), true, false, true))
                {
                    CapturesScroll = true;
                    if (controller && questControls)
                    {
                        QuestPointer(point, trigger, pressed, grip, sidePressed, stick, stickPressed, axis);
                        return true;
                    }
                    lastPoint = point;
                    if (Time.unscaledTime >= nextPointer)
                    { nextPointer = Time.unscaledTime + .025f; pendingPointer = At("pointer", point); }
                    if (pressed)
                    {
                        if (mouseButton == "left") RememberEditor(point);
                        FlushPointer();
                        var e = At("button", point); e["button"] = mouseButton; e["action"] = "down";
                        Enqueue(e); mouseHeld = true; heldMouseButton = mouseButton;
                    }
                    if (released && mouseHeld)
                    { var e = At("button", point); e["button"] = heldMouseButton; e["action"] = "up"; Enqueue(e); mouseHeld = false; }
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

        void QuestPointer(Vector2 point, bool trigger, bool pressed, bool side, bool sidePressed, bool stick, bool stickPressed, Vector2 axis)
        {
            string desired = stick ? "middle" : side ? "right" : "left";
            bool down = stick ? stickPressed : side ? sidePressed : pressed;
            if (mouseHeld && (heldMouseButton == "middle" ? !stick : heldMouseButton == "right" ? !side : !trigger)) ReleasePointer();
            if (down && mouseHeld && heldMouseButton != desired) ReleasePointer();
            if (down && !mouseHeld)
            {
                FlushPointer(); heldMouseButton = desired;
                if (desired == "middle")
                {
                    panPoint = point;
                    panShift = !modifiers.Contains("SHIFT");
                    if (panShift) Enqueue(new JObject { ["type"] = "key", ["key"] = "SHIFT", ["action"] = "down" });
                }
                if (desired == "left") RememberEditor(point);
                var button = At("button", point); button["button"] = desired; button["action"] = "down";
                Enqueue(button); mouseHeld = true;
            }
            if (mouseHeld && heldMouseButton == "middle")
            {
                panPoint += new Vector2(axis.x, -axis.y) * (.12f * Time.unscaledDeltaTime);
                panPoint = new Vector2(Mathf.Clamp(panPoint.x, .02f, .98f), Mathf.Clamp(panPoint.y, .02f, .98f));
                point = panPoint;
            }
            lastPoint = point;
            if (Time.unscaledTime >= nextPointer)
            { nextPointer = Time.unscaledTime + .025f; pendingPointer = At("pointer", point); }
            if (!stick && axis.sqrMagnitude > .16f && Time.unscaledTime >= nextScroll)
            {
                nextScroll = Time.unscaledTime + .16f;
                var scroll = At("scroll", point); scroll["dx"] = Mathf.Abs(axis.x) > .5f ? Mathf.Sign(axis.x) : 0;
                scroll["dy"] = Mathf.Abs(axis.y) > .5f ? Mathf.Sign(axis.y) : 0; Enqueue(scroll);
            }
        }

        void ToggleScreenLock()
        {
            ReleaseNative(); screen?.TogglePositionLock();
            Notice = screen != null && screen.PositionLocked ? "Screen LOCKED Â· front: click Â· side: right-click Â· stick: scroll/zoom Â· hold stick + tilt: pan"
                : "Screen UNLOCKED Â· side grip moves the screen";
        }

        void RefreshControlFeedback()
        {
            foreach (var b in buttons)
            {
                if (b == null || b == focusButton) continue;
                bool selected = false, stateful = true;
                switch (b.name)
                {
                    case "Keyboard": selected = keyboardShown && !fullKeyboard; break;
                    case "Full keyboard": selected = keyboardShown && fullKeyboard; break;
                    case "CTRL": case "SHIFT": case "ALT": selected = modifiers.Contains(b.name); break;
                    case "Caps": selected = shiftText; break;
                    case "Lock screen position": selected = screen != null && screen.PositionLocked; break;
                    case "Controller controls": selected = questControls; break;
                    case "Other hand": selected = PrimaryHand == XRNode.LeftHand; break;
                    case "Mouse options": selected = mouseOptionsShown; break;
                    case "Mouse left": case "Mouse right": case "Mouse middle": selected = !questControls && mouseButton == b.name.Substring(6); break;
                    case "Draw in VR": selected = Drawing != null && (Drawing.EnabledForInput || spatialRequested); break;
                    case "Line": case "Circle": case "Rectangle": selected = Drawing != null && Drawing.EnabledForInput && Drawing.Tool == b.name.ToLowerInvariant(); break;
                    case "Model tools": selected = modelToolsShown || objectsRequested; break;
                    case "Preview tools": selected = shortcutsShown; break;
                    case "Windows / dialogs": selected = windowsShown; break;
                    default: stateful = false; break;
                }
                if (stateful)
                {
                    string label = b.name == "Lock screen position" ? (selected ? "Screen LOCKED" : "Lock screen position")
                        : b.name == "Other hand" ? "Pointer: " + (selected ? "Left" : "Right") : b.name + (selected ? " Â· ON" : "");
                    b.GetComponentInChildren<Text>().text = label;
                }
                var c = b.colors;
                c.normalColor = b == pulsedButton && Time.unscaledTime < pulseUntil ? new Color(1f, .62f, .08f)
                    : selected ? new Color(.12f, .65f, .28f) : new Color(.08f, .24f, .34f);
                c.highlightedColor = c.selectedColor = c.normalColor; b.colors = c;
            }
            if (actionFeedback != null)
                actionFeedback.text = lastControlAction + "\n" + (screen != null && screen.PositionLocked ? "Screen LOCKED Â· front: click Â· side: right-click Â· stick: scroll/zoom Â· hold stick + tilt: pan"
                    : "Screen UNLOCKED Â· side grip moves screen; lock it for right-click") + "\n"
                    + (Drawing != null && (Drawing.EnabledForInput || spatialRequested) && (string)Drawing.NativeState["mode"] != "OBJECT"
                        ? "Direct VR drawing needs Blender Object Mode; use its top-left mode dropdown" : Notice);
        }

        bool NativeInputOwned => scene != null && scene.IsCurrent && Drawing != null && (Drawing.IsNativeUiOwned
            || windowAuthority.Matches(Drawing.Session, Drawing.NativeState, state));
        long NativeInputProcess => Drawing == null ? 0 : Drawing.NativeProcessId > 0 ? Drawing.NativeProcessId
            : windowAuthority.Matches(Drawing.Session, Drawing.NativeState, state) ? windowAuthority.ProcessId : 0;
        bool MatchesNativeHost() => state != null && NativeInputProcess > 0
            && PreviewWindowState.RootPid(state) == NativeInputProcess;
        bool Ready() => state != null && (bool?)state["ready"] == true && (bool?)state["focused"] == true
            && (bool?)state["release_error"] == false
            && MatchesNativeHost() && NativeInputOwned && screen != null && screen.HasImage
            && PreviewInputMapping.FrameMatches(screen.DisplayedCaptureInstance, screen.DisplayedSelectionGeneration,
                (string)state["capture_instance"], (long?)state["capture_generation"] ?? -1)
            && !string.IsNullOrEmpty(screen.DisplayedCaptureGeometry)
            && screen.DisplayedCaptureGeometry == (string)state["capture_geometry"];
        string InputMode => endAfterRelease ? "Releasing" : lastInputFailure.Length != 0 ? "Blocked"
            : inputEnabled && Ready() ? "On" : inputEnabled || focusRequested || windowResuming ? "Enabling" : "Off";
        void RefreshInputIndicator()
        {
            if (focusButton == null) return;
            string mode = InputMode;
            focusButton.GetComponentInChildren<Text>().text = mode == "On" ? "Input ON Â· turn off"
                : mode == "Off" ? "Input OFF Â· enable" : mode == "Blocked" ? "Input blocked Â· retry"
                : mode == "Releasing" ? "Releasing inputâ€¦" : "Enablingâ€¦ Â· cancel";
            focusButton.interactable = !endAfterRelease;
            var colors = focusButton.colors;
            colors.normalColor = mode == "On" ? new Color(.12f, .65f, .28f)
                : mode == "Blocked" ? new Color(.75f, .18f, .16f)
                : mode == "Enabling" || mode == "Releasing" ? new Color(.8f, .5f, .08f)
                : new Color(.16f, .36f, .65f);
            colors.highlightedColor = colors.selectedColor = colors.normalColor;
            focusButton.colors = colors;
        }
        void ToggleNativeUi()
        {
            if (endAfterRelease) return;
            if (inputEnabled || focusRequested || windowResuming)
            { Suspend(); Notice = "Input disabled; releasing held keys and buttons"; }
            else FocusNativeUi();
            RefreshInputIndicator();
        }
        void FocusNativeUi()
        {
            if (endAfterRelease) { Notice = "Waiting for native input cleanup before focusing again"; return; }
            lastInputFailure = "";
            if (state == null || (bool?)state["enabled"] != true || session.Length == 0)
            { Notice = "Start the P2.5 helper with input enabled and select the connected Blender window"; return; }
            objectsRequested = modelToolsShown = false;
            windowAuthority.Clear(); windowResuming = windowReleaseQueued = inputResync = windowsShown = false;
            numbersShown = shortcutsShown = windowsShown = editorPointSet = false; Drawing.Numeric.Invalidate();
            Drawing.Cancel(); Drawing.SetEnabled(false); Drawing.SetObjectToolsEnabled(false);
            focusRequested = true; spatialRequested = false;
            Drawing.BeginNativeUi();
            Notice = "Waiting for native UI editing permission";
        }
        void RequestEndNativeUi()
        {
            inputEnabled = focusRequested = false;
            windowAuthority.Clear(); windowResuming = windowReleaseQueued = inputResync = false;
            if (endAfterRelease) return;
            events.Clear(); pendingPointer = null; mouseHeld = panShift = false; modifiers.Clear();
            endAfterRelease = true; releaseQueued = false;
            // release is idempotent cleanup, never a replay of a model operation.
            // Keep the native lease until the helper confirms all held input up.
        }
        void BeginSpatial()
        {
            mouseOptionsShown = false;
            if (Drawing.NativeModalActive)
            { Notice = "Finish the native operation with Enter or Escape before switching to VR drawing"; return; }
            objectsRequested = modelToolsShown = false;
            numbersShown = shortcutsShown = windowsShown = editorPointSet = false; Drawing.Numeric.Invalidate();
            Drawing.SetObjectToolsEnabled(false);
            bool needsRelease = inputEnabled || focusRequested || windowResuming || NativeInputOwned || Drawing.NativeUiTransitionPending;
            ReleaseNative(); inputEnabled = focusRequested = false;
            if (needsRelease) RequestEndNativeUi();
            spatialRequested = true;
        }
        void BeginObjects()
        {
            mouseOptionsShown = false;
            if (Drawing == null) return;
            numbersShown = shortcutsShown = windowsShown = editorPointSet = false; Drawing.Numeric.Invalidate();
            if (Drawing.NativeModalActive) { Notice = "Finish or cancel the running Blender operation before Model tools"; return; }
            bool needsRelease = inputEnabled || focusRequested || windowResuming || NativeInputOwned || Drawing.NativeUiTransitionPending;
            ReleaseNative(); inputEnabled = focusRequested = false;
            Drawing.SetEnabled(false); spatialRequested = false; keyboardShown = false;
            if (needsRelease) RequestEndNativeUi();
            objectsRequested = true;
            Notice = "Opening Model tools after native input cleanup";
        }
        void RememberEditor(Vector2 point)
        {
            if (!Ready() || Drawing == null || !Drawing.NativeStateCurrent) return;
            editorPoint = point; editorPointSet = true;
            editorInstance = (string)state["capture_instance"]; editorGeometry = (string)state["capture_geometry"];
            editorGeneration = (long)state["capture_generation"];
            editorIdentity = Drawing.Session.RequestIdentity?.ToString(Newtonsoft.Json.Formatting.None);
        }
        bool EditorCurrent() => editorPointSet && Ready() && Drawing.NativeStateCurrent
            && editorInstance == (string)state["capture_instance"] && editorGeometry == (string)state["capture_geometry"]
            && editorGeneration == (long)state["capture_generation"]
            && editorIdentity == Drawing.Session.RequestIdentity?.ToString(Newtonsoft.Json.Formatting.None);
        void RunShortcut(string id)
        {
            if (!PreviewShortcutCatalog.TryGet(id, out var shortcut) || !inputEnabled || !Ready() || !Drawing.NativeStateCurrent)
            { Notice = "Focus Blender with fresh native state before using preview shortcuts"; return; }
            if (shortcut.RequiresEditorContext && !EditorCurrent())
            { Notice = "Click the intended Blender editor again; the previous editor point is unavailable"; return; }
            if (id.StartsWith("mesh.", StringComparison.Ordinal) && (string)Drawing.NativeState["mode"] != "EDIT_MESH")
            { Notice = "Mesh shortcuts require native mesh Edit Mode"; return; }
            if (Drawing.NativeModalActive && id != "cancel" && id != "confirm")
            { Notice = "Confirm or cancel the running Blender operation first"; return; }
            if (!QueueChord(shortcut.BuildEvents(), shortcut.RequiresEditorContext)) return;
            Notice = shortcut.Label + (shortcut.OpensModal ? " Â· continue in Blender; Enter confirms, Escape cancels" : " Â· sent to the chosen native editor");
        }
        bool QueueChord(IReadOnlyList<JObject> chord, bool returnToEditor)
        {
            var batch = new List<JObject>();
            if (mouseHeld) { var up = At("button", lastPoint); up["button"] = heldMouseButton; up["action"] = "up"; batch.Add(up); }
            if (panShift) { batch.Add(new JObject { ["type"] = "key", ["key"] = "SHIFT", ["action"] = "up" }); panShift = false; }
            var held = new List<string>(modifiers); held.Sort(StringComparer.Ordinal);
            foreach (string key in held) batch.Add(new JObject { ["type"] = "key", ["key"] = key, ["action"] = "up" });
            if (returnToEditor) batch.Add(At("pointer", editorPoint));
            foreach (var e in chord) batch.Add(e);
            foreach (string key in held) batch.Add(new JObject { ["type"] = "key", ["key"] = key, ["action"] = "down" });
            if (events.Count + batch.Count > 64)
            { FailTransport("Shortcut backlog cancelled; cleanup is required before focusing again"); return false; }
            pendingPointer = null; mouseHeld = false;
            foreach (var e in batch) events.Enqueue(e);
            return true;
        }
        void OpenKeyboard(bool full)
        {
            mouseOptionsShown = false;
            modelToolsShown = objectsRequested = numbersShown = shortcutsShown = windowsShown = false;
            Drawing.SetObjectToolsEnabled(false); Drawing.Numeric.Invalidate();
            keyboardShown = true; SetKeyboardPage(full);
        }
        void SetKeyboardPage(bool full)
        {
            fullKeyboard = full;
            foreach (var button in basicKeys) button.gameObject.SetActive(!full);
            foreach (var button in fullKeys) button.gameObject.SetActive(full);
        }
        void OpenNumbers(string mode)
        {
            mouseOptionsShown = false;
            if (!Drawing.LoadNumeric(mode)) { Notice = Drawing.Numeric.Notice; return; }
            numbersShown = true; modelToolsShown = keyboardShown = shortcutsShown = windowsShown = false; RefreshNumbers();
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
            if (mouseHeld || modifiers.Count != 0 || panShift)
            { Enqueue(new JObject { ["type"] = "release" }); mouseHeld = panShift = false; modifiers.Clear(); }
        }
        void ReleasePointer()
        {
            pendingPointer = null;
            if (!mouseHeld) return;
            var e = At("button", lastPoint); e["button"] = heldMouseButton; e["action"] = "up";
            Enqueue(e); mouseHeld = false;
            if (panShift) { Enqueue(new JObject { ["type"] = "key", ["key"] = "SHIFT", ["action"] = "up" }); panShift = false; }
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
            if (!inputEnabled || !Ready()) { Notice = "Enable Blender input before using modifiers"; return; }
            bool down = !modifiers.Contains(key);
            if (down) modifiers.Add(key); else modifiers.Remove(key);
            Enqueue(new JObject { ["type"] = "key", ["key"] = key, ["action"] = down ? "down" : "up" });
            Notice = "Held modifiers: " + string.Join(" + ", modifiers);
        }
        void Shortcut(string key, bool shift = false)
        {
            if (!inputEnabled || !Ready()) return;
            var shortcut = new PreviewShortcut("keyboard." + key, key, "Keyboard", key, editor: false,
                modifiers: shift ? new[] { "CTRL", "SHIFT" } : new[] { "CTRL" });
            QueueChord(shortcut.BuildEvents(), false);
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
                    try
                    {
                        using (var request = UnityWebRequest.Get(url + "/input/state"))
                        {
                            request.timeout = 2; yield return request.SendWebRequest();
                            if (request.result == UnityWebRequest.Result.Success)
                            {
                                if (!PreviewInputProtocol.TryState(request.downloadHandler.text, out var fresh))
                                    FailTransport("Input helper returned invalid state");
                                else ApplyInputState(fresh);
                            }
                            else FailTransport("P2.5 input helper unavailable");
                        }
                    }
                    finally { readingState = false; }
                }
                yield return new WaitForSecondsRealtime(.5f);
            }
        }

        void AwaitWindowState(string reason) => AwaitInputState(reason, false);
        void AwaitInputState(string reason, bool sameWindowResync)
        {
            if (!windowResuming)
            { windowAwaitSession = session; windowResumeUntil = Time.unscaledTime + 4f; awaitedWindow = 0; }
            windowResuming = true; windowReleaseQueued = false; inputEnabled = focusRequested = false;
            inputResync = sameWindowResync;
            events.Clear(); pendingPointer = null; mouseHeld = panShift = false; modifiers.Clear(); editorPointSet = false;
            triggerWasDown = true; Drawing?.Numeric.Invalidate(); transport.Unknown();
            Notice = reason;
        }

        void ApplyInputState(JObject fresh)
        {
            string nextSession = (string)fresh["session"] ?? "";
            if (session != nextSession)
            {
                bool wasActive = inputEnabled || focusRequested || windowResuming || NativeInputOwned;
                bool sameFamily = !endAfterRelease && NativeInputOwned
                    && PreviewWindowState.CanContinue(state, fresh, NativeInputProcess);
                if (wasActive && sameFamily) AwaitWindowState("Following Blender dialog/window; release trigger before continuing");
                else
                {
                    events.Clear(); pendingPointer = null; mouseHeld = panShift = inputEnabled = false; modifiers.Clear();
                    editorPointSet = false; Drawing?.Cancel();
                    if (wasActive) RequestEndNativeUi();
                }
                releaseQueued = false; session = nextSession;
            }
            state = fresh; token = (string)fresh["token"] ?? "";
            if (session.Length != 0 && token.Length != 0 && (long?)fresh["next_seq"] >= 1)
                transport.Observe(session, (long)fresh["next_seq"]);
            else transport.Unknown();
            if ((bool?)fresh["enabled"] != true) Notice = "Start this feature's helper with --enable-input";
            else if (lastInputFailure.Length != 0) { ReleaseNative(); Notice = lastInputFailure; }
            else if (!Ready())
            {
                ReleaseNative();
                string why = (string)fresh["reason"];
                Notice = !MatchesNativeHost() ? "Capture must select the connected Blender host"
                    : !NativeInputOwned ? "Use Focus Blender to begin native preview interaction"
                    : !string.IsNullOrEmpty(why) ? why
                    : (bool?)fresh["focused"] != true ? "Blender is not the active desktop window; use Focus Blender"
                    : screen == null || !screen.HasImage ? "Waiting for a fresh Blender image"
                    : "Waiting for the selected window's matching displayed frame";
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
                {
                    if (NativeInputOwned && !endAfterRelease && windowAuthority.ProcessId > 0)
                        AwaitWindowState("Window context changed; pending actions discarded");
                    else FailTransport("Input context changed; pending actions cancelled");
                    continue;
                }
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
                        string rejection = "";
                        try { rejection = (string)JObject.Parse(request.downloadHandler.text)["reason"] ?? ""; }
                        catch (Exception) { }
                        // Log only bounded protocol reason codes, never request data/tokens.
                        if (rejection.Length <= 80 && System.Text.RegularExpressions.Regex.IsMatch(rejection, "^[a-z_]+$"))
                            Debug.Log("P25_INPUT_REJECT kind=" + kind + " status=" + request.responseCode + " reason=" + rejection);
                        // input_busy is a pre-admission lock collision: the helper
                        // consumed neither sequence nor action. Drop the gesture;
                        // resync and ACK release before admitting a NEW gesture.
                        if (request.responseCode == 429 && rejection == "input_busy" && !endAfterRelease
                            && NativeInputOwned && windowAuthority.ProcessId > 0)
                            AwaitInputState("Input helper busy; discarding gesture and confirming cleanup", true);
                        else if (kind == "focus" && rejection == "foreground_activation_denied")
                            FailTransport("Windows did not activate Blender. Bring the test Blender window forward, then use Focus Blender. No click was sent.");
                        else if (request.responseCode == 409 && !endAfterRelease && NativeInputOwned && windowAuthority.ProcessId > 0)
                            AwaitWindowState("Blender window changed; waiting for fresh state. The action was not retried.");
                        else FailTransport("Input stopped: " + request.responseCode + ". Refresh/focus; the action was not retried.");
                    }
                    else if (!PreviewInputProtocol.Acknowledged(request.downloadHandler.text, (long)e["seq"]))
                    {
                        FailTransport("Input acknowledgement was invalid; pending actions cancelled. Refresh/focus before editing.");
                    }
                    else if ((string)e["type"] == "release" && endAfterRelease)
                    {
                        if (ownedCaptureInstance.Length != 0 && ownedCaptureInstance != (string)state?["capture_instance"])
                        { Notice = "Input helper restarted; release status is unknown. Check native input and reconnect."; releaseQueued = true; }
                        else
                        { releaseQueued = endAfterRelease = false; ownedCaptureInstance = ""; Drawing.EndNativeUi(); Notice = "Native UI input released"; }
                    }
                    else if ((string)e["type"] == "release" && windowResuming && windowReleaseQueued)
                    {
                        windowReleaseQueued = false;
                        if (Ready())
                        {
                            windowResuming = false; inputEnabled = true; awaitedWindow = 0;
                            Notice = inputResync ? "Blender input ready Â· previous gesture discarded; use a new gesture"
                                : "Blender dialog/window ready Â· old input released";
                            inputResync = false;
                        }
                    }
                    else if ((string)e["type"] == "focus")
                    {
                        // The helper acknowledged exact-window foreground after
                        // verification. A later event still rechecks it natively.
                        if (state != null) state["focused"] = true;
                        Notice = "Blender focused Â· trigger: mouse Â· stick: scroll Â· grip: move preview";
                    }
                }
                sendingEvent = false;
            }
        }

        void FailTransport(string reason)
        {
            lastInputFailure = reason;
            bool needsCleanup = inputEnabled || focusRequested || endAfterRelease || windowResuming || NativeInputOwned;
            transport.Unknown(); state = null; events.Clear(); pendingPointer = null;
            inputEnabled = focusRequested = mouseHeld = panShift = false; modifiers.Clear();
            windowAuthority.Clear(); windowResuming = windowReleaseQueued = inputResync = false;
            releaseQueued = false;
            if (needsCleanup) RequestEndNativeUi();
            Notice = reason;
        }

        void BuildControls()
        {
            panel = MakePanel("P2.5 controls", new Vector2(0, -1120), new Vector2(1840, 540));
            focusButton = AddButton(panel, "Focus Blender", 0, 0, ToggleNativeUi);
            RefreshInputIndicator();
            AddButton(panel, "Disable input", 1, 0, Suspend);
            AddButton(panel, "Keyboard", 2, 0, () => { if (keyboardShown) keyboardShown = false; else OpenKeyboard(false); });
            AddButton(panel, "Lock screen position", 3, 0, ToggleScreenLock);
            AddButton(panel, "Controller controls", 4, 0, () => { ReleaseNative(); questControls = true; mouseOptionsShown = false; Notice = "Front: click Â· side: right-click with screen locked Â· stick: scroll/zoom Â· hold stick + tilt: pan"; });
            AddButton(panel, "Mouse options", 5, 0, () =>
            {
                mouseOptionsShown = !mouseOptionsShown;
                if (mouseOptionsShown) keyboardShown = numbersShown = shortcutsShown = windowsShown = modelToolsShown = false;
            });
            AddButton(panel, "Windows / dialogs", 6, 0, OpenWindows);
            AddButton(panel, "Escape / cancel", 0, 1, () => { Drawing.Cancel(); Key("ESC"); });
            AddButton(panel, "Enter", 1, 1, () => Key("ENTER"));
            // Blender owns modeling, tools, dimensions, history and file actions.
            AddButton(panel, "Draw in VR", 2, 1, BeginSpatial);
            AddButton(panel, "Full keyboard", 3, 1, () => OpenKeyboard(true));
            AddButton(panel, "Next window", 4, 1, NextWindow);
            feedback = MakeText(panel, new Vector2(0, -155), new Vector2(1780, 160), "", 25);
            actionFeedback = MakeText(panel, new Vector2(0, 355), new Vector2(1780, 160), "", 28);
            actionFeedback.gameObject.AddComponent<Outline>().effectColor = Color.black;
            mouseOptionsPanel = MakePanel("Optional mouse modes", new Vector2(0, -200), new Vector2(1840, 320));
            AddButton(mouseOptionsPanel, "Mouse left", 0, 0, () => { ReleaseNative(); questControls = false; mouseButton = "left"; });
            AddButton(mouseOptionsPanel, "Mouse right", 1, 0, () => { ReleaseNative(); questControls = false; mouseButton = "right"; });
            AddButton(mouseOptionsPanel, "Mouse middle", 2, 0, () => { ReleaseNative(); questControls = false; mouseButton = "middle"; });
            AddButton(mouseOptionsPanel, "Close mouse options", 6, 0, () => mouseOptionsShown = false);
            mouseOptionsPanel.gameObject.SetActive(false);
            // A temporary keyboard overlays the lower preview while typing. It
            // must not be placed metres below the screen (possibly below floor).
            keyboard = MakePanel("P2.5 keyboard", new Vector2(0, -200), new Vector2(1840, 640));
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
            AddButton(keyboard, "More keys", 0, 6, () => SetKeyboardPage(true), 145, 12);
            basicKeys.AddRange(keyboard.GetComponentsInChildren<Button>(true));
            for (int i = 0; i < PreviewShortcutCatalog.FullKeyboardKeys.Count; i++)
            {
                string key = PreviewShortcutCatalog.FullKeyboardKeys[i];
                var button = AddButton(keyboard, "Full " + key, i % 7, i / 7, () => Key(key));
                button.GetComponentInChildren<Text>().text = key; fullKeys.Add(button);
            }
            fullKeys.Add(AddButton(keyboard, "Letters", 0, 5, () => SetKeyboardPage(false)));
            fullKeys.Add(AddButton(keyboard, "Close full keyboard", 1, 5, () => keyboardShown = false));
            SetKeyboardPage(false); keyboard.gameObject.SetActive(false);
            // Historical palette builders remain for backend regression evidence,
            // but have no production entry point or constructed controls.
            BuildWindowControls();
        }

        void BuildModelTools()
        {
            modelToolsPanel = MakePanel("P2.5 model tools", new Vector2(0, -200), new Vector2(1840, 640));
            modelToolsPanel.localPosition += Vector3.back * 8f;
            AddButton(modelToolsPanel, "Previous object", 0, 0, () => Drawing.ObjectTools.SelectRelative(-1));
            AddButton(modelToolsPanel, "Next object", 1, 0, () => Drawing.ObjectTools.SelectRelative(1));
            moveStepButton = AddButton(modelToolsPanel, "Move step", 2, 0, () => { if (!Drawing.Session.Busy) Drawing.ObjectTools.CycleMoveStep(); RefreshObjectLabels(); });
            turnStepButton = AddButton(modelToolsPanel, "Turn step", 3, 0, () => { if (!Drawing.Session.Busy) Drawing.ObjectTools.CycleTurnDegrees(); RefreshObjectLabels(); });
            primitiveSizeButton = AddButton(modelToolsPanel, "Primitive size", 4, 0, () => { if (!Drawing.Session.Busy) Drawing.ObjectTools.CyclePrimitiveSize(); RefreshObjectLabels(); });
            AddButton(modelToolsPanel, "Close model tools", 6, 0, () => { modelToolsShown = objectsRequested = false; Drawing.SetObjectToolsEnabled(false); });
            ObjectButton("Add cube", "add.cube", 0, 1);
            ObjectButton("Add sphere", "add.sphere", 1, 1);
            ObjectButton("Add cylinder", "add.cylinder", 2, 1);
            AddButton(modelToolsPanel, "Exact move", 3, 1, () => OpenNumbers("move"));
            AddButton(modelToolsPanel, "Set position", 4, 1, () => OpenNumbers("position"));
            AddButton(modelToolsPanel, "Set rotation", 5, 1, () => OpenNumbers("rotation"));
            AddButton(modelToolsPanel, "Scale factors", 6, 1, () => OpenNumbers("scale.by"));
            for (int axis = 0; axis < 3; axis++)
            {
                string name = "XYZ"[axis].ToString(), id = name.ToLowerInvariant();
                ObjectButton("Move " + name + " -", "move." + id + "-", axis * 2, 2);
                ObjectButton("Move " + name + " +", "move." + id + "+", axis * 2 + 1, 2);
                ObjectButton("Turn " + name + " -", "turn." + id + "-", axis * 2, 3);
                ObjectButton("Turn " + name + " +", "turn." + id + "+", axis * 2 + 1, 3);
            }
            ObjectButton("Scale down", "scale.down", 0, 4);
            ObjectButton("Scale up", "scale.up", 1, 4);
            ObjectButton("Delete target", "delete", 2, 4);
            AddButton(modelToolsPanel, "Model Undo", 3, 4, () => Drawing.Undo());
            AddButton(modelToolsPanel, "Model Redo", 4, 4, () => Drawing.Redo());
            AddButton(modelToolsPanel, "Model Save", 5, 4, () => Drawing.Save());
            AddButton(modelToolsPanel, "Cancel pending", 6, 4, () => Drawing.Cancel());
            AddButton(modelToolsPanel, "Set scale", 0, 5, () => OpenNumbers("scale.to"));
            AddButton(modelToolsPanel, "Cube dimensions", 1, 5, () => OpenNumbers("add.cube"));
            AddButton(modelToolsPanel, "Sphere dimensions", 2, 5, () => OpenNumbers("add.sphere"));
            AddButton(modelToolsPanel, "Cylinder dimensions", 3, 5, () => OpenNumbers("add.cylinder"));
            objectTargetText = MakeText(modelToolsPanel, new Vector2(0, -240), new Vector2(1780, 96), "", 25);
            RefreshObjectLabels(); modelToolsPanel.gameObject.SetActive(false);
        }
        void BuildCommonControls()
        {
            shortcutPanel = MakePanel("P2.5 preview tools", new Vector2(0, -200), new Vector2(1840, 640));
            shortcutPanel.localPosition += Vector3.back * 8f;
            AddButton(shortcutPanel, "Previous tools", 0, 0, () => SetShortcutPage((shortcutPage + 1) % 2));
            AddButton(shortcutPanel, "Next tools", 1, 0, () => SetShortcutPage((shortcutPage + 1) % 2));
            AddButton(shortcutPanel, "Close preview tools", 6, 0, () => shortcutsShown = false);
            for (int i = 0; i < PreviewShortcutCatalog.All.Count; i++)
            {
                var item = PreviewShortcutCatalog.All[i];
                shortcutButtons.Add(AddButton(shortcutPanel, "Shortcut " + item.Id, i % 7, 1 + i / 7 % 3, () => RunShortcut(item.Id)));
                shortcutButtons[i].GetComponentInChildren<Text>().text = item.Label;
            }
            AddButton(shortcutPanel, "Preview Escape", 5, 4, () => RunShortcut("cancel"));
            AddButton(shortcutPanel, "Preview Enter", 6, 4, () => RunShortcut("confirm"));
            shortcutFeedback = MakeText(shortcutPanel, new Vector2(0, -230), new Vector2(1780, 120), "", 25);
            SetShortcutPage(0); shortcutPanel.gameObject.SetActive(false);
            numberPanel = MakePanel("P2.5 exact numbers", new Vector2(0, -200), new Vector2(1840, 640));
            numberPanel.localPosition += Vector3.back * 8f;
            for (int i = 0; i < 3; i++)
            { int axis = i; numberFields.Add(AddButton(numberPanel, "Number " + "XYZ"[i], i, 0, () => Drawing.Numeric.SelectAxis(axis), 580, 3)); }
            string[] keys = { "7", "8", "9", "4", "5", "6", "1", "2", "3", "0", ".", "sign", "back", "clear" };
            for (int i = 0; i < keys.Length; i++)
            { string key = keys[i]; AddButton(numberPanel, "Number " + key, i % 3, 1 + i / 3, () => { Drawing.Numeric.Enter(key); RefreshNumbers(); }); }
            AddButton(numberPanel, "Apply numbers", 4, 1, () => { Drawing.ApplyNumeric(); RefreshNumbers(); });
            AddButton(numberPanel, "Reload numbers", 4, 2, () => { Drawing.LoadNumeric(Drawing.Numeric.Mode); RefreshNumbers(); });
            AddButton(numberPanel, "Close numbers", 6, 3, () => { numbersShown = false; modelToolsShown = true; Drawing.Numeric.Invalidate(); });
            numberFeedback = MakeText(numberPanel, new Vector2(0, -240), new Vector2(1780, 100), "", 25);
            numberPanel.gameObject.SetActive(false);
        }
        void SetShortcutPage(int page)
        {
            shortcutPage = page;
            for (int i = 0; i < shortcutButtons.Count; i++) shortcutButtons[i].gameObject.SetActive(i / 21 == page);
        }
        void RefreshNumbers()
        {
            var values = Drawing.Numeric;
            bool current = values.IsCurrent;
            for (int i = 0; i < numberFields.Count; i++) numberFields[i].GetComponentInChildren<Text>().text = (values.Axis == i ? "> " : "") + "XYZ"[i] + ": " + values.Value(i);
            if (numberFeedback != null) numberFeedback.text = values.Mode + " Â· " + values.Unit + "\n" + (current ? "Local values Â· Apply explicitly changes Blender" : "Draft needs reload") + "\n" + values.Notice;
        }
        void ObjectButton(string label, string action, int col, int row) =>
            AddButton(modelToolsPanel, label, col, row, () => Drawing.ApplyObjectAction(action));
        void RefreshObjectLabels()
        {
            if (Drawing == null) return;
            var tools = Drawing.ObjectTools;
            if (moveStepButton != null) moveStepButton.GetComponentInChildren<Text>().text = "Move: " + (tools.MoveStepMeters * 1000).ToString("0") + " mm";
            if (turnStepButton != null) turnStepButton.GetComponentInChildren<Text>().text = "Turn: " + tools.TurnDegrees + " deg";
            if (primitiveSizeButton != null) primitiveSizeButton.GetComponentInChildren<Text>().text = "Size: " + (tools.PrimitiveSizeMeters * 1000).ToString("0") + " mm";
            if (objectTargetText != null) objectTargetText.text = "Model target: " + tools.TargetLabel + "\nBlender world XYZ Â· primitives at world origin Â· Undo restores edits";
        }

        void NextWindow()
        {
            var windows = state?["windows"] as JArray;
            if (windows == null || windows.Count == 0) { Notice = "No other Blender windows available"; return; }
            long current = (long?)state?["selection"]?["hwnd"] ?? 0; int at = -1;
            for (int i = 0; i < windows.Count; i++) if ((long?)windows[i]["hwnd"] == current) at = i;
            var next = windows[(at + 1) % windows.Count];
            ChooseWindow((long)next["hwnd"]);
        }
        void BuildWindowControls()
        {
            windowPanel = MakePanel("P2.5 Blender windows", new Vector2(0, -200), new Vector2(1840, 640));
            windowPanel.localPosition += Vector3.back * 8f;
            AddButton(windowPanel, "Previous windows", 0, 0, () => { windowPage = Mathf.Max(0, windowPage - 1); windowListSignature = ""; RefreshWindows(); });
            AddButton(windowPanel, "Next windows", 1, 0, () => { windowPage++; windowListSignature = ""; RefreshWindows(); });
            AddButton(windowPanel, "Back to Blender", 4, 0, ReturnToBlender);
            AddButton(windowPanel, "Close windows", 6, 0, () => windowsShown = false);
            windowFeedback = MakeText(windowPanel, new Vector2(0, -270), new Vector2(1780, 80), "", 25);
            windowFeedback.supportRichText = false;
            windowPanel.gameObject.SetActive(false);
        }
        void OpenWindows()
        {
            ReleasePointer();
            windowsShown = true; modelToolsShown = numbersShown = shortcutsShown = keyboardShown = objectsRequested = spatialRequested = false;
            Drawing?.SetObjectToolsEnabled(false); Drawing?.SetEnabled(false); Drawing?.Numeric.Invalidate();
            windowListSignature = ""; RefreshWindows();
        }
        void RefreshWindows()
        {
            var list = state?["windows"] as JArray;
            int count = list?.Count ?? 0, pages = Math.Max(1, (count + 5) / 6);
            windowPage = Mathf.Clamp(windowPage, 0, pages - 1);
            string signature = windowPage + ":" + (list?.ToString(Newtonsoft.Json.Formatting.None) ?? "");
            if (signature == windowListSignature) return;
            windowListSignature = signature;
            foreach (var button in windowButtons)
            {
                buttons.Remove(button);
                if (button != null)
                {
                    button.gameObject.SetActive(false);
                    if (Application.isPlaying) Destroy(button.gameObject); else DestroyImmediate(button.gameObject);
                }
            }
            windowButtons.Clear();
            for (int i = windowPage * 6; i < Math.Min(count, windowPage * 6 + 6); i++)
            {
                var item = list[i]; long hwnd = (long)item["hwnd"];
                var button = AddButton(windowPanel, "Window " + hwnd, 0, 1 + i % 6, () => ChooseWindow(hwnd), 1780, 1);
                var label = button.GetComponentInChildren<Text>(); label.supportRichText = false;
                string title = (string)item["title"] ?? "Untitled Blender window";
                if (title.Length > 110) title = title.Substring(0, 110) + "â€¦";
                label.text = ((string)item["kind"] ?? "blender") + " Â· " + title;
                windowButtons.Add(button);
            }
            windowFeedback.text = count == 0 ? "Waiting for a verified Blender window list. Focus Blender or refresh the helper selection."
                : "Page " + (windowPage + 1) + " / " + pages + " Â· owned dialogs follow automatically; choose a window to recover or switch";
        }
        void ReturnToBlender()
        {
            long root = (long?)state?["selection"]?["blender_hwnd"] ?? 0;
            var list = state?["windows"] as JArray;
            if (list != null && root == 0)
                foreach (var item in list) if ((string)item["kind"] == "blender" || item["kind"] == null) { root = (long)item["hwnd"]; break; }
            if (root > 0) ChooseWindow(root); else Notice = "Main Blender window is unavailable; choose a verified window";
        }
        void ChooseWindow(long hwnd)
        {
            var list = state?["windows"] as JArray; JObject chosen = null;
            if (list != null) foreach (var item in list)
                if ((long?)item["hwnd"] == hwnd) { chosen = item as JObject; break; }
            long pid = (long?)chosen?["blender_pid"] ?? (long?)chosen?["pid"] ?? 0;
            if (chosen == null || pid <= 0 || pid != NativeInputProcess || endAfterRelease)
            { Notice = "That window is unavailable or belongs to another Blender session"; return; }
            // Selecting the current window is also an explicit focus/recovery
            // request. Refresh its generation through the same verified path.
            bool resume = NativeInputOwned;
            bool synchronized = transport.Synchronized; long nextSequence = transport.NextSequence;
            AwaitWindowState("Switching Blender window; pending input discarded");
            windowResuming = resume; awaitedWindow = hwnd;
            Enqueue(new JObject { ["type"] = "select_window", ["hwnd"] = hwnd });
            // Selection itself must be sent on the authoritative old sequence.
            if (synchronized) transport.Observe(session, nextSequence);
            windowsShown = false;
        }
        RectTransform MakePanel(string name, Vector2 position, Vector2 size)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Image));
            var rect = go.GetComponent<RectTransform>(); rect.SetParent(screen.Placement, false);
            rect.anchoredPosition = position; rect.sizeDelta = size;
            go.GetComponent<Image>().color = new Color(.015f, .035f, .06f, .98f);
            return rect;
        }
        Button AddButton(RectTransform parent, string label, int col, int row, Action action, float width = 250, int columns = 7)
        {
            var go = new GameObject(label, typeof(RectTransform), typeof(Image), typeof(Button));
            var rect = go.GetComponent<RectTransform>(); rect.SetParent(parent, false);
            rect.sizeDelta = new Vector2(width - 8, 64);
            rect.anchoredPosition = new Vector2((col - (columns - 1) * .5f) * width, parent.rect.height * .5f - 48 - row * 72);
            go.GetComponent<Image>().color = Color.white;
            var button = go.GetComponent<Button>(); button.onClick.AddListener(() =>
            {
                pulsedButton = button; pulseUntil = Time.unscaledTime + .35f;
                lastControlAction = "Pressed: " + label;
                Debug.Log("P25_CONTROL_ACTION " + (parent == keyboard ? "Keyboard key" : label));
                action(); RefreshControlFeedback();
            }); buttons.Add(button);
            var colors = button.colors; colors.normalColor = new Color(.08f, .24f, .34f); colors.highlightedColor = colors.selectedColor = colors.normalColor; button.colors = colors;
            MakeText(rect, Vector2.zero, rect.sizeDelta, label, columns == 12 ? 22 : 25);
            return button;
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

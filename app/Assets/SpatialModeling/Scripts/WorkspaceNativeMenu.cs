using System;
using System.Collections.Generic;
using System.Globalization;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using UnityEngine.XR;

namespace SpatialModeling
{
    // Real world-space controls reached by the existing stabilized controller ray.
    // The off hand holds the menu; the preferred hand points. Pin freezes its room pose.
    public sealed class WorkspaceNativeMenu : MonoBehaviour
    {
        public static WorkspaceNativeMenu Current { get; private set; }
        public bool SelectingNative { get; private set; } = true;
        public NativeEditSession Session => bridge.Session;
        public bool Pinned { get; private set; }
        public bool Visible { get; private set; } = true;
        public Action<WorkspaceNativeMenu> BuildSketchPage;
        public string Page { get; private set; } = "home";
        NativeEditBridge bridge;
        RectTransform panel, content;
        Text feedback, selected, heading;
        Font font;
        readonly List<Button> buttons = new List<Button>();
        readonly List<InputField> fields = new List<InputField>();
        InputField focused;
        string tool = "", primitive = "cube", axis = "Z", localError = "";
        InputAction toggle;
        bool heldTracked;
        Pose menuHand;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            if (FindFirstObjectByType<HostScene>() == null || FindFirstObjectByType<WorkspaceNativeMenu>() != null) return;
            var go = new GameObject("Native editing menu");
            go.AddComponent<NativeEditBridge>();
            go.AddComponent<WorkspaceNativeMenu>();
        }

        void OnEnable()
        {
            Current = this;
            bridge = GetComponent<NativeEditBridge>();
            Session.Changed += Refresh;
            WorkspaceHandPreference.Changed += Rebind;
            font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            BuildPanel();
            Rebind();
            Home();
        }

        void Rebind()
        {
            toggle?.Dispose();
            toggle = new InputAction("Native menu", InputActionType.Button);
            string offHand = WorkspaceHandPreference.Left ? "RightHand" : "LeftHand";
            toggle.AddBinding("<XRController>{" + offHand + "}/thumbstickClicked");
            toggle.AddBinding("<Keyboard>/f3");
            toggle.performed += _ => { Visible = !Visible; panel.gameObject.SetActive(Visible); };
            toggle.Enable();
            heldTracked = false;
            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
            Refresh();
        }

        void OnDisable()
        {
            toggle?.Dispose();
            Session.Changed -= Refresh;
            WorkspaceHandPreference.Changed -= Rebind;
            if (Current == this) Current = null;
            if (panel != null) Destroy(panel.gameObject);
        }

        void BuildPanel()
        {
            panel = new GameObject("Native edit controls", typeof(RectTransform), typeof(Canvas), typeof(Image), typeof(GraphicRaycaster)).GetComponent<RectTransform>();
            panel.sizeDelta = new Vector2(940, 1100);
            panel.localScale = Vector3.one * 0.00065f;
            var canvas = panel.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            panel.GetComponent<Image>().color = new Color(0.015f, 0.03f, 0.05f, 0.97f);
            heading = Label(panel, "Edit Blender", 24, 20, 890, 55, 34);
            selected = Label(panel, "", 24, 78, 890, 80, 25);
            content = new GameObject("Page", typeof(RectTransform)).GetComponent<RectTransform>();
            content.SetParent(panel, false); SetRect(content, 0, 165, 940, 720);
            feedback = Label(panel, "", 24, 902, 890, 172, 25);
        }

        void LateUpdate()
        {
            if (panel == null || Camera.main == null || !Visible) return;
            if (Pinned) return;
            if (heldTracked)
            {
                float side = WorkspaceHandPreference.Left ? 1 : -1;
                panel.position = menuHand.position + menuHand.rotation * new Vector3(side * 0.08f, 0.13f, 0.15f);
                panel.rotation = Quaternion.LookRotation(panel.position - Camera.main.transform.position, Vector3.up);
            }
            else
            {
                // Desktop/no-controller access is also useful for protocol checks.
                var camera = Camera.main.transform;
                panel.position = camera.position + camera.forward * 0.85f - camera.right * 0.42f - Vector3.up * 0.1f;
                panel.rotation = Quaternion.LookRotation(panel.position - camera.position, Vector3.up);
            }
        }

        public void UpdateMenuHand(XRNode hand, Pose pose)
        { if (hand == WorkspaceHandPreference.MenuHand) { menuHand = pose; heldTracked = true; } }

        public void TrackingLost(XRNode hand)
        { if (hand == WorkspaceHandPreference.MenuHand) heldTracked = false; }

        public bool Raycast(Ray ray, out float distance)
        {
            distance = 0;
            if (panel == null || !Visible || !panel.gameObject.activeInHierarchy) return false;
            if (!new Plane(panel.forward, panel.position).Raycast(ray, out distance) || distance < 0 || distance > 4) return false;
            return panel.rect.Contains((Vector2)panel.InverseTransformPoint(ray.GetPoint(distance)));
        }

        public bool HoverController(Ray ray, bool pressed, XRNode hand, out float distance)
        {
            if (hand != WorkspaceHandPreference.Primary || !Raycast(ray, out distance)) { distance = 0; return false; }
            var point = ray.GetPoint(distance);
            foreach (var field in fields)
                if (field.GetComponent<RectTransform>().rect.Contains((Vector2)field.transform.InverseTransformPoint(point)) && pressed)
                { focused = field; field.ActivateInputField(); }
            // A page switch destroys the old controls. Invoke at most one callback per input edge.
            foreach (var button in buttons)
            {
                if (button == null || !button.interactable) continue;
                if (!button.GetComponent<RectTransform>().rect.Contains((Vector2)button.transform.InverseTransformPoint(point))) continue;
                if (pressed) button.onClick.Invoke();
                break;
            }
            return true;
        }

        public void Select(WorkspaceObjectView view, XRNode hand)
        { if (SelectingNative && hand == WorkspaceHandPreference.Primary && view != null) { Session.Select(view.ObjectId); Refresh(); } }

        public void Home()
        {
            ClearPage("home", "Edit Blender · native commands");
            ButtonAt("Select next", 24, 0, 275, () => CycleTarget(false));
            ButtonAt("Arrange view", 333, 0, 275, () => { SelectingNative = false; Session.Cancel(); FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs(); Home(); });
            ButtonAt(Pinned ? "Hold menu" : "Pin menu", 642, 0, 275, () => { Pinned = !Pinned; Home(); });
            ButtonAt("Cube", 24, 85, 275, () => Tool("object.add", "cube"));
            ButtonAt("Sphere", 333, 85, 275, () => Tool("object.add", "sphere"));
            ButtonAt("Cylinder", 642, 85, 275, () => Tool("object.add", "cylinder"));
            ButtonAt("Move object", 24, 170, 275, () => Tool("object.move"));
            ButtonAt("Rotate object", 333, 170, 275, () => Tool("object.rotate"));
            ButtonAt("Scale object", 642, 170, 275, () => Tool("object.scale"));
            ButtonAt("Delete object", 24, 255, 275, () => Tool("object.delete"));
            ButtonAt("Undo", 333, 255, 275, () => Tool("history.undo"));
            ButtonAt("Redo", 642, 255, 275, () => Tool("history.redo"));
            ButtonAt("Save", 24, 340, 275, () => Tool("document.save"));
            var sketch = ButtonAt(Session.SketchAvailable ? "Sketch" : "Sketch unavailable", 333, 340, 275, () => BuildSketchPage?.Invoke(this));
            sketch.interactable = Session.SketchAvailable && BuildSketchPage != null;
            ButtonAt("Settings", 642, 340, 275, Settings);
            ButtonAt("Select / Edit", 24, 425, 275, () => { SelectingNative = true; Home(); });
            Label(content, "Trigger selects a native target. Grip arranges your view only.\nNative axes: X / Y / Z (Blender Z is up).\nApply requests permission, then waits for Blender's receipt.", 24, 520, 890, 150, 27);
            Refresh();
        }

        void Settings()
        {
            ClearPage("settings", "Settings");
            ButtonAt("Right hand", 24, 0, 425, () => { WorkspaceHandPreference.SetLeft(false); Settings(); });
            ButtonAt("Left hand", 485, 0, 425, () => { WorkspaceHandPreference.SetLeft(true); Settings(); });
            ButtonAt("Move Table / Recenter", 24, 100, 886, () => FindFirstObjectByType<HostScene>()?.RequestRecenter());
            ButtonAt("Show / Hide Blender", 24, 200, 886, () => FindFirstObjectByType<BlenderScreen>()?.Toggle());
            Label(content, "Primary hand points and uses shortcuts. The other hand holds the menu.\nA/X: screen · B/Y: recenter · primary stick click: magnify\nOther stick click: show/hide menu · F3 on desktop", 24, 310, 886, 170, 27);
            ButtonAt("Back", 24, 610, 886, Home);
        }

        void Tool(string op, string shape = "cube")
        {
            SelectingNative = true;
            tool = op; primitive = shape;
            bool targeted = op.StartsWith("object.") && op != "object.add";
            if (!Session.BeginDraft(op, new JObject(), targeted)) { Refresh(); return; }
            ClearPage("tool", op.Replace("object.", "") + (op == "object.add" ? " " + shape : "") + " · draft");
            if (op == "object.add")
            {
                Label(content, "Location in mm (native X, Y, Z)", 24, 0, 890, 40, 27);
                Field("X", "0", 24, 48); Field("Y", "0", 333, 48); Field("Z", "0", 642, 48);
                Label(content, "Dimensions in mm (cylinder X/Y = diameter)", 24, 130, 890, 40, 27);
                Field("X", "20", 24, 178); Field("Y", "20", 333, 178); Field("Z", "20", 642, 178);
            }
            else if (op == "object.move" || op == "object.scale")
            {
                bool move = op == "object.move";
                Label(content, move ? "Move BY mm in native axes" : "Multiply scale BY factors (unitless)", 24, 0, 890, 60, 27);
                Field("X", move ? "10" : "1", 24, 78); Field("Y", move ? "0" : "1", 333, 78); Field("Z", move ? "0" : "1", 642, 78);
            }
            else if (op == "object.rotate")
            {
                Label(content, "Rotate BY degrees around native axis", 24, 0, 890, 60, 27);
                Field("Degrees", "90", 24, 78);
                foreach (var a in new[] { "X", "Y", "Z" }) { var value = a; ButtonAt(a, 24 + Array.IndexOf(new[] { "X", "Y", "Z" }, a) * 309, 180, 275, () => { axis = value; heading.text = "Rotate about native " + axis; }); }
            }
            else Label(content, "Confirm " + op + ". Apply sends one real native command.\nSave uses Blender's current document path; an unsaved file may require Save As in Blender.", 24, 0, 890, 200, 28);
            Keypad(300);
            ButtonAt("Apply", 24, 610, 425, ApplyTool);
            ButtonAt("Cancel / Back", 485, 610, 425, () => { Session.Cancel(); Home(); });
            Refresh();
        }

        void ApplyTool()
        {
            try
            {
                if (Session.Draft == null) { localError = "Draft expired. Choose the tool again."; Refresh(); return; }
                JObject args = new JObject();
                if (tool == "object.add") args = new JObject { ["primitive"] = primitive, ["location"] = Values(0, 3, 0.001), ["dimensions"] = Values(3, 3, 0.001, true) };
                if (tool == "object.move") args["by"] = Values(0, 3, 0.001);
                if (tool == "object.scale") args["by"] = Values(0, 3, 1, true);
                if (tool == "object.rotate") args["by"] = new JObject { ["axis"] = axis, ["angle"] = Number(0) * Math.PI / 180 };
                Session.Draft["args"] = args;
                localError = "";
                Session.Apply();
            }
            catch (FormatException e) { localError = e.Message; Refresh(); }
        }

        public double Number(int index)
        {
            if (!double.TryParse(fields[index].text, NumberStyles.Float, CultureInfo.InvariantCulture, out var value)
                || double.IsNaN(value) || double.IsInfinity(value)) throw new FormatException("Enter a finite number using a decimal point");
            return value;
        }
        public JArray Values(int first, int count, double multiplier, bool positive = false)
        {
            var values = new JArray();
            for (int i = first; i < first + count; i++) { double v = Number(i) * multiplier; if (positive && v <= 0) throw new FormatException("Dimensions and scale factors must be positive"); values.Add(v); }
            return values;
        }

        public void CycleTarget(bool sketch)
        {
            var ids = new List<string>(sketch ? Session.Sketches.Keys : Session.Objects.Keys);
            ids.Sort(StringComparer.Ordinal);
            if (ids.Count == 0) return;
            int next = (ids.IndexOf(Session.SelectedId) + 1) % ids.Count;
            Session.Select(ids[next]);
        }

        public void ClearPage(string page, string title)
        {
            Page = page; heading.text = title; localError = "";
            foreach (Transform child in content) Destroy(child.gameObject);
            buttons.Clear(); fields.Clear(); focused = null;
        }

        public void Refresh()
        {
            if (selected == null) return;
            string name = (string)Session.Selected?["name"] ?? "None";
            string saved = (bool?)Session.Document["dirty"] == true ? "Unsaved" : "Saved";
            selected.text = $"Target: {name} · revision {Session.Revision}\n{(SelectingNative ? "Native edit" : "Arrange view")} · {(WorkspaceHandPreference.Left ? "Left" : "Right")} hand · {(Pinned ? "Pinned" : "Held")} · {saved}";
            feedback.text = localError.Length > 0 ? localError : Session.Notice;
            feedback.color = Session.OutcomeUnknown || !Session.Ready || localError.Length > 0 ? new Color(1, 0.7f, 0.45f) : Color.white;
        }

        public Button ButtonAt(string title, float x, float y, float width, Action action)
        {
            var go = new GameObject(title, typeof(RectTransform), typeof(Image), typeof(Button));
            go.transform.SetParent(content, false); SetRect(go.GetComponent<RectTransform>(), x, y, width, 70);
            go.GetComponent<Image>().color = new Color(0.06f, 0.22f, 0.32f, 1);
            var button = go.GetComponent<Button>(); button.onClick.AddListener(() => action());
            Label(go.transform, title, 10, 4, width - 20, 62, 25).alignment = TextAnchor.MiddleCenter;
            buttons.Add(button); return button;
        }
        public InputField Field(string title, string value, float x, float y)
        {
            var go = new GameObject(title, typeof(RectTransform), typeof(Image), typeof(InputField));
            go.transform.SetParent(content, false); SetRect(go.GetComponent<RectTransform>(), x, y, 275, 72);
            go.GetComponent<Image>().color = new Color(0.12f, 0.16f, 0.21f);
            var text = Label(go.transform, value, 12, 4, 251, 64, 28);
            var field = go.GetComponent<InputField>(); field.textComponent = text; field.contentType = InputField.ContentType.DecimalNumber; field.text = value;
            var focus = go.AddComponent<EventTrigger>();
            var entry = new EventTrigger.Entry { eventID = EventTriggerType.Select };
            entry.callback.AddListener(_ => focused = field); focus.triggers.Add(entry);
            fields.Add(field); if (focused == null) focused = field; return field;
        }
        public void Keypad(float y)
        {
            var keys = new[] { "7", "8", "9", "4", "5", "6", "1", "2", "3", "-", "0", ".", "Clear", "Backspace", "Next field" };
            for (int i = 0; i < keys.Length; i++)
            {
                string key = keys[i];
                ButtonAt(key, 24 + (i % 5) * 180, y + (i / 5) * 82, 168, () =>
                {
                    if (focused == null) return;
                    if (key == "Clear") focused.text = "";
                    else if (key == "Backspace") { if (focused.text.Length > 0) focused.text = focused.text.Substring(0, focused.text.Length - 1); }
                    else if (key == "Next field") focused = fields[(fields.IndexOf(focused) + 1) % fields.Count];
                    else focused.text += key;
                });
            }
        }
        public Text ContentLabel(string text, float y, float height = 80) => Label(content, text, 24, y, 890, height, 26);
        Text Label(Transform parent, string value, float x, float y, float width, float height, int size)
        {
            var go = new GameObject("Label", typeof(RectTransform), typeof(Text)); go.transform.SetParent(parent, false);
            SetRect(go.GetComponent<RectTransform>(), x, y, width, height);
            var text = go.GetComponent<Text>(); text.font = font; text.text = value; text.fontSize = size; text.color = Color.white;
            text.alignment = TextAnchor.UpperLeft; text.raycastTarget = false; return text;
        }
        static void SetRect(RectTransform rect, float x, float y, float width, float height)
        { rect.anchorMin = rect.anchorMax = rect.pivot = new Vector2(0, 1); rect.anchoredPosition = new Vector2(x, -y); rect.sizeDelta = new Vector2(width, height); }
    }
}

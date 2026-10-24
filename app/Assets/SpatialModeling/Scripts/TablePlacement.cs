using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.UI;
using UnityEngine.XR;

namespace SpatialModeling
{
    // P2 inspection only. There is deliberately no HostLink/command reference here.
    public sealed class TablePlacement : MonoBehaviour
    {
        public enum PlacementState { Preview, Placed, Moving, ConfirmTrackingReset }
        public PlacementState State { get; private set; } = PlacementState.Preview;
        public bool IsPlaced => State == PlacementState.Placed;
        public bool NeedsSeed => !seeded;
        public bool IsPointing => pointing && !IsPlaced;
        public float Height { get; private set; } = 0.8f;
        public float Distance { get; private set; } = 1.1f;
        public float Size { get; private set; } = 1f;
        public float Yaw { get; private set; }
        public Transform Display => display;
        Transform display, preview, panel;
        float baseScale;
        bool seeded, pointing, cancelAllowed;
        Pose savedPose;
        float savedSize, savedHeight, savedDistance, savedYaw;
        Text title;
        Material material;
        readonly List<XRInputSubsystem> subsystems = new List<XRInputSubsystem>();
        readonly List<TableAction> buttons = new List<TableAction>();
        static void ReleaseObject(UnityEngine.Object value)
        {
            if (value == null) return;
            if (Application.isPlaying) Destroy(value);
            else DestroyImmediate(value);
        }

        public void Initialize(Transform target, Material previewMaterial)
        {
            if (display != null) return;
            display = target;
            baseScale = display.localScale.x;
            // Clone an actual scene asset so its shader is retained in a Player.
            // Shader.Find alone can succeed in the Editor and be stripped in a build.
            material = new Material(previewMaterial);
            material.color = new Color(0.15f, 0.65f, 0.85f, 1);
            var table = GameObject.CreatePrimitive(PrimitiveType.Cube);
            table.name = "Table preview — local inspection only";
            preview = table.transform;
            preview.GetComponent<Renderer>().sharedMaterial = material;
            preview.GetComponent<Collider>().enabled = false;
            RequirePlacement();
        }

        void OnEnable()
        {
            SubsystemManager.GetSubsystems(subsystems);
            foreach (var subsystem in subsystems) subsystem.trackingOriginUpdated += TrackingReset;
        }

        void OnDisable()
        {
            foreach (var subsystem in subsystems) subsystem.trackingOriginUpdated -= TrackingReset;
            subsystems.Clear();
        }

        void OnDestroy()
        {
            if (preview != null) ReleaseObject(preview.gameObject);
            if (panel != null) ReleaseObject(panel.gameObject);
            if (material != null) ReleaseObject(material);
        }

        void TrackingReset(XRInputSubsystem _)
        {
            GetComponent<HostScene>()?.RequestTrackedPlacement();
            ConfirmTrackingReset();
        }

        public void ConfirmTrackingReset()
        {
            State = PlacementState.ConfirmTrackingReset;
            seeded = false;
            pointing = cancelAllowed = false;
            Refresh();
        }

        public void RequirePlacement()
        {
            State = PlacementState.Preview;
            seeded = false;
            cancelAllowed = pointing = false;
            Refresh();
        }

        public void InvalidateSeed()
        {
            // Preserve Move/Cancel's saved arrangement while hiding a pending
            // preview captured before the current worn/focused headset session.
            seeded = false;
            Refresh();
        }

        public void BeginMove()
        {
            if (display == null || State != PlacementState.Placed) return;
            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
            savedPose = new Pose(display.position, display.rotation);
            savedSize = Size;
            savedHeight = Height; savedDistance = Distance; savedYaw = Yaw;
            cancelAllowed = IsPlaced;
            State = PlacementState.Moving;
            Refresh();
        }

        public void Place()
        {
            if (display == null || !seeded) return;
            State = PlacementState.Placed;
            cancelAllowed = pointing = false;
            Refresh();
        }

        public void CancelMove()
        {
            if (!cancelAllowed) return;
            display.SetPositionAndRotation(savedPose.position, savedPose.rotation);
            Size = savedSize;
            Height = savedHeight; Distance = savedDistance; Yaw = savedYaw;
            State = PlacementState.Placed;
            pointing = cancelAllowed = false;
            Refresh();
        }

        public void ResetView()
        {
            foreach (var view in display.GetComponentsInChildren<WorkspaceObjectView>(true)) view.ResetArrangement();
            Size = 1;
            ConfirmTrackingReset(); // Explicit Place confirmation after recenter/reset.
        }

        public void SeedFromHead(Vector3 head, Vector3 forward)
        {
            forward.y = 0;
            if (forward.sqrMagnitude < 0.001f) forward = Vector3.forward;
            forward.Normalize();
            var position = head + forward * Distance;
            position.y = Height;
            display.SetPositionAndRotation(position, Quaternion.LookRotation(forward, Vector3.up));
            Yaw = display.eulerAngles.y;
            seeded = true;
            Refresh();
        }

        public bool PointAt(Ray ray)
        {
            if (IsPlaced) return false;
            var plane = new Plane(Vector3.up, Vector3.up * Height);
            if (!plane.Raycast(ray, out var distance) || distance > 5 || distance < 0.15f) return false;
            // Ray is already stabilized by the accepted WorkspaceInteraction path.
            display.position = ray.GetPoint(distance);
            seeded = true;
            Refresh();
            return true;
        }

        public void Adjust(float height, float distance, float size, float yaw, Vector3 head, Vector3 forward)
        {
            Height = Mathf.Clamp(Height + height, 0.35f, 1.5f);
            Distance = Mathf.Clamp(Distance + distance, 0.4f, 2.5f);
            Size = Mathf.Clamp(Size + size, 0.25f, 4f);
            Yaw += yaw;
            var position = display.position;
            position.y = Height;
            if (distance != 0)
            {
                forward.y = 0;
                if (forward.sqrMagnitude < 0.001f) forward = Vector3.forward;
                position = head + forward.normalized * Distance;
                position.y = Height;
            }
            display.SetPositionAndRotation(position, Quaternion.Euler(0, Yaw, 0));
            Refresh();
        }

        void Refresh()
        {
            if (display == null) return;
            display.localScale = Vector3.one * baseScale * Size;
            display.gameObject.SetActive(IsPlaced);
            if (panel != null) panel.gameObject.SetActive(seeded);
            if (preview != null)
            {
                preview.SetPositionAndRotation(display.position - Vector3.up * 0.015f, display.rotation);
                preview.localScale = new Vector3(0.65f * Size, 0.025f, 0.45f * Size);
                preview.gameObject.SetActive(!IsPlaced && seeded);
            }
        }

        void Update()
        {
            var camera = Camera.main;
            if (camera == null || display == null) return;
            var head = camera.transform;
            bool xr = XRSettings.enabled || XRSettings.isDeviceActive;
            if (xr)
            {
                var trackedHead = InputDevices.GetDeviceAtXRNode(XRNode.Head);
                if (!trackedHead.TryGetFeatureValue(UnityEngine.XR.CommonUsages.isTracked, out bool tracked) || !tracked) return;
            }
            if (!seeded) return; // HostScene supplies the common settled tracked-head pose.
            if (panel == null) CreatePanel();
            panel.SetPositionAndRotation(head.TransformPoint(new Vector3(-0.34f, -0.20f, 0.85f)), head.rotation);
            var connection = GetComponent<HostScene>();
            title.text = $"{(IsPlaced ? "Inspect table" : State == PlacementState.ConfirmTrackingReset ? "Tracking reset — confirm placement" : "Choose table position")}" +
                $"\nHeight {Height:F2} m · distance {Distance:F2} m · size {Size:F2}×\n{connection.ConnectionText}";
            var keyboard = Keyboard.current;
            if (keyboard != null)
            {
                if (keyboard.enterKey.wasPressedThisFrame) Place();
                if (keyboard.mKey.wasPressedThisFrame) BeginMove();
                if (keyboard.escapeKey.wasPressedThisFrame) CancelMove();
            }
        }

        // Use the same typed aim pose, stabilization, pointer and trigger edges
        // as P1. There is one input owner and no competing legacy table ray.
        public bool RaycastControls(Ray ray, out float distance)
        {
            distance = 4f;
            bool hit = false;
            foreach (var action in buttons)
            {
                if (action == null || !action.gameObject.activeInHierarchy) continue;
                if (action.GetComponent<Collider>().Raycast(ray, out var result, distance))
                { distance = result.distance; hit = true; }
            }
            return hit;
        }

        public bool HoverController(Ray ray, bool click)
        {
            float distance = 4f;
            TableAction selected = null;
            foreach (var action in buttons)
            {
                if (action == null || !action.gameObject.activeInHierarchy) continue;
                if (action.GetComponent<Collider>().Raycast(ray, out var result, distance))
                { distance = result.distance; selected = action; }
            }
            if (click) selected?.Invoke();
            return selected != null;
        }

        void CreatePanel()
        {
            panel = new GameObject("P2 table controls", typeof(RectTransform), typeof(Canvas)).transform;
            panel.localScale = Vector3.one * 0.001f;
            var canvas = panel.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            panel.GetComponent<RectTransform>().sizeDelta = new Vector2(620, 600);
            var header = Label(panel, "Table", new Vector2(0, 230), new Vector2(620, 120));
            title = header;
            Action<float, float, float, float> adjust = (h, d, s, y) =>
                Adjust(h, d, s, y, Camera.main.transform.position, Camera.main.transform.forward);
            var actions = new (string, Action)[] {
                ("Place Table", Place), ("Move Table", BeginMove),
                ("Point to position", () => { if (IsPlaced) BeginMove(); pointing = true; }),
                ("Cancel move", CancelMove), ("Height +", () => adjust(.05f,0,0,0)),
                ("Height −", () => adjust(-.05f,0,0,0)), ("Farther", () => adjust(0,.1f,0,0)),
                ("Closer", () => adjust(0,-.1f,0,0)), ("Larger", () => adjust(0,0,.1f,0)),
                ("Smaller", () => adjust(0,0,-.1f,0)), ("Rotate left", () => adjust(0,0,0,-15)),
                ("Rotate right", () => adjust(0,0,0,15)), ("Recenter / confirm", () => GetComponent<HostScene>()?.RequestRecenter()),
                ("Reset View", () => GetComponent<HostScene>()?.ResetObjectArrangement())
            };
            for (int i = 0; i < actions.Length; i++)
            {
                var background = new GameObject(actions[i].Item1, typeof(RectTransform), typeof(Image));
                background.transform.SetParent(panel, false);
                var rect = background.GetComponent<RectTransform>();
                rect.anchoredPosition = new Vector2((i%2 == 0 ? -1 : 1)*155, 130-i/2*58);
                rect.sizeDelta = new Vector2(300,52);
                var image = background.GetComponent<Image>();
                image.color = new Color(.02f,.05f,.09f,.96f);
                image.raycastTarget = false;
                // Render text as a child so the background sits behind it.
                Label(background.transform, actions[i].Item1, Vector2.zero, new Vector2(300,52));
                var collider = background.AddComponent<BoxCollider>();
                collider.size = new Vector3(300,52,8);
                var action = collider.gameObject.AddComponent<TableAction>();
                action.Click = actions[i].Item2;
                buttons.Add(action);
            }
        }

        static Text Label(Transform parent, string value, Vector2 position, Vector2 size)
        {
            var go = new GameObject(value, typeof(RectTransform), typeof(Text));
            go.transform.SetParent(parent, false);
            var rect = go.GetComponent<RectTransform>();
            rect.anchoredPosition = position; rect.sizeDelta = size;
            var text = go.GetComponent<Text>();
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.fontSize = 23; text.alignment = TextAnchor.MiddleCenter;
            text.color = Color.white; text.text = value; text.raycastTarget = false;
            return text;
        }
    }

    public sealed class TableAction : MonoBehaviour
    {
        public Action Click;
        public void Invoke() => Click?.Invoke();
    }
}

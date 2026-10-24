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
        public Transform Menu => panel;
        public Material PreviewMaterial => material;
        public bool MenuDocked { get; private set; } = true;
        const float MenuScale = 0.00055f;
        Transform display, preview, panel;
        float baseScale;
        bool seeded, pointing, cancelAllowed, menuTracked;
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

        public void RememberDisplayScale()
        {
            // Direct two-hand magnification stays on this display root. Keep
            // menu refresh/docking from restoring an older inspection size.
            if(display!=null && baseScale>0) Size=display.localScale.x/baseScale;
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
            if (panel != null) panel.gameObject.SetActive(seeded && (!MenuDocked || menuTracked));
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
            bool xr = XRSettings.enabled || XRSettings.isDeviceActive;
            if (xr)
            {
                var trackedHead = InputDevices.GetDeviceAtXRNode(XRNode.Head);
                if (!trackedHead.TryGetFeatureValue(UnityEngine.XR.CommonUsages.isTracked, out bool tracked) || !tracked) return;
            }
            if (!seeded) return; // HostScene supplies the common settled tracked-head pose.
            if (panel == null) CreatePanel();
            var connection = GetComponent<HostScene>();
            var arrangement=FindFirstObjectByType<WorkspaceArrangement>();
            title.text = arrangement!=null ? $"Arrange space · {(MenuDocked ? "left hand" : "in space")}\n{arrangement.SurfaceState}\nGrip menu to place it" : $"{(IsPlaced ? "Inspect table" : State == PlacementState.ConfirmTrackingReset ? "Tracking reset — confirm placement" : "Choose table position")}" +
                $" · {(MenuDocked ? "left hand" : "in space")}\nGrip menu, move, release to place" +
                $"\nHeight {Height:F2} m · size {Size:F2}× · {connection.ConnectionText}";
            var keyboard = Keyboard.current;
            if (keyboard != null)
            {
                if (keyboard.enterKey.wasPressedThisFrame) Place();
                if (keyboard.mKey.wasPressedThisFrame) BeginMove();
                if (keyboard.escapeKey.wasPressedThisFrame) CancelMove();
            }
        }

        // The accepted controller reader supplies a world-space grip pose.
        // Never add the XR origin a second time or substitute a head-relative HUD.
        public static Pose LeftHandMenuPose(Pose hand, Vector3 head)
        {
            var position = hand.position + Vector3.up * 0.16f + hand.rotation * Vector3.forward * 0.04f;
            var forward = position - head;
            if (forward.sqrMagnitude < .0001f) forward = Vector3.forward;
            var up = Mathf.Abs(Vector3.Dot(forward.normalized, Vector3.up)) > .98f ? Vector3.forward : Vector3.up;
            return new Pose(position, Quaternion.LookRotation(forward, up));
        }

        public void UpdateLeftHandMenu(Pose hand, Vector3 head, bool tracked)
        {
            menuTracked = tracked;
            if (!MenuDocked) return; // Pinned/grabbed menus have exactly one other pose writer.
            if (panel == null && seeded) CreatePanel();
            if (panel == null) return;
            if (tracked)
            {
                var pose = LeftHandMenuPose(hand, head);
                panel.SetPositionAndRotation(pose.position, pose.rotation);
            }
            panel.gameObject.SetActive(seeded && tracked);
        }

        public void PinMenu()
        {
            if (panel == null || !panel.gameObject.activeInHierarchy) return;
            MenuDocked = false;
            Debug.Log("P2_MENU_PLACEMENT world anchored; grip/release to reposition");
        }

        public void DockMenu()
        {
            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
            MenuDocked = true;
            menuTracked = false; // Wait for a current left-hand sample, not a stale pose.
            Refresh();
            Debug.Log("P2_MENU_PLACEMENT left hand; waiting for tracked grip pose");
        }

        // Use the same typed aim pose, stabilization, pointer and trigger edges
        // as P1. There is one input owner and no competing legacy table ray.
        public bool RaycastControls(Ray ray, out float distance)
        {
            distance = 4f;
            RaycastHit panelHit = default;
            bool hit = panel != null && panel.gameObject.activeInHierarchy &&
                panel.GetComponent<Collider>().Raycast(ray, out panelHit, distance);
            if (hit) distance = panelHit.distance;
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
            if (panel != null) return;
            panel = new GameObject("P2 left-hand placeable menu", typeof(RectTransform), typeof(Canvas), typeof(Image)).transform;
            panel.localScale = Vector3.one * MenuScale;
            var canvas = panel.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            var arrangement=FindFirstObjectByType<WorkspaceArrangement>();
            bool compact=arrangement!=null;
            panel.GetComponent<RectTransform>().sizeDelta = new Vector2(640, compact?580:650);
            panel.GetComponent<Image>().color = new Color(.015f,.025f,.04f,.96f);
            panel.GetComponent<Image>().raycastTarget = false;
            var surface = panel.gameObject.AddComponent<BoxCollider>();
            surface.center = new Vector3(0, -6, 5);
            surface.size = new Vector3(640, compact?580:650, 14);
            var header = Label(panel, "Table", new Vector2(0, compact?220:230), new Vector2(620, 120));
            if(compact) header.fontSize=20;
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
                ("Reset View", () => GetComponent<HostScene>()?.ResetObjectArrangement()),
                ("Pin menu here", PinMenu), ("Return to left hand", DockMenu)
            };
            if(compact) actions=new (string, Action)[] {
                ("Undo placement",arrangement.UndoPlacement), ("Recover workspace",arrangement.Recover),
                ("Desk level",()=>arrangement.Surfaces.BeginLevel("desk")),
                ("Wall level",()=>arrangement.Surfaces.BeginLevel("wall")),
                ("Floor level",()=>arrangement.Surfaces.BeginLevel("floor")),
                ("Reload room surfaces",arrangement.Surfaces.Reload),
                ("Auto detection on/off",arrangement.Surfaces.ToggleAutomatic),
                ("Show/hide detected",arrangement.Surfaces.ToggleDetected),
                ("Clear manual levels",arrangement.Surfaces.ClearLevels),
                ("Pin menu here",PinMenu), ("Return to left hand",DockMenu)
            };
            for (int i = 0; i < actions.Length; i++)
            {
                var background = new GameObject(actions[i].Item1, typeof(RectTransform), typeof(Image));
                background.transform.SetParent(panel, false);
                var rect = background.GetComponent<RectTransform>();
                rect.anchoredPosition = new Vector2((i%2 == 0 ? -1 : 1)*155, 130-i/2*(compact?65:58));
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
            panel.gameObject.SetActive(seeded && (!MenuDocked || menuTracked));
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

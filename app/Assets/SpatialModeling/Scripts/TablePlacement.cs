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
        public bool IsActualSize => Mathf.Approximately(Size, 1f);
        public string ScaleLabel => IsActualSize ? "Actual size · 1:1"
            : $"Inspection size · {Size.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)}×";
        public float Yaw { get; private set; }
        public Transform Display => display;
        public Transform Menu => panel;
        public Material PreviewMaterial => material;
        public bool MenuDocked { get; private set; } = true;
        const float MenuScale = 0.00055f;
        Transform display, preview, panel;
        bool seeded, pointing, cancelAllowed, menuTracked;
        Pose savedPose;
        float savedSize, savedHeight, savedDistance, savedYaw;
        Text title;
        enum MenuPage { Arrange, Settings, Planes, Environment }
        MenuPage menuPage;
        int planePage;
        string planeNotice;
        public bool SettingsOpen => menuPage == MenuPage.Settings;
        WorkspaceRoomSetup roomSetup;
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
            // Size is an explicit inspection multiplier relative to metres,
            // never relative to a hidden scale inherited from the scene.
            Size = 1f;
            display.localScale = Vector3.one;
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
            if(display!=null) Size=display.localScale.x;
        }

        public void RestoreActualSize()
        {
            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
            Size = 1f;
            Refresh();
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
            display.localScale = Vector3.one * Size;
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
            var arrangement=GetComponent<WorkspaceArrangement>() ?? FindFirstObjectByType<WorkspaceArrangement>();
            title.text = arrangement!=null ? MenuHeading(arrangement) : $"{(IsPlaced ? "Inspect table" : State == PlacementState.ConfirmTrackingReset ? "Tracking reset — confirm placement" : "Choose table position")}" +
                $" · {(MenuDocked ? "left hand" : "in space")}\nGrip menu, move, release to place" +
                $"\nHeight {Height:F2} m · {ScaleLabel} · {connection.ConnectionText}";
            var keyboard = Keyboard.current;
            if (keyboard != null && !PreviewInteraction.BlocksDesktopShortcuts)
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
            if(selected==null) return false;
            // Page callbacks may destroy/rebuild this action. Retain the hit
            // result so the same trigger cannot fall through after dispatch.
            if(click) selected.Invoke();
            return true;
        }

        void CreatePanel()
        {
            if (panel != null) return;
            if(roomSetup==null) roomSetup=gameObject.AddComponent<WorkspaceRoomSetup>();
            panel = new GameObject("P2 left-hand placeable menu", typeof(RectTransform), typeof(Canvas), typeof(Image)).transform;
            panel.localScale = Vector3.one * MenuScale;
            var canvas = panel.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            var arrangement=GetComponent<WorkspaceArrangement>() ?? FindFirstObjectByType<WorkspaceArrangement>();
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
                ("Add horizontal plane",()=>arrangement.Surfaces.BeginPlane("horizontal")),
                ("Add vertical plane",()=>arrangement.Surfaces.BeginPlane("vertical")),
                ("Manage planes",()=>ChangeMenu(MenuPage.Planes)), ("Actual size",RestoreActualSize),
                ("Pin menu here",PinMenu), ("Return to left hand",DockMenu),
            };
            if(compact && menuPage==MenuPage.Settings) actions=new (string,Action)[] {
                ("Show room geometry",()=>{ arrangement.Surfaces.ToggleDetected(); RefreshMenu(); }),
                ("Auto surfaces on/off",arrangement.Surfaces.ToggleAutomatic),
                ("Environment setup",()=>SetupMenu(true)), ("Manage planes",()=>ChangeMenu(MenuPage.Planes)),
                ("Surface help on/off",arrangement.ToggleAssist), ("Actual size",RestoreActualSize),
                (FindFirstObjectByType<BlenderScreen>()?.PositionLocked == true ? "Unlock Blender screen" : "Lock Blender screen",
                    ()=>{ FindFirstObjectByType<BlenderScreen>()?.TogglePositionLock(); RefreshMenu(); }),
                ("Back to arrange",()=>ChangeMenu(MenuPage.Arrange))
            };
            if(compact && menuPage==MenuPage.Environment) actions=new (string,Action)[] {
                ("Load saved room",arrangement.Surfaces.Reload), ("Scan / update on Quest",roomSetup.Scan),
                ("Show room geometry",()=>{ arrangement.Surfaces.ToggleDetected(); RefreshMenu(); }),
                ("Back to Settings",()=>ChangeMenu(MenuPage.Settings))
            };
            if(compact && menuPage==MenuPage.Planes) actions=PlaneActions(arrangement.Surfaces);
            if(compact) title.text=MenuHeading(arrangement);
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
            if(compact)
            {
                var gear=new GameObject("Settings",typeof(RectTransform),typeof(CanvasRenderer),typeof(SettingsGearGraphic),typeof(BoxCollider),typeof(TableAction));
                gear.transform.SetParent(panel,false);
                var rect=gear.GetComponent<RectTransform>();
                rect.anchoredPosition=new Vector2(265,-240); rect.sizeDelta=new Vector2(64,64);
                gear.GetComponent<SettingsGearGraphic>().color=new Color(.85f,.94f,1);
                gear.GetComponent<SettingsGearGraphic>().raycastTarget=false;
                gear.GetComponent<BoxCollider>().size=new Vector3(64,64,8);
                var action=gear.GetComponent<TableAction>();
                action.Click=()=>ChangeMenu(menuPage==MenuPage.Settings?MenuPage.Arrange:MenuPage.Settings);
                buttons.Add(action);
            }
            panel.gameObject.SetActive(seeded && (!MenuDocked || menuTracked));
        }

        string MenuHeading(WorkspaceArrangement arrangement)
        {
            if(menuPage==MenuPage.Environment) return roomSetup.Heading;
            if(menuPage==MenuPage.Settings) return "Settings\nRoom geometry: "+(arrangement.Surfaces.ShowDetected?"shown":"hidden")+
                " · auto surfaces: "+(arrangement.Surfaces.AutomaticEnabled?"on":"off")+
                "\nSurface help: "+(arrangement.AssistEnabled?"on":"off")+"\n"+ScaleLabel;
            if(menuPage==MenuPage.Planes) return "Horizontal / vertical planes\n"+(string.IsNullOrEmpty(planeNotice)?"Manual corrections stay independent":planeNotice)+"\nPage "+(planePage+1)+" · "+arrangement.Surfaces.PlaneTargets.Count+" planes";
            return $"Arrange space · {(MenuDocked ? "left hand" : "in space")}\n{arrangement.SurfaceState}\n{ScaleLabel}\nGrip menu to place it";
        }

        (string,Action)[] PlaneActions(WorkspaceSurfaces surfaces)
        {
            const int perPage=3;
            var planes=surfaces.PlaneTargets;
            int pages=Mathf.Max(1,(planes.Count+perPage-1)/perPage);
            planePage=Mathf.Clamp(planePage,0,pages-1);
            var result=new List<(string,Action)>();
            for(int i=planePage*perPage;i<Mathf.Min(planes.Count,(planePage+1)*perPage);i++)
            {
                var target=planes[i]; var label=surfaces.PlaneLabel(target);
                result.Add(("Align "+label,()=>{planeNotice=surfaces.AlignPlaneToDetected(target)?"Aligned once · future grabs stay free":"No matching detected surface nearby";RefreshMenu();}));
                result.Add(("Delete "+label,()=>{surfaces.DeletePlane(target);planeNotice="Deleted "+label;RefreshMenu();}));
            }
            if(pages>1) {
                result.Add(("Previous planes",()=>{planePage=(planePage+pages-1)%pages;RefreshMenu();}));
                result.Add(("Next planes",()=>{planePage=(planePage+1)%pages;RefreshMenu();}));
            }
            result.Add(("Back to arrange",()=>ChangeMenu(MenuPage.Arrange)));
            return result.ToArray();
        }

        void ChangeMenu(MenuPage page)
        {
            menuPage=page;
            planeNotice=null;
            if(roomSetup!=null) { if(page==MenuPage.Environment) roomSetup.Open();else roomSetup.Close(); }
            RefreshMenu();
        }

        void RefreshMenu()
        {
            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
            if(panel==null) return;
            var pose=new Pose(panel.position,panel.rotation);
            panel.gameObject.SetActive(false);ReleaseObject(panel.gameObject);panel=null;buttons.Clear();
            CreatePanel();panel.SetPositionAndRotation(pose.position,pose.rotation);
        }

        void SetupMenu(bool open)
        {
            ChangeMenu(open?MenuPage.Environment:MenuPage.Arrange);
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

    // Code-drawn gear: no dependency on a platform font containing a gear glyph.
    [RequireComponent(typeof(CanvasRenderer))]
    public sealed class SettingsGearGraphic : MaskableGraphic
    {
        protected override void OnPopulateMesh(VertexHelper helper)
        {
            helper.Clear(); const int count=48;
            float size=Mathf.Min(rectTransform.rect.width,rectTransform.rect.height)*.46f;
            var center=rectTransform.rect.center;
            for(int i=0;i<count;i++)
            {
                float angle=i*Mathf.PI*2/count;
                var direction=new Vector2(Mathf.Sin(angle),Mathf.Cos(angle));
                float radius=(i%6==0||i%6==5)?size*.76f:size;
                helper.AddVert(center+direction*radius,color,Vector2.zero);
                helper.AddVert(center+direction*size*.38f,color,Vector2.zero);
            }
            for(int i=0;i<count;i++) {
                int a=i*2,b=((i+1)%count)*2;
                helper.AddTriangle(a,b,a+1);helper.AddTriangle(a+1,b,b+1);
            }
        }
    }
}

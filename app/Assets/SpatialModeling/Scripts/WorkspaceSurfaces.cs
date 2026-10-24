using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR;
using UnityEngine.XR.OpenXR;

namespace SpatialModeling
{
    // Scene anchors and controllers use the same tracking origin, exactly once.
    // Levels are session-only; a changed room origin invalidates manual calibration.
    public sealed class WorkspaceSurfaces : MonoBehaviour
    {
        public struct Surface
        {
            public string Name;
            public Pose Pose;
            public Vector2 Size;
            public Vector3 Normal => Pose.rotation * Vector3.forward;
        }
        struct RoomAnchor { public OVRAnchor Anchor; public OVRLocatable Locatable; public Guid Room; public string Kind; }
        sealed class Level { public string Kind; public Transform Target; public Vector2 Size; public Text Label; }
        readonly List<RoomAnchor> anchors = new List<RoomAnchor>();
        readonly List<Surface> surfaces = new List<Surface>();
        readonly List<Surface> detected = new List<Surface>();
        readonly List<Level> levels = new List<Level>();
        readonly List<OVRSemanticLabels.Classification> labels = new List<OVRSemanticLabels.Classification>();
        readonly List<XRInputSubsystem> subsystems = new List<XRInputSubsystem>();
        readonly List<LineRenderer> outlines = new List<LineRenderer>();
        readonly HashSet<Guid> invalidLogged = new HashSet<Guid>();
        public IReadOnlyList<Surface> Surfaces => surfaces;
        public bool AutomaticEnabled { get; private set; } = true;
        public bool ShowDetected { get; private set; } = true;
        public string State => AutomaticEnabled ? message + "\n" + Counts(detected) + " · levels " + levels.Count
            : "Auto detection OFF · levels " + levels.Count;
        public int LevelCount => levels.Count;
        string message = "Checking saved room";
        bool loading, disposed, reloadPending, wasPresent;
        int generation, attempts, roomCount;
        float retryAt;
        Material levelMaterial, detectedMaterial;
        Transform Origin => Camera.main != null ? Camera.main.transform.parent : null;

        IEnumerator Start()
        {
            float until = Time.realtimeSinceStartup + 12;
            while (!OVRPlugin.initialized && Time.realtimeSinceStartup < until) yield return null;
            Reload();
        }
        void OnEnable()
        {
            SubsystemManager.GetSubsystems(subsystems);
            foreach (var system in subsystems) system.trackingOriginUpdated += TrackingReset;
        }
        void OnDisable()
        {
            foreach (var system in subsystems) system.trackingOriginUpdated -= TrackingReset;
            subsystems.Clear();
        }
        void OnDestroy()
        {
            disposed = true; generation++;
            ClearAnchors(); ClearLevels();
            foreach (var outline in outlines) if (outline != null) DestroyObject(outline.gameObject);
            if (levelMaterial != null) DestroyObject(levelMaterial);
            if (detectedMaterial != null) DestroyObject(detectedMaterial);
        }
        static void DestroyObject(UnityEngine.Object value)
        { if (Application.isPlaying) Destroy(value); else DestroyImmediate(value); }
        void ClearAnchors()
        {
            foreach (var item in anchors) item.Anchor.Dispose();
            anchors.Clear(); detected.Clear(); surfaces.Clear(); invalidLogged.Clear();
        }
        void TrackingReset(XRInputSubsystem _)
        {
            generation++; ClearAnchors(); ClearLevels();
            message = "Room origin changed · reloading room";
            attempts = 0; Reload();
        }
        void OnApplicationFocus(bool focus)
        { if (focus && Application.isPlaying && AutomaticEnabled) { attempts = 0; Reload(); } }
        void Update()
        {
            var headset = InputDevices.GetDeviceAtXRNode(XRNode.Head);
            headset.TryGetFeatureValue(CommonUsages.userPresence, out bool present);
            if (present && !wasPresent && AutomaticEnabled) { attempts = 0; Reload(); }
            wasPresent = present;
            if (present && AutomaticEnabled && detected.Count == 0 && !loading && attempts < 3
                && Time.realtimeSinceStartup >= retryAt) Reload();
        }
        public void ToggleAutomatic()
        {
            AutomaticEnabled = !AutomaticEnabled; generation++; ClearAnchors();
            if (AutomaticEnabled) { attempts = 0; Reload(); }
            RefreshVisuals();
        }
        public void ToggleDetected() { ShowDetected = !ShowDetected; RefreshVisuals(); }

        // The SDK only accepts the first 50 UUIDs in one request.
        public static List<Guid[]> Batches(IEnumerable<Guid> values)
        {
            var unique = new HashSet<Guid>(values); unique.Remove(Guid.Empty);
            var result = new List<Guid[]>(); var batch = new List<Guid>();
            foreach (var id in unique)
            {
                batch.Add(id);
                if (batch.Count == 50) { result.Add(batch.ToArray()); batch.Clear(); }
            }
            if (batch.Count > 0) result.Add(batch.ToArray());
            return result;
        }
        public async void Reload()
        {
            if (disposed || !AutomaticEnabled) return;
            if (loading) { reloadPending = true; return; }
            if (!OVRPlugin.initialized || !OpenXRRuntime.IsExtensionEnabled("XR_FB_scene"))
            { message = "Room data unavailable · use a level"; retryAt = Time.realtimeSinceStartup + 15; attempts++; return; }
            loading = true; reloadPending = false; attempts++; retryAt = Time.realtimeSinceStartup + 15;
            int version = ++generation;
            ClearAnchors(); roomCount = 0;
            var owned = new List<OVRAnchor>();
            var rooms = new List<OVRAnchor>();
            var next = new List<RoomAnchor>();
            bool Current() => !disposed && version == generation && AutomaticEnabled;
            try
            {
                message = "Loading saved room";
                var result = await OVRAnchor.FetchAnchorsAsync(rooms,
                    new OVRAnchor.FetchOptions { SingleComponentType = typeof(OVRRoomLayout) });
                owned.AddRange(rooms);
                if (!Current()) return;
                if (!result.Success) { message = "Room query failed · retry or use a level"; Debug.LogWarning("WORKSPACE_SURFACES rooms status=" + result.Status); return; }
                roomCount = rooms.Count;
                if (rooms.Count == 0)
                { message = "No room data · scan room / check Link spatial data"; return; }
                foreach (var room in rooms)
                {
                    var ids = new HashSet<Guid>(); var kinds = new Dictionary<Guid,string>();
                    if (room.TryGetComponent<OVRRoomLayout>(out var layout)
                        && layout.TryGetRoomLayout(out _, out var floor, out var walls))
                    {
                        ids.Add(floor); kinds[floor] = "Floor";
                        foreach (var wall in walls) { ids.Add(wall); kinds[wall] = "Wall"; }
                    }
                    if (room.TryGetComponent<OVRAnchorContainer>(out var container))
                        foreach (var id in container.Uuids) ids.Add(id); // Includes desks/furniture, not just room bounds.
                    foreach (var batch in Batches(ids))
                    {
                        var children = new List<OVRAnchor>();
                        var childrenResult = await OVRAnchor.FetchAnchorsAsync(children, new OVRAnchor.FetchOptions { Uuids = batch });
                        owned.AddRange(children);
                        if (!Current()) return;
                        if (!childrenResult.Success) { Debug.LogWarning("WORKSPACE_SURFACES children status=" + childrenResult.Status); continue; }
                        foreach (var anchor in children)
                        {
                            if (!anchor.TryGetComponent<OVRLocatable>(out var locatable)) continue;
                            await locatable.SetEnabledAsync(true);
                            if (!Current()) return;
                            if (!locatable.IsEnabled || next.Exists(a => a.Anchor.Uuid == anchor.Uuid)) continue;
                            kinds.TryGetValue(anchor.Uuid, out var kind);
                            next.Add(new RoomAnchor { Anchor = anchor, Locatable = locatable, Room = room.Uuid, Kind = kind });
                        }
                    }
                }
                if (!Current()) return;
                anchors.AddRange(next);
                message = anchors.Count == 0 ? "Room found · surfaces unavailable · use a level" : "Saved room loaded";
            }
            catch (Exception error)
            {
                if (Current()) message = "Room data unavailable · retry or use a level";
                Debug.LogWarning("WORKSPACE_SURFACES " + error.GetType().Name + ": " + error.Message);
            }
            finally
            {
                // A query completing after reset/toggle/destruction must not resurrect stale anchors.
                var released = new List<OVRAnchor>();
                foreach (var anchor in owned)
                    if (!anchors.Exists(a => a.Anchor.Equals(anchor)) && !released.Contains(anchor))
                    { anchor.Dispose(); released.Add(anchor); }
                loading = false;
                Debug.Log("WORKSPACE_SURFACES rooms=" + roomCount + " anchors=" + anchors.Count + " " + message);
                if (reloadPending && !disposed && AutomaticEnabled) Reload();
            }
        }

        public static Pose LevelPose(string kind, Pose desired)
        {
            bool wall = kind == "wall";
            var axis = Vector3.ProjectOnPlane(desired.rotation * (wall ? Vector3.forward : Vector3.up), Vector3.up);
            if (axis.sqrMagnitude < .001f) axis = Vector3.forward;
            return new Pose(desired.position, wall ? Quaternion.LookRotation(axis, Vector3.up)
                : Quaternion.LookRotation(Vector3.up, axis));
        }
        public bool IsLevel(Transform target) => levels.Exists(l => l.Target == target);
        public Pose ConstrainLevel(Transform target, Pose desired)
        { var level = levels.Find(l => l.Target == target); return level == null ? desired : LevelPose(level.Kind, desired); }
        public Transform CreateLevel(string kind, Pose desired)
        {
            if (kind != "desk" && kind != "floor" && kind != "wall") throw new ArgumentException("Unknown level kind");
            EnsureMaterials();
            var level = levels.Find(l => l.Kind == kind);
            if (level == null)
            {
                var target = new GameObject(kind + " movable level").transform;
                target.SetParent(Origin, false);
                level = new Level { Kind = kind, Target = target, Size = kind == "desk" ? new Vector2(1.2f,.8f) : new Vector2(2.4f,2.4f) };
                levels.Add(level);
                var line = MakeLine(target, levelMaterial); DrawGrid(line, level.Size);
                var label = new GameObject("Level grip handle", typeof(RectTransform), typeof(Canvas), typeof(Text));
                label.transform.SetParent(target, false); label.transform.localScale = Vector3.one * .001f;
                label.GetComponent<Canvas>().renderMode = RenderMode.WorldSpace;
                label.GetComponent<RectTransform>().sizeDelta = new Vector2(500,100);
                level.Label = label.GetComponent<Text>(); level.Label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                level.Label.fontSize = 28; level.Label.alignment = TextAnchor.MiddleCenter; level.Label.color = Color.white;
                level.Label.text = kind.ToUpperInvariant() + " LEVEL\nGrip grid/label · move · release to place";
                level.Label.raycastTarget = false;
            }
            var pose = LevelPose(kind, desired); level.Target.SetPositionAndRotation(pose.position, pose.rotation);
            level.Target.localScale = Vector3.one;
            RebuildSurfaces();
            return level.Target;
        }
        public void BeginLevel(string kind)
        {
            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
            var camera = Camera.main; if (camera == null) return;
            var forward = Vector3.ProjectOnPlane(camera.transform.forward, Vector3.up).normalized;
            if (forward.sqrMagnitude < .5f) forward = Vector3.forward;
            var position = camera.transform.position + forward * .8f;
            if (kind != "wall") position.y -= kind == "desk" ? .6f : 1.2f;
            CreateLevel(kind, new Pose(position, kind == "wall" ? Quaternion.LookRotation(-forward,Vector3.up)
                : Quaternion.LookRotation(Vector3.up,forward)));
        }
        public void ClearLevels()
        {
            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
            foreach (var level in levels) if (level.Target != null) DestroyObject(level.Target.gameObject);
            levels.Clear(); surfaces.Clear();
        }
        public Transform RaycastLevel(Ray ray, out float distance)
        {
            distance = float.PositiveInfinity; Transform target = null;
            foreach (var level in levels)
            {
                var center = level.Target.position;
                // A small central handle also works when a horizontal level is viewed edge-on.
                float along = Vector3.Dot(center + Vector3.up*.06f - ray.origin,ray.direction);
                if (along > 0 && Vector3.Distance(ray.GetPoint(along), center + Vector3.up*.06f) < .13f && along < distance)
                { distance = along; target = level.Target; }
                var plane = new Plane(level.Target.forward, center);
                if (!plane.Raycast(ray, out float hit) || hit >= distance) continue;
                var local = level.Target.InverseTransformPoint(ray.GetPoint(hit));
                if (Mathf.Abs(local.x) <= level.Size.x*.5f && Mathf.Abs(local.y) <= level.Size.y*.5f)
                { distance = hit; target = level.Target; }
            }
            return target;
        }
        void LateUpdate()
        {
            detected.Clear(); var candidates = new List<(Guid room, Surface surface)>(); Guid currentRoom = Guid.Empty;
            foreach (var item in anchors)
            {
                if (!item.Locatable.TryGetSceneAnchorPose(out var tracked) || !tracked.Position.HasValue
                    || !tracked.Rotation.HasValue || !tracked.IsPositionTracked || !tracked.IsRotationTracked) continue;
                try
                {
                    string kind = item.Kind;
                    if (kind == null && item.Anchor.TryGetComponent<OVRSemanticLabels>(out var semantic))
                    {
                        labels.Clear(); semantic.GetClassifications(labels);
                        if (labels.Contains(OVRSemanticLabels.Classification.Table)) kind = "Desk";
                    }
                    if (kind == null) continue;
                    var world = WorkspaceInteraction.ToWorldPose(Origin, new Pose(tracked.Position.Value,tracked.Rotation.Value));
                    Surface surface;
                    // Furniture may expose both a vertical plane and a volume. Its top face is the desk.
                    if (kind == "Desk" && item.Anchor.TryGetComponent<OVRBounded3D>(out var volume))
                        surface = DeskTop(world,volume.BoundingBox);
                    else if (item.Anchor.TryGetComponent<OVRBounded2D>(out var plane))
                    {
                        var bounds = plane.BoundingBox; var center = world.position + world.rotation * new Vector3(bounds.center.x,bounds.center.y,0);
                        var normal = world.rotation * Vector3.forward;
                        var toward = kind != "Wall" ? Vector3.up : (Camera.main != null ? Camera.main.transform.position-center : normal);
                        if (Vector3.Dot(normal,toward)<0) normal=-normal;
                        surface = new Surface { Name=kind,Pose=new Pose(center,Quaternion.LookRotation(normal,world.rotation*Vector3.up)),Size=bounds.size };
                    }
                    else continue;
                    if (surface.Size.x <= .01f || surface.Size.y <= .01f) continue;
                    candidates.Add((item.Room,surface));
                    if (kind == "Floor" && Camera.main != null)
                    {
                        var local = Quaternion.Inverse(surface.Pose.rotation)*(Camera.main.transform.position-surface.Pose.position);
                        if (Mathf.Abs(local.x) <= surface.Size.x*.5f && Mathf.Abs(local.y) <= surface.Size.y*.5f) currentRoom=item.Room;
                    }
                }
                catch (Exception error) { if(invalidLogged.Add(item.Anchor.Uuid)) Debug.LogWarning("WORKSPACE_SURFACES invalid surface " + error.GetType().Name); }
            }
            foreach (var item in candidates) if (roomCount == 1 || item.room == currentRoom) detected.Add(item.surface);
            if (!loading && anchors.Count > 0) message = detected.Count > 0 ? "Saved room loaded" : "Room not localized · look around or use a level";
            foreach (var level in levels)
            {
                // Label faces the wearer; the calibrated plane itself never follows the head.
                level.Label.transform.position = level.Target.position + Vector3.up*.06f;
                if (Camera.main != null) level.Label.transform.rotation = Quaternion.LookRotation(level.Label.transform.position-Camera.main.transform.position,Vector3.up);
            }
            RebuildSurfaces(); RefreshVisuals();
        }
        public static Surface DeskTop(Pose world, Bounds bounds)
        {
            var axes=new[]{world.rotation*Vector3.right,world.rotation*Vector3.up,world.rotation*Vector3.forward};
            int top=0; for(int i=1;i<3;i++) if(Mathf.Abs(axes[i].y)>Mathf.Abs(axes[top].y)) top=i;
            var normal=axes[top]*Mathf.Sign(axes[top].y);
            return new Surface { Name="Desk",Pose=new Pose(world.position+world.rotation*bounds.center+normal*bounds.extents[top],
                Quaternion.LookRotation(normal,axes[(top+1)%3])), Size=new Vector2(bounds.size[(top+2)%3],bounds.size[(top+1)%3]) };
        }
        void RebuildSurfaces()
        {
            surfaces.Clear();
            foreach (var level in levels) surfaces.Add(new Surface {Name=Title(level.Kind),Pose=new Pose(level.Target.position,level.Target.rotation),
                Size=Vector2.Scale(level.Size,new Vector2(level.Target.lossyScale.x,level.Target.lossyScale.y))});
            if (AutomaticEnabled) foreach (var surface in detected)
                if (!levels.Exists(l => Title(l.Kind) == surface.Name)) surfaces.Add(surface);
        }
        static string Title(string kind) => char.ToUpperInvariant(kind[0])+kind.Substring(1);
        static string Counts(List<Surface> values)
            => "Desk " + values.FindAll(s=>s.Name=="Desk").Count + " · floor " + values.FindAll(s=>s.Name=="Floor").Count + " · wall " + values.FindAll(s=>s.Name=="Wall").Count;
        void EnsureMaterials()
        {
            if (levelMaterial != null) return;
            var table=FindFirstObjectByType<TablePlacement>(); var source=table!=null?table.PreviewMaterial:null;
            levelMaterial=source!=null?new Material(source):new Material(Shader.Find("UI/Default"));
            levelMaterial.color=new Color(1,.75f,.15f,1);
            detectedMaterial=new Material(levelMaterial); detectedMaterial.color=new Color(.1f,.85f,.7f,1);
        }
        static LineRenderer MakeLine(Transform parent, Material material)
        {
            var go=new GameObject("Visible surface grid",typeof(LineRenderer)); go.transform.SetParent(parent,false);
            var line=go.GetComponent<LineRenderer>(); line.sharedMaterial=material; line.useWorldSpace=false;
            line.startWidth=line.endWidth=.003f; return line;
        }
        static void DrawGrid(LineRenderer line, Vector2 size)
        {
            var points=new List<Vector3>();
            for(int i=0;i<=6;i++) {float u=i/6f-.5f,sign=i%2==0?1:-1;
                points.Add(new Vector3(u*size.x,-sign*size.y*.5f,.004f)); points.Add(new Vector3(u*size.x,sign*size.y*.5f,.004f));}
            for(int i=0;i<=6;i++) {float u=.5f-i/6f,sign=i%2==0?1:-1;
                points.Add(new Vector3(sign*size.x*.5f,u*size.y,.004f)); points.Add(new Vector3(-sign*size.x*.5f,u*size.y,.004f));}
            line.positionCount=points.Count; line.SetPositions(points.ToArray());
        }
        void RefreshVisuals()
        {
            if (detected.Count>0) EnsureMaterials();
            for(int i=0;i<detected.Count;i++)
            {
                if(i>=outlines.Count) outlines.Add(MakeLine(transform,detectedMaterial));
                var surface=detected[i]; var line=outlines[i];
                line.transform.SetPositionAndRotation(surface.Pose.position,surface.Pose.rotation); DrawGrid(line,surface.Size);
                line.gameObject.SetActive(AutomaticEnabled && ShowDetected && !levels.Exists(l=>Title(l.Kind)==surface.Name));
            }
            for(int i=detected.Count;i<outlines.Count;i++) outlines[i].gameObject.SetActive(false);
        }
    }
}

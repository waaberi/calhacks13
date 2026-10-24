using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR;
using UnityEngine.XR.OpenXR;

namespace SpatialModeling
{
    // Scene anchors and controllers use the same tracking origin, exactly once.
    // Levels are session-only; a changed room origin invalidates manual calibration.
    public sealed partial class WorkspaceSurfaces : MonoBehaviour
    {
        public struct Surface
        {
            public string Name;
            public Guid Id;
            public Pose Pose;
            public Vector2 Size;
            public Vector2[] Boundary;
            public string GeometrySource;
            public Vector3 Normal => Pose.rotation * Vector3.forward;
        }
        struct RoomAnchor { public OVRAnchor Anchor; public OVRLocatable Locatable; public Guid Room; public string Kind; }
        sealed class Level { public string Kind; public Transform Target, LabelRoot, Handle; public Vector2 Size; public Text Label; public Guid? Replaces; }
        readonly List<RoomAnchor> anchors = new List<RoomAnchor>();
        readonly List<Surface> surfaces = new List<Surface>();
        readonly List<Surface> detected = new List<Surface>();
        readonly List<Level> levels = new List<Level>();
        readonly List<XRInputSubsystem> subsystems = new List<XRInputSubsystem>();
        readonly List<LineRenderer> outlines = new List<LineRenderer>();
        readonly HashSet<Guid> invalidLogged = new HashSet<Guid>();
        bool evidenceWritten;
        [Serializable] public sealed class RoomEvidence
        {
            public string trackingOrigin;
            public Pose metaHead, unityHead, cameraWorld, originWorld;
            public List<AnchorEvidence> anchors=new List<AnchorEvidence>();
        }
        [Serializable] public sealed class AnchorEvidence
        {
            public string id,kind,labels,classifications;
            public Pose trackingPose;
            public bool plane,volume;
            public Rect planeBounds;
            public Bounds volumeBounds;
            public Vector2[] boundary;
        }
        public IReadOnlyList<Surface> Surfaces => surfaces;
        public bool AutomaticEnabled { get; private set; } = true;
        public bool ShowDetected { get; private set; } = true;
        public string State => AutomaticEnabled ? message + "\n" + Counts(detected) + " · " + GeometrySummary + " · levels " + levels.Count
            : "Auto detection OFF · levels " + levels.Count;
        public int LevelCount => levels.Count;
        public int DetectedCount => detected.Count;
        string message = "Checking saved room";
        string lastCounts;
        string pendingLevel;
        bool loading, disposed, reloadPending, wasPresent;
        int generation, attempts, roomCount;
        float retryAt;
        Material levelMaterial, detectedMaterial, contrastMaterial;
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
            if (contrastMaterial != null) DestroyObject(contrastMaterial);
        }
        static void DestroyObject(UnityEngine.Object value)
        { if (Application.isPlaying) Destroy(value); else DestroyImmediate(value); }
        void ClearAnchors()
        {
            foreach (var item in anchors) item.Anchor.Dispose();
            anchors.Clear(); detected.Clear(); surfaces.Clear(); invalidLogged.Clear(); evidenceWritten=false;
            ClearScanGeometry();
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
                Debug.Log("WORKSPACE_SURFACES discovery rooms="+rooms.Count+" status="+result.Status);
                // Link also exposes the earlier FB query API. Try it only when discovery
                // fails/returns no data; this is a compatibility path, not evidence of a scan.
                if ((!result.Success || rooms.Count == 0) && OpenXRRuntime.IsExtensionEnabled("XR_FB_spatial_entity_query"))
                {
                    rooms = new List<OVRAnchor>();
#pragma warning disable CS0618
                    bool legacy = await OVRAnchor.FetchAnchorsAsync<OVRRoomLayout>(rooms, timeout: 5);
#pragma warning restore CS0618
                    owned.AddRange(rooms);
                    if (!Current()) return;
                    Debug.Log("WORKSPACE_SURFACES compatibility rooms="+rooms.Count+" success="+legacy);
                }
                roomCount = rooms.Count;
                if (rooms.Count == 0)
                {
                    // Some runtimes expose labelled elements without a RoomLayout root.
                    // These are still real saved scene anchors, never synthetic desks/walls.
                    var elements = new List<OVRAnchor>();
                    var elementsResult = await OVRAnchor.FetchAnchorsAsync(elements,
                        new OVRAnchor.FetchOptions { SingleComponentType = typeof(OVRSemanticLabels) });
                    owned.AddRange(elements);
                    if (!Current()) return;
                    Debug.Log("WORKSPACE_SURFACES discovery labelled="+elements.Count+" status="+elementsResult.Status);
                    if ((!elementsResult.Success || elements.Count == 0) && OpenXRRuntime.IsExtensionEnabled("XR_FB_spatial_entity_query"))
                    {
                        elements = new List<OVRAnchor>();
#pragma warning disable CS0618
                        bool legacy = await OVRAnchor.FetchAnchorsAsync<OVRSemanticLabels>(elements, timeout: 5);
#pragma warning restore CS0618
                        owned.AddRange(elements);
                        if (!Current()) return;
                        Debug.Log("WORKSPACE_SURFACES compatibility labelled="+elements.Count+" success="+legacy);
                    }
                    foreach (var anchor in elements)
                    {
                        if (!anchor.TryGetComponent<OVRLocatable>(out var locatable)) continue;
                        await locatable.SetEnabledAsync(true);
                        if (!Current()) return;
                        if (locatable.IsEnabled && !next.Exists(a=>a.Anchor.Uuid==anchor.Uuid))
                            next.Add(new RoomAnchor { Anchor=anchor,Locatable=locatable });
                    }
                    if (!Current()) return;
                    anchors.AddRange(next);
                    ReadScanGeometry();
                    message = anchors.Count > 0 ? "Saved surfaces loaded" : "No room data received · adjust/add a level";
                    return;
                }
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
                        if ((!childrenResult.Success || children.Count == 0) && OpenXRRuntime.IsExtensionEnabled("XR_FB_spatial_entity_query"))
                        {
                            children = new List<OVRAnchor>();
#pragma warning disable CS0618
                            bool legacy = await OVRAnchor.FetchAnchorsAsync(batch, children, timeout: 5);
#pragma warning restore CS0618
                            owned.AddRange(children);
                            if (!Current()) return;
                            Debug.Log("WORKSPACE_SURFACES compatibility children="+children.Count+" success="+legacy);
                        }
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
                // The reconstruction mesh is not guaranteed to be in AnchorContainer.
                // Query its component explicitly rather than manufacturing a mesh from bounds.
                try
                {
                var meshes = new List<OVRAnchor>();
                var meshResult = await OVRAnchor.FetchAnchorsAsync(meshes,
                    new OVRAnchor.FetchOptions { SingleComponentType = typeof(OVRTriangleMesh) });
                owned.AddRange(meshes);
                if (!Current()) return;
                if ((!meshResult.Success || meshes.Count == 0) && OpenXRRuntime.IsExtensionEnabled("XR_FB_spatial_entity_query"))
                {
                    meshes = new List<OVRAnchor>();
#pragma warning disable CS0618
                    bool meshLegacy = await OVRAnchor.FetchAnchorsAsync<OVRTriangleMesh>(meshes, timeout: 5);
#pragma warning restore CS0618
                    owned.AddRange(meshes);
                    if (!Current()) return;
                    Debug.Log("WORKSPACE_SCAN mesh compatibility count=" + meshes.Count + " success=" + meshLegacy);
                }
                foreach (var mesh in meshes)
                {
                    if (next.Exists(a => a.Anchor.Uuid == mesh.Uuid) || !mesh.TryGetComponent<OVRLocatable>(out var local)) continue;
                    await local.SetEnabledAsync(true);
                    if (!Current()) return;
                    if (local.IsEnabled) next.Add(new RoomAnchor { Anchor = mesh, Locatable = local });
                }
                }
                catch(Exception error) {Debug.LogWarning("WORKSPACE_SCAN optional mesh query unavailable " + error.GetType().Name);}
                if (!Current()) return;
                anchors.AddRange(next);
                ReadScanGeometry();
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
        public Pose ConstrainLevel(Transform target, Pose desired, bool free=false)
        {
            var level=levels.Find(l=>l.Target==target); if(level==null) return desired;
            var result=LevelPose(level.Kind,desired);
            if(AutomaticEnabled && !free && TryAttachLevel(level.Kind,result,detected,out var source,out var attached,level.Replaces))
            {
                bool changed=level.Replaces!=source.Id;
                level.Replaces=source.Id;
                if(changed) DrawLevel(level);
                return attached;
            }
            return result;
        }
        public static Vector3 ClosestPoint(Surface surface,Vector3 position)
        {
            var local=Quaternion.Inverse(surface.Pose.rotation)*(position-surface.Pose.position);
            var point=ClosestOnBoundary(surface,new Vector2(local.x,local.y));
            local=new Vector3(point.x,point.y,0);
            return surface.Pose.position+surface.Pose.rotation*local;
        }
        public static bool TryAttachLevel(string kind,Pose desired,IReadOnlyList<Surface> values,out Surface source,out Pose attached,Guid? preferred=null)
        {
            source=default;attached=desired;float distance=.3f;bool found=false;
            Surface previous=default;float previousDistance=float.PositiveInfinity;
            foreach(var surface in values)
            {
                if(surface.Name!=Title(kind)) continue;
                var point=ClosestPoint(surface,desired.position);
                float separation=Vector3.Distance(point,desired.position);
                if(preferred==surface.Id&&separation<.3f) {previous=surface;previousDistance=separation;}
                if(separation>=distance) continue;
                distance=separation;source=surface;found=true;
            }
            // Real scans contain overlapping tabletop annotations. Preserve the
            // chosen anchor until another is meaningfully nearer, including corners.
            if(found && previousDistance<=distance+.025f) source=previous;
            if(found) attached=LevelPose(kind,new Pose(ClosestPoint(source,desired.position)+source.Normal*.003f,source.Pose.rotation));
            return found;
        }
        public Transform CreateLevel(string kind, Pose desired, Vector2? size = null, Guid? replaces = null)
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
                // Double-stroke unlit lines stay readable against both light and dark desks.
                var backing = MakeLine(target, contrastMaterial,.014f); backing.name="Grid contrast backing"; DrawGrid(backing,level.Size);
                var line = MakeLine(target, levelMaterial,.006f); line.transform.localPosition=Vector3.forward*.0005f; DrawGrid(line, level.Size);
                var rim = MakeLine(target,contrastMaterial,.024f); rim.name="Level outer border contrast"; DrawBorder(rim,level.Size,.0006f);
                rim = MakeLine(target,levelMaterial,.012f); rim.name="Level outer border"; DrawBorder(rim,level.Size,.0012f);
                var handle=GameObject.CreatePrimitive(PrimitiveType.Sphere); handle.name="Visible level grip handle";
                DestroyObject(handle.GetComponent<Collider>()); handle.transform.SetParent(target,false);
                handle.transform.localScale=Vector3.one*.065f; handle.GetComponent<Renderer>().sharedMaterial=levelMaterial;
                level.Handle=handle.transform;
                var label = new GameObject("Level label backing",typeof(RectTransform),typeof(Canvas),typeof(Image));
                label.transform.SetParent(target,false); label.transform.localScale=Vector3.one*.001f;
                label.GetComponent<Canvas>().renderMode=RenderMode.WorldSpace;
                label.GetComponent<RectTransform>().sizeDelta=new Vector2(620,125);
                label.GetComponent<Image>().color=new Color(.015f,.02f,.025f,.96f); label.GetComponent<Image>().raycastTarget=false;
                level.LabelRoot=label.transform;
                var text=new GameObject("Level instructions",typeof(RectTransform),typeof(Text)); text.transform.SetParent(label.transform,false);
                var rect=text.GetComponent<RectTransform>(); rect.sizeDelta=new Vector2(600,115);
                level.Label=text.GetComponent<Text>(); level.Label.font=Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                level.Label.fontSize=32; level.Label.fontStyle=FontStyle.Bold; level.Label.alignment=TextAnchor.MiddleCenter; level.Label.color=Color.white;
                level.Label.raycastTarget = false;
            }
            level.Replaces=replaces;
            level.Size=size??(kind=="desk"?Vector2.one*.8f:new Vector2(2.4f,2.4f));
            DrawLevel(level);
            var pose = LevelPose(kind, desired); level.Target.SetPositionAndRotation(pose.position, pose.rotation);
            level.Target.localScale = Vector3.one;
            UpdateLabel(level);
            RebuildSurfaces();
            return level.Target;
        }
        static bool RoundLevel(Level level) => level.Kind=="desk" && !level.Replaces.HasValue;
        static void DrawLevel(Level level)
        {
            level.Label.text=level.Kind.ToUpperInvariant()+(level.Replaces.HasValue?" · ADJUST DETECTED":level.Kind=="desk"?" HEIGHT · MANUAL":" LEVEL · MANUAL")+"\nGrip move · stick click: free adjust";
            foreach(var stroke in level.Target.GetComponentsInChildren<LineRenderer>())
            {
                bool border=stroke.name.StartsWith("Level outer border");
                float depth=stroke.name=="Level outer border"?.0012f:stroke.name=="Level outer border contrast"?.0006f:.0005f;
                if(RoundLevel(level)) DrawCircle(stroke,Mathf.Min(level.Size.x,level.Size.y)*(border?.5f:.32f),depth);
                else if(border) DrawBorder(stroke,level.Size,depth);
                else DrawGrid(stroke,level.Size);
            }
        }
        public void BeginLevel(string kind)
        {
            pendingLevel=null; // Consume queued setup even if detection won the race or a level already exists.
            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
            var camera = Camera.main; if (camera == null) return;
            // Selecting again must not throw an already adjusted surface back at the wearer.
            if (levels.Exists(l=>l.Kind==kind)) return;
            if (AutomaticEnabled && TryChooseDetected(kind,camera.transform.position,out var surface))
            { CreateLevel(kind,surface.Pose,surface.Size,surface.Id); return; }
            var host=FindFirstObjectByType<HostScene>();
            // A menu click before the startup gate settles cannot seed an alternate
            // frame. Queue it until the same tracked workspace pose is available.
            if(host!=null && !host.DisplayPlacementReady)
            { pendingLevel=kind; message="Look ahead · waiting for workspace position"; return; }
            var facing=host!=null ? host.PlacementHeadPose.rotation : camera.transform.rotation;
            CreateLevel(kind,InitialLevelPose(kind,camera.transform.position,facing));
        }
        public static Pose InitialLevelPose(string kind, Vector3 eye, Quaternion workspaceFacing)
        {
            var forward=Vector3.ProjectOnPlane(workspaceFacing*Vector3.forward,Vector3.up).normalized;
            if(forward.sqrMagnitude<.5f) forward=Vector3.forward;
            var position=eye+forward*.8f;
            if(kind!="wall") position.y-=kind=="desk"?.6f:1.2f;
            return new Pose(position,kind=="wall"?Quaternion.LookRotation(-forward,Vector3.up):Quaternion.LookRotation(Vector3.up,forward));
        }
        public bool TryChooseDetected(string kind, Vector3 eye, out Surface surface)
        {
            surface=default; float nearest=float.PositiveInfinity; bool found=false;
            foreach(var candidate in detected)
            {
                if(candidate.Name!=Title(kind)) continue;
                float distance=(ClosestPoint(candidate,eye)-eye).sqrMagnitude;
                if(distance>=nearest) continue;
                nearest=distance; surface=candidate; found=true;
            }
            return found;
        }
        public void ClearLevels()
        {
            pendingLevel=null;
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
                var labelPlane=new Plane(level.LabelRoot.forward,level.LabelRoot.position);
                if(labelPlane.Raycast(ray,out float labelHit) && labelHit<distance)
                {
                    var localLabel=level.LabelRoot.InverseTransformPoint(ray.GetPoint(labelHit));
                    if(Mathf.Abs(localLabel.x)<=310 && Mathf.Abs(localLabel.y)<=62.5f)
                    { distance=labelHit; target=level.Target; }
                }
                var plane = new Plane(level.Target.forward, center);
                if (!plane.Raycast(ray, out float hit) || hit >= distance) continue;
                var local = level.Target.InverseTransformPoint(ray.GetPoint(hit));
                if (RoundLevel(level)?new Vector2(local.x,local.y).magnitude<=Mathf.Min(level.Size.x,level.Size.y)*.5f
                    :Mathf.Abs(local.x) <= level.Size.x*.5f && Mathf.Abs(local.y) <= level.Size.y*.5f)
                { distance = hit; target = level.Target; }
            }
            return target;
        }
        void LateUpdate()
        {
            if(pendingLevel!=null)
            {
                var host=FindFirstObjectByType<HostScene>();
                if(host!=null && host.DisplayPlacementReady) BeginLevel(pendingLevel);
            }
            detected.Clear(); var candidates = new List<(Guid room, Surface surface)>(); Guid currentRoom = Guid.Empty;
            foreach (var item in anchors)
            {
                if (!item.Locatable.TryGetSceneAnchorPose(out var tracked) || !tracked.Position.HasValue
                    || !tracked.Rotation.HasValue || !tracked.IsPositionTracked || !tracked.IsRotationTracked) continue;
                try
                {
                    string kind = item.Kind;
                    if (kind == null && item.Anchor.TryGetComponent<OVRSemanticLabels>(out var semantic))
                        // SDK GetClassifications doesn't apply the DESK->TABLE alias upgrade
                        // performed by Labels. Real room capture exposed DESK-only anchors.
#pragma warning disable CS0618
                        kind=ClassifyLabels(semantic.Labels);
#pragma warning restore CS0618
                    if (kind == null) continue;
                    var world = WorkspaceInteraction.ToWorldPose(Origin, new Pose(tracked.Position.Value,tracked.Rotation.Value));
                    Surface surface;
                    // Furniture may expose both a vertical plane and a volume. Its top face is the desk.
                    if (kind == "Desk" && item.Anchor.TryGetComponent<OVRBounded2D>(out var topPlane)
                        && Mathf.Abs(Vector3.Dot(world.rotation*Vector3.forward,Vector3.up))>.9f)
                        surface=PlaneFromMeta(kind,world,topPlane.BoundingBox,world.position+Vector3.up);
                    else if (kind == "Desk" && item.Anchor.TryGetComponent<OVRBounded3D>(out var volume))
                        surface = DeskTop(world,volume.BoundingBox);
                    else if (item.Anchor.TryGetComponent<OVRBounded2D>(out var plane))
                    {
                        surface=PlaneFromMeta(kind,world,plane.BoundingBox,Camera.main!=null?Camera.main.transform.position:world.position);
                    }
                    else continue;
                    surface.Id=item.Anchor.Uuid;
                    SetBoundary(ref surface,item,world);
                    if (surface.Size.x <= .01f || surface.Size.y <= .01f) continue;
                    candidates.Add((item.Room,surface));
                    if (kind == "Floor" && Camera.main != null)
                    {
                        var local = Quaternion.Inverse(surface.Pose.rotation)*(Camera.main.transform.position-surface.Pose.position);
                        if (ContainsPoint(surface,new Vector2(local.x,local.y))) currentRoom=item.Room;
                    }
                }
                catch (Exception error) { if(invalidLogged.Add(item.Anchor.Uuid)) Debug.LogWarning("WORKSPACE_SURFACES invalid surface " + error.GetType().Name); }
            }
            foreach (var item in candidates)
            {
                if(roomCount!=1 && item.room!=currentRoom) continue;
                // A legacy DESK alias can also describe a nearly coplanar floor patch.
                // Keep it as floor support, not the preferred tabletop under the wearer.
                var floor=candidates.Find(c=>c.room==item.room && c.surface.Name=="Floor");
                if(item.surface.Name=="Desk" && floor.surface.Name!=null && !AboveFloor(item.surface,floor.surface)) continue;
                detected.Add(item.surface);
            }
            localizedRoom=currentRoom;
            var counts=Counts(detected);
            if(counts!=lastCounts) { lastCounts=counts; Debug.Log("WORKSPACE_SURFACES localized " + counts); }
            if (!loading && anchors.Count > 0) message = detected.Count > 0 ? "Automatic surfaces · adjust if needed" : "Room not localized · look around or use a level";
            foreach (var level in levels)
                UpdateLabel(level);
            RebuildSurfaces(); RefreshVisuals();
            UpdateScanMeshes();
            WriteRoomEvidence();
            StartReferenceAuditOnce();
        }
        public static string ClassifyLabels(string value)
        {
            if(string.IsNullOrEmpty(value)) return null;
            var names=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach(var name in value.Split(',')) names.Add(name.Trim());
            if(names.Contains("DESK")||names.Contains("TABLE")) return "Desk";
            if(names.Contains("FLOOR")) return "Floor";
            if(names.Contains("WALL_FACE")||names.Contains("WALL")||names.Contains("INNER_WALL_FACE")) return "Wall";
            return null;
        }
        public static bool AboveFloor(Surface desk,Surface floor)
            => Vector3.Dot(desk.Pose.position-floor.Pose.position,floor.Normal)>.1f;
        public static Surface PlaneFromMeta(string kind,Pose world,Rect bounds,Vector3 eye)
        {
            var center=world.position+world.rotation*new Vector3(bounds.center.x,bounds.center.y,0);
            var normal=world.rotation*Vector3.forward;
            var toward=kind=="Wall"?eye-center:Vector3.up;
            if(Vector3.Dot(normal,toward)<0) normal=-normal;
            return new Surface {Name=kind,Pose=new Pose(center,Quaternion.LookRotation(normal,world.rotation*Vector3.up)),Size=bounds.size};
        }
        void WriteRoomEvidence()
        {
            var path=Environment.GetEnvironmentVariable("CALHACKS_ROOM_EVIDENCE");
            if(evidenceWritten || string.IsNullOrEmpty(path) || detected.Count==0 || Camera.main==null) return;
            var head=InputDevices.GetDeviceAtXRNode(XRNode.Head);
            if(!head.TryGetFeatureValue(CommonUsages.isTracked,out bool tracked)||!tracked
                ||!head.TryGetFeatureValue(CommonUsages.devicePosition,out Vector3 position)
                ||!head.TryGetFeatureValue(CommonUsages.deviceRotation,out Quaternion rotation)) return;
            evidenceWritten=true; // Optional diagnostics cannot throw every frame or interrupt placement.
            try
            {
            var meta=OVRPlugin.GetNodePose(OVRPlugin.Node.Head,OVRPlugin.Step.Render).ToOVRPose();
            var data=new RoomEvidence { trackingOrigin=OVRPlugin.GetTrackingOriginType().ToString(),
                metaHead=new Pose(meta.position,meta.orientation),unityHead=new Pose(position,rotation),
                cameraWorld=new Pose(Camera.main.transform.position,Camera.main.transform.rotation),
                originWorld=Origin!=null?new Pose(Origin.position,Origin.rotation):Pose.identity };
            foreach(var item in anchors)
            {
                if(!item.Locatable.TryGetSceneAnchorPose(out var pose)||!pose.Position.HasValue||!pose.Rotation.HasValue) continue;
                var entry=new AnchorEvidence {id=item.Anchor.Uuid.ToString(),kind=item.Kind,
                    trackingPose=new Pose(pose.Position.Value,pose.Rotation.Value)};
                if(scanBoundaries.TryGetValue(item.Anchor.Uuid,out var boundary)) entry.boundary=boundary;
                try { if(item.Anchor.TryGetComponent<OVRSemanticLabels>(out var semantic))
                    { entry.labels=semantic.Labels;var values=new List<OVRSemanticLabels.Classification>();semantic.GetClassifications(values);entry.classifications=string.Join(",",values); }
                } catch(Exception) {entry.labels="unavailable";}
                try { if(item.Anchor.TryGetComponent<OVRBounded2D>(out var plane)) {entry.planeBounds=plane.BoundingBox;entry.plane=true;} } catch(InvalidOperationException) {entry.plane=false;}
                try { if(item.Anchor.TryGetComponent<OVRBounded3D>(out var volume)) {entry.volumeBounds=volume.BoundingBox;entry.volume=true;} } catch(InvalidOperationException) {entry.volume=false;}
                data.anchors.Add(entry);
            }
            Directory.CreateDirectory(Path.GetDirectoryName(path)); File.WriteAllText(path,JsonUtility.ToJson(data,true));
            Debug.Log("WORKSPACE_ROOM_EVIDENCE captured anchor_count="+data.anchors.Count);
            }
            catch(Exception error) {Debug.LogWarning("WORKSPACE_ROOM_EVIDENCE unavailable "+error.GetType().Name);}
        }
        static void UpdateLabel(Level level)
        {
            // Only the text billboards. The plane and physical handle remain world-stationary.
            level.Handle.position=level.Target.position+Vector3.up*.06f;
            level.LabelRoot.position=level.Target.position+Vector3.up*.17f;
            float scale=Mathf.Max(.001f,Mathf.Abs(level.Target.lossyScale.x));
            level.Handle.localScale=Vector3.one*(.065f/scale);
            level.LabelRoot.localScale=Vector3.one*(.001f/scale);
            level.LabelRoot.rotation=Camera.main!=null ? Quaternion.LookRotation(level.LabelRoot.position-Camera.main.transform.position,Vector3.up) : Quaternion.identity;
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
                if (!IsOverridden(surface)) surfaces.Add(surface);
        }
        bool IsOverridden(Surface surface) => levels.Exists(l=>l.Replaces.HasValue && l.Replaces.Value==surface.Id && Title(l.Kind)==surface.Name);
        static string Title(string kind) => char.ToUpperInvariant(kind[0])+kind.Substring(1);
        static string Counts(List<Surface> values)
            => "Desk " + values.FindAll(s=>s.Name=="Desk").Count + " · floor " + values.FindAll(s=>s.Name=="Floor").Count + " · wall " + values.FindAll(s=>s.Name=="Wall").Count;
        void EnsureMaterials()
        {
            if (levelMaterial != null) return;
            // Resource asset pins the unlit shader in the Player, independent of scene lighting/Shader.Find stripping.
            var source=Resources.Load<Material>("WorkspaceSurfaceGuide");
            if(source==null) throw new InvalidOperationException("WorkspaceSurfaceGuide material missing");
            levelMaterial=new Material(source); levelMaterial.color=new Color(1,.85f,.1f,1);
            detectedMaterial=new Material(levelMaterial); detectedMaterial.color=new Color(.1f,.85f,.7f,1);
            contrastMaterial=new Material(levelMaterial); contrastMaterial.color=new Color(.015f,.02f,.025f,1);
        }
        static LineRenderer MakeLine(Transform parent, Material material,float width=.003f)
        {
            var go=new GameObject("Visible surface grid",typeof(LineRenderer)); go.transform.SetParent(parent,false);
            var line=go.GetComponent<LineRenderer>(); line.sharedMaterial=material; line.useWorldSpace=false;
            line.alignment=LineAlignment.TransformZ; // Flat on the plane; camera-facing ribbons can cover their own bright core.
            line.startWidth=line.endWidth=width;
            line.shadowCastingMode=UnityEngine.Rendering.ShadowCastingMode.Off; line.receiveShadows=false;
            return line;
        }
        static void DrawBorder(LineRenderer line,Vector2 size,float depth)
        {
            line.loop=true; line.positionCount=4;
            line.SetPositions(new[]{new Vector3(-size.x*.5f,-size.y*.5f,depth),new Vector3(-size.x*.5f,size.y*.5f,depth),
                new Vector3(size.x*.5f,size.y*.5f,depth),new Vector3(size.x*.5f,-size.y*.5f,depth)});
        }
        static void DrawCircle(LineRenderer line,float radius,float depth)
        {
            line.loop=true;line.positionCount=64;
            for(int i=0;i<64;i++) {float angle=i*Mathf.PI*2/64;line.SetPosition(i,new Vector3(Mathf.Cos(angle)*radius,Mathf.Sin(angle)*radius,depth));}
        }
        static void DrawGrid(LineRenderer line, Vector2 size)
        {
            line.loop=false;
            var points=new List<Vector3>();
            for(int i=0;i<=6;i++) {float u=i/6f-.5f,sign=i%2==0?1:-1;
                points.Add(new Vector3(u*size.x,-sign*size.y*.5f,.0005f)); points.Add(new Vector3(u*size.x,sign*size.y*.5f,.0005f));}
            for(int i=0;i<=6;i++) {float u=.5f-i/6f,sign=i%2==0?1:-1;
                points.Add(new Vector3(sign*size.x*.5f,u*size.y,.0005f)); points.Add(new Vector3(-sign*size.x*.5f,u*size.y,.0005f));}
            line.positionCount=points.Count; line.SetPositions(points.ToArray());
        }
        void RefreshVisuals()
        {
            if (detected.Count>0) EnsureMaterials();
            for(int i=0;i<detected.Count;i++)
            {
                if(i>=outlines.Count) outlines.Add(MakeLine(transform,detectedMaterial));
                var surface=detected[i]; var line=outlines[i];
                line.transform.SetPositionAndRotation(surface.Pose.position,surface.Pose.rotation);
                bool polygon=surface.Boundary!=null && surface.Boundary.Length>=3;
                line.loop=true; line.positionCount=polygon?surface.Boundary.Length:0;
                if(polygon) for(int p=0;p<surface.Boundary.Length;p++)
                    line.SetPosition(p,new Vector3(surface.Boundary[p].x,surface.Boundary[p].y,.001f));
                // A semantic rectangle is useful for contact, but it is NOT a scan outline.
                line.gameObject.SetActive(polygon && AutomaticEnabled && ShowDetected && !IsOverridden(surface));
            }
            for(int i=detected.Count;i<outlines.Count;i++) outlines[i].gameObject.SetActive(false);
        }
    }
}

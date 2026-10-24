using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR;
using UnityEngine.XR.OpenXR;

namespace SpatialModeling
{
    // Room data and manually marked planes share the controller's tracking origin.
    // No reconstructed room geometry is ever sent to Blender or saved to disk.
    public sealed class WorkspaceSurfaces : MonoBehaviour
    {
        public struct Surface
        {
            public string Name;
            public Pose Pose;
            public Vector2 Size;
            public Vector3 Normal => Pose.rotation * Vector3.forward;
        }
        struct RoomAnchor { public OVRAnchor Anchor; public OVRLocatable Locatable; }
        readonly List<RoomAnchor> anchors = new List<RoomAnchor>();
        readonly List<Surface> manual = new List<Surface>();
        readonly List<Surface> surfaces = new List<Surface>();
        readonly List<OVRSemanticLabels.Classification> labels = new List<OVRSemanticLabels.Classification>();
        readonly List<XRInputSubsystem> subsystems = new List<XRInputSubsystem>();
        public IReadOnlyList<Surface> Surfaces => surfaces;
        public string State { get; private set; } = "Checking room surfaces";
        public string Marking { get; private set; }
        bool loading, disposed;
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
            disposed = true;
            foreach (var item in anchors) item.Anchor.Dispose();
            anchors.Clear();
        }
        void TrackingReset(XRInputSubsystem _)
        {
            manual.Clear(); // A room-origin reset invalidates manually touched coordinates.
            surfaces.Clear();
            Marking = null;
            State = "Room origin changed · reload surfaces or mark again";
        }

        public async void Reload()
        {
            if (loading || disposed) return;
            if (!OVRPlugin.initialized || !OpenXRRuntime.IsExtensionEnabled("XR_FB_scene"))
            {
                State = "Room data unavailable · mark a desk, floor or wall";
                return;
            }
            loading = true;
            var fetched = new List<OVRAnchor>();
            try
            {
                State = "Loading room surfaces";
                var result = await OVRAnchor.FetchAnchorsAsync(fetched,
                    new OVRAnchor.FetchOptions { SingleComponentType = typeof(OVRSemanticLabels) });
                if (!result.Success) { State = "Room scan unavailable · mark surfaces manually"; return; }
                foreach (var anchor in fetched)
                {
                    if (disposed) break;
                    if (!anchor.TryGetComponent<OVRLocatable>(out var locatable)) continue;
                    await locatable.SetEnabledAsync(true);
                    if (disposed) break;
                    if (!anchors.Exists(a => a.Anchor.Uuid == anchor.Uuid))
                        anchors.Add(new RoomAnchor { Anchor = anchor, Locatable = locatable });
                }
                State = anchors.Count > 0 ? "Room surfaces loaded" : "No room scan · mark surfaces manually";
                Debug.Log("WORKSPACE_SURFACES anchors=" + anchors.Count + " " + State);
            }
            catch (Exception error)
            {
                State = "Room surfaces unavailable · manual marking available";
                Debug.LogWarning("WORKSPACE_SURFACES " + error.GetType().Name + ": " + error.Message);
            }
            finally
            {
                foreach (var anchor in fetched)
                    if (!anchors.Exists(a => a.Anchor.Handle == anchor.Handle)) anchor.Dispose();
                loading = false;
            }
        }

        public void BeginMark(string kind) { Marking = kind; }
        public void CancelMark() { Marking = null; }
        public void CaptureMark(Pose hand, Vector3 head)
        {
            if (Marking == null) return;
            Vector3 normal = Marking == "wall" ? Vector3.ProjectOnPlane(head - hand.position, Vector3.up).normalized : Vector3.up;
            if (normal.sqrMagnitude < .5f) normal = Vector3.back;
            var up = Marking == "wall" ? Vector3.up : Vector3.forward;
            var world = new Pose(hand.position, Quaternion.LookRotation(normal, up));
            var origin = Origin;
            var local = origin == null ? world : new Pose(origin.InverseTransformPoint(world.position), Quaternion.Inverse(origin.rotation) * world.rotation);
            manual.RemoveAll(s => s.Name == "Marked " + Marking);
            manual.Add(new Surface { Name = "Marked " + Marking, Pose = local,
                Size = Marking == "desk" ? new Vector2(1.5f,1f) : new Vector2(4,3) });
            State = "Marked " + Marking;
            Marking = null;
        }

        void LateUpdate()
        {
            surfaces.Clear();
            foreach (var item in manual)
            {
                var world = item;
                world.Pose = WorkspaceInteraction.ToWorldPose(Origin, item.Pose);
                surfaces.Add(world);
            }
            if (Camera.main == null) return;
            foreach (var item in anchors)
            {
                if (!item.Locatable.TryGetSceneAnchorPose(out var tracked) || !tracked.Position.HasValue
                    || !tracked.Rotation.HasValue || !tracked.IsPositionTracked || !tracked.IsRotationTracked) continue;
                try
                {
                    if (!item.Anchor.TryGetComponent<OVRSemanticLabels>(out var semantic)) continue;
                    semantic.GetClassifications(labels);
                    bool floor = labels.Contains(OVRSemanticLabels.Classification.Floor);
                    bool wall = labels.Contains(OVRSemanticLabels.Classification.WallFace);
                    bool desk = labels.Contains(OVRSemanticLabels.Classification.Table);
                    if (!floor && !wall && !desk) continue;
                    var world = WorkspaceInteraction.ToWorldPose(Origin, new Pose(tracked.Position.Value,tracked.Rotation.Value));
                    if (item.Anchor.TryGetComponent<OVRBounded2D>(out var plane))
                    {
                        var bounds = plane.BoundingBox;
                        var center = world.position + world.rotation * new Vector3(bounds.center.x,bounds.center.y,0);
                        var normal = world.rotation * Vector3.forward;
                        var toward = floor || desk ? Vector3.up : Camera.main.transform.position-center;
                        if (Vector3.Dot(normal,toward)<0) normal=-normal;
                        surfaces.Add(new Surface { Name = floor ? "Floor" : wall ? "Wall" : "Desk",
                            Pose = new Pose(center,Quaternion.LookRotation(normal,world.rotation*Vector3.up)), Size=bounds.size });
                    }
                    else if (desk && item.Anchor.TryGetComponent<OVRBounded3D>(out var volume))
                    {
                        var bounds = volume.BoundingBox;
                        // Find the top face in world gravity, regardless of the anchor's local axis.
                        var axes=new[]{world.rotation*Vector3.right,world.rotation*Vector3.up,world.rotation*Vector3.forward};
                        int top=0;
                        for(int i=1;i<3;i++) if(Mathf.Abs(axes[i].y)>Mathf.Abs(axes[top].y)) top=i;
                        var normal=axes[top]*Mathf.Sign(axes[top].y);
                        var center=world.position+world.rotation*bounds.center+normal*bounds.extents[top];
                        var tangent=axes[(top+1)%3];
                        surfaces.Add(new Surface {Name="Desk",Pose=new Pose(center,Quaternion.LookRotation(normal,tangent)),
                            Size=new Vector2(bounds.size[(top+2)%3],bounds.size[(top+1)%3])});
                    }
                }
                catch (Exception) { /* Invalid/unavailable anchor data is never a placement surface. */ }
            }
        }
    }
}

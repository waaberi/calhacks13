using System;
using System.Collections.Generic;
using Unity.Collections;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpatialModeling
{
    public sealed partial class WorkspaceSurfaces
    {
        readonly Dictionary<Guid,Vector2[]> scanBoundaries = new Dictionary<Guid,Vector2[]>();
        sealed class ScanMesh { public RoomAnchor Anchor; public GameObject Root; public Mesh Mesh; }
        readonly List<ScanMesh> scanMeshes = new List<ScanMesh>();
        sealed class RoomGeometryStage
        {
            public readonly Dictionary<Guid,Vector2[]> Boundaries=new Dictionary<Guid,Vector2[]>();
            public readonly List<ScanMesh> Meshes=new List<ScanMesh>();
            public Material Material;
        }
        Material scanMaterial;
        Guid localizedRoom;
        public string GeometrySummary => scanBoundaries.Count + " polygons / " + scanMeshes.Count + " scan meshes";

        void ClearScanGeometry()
        {
            scanBoundaries.Clear();
            foreach(var mesh in scanMeshes) { DestroyObject(mesh.Root); DestroyObject(mesh.Mesh); }
            scanMeshes.Clear();
            if(scanMaterial!=null) DestroyObject(scanMaterial);
            scanMaterial=null;
        }
        void ReadScanGeometry(IReadOnlyList<RoomAnchor> source,RoomGeometryStage stage)
        {
            foreach(var item in source??anchors)
            {
                try
                {
                    if(item.Anchor.TryGetComponent<OVRBounded2D>(out var plane)
                        && plane.TryGetBoundaryPointsCount(out int count) && count>=3 && count<=16384)
                    {
                        using(var points=new NativeArray<Vector2>(count,Allocator.Temp))
                            if(plane.TryGetBoundaryPoints(points)) stage.Boundaries[item.Anchor.Uuid]=points.ToArray();
                    }
                    if(!item.Anchor.TryGetComponent<OVRTriangleMesh>(out var triangles)
                        || !triangles.TryGetCounts(out int vertices,out int faces) || vertices<=0 || faces<=0
                        || vertices>2000000 || faces>2000000) continue;
                    using(var positions=new NativeArray<Vector3>(vertices,Allocator.Temp))
                    using(var indices=new NativeArray<int>(checked(faces*3),Allocator.Temp))
                    {
                        if(!triangles.TryGetMesh(positions,indices)) continue;
                        // TryGetMesh already performs Meta's scene handedness/winding conversion.
                        // Its vertices belong to the scene anchor, not to the head or workspace.
                        var mesh=MakeScanMesh(positions.ToArray(),indices.ToArray());
                        if(stage.Material==null)
                        {
                            var shader=Resources.Load<Shader>("WorkspaceRoomScan");
                            if(shader==null) throw new InvalidOperationException("Room scan shader missing");
                            stage.Material=new Material(shader);
                        }
                        var root=new GameObject("Meta captured scene mesh",typeof(MeshFilter),typeof(MeshRenderer));
                        root.GetComponent<MeshFilter>().sharedMesh=mesh;
                        var renderer=root.GetComponent<MeshRenderer>(); renderer.sharedMaterial=stage.Material;
                        renderer.shadowCastingMode=ShadowCastingMode.Off;renderer.receiveShadows=false;
                        root.SetActive(false);
                        stage.Meshes.Add(new ScanMesh {Anchor=item,Root=root,Mesh=mesh});
                    }
                }
                catch(Exception error) { Debug.LogWarning("WORKSPACE_SCAN geometry unavailable " + error.GetType().Name); }
            }
            Debug.Log("WORKSPACE_SCAN source=MetaScene " + stage.Boundaries.Count+" polygons / "+stage.Meshes.Count+" scan meshes staged=True rectangular_scan_fallback=False");
        }
        void UpdateScanMeshes()
        {
            foreach(var mesh in scanMeshes)
            {
                bool tracked=mesh.Anchor.Locatable.TryGetSceneAnchorPose(out var pose)
                    && pose.Position.HasValue && pose.Rotation.HasValue && pose.IsPositionTracked && pose.IsRotationTracked;
                Guid soleKnown=Guid.Empty;
                if(knownRooms.Count==1 && scanMeshes.Count==1) foreach(var room in knownRooms) soleKnown=room;
                bool currentRoom=WorkspaceRoomLocalization.BelongsToRoom(mesh.Anchor.Room,localizedRoom,soleKnown);
                mesh.Root.SetActive(AutomaticEnabled && ShowDetected && tracked && currentRoom);
                if(!tracked) continue;
                var world=SceneToWorld(sceneTrackingWorld,new Pose(pose.Position.Value,pose.Rotation.Value));
                mesh.Root.transform.SetPositionAndRotation(world.position,world.rotation);
            }
        }
        public static Mesh MakeScanMesh(Vector3[] vertices,int[] indices)
        {
            if(indices.Length%3!=0) throw new ArgumentException("Invalid scene mesh triangles");
            var points=new Vector3[indices.Length];var barycentric=new Vector2[indices.Length];var faces=new int[indices.Length];
            for(int i=0;i<indices.Length;i++)
            {
                if(indices[i]<0 || indices[i]>=vertices.Length) throw new ArgumentException("Invalid scene mesh index");
                points[i]=vertices[indices[i]];faces[i]=i;
                barycentric[i]=i%3==0?new Vector2(1,0):i%3==1?new Vector2(0,1):Vector2.zero;
            }
            var mesh=new Mesh {name="Actual Meta reconstruction",indexFormat=IndexFormat.UInt32};
            mesh.vertices=points;mesh.uv2=barycentric;mesh.triangles=faces;mesh.RecalculateBounds();return mesh;
        }
        void SetBoundary(ref Surface surface,RoomAnchor item,Pose anchorWorld)
        {
            surface.GeometrySource="semantic bounds (approximate)";
            if(!scanBoundaries.TryGetValue(item.Anchor.Uuid,out var points)) return;
            // Boundaries describe the plane. Never apply a side-plane boundary to a volume top.
            if(Mathf.Abs(Vector3.Dot(anchorWorld.rotation*Vector3.forward,surface.Normal))<.95f) return;
            surface.Boundary=new Vector2[points.Length];
            for(int i=0;i<points.Length;i++)
            {
                var world=anchorWorld.position+anchorWorld.rotation*new Vector3(points[i].x,points[i].y,0);
                var local=Quaternion.Inverse(surface.Pose.rotation)*(world-surface.Pose.position);
                surface.Boundary[i]=new Vector2(local.x,local.y);
            }
            surface.GeometrySource="Meta Boundary2D";
        }
        public static bool ContainsPoint(Surface surface,Vector2 point)
        {
            var points=surface.Boundary;
            if(points==null || points.Length<3)
                return Mathf.Abs(point.x)<=surface.Size.x*.5f && Mathf.Abs(point.y)<=surface.Size.y*.5f;
            bool inside=false;
            for(int i=0,j=points.Length-1;i<points.Length;j=i++)
            {
                var a=points[i];var b=points[j];
                var segment=b-a;
                float t=segment.sqrMagnitude>0?Mathf.Clamp01(Vector2.Dot(point-a,segment)/segment.sqrMagnitude):0;
                if((a+segment*t-point).sqrMagnitude<1e-10f) return true;
                if((a.y>point.y)!=(b.y>point.y) && point.x<(b.x-a.x)*(point.y-a.y)/(b.y-a.y)+a.x) inside=!inside;
            }
            return inside;
        }
        public static Vector2 ClosestOnBoundary(Surface surface,Vector2 point)
        {
            var points=surface.Boundary;
            if(points==null || points.Length<3)
                return new Vector2(Mathf.Clamp(point.x,-surface.Size.x*.5f,surface.Size.x*.5f),Mathf.Clamp(point.y,-surface.Size.y*.5f,surface.Size.y*.5f));
            if(ContainsPoint(surface,point)) return point;
            var nearest=points[0];float distance=float.PositiveInfinity;
            for(int i=0;i<points.Length;i++)
            {
                var a=points[i];var delta=points[(i+1)%points.Length]-a;
                float t=delta.sqrMagnitude>0?Mathf.Clamp01(Vector2.Dot(point-a,delta)/delta.sqrMagnitude):0;
                var candidate=a+t*delta;float d=(candidate-point).sqrMagnitude;
                if(d<distance) {distance=d;nearest=candidate;}
            }
            return nearest;
        }
    }
}

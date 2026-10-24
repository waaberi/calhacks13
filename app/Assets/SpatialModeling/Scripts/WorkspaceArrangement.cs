using System.Collections.Generic;
using UnityEngine;

namespace SpatialModeling
{
    // Viewer-only manipulation. No HostLink commands, native dimensions or native Undo.
    public sealed class WorkspaceArrangement : MonoBehaviour
    {
        struct Entry
        {
            public Transform Target;
            public Pose Pose;
            public Vector3 Scale, PositionOffset;
            public Quaternion RotationOffset;
            public WorkspaceObjectView Part;
            public Dictionary<WorkspaceObjectView,(Vector3 position,Quaternion rotation)> Parts;
        }
        readonly List<Entry> history = new List<Entry>();
        public bool AssistEnabled { get; private set; } = true;
        public bool EditModelAvailable => false;
        public WorkspaceSurfaces Surfaces { get; private set; }
        public string Instruction => "Grip: move · stick ←/→: rotate 15° · ↑/↓: distance · second grip: rotate/size";
        public string SurfaceState => Surfaces != null ? Surfaces.State : "Checking surfaces";
        public Vector3 RotationAxis { get; private set; } = Vector3.up;
        HostScene scene;
        string document, epoch;
        LineRenderer surfaceGuide, ghost;
        Material guideMaterial;
        bool visible;

        void Awake()
        {
            scene=FindFirstObjectByType<HostScene>();
            Surfaces=gameObject.AddComponent<WorkspaceSurfaces>();
        }
        void Update()
        {
            if(scene==null) return;
            if(document!=scene.DocumentId || epoch!=scene.OpenEpoch)
            { history.Clear(); HideGuide(); document=scene.DocumentId; epoch=scene.OpenEpoch; }
            // Direct arranging presents a stationary build after the common worn/focused
            // startup gate; users place it by grabbing/releasing, without a Place menu.
            if(scene.DisplayPlacementReady && !scene.Table.NeedsSeed && !scene.Table.IsPlaced)
                scene.Table.Place();
        }
        public void ToggleAssist() { AssistEnabled=!AssistEnabled; HideGuide(); }
        public void SelectArrange() { /* Edit model remains explicitly disabled until native editing is integrated. */ }
        public void Remember(Transform target)
        {
            if(target==null) return;
            var part=target.GetComponent<WorkspaceObjectView>();
            var parts=new Dictionary<WorkspaceObjectView,(Vector3,Quaternion)>();
            foreach(var view in target.GetComponentsInChildren<WorkspaceObjectView>(true))
                parts[view]=(view.PositionOffset,view.RotationOffset);
            history.Add(new Entry { Target=target,Pose=new Pose(target.position,target.rotation),Scale=target.localScale,Parts=parts,
                Part=part,PositionOffset=part!=null?part.PositionOffset:Vector3.zero,
                RotationOffset=part!=null?part.RotationOffset:Quaternion.identity });
            if(history.Count>20) history.RemoveAt(0);
        }
        public void UndoPlacement()
        {
            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
            while(history.Count>0)
            {
                var entry=history[history.Count-1]; history.RemoveAt(history.Count-1);
                if(entry.Target==null) continue;
                if(entry.Part!=null) entry.Part.RestoreArrangement(entry.PositionOffset,entry.RotationOffset);
                else
                {
                    entry.Target.SetPositionAndRotation(entry.Pose.position,entry.Pose.rotation); entry.Target.localScale=entry.Scale;
                    if(scene!=null && entry.Target==scene.Placement) scene.Table.RememberDisplayScale();
                    foreach(var item in entry.Parts) if(item.Key!=null) item.Key.RestoreArrangement(item.Value.position,item.Value.rotation);
                }
                break;
            }
            HideGuide();
        }
        public void Recover()
        {
            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
            if(scene!=null) { Remember(scene.Placement); scene.ResetObjectArrangement(); scene.Table.DockMenu(); }
            var screen=FindFirstObjectByType<BlenderScreen>();
            if(screen!=null && screen.Placement!=null) screen.Placement.localScale=Vector3.one*.001f;
            HideGuide();
        }
        public static Bounds LocalBounds(Transform target)
        {
            if(target is RectTransform rect) return new Bounds(rect.rect.center,new Vector3(rect.rect.width,rect.rect.height,8));
            var result=new Bounds(Vector3.zero,Vector3.zero);
            bool first=true;
            foreach(var filter in target.GetComponentsInChildren<MeshFilter>(true))
            {
                if(filter.sharedMesh==null) continue;
                var meshBounds=filter.sharedMesh.bounds;
                for(int i=0;i<8;i++)
                {
                    var corner=target.InverseTransformPoint(filter.transform.TransformPoint(Corner(meshBounds,i)));
                    if(first) { result=new Bounds(corner,Vector3.zero); first=false; } else result.Encapsulate(corner);
                }
            }
            return result;
        }
        public static Vector3 Corner(Bounds bounds,int index) => bounds.center+Vector3.Scale(bounds.extents,
            new Vector3((index&1)==0?-1:1,(index&2)==0?-1:1,(index&4)==0?-1:1));
        public static float MinimumDistance(Bounds bounds,Vector3 scale,Pose pose,WorkspaceSurfaces.Surface surface)
        {
            float minimum=float.PositiveInfinity;
            for(int i=0;i<8;i++) minimum=Mathf.Min(minimum,Vector3.Dot(
                pose.position+pose.rotation*Vector3.Scale(Corner(bounds,i),scale)-surface.Pose.position,surface.Normal));
            return minimum;
        }
        public static bool Assist(Bounds bounds,Vector3 scale,Pose previous,Pose desired,
            WorkspaceSurfaces.Surface surface,bool align,out Pose result,out Pose suggested,Vector3? previousScale=null)
        {
            result=desired; suggested=desired;
            var normal=surface.Normal;
            var local=Quaternion.Inverse(surface.Pose.rotation)*(desired.position+desired.rotation*Vector3.Scale(bounds.center,scale)-surface.Pose.position);
            float radius=Vector3.Scale(bounds.extents,scale).magnitude;
            if(Mathf.Abs(local.x)>surface.Size.x*.5f+radius || Mathf.Abs(local.y)>surface.Size.y*.5f+radius) return false;
            float before=MinimumDistance(bounds,previousScale??scale,previous,surface);
            float after=MinimumDistance(bounds,scale,desired,surface);
            // A deep object already behind a surface must be allowed to escape.
            if(before<-.02f || after>.14f) return false;
            var rotation=AlignedRotation(desired.rotation,normal);
            suggested=new Pose(desired.position,rotation);
            suggested.position+=normal*(.003f-MinimumDistance(bounds,scale,suggested,surface));
            if(align) result=suggested;
            else if(after<.003f) result.position+=normal*(.003f-after); // Contact stop only; never auto-rotate or attract.
            return true;
        }
        public static Quaternion AlignedRotation(Quaternion desired,Vector3 normal)
        {
            if(Mathf.Abs(normal.y)<=.7f) return Quaternion.LookRotation(-normal,Vector3.up);
            // Keep the user's heading when levelling pitch/roll; shortest-arc up-vector
            // rotation can otherwise change yaw unexpectedly for a heavily tilted object.
            var forward=Vector3.ProjectOnPlane(desired*Vector3.forward,normal);
            if(forward.sqrMagnitude<.0001f)
                forward=Vector3.Cross(Vector3.ProjectOnPlane(desired*Vector3.right,normal),normal);
            if(forward.sqrMagnitude<.0001f) forward=Vector3.ProjectOnPlane(Vector3.forward,normal);
            return Quaternion.LookRotation(forward.normalized,normal);
        }
        public Pose Apply(Transform target,Pose previous,Pose desired,bool align,bool bypass,Vector3? previousScale=null)
        {
            RotationAxis=Vector3.up; // A previous wall contact must not leak its rotation axis into the next grab/level.
            if(Surfaces!=null && Surfaces.IsLevel(target))
            { HideGuide(); return Surfaces.ConstrainLevel(target,desired,bypass || !AssistEnabled); }
            if(!AssistEnabled || bypass || Surfaces==null) { HideGuide(); return desired; }
            var bounds=LocalBounds(target);
            foreach(var surface in Surfaces.Surfaces)
                if(Assist(bounds,target.lossyScale,previous,desired,surface,align,out var assisted,out var suggested,previousScale))
                {
                    RotationAxis=surface.Normal;
                    DrawGuide(surface,bounds,target.lossyScale,suggested);
                    return assisted;
                }
            HideGuide();
            return desired;
        }
        void EnsureGuides()
        {
            if(guideMaterial!=null) return;
            var source=scene!=null ? scene.GetComponent<TablePlacement>().PreviewMaterial : null;
            guideMaterial=source!=null?new Material(source):new Material(Shader.Find("UI/Default"));
            guideMaterial.color=new Color(.15f,1f,.8f,1);
            surfaceGuide=MakeLine("Placement surface outline");
            ghost=MakeLine("Suggested aligned placement");
        }
        LineRenderer MakeLine(string name)
        {
            var go=new GameObject(name,typeof(LineRenderer)); go.transform.SetParent(transform,false);
            var line=go.GetComponent<LineRenderer>(); line.sharedMaterial=guideMaterial;
            line.startWidth=line.endWidth=.002f; line.useWorldSpace=true;
            return line;
        }
        void DrawGuide(WorkspaceSurfaces.Surface surface,Bounds bounds,Vector3 scale,Pose suggested)
        {
            EnsureGuides();
            surfaceGuide.gameObject.SetActive(true); ghost.gameObject.SetActive(true); visible=true;
            var points=new List<Vector3>();
            // Small grid gives depth/orientation without showing an entire persistent room mesh.
            float width=Mathf.Min(surface.Size.x,1.5f),height=Mathf.Min(surface.Size.y,1.5f);
            var local=Quaternion.Inverse(surface.Pose.rotation)*(suggested.position-surface.Pose.position);
            var center=surface.Pose.position+surface.Pose.rotation*new Vector3(
                Mathf.Clamp(local.x,-(surface.Size.x-width)*.5f,(surface.Size.x-width)*.5f),
                Mathf.Clamp(local.y,-(surface.Size.y-height)*.5f,(surface.Size.y-height)*.5f),0);
            for(int i=0;i<=4;i++)
            {
                float u=i/4f-.5f;
                float sign=i%2==0?1:-1;
                points.Add(center+surface.Pose.rotation*new Vector3(u*width,-sign*height*.5f,.004f));
                points.Add(center+surface.Pose.rotation*new Vector3(u*width,sign*height*.5f,.004f));
            }
            for(int i=0;i<=4;i++)
            {
                float v=.5f-i/4f,sign=i%2==0?1:-1;
                points.Add(center+surface.Pose.rotation*new Vector3(sign*width*.5f,v*height,.004f));
                points.Add(center+surface.Pose.rotation*new Vector3(-sign*width*.5f,v*height,.004f));
            }
            surfaceGuide.positionCount=points.Count; surfaceGuide.SetPositions(points.ToArray());
            var edges=new[]{0,1,3,2,0,4,5,1,5,7,3,7,6,2,6,4};
            ghost.positionCount=edges.Length;
            for(int i=0;i<edges.Length;i++) ghost.SetPosition(i,suggested.position+suggested.rotation*Vector3.Scale(Corner(bounds,edges[i]),scale));
        }
        public void HideGuide()
        {
            RotationAxis=Vector3.up;
            if(!visible) return;
            if(surfaceGuide!=null) surfaceGuide.gameObject.SetActive(false);
            if(ghost!=null) ghost.gameObject.SetActive(false);
            visible=false;
        }
        void OnDestroy() { if(guideMaterial!=null) Destroy(guideMaterial); }
    }
}

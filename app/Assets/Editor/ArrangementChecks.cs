using System;
using System.Linq;
using System.Reflection;
using SpatialModeling;
using UnityEngine;
using UnityEngine.UI;

public static class ArrangementChecks
{
    static void Check(bool value,string message) { if(!value) throw new Exception("Arrange: "+message); }
    static void Near(Vector3 a,Vector3 b,string message) => Check(Vector3.Distance(a,b)<.0001f,message);
    public static void Run()
    {
        var bounds=new Bounds(new Vector3(.2f,.1f,0),new Vector3(.4f,.2f,.3f));
        var desk=new WorkspaceSurfaces.Surface {Name="Desk",Pose=new Pose(new Vector3(0,.8f,0),Quaternion.LookRotation(Vector3.up,Vector3.forward)),Size=new Vector2(1.5f,1)};
        var before=new Pose(new Vector3(0,.85f,0),Quaternion.identity);
        var desired=new Pose(new Vector3(.1f,.65f,0),Quaternion.Euler(0,37,0));
        Check(WorkspaceArrangement.Assist(bounds,Vector3.one,before,desired,desk,false,out var stopped,out var suggested),"desk crossing gets assistance");
        Check(WorkspaceArrangement.MinimumDistance(bounds,Vector3.one,stopped,desk)>=.0029f,"desk stops the actual bottom, including non-centred mesh origin");
        Check(Quaternion.Angle(stopped.rotation,desired.rotation)<.001f,"contact stop never force-rotates the item");
        Check(Mathf.Abs(stopped.position.x-desired.position.x)<.0001f,"contact stop preserves user's motion parallel to desk");
        Check(WorkspaceArrangement.Assist(bounds,Vector3.one,before,new Pose(new Vector3(0,.86f,0),Quaternion.Euler(15,12,8)),desk,false,out var near,out _),"near surface offers an alignment guide");
        Near(near.position,new Vector3(0,.86f,0),"near contact never attracts object down onto the desk");
        var wall=new WorkspaceSurfaces.Surface {Name="Wall",Pose=new Pose(Vector3.forward,Quaternion.LookRotation(Vector3.back,Vector3.up)),Size=new Vector2(3,3)};
        before=new Pose(new Vector3(0,0,.4f),Quaternion.identity);
        desired=new Pose(new Vector3(.1f,0,2),Quaternion.Euler(0,38,0));
        Check(WorkspaceArrangement.Assist(bounds,Vector3.one,before,desired,wall,false,out stopped,out suggested),"one-frame crossing cannot tunnel straight through wall");
        Check(WorkspaceArrangement.MinimumDistance(bounds,Vector3.one,stopped,wall)>=.0029f,"wall stop uses frontmost geometry contact");
        Check(Quaternion.Angle(stopped.rotation,desired.rotation)<.001f,"wall assistance preserves free orientation until explicit alignment");
        Check(WorkspaceArrangement.Assist(bounds,Vector3.one,before,desired,wall,true,out var aligned,out _),"explicit trigger can accept wall alignment");
        Check(Vector3.Dot(aligned.rotation*Vector3.forward,-wall.Normal)>.999f,"wall alignment faces the panel into the room");
        Check(!WorkspaceArrangement.Assist(bounds,Vector3.one,before,new Pose(new Vector3(5,0,2),Quaternion.identity),wall,false,out _,out _),"finite wall patch never blocks objects outside its area");
        Check(!WorkspaceArrangement.Assist(bounds,Vector3.one,new Pose(new Vector3(0,0,2),Quaternion.identity),new Pose(new Vector3(0,0,1.7f),Quaternion.identity),wall,false,out _,out _),"already misplaced object can escape through the surface");
        var origin=new GameObject("Arrange rotated origin");
        try
        {
            origin.transform.SetPositionAndRotation(new Vector3(2,.2f,3),Quaternion.Euler(0,75,0));
            var local=new Pose(new Vector3(.4f,1,.2f),Quaternion.Euler(10,20,0));
            var world=WorkspaceInteraction.ToWorldPose(origin.transform,local);
            Near(world.position,origin.transform.TransformPoint(local.position),"surface/controller origin converts exactly once");
            var a=new Pose(Vector3.left*.3f,Quaternion.identity);
            var b=new Pose(Vector3.right*.3f,Quaternion.identity);
            var turn=Quaternion.Euler(30,40,15);
            var first=WorkspaceInteraction.TwoHandFrame(a,b);
            var second=WorkspaceInteraction.TwoHandFrame(new Pose(turn*a.position,turn),new Pose(turn*b.position,turn));
            Check(Quaternion.Angle(second*Quaternion.Inverse(first),turn)<.01f,"two hands provide full rotation, including roll");
        }
        finally { UnityEngine.Object.DestroyImmediate(origin); }
        var container=new GameObject("Arrangement checks");
        var cameraObject=new GameObject("Arrange UI check camera",typeof(Camera));
        container.SetActive(false);
        BlenderScreen screen=null;
        try
        {
            var arrangement=container.AddComponent<WorkspaceArrangement>();
            typeof(WorkspaceArrangement).GetMethod("Awake",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(arrangement,null);
            Check(!arrangement.EditModelAvailable,"native Edit model is disabled until real P3 integration");
            var viewObject=new GameObject("Current native part"); viewObject.transform.SetParent(container.transform);
            var view=viewObject.AddComponent<WorkspaceObjectView>();
            view.SetNativePose(new Vector3(.01f,.02f,0),Quaternion.identity,Vector3.one);
            arrangement.Remember(view.transform);
            view.transform.localPosition+=Vector3.one; view.RememberArrangement();
            view.SetNativePose(new Vector3(.06f,.02f,0),Quaternion.identity,Vector3.one);
            arrangement.UndoPlacement();
            Near(view.NativePosition,new Vector3(.06f,.02f,0),"placement Undo never undoes a newer native Blender generation");
            Near(view.PositionOffset,Vector3.zero,"placement Undo restores only viewer offsets");
            arrangement.Surfaces.BeginMark("desk");
            arrangement.Surfaces.CaptureMark(new Pose(new Vector3(.1f,.8f,.2f),Quaternion.identity),new Vector3(0,1.6f,0));
            Check(arrangement.Surfaces.Marking==null && arrangement.Surfaces.State=="Marked desk","manual fallback commits a touched desk without a room scan");
            screen=container.AddComponent<BlenderScreen>();
            typeof(BlenderScreen).GetField("arrangement",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(screen,arrangement);
            var camera=cameraObject.GetComponent<Camera>();
            typeof(BlenderScreen).GetMethod("BuildUi",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(screen,new object[]{camera});
            var buttons=screen.Placement.GetComponentsInChildren<Button>(true);
            Check(buttons.Single(b=>b.name=="Arrange space mode").interactable,"Arrange space is available at top-left");
            Check(!buttons.Single(b=>b.name=="Edit model mode").interactable,"Edit model is visibly disabled, not a no-op mode");
            screen.Toggle();
            var top=buttons.Single(b=>b.name=="Arrange space mode").transform;
            Check(screen.RaycastSurface(new Ray(top.position-top.forward*.3f,top.forward),out _),"mode strip remains reachable with Blender preview hidden");
            Debug.Log("ARRANGEMENT_CHECKS PASS contact stops/no forced snap/explicit align/bounds/tunnelling/manual surface/rotated origin/two-hand rotation/native-safe undo/disabled Edit/hidden-preview mode strip");
        }
        finally
        {
            if(screen!=null && screen.Placement!=null) UnityEngine.Object.DestroyImmediate(screen.Placement.gameObject);
            UnityEngine.Object.DestroyImmediate(container);
            UnityEngine.Object.DestroyImmediate(cameraObject);
        }
    }
}

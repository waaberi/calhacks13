using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using SpatialModeling;
using UnityEngine;

// Exercises the production creation/constraint/deletion APIs without a headset.
public static class IndependentPlaneChecks
{
    public static void Run()
    {
        var root=new GameObject("Independent manual plane checks");
        try
        {
            var provider=root.AddComponent<WorkspaceSurfaces>();
            Check(!provider.ShowDetected,"Room visualization starts hidden");
            Check(provider.AutomaticEnabled,"Hidden visualization does not disable room detection");
            var source=new WorkspaceSurfaces.Surface {Name="Wall",Id=Guid.NewGuid(),
                Pose=new Pose(new Vector3(0,1,1),Quaternion.identity),Size=new Vector2(3,2)};
            var other=source;other.Id=Guid.NewGuid();other.Pose.position+=Vector3.right*4;
            var detected=(List<WorkspaceSurfaces.Surface>)typeof(WorkspaceSurfaces)
                .GetField("detected",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(provider);
            detected.Add(source);detected.Add(other);
            var first=provider.CreatePlane("vertical",source.Pose,source.Size,source.Id);
            var second=provider.CreatePlane("vertical",new Pose(new Vector3(2,1,1),Quaternion.identity));
            var horizontal=provider.CreatePlane("horizontal",new Pose(new Vector3(0,.8f,1),Quaternion.Euler(30,40,20)));
            Check(first!=second && provider.PlaneTargets.Count==3,"Multiple planes of the same orientation remain distinct");
            Check(provider.Surfaces.Count==4,"A correction overrides only its source UUID, preserving other detected surfaces");
            Check(Vector3.Dot(horizontal.forward,Vector3.up)>.999f,"Horizontal plane stays gravity level");
            Check(horizontal.Find("Level outer border").GetComponent<LineRenderer>().positionCount==4,
                "Explicit horizontal plane has an honest rectangular manual extent");
            var desired=new Pose(new Vector3(.1f,1.12f,1.1f),Quaternion.Euler(0,25,0));
            Check(WorkspaceSurfaces.TryAttachLevel("wall",desired,detected,out _,out _),
                "Regression fixture is inside the former forced-attachment distance");
            for(int grab=0;grab<3;grab++)
            {
                // false reproduces the default state on each newly acquired grip.
                var independent=provider.ConstrainLevel(first,desired,false);
                Near(independent.position,desired.position,"Release/regrab cannot restore scan position");
                Check(Quaternion.Angle(independent.rotation,desired.rotation)<.001f,
                    "Release/regrab cannot restore scan orientation");
                first.SetPositionAndRotation(independent.position,independent.rotation);
            }
            Check(provider.AlignPlaneToDetected(first),"Explicit one-shot alignment can use detected geometry");
            Near(first.position,source.Pose.position+Vector3.right*.1f+Vector3.up*.12f+Vector3.forward*.003f,
                "Explicit alignment projects onto the actual detected plane");
            var afterAlignment=provider.ConstrainLevel(first,desired,false);
            Near(afterAlignment.position,desired.position,"One-shot alignment never turns into persistent attachment");
            var secondLabel=provider.PlaneLabel(second);
            Check(provider.DeletePlane(first),"Individual plane deletion succeeds");
            Check(provider.PlaneLabel(second)==secondLabel,"Deleting a plane does not rename another plane");
            Check(!provider.DeletePlane(first),"Deleting an already removed plane is harmless");
            Check(provider.PlaneTargets.Count==2 && provider.PlaneTargets.Contains(second),"Deleting one plane preserves the others");
            Check(provider.Surfaces.Any(s=>s.Id==source.Id) && provider.Surfaces.Any(s=>s.Id==other.Id),
                "Deleting correction restores its detected source without losing unrelated anchors");
            provider.ToggleDetected();
            Check(provider.ShowDetected && provider.AutomaticEnabled,"Visualization toggle keeps functional detection enabled");
            provider.ToggleDetected();
            Check(!provider.ShowDetected && provider.Surfaces.Count==4,"Hiding mesh preserves functional surfaces and planes");
            provider.ClearLevels();
            Check(provider.Surfaces.Count==2 && provider.Surfaces.Any(s=>s.Id==source.Id),
                "Clear planes immediately restores detected functional surfaces without waiting a frame");
            detected.Clear();
            var floor=new WorkspaceSurfaces.Surface {Name="Floor",Id=Guid.NewGuid(),
                Pose=new Pose(Vector3.zero,Quaternion.LookRotation(Vector3.up,Vector3.forward)),Size=Vector2.one*4};
            detected.Add(floor);
            var floorGuide=provider.CreatePlane("horizontal",new Pose(new Vector3(.2f,.12f,.3f),Quaternion.identity));
            Check(provider.AlignPlaneToDetected(floorGuide),"Horizontal plane explicitly aligns in a floor-only room");
            Near(floorGuide.position,new Vector3(.2f,.003f,.3f),"Floor-only alignment uses the actual floor plane");
            Check(provider.Surfaces.Count==1 && !provider.Surfaces.Any(s=>s.Id==floor.Id),
                "Horizontal correction overrides its floor source identity");
            Check(provider.DeletePlane(floorGuide) && provider.Surfaces.Any(s=>s.Id==floor.Id),
                "Deleting a floor correction restores the floor source immediately");
            CheckVerticalCreation(provider,detected);
            Debug.Log("INDEPENDENT_PLANE_CHECK PASS multiple planes, default hidden mesh, durable manual correction, one-shot alignment, individual deletion/source restoration");
        }
        finally {UnityEngine.Object.DestroyImmediate(root);}
    }
    static void CheckVerticalCreation(WorkspaceSurfaces provider,List<WorkspaceSurfaces.Surface> detected)
    {
        var activeMainCameras=Camera.allCameras.Where(c=>c.CompareTag("MainCamera")).ToArray();
        var trackingRoot=new GameObject("Rotated manual plane tracking origin");
        var hostObject=new GameObject("Disabled no-network vertical creation host");
        hostObject.SetActive(false);
        var host=hostObject.AddComponent<HostScene>();host.enabled=false;
        try
        {
            foreach(var existing in activeMainCameras) existing.enabled=false;
            trackingRoot.transform.SetPositionAndRotation(new Vector3(2,.15f,-3),Quaternion.Euler(0,47,0));
            var cameraObject=new GameObject("Vertical creation menu-facing camera",typeof(Camera));
            cameraObject.tag="MainCamera";cameraObject.transform.SetParent(trackingRoot.transform,false);
            cameraObject.transform.localPosition=new Vector3(.2f,1.65f,.3f);
            cameraObject.transform.localRotation=Quaternion.Euler(35,-80,15);
            var eye=cameraObject.transform.position;
            var settled=new Pose(eye,Quaternion.Euler(0,123,0));
            var forward=settled.rotation*Vector3.forward;
            typeof(HostScene).GetProperty("PlacementHeadPose").SetValue(host,settled);
            hostObject.SetActive(true); // Disabled component never opens its transport.
            detected.Clear();
            var behind=new WorkspaceSurfaces.Surface {Name="Wall",Id=Guid.NewGuid(),
                Pose=new Pose(eye-forward*.2f,Quaternion.LookRotation(forward,Vector3.up)),Size=new Vector2(3,2)};
            detected.Add(behind);
            var preserved=provider.CreatePlane("horizontal",new Pose(eye+Vector3.right*2,Quaternion.identity));
            var preservedPose=new Pose(preserved.position,preserved.rotation);
            var preservedLabel=provider.PlaneLabel(preserved);
            provider.BeginPlane("vertical");
            Check(provider.LevelCount==1,"Vertical menu action waits for accepted shared workspace readiness");
            var pending=typeof(WorkspaceSurfaces).GetField("pendingLevel",BindingFlags.Instance|BindingFlags.NonPublic);
            Check((string)pending.GetValue(provider)=="plane:vertical","Early vertical creation queues its orientation");
            typeof(HostScene).GetField("placed",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(host,true);
            var update=typeof(WorkspaceSurfaces).GetMethod("LateUpdate",BindingFlags.Instance|BindingFlags.NonPublic);
            update.Invoke(provider,null);
            Check(provider.LevelCount==2 && pending.GetValue(provider)==null,"Settled readiness consumes queued vertical creation exactly once");
            var created=provider.PlaneTargets.Single(t=>t!=preserved);
            Near(created.position,eye+forward*.8f,"Queued actual BeginPlane spawns ahead of settled facing in rotated tracking origin");
            Check(Vector3.Dot(created.forward,-forward)>.999f,"Created vertical plane faces the wearer with shared workspace heading");
            Check(created.parent==trackingRoot.transform,"Vertical plane retains the existing tracking origin parent exactly once");
            Check(Vector3.Distance(created.position,behind.Pose.position)>.9f,
                "A nearer detected wall behind cannot seed the vertical adjuster");
            update.Invoke(provider,null);
            Check(provider.LevelCount==2,"Consumed queue cannot create duplicate planes on later frames");
            detected.Add(behind);
            provider.BeginPlane("vertical");
            var immediate=provider.PlaneTargets.Last();
            Near(immediate.position,eye+forward*.8f,"Ready actual BeginPlane also ignores a nearer wall behind and menu click gaze");
            Check(provider.Surfaces.Any(s=>s.Id==behind.Id),"New vertical adjuster does not override an unrelated behind-wall anchor");
            Near(preserved.position,preservedPose.position,"Vertical creation preserves existing horizontal plane position");
            Check(Quaternion.Angle(preserved.rotation,preservedPose.rotation)<.001f && provider.PlaneLabel(preserved)==preservedLabel,
                "Vertical creation preserves existing plane orientation and identity");
            var moved=new Pose(created.position+Vector3.right*.1f,Quaternion.Euler(0,38,0));
            var constrained=provider.ConstrainLevel(created,moved,false);
            Near(constrained.position,moved.position,"Front-spawned vertical plane remains independently movable");
            Check(Quaternion.Angle(constrained.rotation,moved.rotation)<.001f,"Front-spawned vertical plane retains deliberate yaw");
            Debug.Log("VERTICAL_PLANE_FRONT_CHECK PASS actual queued/ready BeginPlane, closer wall behind, rotated tracking origin, menu-facing gaze, independent holds and other-plane preservation");
        }
        finally
        {
            provider.ClearLevels();
            UnityEngine.Object.DestroyImmediate(hostObject);
            UnityEngine.Object.DestroyImmediate(trackingRoot);
            foreach(var existing in activeMainCameras) if(existing!=null) existing.enabled=true;
        }
    }
    static void Check(bool value,string message) {if(!value) throw new Exception(message);}
    static void Near(Vector3 actual,Vector3 expected,string message)
        => Check(Vector3.Distance(actual,expected)<.0001f,message+" actual="+actual+" expected="+expected);
}

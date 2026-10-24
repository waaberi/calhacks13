using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.IO;
using UnityEditor;
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
        desk.Id=Guid.NewGuid();
        // Menu attention must not define the guide frame. Replay sideward/downward
        // menu gaze against a previously settled workspace at several room headings.
        foreach(float heading in new[]{0f,73f,180f,-120f})
        {
            var facing=Quaternion.Euler(0,heading,0);
            var eye=new Vector3(2,1.6f,-3);
            var pose=WorkspaceSurfaces.InitialLevelPose("desk",eye,facing);
            Near(Vector3.ProjectOnPlane(pose.position-eye,Vector3.up),facing*Vector3.forward*.8f,"fallback starts along settled workspace forward, independent of left-menu gaze");
            Check(Vector3.Dot(pose.rotation*Vector3.forward,Vector3.up)>.999f
                && Vector3.Dot(pose.rotation*Vector3.up,facing*Vector3.forward)>.999f,"desk is gravity level with a consistent heading at any room yaw");
            var wallPose=WorkspaceSurfaces.InitialLevelPose("wall",eye,facing);
            Check(Vector3.Dot(wallPose.rotation*Vector3.up,Vector3.up)>.999f
                && Vector3.Dot(wallPose.rotation*Vector3.forward,-(facing*Vector3.forward))>.999f,"new wall is upright and faces into the workspace");
        }
        Check(WorkspaceArrangement.Assist(bounds,Vector3.one,before,desired,desk,false,out var stopped,out var suggested),"desk crossing gets assistance");
        Check(WorkspaceArrangement.MinimumDistance(bounds,Vector3.one,stopped,desk)>=.0029f,"desk stops the actual bottom, including non-centred mesh origin");
        Check(Quaternion.Angle(stopped.rotation,desired.rotation)<.001f,"contact stop never force-rotates the item");
        Check(Mathf.Abs(stopped.position.x-desired.position.x)<.0001f,"contact stop preserves user's motion parallel to desk");
        Check(WorkspaceArrangement.Assist(bounds,Vector3.one,before,new Pose(new Vector3(0,.86f,0),Quaternion.Euler(15,12,8)),desk,false,out var near,out _),"near surface offers an alignment guide");
        Near(near.position,new Vector3(0,.86f,0),"near contact never attracts object down onto the desk");
        var cube=new Bounds(Vector3.zero,Vector3.one*.2f);
        var scalingPose=new Pose(new Vector3(0,.9f,0),Quaternion.identity);
        Check(WorkspaceArrangement.Assist(cube,Vector3.one*2,scalingPose,scalingPose,desk,false,out var enlarged,out _,Vector3.one),"two-hand enlargement respects previous geometry at contact");
        Check(WorkspaceArrangement.MinimumDistance(cube,Vector3.one*2,enlarged,desk)>=.0029f,"enlarging a model does not bury it in the desk");
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
            var table=container.AddComponent<TablePlacement>();
            var display=new GameObject("Direct magnification root"); display.transform.SetParent(container.transform);
            display.transform.localScale=Vector3.one*5;
            table.Initialize(display.transform,AssetDatabase.LoadAssetAtPath<Material>("Assets/SpatialModeling/Materials/HostObject.mat"));
            display.transform.localScale=Vector3.one*7;
            table.RememberDisplayScale();
            table.DockMenu();
            Near(display.transform.localScale,Vector3.one*7,"menu docking cannot undo direct two-hand build magnification");
            var provider=arrangement.Surfaces;
            var guideAsset=Resources.Load<Material>("WorkspaceSurfaceGuide");
            Check(guideAsset!=null && guideAsset.shader.name=="Universal Render Pipeline/Unlit","guide shader is a retained resource independent of room lighting");
            var ids=Enumerable.Range(0,123).Select(_=>Guid.NewGuid()).ToList();
            var batches=WorkspaceSurfaces.Batches(ids.Concat(ids).Concat(new[]{Guid.Empty}));
            Check(batches.Count==3 && batches.All(batch=>batch.Length<=50)
                && batches.SelectMany(batch=>batch).Distinct().Count()==123,"room children beyond SDK's first50 are fetched without duplicates/empty UUIDs");
            var deskFace=WorkspaceSurfaces.DeskTop(new Pose(new Vector3(2,.5f,3),Quaternion.Euler(90,30,0)),new Bounds(new Vector3(.2f,0,0),new Vector3(1,.6f,.4f)));
            Check(deskFace.Normal.y>.999f && Mathf.Abs(deskFace.Pose.position.y-.7f)<.0001f,"desk uses volume top, including non-centred bounds and rotated anchor");
            var level=provider.CreateLevel("desk",new Pose(new Vector3(.1f,.8f,.2f),Quaternion.Euler(31,42,18)));
            Check(level.gameObject.activeSelf && level.GetComponentInChildren<LineRenderer>().positionCount>20,"fallback is a visible grid immediately, without holding an object near it");
            Check(level.Find("Level outer border").GetComponent<LineRenderer>().startWidth>=.012f
                && level.Find("Grid contrast backing")!=null,"level has thick contrasted borders and double-stroke grid");
            Check(level.Find("Visible level grip handle").GetComponent<Renderer>()!=null
                && level.GetComponentInChildren<Image>().color.a>.9f,"handle is physical visible geometry and instructions have a dark backing");
            Check(Vector3.Dot(level.forward,Vector3.up)>.999f,"desk level stays horizontal despite wrist tilt");
            RenderLevelPreview(level,cameraObject.GetComponent<Camera>());
            var moved=arrangement.Apply(level,new Pose(level.position,level.rotation),new Pose(new Vector3(0,.5f,.4f),Quaternion.Euler(50,60,70)),false,false);
            Near(moved.position,new Vector3(0,.5f,.4f),"level itself is not blocked by existing surface assistance");
            Check(Vector3.Dot(moved.rotation*Vector3.forward,Vector3.up)>.999f,"moving a level preserves horizontal constraint");
            var ray=new Ray(level.position+Vector3.up,Vector3.down);
            Check(provider.RaycastLevel(ray,out float levelDistance)==level && levelDistance>.7f && levelDistance<=1.01f,
                "visible grid, raised label or central handle is the nearest grabbable level hit");
            level.SetPositionAndRotation(moved.position,moved.rotation);
            typeof(WorkspaceSurfaces).GetMethod("LateUpdate",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(provider,null);
            Near(provider.Surfaces.Single().Pose.position,moved.position,"placed plane reads the moved grid's world pose exactly once");
            var detectedSurfaces=(List<WorkspaceSurfaces.Surface>)typeof(WorkspaceSurfaces).GetField("detected",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(provider);
            detectedSurfaces.Add(desk); detectedSurfaces.Add(wall);
            var secondDesk=desk; secondDesk.Id=Guid.NewGuid(); secondDesk.Pose.position+=Vector3.right*5;
            detectedSurfaces.Add(secondDesk);
            Check(provider.TryChooseDetected("desk",new Vector3(0,1.5f,0),out var chosen) && chosen.Id==desk.Id,"adjust starts from the nearest REAL detected surface");
            provider.CreateLevel("desk",chosen.Pose,chosen.Size,chosen.Id);
            typeof(WorkspaceSurfaces).GetMethod("RebuildSurfaces",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(provider,null);
            Check(provider.Surfaces.Count==3 && provider.Surfaces.Count(s=>s.Name=="Desk")==2,"adjusted desk replaces only its source anchor, preserving other desk and wall");
            Near(level.position,desk.Pose.position,"adjustable overlay retains the actual detected desk position");
            Check(level.Find("Level outer border").GetComponent<LineRenderer>().GetPosition(0).x==-desk.Size.x*.5f,"adjust overlay uses actual detected extents");
            // Run the real menu callback with a camera looking to the left. The
            // existing calibrated guide must never reset to that click-time gaze.
            string oldTag=cameraObject.tag; cameraObject.tag="MainCamera";
            cameraObject.GetComponent<Camera>().enabled=true; // Preview rendering disabled it; Camera.main requires an enabled camera.
            cameraObject.transform.rotation=Quaternion.Euler(35,-70,12);
            var calibrated=new Pose(new Vector3(.2f,.75f,.9f),level.rotation);
            level.SetPositionAndRotation(calibrated.position,calibrated.rotation);
            provider.BeginLevel("desk");
            Near(level.position,calibrated.position,"reselecting Desk adjustment never resets the calibrated position");
            Check(Quaternion.Angle(level.rotation,calibrated.rotation)<.001f,"reselecting from a side-facing menu never twists the calibrated desk");
            cameraObject.tag=oldTag;
            provider.ToggleAutomatic();
            Check(!provider.AutomaticEnabled && provider.LevelCount==1,"turning off an inaccurate room scan preserves manual levels");
            typeof(WorkspaceSurfaces).GetMethod("LateUpdate",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(provider,null);
            Check(provider.Surfaces.Count==1,"manual surface remains usable with automatic detection off");
            var wallLevel=provider.CreateLevel("wall",new Pose(new Vector3(0,1,1),Quaternion.Euler(45,30,25)));
            Check(Mathf.Abs(wallLevel.forward.y)<.0001f && wallLevel.up.y>.999f,"wall level remains vertical while yaw is adjustable");
            var placed=level.position;
            cameraObject.transform.position+=Vector3.right;
            typeof(WorkspaceSurfaces).GetMethod("LateUpdate",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(provider,null);
            Near(level.position,placed,"head movement only billboards level label, never moves the calibrated plane");
            provider.ClearLevels(); Check(provider.LevelCount==0,"clear levels removes overrides so automatic surfaces can be reused");
            var facingHostObject=new GameObject("Disabled no-network workspace facing fixture");
            facingHostObject.SetActive(false);
            var facingHost=facingHostObject.AddComponent<HostScene>(); facingHost.enabled=false;
            try
            {
                facingHostObject.SetActive(true); // Disabled HostScene never opens its transport.
                typeof(HostScene).GetField("placed",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(facingHost,true);
                var settled=new Pose(new Vector3(2,1.65f,3),Quaternion.Euler(0,73,0));
                typeof(HostScene).GetProperty("PlacementHeadPose").SetValue(facingHost,settled);
                cameraObject.tag="MainCamera";
                cameraObject.transform.SetPositionAndRotation(settled.position,Quaternion.Euler(35,3,12));
                provider.BeginLevel("desk");
                var spawned=provider.Surfaces.Single();
                Near(spawned.Pose.position,WorkspaceSurfaces.InitialLevelPose("desk",settled.position,settled.rotation).position,
                    "actual menu callback uses common settled workspace frame even when head looks70degrees left at the menu");
                Check(Vector3.Dot(spawned.Pose.rotation*Vector3.up,settled.rotation*Vector3.forward)>.999f,
                    "actual menu callback does not seed side-menu yaw");
                var adjustedLevel=provider.RaycastLevel(new Ray(spawned.Pose.position+Vector3.up,Vector3.down),out _);
                typeof(WorkspaceArrangement).GetProperty("RotationAxis").SetValue(arrangement,Vector3.right);
                arrangement.Apply(adjustedLevel,spawned.Pose,spawned.Pose,false,false);
                Near(arrangement.RotationAxis,Vector3.up,"level rotation cannot inherit a previous wall normal");
            }
            finally
            {
                cameraObject.tag=oldTag;
                provider.ClearLevels();
                UnityEngine.Object.DestroyImmediate(facingHostObject);
            }
            screen=container.AddComponent<BlenderScreen>();
            typeof(BlenderScreen).GetField("arrangement",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(screen,arrangement);
            var camera=cameraObject.GetComponent<Camera>();
            typeof(BlenderScreen).GetMethod("BuildUi",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(screen,new object[]{camera});
            // Exercise actual pickup policy and the same rebase path used by trigger alignment/two-hand release.
            var interaction=container.AddComponent<WorkspaceInteraction>();
            var host=container.AddComponent<HostScene>();
            typeof(HostScene).GetField("root",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(host,display.transform);
            var handType=typeof(WorkspaceInteraction).GetNestedType("Hand",BindingFlags.NonPublic);
            var leftHand=Activator.CreateInstance(handType,true); var rightHand=Activator.CreateInstance(handType,true);
            foreach(var item in new[]{("left",leftHand),("right",rightHand),("scene",(object)host),("arrangement",(object)arrangement)})
                typeof(WorkspaceInteraction).GetField(item.Item1,BindingFlags.Instance|BindingFlags.NonPublic).SetValue(interaction,item.Item2);
            var begin=typeof(WorkspaceInteraction).GetMethod("Begin",BindingFlags.Instance|BindingFlags.NonPublic);
            var rebase=typeof(WorkspaceInteraction).GetMethod("RebasePlacement",BindingFlags.Static|BindingFlags.NonPublic);
            var pickupAim=new Pose(Vector3.zero,Quaternion.identity);
            display.transform.SetPositionAndRotation(new Vector3(0,1,1),Quaternion.Euler(0,47,0));
            begin.Invoke(interaction,new object[]{leftHand,display.transform,null,pickupAim,display.transform.position});
            Check((bool)handType.GetField("preserveRotation").GetValue(leftHand),"actual model pickup selects orientation-preserving placement");
            var relative=(Pose)handType.GetField("rayRelative").GetValue(leftHand);
            var held=(Quaternion)handType.GetField("placementRotation").GetValue(leftHand);
            var changedAim=new Pose(new Vector3(.1f,-.2f,0),Quaternion.Euler(32,25,18));
            var movedModel=WorkspaceInteraction.FollowPlacementRay(changedAim,relative,0,true,held,Quaternion.identity);
            Check(Vector3.Distance(movedModel.position,display.transform.position)>.4f,"wrist AIM still moves distant object through space; no return to rejected v17 mapping");
            Check(Quaternion.Angle(movedModel.rotation,held)<.001f,"wrist pitch/roll no longer tilts held model");
            var turned=WorkspaceInteraction.FollowPlacementRay(changedAim,relative,0,true,held,Quaternion.AngleAxis(15,Vector3.up));
            Check(Quaternion.Angle(turned.rotation,Quaternion.Euler(0,62,0))<.01f,"stick deliberately rotates the fixed held orientation");
            var leaning=Quaternion.Euler(35,47,28);
            var levelled=WorkspaceArrangement.AlignedRotation(leaning,Vector3.up);
            Check(Vector3.Dot(levelled*Vector3.up,Vector3.up)>.999f
                && Vector3.Angle(levelled*Vector3.forward,Vector3.ProjectOnPlane(leaning*Vector3.forward,Vector3.up))<.01f,"explicit desk alignment keeps heading while removing tilt");
            rebase.Invoke(null,new object[]{leftHand,changedAim,new Pose(movedModel.position,levelled)});
            relative=(Pose)handType.GetField("rayRelative").GetValue(leftHand); held=(Quaternion)handType.GetField("placementRotation").GetValue(leftHand);
            var continued=WorkspaceInteraction.FollowPlacementRay(new Pose(changedAim.position,Quaternion.Euler(60,-20,12)),relative,0,true,held,Quaternion.identity);
            Check(Quaternion.Angle(continued.rotation,levelled)<.001f,"aligned model stays level during continued one-hand movement");
            var twoHandRotation=Quaternion.Euler(22,71,17);
            rebase.Invoke(null,new object[]{leftHand,changedAim,new Pose(movedModel.position,twoHandRotation)});
            held=(Quaternion)handType.GetField("placementRotation").GetValue(leftHand);
            Check(Quaternion.Angle(WorkspaceInteraction.FollowPlacementRay(pickupAim,relative,0,true,held,Quaternion.identity).rotation,twoHandRotation)<.001f,"two-hand handoff retains its deliberately chosen orientation");
            begin.Invoke(interaction,new object[]{leftHand,screen.Placement,null,pickupAim,screen.Placement.position});
            Check(!(bool)handType.GetField("preserveRotation").GetValue(leftHand),"screen keeps accepted legacy grip orientation mapping");
            var legacy=WorkspaceInteraction.FollowPlacementRay(changedAim,relative,0,false,held,Quaternion.identity);
            Check(Quaternion.Angle(legacy.rotation,WorkspaceInteraction.FollowRay(changedAim,relative,0).rotation)<.001f,"legacy panel/menu orientation path is unchanged");
            var buttons=screen.Placement.GetComponentsInChildren<Button>(true);
            Check(buttons.Single(b=>b.name=="Arrange space mode").interactable,"Arrange space is available at top-left");
            Check(!buttons.Single(b=>b.name=="Edit model mode").interactable,"Edit model is visibly disabled, not a no-op mode");
            screen.Toggle();
            var top=buttons.Single(b=>b.name=="Arrange space mode").transform;
            Check(screen.RaycastSurface(new Ray(top.position-top.forward*.3f,top.forward),out _),"mode strip remains reachable with Blender preview hidden");
            Debug.Log("ARRANGEMENT_CHECKS PASS contact stops/no forced snap/explicit align/bounds/tunnelling/visible grabbable level/auto-off fallback/desk volume top/room UUID batches/rotated origin/two-hand rotation/native-safe undo/disabled Edit/hidden-preview mode strip/model grip orientation/aim position/stick rotation/heading-preserving align/rebase handoff/unlit contrast");
        }
        finally
        {
            if(screen!=null && screen.Placement!=null) UnityEngine.Object.DestroyImmediate(screen.Placement.gameObject);
            UnityEngine.Object.DestroyImmediate(container);
            UnityEngine.Object.DestroyImmediate(cameraObject);
        }
    }
    static void RenderLevelPreview(Transform level,Camera camera)
    {
        var path=Environment.GetEnvironmentVariable("CALHACKS_SURFACE_QA_PATH");
        if(string.IsNullOrEmpty(path)) return;
        var reference=GameObject.CreatePrimitive(PrimitiveType.Cube);
        var material=new Material(Resources.Load<Material>("WorkspaceSurfaceGuide"));
        var target=new RenderTexture(1280,960,24){antiAliasing=4};
        var image=new Texture2D(1280,960,TextureFormat.RGB24,false);
        var previous=RenderTexture.active;
        try
        {
            foreach(var item in level.GetComponentsInChildren<Transform>(true)) item.gameObject.layer=31;
            reference.layer=31; reference.name="Visual check desktop";
            reference.transform.position=level.position-Vector3.up*.03f;
            reference.transform.localScale=new Vector3(1.6f,.05f,1.2f);
            material.color=new Color(.65f,.65f,.65f,1); reference.GetComponent<Renderer>().sharedMaterial=material;
            camera.enabled=false; camera.cullingMask=1<<31; camera.clearFlags=CameraClearFlags.SolidColor;
            camera.backgroundColor=new Color(.25f,.3f,.35f,1); camera.stereoTargetEye=StereoTargetEyeMask.None;
            camera.transform.position=level.position+new Vector3(-.65f,.8f,-1.25f);
            camera.transform.LookAt(level.position+Vector3.up*.05f);
            var label=level.Find("Level label backing"); label.rotation=Quaternion.LookRotation(label.position-camera.transform.position,Vector3.up);
            Canvas.ForceUpdateCanvases(); camera.targetTexture=target; target.Create(); camera.Render();
            RenderTexture.active=target; image.ReadPixels(new Rect(0,0,1280,960),0,0); image.Apply();
            Directory.CreateDirectory(Path.GetDirectoryName(path)); File.WriteAllBytes(path,image.EncodeToPNG());
            int yellow=0,white=0;
            foreach(var pixel in image.GetPixels32())
            { if(pixel.r>180 && pixel.g>140 && pixel.b<100)yellow++; if(pixel.r>220&&pixel.g>220&&pixel.b>220)white++; }
            Check(yellow>500 && white>100,"real no-light camera render contains visible yellow grid/handle and white text");
            Debug.Log("SURFACE_VISUAL_CHECK PASS no_scene_lights yellow_pixels="+yellow+" white_text_pixels="+white);
        }
        finally
        {
            RenderTexture.active=previous; camera.targetTexture=null; target.Release();
            UnityEngine.Object.DestroyImmediate(reference); UnityEngine.Object.DestroyImmediate(material);
            UnityEngine.Object.DestroyImmediate(target); UnityEngine.Object.DestroyImmediate(image);
        }
    }
}

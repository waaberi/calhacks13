using System;
using System.Reflection;
using SpatialModeling;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;
using UnityEngine.InputSystem.XR;
using UnityEngine.XR;

public static class GlassControllerChecks
{
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static void Check(bool value,string why){if(!value)throw new Exception("GLASS_RENDER_AIM: "+why);}
    static void Set(object owner,string name,object value)=>owner.GetType().GetField(name,Private).SetValue(owner,value);
    static object Get(object hand,string name)=>hand.GetType().GetField(name).GetValue(hand);
    static void Pose(InputControl control,Vector3 position,Quaternion rotation,bool valid=true)
        => InputState.Change(control,new PoseState(valid,valid?InputTrackingState.Position|InputTrackingState.Rotation:InputTrackingState.None,position,rotation,Vector3.zero,Vector3.zero));
    public static void Run()
    {
        InputSystem.RegisterLayout<UnityEngine.InputSystem.XR.PoseControl>("GlassCurrentPose");
        InputSystem.RegisterLayout<UnityEngine.XR.OpenXR.Input.PoseControl>("GlassLegacyPose");
        try{foreach(string format in new[]{"Current","Legacy"})Format(format);}
        finally{InputSystem.RemoveLayout("GlassCurrentPose");InputSystem.RemoveLayout("GlassLegacyPose");}
        Depth();
        Debug.Log("P3_GLASS_RENDER_AIM_CHECK PASS actual_BeforeRender RenderHand same_sample_body_pointer hands=2 formats=2 rapid_samples=480 loss_release recenter object_filter_independent unlimited_depth");
    }
    static void Depth()
    {
        float depth=0;
        var aim=new UnityEngine.Pose(new Vector3(.1f,1,-.2f),Quaternion.Euler(0,71,0));
        var relative=new UnityEngine.Pose(new Vector3(0,0,1),Quaternion.identity);
        for(int i=0;i<1800;i++)depth=WorkspaceInteraction.AdvanceDepth(depth,1,1f/90);
        var far=WorkspaceInteraction.FollowRay(aim,relative,depth);
        Check(depth>19.9f&&Vector3.Distance(aim.position,far.position)>20.9f,"held stick keeps moving beyond old two metre limit without reselect");
        float before=depth;depth=WorkspaceInteraction.AdvanceDepth(depth,1,1f/90);
        Check(depth>before,"outward motion continues after extended hold");
        for(int i=0;i<3600;i++)depth=WorkspaceInteraction.AdvanceDepth(depth,-1,1f/90);
        Check(depth< -19.9f,"inward motion is not capped at the old minus half metre limit");
        before=depth;Check(WorkspaceInteraction.AdvanceDepth(depth,.19f,1)==before,"dead zone still avoids accidental motion");
    }
    static void Format(string format)
    {
        string layout="Glass"+format+"Controller";
        InputSystem.RegisterLayout("{\"name\":\""+layout+"\",\"extend\":\"XRController\",\"controls\":[{\"name\":\"devicePose\",\"layout\":\"Glass"+format+"Pose\",\"offset\":128},{\"name\":\"pointer\",\"layout\":\"Glass"+format+"Pose\",\"offset\":256,\"usages\":[\"Pointer\"]}]}");
        var a=InputSystem.AddDevice(layout);var b=InputSystem.AddDevice(layout);InputSystem.SetDeviceUsage(a,"LeftHand");InputSystem.SetDeviceUsage(b,"RightHand");
        var owner=new GameObject("inactive real render fixture");owner.SetActive(false);
        var origin=new GameObject("translated rotated render origin");origin.transform.SetPositionAndRotation(new Vector3(1,.2f,-2),Quaternion.Euler(0,123,0));
        var camera=new GameObject("render fixture main camera",typeof(Camera));camera.tag="MainCamera";camera.transform.SetParent(origin.transform,false);
        object left=null,right=null;Material material=null;GameObject movingCollider=null;
        var previous=PreviewInteraction.Current;
        typeof(PreviewInteraction).GetProperty("Current").GetSetMethod(true).Invoke(null,new object[]{null});
        try
        {
            var interaction=owner.AddComponent<WorkspaceInteraction>();var host=owner.AddComponent<HostScene>();var screen=owner.AddComponent<BlenderScreen>();
            material=new Material(Shader.Find("Universal Render Pipeline/Unlit"));Set(interaction,"material",material);Set(interaction,"scene",host);Set(interaction,"screen",screen);Set(interaction,"trackingOrigin",origin.transform);
            var create=typeof(WorkspaceInteraction).GetMethod("CreateHand",Private);
            left=create.Invoke(interaction,new object[]{XRNode.LeftHand,"LeftHand",GlassTheme.LeftMetal});
            right=create.Invoke(interaction,new object[]{XRNode.RightHand,"RightHand",GlassTheme.RightMetal});
            Set(interaction,"left",left);Set(interaction,"right",right);
            foreach(var hand in new[]{left,right})
            {
                ((InputAction)Get(hand,"gripPose")).Dispose();((InputAction)Get(hand,"aimPose")).Dispose();
                string usage=hand==left?"LeftHand":"RightHand";
                var grip=new InputAction("glass grip",InputActionType.Value,"<"+layout+">{"+usage+"}/devicePose",expectedControlType:"Pose");
                var aim=new InputAction("glass aim",InputActionType.Value,"<"+layout+">{"+usage+"}/{Pointer}",expectedControlType:"Pose");grip.Enable();aim.Enable();
                hand.GetType().GetField("gripPose").SetValue(hand,grip);hand.GetType().GetField("aimPose").SetValue(hand,aim);
            }
            for(int sample=0;sample<120;sample++)
            {
                var rotation=Quaternion.Euler(sample%40-20,sample*7,13);
                var aimRotation=rotation*Quaternion.Euler(-35,23,0);
                Pose(a["devicePose"],new Vector3(-.2f,.9f,.3f),rotation);Pose(a["pointer"],new Vector3(-.16f,.92f,.37f),aimRotation);
                Pose(b["devicePose"],new Vector3(.2f,.9f,.3f),Quaternion.Inverse(rotation));Pose(b["pointer"],new Vector3(.23f,.92f,.37f),Quaternion.Inverse(aimRotation));
                if(sample==60)origin.transform.rotation=Quaternion.Euler(0,71,0); // Recenter uses the same conversion once.
                Set(interaction,"renderedFrame",-1);typeof(WorkspaceInteraction).GetMethod("BeforeRender",Private).Invoke(interaction,null);
                foreach(var hand in new[]{left,right})
                {
                    var control=hand==left?a["pointer"]:b["pointer"];Check(WorkspaceInteraction.TryReadControllerPose(control,out var local),"current typed aim is readable");
                    var expected=WorkspaceInteraction.ToWorldPose(origin.transform,local);var visual=(GameObject)Get(hand,"visual");var ray=(LineRenderer)Get(hand,"ray");
                    var raw=(Transform)Get(hand,"rawAim");var stable=(Transform)Get(hand,"stableAim");
                    Check(Vector3.Distance(raw.position,expected.position)<.000001f&&Quaternion.Angle(raw.rotation,expected.rotation)<.03f,"raw same-device sample and origin conversion preserved");
                    var body=(Transform)Get(hand,"body");
                    Check(visual.activeSelf&&Vector3.Distance(body.position,expected.position)<.000001f&&Quaternion.Angle(body.rotation,expected.rotation)<.03f,"body uses current same-device aim without filtering or hover-contact rotation");
                    var gripControl=hand==left?a["devicePose"]:b["devicePose"];Check(WorkspaceInteraction.TryReadControllerPose(gripControl,out var gripLocal),"paired grip readable");
                    var gripWorld=WorkspaceInteraction.ToWorldPose(origin.transform,gripLocal);
                    Check(Vector3.Distance(visual.transform.position,gripWorld.position)<.000001f,"accepted grip-root tracking preserved");
                    Check(Vector3.Distance(ray.GetPosition(0),expected.position)<.000001f,"pointer origin and cylinder share exact current sample");
                    Check(Vector3.Angle(ray.GetPosition(1)-ray.GetPosition(0),expected.rotation*Vector3.forward)<.03f,"pointer direction follows current cylinder without stable-ray latency");
                    Check(Vector3.Distance(((Transform)Get(hand,"tip")).position,ray.GetPosition(1))<.000001f,"tip shares current ray endpoint");

                }
            }
            var contactTarget=new GameObject("held contact must not steer body");contactTarget.transform.SetParent(owner.transform,false);
            contactTarget.transform.SetPositionAndRotation(new Vector3(2,.5f,1),Quaternion.Euler(35,71,20));
            left.GetType().GetField("target").SetValue(left,contactTarget.transform);left.GetType().GetField("localContact").SetValue(left,new Vector3(.2f,.1f,.3f));Set(interaction,"pairTarget",contactTarget.transform);
            var route=typeof(WorkspaceInteraction).GetMethod("RouteHand",Private);
            foreach(float depth in new[]{9f,-9f})
            {
                left.GetType().GetField("depth").SetValue(left,depth);
                route.Invoke(interaction,new object[]{left,right,new UnityEngine.Pose(Vector3.zero,Quaternion.identity),new Ray(Vector3.zero,Vector3.forward),true,false,false,false,new Vector2(0,Mathf.Sign(depth)),false});
                Check(Mathf.Abs((float)Get(left,"depth"))>=9,"production held routing does not cap accumulated positive or negative depth");
                Check(Get(left,"target")==contactTarget.transform,"extended stick motion never requires reselecting held object");
            }
            typeof(WorkspaceInteraction).GetMethod("RenderHand",Private).Invoke(interaction,new object[]{left,Time.realtimeSinceStartupAsDouble});
            Check(WorkspaceInteraction.TryReadControllerPose(a["pointer"],out var heldLocal),"held device aim readable");
            var heldAim=WorkspaceInteraction.ToWorldPose(origin.transform,heldLocal);var heldBody=(Transform)Get(left,"body");
            Check(Vector3.Distance(heldBody.position,heldAim.position)<.000001f&&Quaternion.Angle(heldBody.rotation,heldAim.rotation)<.03f,"held contact cannot pull or turn the physical controller body");
            var heldRay=(LineRenderer)Get(left,"ray");Check(Vector3.Angle(heldRay.GetPosition(1)-heldRay.GetPosition(0),heldAim.rotation*Vector3.forward)<.03f,"held contact cannot pull pointer behind current cylinder; object filter stays separate");
            left.GetType().GetField("target").SetValue(left,null);Set(interaction,"pairTarget",null);
            UnityEngine.Object.DestroyImmediate(contactTarget);
            // Collider queries must see geometry moved since LateUpdate, just
            // as the hand menu and held meshes move during BeforeRender.
            movingCollider=GameObject.CreatePrimitive(PrimitiveType.Cube);
            movingCollider.AddComponent<WorkspaceObjectView>();
            movingCollider.AddComponent<MeshCollider>().sharedMesh=movingCollider.GetComponent<MeshFilter>().sharedMesh;
            movingCollider.transform.position=heldAim.position+Vector3.up*50;
            movingCollider.transform.localScale=Vector3.one*.1f;
            var objects=(System.Collections.IDictionary)typeof(HostScene).GetField("objects",Private).GetValue(host);
            objects["moving collider"]=movingCollider;Physics.SyncTransforms();
            movingCollider.transform.SetPositionAndRotation(heldAim.position+heldAim.rotation*Vector3.forward*1.5f,heldAim.rotation);
            typeof(WorkspaceInteraction).GetMethod("RenderHand",Private).Invoke(interaction,new object[]{left,Time.realtimeSinceStartupAsDouble});
            Check(Mathf.Abs(Vector3.Distance(heldRay.GetPosition(0),heldRay.GetPosition(1))-1.45f)<.002f,"late visual ray sees moved collider in current frame rather than its old physics pose");
            objects.Clear();UnityEngine.Object.DestroyImmediate(movingCollider);movingCollider=null;
            Pose(a["pointer"],Vector3.zero,Quaternion.identity,false);
            var held=new GameObject("held fixture");left.GetType().GetField("target").SetValue(left,held.transform);
            Set(interaction,"renderedFrame",-1);typeof(WorkspaceInteraction).GetMethod("BeforeRender",Private).Invoke(interaction,null);
            Check(!((GameObject)Get(left,"visual")).activeSelf&&Get(left,"target")==null,"aim loss hides cylinder and releases held target without grip fallback");
            UnityEngine.Object.DestroyImmediate(held);
        }
        finally
        {
            foreach(var hand in new[]{left,right})if(hand!=null){((InputAction)Get(hand,"gripPose")).Dispose();((InputAction)Get(hand,"aimPose")).Dispose();}
            typeof(PreviewInteraction).GetProperty("Current").GetSetMethod(true).Invoke(null,new object[]{previous});
            UnityEngine.Object.DestroyImmediate(owner);UnityEngine.Object.DestroyImmediate(origin);if(material!=null)UnityEngine.Object.DestroyImmediate(material);
            if(movingCollider!=null)UnityEngine.Object.DestroyImmediate(movingCollider);
            InputSystem.RemoveDevice(a);InputSystem.RemoveDevice(b);InputSystem.RemoveLayout(layout);
        }
    }
}

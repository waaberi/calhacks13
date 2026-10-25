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
        Debug.Log("P3_GLASS_RENDER_AIM_CHECK PASS actual_BeforeRender RenderHand accepted_stabilized_ray hands=2 formats=2 rapid_samples=480 loss_release recenter no_extra_visual_filter");
    }
    static void Format(string format)
    {
        string layout="Glass"+format+"Controller";
        InputSystem.RegisterLayout("{\"name\":\""+layout+"\",\"extend\":\"XRController\",\"controls\":[{\"name\":\"devicePose\",\"layout\":\"Glass"+format+"Pose\",\"offset\":128},{\"name\":\"pointer\",\"layout\":\"Glass"+format+"Pose\",\"offset\":256,\"usages\":[\"Pointer\"]}]}");
        var a=InputSystem.AddDevice(layout);var b=InputSystem.AddDevice(layout);InputSystem.SetDeviceUsage(a,"LeftHand");InputSystem.SetDeviceUsage(b,"RightHand");
        var owner=new GameObject("inactive real render fixture");owner.SetActive(false);
        var origin=new GameObject("translated rotated render origin");origin.transform.SetPositionAndRotation(new Vector3(1,.2f,-2),Quaternion.Euler(0,123,0));
        var camera=new GameObject("render fixture main camera",typeof(Camera));camera.tag="MainCamera";camera.transform.SetParent(origin.transform,false);
        object left=null,right=null;Material material=null;
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
                    Check(visual.activeSelf&&Vector3.Distance(visual.transform.position,stable.position)<.000001f,"body follows accepted stabilized ray without another filter");
                    Check(Vector3.Distance(ray.GetPosition(0),stable.position)<.000001f,"actual body and accepted ray origin agree");
                    Check(Vector3.Angle(visual.transform.forward,ray.GetPosition(1)-ray.GetPosition(0))<.03f,"actual ray stays coaxial during rapid turns");
                }
            }
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
            InputSystem.RemoveDevice(a);InputSystem.RemoveDevice(b);InputSystem.RemoveLayout(layout);
        }
    }
}

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
    static void HandSet(object hand,string name,object value)=>hand.GetType().GetField(name).SetValue(hand,value);
    static void Pose(InputControl control,Vector3 position,Quaternion rotation,bool valid=true)
        => InputState.Change(control,new PoseState(valid,valid?InputTrackingState.Position|InputTrackingState.Rotation:InputTrackingState.None,position,rotation,Vector3.zero,Vector3.zero));
    public static void Run()
    {
        InputSystem.RegisterLayout<UnityEngine.InputSystem.XR.PoseControl>("GlassCurrentPose");
        InputSystem.RegisterLayout<UnityEngine.XR.OpenXR.Input.PoseControl>("GlassLegacyPose");
        try{foreach(string format in new[]{"Current","Legacy"})Format(format);}
        finally{InputSystem.RemoveLayout("GlassCurrentPose");InputSystem.RemoveLayout("GlassLegacyPose");}
        Depth();
        Debug.Log("P3_GLASS_RENDER_AIM_CHECK PASS actual_BeforeRender RenderHand stabilized_body_pointer hands=2 formats=2 rapid_samples=480 held_exact_contact jitter_suppressed_with_unchanged_object_follower no_nearer_surface_jumps loss_release recenter unlimited_depth");
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
        object left=null,right=null;Material material=null;GameObject movingCollider=null,nearMenu=null;
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
                    Check(visual.activeSelf&&Vector3.Distance(body.position,stable.position)<.000001f,"body and stabilized ray use the same displayed origin in this frame");
                    var gripControl=hand==left?a["devicePose"]:b["devicePose"];Check(WorkspaceInteraction.TryReadControllerPose(gripControl,out var gripLocal),"paired grip readable");
                    var gripWorld=WorkspaceInteraction.ToWorldPose(origin.transform,gripLocal);
                    Check(Vector3.Distance(visual.transform.position,gripWorld.position)<.000001f,"accepted grip-root tracking preserved");
                    Check(Vector3.Distance(ray.GetPosition(0),stable.position)<.000001f,"pointer origin and cylinder share the exact stabilized pose");
                    Check(Vector3.Angle(ray.GetPosition(1)-ray.GetPosition(0),stable.forward)<.03f,"free pointer follows the same stabilized aim used for logical UI hits");
                    Check(Vector3.Angle(body.forward,ray.GetPosition(1)-ray.GetPosition(0))<.03f,"cylinder axis and displayed pointer are coaxial in the same frame");
                    float endpointError=Vector3.Distance(((Transform)Get(hand,"tip")).position,ray.GetPosition(1));
                    Check(endpointError<.00001f,"tip shares current ray endpoint within world/local float precision; error_m="+endpointError);

                }
            }
            Check(WorkspaceInteraction.TryReadControllerPose(a["pointer"],out var heldLocal),"held device aim readable");
            var heldAim=WorkspaceInteraction.ToWorldPose(origin.transform,heldLocal);
            var contactTarget=new GameObject("held smooth contact");contactTarget.transform.SetParent(owner.transform,false);
            contactTarget.transform.SetPositionAndRotation(heldAim.position+heldAim.rotation*Vector3.forward*9,Quaternion.Euler(35,71,20));
            left.GetType().GetField("target").SetValue(left,contactTarget.transform);left.GetType().GetField("localContact").SetValue(left,new Vector3(.2f,.1f,.3f));Set(interaction,"pairTarget",contactTarget.transform);
            var route=typeof(WorkspaceInteraction).GetMethod("RouteHand",Private);
            foreach(float depth in new[]{9f,-9f})
            {
                left.GetType().GetField("depth").SetValue(left,depth);
                route.Invoke(interaction,new object[]{left,right,new UnityEngine.Pose(Vector3.zero,Quaternion.identity),new Ray(Vector3.zero,Vector3.forward),true,false,false,false,new Vector2(0,Mathf.Sign(depth)),false});
                Check(Mathf.Abs((float)Get(left,"depth"))>=9,"production held routing does not cap accumulated positive or negative depth");
                Check(Get(left,"target")==contactTarget.transform,"extended stick motion never requires reselecting held object");
            }
            movingCollider=GameObject.CreatePrimitive(PrimitiveType.Cube);
            movingCollider.AddComponent<WorkspaceObjectView>();
            movingCollider.AddComponent<MeshCollider>().sharedMesh=movingCollider.GetComponent<MeshFilter>().sharedMesh;
            movingCollider.transform.localScale=Vector3.one*.1f;
            var objects=(System.Collections.IDictionary)typeof(HostScene).GetField("objects",Private).GetValue(host);
            objects["moving collider"]=movingCollider;
            movingCollider.transform.SetPositionAndRotation(heldAim.position+heldAim.rotation*Vector3.forward*1.5f,heldAim.rotation);
            nearMenu=new GameObject("nearer unrelated menu",typeof(RectTransform),typeof(BoxCollider),typeof(RoundedGlassImage));
            nearMenu.transform.localScale=Vector3.one*.001f;
            nearMenu.GetComponent<RectTransform>().sizeDelta=new Vector2(640,580);
            nearMenu.GetComponent<BoxCollider>().size=new Vector3(640,580,14);
            GlassTheme.StylePanel(nearMenu.GetComponent<RoundedGlassImage>());
            nearMenu.transform.SetPositionAndRotation(heldAim.position+heldAim.rotation*Vector3.forward*.8f,heldAim.rotation);
            var table=owner.AddComponent<TablePlacement>();Set(table,"panel",nearMenu.transform);Set(host,"table",table);
            var stableHeld=(Transform)Get(left,"stableAim");stableHeld.SetPositionAndRotation(heldAim.position,heldAim.rotation);
            Physics.SyncTransforms();var probe=new Ray(heldAim.position,heldAim.rotation*Vector3.forward);
            Check(host.PickObject(probe,out var meshDistance)!=null&&meshDistance<2
                &&table.RaycastControls(probe,out var menuDistance)&&menuDistance<1,"adversarial unrelated mesh and menu are genuinely nearer than the held contact");
            typeof(WorkspaceInteraction).GetMethod("RenderHand",Private).Invoke(interaction,new object[]{left,Time.realtimeSinceStartupAsDouble});
            var heldBody=(Transform)Get(left,"body");var heldRay=(LineRenderer)Get(left,"ray");
            var exactContact=contactTarget.transform.TransformPoint((Vector3)Get(left,"localContact"));
            Check(Vector3.Distance(heldRay.GetPosition(1),exactContact)<.000001f
                &&Vector3.Distance(((Transform)Get(left,"tip")).position,exactContact)<.00001f
                &&Vector3.Distance(heldRay.GetPosition(0),exactContact)>4,"held endpoint is the exact local contact beyond four metres despite nearer unrelated mesh/menu");
            Check(Vector3.Distance(heldBody.position,stableHeld.position)<.000001f
                &&Vector3.Distance(heldRay.GetPosition(0),stableHeld.position)<.000001f
                &&Vector3.Angle(heldBody.forward,exactContact-stableHeld.position)<.03f,"held cylinder, ray and tip use one stabilized origin and actual smooth contact");
            Set(interaction,"pairTarget",null);
            foreach(var hand in new[]{left,right})
                Jitter(interaction,hand,hand==left?a:b,origin.transform,contactTarget.transform,movingCollider,nearMenu,format);
            HandSet(left,"target",null);HandSet(right,"target",null);Set(host,"table",null);nearMenu.SetActive(false);
            UnityEngine.Object.DestroyImmediate(contactTarget);
            // Seed a known stabilized pose before the free-ray physics check;
            // this isolates moved-collider freshness from the smoothing filter.
            Pose(a["pointer"],heldLocal.position,heldLocal.rotation);
            stableHeld.SetPositionAndRotation(heldAim.position,heldAim.rotation);HandSet(left,"aimInitialized",true);
            HandSet(left,"previousPoseTime",Time.realtimeSinceStartupAsDouble);
            movingCollider.SetActive(true);movingCollider.transform.position=heldAim.position+Vector3.up*50;Physics.SyncTransforms();
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
            if(nearMenu!=null)UnityEngine.Object.DestroyImmediate(nearMenu);
            InputSystem.RemoveDevice(a);InputSystem.RemoveDevice(b);InputSystem.RemoveLayout(layout);
        }
    }

    static void Jitter(WorkspaceInteraction interaction,object hand,UnityEngine.InputSystem.InputDevice device,Transform origin,
        Transform target,GameObject occluder,GameObject menu,string format)
    {
        const int rate=90;const float dt=1f/rate;
        var localOrigin=new Vector3(hand.GetType().GetField("node").GetValue(hand).Equals(XRNode.LeftHand)?-.16f:.23f,.92f,.37f);
        var baseline=WorkspaceInteraction.ToWorldPose(origin,new UnityEngine.Pose(localOrigin,Quaternion.identity));
        target.SetPositionAndRotation(baseline.position+baseline.rotation*Vector3.forward*1.02f,baseline.rotation);
        var relative=WorkspaceInteraction.RelativeRayPose(baseline,new UnityEngine.Pose(target.position,target.rotation));
        var contact=new Vector3(.02f,.01f,.03f);
        HandSet(hand,"target",target);HandSet(hand,"localContact",contact);HandSet(hand,"rayRelative",relative);
        HandSet(hand,"depth",0f);HandSet(hand,"preserveRotation",true);HandSet(hand,"placementRotation",target.rotation);
        HandSet(hand,"rotationOffset",Quaternion.identity);HandSet(hand,"aimInitialized",true);HandSet(hand,"previousPoseTime",100d);
        var stable=(Transform)Get(hand,"stableAim");stable.SetPositionAndRotation(baseline.position,baseline.rotation);
        var ray=(LineRenderer)Get(hand,"ray");var body=(Transform)Get(hand,"body");var tip=(Transform)Get(hand,"tip");
        var previousShown=target.TransformPoint(contact);var previousRaw=previousShown;
        double rawSquared=0,shownSquared=0;float worstContactError=0;
        for(int sample=1;sample<=rate*3;sample++)
        {
            float noise=Mathf.Sin(sample*dt*2*Mathf.PI*24);
            var local=new UnityEngine.Pose(localOrigin+Vector3.right*(.0016f*noise),Quaternion.Euler(0,2.84f*noise,0));
            Pose(device["devicePose"],localOrigin-Vector3.forward*.04f,Quaternion.identity);
            Pose(device["pointer"],local.position,local.rotation);
            var raw=WorkspaceInteraction.ToWorldPose(origin,local);
            float near=sample%2==0?.35f:.65f;
            occluder.SetActive(true);occluder.transform.SetPositionAndRotation(baseline.position+baseline.rotation*Vector3.forward*near,baseline.rotation);
            menu.SetActive(true);menu.transform.SetPositionAndRotation(baseline.position+baseline.rotation*Vector3.forward*(1-near),baseline.rotation);
            typeof(WorkspaceInteraction).GetMethod("RenderHand",Private).Invoke(interaction,new object[]{hand,100d+sample*dt});
            var shown=target.TransformPoint(contact);
            var expectedFollower=WorkspaceInteraction.FollowPlacementRay(new UnityEngine.Pose(stable.position,stable.rotation),relative,0,true,baseline.rotation,Quaternion.identity);
            Check(Vector3.Distance(target.position,expectedFollower.position)<.000001f&&Quaternion.Angle(target.rotation,expectedFollower.rotation)<.03f,
                "production held-object follower still uses the unchanged stabilized placement mapping");
            float error=Vector3.Distance(ray.GetPosition(1),shown);worstContactError=Mathf.Max(worstContactError,error);
            Check(error<.000001f&&Vector3.Distance(tip.position,shown)<.00001f,"visible point follows the exact smooth object contact each noisy sample; nearer surfaces cannot steal it");
            Check(Vector3.Distance(body.position,stable.position)<.000001f&&Vector3.Distance(ray.GetPosition(0),body.position)<.000001f
                &&Vector3.Angle(body.forward,shown-body.position)<.03f,"stabilized cylinder and contact ray stay coaxial within the same render update");
            var rawFollower=WorkspaceInteraction.FollowPlacementRay(raw,relative,0,true,baseline.rotation,Quaternion.identity);
            var rawContact=rawFollower.position+rawFollower.rotation*contact;
            if(sample>rate){rawSquared+=(rawContact-previousRaw).sqrMagnitude;shownSquared+=(shown-previousShown).sqrMagnitude;}
            previousRaw=rawContact;previousShown=shown;
        }
        Check(rawSquared>0,"synthetic device poses contain measurable high-frequency hand jitter");
        double ratio=Math.Sqrt(shownSquared/rawSquared);
        Check(ratio<.35,"actual RenderHand retains the accepted object's jitter suppression while point follows identically; ratio="+ratio);
        Debug.Log("GLASS_HELD_POINT_JITTER_CHECK PASS format="+format+" hand="+Get(hand,"node")+" actual_RenderHand samples=270 controlled_time=True unchanged_object_follower=True shown_step_ratio="+ratio+" max_contact_error_m="+worstContactError+" nearer_mesh_menu_swap_ignored=True");
        HandSet(hand,"target",null);
    }
}

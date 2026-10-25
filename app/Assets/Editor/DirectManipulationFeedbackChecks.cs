using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEngine;

public static class DirectManipulationFeedbackChecks
{
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    const string A="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",B="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    static void Check(bool value,string why){if(!value)throw new Exception("DIRECT_MANIPULATION_FEEDBACK: "+why);}
    static object Get(object value,string field)=>value.GetType().GetField(field,Private).GetValue(value);
    static void Set(object value,string field,object data)=>value.GetType().GetField(field,Private).SetValue(value,data);
    static object Call(object value,string method,params object[] args)=>value.GetType().GetMethod(method,Private).Invoke(value,args);
    static void Native(DirectModelEditingChecks.Fixture f,string tool)=>typeof(LiveControllerChecks).GetMethod("NativeLive",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{f,tool});
    static void Grant(DirectModelEditingChecks.Fixture f)=>typeof(LiveControllerChecks).GetMethod("GrantAndBegin",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{f});
    static void State(DirectModelEditingChecks.Fixture f,string phase,long sequence,string re)=>typeof(LiveControllerChecks).GetMethod("State",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{f,phase,sequence,re});
    public static void Run()
    {
        ArrowVisualAndMath();ArrowNativeRoute();ArrowOuterFences();MoveBodyAndPlane();ScaleFormat();ScaleAcknowledgments();ScaleCommitAndSelection();ScaleMultiTarget();DisplayScale();
        Debug.Log("DIRECT_MANIPULATION_FEEDBACK_CHECK PASS RGB-Move-arrowheads/native-constrained-trigger-route/frozen-reflected-affine-frame/nearer-fence/free-body+planes/acknowledged-scale-multiplier/axis-factors/no-queued-or-late-ACK-display/cancel+commit-reset; physical acceptance pending");
    }
    static void ArrowVisualAndMath()
    {
        foreach(var scale in new[]{Vector3.one,new Vector3(-2,.4f,3)})
        {
            var map=Matrix4x4.TRS(Vector3.one,Quaternion.Euler(19,41,-27),scale);
            var axes=new[]{map.MultiplyVector(Vector3.right),map.MultiplyVector(Vector3.forward),map.MultiplyVector(Vector3.up)};
            var frame=new DirectTranslationHandles.Frame(Vector3.one,axes,Vector3.back);
            var frozen=frame.Axis(0);axes[0]=Vector3.zero;Check(frame.Valid&&frame.Axis(0)==frozen,"frame owns its original native axis directions");
            using var arrows=new DirectTranslationHandles();arrows.Draw(frame);
            var root=GameObject.Find("Native Blender Move arrows");Check(root!=null,"production Move arrows render");
            Check(root.GetComponentsInChildren<LineRenderer>().Length==3&&root.GetComponentsInChildren<MeshRenderer>().Length==3,"three shafts and three actual solid cone arrowheads");
            for(int axis=0;axis<3;axis++)
            {
                var side=Vector3.Cross(frame.Axis(axis),Mathf.Abs(Vector3.Dot(frame.Axis(axis),Vector3.up))<.8f?Vector3.up:Vector3.right).normalized;
                var ray=new Ray(frame.Tip(axis)+side*.4f,-side);
                Check(DirectTranslationHandles.TryPick(frame,ray,.41f,out var hit)&&hit.Axis==axis,"visible cone/shaft picks matching native axis under reflected nonuniform placement");
                Check(!DirectTranslationHandles.TryPick(frame,ray,.30f,out _),"nearer UI fence prevents an arrow behind it");
                arrows.Draw(frame,axis);var tip=root.transform.Find("Native "+"XYZ"[axis]+" Move arrow");
                Check(Vector3.Distance(tip.position,frame.Tip(axis))<.00001f,"arrowhead geometry and hit frame use the same frozen tip");
            }
            arrows.Hide();Check(!root.activeSelf,"ending editing hides Move arrows");
        }
    }
    static void ArrowNativeRoute()
    {
        foreach(bool reflected in new[]{false,true})
        foreach(int axis in new[]{0,1,2})
        {
            using var f=new DirectModelEditingChecks.Fixture("builtin.move");Native(f,"object.translate");
            if(reflected){f.View.transform.parent.localScale=new Vector3(-2,.7f,1.5f);f.View.transform.parent.rotation=Quaternion.Euler(13,31,-7);}
            var model=(JObject)f.Drawing.NativeState["model_edit"];model["settings"]["pivot_m"]=new JArray(0,2,0);
            Call(f.Direct,"Update");Physics.SyncTransforms();var live=(DirectLiveController)Get(f.Direct,"live");
            var frame=(DirectTranslationHandles.Frame)Call(live,"TranslationFrame",f.View);
            var side=Vector3.Cross(frame.Axis(axis),Mathf.Abs(Vector3.Dot(frame.Axis(axis),Vector3.up))<.8f?Vector3.up:Vector3.right).normalized;
            var eye=frame.Tip(axis)+side*.6f;var first=new Ray(eye,-side);
            bool Route(Ray ray,bool trigger,float limit=4)=>f.Preview.RouteControllerHand(UnityEngine.XR.XRNode.RightHand,ray,trigger,false,Vector2.zero,limit,out _,false);
            Check(Route(first,true)&&f.Direct.Gesturing,"actual front trigger grabs the Move arrow");
            var moved=new Ray(eye,(frame.Tip(axis)+frame.Axis(axis)*.03f-eye).normalized);
            Route(moved,true);Grant(f);
            var begin=f.Sent.Last(m=>(string)m["type"]=="live.edit.begin");var constraint=(JArray)begin["payload"]["operation"]["settings"]["constraint_axis"];
            Check(Enumerable.Range(0,3).All(i=>(bool)constraint[i]==(i==axis)),"actual typed begin carries only grabbed native X/Y/Z constraint");
            var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");var delta=DirectModelEditMath.ToUnity((JArray)update["payload"]["parameters"]["translation_m"]);
            var expected=(f.View.NativeToDisplayMatrix.inverse.MultiplyVector(frame.Axis(axis))).normalized;
            Check(delta.sqrMagnitude>1e-10f&&Vector3.Dot(delta.normalized,expected)>.9999f,"held arrow movement converts its frozen affine display axis back into native metres once");
            model["settings"]["pivot_m"]=new JArray(8,9,10);Call(f.Direct,"Update");
            var root=GameObject.Find("Native Blender Move arrows");var shaft=root.transform.Find("Native "+"XYZ"[axis]+" Move shaft").GetComponent<LineRenderer>();
            Check(Vector3.Distance(shaft.GetPosition(0),frame.Start(axis))<.00001f,"native own telemetry does not shift the held arrow pivot or axes");
            State(f,"updated",1,(string)update["id"]);Route(moved,false);
            var commit=f.Sent.Last(m=>(string)m["type"]=="live.edit.commit");State(f,"committed",1,(string)commit["id"]);
            Check(f.Sent.Count(m=>(string)m["type"]=="live.edit.commit")==1,"released arrow makes exactly one native history commit");
        }
    }
    static void MoveBodyAndPlane()
    {
        using(var f=new DirectModelEditingChecks.Fixture("builtin.move"))
        {
            Native(f,"object.translate");var model=(JObject)f.Drawing.NativeState["model_edit"];model["settings"]["pivot_m"]=new JArray(0,2,0);Call(f.Direct,"Update");
            f.Route(true);f.Route(false);Check(((JArray)f.Direct.SelectionSnapshot["objects"]).Count==0,"body trigger tap still explicitly deselects without dragging");
            Check(!f.Sent.Any(m=>(string)m["type"]=="live.edit.begin"),"body selection tap cannot send geometry");
        }
        using(var f=new DirectModelEditingChecks.Fixture("builtin.move"))
        {
            Native(f,"object.translate");var model=(JObject)f.Drawing.NativeState["model_edit"];model["settings"]["pivot_m"]=new JArray(0,2,0);Call(f.Direct,"Update");
            var ray=new Ray(Vector3.zero,new Vector3(.04f,.04f,2).normalized);
            Check(f.Preview.RouteControllerHand(UnityEngine.XR.XRNode.RightHand,ray,true,false,Vector2.zero,4,out _,false),"existing Move plane square is still trigger routed");
            var live=(DirectLiveController)Get(f.Direct,"live");var constraints=(bool[])Get(live,"gizmoConstraint");
            Check(constraints.Count(v=>v)==2&&Get(live,"translationGestureFrame")==null,"plane square preserves a plane constraint rather than becoming an axis arrow");
        }
    }
    static void ArrowOuterFences()
    {
        using var f=new DirectModelEditingChecks.Fixture("builtin.move");Native(f,"object.translate");
        SurfaceScaleChecks.SetBox(f.View,new Vector3(0,0,2),Vector3.one*.4f);
        var model=(JObject)f.Drawing.NativeState["model_edit"];model["settings"]["pivot_m"]=new JArray(0,2,0);Call(f.Direct,"Update");Physics.SyncTransforms();
        var live=(DirectLiveController)Get(f.Direct,"live");var frame=(DirectTranslationHandles.Frame)Call(live,"TranslationFrame",f.View);
        var ray=new Ray(Vector3.zero,frame.Tip(0).normalized);var selected=f.Host.PickObject(ray,out var ownDepth);
        Check(selected==f.View&&ownDepth<Vector3.Distance(ray.origin,frame.Tip(0)),"regression places rendered Move arrow behind the actual selected mesh front");
        Check(f.Preview.RouteControllerHand(UnityEngine.XR.XRNode.RightHand,ray,true,false,Vector2.zero,ownDepth,out _,false)
            &&Get(live,"translationGestureFrame")!=null,"exact selected-mesh fence exception makes its rendered Move arrow triggerable");
        f.Preview.CancelDirectModelDraft("test cleanup");f.Preview.RouteControllerHand(UnityEngine.XR.XRNode.RightHand,ray,false,false,Vector2.zero,4,out _,false);
        Check(!f.Preview.RouteControllerHand(UnityEngine.XR.XRNode.RightHand,ray,true,false,Vector2.zero,ownDepth-.01f,out _,false),"a nearer unrelated control fence cannot inherit the selected-mesh exception");
        f.Preview.RouteControllerHand(UnityEngine.XR.XRNode.RightHand,ray,false,false,Vector2.zero,4,out _,false);
        var other=new GameObject("Nearer independent object",typeof(MeshFilter),typeof(MeshCollider),typeof(WorkspaceObjectView));other.transform.SetParent(f.View.transform.parent,false);
        var mesh=f.View.GetComponent<MeshFilter>().sharedMesh;other.GetComponent<MeshFilter>().sharedMesh=mesh;other.GetComponent<MeshCollider>().sharedMesh=mesh;
        var view=other.GetComponent<WorkspaceObjectView>();view.ObjectId=B;view.Generation=4;view.SetNativePose(ray.GetPoint(1.2f)-new Vector3(0,0,2),Quaternion.identity,Vector3.one);
        ((Dictionary<string,GameObject>)Get(f.Host,"objects"))[B]=other;f.Drawing.Session.Objects[B]=new JObject{["id"]=B,["generation"]=4};Physics.SyncTransforms();
        Check(f.Host.PickObject(ray,out var blockerDepth)==view,"nearer object is an actual native-view collider");
        f.Preview.RouteControllerHand(UnityEngine.XR.XRNode.RightHand,ray,true,false,Vector2.zero,blockerDepth,out _,false);
        Check(Get(live,"translationGestureFrame")==null&&((WorkspaceObjectView)Get(live,"picked")).ObjectId==B,"nearer independent geometry receives ordinary body selection and never the hidden selected object's arrow");
    }
    static void ScaleFormat()
    {
        Check(LiveScaleFeedback.Format(Vector3.one*1.25f).Contains("×1.25")&&LiveScaleFeedback.Format(Vector3.one*1.25f).Contains("larger"),"unitless enlarged multiplier is explicit");
        Check(LiveScaleFeedback.Format(Vector3.one*.8f).Contains("×0.80")&&LiveScaleFeedback.Format(Vector3.one*.8f).Contains("smaller"),"shrinking multiplier remains visible");
        Check(LiveScaleFeedback.Format(new Vector3(1.2f,1,.7f)).Contains("X ×1.20")&&LiveScaleFeedback.Format(new Vector3(1.2f,1,.7f)).Contains("Z ×0.70"),"native axes have separate multipliers");
    }
    static void ScaleAcknowledgments()
    {
        foreach(bool constrained in new[]{false,true})
        {
            using var f=new DirectModelEditingChecks.Fixture("builtin.scale");Native(f,"object.scale");
            var model=(JObject)f.Drawing.NativeState["model_edit"];if(constrained)model["settings"]["constraint_axis"]=new JArray(true,false,false);
            f.Route(true);var live=(DirectLiveController)Get(f.Direct,"live");var feedback=(LiveScaleFeedback)Get(live,"scaleFeedback");
            Check(feedback.Visible&&feedback.Label.Contains("×1.00")&&!feedback.Acknowledged,"gesture starts at neutral multiplier while waiting for actual Blender acknowledgement");
            f.Route(true,.05f);Grant(f);var first=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");
            Check(!feedback.Acknowledged&&feedback.Factors==Vector3.one,"queued/in-flight intent is not presented as native-applied scale");
            Set(live,"nextUpdate",float.NegativeInfinity);f.Route(true,.1f);
            State(f,"updated",1,(string)first["id"]);
            var accepted=(JArray)first["payload"]["parameters"]["scale"];
            Check(feedback.Acknowledged&&Mathf.Abs(feedback.Factors.x-(float)accepted[0])<.000001f,"native ACK publishes the actual cumulative accepted factor, not newer queued intent");
            if(constrained)Check(feedback.Factors.y==1&&feedback.Factors.z==1&&feedback.Label.Contains("Y ×1.00"),"native constrained scale feedback leaves unaffected axes at exactly one");
            var clone=live.Session.AcknowledgedParameters;clone["scale"][0]=999;
            Check((float)live.Session.AcknowledgedParameters["scale"][0]!=999,"read-only acknowledged parameters cannot mutate session input or a receipt");
            f.Preview.CancelDirectModelDraft("test cancel");Check(!feedback.Visible&&feedback.Factors==Vector3.one,"Cancel hides feedback and resets its factor");
            var pending=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");State(f,"updated",2,(string)pending["id"]);
            Check(!feedback.Visible&&feedback.Label=="","late update acknowledgement cannot revive cancelled scale feedback");
        }
    }
    static void ScaleCommitAndSelection()
    {
        using(var f=new DirectModelEditingChecks.Fixture("builtin.scale"))
        {
            Native(f,"object.scale");f.Route(true);f.Route(true,-.05f);Grant(f);
            var live=(DirectLiveController)Get(f.Direct,"live");var feedback=(LiveScaleFeedback)Get(live,"scaleFeedback");var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");
            State(f,"updated",1,(string)update["id"]);Check(feedback.Factors.x<1&&feedback.Label.Contains("smaller"),"actual controller shrink ACK reports its accepted smaller factor");
            f.Route(false,-.05f);var commit=f.Sent.Last(m=>(string)m["type"]=="live.edit.commit");State(f,"committed",1,(string)commit["id"]);
            Check(!feedback.Visible&&feedback.Factors==Vector3.one,"commit receipt hides and resets multiplier");
        }
        using(var f=new DirectModelEditingChecks.Fixture("builtin.scale"))
        {
            Native(f,"object.scale");f.Route(true);f.Route(false);
            var live=(DirectLiveController)Get(f.Direct,"live");var feedback=(LiveScaleFeedback)Get(live,"scaleFeedback");
            Check(!feedback.Visible&&!f.Sent.Any(m=>(string)m["type"]=="live.edit.update"),"selection-only tap does not leave scaling feedback or alter geometry");
        }
    }
    static void DisplayScale()
    {
        using var feedback=new LiveScaleFeedback();
        var original=new Vector3(-2,.001f,3);
        var current=original*1.75f;
        var factors=WorkspaceInteraction.DisplayScaleFactors(current,original);
        Check((factors-Vector3.one*1.75f).sqrMagnitude<1e-10f,"display feedback reads actual cumulative pair scale across negative/nonuniform/unit-scaled baselines");
        feedback.ShowDisplayScale(factors);
        Check(feedback.Label.Contains("Display scale ×1.75")&&feedback.Label.Contains("VR view only")&&!feedback.Label.Contains("Blender applied"),"two-hand arrangement feedback explicitly distinguishes display resizing from native model editing");
        var rebased=current*.8f;feedback.ShowDisplayScale(WorkspaceInteraction.DisplayScaleFactors(rebased,original));
        Check(feedback.Label.Contains("×1.40"),"rebase does not reset the user's cumulative grab-start multiplier");
        feedback.Hide();Check(!feedback.Visible&&feedback.Factors==Vector3.one,"ending the pair hides and resets display feedback");
    }
    static void ScaleMultiTarget()
    {
        using var f=new DirectModelEditingChecks.Fixture("builtin.scale");Native(f,"object.scale");
        var other=new GameObject("Second scale target",typeof(MeshFilter),typeof(MeshCollider),typeof(WorkspaceObjectView));other.transform.SetParent(f.View.transform.parent,false);
        var mesh=f.View.GetComponent<MeshFilter>().sharedMesh;other.GetComponent<MeshFilter>().sharedMesh=mesh;other.GetComponent<MeshCollider>().sharedMesh=mesh;
        var view=other.GetComponent<WorkspaceObjectView>();view.ObjectId=B;view.Generation=4;view.SetNativePose(new Vector3(.6f,0,0),Quaternion.identity,Vector3.one);
        ((Dictionary<string,GameObject>)Get(f.Host,"objects"))[B]=other;f.Drawing.Session.Objects[B]=new JObject{["id"]=B,["generation"]=4};
        var model=(JObject)f.Drawing.NativeState["model_edit"];((JArray)model["selection"]["objects"]).Add(new JObject{["id"]=B,["generation"]=4});
        Call(f.Direct,"Update");Physics.SyncTransforms();f.Route(true);f.Route(true,.05f);Grant(f);
        var live=(DirectLiveController)Get(f.Direct,"live");var feedback=(LiveScaleFeedback)Get(live,"scaleFeedback");var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");
        var parameters=(JObject)update["payload"]["parameters"];var branches=(JObject)parameters["per_target"];
        Check(branches.Properties().Count()==2&&JToken.DeepEquals(branches[A]["scale"],branches[B]["scale"]),"multi-selection keeps the same cumulative scale factor for both native branches");
        State(f,"updated",1,(string)update["id"]);
        Check(Mathf.Abs(feedback.Factors.x-(float)branches[B]["scale"][0])<.000001f,"one multiplier describes the actual shared accepted factor for every target");
    }
}

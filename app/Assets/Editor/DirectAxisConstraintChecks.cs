using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR;

// Actual controller route, real selected colliders and outgoing typed live
// payloads. No native process/input, API service or interactive runtime.
public static class DirectAxisConstraintChecks
{
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static void Check(bool value,string why){if(!value)throw new Exception("DIRECT_AXIS_CONSTRAINT: "+why);}
    static object Get(object value,string field)=>value.GetType().GetField(field,Private).GetValue(value);
    static void Set(object value,string field,object data)=>value.GetType().GetField(field,Private).SetValue(value,data);
    static object Call(object value,string method,params object[] args)=>value.GetType().GetMethod(method,Private).Invoke(value,args);
    static void Native(DirectModelEditingChecks.Fixture f)=>typeof(LiveControllerChecks).GetMethod("NativeLive",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{f,"object.translate"});
    static void Grant(DirectModelEditingChecks.Fixture f)=>typeof(LiveControllerChecks).GetMethod("GrantAndBegin",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{f});
    static void State(DirectModelEditingChecks.Fixture f,string phase,long sequence,string re)=>typeof(LiveControllerChecks).GetMethod("State",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{f,phase,sequence,re});
    static DirectLiveController Live(DirectModelEditingChecks.Fixture f)=>(DirectLiveController)Get(f.Direct,"live");
    static DirectTranslationHandles.Frame Frame(DirectModelEditingChecks.Fixture f)=>(DirectTranslationHandles.Frame)Call(Live(f),"TranslationFrame",f.View);
    static bool Route(DirectModelEditingChecks.Fixture f,Ray ray,bool down,float nearest=4)=>f.Preview.RouteControllerHand(XRNode.RightHand,ray,down,false,Vector2.zero,nearest,out _,false);
    static void Prepare(DirectModelEditingChecks.Fixture f)
    {Native(f);f.Drawing.NativeState["model_edit"]["settings"]["pivot_m"]=new JArray(0,2,0);Call(f.Direct,"Update");Physics.SyncTransforms();}
    static void Constraint(DirectLiveController live,int axis,string why)
    {
        var actual=(bool[])Get(live,"gizmoConstraint");
        Check(actual!=null&&actual.Length==3&&Enumerable.Range(0,3).All(i=>actual[i]==(i==axis)),
            why+" expected_axis="+axis+" captured="+(actual==null?"body":string.Concat(actual.Select(value=>value?"1":"0"))));
    }
    static void Locked(JObject update,Vector3 expected,string why)
    {
        var delta=DirectModelEditMath.ToUnity((JArray)update["payload"]["parameters"]["translation_m"]);
        Check(delta.sqrMagnitude>1e-9f&&Vector3.Cross(delta.normalized,expected.normalized).magnitude<.00003f,why+" delta="+delta+" axis="+expected);
    }
    public static void Run()
    {
        foreach(int layout in new[]{0,1,2})foreach(int axis in new[]{0,1,2})ThickMeshAndOffAxis(layout,axis);
        foreach(int axis in new[]{0,1,2})foreach(bool push in new[]{false,true})EndOnCapture(axis,push);
        ArrowPlaneOverlap();BodyFreeAndPlane();UiFence();
        Debug.Log("DIRECT_AXIS_CONSTRAINT_CHECK PASS actual thick-own-mesh XYZ arrows; strict rendered-cone+shaft nearparallel XYZ+controller-origin axial push; handle taps no lease/geometry; oblique/plane-overlap arbitration; large off-axis typed native payloads; reflected nonuniform+sheared affine display; immutable capture through visual query/native ACK+one commit; clear free body+plane selection preserved; nearer UI fence; physical acceptance pending");
    }
    static void EndOnCapture(int axis,bool push)
    {
        using var f=new DirectModelEditingChecks.Fixture("builtin.move");SurfaceScaleChecks.SetBox(f.View,new Vector3(0,0,2),Vector3.one*1.2f);Prepare(f);
        var live=Live(f);var frame=Frame(f);var direction=frame.Axis(axis);
        var side=Vector3.Cross(direction,Mathf.Abs(Vector3.Dot(direction,Vector3.up))<.8f?Vector3.up:Vector3.right).normalized;
        var transverse=Vector3.Cross(direction,side).normalized;
        var origin=push?frame.Start(axis)-direction*.35f+side*.0005f+transverse*.00023f:frame.Tip(axis)+direction*.8f+side*.001f+transverse*.00037f;
        var first=new Ray(origin,push?direction:-direction);
        string context="end-on axis="+axis+" push="+push;
        bool hitPresent=DirectTranslationHandles.TryPick(frame,first,4,out var hit);
        Check(Mathf.Abs(Vector3.Dot(first.direction,direction))>.999f&&hitPresent&&hit.Axis==axis,context+": strict real cone/shaft is pickable near parallel from either direction");
        Check(!DirectTranslationHandles.TryPick(frame,first,hit.Distance-.001f,out _),context+": a nearer foreign UI fence still blocks actual geometry");
        var miss=new Ray(frame.Tip(axis)+direction*.8f+(side+transverse)*.06f,-direction);
        Check(!DirectTranslationHandles.TryPick(frame,miss,4,out _),context+": nearparallel body outside actual cone/shaft is not a broad catchall");
        // Workspace supplies the nearest actual collider, not just its range
        // limit. The own-mesh exception deliberately requires that proof so a
        // nearer independent surface cannot be mistaken for the selected mesh.
        var mesh=f.Host.PickObject(first,out float meshDepth);
        float nearest=mesh!=null?Mathf.Min(4,meshDepth):4;
        Debug.Log("DIRECT_AXIS_CASE "+context+" picker_axis="+hit.Axis+" picker_depth="+hit.Distance+" mesh="+(mesh==null?"none":mesh.ObjectId)+" mesh_depth="+meshDepth+" input_fence="+nearest);
        Check(Route(f,first,true,nearest)&&f.Direct.Gesturing,context+": actual controller press captures arrow");Constraint(live,axis,context+": constraint is frozen on the real hit");
        Route(f,first,false,nearest);
        Check(f.Sent.Count==0&&!f.Direct.Gesturing,context+": handle tap sends no geometry/lease and cannot toggle selection");
        Check(Route(f,first,true,nearest),context+": deliberate new press reacquires same axis");
        var moved=new Ray(origin+direction*.12f+side*.8f+transverse*.55f,first.direction);
        Route(f,moved,true);Grant(f);
        var begin=f.Sent.Last(message=>(string)message["type"]=="live.edit.begin");var flags=(JArray)begin["payload"]["operation"]["settings"]["constraint_axis"];
        Check(Enumerable.Range(0,3).All(i=>(bool)flags[i]==(i==axis)),"end-on press sends actual single native XYZ constraint");
        var update=f.Sent.Last(message=>(string)message["type"]=="live.edit.update");
        Locked(update,f.View.NativeToDisplayMatrix.inverse.MultiplyVector(direction),"axial controller-origin push with large sideways motion remains locked to captured native axis");
        f.Preview.CancelDirectModelDraft("fixture cleanup");
    }
    static void ThickMeshAndOffAxis(int layout,int axis)
    {
        using var f=new DirectModelEditingChecks.Fixture("builtin.move");
        if(layout>0)
        {
            f.View.transform.parent.localScale=new Vector3(-1.7f,.8f,1.3f);
            f.View.transform.parent.rotation=Quaternion.Euler(17,34,-13);
            if(layout==2)f.View.RestoreArrangement(Vector3.zero,Quaternion.Euler(27,-19,11));
        }
        SurfaceScaleChecks.SetBox(f.View,new Vector3(0,0,2),Vector3.one*1.2f);Prepare(f);
        var live=Live(f);var frame=Frame(f);var axisDirection=frame.Axis(axis);
        var side=Vector3.Cross(axisDirection,Mathf.Abs(Vector3.Dot(axisDirection,Vector3.up))<.8f?Vector3.up:Vector3.right).normalized;
        var origin=frame.Tip(axis)+side*2.8f-axisDirection*.2f;
        var first=new Ray(origin,frame.Tip(axis)-origin);
        Check(f.Host.PickObject(first,out float meshDepth)==f.View,"selected thick native mesh is genuinely the first collider");
        Check(DirectTranslationHandles.TryPick(frame,first,4,out var expected)&&expected.Axis==axis,"ray genuinely aims at rendered XYZ arrow");
        if(layout==0)
            Check(expected.Distance>meshDepth+.35f&&!DirectTranslationHandles.TryPick(frame,first,meshDepth+.35f,out _),"repro: previous 35cm own-mesh allowance cannot reach visible arrow");
        Check(Route(f,first,true,meshDepth)&&f.Direct.Gesturing,"actual input route captures arrow over its own thick mesh");
        Constraint(live,axis,"captured one-axis constraint cannot silently become free body movement");
        var captured=Get(live,"translationGestureFrame");var capturedAxis=(int)Get(live,"translationAxis");
        var another=new Ray(frame.Tip((axis+1)%3)+side*.8f,-side);
        live.TryVisualAim(another,out _);
        Check(ReferenceEquals(captured,Get(live,"translationGestureFrame"))&&(int)Get(live,"translationAxis")==capturedAxis,"other-hand visual query cannot overwrite held capture/highlight");
        float depth=(float)Get(live,"depth");var transverse=Vector3.Cross(axisDirection,side).normalized;
        var moved=new Ray(origin,first.GetPoint(depth)+axisDirection*.3f+side*.9f+transverse*.6f-origin);
        Route(f,moved,true);Grant(f);
        var begin=f.Sent.Last(m=>(string)m["type"]=="live.edit.begin");var flags=(JArray)begin["payload"]["operation"]["settings"]["constraint_axis"];
        Check(Enumerable.Range(0,3).All(i=>(bool)flags[i]==(i==axis)),"actual native begin receives frozen selected XYZ axis");
        var map=f.View.NativeToDisplayMatrix;var nativeAxis=map.inverse.MultiplyVector(axisDirection).normalized;
        var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");Locked(update,nativeAxis,"large off-axis controller motion still emits only grabbed native axis");
        var baseline=f.View.NativePosition;
        Check(f.View.AcceptLiveEcho(new JObject { ["id"]=live.Session.EditSessionId,["actor_id"]="actor",["sequence"]=1,["phase"]="updated" },"actor"),"actual own preview echo is admitted");
        f.View.SetNativePose(baseline+DirectModelEditMath.ToUnity((JArray)update["payload"]["parameters"]["translation_m"]),f.View.NativeRotation,f.View.NativeScale);
        f.View.Generation=4;f.Drawing.Session.Objects[f.View.ObjectId]["generation"]=4;
        State(f,"updated",1,(string)update["id"]);
        // A real controller tick also refreshes the live lease. A keepalive
        // repeats the acknowledged sequence; it is not the next user preview.
        // Exercise that in-flight request rather than accidentally ACKing it as
        // the subsequent controller movement and skipping the actual update.
        f.Drawing.NativeState["model_edit"]["settings"]["pivot_m"]=new JArray(7,8,9);
        Set(live,"nextKeepAlive",float.NegativeInfinity);Call(f.Direct,"Update");
        var keepalive=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");
        Check((string)keepalive["id"]!=(string)update["id"]&&(long)keepalive["payload"]["sequence"]==1
            &&JToken.DeepEquals(keepalive["payload"]["parameters"],update["payload"]["parameters"]),
            "native keepalive repeats the acknowledged preview without advancing its sequence");
        live.TryVisualAim(another,out _);Constraint(live,axis,"own ACK/pivot telemetry preserves captured axis");
        Check(ReferenceEquals(captured,Get(live,"translationGestureFrame"))&&(int)Get(live,"translationAxis")==capturedAxis,"ACK and hover cannot rebase held arrow");
        var second=new Ray(origin,first.GetPoint(depth)+axisDirection*.45f-side*.8f+transverse*1.1f-origin);
        Set(live,"nextUpdate",float.NegativeInfinity);Route(f,second,true);
        Check((string)f.Sent.Last(m=>(string)m["type"]=="live.edit.update")["id"]==(string)keepalive["id"],
            "controller preview waits behind the in-flight native keepalive");
        State(f,"updated",1,(string)keepalive["id"]);
        var next=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");Locked(next,nativeAxis,"later controller movement remains locked after native ACK");
        Check((string)next["id"]!=(string)keepalive["id"]&&(long)next["payload"]["sequence"]==2
            &&!JToken.DeepEquals(next["payload"]["parameters"],update["payload"]["parameters"]),
            "keepalive ACK releases the distinct cumulative controller preview at the next sequence");
        Check(f.View.AcceptLiveEcho(new JObject { ["id"]=live.Session.EditSessionId,["actor_id"]="actor",["sequence"]=2,["phase"]="updated" },"actor"),"second own preview echo is admitted");
        f.View.SetNativePose(baseline+DirectModelEditMath.ToUnity((JArray)next["payload"]["parameters"]["translation_m"]),f.View.NativeRotation,f.View.NativeScale);
        f.View.Generation=5;f.Drawing.Session.Objects[f.View.ObjectId]["generation"]=5;State(f,"updated",2,(string)next["id"]);
        Route(f,second,false);var commit=f.Sent.Last(m=>(string)m["type"]=="live.edit.commit");State(f,"committed",2,(string)commit["id"]);
        Check(f.Sent.Count(m=>(string)m["type"]=="live.edit.commit")==1&&!f.Drawing.Session.ExternalEditBusy,"one gesture retains one acknowledged history commit and releases writer");
    }
    static void ArrowPlaneOverlap()
    {
        using var f=new DirectModelEditingChecks.Fixture("builtin.move");Prepare(f);var frame=Frame(f);
        var square=frame.Pivot+frame.Axis(1)*.04f+frame.Axis(2)*.04f;
        var point=frame.Pivot+frame.Axis(0)*.12f;var direction=(point-square).normalized;var first=new Ray(square-direction*.6f,direction);
        Check(DirectTranslationHandles.TryPick(frame,first,4,out var arrow)&&arrow.Axis==0,"oblique overlap ray really picks X shaft");
        var plane=new Plane(frame.Axis(0),frame.Pivot);Check(plane.Raycast(first,out float planeDepth)&&planeDepth<arrow.Distance,"same ray crosses another plane square before the visible arrow");
        Check(Route(f,first,true),"actual overlapping controller ray routes");Constraint(Live(f),0,"visible X arrow wins over intersected YZ plane square");
        Check(Get(Live(f),"translationGestureFrame")!=null&&Get(Live(f),"gizmoPlaneNormal")==null,"overlap cannot silently replace arrow capture with a plane");
    }
    static void BodyFreeAndPlane()
    {
        using(var f=new DirectModelEditingChecks.Fixture("builtin.move"))
        {
            Prepare(f);var first=new Ray(Vector3.zero,new Vector3(-.12f,-.12f,2));Route(f,first,true);var live=Live(f);
            Check(Get(live,"gizmoConstraint")==null&&Get(live,"translationGestureFrame")==null,"clear body area outside visible handles keeps free movement");
            Route(f,new Ray(Vector3.zero,new Vector3(-.03f,-.02f,2)),true);Grant(f);
            var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");var value=(JArray)update["payload"]["parameters"]["translation_m"];
            Check(Mathf.Abs((float)value[0])>.01f&&Mathf.Abs((float)value[2])>.01f,"body movement retains two unconstrained native coordinates");
            f.Preview.CancelDirectModelDraft("fixture cleanup");
        }
        using(var f=new DirectModelEditingChecks.Fixture("builtin.move"))
        {
            Prepare(f);Route(f,new Ray(Vector3.zero,new Vector3(.04f,.04f,2)),true);
            var flags=(bool[])Get(Live(f),"gizmoConstraint");Check(flags!=null&&flags.Count(value=>value)==2&&Get(Live(f),"translationGestureFrame")==null,"a deliberate plane square away from arrows retains its two axes");
        }
    }
    static void UiFence()
    {
        using var f=new DirectModelEditingChecks.Fixture("builtin.move");SurfaceScaleChecks.SetBox(f.View,new Vector3(0,0,2),Vector3.one*1.2f);Prepare(f);var frame=Frame(f);
        var first=new Ray(frame.Tip(0)+Vector3.up*2.8f-Vector3.right*.2f,Vector3.down*2.8f+Vector3.right*.2f);
        bool arrowHit=DirectTranslationHandles.TryPick(frame,first,4,out var arrow);
        Check(f.Host.PickObject(first,out float meshDepth)==f.View&&arrowHit,"UI fence fixture has own mesh and visible arrow");
        var canvas=new GameObject("Independent preview UI fence",typeof(RectTransform),typeof(Canvas));canvas.transform.SetPositionAndRotation(first.GetPoint((meshDepth+arrow.Distance)*.5f),Quaternion.LookRotation(first.direction));canvas.transform.localScale=Vector3.one*.001f;
        try
        {
            var button=GlassTheme.Action(canvas.transform,"Actual preview control",Vector2.zero,new Vector2(400,400),()=>{});
            ((List<Button>)Get(f.Preview,"buttons")).Add(button);
            Check(f.Preview.RaycastUiOnly(first,out float uiDepth)&&uiDepth>meshDepth&&uiDepth<arrow.Distance,"actual UI-only query detects independent control between selected mesh front and arrow");
            var before=f.Direct.SelectionSnapshot.ToString();int messages=f.Sent.Count;
            f.Preview.RaycastUiOnly(first,out _);Check(before==f.Direct.SelectionSnapshot.ToString()&&messages==f.Sent.Count,"UI fence query is read-only");
            Route(f,first,true,meshDepth);Check(Get(Live(f),"translationGestureFrame")==null,"own mesh exception cannot cross independent UI control to grab an arrow");
        }
        finally{UnityEngine.Object.DestroyImmediate(canvas);}
    }
}

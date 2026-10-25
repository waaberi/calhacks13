using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEngine;

public static class LiveControllerChecks
{
    const string A="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",B="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    static readonly BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static void Check(bool value,string why){if(!value)throw new Exception("LIVE_CONTROLLER: "+why);}
    static object Get(object target,string field)=>target.GetType().GetField(field,Private).GetValue(target);
    static void Set(object target,string field,object value)=>target.GetType().GetField(field,Private).SetValue(target,value);
    static void Invoke(object target,string method)=>target.GetType().GetMethod(method,Private).Invoke(target,null);
    static void MatrixNear(Matrix4x4 a,Matrix4x4 b,string why)
    {for(int i=0;i<16;i++)Check(Mathf.Abs(a[i]-b[i])<.00005f,why+" element "+i);}
    public static void Run()
    {
        Selection();Presentation();GestureMath();LiveRoute();SelectionSync();ToolGestures();SelectionAndCancellation();SelectionOutlineBound();
        Debug.Log("LIVE_CONTROLLER_CHECK PASS actual held native-update route/one commit/cancel/selection-only no-geometry/SHIFT multi-selection+input-off/epoch/native Inset+Bevel+LoopCut+surface Knife/native axis handle+settings cancellation/own-echo identity+sequence/affine M0 mirrored nonuniform live+commit+reset+restore; physical acceptance pending");
    }
    public static void Selection()
    {
        var selection=new NativeSpatialSelection();long epoch=selection.Epoch;
        selection.Pick(A,3,"object",-1,"a",false);Check(selection.ObjectIds.SequenceEqual(new[]{A}),"trigger selects without geometry");
        selection.SetAdditive(true);selection.Pick(B,4,"object",-1,"b",false);
        Check(selection.ObjectIds.SequenceEqual(new[]{A,B}),"sticky SHIFT adds the second native target");
        selection.Pick(A,3,"object",-1,"a",false);Check(selection.ObjectIds.SequenceEqual(new[]{B}),"SHIFT tap removes a selected target");
        selection.Pick(B,4,"object",-1,"b",true);Check(selection.ObjectIds.SequenceEqual(new[]{B}),"drag on selected member preserves entire set");
        selection.SetAdditive(false);selection.Pick(A,3,"face",5,"topology",false);
        selection.SetAdditive(true);selection.Pick(A,3,"face",8,"topology",false);
        Check(selection.Indices.SequenceEqual(new[]{5,8}),"native face selection keeps ordered picks for FIRST/LAST operations");
        selection.Pick(A,3,"face",5,"topology",false);Check(selection.Indices.SequenceEqual(new[]{8}),"component toggle removes exactly one face");
        var snapshot=selection.Snapshot();snapshot["indices"][0]=999;
        Check(selection.Indices[0]==8&&selection.Epoch>epoch,"snapshot is detached and context epoch records transient intent");
        long before=selection.Epoch;selection.InvalidateIntent();selection.InvalidateIntent();Check(selection.Epoch==before+2,"AI reply becomes stale after gesture begin/end even when final selection matches");
    }
    static void Presentation()
    {
        var root=new GameObject("Frozen live map fixture root");var obj=new GameObject("Native live model",typeof(WorkspaceObjectView));
        try
        {
            root.transform.SetPositionAndRotation(new Vector3(2,1,-3),Quaternion.Euler(17,52,-9));root.transform.localScale=new Vector3(1.7f,.8f,2.1f);
            obj.transform.SetParent(root.transform,false);var view=obj.GetComponent<WorkspaceObjectView>();
            view.SetNativePose(new Vector3(.2f,.1f,-.3f),Quaternion.Euler(12,-38,21),new Vector3(-2,.3f,1.2f));
            view.RestoreArrangement(new Vector3(.4f,-.1f,.2f),Quaternion.Euler(-16,91,29));
            obj.transform.localScale=Vector3.Scale(view.NativeScale,new Vector3(-.7f,2.3f,.4f));view.RememberArrangement();
            var baseline=obj.transform.localToWorldMatrix;var map=view.NativeToDisplayMatrix;
            view.BeginLivePresentation("edit","actor");MatrixNear(obj.transform.localToWorldMatrix,baseline,"begin has no display jump even with mirrored/nonuniform inspection and parent shear");
            var nextPosition=new Vector3(.25f,-.04f,.17f);var nextRotation=Quaternion.Euler(31,57,-18);var nextScale=new Vector3(-.8f,1.6f,.2f);
            Check(view.AcceptLiveEcho(Tag("edit",1,"updated"),"actor"),"own tagged sequence admitted");
            view.SetNativePose(nextPosition,nextRotation,nextScale);
            MatrixNear(obj.transform.localToWorldMatrix,map*Matrix4x4.TRS(nextPosition,nextRotation,nextScale),"actual live renderer is M0 times new native world pose, not a local-only ghost");
            Check(!view.AcceptLiveEcho(Tag("edit",0,"updated"),"actor"),"out-of-order own echo cannot regress geometry");
            view.EndLivePresentation("edit",true);view.EndLivePresentation("edit",true);
            Check(view.LivePresentationRebases==1,"duplicate native receipts rebase viewer arrangement once only");
            MatrixNear(obj.transform.localToWorldMatrix,map*Matrix4x4.TRS(nextPosition,nextRotation,nextScale),"commit retains exact live position and orientation");
            var saved=view.CaptureArrangementState();view.ResetArrangement();
            MatrixNear(obj.transform.localToWorldMatrix,root.transform.localToWorldMatrix*Matrix4x4.TRS(nextPosition,nextRotation,nextScale),"Reset View uses current native state");
            view.RestoreArrangementState(saved);
            MatrixNear(obj.transform.localToWorldMatrix,map*Matrix4x4.TRS(nextPosition,nextRotation,nextScale),"placement Undo restores affine inspector state without changing Blender");
            view.BeginLivePresentation("next","actor");
            var wrong=Tag("next",1,"updated");wrong["actor_id"]="other";
            Check(!view.AcceptLiveEcho(wrong,"actor")&&view.LivePresentationConflict,"same edit ID from another actor never becomes an own live update");
            view.EndLivePresentation("next",false);
        }
        finally{UnityEngine.Object.DestroyImmediate(obj);UnityEngine.Object.DestroyImmediate(root);}
    }
    static JObject Tag(string id,long sequence,string phase)=>new JObject { ["id"]=id,["actor_id"]="actor",["sequence"]=sequence,["phase"]=phase };
    static void GestureMath()
    {
        var map=Matrix4x4.TRS(new Vector3(3,1,-2),Quaternion.Euler(33,90,-11),new Vector3(-2,.3f,1.7f));
        var display=map.MultiplyVector(Vector3.right*.02f);var aim=Quaternion.LookRotation(Vector3.forward)*Vector3.forward;
        float expected=.02f*Vector3.Dot(display.normalized,Vector3.right+Vector3.up);
        Check(Mathf.Abs(DirectLiveController.MetricDrag(map,display,aim)-expected)<.00001f,"Inset/Bevel native metric amount does not project a native vector onto unrelated display axes");
        Check(Vector3.Distance(DirectLiveController.PerpendicularPoint(Vector3.zero,Vector3.right,new Vector3(.3f,2,4)),new Vector3(.3f,0,0))<.00001f,"edge perpendicular snap projects native selection origin onto the true native edge");
        Check(DirectLiveController.PerpendicularPoint(Vector3.zero,Vector3.right,new Vector3(2,2,0))==Vector3.right,"perpendicular target is clamped to finite native segment");
    }
    static void NativeLive(DirectModelEditingChecks.Fixture f,string tool="object.translate")
    {
        var model=(JObject)f.Drawing.NativeState["model_edit"];model["live_supported"]=true;model["tool"]=tool;
        model["settings"]=new JObject { ["orientation"]="GLOBAL",["constraint_axis"]=new JArray(false,false,false) };
        string component=(string)model["component"];
        model["selection"]=new JObject { ["objects"]=new JArray(new JObject{["id"]=A,["generation"]=3}),["active_id"]=A,["component"]=component,
            ["indices"]=component=="object"?new JArray():new JArray(component=="face"?20:component=="edge"?10:0) };
        Invoke(f.Direct,"Update");
    }
    static void State(DirectModelEditingChecks.Fixture f,string phase,long sequence,string re)
    {
        var p=f.Drawing.Session.RequestIdentity;p["edit_session_id"]="live-edit";p["phase"]=phase;p["sequence"]=sequence;p["notice"]="Native "+phase;
        p["revision"]=7+sequence;p["generations"]=new JObject { [A]=3+sequence };
        p["selection"]=new JObject { ["id"]=A,["objects"]=new JArray(A),["component"]="object",["indices"]=new JArray() };
        var begin=f.Sent.LastOrDefault(m=>(string)m["type"]=="live.edit.begin");
        if((bool?)begin?["payload"]?["operation"]?["selection_only"]==true)
        {
            var selection=(JObject)begin["payload"]["operation"]["selection"].DeepClone();
            selection["id"]=selection["active_id"]?.DeepClone()??"";p["selection"]=selection;p["generations"]=new JObject{[A]=3};
        }
        f.Receive("live.edit.state",p,re);
    }
    static void GrantAndBegin(DirectModelEditingChecks.Fixture f)
    {
        var lease=f.Sent.Last(m=>(string)m["type"]=="lease.acquire");
        f.Receive("lease.granted",new JObject { ["lease"]=new JObject { ["lease_id"]="live-lease" } },(string)lease["id"]);
        var begin=f.Sent.Last(m=>(string)m["type"]=="live.edit.begin");State(f,"active",0,(string)begin["id"]);
    }
    static void LiveRoute()
    {
        foreach(bool cancel in new[]{false,true})
        {
            using var f=new DirectModelEditingChecks.Fixture();NativeLive(f);
            var initial=f.View.NativePosition;var map=f.View.NativeToDisplayMatrix;
            f.Route(true);f.Route(true,.05f);GrantAndBegin(f);
            var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");
            Check(update["payload"]["parameters"]["translation_m"] is JArray,"controller emits canonical typed native meter update while trigger remains held");
            var native=DirectModelEditMath.ToUnity((JArray)update["payload"]["parameters"]["translation_m"]);
            f.View.AcceptLiveEcho(Tag("live-edit",1,"updated"),"actor");f.View.SetNativePose(initial+native,f.View.NativeRotation,f.View.NativeScale);
            f.View.Generation=4;f.Drawing.Session.Objects[A]["generation"]=4;
            State(f,"updated",1,(string)update["id"]);
            Check(f.Direct.Gesturing&&f.View.NativePosition!=initial,"actual native geometry changes before release");
            MatrixNear(f.View.transform.localToWorldMatrix,map*Matrix4x4.TRS(f.View.NativePosition,f.View.NativeRotation,f.View.NativeScale),"live echo uses frozen mapping");
            if(cancel)
            {
                f.Preview.CancelDirectModelDraft("Escape");var rollback=f.Sent.Last(m=>(string)m["type"]=="live.edit.cancel");
                f.View.AcceptLiveEcho(Tag("live-edit",1,"cancelled"),"actor");f.View.SetNativePose(initial,f.View.NativeRotation,f.View.NativeScale);
                State(f,"cancelled",1,(string)rollback["id"]);f.Route(false,.05f);
                Check(f.View.NativePosition==initial&&!f.Sent.Any(m=>(string)m["type"]=="live.edit.commit"),"Escape restores baseline and no later release commits");
            }
            else
            {
                f.Route(false,.05f);var commit=f.Sent.Last(m=>(string)m["type"]=="live.edit.commit");State(f,"committed",1,(string)commit["id"]);
                Check(f.Sent.Count(m=>(string)m["type"]=="live.edit.commit")==1,"one completed gesture emits one native history commit");
            }
            Check(!f.Drawing.Session.ExternalEditBusy&&f.View.LivePresentationRebases==1,"terminal native acknowledgement releases writer and rebases once");
        }
    }
    static void SelectionSync()
    {
        using var f=new DirectModelEditingChecks.Fixture();NativeLive(f);f.Route(true);f.Route(false);
        Check(!f.Sent.Any(m=>(string)m["type"]=="live.edit.update"),"simple selection tap is not a geometry drag");
        Invoke(f.Direct,"Update");GrantAndBegin(f);
        var begin=f.Sent.Last(m=>(string)m["type"]=="live.edit.begin");var op=begin["payload"]["operation"];
        Check((bool?)op["selection_only"]==true&&(string)op["tool"]=="object.selection","explicit native selection sync is separately typed with no history step");
        var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");Check(!((JObject)update["payload"]["parameters"]).Properties().Any(),"selection sync never contains a transform");
        State(f,"updated",1,(string)update["id"]);var commit=f.Sent.Last(m=>(string)m["type"]=="live.edit.commit");State(f,"committed",1,(string)commit["id"]);
        Check(f.View.NativePosition==Vector3.zero,"selection alone leaves actual native transform unchanged");
    }
    static void ToolGestures()
    {
        foreach(string tool in new[]{"mesh.inset","mesh.bevel","mesh.loop_cut","mesh.knife"})
        {
            string native=tool=="mesh.inset"?"builtin.inset_faces":tool=="mesh.bevel"?"builtin.bevel":tool=="mesh.loop_cut"?"builtin.loop_cut":"builtin.knife";
            using var f=new DirectModelEditingChecks.Fixture(native,"EDIT_MESH");var model=(JObject)f.Drawing.NativeState["model_edit"];
            if(tool=="mesh.loop_cut")model["component"]="edge";
            if(tool=="mesh.knife")model["component"]="vertex";
            NativeLive(f,tool);var settings=(JObject)model["settings"];settings["segments"]=3;settings["cuts"]=2;
            bool Route(bool trigger,float x)
            {
                var ray=tool=="mesh.loop_cut"?new Ray(Vector3.zero,new Vector3(x,-.2f,2).normalized):f.Ray(x);
                return f.Preview.RouteControllerHand(UnityEngine.XR.XRNode.RightHand,ray,trigger,false,Vector2.zero,4,out _,false);
            }
            Check(Route(true,0),"actual floating-model controller route starts "+tool);Route(true,.05f);GrantAndBegin(f);
            var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");var parameters=(JObject)update["payload"]["parameters"];
            if(tool=="mesh.inset")Check((float)parameters["thickness_m"]>0,"Inset emits native metric thickness");
            if(tool=="mesh.bevel")Check((float)parameters["width_m"]>0&&(int)parameters["segments"]==3,"Bevel preserves native segment settings");
            if(tool=="mesh.loop_cut")Check((int)parameters["cuts"]==2&&Mathf.Abs((float)parameters["slide"])>.01f,"Loop Cut emits native picked-ring cuts and slide");
            if(tool=="mesh.knife")Check(((JArray)parameters["path_m"]).Count>=2&&((JArray)parameters["projection"]).Count==16,"Knife starts on a face interior in vertex mode and sends surface path with frozen projection");
            f.Preview.CancelDirectModelDraft("test cleanup");
        }
        using(var f=new DirectModelEditingChecks.Fixture("builtin.move","EDIT_MESH"))
        {
            NativeLive(f,"mesh.translate");var model=(JObject)f.Drawing.NativeState["model_edit"];
            model["settings"]["pivot_m"]=new JArray(.4,2,0);
            var ray=new Ray(Vector3.zero,new Vector3(.475f,0,2).normalized);
            Check(f.Direct.TryVisualAim(ray,out _),"native axis handle outside mesh has a stabilized visual endpoint");
            f.Preview.RouteControllerHand(UnityEngine.XR.XRNode.RightHand,ray,true,false,Vector2.zero,4,out _,false);
            Check(f.Direct.Gesturing,"native mesh axis handle reuses selected components without repicking empty space");
            var moved=new Ray(Vector3.zero,new Vector3(.525f,0,2).normalized);
            f.Preview.RouteControllerHand(UnityEngine.XR.XRNode.RightHand,moved,true,false,Vector2.zero,4,out _,false);GrantAndBegin(f);
            var begin=f.Sent.Last(m=>(string)m["type"]=="live.edit.begin");var constraint=(JArray)begin["payload"]["operation"]["settings"]["constraint_axis"];
            Check((bool)constraint[0]&&!(bool)constraint[1]&&!(bool)constraint[2],"native X constraint is frozen in actual typed operation");
        }
    }
    static void SelectionAndCancellation()
    {
        using(var f=new DirectModelEditingChecks.Fixture())
        {
            NativeLive(f);typeof(PreviewInteraction).GetMethod("Modifier",Private).Invoke(f.Preview,new object[]{"SHIFT"});
            Check(f.Direct.AdditiveSelection,"existing keyboard SHIFT controls spatial additive selection without native OS focus");
            Invoke(f.Preview,"DisableNativeInput");Check(f.Direct.Active&&f.Direct.AdditiveSelection,"manual Input OFF preserves explicit direct mode and sticky SHIFT intent");
            f.Preview.Suspend();Check(!f.Direct.Active&&!f.Direct.AdditiveSelection,"HMD/arrangement suspension releases spatial modifier intent");
        }
        using(var f=new DirectModelEditingChecks.Fixture())
        {
            NativeLive(f);f.Route(true);f.Route(true,.05f);GrantAndBegin(f);var model=(JObject)f.Drawing.NativeState["model_edit"];
            model["settings"]["pivot_m"]=new JArray(.1,0,0);model["settings"]["native_context_fingerprint"]="own-updated-native-mesh";Invoke(f.Direct,"Update");
            Check(!f.Sent.Any(m=>(string)m["type"]=="live.edit.cancel"),"own-derived native pivot/fingerprint telemetry does not cancel a frozen gesture");
            model["settings"]["orientation"]="LOCAL";Invoke(f.Direct,"Update");f.Route(false,.05f);
            Check(!f.Sent.Any(m=>(string)m["type"]=="live.edit.commit")&&!f.Direct.Gesturing,"native settings invalidate the gesture immediately while its update receipt is pending");
            var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");State(f,"updated",1,(string)update["id"]);
            Check(f.Sent.Count(m=>(string)m["type"]=="live.edit.cancel")==1&&!f.Sent.Any(m=>(string)m["type"]=="live.edit.commit"),"actual native tool-setting change cancels once and delayed release cannot commit");
            var rollback=f.Sent.Last(m=>(string)m["type"]=="live.edit.cancel");State(f,"cancelled",1,(string)rollback["id"]);f.Route(false,.05f);
            Check(!f.Drawing.Session.ExternalEditBusy&&!f.Sent.Any(m=>(string)m["type"]=="live.edit.commit"),"native cancellation receipt finishes cleanup without a replay");
        }
    }
    static void SelectionOutlineBound()
    {
        using var f=new DirectModelEditingChecks.Fixture("builtin.move","EDIT_MESH");var model=(JObject)f.Drawing.NativeState["model_edit"];model["component"]="vertex";
        NativeLive(f,"mesh.translate");var vertices=new JArray();var indices=new JArray();
        for(int index=0;index<600;index++){vertices.Add(new JObject { ["index"]=index,["position"]=new JArray(index*.001,2,0) });indices.Add(index);}
        model["vertices"]=vertices;model["selection"]["indices"]=indices;Invoke(f.Direct,"Update");
        var live=(DirectLiveController)Get(f.Direct,"live");var lines=(List<LineRenderer>)Get(live,"selectionLines");
        Check(lines.Count>0&&lines.Count<=DirectLiveController.MaximumSelectionSegments,"native Select All bounds allocated outline GameObjects");
        Check(live.Selection.Indices.Count==600&&((JArray)f.Direct.SelectionSnapshot["indices"]).Count==600&&live.Notice.Contains("600"),"outline sampling retains the complete actionable selection and full count feedback");
        model["selection"]["indices"]=new JArray(0,1);Invoke(f.Direct,"Update");
        Check(lines.Count(line=>line.gameObject.activeSelf)==6,"small selected vertex crosses remain exact after large selection reuse");
    }
}

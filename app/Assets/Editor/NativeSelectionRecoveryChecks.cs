using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using SpatialModeling;
#if !NATIVE_SELECTION_STANDALONE
using System.Reflection;
using UnityEngine;
#endif

public static class NativeSelectionRecoveryChecks
{
    const string A="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    static void Check(bool ok,string why){if(!ok)throw new Exception("NATIVE_SELECTION_RECOVERY: "+why);}
    public static void Run()
    {
        Parser();
#if NATIVE_SELECTION_STANDALONE
        Console.WriteLine("NATIVE_SELECTION_PARSER_CHECK PASS legacy-explicit-empty/stale-preview-recovery/pending-intent/unknown-state/not-active-invention");
#else
        RouteRecovery();
        Debug.Log("NATIVE_SELECTION_RECOVERY_CHECK PASS real-deselect-commit/stale-preview/fresh-legacy-empty/no-selection-drag-refused/tap-reselect/native-Scale-ACK+commit/no-auto-selection; physical acceptance pending");
#endif
    }
    static JObject Selected()=>new JObject{["mode"]="OBJECT",["active_object_id"]=A,["topology_token"]="selected",
        ["component"]="object",["selection"]=new JObject{["objects"]=new JArray(A),["active_id"]=A,["component"]="object",["indices"]=new JArray()}};
    static JObject NoActive()=>new JObject{["mode"]="OBJECT",["active_object_id"]="",["topology_token"]="",
        ["available"]=false,["live_supported"]=true,["tool"]="",["native_tool"]="builtin.scale",["component"]="object",["selection"]=new JObject()};
    static void Parser()
    {
        var selection=new NativeSpatialSelection();var objects=new Dictionary<string,JObject>{{A,new JObject{["id"]=A,["generation"]=17}}};
        selection.ObserveNative(Selected(),objects,true);selection.Pick(A,17,"object",-1,"selected",false);
        Check(selection.ObjectIds.Count==0,"deliberate sole-object tap still deselects");
        selection.ObserveNative(Selected(),objects,true);Check(selection.ObjectIds.Count==1,"reproduction admits delayed selected preview after deselect receipt");
        selection.ObserveNative(NoActive(),objects,true);
        Check(selection.ObjectIds.Count==0&&selection.ActiveId==""&&selection.Indices.Count==0,"fresh legacy explicit empty selection clears stale selected target");
        selection.Pick(A,17,"object",-1,"",false);Check(selection.ObjectIds.SequenceEqual(new[]{A}),"next deliberate tap selects rather than deselecting a stale target");
        selection.ObserveNative(NoActive(),objects,false);Check(selection.ObjectIds.Count==1,"unadmitted native state cannot erase pending local selection intent");
        var missing=NoActive();missing.Remove("selection");selection.ObserveNative(missing,objects,true);
        Check(selection.ObjectIds.Count==1,"omitted selection remains unknown rather than an inferred clear");
        var active=NoActive();active["active_object_id"]=A;selection.ObserveNative(active,objects,true);
        Check(selection.ObjectIds.Count==1,"empty partial selection with native active target does not imply no selection");
        selection.Pick(A,17,"face",20,"topology",false);selection.ObserveNative(NoActive(),objects,true);
        Check(selection.Component=="object"&&selection.Indices.Count==0&&selection.ActiveId=="","returning to explicit empty Object mode removes old component indices");
    }
#if NATIVE_SELECTION_STANDALONE
    public static void Main()=>Run();
#else
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static object Get(object value,string field)=>value.GetType().GetField(field,Private).GetValue(value);
    static object Call(object value,string method)=>value.GetType().GetMethod(method,Private).Invoke(value,null);
    static void Native(DirectModelEditingChecks.Fixture f)=>typeof(LiveControllerChecks).GetMethod("NativeLive",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{f,"object.scale"});
    static void Grant(DirectModelEditingChecks.Fixture f)=>typeof(LiveControllerChecks).GetMethod("GrantAndBegin",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{f});
    static void State(DirectModelEditingChecks.Fixture f,string phase,long sequence,string reply)=>typeof(LiveControllerChecks).GetMethod("State",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{f,phase,sequence,reply});
    static void FinishSelection(DirectModelEditingChecks.Fixture f)
    {
        Grant(f);var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");State(f,"updated",1,(string)update["id"]);
        var commit=f.Sent.Last(m=>(string)m["type"]=="live.edit.commit");State(f,"committed",1,(string)commit["id"]);
    }
    static void RouteRecovery()
    {
        using var f=new DirectModelEditingChecks.Fixture("builtin.scale");Native(f);
        var live=(DirectLiveController)Get(f.Direct,"live");var selected=(JObject)f.Drawing.NativeState["model_edit"].DeepClone();
        int blocked=0,unavailable=0;live.BlockedAttempt+=_=>blocked++;live.UnavailableAttempt+=_=>unavailable++;
        f.Route(true);f.Route(false);Call(f.Direct,"Update");FinishSelection(f);
        Call(f.Direct,"Update");Check(live.Selection.ObjectIds.Count==1,"actual receipt-before-preview ordering reproduces a stale selected local echo");
        var empty=NoActive();empty["settings"]=new JObject();empty["generation"]=0;f.Drawing.NativeState["model_edit"]=empty;
        Call(f.Direct,"Update");Check(live.Selection.ObjectIds.Count==0&&live.Selection.ActiveId=="","fresh no-active legacy state clears the actual controller's stale selection");
        int sent=f.Sent.Count;f.Route(true);f.Route(true,.05f);f.Route(false,.05f);
        Check(blocked==1&&unavailable==0&&f.Sent.Count==sent&&live.Selection.ObjectIds.Count==0,"no-selection edit still refuses without lease, geometry or automatic reselect");
        f.Route(true);f.Route(false);Call(f.Direct,"Update");Grant(f);
        var begin=f.Sent.Last(m=>(string)m["type"]=="live.edit.begin");
        Check((bool?)begin["payload"]["operation"]["selection_only"]==true&&((JArray)begin["payload"]["operation"]["selection"]["objects"]).Count==1,"explicit floating-model tap independently reselects while edit availability is false");
        f.Drawing.NativeState["model_edit"]=selected;Call(f.Direct,"Update");var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");State(f,"updated",1,(string)update["id"]);
        var commit=f.Sent.Last(m=>(string)m["type"]=="live.edit.commit");State(f,"committed",1,(string)commit["id"]);Call(f.Direct,"Update");
        Check(live.Selection.ActiveId==A&&f.Direct.Active&&!f.Sent.Any(m=>(string)m["type"]=="live.edit.cancel"),"own selection restore survives context echo and keeps edit mode");
        f.Route(true);f.Route(true,.05f);Grant(f);update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");
        Check(update["payload"]["parameters"]["scale"] is JArray,"next actual held gesture routes native Scale normally after explicit reselect");
        State(f,"updated",1,(string)update["id"]);f.Route(false,.05f);commit=f.Sent.Last(m=>(string)m["type"]=="live.edit.commit");State(f,"committed",1,(string)commit["id"]);
        Check(blocked==1&&unavailable==0&&f.Sent.Count(m=>(string)m["type"]=="live.edit.commit")==3,"two explicit selection transactions and one Scale commit preserve legitimate refusal and native history boundaries");
        f.Direct.AvailabilityPopup?.Dispose();
    }
#endif
}

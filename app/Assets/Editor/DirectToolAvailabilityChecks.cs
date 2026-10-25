using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR;

// Real controller adapter routes and production informational canvas; no host,
// native input, microphone, service or interactive runtime is used here.
public static class DirectToolAvailabilityChecks
{
    const string Id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static void Check(bool value,string why){if(!value)throw new Exception("DIRECT_TOOL_AVAILABILITY: "+why);}
    static object Get(object target,string name)=>target.GetType().GetField(name,Private).GetValue(target);
    static object Invoke(object target,string name,params object[] args)=>target.GetType().GetMethod(name,Private).Invoke(target,args);
    static void Tick(DirectModelEditing direct)=>Invoke(direct,"Update");
    static bool Geometry(JObject message)=>new[]{"command","live.edit.begin","live.edit.update","live.edit.commit"}.Contains((string)message["type"]);
    public static void Run()
    {
        var cameraObject=new GameObject("Direct availability synthetic head",typeof(Camera));
        cameraObject.tag="MainCamera";
        try
        {
            var camera=cameraObject.GetComponent<Camera>();
            LayoutAndWorldAnchor(camera);Routes();KnifeRollbackFeedback();VoiceReviewIndependence(camera);Capture(camera);
        }
        finally{UnityEngine.Object.DestroyImmediate(cameraObject);}
        Debug.Log("DIRECT_TOOL_AVAILABILITY_CHECK PASS actual unknown/live-disabled/legacy/selection-blocked drag routes; zero rejected geometry; tap+repeat suppression; cancel/mode/tracking/dispose cleanup; world pose+physical size independent of affine owner; measured complete reason pages; honest pending rollback; synthetic production popup capture; physical acceptance pending");
    }
    static void NativeLive(DirectModelEditingChecks.Fixture f,string tool="object.translate")
    {
        var model=(JObject)f.Drawing.NativeState["model_edit"];
        model["live_supported"]=true;model["tool"]=tool;
        model["settings"]=new JObject { ["orientation"]="GLOBAL",["constraint_axis"]=new JArray(false,false,false) };
        string component=(string)model["component"];
        model["selection"]=new JObject { ["objects"]=new JArray(new JObject { ["id"]=Id,["generation"]=3 }),["active_id"]=Id,["component"]=component,
            ["indices"]=component=="object"?new JArray():new JArray(component=="face"?20:0) };
        Tick(f.Direct);
    }
    static ToolAvailabilityPopup Drag(DirectModelEditingChecks.Fixture f)
    {
        f.Route(true);f.Route(true,.05f);
        Check(f.Direct.AvailabilityPopup?.Visible==true,"an actual rejected drag opens a visible production popup");
        return f.Direct.AvailabilityPopup;
    }
    static void Routes()
    {
        foreach(bool liveProtocol in new[]{false,true})
        {
            using var f=new DirectModelEditingChecks.Fixture("builtin.shear");
            if(liveProtocol)NativeLive(f,"");
            f.Route(true);f.Route(false);
            Check(f.Direct.AvailabilityPopup==null,"mere selection taps never claim unsupported editing");
            // A tap can deliberately synchronize selection. This next fixture
            // isolates unsupported geometry from any such independent work.
        }
        foreach(bool liveProtocol in new[]{false,true})
        {
            using var f=new DirectModelEditingChecks.Fixture("builtin.shear");
            if(liveProtocol)NativeLive(f,"");
            f.Direct.Initialize(f.Host,f.Preview,f.Drawing);f.Direct.Initialize(f.Host,f.Preview,f.Drawing);
            var popup=Drag(f);
            Check(popup.Unsupported&&popup.Title==ToolAvailabilityPopup.UnsupportedTitle&&popup.ToolName=="Shear","unknown tool is named and honestly reported unavailable");
            Check(!f.Sent.Any(Geometry)&&!f.Sent.Any(m=>(string)m["type"]=="lease.acquire"),"unknown tool produces no native geometry or lease");
            f.Route(true,.07f);f.Route(true,.09f);f.Route(false,.09f);Tick(f.Direct);
            Check(popup.ShowCount==1,"one attempt reports once despite held frames, release and repeated initialization");
            Check(!f.Sent.Any(Geometry),"rejected drag release cannot become a queued edit or selection transaction");
            f.Direct.Cancel("explicit cancel");Check(!popup.Visible,"explicit cancellation hides informational popup");
        }
        foreach(bool liveProtocol in new[]{false,true})
        {
            using var f=new DirectModelEditingChecks.Fixture();
            if(liveProtocol)NativeLive(f);
            var model=(JObject)f.Drawing.NativeState["model_edit"];
            model["available"]=false;model["reason"]="Select the required native mesh elements before moving.";
            var popup=Drag(f);
            Check(!popup.Unsupported&&popup.Title==ToolAvailabilityPopup.BlockedTitle&&popup.Reason==(string)model["reason"],"supported tool preserves specific selection/context reason without claiming unimplemented");
            Check(!f.Sent.Any(Geometry),"blocked selection never sends geometry");
            f.Route(false,.05f);f.Direct.SetActive(false);Check(!popup.Visible,"explicit mode off hides popup");
        }
        using(var f=new DirectModelEditingChecks.Fixture("builtin.shear"))
        {
            NativeLive(f,"");f.Drawing.NativeState["model_edit"]["live_supported"]=false;
            var popup=Drag(f);
            Check(popup.Unsupported&&!f.Sent.Any(Geometry),"live protocol capability false remains on explicit unsupported route, never legacy geometry fallback");
            f.Preview.TrackingLost(XRNode.RightHand);Check(!popup.Visible,"tracking loss hides popup and invalidates held attempt");
            f.Route(false,.05f);Check(!f.Sent.Any(Geometry),"tracking recovery release never replays rejected geometry");
        }
        using(var f=new DirectModelEditingChecks.Fixture("builtin.shear"))
        {
            var popup=Drag(f);Invoke(f.Direct,"OnDestroy");
            Check(popup.IsDisposed&&popup.VisualRoot==null,"adapter destruction disposes external world canvas");
        }
    }
    static void LayoutAndWorldAnchor(Camera camera)
    {
        var parent=new GameObject("Popup affine grandparent");var owner=new GameObject("Popup affine owner");
        owner.transform.SetParent(parent.transform,false);
        parent.transform.localScale=new Vector3(2,.4f,-3);owner.transform.localScale=new Vector3(.2f,4,1.7f);
        owner.transform.localRotation=Quaternion.Euler(19,41,12);
        using var popup=new ToolAvailabilityPopup(owner.transform);
        try
        {
            string reason="The connected native tool uses a modifier and a different selection type. Choose a supported base mesh in Blender, turn off the modifier for this edit, and select the required faces before trying again. Your existing selection, document and native history remain controlled by Blender.";
            Check(popup.Show(false,"builtin.inset_faces",reason,camera,100),"real canvas opens with complete bounded reason");
            Check(popup.Visible&&popup.Reason==reason&&popup.DisplayedText.Contains(reason)&&popup.TextFits,"complete reason is visible without clipping or truncation");
            Check(popup.PanelSize.x==800&&popup.PanelSize.y<=560,"canvas dimensions remain bounded");
            Check(popup.VisualRoot.transform.parent==null,"visual root is independent of owner affine hierarchy");
            var position=popup.WorldPose.position;var rotation=popup.WorldPose.rotation;var scale=popup.VisualRoot.transform.lossyScale;
            camera.transform.SetPositionAndRotation(new Vector3(2,1,-3),Quaternion.Euler(22,118,13));
            parent.transform.SetPositionAndRotation(new Vector3(4,5,6),Quaternion.Euler(31,87,19));parent.transform.localScale=new Vector3(-8,13,.03f);
            owner.transform.localScale=new Vector3(17,.001f,2);popup.Tick(100.2f);
            Check(Vector3.Distance(position,popup.WorldPose.position)<.00001f&&Quaternion.Angle(rotation,popup.WorldPose.rotation)<.001f,"turning head and moving owner do not move/reorient open popup");
            Check(Vector3.Distance(scale,popup.VisualRoot.transform.lossyScale)<.0000001f,"nonuniform moving owner cannot resize or shear physical popup");
            Check(!popup.Show(false,"builtin.inset_faces",reason,camera,100.3f)&&popup.ShowCount==1,"same short-interval repeat neither reanchors nor extends popup");
            Check(Vector3.Distance(position,popup.WorldPose.position)<.00001f,"repeat suppression preserves original world position");
            Check(!popup.VisualRoot.GetComponentsInChildren<Collider>(true).Any()&&!popup.VisualRoot.GetComponentsInChildren<Selectable>(true).Any()
                &&!popup.VisualRoot.GetComponentsInChildren<GraphicRaycaster>(true).Any(),"informational popup captures no ray/controller input and adds no controls");
            Check(popup.VisualRoot.GetComponentsInChildren<Graphic>(true).All(g=>!g.raycastTarget)&&!popup.VisualRoot.GetComponent<CanvasGroup>().blocksRaycasts,"all visual elements pass input through");
            popup.Tick(1000);Check(!popup.Visible,"popup automatically dismisses after reading lifetime");
            Check(popup.Show(false,"builtin.inset_faces",reason,camera,1001),"dismissed popup may be retriggered by later attempt");
            string longReason=string.Join(" ",Enumerable.Range(0,160).Select(i=>"condition"+i));
            popup.Show(true,"builtin.custom_tool",longReason,camera,1003);
            Check(popup.PageCount>1&&popup.Reason==longReason,"unusually long reason is preserved over bounded automatic pages");
            var shown=new List<string>();int count=popup.PageCount;
            for(int i=0;i<count;i++)
            {Check(popup.Visible&&popup.CurrentPage==i&&popup.TextFits,"every complete reason page fits measured canvas");shown.Add(popup.DisplayedReason);popup.Tick(popup.NextPageAt+.001f);}
            Check(string.Join(" ",shown)==longReason&&!popup.Visible,"all reason words appear before automatic dismissal");
            popup.Hide();Check(!popup.Visible,"Hide is idempotent");
        }
        finally{UnityEngine.Object.DestroyImmediate(owner);UnityEngine.Object.DestroyImmediate(parent);camera.transform.SetPositionAndRotation(Vector3.zero,Quaternion.identity);}
    }
    static void KnifeRollbackFeedback()
    {
        using var f=new DirectModelEditingChecks.Fixture("builtin.knife","EDIT_MESH");
        ((JObject)f.Drawing.NativeState["model_edit"])["component"]="vertex";NativeLive(f,"mesh.knife");
        f.Route(true);f.Route(true,.05f);
        var lease=f.Sent.Last(m=>(string)m["type"]=="lease.acquire");
        f.Receive("lease.granted",new JObject { ["lease"]=new JObject { ["lease_id"]="popup-live-lease" } },(string)lease["id"]);
        var begin=f.Sent.Last(m=>(string)m["type"]=="live.edit.begin");
        var state=f.Drawing.Session.RequestIdentity;state["edit_session_id"]="popup-live-edit";state["phase"]="active";state["sequence"]=0;
        state["revision"]=7;state["generations"]=new JObject { [Id]=3 };
        f.Receive("live.edit.state",state,(string)begin["id"]);
        Check(f.Sent.Any(m=>(string)m["type"]=="live.edit.update"),"Knife fixture sends a real live preview before reaching safety bound");
        var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");
        state["phase"]="updated";state["sequence"]=1;state["revision"]=8;state["generations"]=new JObject { [Id]=4 };
        f.View.Generation=4;f.Drawing.Session.Objects[Id]["generation"]=4;
        f.Receive("live.edit.state",state,(string)update["id"]);
        var live=(DirectLiveController)Get(f.Direct,"live");var path=(List<Vector3>)Get(live,"knifePath");
        while(path.Count<128)path.Add(new Vector3(-10-path.Count,0,2));
        Invoke(live,"AddKnifePoint",f.Ray(.1f));
        var popup=f.Direct.AvailabilityPopup;
        Check(popup?.Visible==true&&!popup.Unsupported&&popup.Reason.Contains("shorter stroke"),"real Knife overflow reports specific bounded gesture limitation");
        Check(popup.DisplayedText.Contains("If a live preview started")&&popup.DisplayedText.Contains("wait for Blender")&&!popup.DisplayedText.Contains("No edit was sent"),"popup honestly permits earlier previews and pending rollback");
        Check(f.Sent.Any(m=>(string)m["type"]=="live.edit.cancel")&&!f.Sent.Any(m=>(string)m["type"]=="live.edit.commit"),"over-limit preview requests rollback and never commits");
    }
    static void VoiceReviewIndependence(Camera camera)
    {
        var obj=new GameObject("Independent pending AI review");obj.SetActive(false);
        using var popup=new ToolAvailabilityPopup(null);
        try
        {
            var panel=obj.AddComponent<PendingCommandPanel>();Invoke(panel,"Awake");panel.head=camera.transform;
            panel.ShowComposition(string.Join("\n",Enumerable.Range(0,20).Select(i=>"Review step "+i+": bevel the selected native edges by two millimetres.")),DateTime.UtcNow.AddMinutes(2),true);
            Invoke(panel,"LateUpdate");string text=obj.GetComponent<TextMesh>().text;bool reviewed=panel.AllPagesReviewed;var pose=new Pose(obj.transform.position,obj.transform.rotation);
            popup.Show(true,"builtin.shear","This tool has no direct controller gesture in this build.",camera,1);popup.Hide();popup.Dispose();
            Check(panel.Visible&&panel.AllPagesReviewed==reviewed&&obj.GetComponent<TextMesh>().text==text&&obj.transform.position==pose.position&&obj.transform.rotation==pose.rotation,"independent availability lifetime never changes voice/AI review content, pose or page fence");
        }
        finally{UnityEngine.Object.DestroyImmediate(obj);}
    }
    static void Capture(Camera camera)
    {
        string output=Environment.GetEnvironmentVariable("CALHACKS_GLASS_EVIDENCE");if(string.IsNullOrEmpty(output))return;
        Directory.CreateDirectory(output);
        using var popup=new ToolAvailabilityPopup(null);
        camera.transform.SetPositionAndRotation(Vector3.zero,Quaternion.identity);camera.fieldOfView=60;camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.045f,.055f,.07f);camera.cullingMask=1<<31;
        popup.Show(true,"builtin.shear","Shear has no direct controller gesture in this build. Select a supported tool for the floating model, or continue with Shear using the Blender 2D view.",camera,0);
        foreach(var transform in popup.VisualRoot.GetComponentsInChildren<Transform>(true))transform.gameObject.layer=31;
        popup.VisualRoot.GetComponent<Canvas>().worldCamera=camera;
        Check(popup.TextFits,"production capture contains the complete actual reason and conditional guidance");
        typeof(GlassChecks).GetMethod("Render",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{camera,Path.Combine(output,"direct-tool-unavailable.png")});
        Check(new FileInfo(Path.Combine(output,"direct-tool-unavailable.png")).Length>10000,"production world popup synthetic PNG was written");
    }
}

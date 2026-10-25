using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEngine;
using UnityEngine.XR;

public static class DirectToolUsabilityChecks
{
    const BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    static void Check(bool ok,string reason){if(!ok)throw new Exception("DIRECT_TOOL_USABILITY: "+reason);}
    static object Get(object value,string name)=>value.GetType().GetField(name,Private).GetValue(value);
    static void Set(object value,string name,object data)=>value.GetType().GetField(name,Private).SetValue(value,data);
    static object Call(object value,string name,params object[] args)=>value.GetType().GetMethod(name,Private).Invoke(value,args);
    static DirectLiveController Live(DirectModelEditingChecks.Fixture f)=>(DirectLiveController)Get(f.Direct,"live");
    static JObject Model(DirectModelEditingChecks.Fixture f)=>(JObject)f.Drawing.NativeState["model_edit"];
    static void Native(DirectModelEditingChecks.Fixture f,string tool)=>typeof(LiveControllerChecks).GetMethod("NativeLive",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{f,tool});
    static void Grant(DirectModelEditingChecks.Fixture f)=>typeof(LiveControllerChecks).GetMethod("GrantAndBegin",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{f});
    static void State(DirectModelEditingChecks.Fixture f,string phase,long seq,string re)=>typeof(LiveControllerChecks).GetMethod("State",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{f,phase,seq,re});
    static bool Route(DirectModelEditingChecks.Fixture f,Ray ray,bool held,float fence=4)=>f.Preview.RouteControllerHand(XRNode.RightHand,ray,held,false,Vector2.zero,fence,out _,false);
    public static void Run()
    {
        Refusals();ScaleCubeRoutes();ScaleOwnMeshFence();NormalRoutes();RegionMultipleNormals();MetricGuides();SnapGuideReset();KnifeOverflow();RenderHandles();
        Debug.Log("DIRECT_TOOL_USABILITY_CHECK PASS actual-trigger/native-XYZ-cube-outward+inward/reflected-affine/own-mesh+nearer-UI-fences/frozen-face-normal/native-mm/ACK-only-guides/unsupported-drag-not-tap/no-missing-tool-sends/knife-whole-gesture-rollback; physical acceptance pending");
    }
    static void Refusals()
    {
        Check(DirectLiveController.CanonicalTool("builtin.extrude_magic","face")==null&&DirectLiveController.CanonicalTool("builtin.spin","face")==null,"unknown toolbar tools never become executable selection or extrusion");
        foreach(string native in new[]{"builtin.spin","builtin.select_box","builtin.select_lasso","builtin.select_circle"})
        {
            using var f=new DirectModelEditingChecks.Fixture(native);Native(f,native=="builtin.spin"?"":"object.selection");
            var model=Model(f);model["available"]=false;model["reason"]="";Call(f.Direct,"Update");
            int unavailable=0,blocked=0;string notice="";Live(f).UnavailableAttempt+=reason=>{unavailable++;notice=reason;};Live(f).BlockedAttempt+=_=>blocked++;
            f.Route(true);Check(unavailable==0&&blocked==0,"press without displacement never opens a refusal popup");
            f.Route(true,.05f);f.Route(true,.07f);f.Route(false,.07f);Call(f.Direct,"Update");
            Check(unavailable==1&&blocked==0&&!f.Sent.Any(m=>(string)m["type"]=="lease.acquire"),"unsupported tool/sweep drag reports once and sends no native transaction");
            Check(Live(f).Selection.ObjectIds.Count==1,"refused drag release cannot silently become a tap deselection");
            if(native!="builtin.spin")Check(notice.Contains("SHIFT")&&notice.Contains("2D"),"spatial sweep refusal gives supported selection alternatives");
        }
        foreach(string tool in new[]{"mesh.merge","mesh.loop_cut","mesh.inset"})
        {
            string native=tool=="mesh.merge"?"spatial_modeling.merge":tool=="mesh.loop_cut"?"builtin.loop_cut":"builtin.inset_faces";
            using var f=new DirectModelEditingChecks.Fixture(native,"EDIT_MESH");Model(f)["component"]="vertex";Native(f,tool);
            int refused=0;Live(f).BlockedAttempt+=_=>refused++;var first=new Ray(Vector3.zero,new Vector3(-.2f,-.2f,2).normalized);
            Check(Route(f,first,true),"actual visible native vertex admits an attempted tool gesture");
            Route(f,new Ray(Vector3.zero,new Vector3(-.15f,-.2f,2).normalized),true);Route(f,first,false);
            Check(refused==1&&!f.Sent.Any(m=>(string)m["type"]=="lease.acquire"),"wrong component/count is blocked before lease/mutation for "+tool);
        }
    }
    static void ScaleCubeRoutes()
    {
        foreach(bool reflected in new[]{false,true})foreach(int axis in new[]{0,1,2})foreach(float sign in new[]{-1f,1f})
        {
            using var f=new DirectModelEditingChecks.Fixture("builtin.scale");Native(f,"object.scale");
            if(reflected){f.View.transform.parent.localScale=new Vector3(-2,.4f,3);f.View.transform.parent.rotation=Quaternion.Euler(23,61,-17);}
            Model(f)["settings"]["pivot_m"]=new JArray(0,2,0);Call(f.Direct,"Update");Physics.SyncTransforms();
            var live=Live(f);var pivot=(Vector3)Call(live,"SelectionPivotDisplay");var direction=(Vector3)Call(live,"Axis",axis);
            var ends=(List<Transform>)Get(live,"scaleEnds");Check(ends.Count==3&&ends.All(end=>end.GetComponent<MeshRenderer>()!=null&&end.GetComponent<Collider>()==null),"production Scale has three solid cube ends and no collider interference");
            Check(((Material)Get(live,"axisMaterial")).GetInt("unity_GUIZTestMode")==8,"native cube axes render as scoped always-visible gizmos over their selected opaque mesh");
            var at=pivot+direction*.11f;Check(Vector3.Distance(ends[axis].position,at)<1e-6f,"visible cube and geometric hit bounds share one endpoint");
            var side=Vector3.Cross(direction,Mathf.Abs(Vector3.Dot(direction,Vector3.up))<.8f?Vector3.up:Vector3.right).normalized;var eye=at+side*.6f;
            var first=new Ray(eye,-side);Check(Route(f,first,true)&&f.Direct.Gesturing,"actual controller grabs the displayed Scale cube");
            var flags=(bool[])Get(live,"gizmoConstraint");Check(flags!=null&&flags.Count(v=>v)==1&&flags[axis],"grabbed cube captures its actual native axis");
            var changed=new Ray(eye,(at+direction*sign*.035f-eye).normalized);Route(f,changed,true);Grant(f);
            var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");var factors=(JArray)update["payload"]["parameters"]["scale"];
            Check(sign>0?(float)factors[axis]>1:(float)factors[axis]<1,"outward always grows and inward always shrinks independent of camera / reflected display");
            Check(Enumerable.Range(0,3).Where(i=>i!=axis).All(i=>(float)factors[i]==1),"only grabbed native axis scales");
            Model(f)["settings"]["pivot_m"]=new JArray(9,8,7);Call(f.Direct,"Update");
            Check(Vector3.Distance(ends[axis].position,at)<1e-6f,"own native pivot echo never shifts the held cube frame");
        }
    }
    static void ScaleOwnMeshFence()
    {
        using var f=new DirectModelEditingChecks.Fixture("builtin.scale");Native(f,"object.scale");SurfaceScaleChecks.SetBox(f.View,new Vector3(0,0,2),Vector3.one*.4f);
        Model(f)["settings"]["pivot_m"]=new JArray(0,2,0);Call(f.Direct,"Update");Physics.SyncTransforms();
        var live=Live(f);var tip=(Vector3)Call(live,"SelectionPivotDisplay")+(Vector3)Call(live,"Axis",0)*.11f;var ray=new Ray(Vector3.zero,tip.normalized);
        Check(f.Host.PickObject(ray,out float meshDepth)==f.View&&meshDepth<tip.magnitude,"selected mesh front actually occludes the visible cube endpoint");
        Check(Route(f,ray,true,meshDepth)&&((bool[])Get(live,"gizmoConstraint"))[0],"exact own-mesh fence exception grabs the visible Scale cube instead of a body drag");
        f.Preview.CancelDirectModelDraft("cleanup");Route(f,ray,false);
        Check(!Route(f,ray,true,meshDepth-.02f),"nearer unrelated UI fence never inherits Scale own-mesh exception");
        Route(f,ray,false);
        var blocker=new GameObject("Foreign collider inside selected bounds",typeof(MeshFilter),typeof(MeshCollider),typeof(WorkspaceObjectView));blocker.transform.SetParent(f.View.transform.parent,false);
        var blockerMesh=new Mesh();var centre=ray.GetPoint((meshDepth+tip.magnitude)*.5f);
        blockerMesh.vertices=new[]{centre+new Vector3(-.05f,-.05f,0),centre+new Vector3(.05f,-.05f,0),centre+new Vector3(.05f,.05f,0),centre+new Vector3(-.05f,.05f,0)};blockerMesh.triangles=new[]{0,2,1,0,3,2};blockerMesh.RecalculateBounds();
        blocker.GetComponent<MeshFilter>().sharedMesh=blockerMesh;blocker.GetComponent<MeshCollider>().sharedMesh=blockerMesh;
        var other=blocker.GetComponent<WorkspaceObjectView>();other.ObjectId=new string('b',32);other.Generation=4;other.SetNativePose(Vector3.zero,Quaternion.identity,Vector3.one);
        ((Dictionary<string,GameObject>)Get(f.Host,"objects"))[other.ObjectId]=blocker;f.Drawing.Session.Objects[other.ObjectId]=new JObject{["id"]=other.ObjectId,["generation"]=4};Physics.SyncTransforms();
        try
        {
            Check(f.Host.PickObject(ray,out float firstDepth)==f.View&&other.GetComponent<MeshCollider>().Raycast(ray,out var foreign,4)&&foreign.distance>firstDepth&&foreign.distance<tip.magnitude-.02f,"real foreign collider lies after own front but before rendered cube");
            Route(f,ray,true,firstDepth);Check(Get(live,"gizmoConstraint")==null,"own-mesh exception cannot pick an axis through a nearer foreign object inside its bounds");
        }
        finally{UnityEngine.Object.DestroyImmediate(blockerMesh);}
    }
    static void RegionMultipleNormals()
    {
        foreach(int face in new[]{20,21})
        {
            using var f=new DirectModelEditingChecks.Fixture("builtin.extrude_region","EDIT_MESH");Native(f,"mesh.extrude");var model=Model(f);
            var extra=new[]{new Vector3(0,-.2f,2),new Vector3(0,.2f,2),new Vector3(0,.2f,2.4f),new Vector3(0,-.2f,2.4f)};
            for(int i=0;i<4;i++)((JArray)model["vertices"]).Add(new JObject{["index"]=5+i,["position"]=DirectModelEditMath.ToWire(extra[i])});
            ((JArray)model["faces"]).Add(new JObject{["index"]=21,["vertices"]=new JArray(5,6,7,8)});model["selection"]["indices"]=new JArray(20,21);
            ((JArray)model["triangles"]).Add(new JObject{["face"]=21,["vertices"]=new JArray(5,6,7)});((JArray)model["triangles"]).Add(new JObject{["face"]=21,["vertices"]=new JArray(5,7,8)});
            var mesh=f.View.GetComponent<MeshFilter>().sharedMesh;mesh.vertices=((JArray)model["vertices"]).OfType<JObject>().Select(p=>DirectModelEditMath.ToUnity((JArray)p["position"])).ToArray();mesh.triangles=new[]{0,2,1,0,3,2,5,6,7,5,7,8};mesh.RecalculateBounds();f.View.GetComponent<MeshCollider>().sharedMesh=null;f.View.GetComponent<MeshCollider>().sharedMesh=mesh;
            Call(f.Direct,"Update");Physics.SyncTransforms();var live=Live(f);var normal=face==20?Vector3.back:Vector3.left;var centre=face==20?new Vector3(0,0,2):new Vector3(0,0,2.2f);
            var tip=centre+normal*.085f;var side=Vector3.Cross(normal,Vector3.up).normalized;var eye=tip+side*.6f;var first=new Ray(eye,-side);
            float fence=f.Host.PickObject(first,out float front)!=null?front:4;
            Check(Route(f,first,true,fence)&&(bool)Get(live,"gestureNormalConstrained"),"each actually drawn noncoplanar selected face normal is a real trigger handle");
            Route(f,new Ray(eye,(tip+normal*.03f-eye).normalized),true);Grant(f);var begin=f.Sent.Last(m=>(string)m["type"]=="live.edit.begin");
            Check(((JArray)begin["payload"]["operation"]["selection"]["indices"]).Count==2,"region normal gesture preserves the complete selected multi-face region");
            var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");var delta=DirectModelEditMath.ToUnity((JArray)update["payload"]["parameters"]["translation_m"]);
            Check(Vector3.Dot(delta.normalized,normal)>.9999f,"entire region follows the actually grabbed face's frozen native normal");
            Call(f.Direct,"Update");Check(((DirectToolGuides.Frame)Get(live,"guideFrame")).IntentLabel.Contains("grabbed face normal"),"region label names the actual chosen normal constraint");
        }
    }
    static void NormalRoutes()
    {
        foreach(bool mirrored in new[]{false,true})foreach(bool individual in new[]{false,true})
        {
            using var f=new DirectModelEditingChecks.Fixture(individual?"builtin.extrude_individual":"builtin.extrude_region","EDIT_MESH");Native(f,"mesh.extrude");
            if(mirrored)f.View.SetNativePose(Vector3.zero,Quaternion.identity,new Vector3(-1,1,1));
            var live=Live(f);var model=Model(f);Call(f.Direct,"Update");
            var nativeCentre=new Vector3(0,0,2);var normal=mirrored?Vector3.forward:Vector3.back;
            var map=f.View.NativeToDisplayMatrix;var centre=map.MultiplyPoint3x4(nativeCentre);var display=map.MultiplyVector(normal).normalized;
            var tip=centre+display*.085f;var side=Vector3.Cross(display,Vector3.up).normalized;var eye=tip+side*.6f;var first=new Ray(eye,-side);
            Check(Route(f,first,true)&&f.Direct.Gesturing&&(bool)Get(live,"gestureNormalConstrained"),"actual yellow face-normal handle is triggerable under native mirror parity");
            Route(f,new Ray(eye,(tip+display*.03f-eye).normalized),true);Grant(f);
            var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");var p=(JObject)update["payload"]["parameters"];
            if(individual)Check((float)p["normal_distance_m"]>0,"individual extrusion uses positive outward signed native normal distance");
            else Check(Vector3.Dot(DirectModelEditMath.ToUnity((JArray)p["translation_m"]),normal)>0,"region normal handle translates along the true frozen native normal");
            Call(f.Direct,"Update");var frame=(DirectToolGuides.Frame)Get(live,"guideFrame");
            Check(frame.ExtrudeNormalConstrained&&frame.NativeObjectMirrored==mirrored&&frame.Acknowledged==null,"held guide records actual normal constraint/parity and does not invent a native ACK");
        }
    }
    static void MetricGuides()
    {
        foreach(string tool in new[]{"mesh.inset","mesh.bevel"})
        {
            using var f=new DirectModelEditingChecks.Fixture(tool=="mesh.inset"?"builtin.inset_faces":"builtin.bevel","EDIT_MESH");Native(f,tool);
            f.View.transform.parent.localScale=new Vector3(-2,.5f,3);f.View.transform.parent.rotation=Quaternion.Euler(11,43,17);Call(f.Direct,"Update");Physics.SyncTransforms();
            var map=f.View.NativeToDisplayMatrix;var start=map.MultiplyPoint3x4(new Vector3(0,0,2));var eye=start-map.MultiplyVector(Vector3.forward).normalized;
            var first=new Ray(eye,(start-eye).normalized);
            Check(f.Host.PickObject(first,out _)==f.View&&DirectModelEditMath.TryPick(Model(f),map,first,.012f,out int face,out _,out _)&&face==20,"transformed metric fixture synchronizes real collider and exact visible native face before route");
            Check(Route(f,first,true)&&f.Direct.Gesturing,"transformed metric native face is admitted by actual controller route");
            var target=start+map.MultiplyVector(new Vector3(.03f,-.03f,0));var next=new Ray(eye,(target-eye).normalized);Route(f,next,true);
            Check(f.Sent.Any(m=>(string)m["type"]=="lease.acquire"),"native distance gesture requests ownership after real movement: "+f.Direct.Notice);Grant(f);
            var update=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");var p=(JObject)update["payload"]["parameters"];var live=Live(f);
            var delta=(Vector3)Get(live,"currentPoint")-(Vector3)Get(live,"startPoint");float expected=map.inverse.MultiplyVector(delta).magnitude;
            Check(Mathf.Abs((float)p[tool=="mesh.inset"?"thickness_m":"width_m"]-expected)<1e-6f&&expected>0,"diagonal movement produces one unsigned native distance instead of cancelling view diagonals");
            Call(f.Direct,"Update");var frame=(DirectToolGuides.Frame)Get(live,"guideFrame");var frozen=(JObject)frame.Model.DeepClone();
            Check(frame.Waiting&&frame.Acknowledged==null&&frame.IntentLabel.Contains("return to reduce"),"pre-ACK guides show actual control semantics and waiting, not queued amounts");
            ((JObject)Model(f)["vertices"][0])["position"]=new JArray(50,50,50);Model(f)["settings"]["pivot_m"]=new JArray(8,9,10);
            Call(f.Direct,"Update");frame=(DirectToolGuides.Frame)Get(live,"guideFrame");Check(JToken.DeepEquals(frame.Model,frozen),"held guide retains immutable native topology when own telemetry changes");
            State(f,"updated",1,(string)update["id"]);Call(f.Direct,"Update");frame=(DirectToolGuides.Frame)Get(live,"guideFrame");
            Check(JToken.DeepEquals(frame.Acknowledged,p),"readout is actual acknowledged cumulative native parameters");
            Set(live,"nextUpdate",float.NegativeInfinity);Route(f,new Ray(eye,(target+map.MultiplyVector(Vector3.right*.01f)-eye).normalized),true);Call(f.Direct,"Update");
            frame=(DirectToolGuides.Frame)Get(live,"guideFrame");Check(frame.Waiting&&JToken.DeepEquals(frame.Acknowledged,p),"newer in-flight intent cannot replace the accepted amount and is labelled pending");
            f.Preview.CancelDirectModelDraft("cleanup");Call(f.Direct,"Update");Check(Get(live,"guideFrame")==null,"rollback hides held guides and old ACKs");
        }
    }
    static void KnifeOverflow()
    {
        using var f=new DirectModelEditingChecks.Fixture("builtin.knife","EDIT_MESH");Native(f,"mesh.knife");var live=Live(f);int blocked=0;string reason="";live.BlockedAttempt+=text=>{blocked++;reason=text;};
        Ray At(float x,float y)=>new Ray(new Vector3(x,y,0),Vector3.forward);
        Route(f,At(-.15f,-.15f),true);Route(f,At(-.13f,-.15f),true);Grant(f);
        var first=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");var path=(List<Vector3>)Get(live,"knifePath");
        for(int i=2;i<128;i++){Set(live,"nextUpdate",float.NegativeInfinity);Route(f,At(-.15f+(i%16)*.018f,-.13f+(i/16)*.03f),true);}
        Check(path.Count==128&&blocked==0,"128 real surface samples are retained without truncation");var last=path[127];
        Set(live,"nextUpdate",float.NegativeInfinity);Route(f,At(.15f,.15f),true);
        Check(blocked==1&&reason=="Knife stroke is too long; use a shorter stroke"&&!f.Direct.Gesturing&&path.Count==128&&path[127]==last,"129th distinct real routed point cancels the whole stroke rather than rewriting its final chord");
        Route(f,At(.15f,.15f),false);State(f,"updated",1,(string)first["id"]);
        Check(f.Sent.Count(m=>(string)m["type"]=="live.edit.update")==1&&!f.Sent.Any(m=>(string)m["type"]=="live.edit.commit")&&f.Sent.Count(m=>(string)m["type"]=="live.edit.cancel")==1,"late ACK cannot send a queued prefix or commit after overflow");
        var cancel=f.Sent.Last(m=>(string)m["type"]=="live.edit.cancel");State(f,"cancelled",1,(string)cancel["id"]);Route(f,At(.15f,.15f),false);
        Check(!f.Drawing.Session.ExternalEditBusy&&!f.Sent.Any(m=>(string)m["type"]=="live.edit.commit"),"native rollback receipt releases ownership with no delayed replay");
    }
    static void SnapGuideReset()
    {
        using var f=new DirectModelEditingChecks.Fixture("builtin.move");Native(f,"object.translate");var model=Model(f);var settings=(JObject)model["settings"];
        settings["use_snap"]=true;settings["snap_elements"]=new JArray("VERTEX");
        var target=new Vector3(.055f,0,2);string id=new string('b',32);
        var other=new GameObject("Actual native snap vertex",typeof(MeshFilter),typeof(MeshCollider),typeof(WorkspaceObjectView));other.transform.SetParent(f.View.transform.parent,false);
        var mesh=new Mesh();mesh.vertices=new[]{target,target+new Vector3(-.015f,-.03f,0),target+new Vector3(.015f,-.03f,0),target+new Vector3(.015f,.03f,0),target+new Vector3(-.015f,.03f,0)};mesh.triangles=new[]{0,2,1,0,3,2,0,4,3,0,1,4};mesh.RecalculateBounds();
        other.GetComponent<MeshFilter>().sharedMesh=mesh;other.GetComponent<MeshCollider>().sharedMesh=mesh;var view=other.GetComponent<WorkspaceObjectView>();view.ObjectId=id;view.Generation=4;view.SetNativePose(Vector3.zero,Quaternion.identity,Vector3.one);
        ((Dictionary<string,GameObject>)Get(f.Host,"objects"))[id]=other;f.Drawing.Session.Objects[id]=new JObject{["id"]=id,["generation"]=4};
        model["snap_geometry"]=new JArray(new JObject{["id"]=id,["vertices"]=new JArray(new JObject{["index"]=77,["position"]=DirectModelEditMath.ToWire(target)})});Call(f.Direct,"Update");Physics.SyncTransforms();
        try
        {
            f.Route(true);f.Route(true,.05f);Grant(f);var first=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");var live=Live(f);
            Check(first["payload"]["parameters"]["snap_point_m"]!=null,"actual native candidate enters the routed snap parameters");Call(f.Direct,"Update");
            Check(((DirectToolGuides.Frame)Get(live,"guideFrame")).SnapPoint.HasValue,"guide shows actual successful target geometry");
            Set(live,"nextUpdate",float.NegativeInfinity);f.Route(true,.15f);State(f,"updated",1,(string)first["id"]);Call(f.Direct,"Update");
            var latest=f.Sent.Last(m=>(string)m["type"]=="live.edit.update");var frame=(DirectToolGuides.Frame)Get(live,"guideFrame");
            Check(latest["payload"]["parameters"]["snap_point_m"]==null&&!frame.SnapPoint.HasValue&&frame.Waiting,"moving outside actual snap range clears target dot and next update, while prior ACK remains labelled pending");
        }
        finally{UnityEngine.Object.DestroyImmediate(mesh);}
    }
    static void RenderHandles()
    {
        string directory=Environment.GetEnvironmentVariable("CALHACKS_GLASS_EVIDENCE");if(string.IsNullOrWhiteSpace(directory))return;
        var canvas=new Texture2D(1280,640,TextureFormat.RGB24,false);var cameraObject=new GameObject("Owned direct handles evidence camera");var camera=cameraObject.AddComponent<Camera>();var target=new RenderTexture(640,640,24);
        try
        {
            for(int panel=0;panel<2;panel++)
            {
                using var f=new DirectModelEditingChecks.Fixture(panel==0?"builtin.scale":"builtin.extrude_region",panel==0?"OBJECT":"EDIT_MESH");Native(f,panel==0?"object.scale":"mesh.extrude");Model(f)["settings"]["pivot_m"]=new JArray(0,2,0);Call(f.Direct,"Update");
                SurfaceScaleChecks.SetBox(f.View,new Vector3(0,0,2),Vector3.one*.4f);f.View.gameObject.layer=31;
                var opaque=new Material(Shader.Find("Universal Render Pipeline/Unlit")??Shader.Find("Unlit/Color"));opaque.color=new Color(.18f,.23f,.3f);if(opaque.HasProperty("_BaseColor"))opaque.SetColor("_BaseColor",opaque.color);
                f.View.gameObject.AddComponent<MeshRenderer>().sharedMaterial=opaque;
                foreach(var name in new[]{"Native tool axes · no alternate modeling menu","Native Blender Move arrows","Native Blender contextual guides"})
                {var root=GameObject.Find(name);if(root!=null)foreach(var child in root.GetComponentsInChildren<Transform>(true))child.gameObject.layer=31;}
                camera.cullingMask=1<<31;camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.025f,.035f,.055f);camera.nearClipPlane=.01f;camera.farClipPlane=10;
                var pivot=(Vector3)Call(Live(f),"SelectionPivotDisplay");camera.transform.position=pivot+new Vector3(.32f,.25f,-.5f);camera.transform.LookAt(pivot);camera.fieldOfView=42;camera.targetTexture=target;camera.Render();
                RenderTexture.active=target;canvas.ReadPixels(new Rect(0,0,640,640),panel*640,0);RenderTexture.active=null;
                UnityEngine.Object.DestroyImmediate(opaque);
            }
            canvas.Apply();Directory.CreateDirectory(directory);File.WriteAllBytes(Path.Combine(directory,"direct-tool-handles.png"),canvas.EncodeToPNG());
        }
        finally{RenderTexture.active=null;camera.targetTexture=null;UnityEngine.Object.DestroyImmediate(target);UnityEngine.Object.DestroyImmediate(cameraObject);UnityEngine.Object.DestroyImmediate(canvas);}
    }
}

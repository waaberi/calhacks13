using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEngine;
using UnityEngine.XR;

// Real route, draft, handoff and lease state machines; no OS input or live host.
public static class DirectModelEditingChecks
{
    const string Id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    static readonly BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static object Get(object obj, string field) => obj.GetType().GetField(field, Private).GetValue(obj);
    static void Set(object obj, string field, object value) => obj.GetType().GetField(field, Private).SetValue(obj, value);
    static void Property(object obj, string name, object value) => obj.GetType().GetProperty(name).GetSetMethod(true).Invoke(obj,new[] { value });
    static object Invoke(object obj, string name, params object[] args) => obj.GetType().GetMethod(name,Private).Invoke(obj,args);
    static void Check(bool ok, string why) { if (!ok) throw new Exception("DIRECT_MODEL_EDIT: " + why); }
    static void Near(Vector3 actual, Vector3 expected, string why) => Check(Vector3.Distance(actual,expected)<.00001f,why);
    public static void Run()
    {
        Mapping(); Picking(); ThinSolidPicking(); Routing(); Handoff(); Invalidation(); ReceiptsAndVisuals(); ExplicitCancel();
        Debug.Log("DIRECT_MODEL_EDIT_CHECK PASS actual preview-route/native-tool/base-topology/concave-triangles/component/occlusion/arrangement+negative-scale/meter-mm/click-only/ACK-release/no-replay/frozen-context/lease-single-submit; physical acceptance pending");
    }
    static void Mapping()
    {
        var root = new GameObject("Direct edit mapping root"); var obj = new GameObject("Direct edit mapping object");
        try
        {
            obj.transform.SetParent(root.transform,false); var view=obj.AddComponent<WorkspaceObjectView>();
            foreach (float unit in new[] { 1f, .001f })
            foreach (Vector3 scale in new[] { Vector3.one, new Vector3(-2,.3f,4) })
            {
                root.transform.SetPositionAndRotation(new Vector3(3,1,-2),Quaternion.Euler(23,67,-11)); root.transform.localScale=Vector3.one*2.3f;
                view.SetNativePose(new Vector3(.1f,.3f,-.2f),Quaternion.Euler(12,-37,18),scale);
                view.RestoreArrangement(new Vector3(-.3f,.1f,.5f),Quaternion.Euler(18,44,9));
                var map=DirectModelEditMath.NativeToDisplay(view);
                var native=new Vector3(.06f,.04f,-.03f);
                var display=map.MultiplyPoint3x4(native);
                var expected=view.transform.TransformPoint(Matrix4x4.TRS(view.NativePosition,view.NativeRotation,scale).inverse.MultiplyPoint3x4(native));
                Near(display,expected,"native world base vertex uses inspection arrangement exactly once");
                Near(DirectModelEditMath.ToUnity(DirectModelEditMath.ToWire(map.inverse.MultiplyVector(map.MultiplyVector(native)))),native,"display delta reverses placement, offsets, rotation and negative/nonuniform native scale exactly once");
                // The wire is already meters regardless of a native document's unit scale.
                Near(DirectModelEditMath.ToUnity(new JArray(.01,0,0)),new Vector3(.01f,0,0),"10mm wire stays 0.01m for native unit " + unit);
            }
            Quaternion q=Quaternion.AngleAxis(47,new Vector3(1,2,3).normalized); var wire=DirectModelEditMath.ToWire(q);
            var roundtrip=new Quaternion(-(float)wire[1],-(float)wire[3],-(float)wire[2],(float)wire[0]);
            Check(Quaternion.Angle(q,roundtrip)<.001f,"quaternion reflection roundtrip [w,x,y,z]");
            Check(!DirectModelEditMath.MeaningfulDelta(new JObject { ["rotation"]=new JArray(1,0,0,0) }),"zero rotation never submits history noise");
        }
        finally { UnityEngine.Object.DestroyImmediate(obj); UnityEngine.Object.DestroyImmediate(root); }
    }
    static JObject Mesh(string component="face", string tool="builtin.move") => new JObject {
        ["available"]=true,["reason"]="",["native_tool"]=tool,["mode"]="EDIT_MESH",["component"]=component,
        ["active_object_id"]=Id,["generation"]=3,["topology_token"]=new string('a',64),
        ["vertices"]=new JArray(
            new JObject { ["index"]=0,["position"]=new JArray(-.2,2,-.2) },
            new JObject { ["index"]=1,["position"]=new JArray(.2,2,-.2) },
            new JObject { ["index"]=2,["position"]=new JArray(.2,2,.2) },
            new JObject { ["index"]=3,["position"]=new JArray(-.2,2,.2) },
            new JObject { ["index"]=4,["position"]=new JArray(0,2.5,0) }),
        ["edges"]=new JArray(
            new JObject { ["index"]=10,["vertices"]=new JArray(0,1) },
            new JObject { ["index"]=11,["vertices"]=new JArray(1,2) }),
        ["faces"]=new JArray(new JObject { ["index"]=20,["vertices"]=new JArray(0,1,2,3) }),
        ["triangles"]=new JArray(new JObject { ["face"]=20,["vertices"]=new JArray(0,2,1) },new JObject { ["face"]=20,["vertices"]=new JArray(0,3,2) })
    };
    static void Picking()
    {
        foreach(string component in new[] { "face","edge","vertex" })
        {
            var model=Mesh(component); Vector3 at=component=="vertex"?new Vector3(-.2f,-.2f,2):component=="edge"?new Vector3(0,-.2f,2):new Vector3(0,0,2);
            var map=Matrix4x4.TRS(new Vector3(1,2,-1),Quaternion.Euler(0,47,0),Vector3.one*1.7f);
            var ray=new Ray(map.MultiplyPoint3x4(at-Vector3.forward),map.MultiplyVector(Vector3.forward).normalized);
            Check(DirectModelEditMath.TryPick(model,map,ray,.012f,out int selected,out var vertices,out var hit),"ray picks visible base "+component);
            Check(selected==(component=="face"?20:component=="edge"?10:0),"actual base index rather than evaluated/split mesh index "+component);
            Check(vertices.Length==(component=="face"?4:component=="edge"?2:1),"component expands to actual base vertices "+component);
            Near(hit,map.MultiplyPoint3x4(at),"pick respects arranged display "+component);
        }
        var hidden=Mesh("vertex");
        Check(!DirectModelEditMath.TryPick(hidden,Matrix4x4.identity,new Ray(Vector3.zero,Vector3.forward),.012f,out _,out _,out _),"hidden vertex behind nearest surface cannot be selected through it");
        var exact=Mesh(); exact["triangles"]=new JArray(new JObject { ["face"]=20,["vertices"]=new JArray(0,1,2) });
        Check(!DirectModelEditMath.TryPick(exact,Matrix4x4.identity,new Ray(new Vector3(-.15f,.15f,0),Vector3.forward),.012f,out _,out _,out _),"tessellation excludes absent concave region instead of guessing a face fan");
    }
    static void Routing()
    {
        using(var f=new Fixture())
        {
            Check(f.Route(false),"actual preview route hovers floating model");
            f.Route(true); f.Route(false); Check(f.Sent.Count==0&&!f.Direct.Gesturing,"simple trigger click creates no edit or lease");
            f.Route(true); Check(!f.Route(true,grip:true)&&!f.Direct.Gesturing,"grip cancels and yields to accepted arrangement");
            Check(!f.Preview.RouteHand(XRNode.LeftHand,f.Ray(),true,false,Vector2.zero,4,out _),"other-hand/native-window routing unchanged");
        }
        const string handPreference="SpatialModeling.PreviewPointerLeft";
        bool hadPreference=PlayerPrefs.HasKey(handPreference);int previousHand=PlayerPrefs.GetInt(handPreference,0);
        try
        {
            using var f=new Fixture();f.Preview.SetPointerHand(XRNode.LeftHand);f.Direct.SetActive(true);
            f.Preview.RouteControllerHand(XRNode.LeftHand,f.Ray(),false,false,Vector2.zero,4,out _,false);
            Check(f.Preview.RouteControllerHand(XRNode.LeftHand,f.Ray(),true,false,Vector2.zero,4,out _,false)&&f.Direct.Gesturing,
                "explicit left-hand pointer uses the actual direct production route");
            Check(!f.Direct.TryGestureVisual(XRNode.RightHand,f.Ray(),out _),"right-hand visuals cannot inherit a left-owned direct gesture");
            f.Preview.RouteControllerHand(XRNode.LeftHand,f.Ray(),false,false,Vector2.zero,4,out _,false);
            Check(f.Sent.Count==0,"left-hand direct selection remains click-only without mutation");
        }
        finally
        { if(hadPreference)PlayerPrefs.SetInt(handPreference,previousHand);else PlayerPrefs.DeleteKey(handPreference);PlayerPrefs.Save(); }
        foreach(string tool in new[] { "builtin.move","builtin.rotate","builtin.scale","builtin.extrude_region" })
        {
            using var f=new Fixture(tool,tool=="builtin.extrude_region"?"EDIT_MESH":"OBJECT");
            f.Route(true); f.Route(true,.05f); Check(f.Sent.Count==0,"draft cannot acquire permission before release "+tool);
            f.Route(false,.05f);
            var acquire=f.Sent.Single(m=>(string)m["type"]=="lease.acquire");
            f.Receive("lease.granted",new JObject { ["lease"]=new JObject { ["lease_id"]="lease" } },(string)acquire["id"]);
            var command=f.Sent.Single(m=>(string)m["type"]=="command");
            Check((string)command["payload"]["op"]=="object.spatial_edit","native typed edit "+tool);
            Check((long)command["payload"]["base_revision"]==7&&(long)command["payload"]["target"]["generation"]==3,"frozen revision/generation "+tool);
            Check((string)command["payload"]["args"]["native_tool"]==tool,"native selected tool preserved "+tool);
            Check(((JArray)command["payload"]["args"]["indices"]).Count==(tool=="builtin.extrude_region"?1:0),"mesh picks exact component; object picks none "+tool);
            f.Route(false,.05f); Check(f.Sent.Count(m=>(string)m["type"]=="command")==1,"released input never replays "+tool);
        }
    }
    static void ThinSolidPicking()
    {
        foreach (var map in new[] { Matrix4x4.identity, Matrix4x4.TRS(new Vector3(1,2,-1),Quaternion.Euler(13,47,-8),Vector3.one*1.7f) })
        {
            var ray=new Ray(map.MultiplyPoint3x4(Vector3.zero),map.MultiplyVector(Vector3.forward).normalized);
            var backOnly=Mesh("vertex"); ((JObject)backOnly["vertices"][4])["position"]=new JArray(0,2.005,0);
            Check(!DirectModelEditMath.TryPick(backOnly,map,ray,.012f,out _,out _,out _),
                "thin solid front wall occludes a rear vertex only 5mm behind it, even inside lateral pick radius");
            foreach(string component in new[] { "vertex","edge" })
            {
                var thin=Mesh(component);var points=(JArray)thin["vertices"];
                ((JObject)points[0])["position"]=new JArray(-.004,2,-.2);
                ((JObject)points[3])["position"]=new JArray(-.004,2,.2);
                ((JObject)points[4])["position"]=new JArray(0,2.005,0);
                points.Add(new JObject { ["index"]=5,["position"]=new JArray(-.004,2,0) });
                points.Add(new JObject { ["index"]=6,["position"]=new JArray(0,2.005,-.1) });
                points.Add(new JObject { ["index"]=7,["position"]=new JArray(0,2.005,.1) });
                thin["faces"]=new JArray(new JObject { ["index"]=20,["vertices"]=new JArray(0,1,2,3,5) });
                thin["triangles"]=new JArray(
                    new JObject { ["face"]=20,["vertices"]=new JArray(0,1,5) },
                    new JObject { ["face"]=20,["vertices"]=new JArray(1,2,5) },
                    new JObject { ["face"]=20,["vertices"]=new JArray(2,3,5) });
                thin["edges"]=new JArray(
                    new JObject { ["index"]=10,["vertices"]=new JArray(0,5) },
                    new JObject { ["index"]=11,["vertices"]=new JArray(5,3) },
                    new JObject { ["index"]=12,["vertices"]=new JArray(6,7) });
                Check(DirectModelEditMath.TryPick(thin,map,ray,.012f,out int picked,out _,out var hit),
                    "slightly off-axis visible front "+component+" remains easy to pick");
                Check(component=="vertex"?picked==5:picked==10||picked==11,
                    "exact-on-ray rear "+component+" cannot beat a visible front component inside the 12mm lateral radius");
                Near(hit,map.MultiplyPoint3x4(new Vector3(-.004f,0,2)),"visible candidate visibility uses its own exact ray "+component);
                if(component=="edge")
                {
                    thin["edges"]=new JArray(new JObject { ["index"]=12,["vertices"]=new JArray(6,7) });
                    Check(!DirectModelEditMath.TryPick(thin,map,ray,.012f,out _,out _,out _),
                        "a hidden edge 5mm behind the solid front is refused when no visible edge is in range");
                }
            }
        }
    }
    static void Handoff()
    {
        foreach(bool earlyRelease in new[] { false,true })
        {
            using var f=new Fixture(); f.State(true); f.Route(true); f.Route(true,.04f);
            Check(f.Sent.Count==0&&f.Direct.Gesturing,"native input must release before draft is ready");
            if(earlyRelease)f.Route(false,.04f);
            Set(f.Preview,"endAfterRelease",false); f.State(false); Invoke(f.Preview,"FlushNativeCommand");
            if(earlyRelease)
            { Check(f.Sent.Count==0&&!f.Direct.Gesturing,"released gesture cannot replay after delayed ACK"); continue; }
            f.Route(true,.06f); f.Route(false,.06f);
            Check(f.Sent.Count(m=>(string)m["type"]=="lease.acquire")==1,"ACK plus fresh native state admits one held direct gesture");
        }
    }
    static void Invalidation()
    {
        foreach(string changed in new[] { "tool","generation","document","placement","modal","stale","component","topology" })
        {
            using var f=new Fixture(); f.Route(true); f.Route(true,.05f);
            f.Change(changed); Invoke(f.Direct,"Update");
            f.Route(false,.05f); Check(!f.Sent.Any(m=>(string)m["type"]=="command"),"context change never commits "+changed);
        }
        using(var f=new Fixture())
        {
            f.Route(true);f.Route(true,.05f);f.Route(false,.05f);var acquire=f.Sent.Single(m=>(string)m["type"]=="lease.acquire");
            f.Change("tool");f.Receive("lease.granted",new JObject { ["lease"]=new JObject { ["lease_id"]="late" } },(string)acquire["id"]);
            Check(!f.Sent.Any(m=>(string)m["type"]=="command")&&f.Sent.Any(m=>(string)m["type"]=="lease.release"),"late permission after native toolbar change releases without mutation");
        }
    }
    static void ReceiptsAndVisuals()
    {
        foreach(string outcome in new[] { "applied","rejected","unknown" })
        {
            using var f=new Fixture();int selected=0;string final=null;
            f.Direct.SelectionCommitted+=id=>{selected++;final=id;};
            f.Route(true);f.Route(true,.05f);
            string beforeDelta=((JObject)Get(f.Direct,"delta")).ToString();
            string beforeContext=(string)Get(f.Direct,"frozenContext"),beforeNotice=f.Direct.Notice;
            var beforePoint=(Vector3)Get(f.Direct,"currentPoint");int beforeSent=f.Sent.Count;
            var ghost=(GameObject)Get(f.Direct,"ghost");var line=ghost.GetComponentsInChildren<LineRenderer>()[0];var beforeVertex=line.GetPosition(0);
            Check(f.Direct.TryGestureVisual(XRNode.RightHand,f.Ray(.09f),out var endpoint),"own held hand has draft contact at current stabilized ray");
            Near(endpoint,f.Ray(.09f).GetPoint(Vector3.Distance(f.Ray().origin,new Vector3(0,0,2))),"visual endpoint follows latest aim without another filter");
            Check(Vector3.Distance(beforeVertex,line.GetPosition(0))>.02f,"late visual refresh moves the ghost with the same latest stabilized ray");
            Check(((JObject)Get(f.Direct,"delta")).ToString()==beforeDelta&&(string)Get(f.Direct,"frozenContext")==beforeContext
                &&(Vector3)Get(f.Direct,"currentPoint")==beforePoint&&f.Direct.Notice==beforeNotice&&f.Sent.Count==beforeSent
                &&f.Direct.Gesturing&&f.Drawing.Session.Draft==null,
                "late visual refresh changes only ghost/endpoint, never queued delta, frozen context, input state, status or native transmission");
            Check(!f.Direct.TryGestureVisual(XRNode.LeftHand,f.Ray(.09f),out _),"other hand cannot inherit gesture distance");
            Check(UnityEngine.Object.FindObjectsByType<Transform>(FindObjectsSortMode.None).Any(t=>t.name=="LOCAL model draft · uncommitted orange preview"),"local draft is visually distinct before native commit");
            f.Route(false,.05f);var acquire=f.Sent.Single(m=>(string)m["type"]=="lease.acquire");
            f.Receive("lease.granted",new JObject { ["lease"]=new JObject { ["lease_id"]="lease" } },(string)acquire["id"]);
            var command=f.Sent.Single(m=>(string)m["type"]=="command");
            const string finalId="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
            f.Drawing.Session.Objects[finalId]=new JObject { ["id"]=finalId,["name"]="Actual final target",["generation"]=4 };
            f.View.Generation=4;Invoke(f.Direct,"Update");
            Check(f.Drawing.Session.NativeCommandExecuting,"expected native geometry change after send waits for actual receipt");
            f.Receive("result",new JObject { ["request_id"]=command["id"],["outcome"]=outcome,["selection"]=new JObject { ["id"]=finalId } },null);
            Invoke(f.Direct,"Update");Invoke(f.Direct,"Update");
            Check(selected==(outcome=="applied"?1:0),"only own applied receipt adopts selection once: "+outcome);
            if(outcome=="applied")Check(final==finalId&&f.Drawing.Session.SelectedId==finalId,"actual final receipt target wins over the original gesture target without toggling it off");
            Check(!UnityEngine.Object.FindObjectsByType<Transform>(FindObjectsSortMode.None).Any(t=>t.name=="LOCAL model draft · uncommitted orange preview"),"receipt cleanup removes local preview immediately in editor");
        }
    }
    static void ExplicitCancel()
    {
        foreach(bool nativeOwned in new[] { false,true })
        {
            using var f=new Fixture();if(nativeOwned)f.State(true);
            f.Route(true);f.Route(true,.05f);
            f.Preview.CancelDirectModelDraft("Escape cancelled the local controller draft");
            f.Route(false,.05f);Set(f.Preview,"endAfterRelease",false);f.State(false);Invoke(f.Preview,"FlushNativeCommand");
            Check(!f.Direct.Gesturing&&!f.Sent.Any(m=>(string)m["type"]=="command"||(string)m["type"]=="lease.acquire"),
                "Escape/cancel prevents late trigger release and delayed input ACK replay; nativeOwned="+nativeOwned);
        }
        using(var f=new Fixture())
        {
            f.Route(true);f.Route(true,.05f);f.Route(false,.05f);var acquire=f.Sent.Single(m=>(string)m["type"]=="lease.acquire");
            f.Receive("lease.granted",new JObject { ["lease"]=new JObject { ["lease_id"]="lease" } },(string)acquire["id"]);
            f.Preview.CancelDirectModelDraft("Escape cancelled; native geometry unchanged");
            Check(f.Drawing.Session.NativeCommandExecuting&&!f.Direct.Notice.Contains("geometry unchanged"),
                "Escape during an executing native transaction waits for receipt without a false unchanged-geometry claim");
            Check(f.Direct.Notice.Contains("wait")||f.Direct.Notice.Contains("receipt"),
                "executing transaction cancellation feedback preserves the native wait-for-receipt notice");
        }
    }
    sealed class Fixture:IDisposable
    {
        readonly GameObject owner,display,obj;
        readonly Mesh mesh;
        readonly string tool,mode;
        public readonly HostScene Host;
        public readonly PreviewSpatialDrawing Drawing;
        public readonly PreviewInteraction Preview;
        public readonly DirectModelEditing Direct;
        public readonly WorkspaceObjectView View;
        public readonly List<JObject> Sent=new List<JObject>();
        public Fixture(string nativeTool="builtin.move",string nativeMode="OBJECT")
        {
            tool=nativeTool;mode=nativeMode;
            owner=new GameObject("Inactive direct model fixture");owner.SetActive(false);
            display=new GameObject("Direct model fixture display");
            Host=owner.AddComponent<HostScene>();Set(Host,"status",Enum.Parse(typeof(HostScene).GetNestedType("Status",BindingFlags.NonPublic),"Connected"));Set(Host,"placed",true);Set(Host,"root",display.transform);
            Drawing=owner.AddComponent<PreviewSpatialDrawing>();Drawing.Initialize(Host);Drawing.Session.Send=m=>Sent.Add((JObject)m.DeepClone());
            Preview=owner.AddComponent<PreviewInteraction>();Set(Preview,"scene",Host);Property(Preview,"Drawing",Drawing);
            Direct=owner.AddComponent<DirectModelEditing>();Direct.Initialize(Host,Preview,Drawing);Property(Preview,"DirectEditing",Direct);
            obj=new GameObject("Native target",typeof(MeshFilter),typeof(MeshCollider),typeof(WorkspaceObjectView));obj.transform.SetParent(display.transform,false);
            View=obj.GetComponent<WorkspaceObjectView>();View.ObjectId=Id;View.Generation=3;View.SetNativePose(Vector3.zero,Quaternion.identity,Vector3.one);
            mesh=new Mesh();mesh.vertices=new[] { new Vector3(-.2f,-.2f,2),new Vector3(.2f,-.2f,2),new Vector3(.2f,.2f,2),new Vector3(-.2f,.2f,2) };mesh.triangles=new[] { 0,2,1,0,3,2 };mesh.RecalculateBounds();obj.GetComponent<MeshFilter>().sharedMesh=mesh;obj.GetComponent<MeshCollider>().sharedMesh=mesh;
            ((Dictionary<string,GameObject>)typeof(HostScene).GetField("objects",Private).GetValue(Host))[Id]=obj;
            Drawing.Session.Receive(new JObject { ["type"]="welcome",["payload"]=new JObject { ["session_id"]="session",["host_epoch"]="host",["actor_id"]="actor",["can_edit"]=true,["document"]=Document(),["capabilities"]=new JObject { ["sketch"]=true } } });
            Drawing.Session.Receive(new JObject { ["type"]="scene.snapshot",["payload"]=new JObject { ["document"]=Document(),["objects"]=new JArray(new JObject { ["id"]=Id,["name"]="Native target",["generation"]=3 }) } });
            State(false);Direct.SetActive(true);Physics.SyncTransforms();
        }
        static JObject Document()=>new JObject { ["id"]="doc",["open_epoch"]="open",["revision"]=7 };
        public void State(bool owned)
        {
            var m=Mesh("face",tool);m["mode"]=mode;m["component"]=mode=="OBJECT"?"object":"face";
            var state=new JObject { ["session_id"]="session",["host_epoch"]="host",["document_id"]="doc",["open_epoch"]="open",["mode"]=mode,["model_edit"]=m,["modal_active"]=false,["editing_mode"]="exclusive",["ui_ending"]=false,["ui_owner"]=owned?new JObject { ["actor_id"]="actor" }:null,["ui_session_id"]=owned?"native-token":null,["input_allowed"]=owned };
            Drawing.SetNativeState(state);
        }
        public Ray Ray(float x=0)=>new Ray(Vector3.zero,new Vector3(x,0,2).normalized);
        public bool Route(bool trigger,float x=0,bool grip=false)=>Preview.RouteControllerHand(XRNode.RightHand,Ray(x),trigger,grip,Vector2.zero,4,out _,false);
        public void Receive(string type,JObject payload,string re)
        {
            var message=new JObject { ["type"]=type,["payload"]=payload,["re"]=re };
            var before=typeof(DirectModelEditing).GetMethod("BeforeMessage",Private);before.Invoke(Direct,new object[] { message });Drawing.Session.Receive(message);
        }
        public void Change(string what)
        {
            var m=(JObject)Drawing.NativeState["model_edit"];
            if(what=="tool")m["native_tool"]="builtin.scale";
            if(what=="generation")View.Generation=4;
            if(what=="document")Drawing.Session.Disconnect("different document");
            if(what=="placement")display.transform.position+=Vector3.right;
            if(what=="modal")Drawing.NativeState["modal_active"]=true;
            if(what=="stale")Set(Drawing,"stateAt",float.NegativeInfinity);
            if(what=="component")m["component"]="vertex";
            if(what=="topology")m["topology_token"]=new string('b',64);
        }
        public void Dispose()
        {
            UnityEngine.Object.DestroyImmediate(owner);UnityEngine.Object.DestroyImmediate(obj);UnityEngine.Object.DestroyImmediate(mesh);UnityEngine.Object.DestroyImmediate(display);
            foreach(var ghost in UnityEngine.Object.FindObjectsByType<Transform>(FindObjectsSortMode.None))
                if(ghost!=null&&ghost.name=="LOCAL model draft · uncommitted orange preview")UnityEngine.Object.DestroyImmediate(ghost.gameObject);
        }
    }
}

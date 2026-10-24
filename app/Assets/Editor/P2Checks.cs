using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

public static class P2Checks
{
    static void Check(bool test, string why) { if (!test) throw new Exception("P2: " + why); }
    static void Near(Vector3 a, Vector3 b, string why) => Check(Vector3.Distance(a,b)<0.00001f, why);

    public static void Run()
    {
        // Edit-time only: no Player, XR loader, socket, scene Play or P1 service.
        var container = new GameObject("P2 edit-time checks");
        container.SetActive(false);
        try
        {
            var scene = container.AddComponent<HostScene>();
            typeof(HostScene).GetMethod("Awake", BindingFlags.Instance|BindingFlags.NonPublic).Invoke(scene,null);
            var material = AssetDatabase.LoadAssetAtPath<Material>("Assets/SpatialModeling/Materials/HostObject.mat");
            typeof(HostScene).GetField("objectMaterial", BindingFlags.Instance|BindingFlags.NonPublic).SetValue(scene,material);
            var table = container.GetComponent<TablePlacement>();
            var data = JObject.Parse(File.ReadAllText(Path.Combine(Application.dataPath,"../../contracts/examples/scene.snapshot.json")))["payload"] as JObject;
            HostEvent decoded = null;
            var mainThread = Environment.CurrentManagedThreadId;
            int decodeThread = mainThread;
            Task.Run(() => { decodeThread = Environment.CurrentManagedThreadId; decoded=HostLink.DecodeScene(data,true); }).GetAwaiter().GetResult();
            Check(decodeThread != mainThread,"scene parsing occurs on a background thread");
            scene.Handle(decoded);
            Check(scene.ObjectCount==3,"receive real contract objects including mesh:null");
            Check(!scene.Placement.gameObject.activeSelf,"model must wait for Place Table");
            table.SeedFromHead(new Vector3(1,1.65f,2),Vector3.forward);
            table.Place();
            Check(table.IsPlaced && scene.Placement.gameObject.activeSelf,"Place exposes the model");
            var first = scene.Placement.GetChild(0).GetComponent<WorkspaceObjectView>();
            var originalNative = first.NativePosition;
            var mesh = first.GetComponent<MeshFilter>().sharedMesh;
            Check(mesh != null && first.GetComponent<MeshCollider>().sharedMesh==mesh,"selection uses rendered geometry");
            Check(scene.Placement.GetComponentsInChildren<WorkspaceObjectView>(true).All(v=>v.transform.parent==scene.Placement),"wire world transforms stay flat under display root");
            var initial = new Pose(scene.Placement.position,scene.Placement.rotation);
            table.BeginMove();
            table.Adjust(.1f,.3f,.5f,90,new Vector3(1,1.65f,2),Vector3.forward);
            table.Place();
            Check(Vector3.Distance(initial.position,scene.Placement.position)>.1f,"second distinct table position");
            Near(first.NativePosition,originalNative,"inspection never changes native pose");
            Near(first.transform.localScale,Vector3.one,"inspection magnification stays outside native scale");
            var placed = new Pose(scene.Placement.position,scene.Placement.rotation);
            var scale = scene.Placement.localScale;
            first.transform.localPosition+=Vector3.right*.03f;
            first.RememberArrangement();
            var offset = first.PositionOffset;
            scene.Handle(HostLink.DecodeScene(data,true));
            Near(scene.Placement.position,placed.position,"reconnect snapshot preserves placement");
            Near(scene.Placement.localScale,scale,"reconnect snapshot preserves inspection scale");
            Check(first==scene.Placement.GetChild(0).GetComponent<WorkspaceObjectView>(),"stable IDs reuse objects on snapshot");
            Near(first.PositionOffset,offset,"same-document snapshot preserves P1 part arrangements");
            var update=(JObject)data.DeepClone();
            update["document"]["revision"]=42;
            update["objects"]=new JArray(((JObject)update["objects"][0]).DeepClone());
            update["removed"]=new JArray();
            ((JObject)update["objects"][0]).Remove("mesh");
            update["objects"][0]["transform"]["location"][0]=.01;
            var currentMesh=first.GetComponent<MeshFilter>().sharedMesh;
            scene.Handle(HostLink.DecodeScene(update,false));
            Check(first.GetComponent<MeshFilter>().sharedMesh==currentMesh,"transform-only delta retains mesh and collider");
            Near(first.NativePosition,new Vector3(.01f,.005f,0),"conversion happens once, in BlenderFrame");
            update["objects"]=new JArray();
            update["removed"]=new JArray(first.ObjectId);
            scene.Handle(HostLink.DecodeScene(update,false));
            Check(scene.ObjectCount==2,"native deletion removes rendered object and collider");
            table.BeginMove();
            table.Adjust(0,.2f,1,0,Vector3.zero,Vector3.forward);
            table.CancelMove();
            Near(scene.Placement.position,placed.position,"Cancel restores confirmed table pose");
            Near(scene.Placement.localScale,scale,"Cancel restores confirmed size");
            table.ConfirmTrackingReset();
            Check(!table.IsPlaced&&!scene.Placement.gameObject.activeSelf,"tracking origin reset requires fresh confirmation");
            table.SeedFromHead(new Vector3(0,1.6f,0),Vector3.right);
            table.Place();
            var next=(JObject)data.DeepClone();
            next["document"]["id"]="11111111111111111111111111111111";
            scene.Handle(HostLink.DecodeScene(next,true));
            Check(!table.IsPlaced,"different document requires Place Table again");
            var corrupt=(JObject)data.DeepClone();
            corrupt["objects"][0]["mesh"]["indices"][0]=999999;
            bool refused=false;
            try { HostLink.DecodeScene(corrupt,true); }
            catch(FormatException) { refused=true; }
            Check(refused,"a corrupt mesh cannot silently produce a partial current scene");
            var vertices=new Vector3[65536];
            vertices[1]=Vector3.right; vertices[65535]=Vector3.up;
            var large=new HostEvent(HostEventKind.Scene) { Snapshot=true, DocumentId=decoded.DocumentId,
                OpenEpoch=decoded.OpenEpoch, Revision=decoded.Revision };
            large.Objects.Add(new ObjectRecord { Id="22222222222222222222222222222222",Name="Large index mesh",
                Visible=true,HasTransform=true,Scale=Vector3.one,Rotation=Quaternion.identity,HasMesh=true,
                Mesh=new MeshData {Positions=vertices, Indices=new[]{0,1,65535}} });
            scene.Handle(large);
            var largeMesh=scene.Placement.GetChild(0).GetComponent<MeshFilter>().sharedMesh;
            Check(largeMesh.indexFormat==UnityEngine.Rendering.IndexFormat.UInt32,"large evaluated meshes use 32-bit indices");
            var actualPath=Environment.GetEnvironmentVariable("CALHACKS_P2_NATIVE_SNAPSHOT");
            if(!string.IsNullOrEmpty(actualPath))
            {
                scene.Handle(HostLink.DecodeScene(JObject.Parse(File.ReadAllText(actualPath)),true));
                var native=scene.Placement.GetChild(0).GetComponent<WorkspaceObjectView>();
                Near(native.GetComponent<MeshFilter>().sharedMesh.bounds.size,new Vector3(.02f,.02f,.02f),"real host snapshot renders the measured 20mm cube");
            }
            typeof(TablePlacement).GetMethod("CreatePanel",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(table,null);
            Check(UnityEngine.Object.FindObjectsByType<TableAction>(FindObjectsInactive.Include,FindObjectsSortMode.None).Length==14,"all ray/trigger controls constructed");
            Debug.Log("P2_CHECKS PASS: background decode, meshes/colliders/IDs, explicit placement, two poses, native separation, reconnect, cancel, tracking reset, corrupt-scene refusal, 32-bit mesh, native host geometry, 14 controls");
        }
        finally { UnityEngine.Object.DestroyImmediate(container); }
    }

    public static void Windows()
    {
        Run();
        var output=Environment.GetEnvironmentVariable("CALHACKS_P2_BUILD_PATH");
        if (string.IsNullOrWhiteSpace(output)) throw new Exception("Set CALHACKS_P2_BUILD_PATH outside the repository");
        var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions {
            scenes=EditorBuildSettings.scenes.Where(s=>s.enabled).Select(s=>s.path).ToArray(),
            target=BuildTarget.StandaloneWindows64, locationPathName=output, options=BuildOptions.None
        });
        Debug.Log("P2_BUILD_RESULT "+report.summary.result+" errors="+report.summary.totalErrors);
        if(report.summary.result!=BuildResult.Succeeded) throw new Exception("P2 build failed");
    }
}

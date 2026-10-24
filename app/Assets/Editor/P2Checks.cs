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
            var preview = (Transform)typeof(TablePlacement).GetField("preview",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(table);
            Check(!preview.gameObject.activeSelf && table.NeedsSeed,"preview waits for the common settled head pose");
            table.Place();
            Check(!table.IsPlaced,"Place cannot bypass the tracked startup seed");
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
            Check(preview.gameObject.activeSelf,"settled seed reveals preview while model remains gated");
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
            update["objects"][0]["generation"]=42;
            update["objects"][0]["transform"]["location"][0]=.01;
            var currentMesh=first.GetComponent<MeshFilter>().sharedMesh;
            scene.Handle(HostLink.DecodeScene(update,false));
            Check(first.GetComponent<MeshFilter>().sharedMesh==currentMesh,"transform-only delta retains mesh and collider");
            Near(first.PositionOffset,offset,"new native generation retains local P1 arrangement");
            Near(first.NativePosition,new Vector3(.01f,.005f,0),"conversion happens once, in BlenderFrame");
            var wrongEpoch=(JObject)update.DeepClone();
            wrongEpoch["document"]["open_epoch"]="33333333333333333333333333333333";
            wrongEpoch["objects"][0]["transform"]["location"][0]=99;
            scene.Handle(HostLink.DecodeScene(wrongEpoch,false));
            Check(!scene.IsCurrent,"wrong-epoch updates cannot be current");
            Near(first.NativePosition,new Vector3(.01f,.005f,0),"wrong-epoch update never mutates displayed native cache");
            scene.Handle(HostLink.DecodeScene(data,true));
            Check(scene.IsCurrent && table.IsPlaced,"fresh same-document snapshot recovers without moving table");
            // A real topology delta must replace both render and selection meshes.
            var topology=(JObject)data.DeepClone();
            topology["document"]["revision"]=42;
            topology["objects"]=new JArray(((JObject)topology["objects"][0]).DeepClone());
            topology["objects"][0]["mesh"]["positions"][0]=-.02;
            var oldMesh=first.GetComponent<MeshFilter>().sharedMesh;
            scene.Handle(HostLink.DecodeScene(topology,false));
            Check(first.GetComponent<MeshFilter>().sharedMesh!=oldMesh &&
                first.GetComponent<MeshCollider>().sharedMesh==first.GetComponent<MeshFilter>().sharedMesh,
                "topology delta replaces render mesh and collider together");
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
            var incomplete=(JObject)data.DeepClone();
            ((JObject)incomplete["objects"][0]).Remove("mesh");
            scene.Handle(HostLink.DecodeScene(incomplete,true));
            Check(!scene.IsCurrent,"incomplete snapshot cannot retain an old mesh as current");
            var noTransform=(JObject)data.DeepClone();
            ((JObject)noTransform["objects"][0]).Remove("transform");
            refused=false;
            try { HostLink.DecodeScene(noTransform,true); }
            catch(FormatException) { refused=true; }
            Check(refused,"missing native transform cannot silently place an object at origin");
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
            table.SeedFromHead(new Vector3(0,1.6f,0),Vector3.forward);
            table.Place();
            var moveButton=UnityEngine.Object.FindObjectsByType<TableAction>(FindObjectsInactive.Include,FindObjectsSortMode.None)
                .Single(a=>a.name=="Move Table");
            Physics.SyncTransforms();
            var buttonRay=new Ray(moveButton.transform.position-moveButton.transform.forward*.5f,moveButton.transform.forward);
            Check(table.RaycastControls(buttonRay,out var buttonDistance) && buttonDistance>0,
                "shared P1 ray discovers actual table button collider");
            Check(table.HoverController(buttonRay,true) && table.State==TablePlacement.PlacementState.Moving,
                "shared P1 trigger invokes table Move through actual collider dispatch");
            table.CancelMove();
            Check(table.IsPlaced,"shared dispatch preserves cancel state machine");
            Debug.Log("P2_CHECKS PASS: background decode, meshes/colliders/IDs, explicit placement, two poses, native separation, reconnect, cancel, tracking reset, corrupt-scene refusal, 32-bit mesh, native host geometry, stale epoch, topology/collider updates, shared-ray dispatch, 14 controls");
        }
        finally { UnityEngine.Object.DestroyImmediate(container); }
    }

    public static void Windows()
    {
        Run();
        var output=Environment.GetEnvironmentVariable("CALHACKS_P2_BUILD_PATH");
        if (string.IsNullOrWhiteSpace(output)) throw new Exception("Set CALHACKS_P2_BUILD_PATH outside the repository");
        // Run the cumulative real P1 interaction, both pose formats, startup,
        // native/view, pixel freshness and graphics/alpha gates and sanitization.
        Environment.SetEnvironmentVariable("CALHACKS_P1_BUILD_PATH", output);
        P1Build.Windows();
        Debug.Log("P2_BUILD_RESULT Succeeded errors=0 cumulative_P1=True");
    }
}

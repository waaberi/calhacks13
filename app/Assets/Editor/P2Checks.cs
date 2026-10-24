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
        Check(HostScene.TryResolvePort(null,8765,out var resolved) && resolved==8765,"default localhost port stays unchanged");
        Check(HostScene.TryResolvePort("43210",8765,out resolved) && resolved==43210,"explicit isolated port is honored");
        foreach(var invalid in new[]{"0","-1","65536","8765oops"," "})
            Check(!HostScene.TryResolvePort(invalid,8765,out resolved),"invalid explicit port must refuse connection instead of using original host");
        // Edit-time only: no Player, XR loader, socket, scene Play or P1 service.
        var container = new GameObject("P2 edit-time checks");
        container.SetActive(false);
        try
        {
            var scene = container.AddComponent<HostScene>();
            var material = AssetDatabase.LoadAssetAtPath<Material>("Assets/SpatialModeling/Materials/HostObject.mat");
            typeof(HostScene).GetField("objectMaterial", BindingFlags.Instance|BindingFlags.NonPublic).SetValue(scene,material);
            typeof(HostScene).GetMethod("Awake", BindingFlags.Instance|BindingFlags.NonPublic).Invoke(scene,null);
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
            var immediateRecenter=typeof(HostScene).GetField("recenterRequested",BindingFlags.Instance|BindingFlags.NonPublic);
            Check(!(bool)immediateRecenter.GetValue(scene),"initial/new-document snapshot cannot bypass startup settling");
            scene.RequestRecenter();
            Check((bool)immediateRecenter.GetValue(scene),"explicit B/Y recenter retains prompt user-requested placement");
            typeof(TablePlacement).GetMethod("TrackingReset",BindingFlags.Instance|BindingFlags.NonPublic)
                .Invoke(table,new object[]{null});
            Check(!(bool)immediateRecenter.GetValue(scene),"actual automatic tracking-origin callback must not impersonate explicit B/Y intent");
            scene.RequestRecenter();
            scene.InvalidateUnconfirmedPlacement();
            Check(!(bool)immediateRecenter.GetValue(scene),"explicit intent from before headset removal cannot bypass remount settling");
            table.SeedFromHead(new Vector3(1,1.65f,2),Vector3.forward);
            Check(preview.gameObject.activeSelf,"settled seed reveals preview while model remains gated");
            scene.InvalidateUnconfirmedPlacement();
            Check(table.NeedsSeed && !preview.gameObject.activeSelf,"unmount/focus loss hides and invalidates an unconfirmed old preview");
            table.Place();
            Check(!table.IsPlaced,"old preview cannot be confirmed after readiness was lost");
            var origin=new GameObject("Rotated placement origin");
            Pose worldHead;
            try
            {
                origin.transform.SetPositionAndRotation(new Vector3(2,.1f,-4),Quaternion.Euler(0,73,0));
                worldHead=WorkspaceInteraction.ToWorldPose(origin.transform,
                    new Pose(new Vector3(.2f,1.55f,.4f),Quaternion.Euler(0,-31,0)));
            }
            finally { UnityEngine.Object.DestroyImmediate(origin); }
            var facing=Vector3.ProjectOnPlane(worldHead.rotation*Vector3.forward,Vector3.up).normalized;
            table.SeedFromHead(worldHead.position,worldHead.rotation*Vector3.forward);
            var expectedTable=worldHead.position+facing*table.Distance;
            expectedTable.y=table.Height;
            Near(scene.Placement.position,expectedTable,"table uses current world headset pose exactly once under a translated/rotated tracking origin");
            Check(HostScene.TryGetDisplayPose(worldHead.position,worldHead.rotation*Vector3.forward,1.05f,0,
                out var screenPosition,out var screenRotation),"same world headset pose produces the screen placement");
            Check(Mathf.Abs(Vector3.Dot(screenPosition-worldHead.position,Vector3.Cross(Vector3.up,facing)))<.00001f,
                "screen has no unexpected lateral offset from the shared forward heading");
            Check(Quaternion.Angle(scene.Placement.rotation,screenRotation)<.001f,
                "table and screen use the same horizontal heading, not opposite or independently sampled headings");
            table.Place();
            Check(table.IsPlaced && scene.Placement.gameObject.activeSelf,"Place exposes the model");
            var confirmedPose=new Pose(scene.Placement.position,scene.Placement.rotation);
            scene.InvalidateUnconfirmedPlacement();
            Check(table.IsPlaced && scene.Placement.gameObject.activeSelf,"removing headset does not undo an explicitly confirmed placement");
            Near(scene.Placement.position,confirmedPose.position,"confirmed table stays world anchored through focus/removal");
            Check(Quaternion.Angle(scene.Placement.rotation,confirmedPose.rotation)<.001f,"focus/removal preserves confirmed orientation");
            Debug.Log("P2_PLACEMENT_LIFECYCLE_CHECK PASS pending invalidation/remount/rotated-origin/shared heading/confirmed anchoring");
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
            Check(UnityEngine.Object.FindObjectsByType<TableAction>(FindObjectsInactive.Include,FindObjectsSortMode.None).Length==16,"table controls plus pin/dock menu actions constructed");
            table.SeedFromHead(new Vector3(0,1.6f,0),Vector3.forward);
            table.Place();
            Check(table.MenuDocked && !table.Menu.gameObject.activeSelf,"menu starts docked and waits for actual left-hand tracking");
            var leftGrip = new Pose(new Vector3(-.35f,1.15f,.35f),Quaternion.Euler(0,25,0));
            table.UpdateLeftHandMenu(leftGrip,new Vector3(0,1.65f,0),true);
            Check(table.Menu.gameObject.activeSelf,"tracked left grip reveals menu");
            Check(Vector3.Distance(table.Menu.position,leftGrip.position)<.21f,"menu starts at left hand instead of a head-relative HUD offset");
            Check(table.Menu.GetComponent<RectTransform>().rect.width*table.Menu.lossyScale.x<.36f,"initial menu width is below 36cm instead of old 62cm");
            var stillTable = new Pose(scene.Placement.position,scene.Placement.rotation);
            table.PinMenu();
            var pinnedMenu = new Pose(table.Menu.position,table.Menu.rotation);
            table.UpdateLeftHandMenu(new Pose(new Vector3(2,1,3),Quaternion.Euler(0,145,0)),new Vector3(1,1.7f,-1),true);
            Near(table.Menu.position,pinnedMenu.position,"placed menu does not follow head or hand motion");
            Check(Quaternion.Angle(table.Menu.rotation,pinnedMenu.rotation)<.001f,"placed menu does not rotate with head");
            table.UpdateLeftHandMenu(default,Vector3.zero,false);
            Check(table.Menu.gameObject.activeSelf,"world menu remains placed when left tracking is lost");
            Near(scene.Placement.position,stillTable.position,"moving/docking menu never moves table");
            Check(Quaternion.Angle(scene.Placement.rotation,stillTable.rotation)<.001f,"menu motion never changes table orientation");
            table.DockMenu();
            Check(table.MenuDocked && !table.Menu.gameObject.activeSelf,"return-to-hand waits for fresh tracking");
            table.UpdateLeftHandMenu(leftGrip,new Vector3(0,1.65f,0),true);
            var menuGrabPose = new Pose(table.Menu.position,table.Menu.rotation);
            table.PinMenu();
            var controllerStart = new Pose(new Vector3(.35f,1.2f,.3f),Quaternion.identity);
            var relativeMenu = WorkspaceInteraction.RelativeRayPose(controllerStart,menuGrabPose);
            var movedMenu = WorkspaceInteraction.FollowRay(new Pose(controllerStart.position,Quaternion.Euler(0,20,0)),relativeMenu,0);
            Check(Vector3.Distance(movedMenu.position,menuGrabPose.position)>.04f,"menu can use accepted aim-driven placement mapping");
            table.Menu.SetPositionAndRotation(movedMenu.position,movedMenu.rotation);
            table.UpdateLeftHandMenu(leftGrip,new Vector3(0,1.65f,0),true);
            Near(table.Menu.position,movedMenu.position,"released menu keeps the pose supplied by the shared grab path");
            table.DockMenu();
            table.UpdateLeftHandMenu(leftGrip,new Vector3(0,1.65f,0),true);
            Debug.Log("P2_LEFT_HAND_MENU_CHECK PASS small docked start/fresh tracking/world pin/aim placement/table invariance");
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
            Debug.Log("P2_CHECKS PASS: background decode, meshes/colliders/IDs, explicit placement, two poses, native separation, reconnect, cancel, tracking reset, corrupt-scene refusal, 32-bit mesh, native host geometry, stale epoch, topology/collider updates, shared-ray dispatch, 16 controls including placeable left-hand menu");
        }
        finally { UnityEngine.Object.DestroyImmediate(container); }
    }

    public static void Windows()
    {
        Run();
        ArrangementChecks.Run();
        var output=Environment.GetEnvironmentVariable("CALHACKS_P2_BUILD_PATH");
        if (string.IsNullOrWhiteSpace(output)) throw new Exception("Set CALHACKS_P2_BUILD_PATH outside the repository");
        // Run the cumulative real P1 interaction, both pose formats, startup,
        // native/view, pixel freshness and graphics/alpha gates and sanitization.
        Environment.SetEnvironmentVariable("CALHACKS_P1_BUILD_PATH", output);
        P1Build.Windows();
        Debug.Log("P2_BUILD_RESULT Succeeded errors=0 cumulative_P1=True");
    }
}

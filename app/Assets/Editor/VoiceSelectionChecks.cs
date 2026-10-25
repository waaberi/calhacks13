using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using SpatialModeling.VoiceCore;
using UnityEditor;
using UnityEngine;
using UnityEngine.XR;

public static class VoiceSelectionChecks
{
    const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static void Check(bool value, string why) { if (!value) throw new Exception("Voice selection: " + why); }
    static void Invoke(object obj, string name) => obj.GetType().GetMethod(name, Private).Invoke(obj, null);
    static void Set(object obj, string name, object value) => obj.GetType().GetField(name, Private).SetValue(obj, value);
    static object Get(object obj, string name) => obj.GetType().GetField(name, Private).GetValue(obj);

    public static void Run()
    {
        var existing = new HashSet<GameObject>(Resources.FindObjectsOfTypeAll<GameObject>());
        var container = new GameObject("Voice selection isolated software fixture");
        container.SetActive(false);
        try
        {
            var host = container.AddComponent<HostScene>();
            Set(host, "objectMaterial", AssetDatabase.LoadAssetAtPath<Material>("Assets/SpatialModeling/Materials/HostObject.mat"));
            Invoke(host, "Awake");
            var voice = container.AddComponent<VoiceUiAdapter>(); voice.host = host; Invoke(voice, "Awake");
            Invoke(voice, "BindHost");
            var data = JObject.Parse(File.ReadAllText(Path.Combine(Application.dataPath, "../../contracts/examples/scene.snapshot.json")))["payload"] as JObject;
            var decoded = HostLink.DecodeScene(data, true);
            host.Handle(new HostEvent(HostEventKind.Welcome) { DocumentId = decoded.DocumentId, OpenEpoch = decoded.OpenEpoch });
            host.Handle(decoded);
            var arrangement = container.AddComponent<WorkspaceArrangement>(); Invoke(arrangement,"Awake");
            Set(arrangement,"scene",host);
            var table = host.Table;
            table.SeedFromHead(new Vector3(0,1.65f,0), Vector3.forward); table.Place();
            var views = host.Placement.GetComponentsInChildren<WorkspaceObjectView>().Where(v => v.GetComponent<MeshCollider>().sharedMesh != null).ToArray();
            Check(views.Length >= 2, "real contract mesh fixture has multiple selectable objects");
            var screen = container.AddComponent<BlenderScreen>();
            var interaction = container.AddComponent<WorkspaceInteraction>();
            Set(interaction, "scene", host); Set(interaction, "screen", screen); Set(interaction, "voice", voice);
            Set(interaction, "arrangement", arrangement);
            var handType = typeof(WorkspaceInteraction).GetNestedType("Hand", BindingFlags.NonPublic);
            var left = Activator.CreateInstance(handType, true); var right = Activator.CreateInstance(handType, true);
            handType.GetField("node").SetValue(left, XRNode.LeftHand); handType.GetField("node").SetValue(right, XRNode.RightHand);
            Set(interaction, "left", left); Set(interaction, "right", right);
            var route = typeof(WorkspaceInteraction).GetMethod("RouteHand", Private);
            Action<object, object, Ray, bool, bool> aim = (hand, other, ray, trigger, grip) => {
                route.Invoke(interaction, new object[] { hand, other,
                    new Pose(ray.origin, Quaternion.LookRotation(ray.direction)), ray, grip, trigger, grip, trigger, Vector2.zero, false });
                voice.SetControllerPointer(interaction.PointedObjectId);
            };
            // Separate fixture objects in world space. Native coordinates remain unchanged.
            for (int i=0; i<views.Length; i++) views[i].transform.position = new Vector3(i*.3f,1f,1.5f);
            Physics.SyncTransforms();
            Func<int,Ray> toward = i => new Ray(views[i].GetComponent<Renderer>().bounds.center - Vector3.forward*.4f, Vector3.forward);
            var native = views.Select(v => v.NativePosition).ToArray();
            var poses = views.Select(v => new Pose(v.transform.position,v.transform.rotation)).ToArray();
            var rootPose = new Pose(host.Placement.position,host.Placement.rotation);

            aim(right,left,toward(0),false,false);
            Check(interaction.PointedObjectId == views[0].ObjectId && voice.SelectedObjectId == null, "controller mesh hit points without selecting");
            aim(right,left,toward(0),true,false);
            Check(voice.SelectedObjectId == views[0].ObjectId && !interaction.IsHolding, "front trigger selects exact object without beginning any hold");
            aim(right,left,toward(0),false,false);
            aim(right,left,toward(0),true,false);
            Check(voice.SelectedObjectId==null && !interaction.IsHolding,"a second trigger click on the selected object deselects without dragging");
            aim(right,left,toward(0),false,false);
            aim(right,left,toward(0),true,false);
            Check(voice.SelectedObjectId==views[0].ObjectId,"a later fresh trigger click can select it again");
            aim(right,left,toward(1),false,false);
            Check(voice.SelectedObjectId == views[0].ObjectId, "selection remains latched when pointer moves away");
            var core = (VoiceSession)Get(voice,"session");
            var command = core.Hear(new RecognitionResult("rotate it ninety degrees around x",1f)).Command;
            Check(command != null && command.TargetId == views[0].ObjectId, "actual VoiceSession resolves this/it to explicit selection rather than hover");
            var namedCommand = core.Hear(new RecognitionResult("rotate " + views[1].name + " forty five degrees around x",1f)).Command;
            Check(namedCommand!=null && namedCommand.TargetId==views[1].ObjectId,"an explicit spoken object name targets that object rather than silently overriding it with selection");
            for(int i=0;i<views.Length;i++)
                Check(Vector3.Distance(poses[i].position,views[i].transform.position)<.000001f &&
                    Quaternion.Angle(poses[i].rotation,views[i].transform.rotation)<.0001f && views[i].NativePosition==native[i],
                    "point/select/voice resolution never drags or changes native/view geometry");
            Check(host.Placement.position==rootPose.position && host.Placement.rotation==rootPose.rotation,"whole-workspace pose unchanged by selection");

            aim(right,left,new Ray(Vector3.one*10,Vector3.up),false,false);
            voice.ClearObjectSelection();
            aim(left,right,toward(1),true,false);
            Check(voice.SelectedObjectId==views[1].ObjectId,"left hand selects through the same production routing");
            Invoke(voice,"LateUpdate");
            var outline=(LineRenderer)Get(voice,"selectionOutline");
            Check(outline!=null && outline.enabled && outline.positionCount==16,"selected object has a visible bounds outline without mesh/material mutation");
            Check(voice.ObjectTargetLabel.Contains(views[1].name),"selection feedback names the actual selected object");

            voice.ClearObjectSelection();
            aim(left,right,toward(1),true,true);
            Check(voice.SelectedObjectId==null && interaction.IsHolding,"grip retains existing workspace grab and suppresses selection");
            aim(left,right,toward(1),false,false);
            Check(!interaction.IsHolding,"existing grip release remains separate");
            table.UpdateLeftHandMenu(new Pose(new Vector3(-.3f,1.1f,.3f),Quaternion.identity),new Vector3(0,1.65f,0),true);
            table.Menu.gameObject.SetActive(true);
            Check(!table.Menu.GetComponentsInChildren<TableAction>().Any(a=>a.name=="Select object"),
                "menu omits Select object while preserving direct trigger selection");
            var clear = table.Menu.GetComponentsInChildren<TableAction>().Single(a=>a.name=="Clear selection");
            var renderCamera = new GameObject("Voice selection menu render",typeof(Camera)).GetComponent<Camera>();
            typeof(SettingsMenuChecks).GetMethod("Preview",BindingFlags.Static|BindingFlags.NonPublic)
                .Invoke(null,new object[]{table,arrangement,renderCamera,"voice-selection-menu.png"});
            Physics.SyncTransforms();
            voice.BeginObjectSelection();
            Check(voice.SelectingObject&&voice.SelectedObjectId==null&&!interaction.IsHolding,
                "public selection mode remains available without a redundant menu-arm button");
            var menuRay = CombinedGlassChecks.ControlRay(clear.GetComponent<RectTransform>(),.2f);
            aim(right,left,menuRay,true,false);
            Check(voice.SelectedObjectId==null,"menu trigger cannot fall through to a model");
            voice.BeginObjectSelection();
            table.Menu.gameObject.SetActive(false);
            aim(right,left,toward(0),true,false);
            Check(!voice.SelectingObject && voice.SelectedObjectId==views[0].ObjectId,"armed mode completes on next model trigger");
            clear.Invoke(); Check(voice.SelectedObjectId==null,"Clear selection removes latched target");

            // Exercise only the newly requested size/removal changes through the
            // real trigger/grip route, including lifecycle and accessibility.
            var leftMenuPose=new Pose(new Vector3(-.3f,1.1f,.3f),Quaternion.identity);
            var menuHead=new Vector3(0,1.65f,0);
            table.UpdateLeftHandMenu(leftMenuPose,menuHead,true);
            var menuGlass=table.Menu.GetComponent<GlassRoot>();
            void MenuGlassLifecycle(bool active)
            {
                // This is an edit-time fixture, not Play mode. Normal
                // MonoBehaviours do not receive the Player lifecycle here.
                // Remove first so initialization is safe even if OnEnable ran.
                Invoke(menuGlass,"OnDisable");
                if(active)Invoke(menuGlass,"OnEnable");
            }
            MenuGlassLifecycle(true);
            var menuNames=table.Menu.GetComponentsInChildren<TableAction>().Select(a=>a.name).ToArray();
            foreach(var removed in new[]{"Select object","Pin menu here","Recover workspace"})
                Check(!menuNames.Contains(removed),"requested left-hand action is absent: "+removed);
            var compactScale=table.Menu.localScale;
            Check(Mathf.Abs(compactScale.x/GlassTheme.TextScale-.00055f*TablePlacement.DockedMenuFactor)<.000001f,
                "docked production menu uses the larger requested docked physical scale");
            var menuPosition=table.Menu.position;var menuRotation=table.Menu.rotation;
            menuRay=CombinedGlassChecks.ControlRay(clear.GetComponent<RectTransform>(),.2f);
            Physics.SyncTransforms();aim(right,left,menuRay,false,true);
            Check(interaction.IsHolding&&!table.MenuDocked&&Vector3.Distance(table.Menu.localScale,compactScale/TablePlacement.DockedMenuFactor)<.000001f,
                "actual side-grip menu route preserves pinning and expands to full size");
            Check(Vector3.Distance(table.Menu.position,menuPosition)<.000001f&&Quaternion.Angle(table.Menu.rotation,menuRotation)<.001f,
                "dock-to-world size change preserves the menu's world pose");
            aim(right,left,menuRay,false,false);
            Check(!interaction.IsHolding,"menu grip release remains available without a Pin menu button");
            table.DockMenu();table.DockMenu();
            MenuGlassLifecycle(false);
            Check(Vector3.Distance(table.Menu.localScale,compactScale)<.000001f&&!table.Menu.gameObject.activeSelf,
                "repeated return-to-hand shrinks once and waits for fresh tracking");
            table.UpdateLeftHandMenu(leftMenuPose,menuHead,true);
            MenuGlassLifecycle(true);
            table.UpdateLeftHandMenu(default,menuHead,false);
            MenuGlassLifecycle(false);
            table.UpdateLeftHandMenu(leftMenuPose,menuHead,true);
            MenuGlassLifecycle(true);
            Check(Vector3.Distance(table.Menu.localScale,compactScale)<.000001f,
                "tracking disable/re-enable does not apply the docked factor again");
            const string glassPrefix="SpatialModeling.Glass.";
            string[] glassKeys={"TextScale","Contrast","Opaque","Motion"};
            var glassPresent=glassKeys.Select(key=>PlayerPrefs.HasKey(glassPrefix+key)).ToArray();
            float oldTextScale=GlassTheme.TextScale;
            bool oldContrast=GlassTheme.HighContrast,oldOpaque=GlassTheme.ReducedTransparency,oldMotion=GlassTheme.ReducedMotion;
            try
            {
                float enlarged=oldTextScale<1.5f?2f:1f;
                GlassTheme.SetAccessibility(enlarged,oldContrast,oldOpaque,oldMotion);
                var accessibleScale=compactScale*(enlarged/oldTextScale);
                Check(Vector3.Distance(table.Menu.localScale,accessibleScale)<.000001f,
                    "actual GlassRoot subscription preserves docked accessibility: scale_x="+table.Menu.localScale.x.ToString("R")+
                    " expected_x="+accessibleScale.x.ToString("R")+" previous="+Get(menuGlass,"previous")+" requested="+enlarged);
                table.PinMenu();table.PinMenu();
                Check(Vector3.Distance(table.Menu.localScale,accessibleScale/TablePlacement.DockedMenuFactor)<.000001f,
                    "full-size world menu preserves accessibility without duplicate enlargement");
                table.DockMenu();table.DockMenu();MenuGlassLifecycle(false);
                table.UpdateLeftHandMenu(leftMenuPose,menuHead,true);MenuGlassLifecycle(true);
                Check(Vector3.Distance(table.Menu.localScale,accessibleScale)<.000001f,
                    "returning accessible menu to hand preserves exactly one compact factor");
                table.UpdateLeftHandMenu(default,menuHead,false);MenuGlassLifecycle(false);
                GlassTheme.SetAccessibility(oldTextScale,oldContrast,oldOpaque,oldMotion);
                Check(Vector3.Distance(table.Menu.localScale,accessibleScale)<.000001f,
                    "hidden menu defers a new accessibility choice until its actual OnEnable");
                table.UpdateLeftHandMenu(leftMenuPose,menuHead,true);MenuGlassLifecycle(true);
                Check(Vector3.Distance(table.Menu.localScale,compactScale)<.000001f,
                    "reactivating hidden menu applies the pending accessibility ratio once");
            }
            finally
            {
                GlassTheme.SetAccessibility(oldTextScale,oldContrast,oldOpaque,oldMotion);
                for(int i=0;i<glassKeys.Length;i++)if(!glassPresent[i])PlayerPrefs.DeleteKey(glassPrefix+glassKeys[i]);
                PlayerPrefs.Save();
                MenuGlassLifecycle(false);
            }
            Debug.Log("LEFT_HAND_MENU_COMPACT_CHECK PASS removed_select_pin_recover direct_trigger_selection public_selection_method grip_world_pin larger_docked_scale full_pinned_scale repeated_dock_pin_idempotent tracking_reenable actual_GlassRoot_lifecycle active_and_hidden_accessibility_retained");
            table.Menu.gameObject.SetActive(false);

            // A nearer screen must occlude a model for selection, exactly as it does for grabbing.
            var panel=new GameObject("Blocking screen fixture",typeof(RectTransform),typeof(Canvas),typeof(GlassCurvedCanvas),typeof(RoundedGlassImage));
            panel.transform.position=toward(0).GetPoint(.2f); panel.transform.localScale=Vector3.one*.001f;
            panel.GetComponent<RectTransform>().sizeDelta=new Vector2(1840,1250);
            Set(screen,"body",panel);
            Set(screen,"canvasObject",panel);
            Set(screen,"buttons",Array.Empty<UnityEngine.UI.Button>());
            aim(right,left,toward(0),true,false);
            Check(voice.SelectedObjectId==null && interaction.PointedObjectId==null,"nearer visible screen prevents selection through it");
            panel.SetActive(false);

            var selectedBeforeReceipt = views[1].transform.position;
            var sequenceRequest = Guid.NewGuid().ToString("N");
            ((HashSet<string>)Get(voice,"voiceRequests")).Add(sequenceRequest);
            typeof(VoiceUiAdapter).GetMethod("OnAnswered",Private).Invoke(voice,new object[]{new CommandAnswer {
                RequestId=sequenceRequest,Op="voice.run",Outcome="applied",SelectionSpecified=true,SelectedId=views[1].ObjectId }});
            Check(voice.SelectedObjectId==views[1].ObjectId && views[1].transform.position==selectedBeforeReceipt,
                "applied chain receipt selects the exact final object without dragging it");
            voice.ClearObjectSelection();

            var now=DateTime.UtcNow;
            core=new VoiceSession(new VoiceSessionOptions { AskHost=false, PointerDwell=TimeSpan.FromSeconds(.5) },()=>now);
            Set(voice,"session",core); Invoke(voice,"OnScene");
            core.Hear(new RecognitionResult("rotate it ninety degrees around x",1));
            Check(core.Pending!=null,"missing-target voice command waits");
            voice.SetControllerPointer(views[0].ObjectId); now=now.AddSeconds(.6);
            voice.SetControllerPointer(views[0].ObjectId);
            Check(core.Pending==null,"stationary controller pointing advances actual pending-target dwell");
            voice.SelectObject(views[0].ObjectId); Invoke(voice,"SuspendObjectTargeting");
            Check((string)Get(voice,"pointerId")==null && voice.SelectedObjectId==views[0].ObjectId,"focus loss clears transient pointer while explicit identity stays latched");
            host.Handle(new HostEvent(HostEventKind.Closed) {Text="isolated regression"});
            Check(voice.SelectedObjectId==null,"disconnect clears explicit selection");
            Check(!voice.SelectObject(views[0].ObjectId),"stale scene cannot be selected");
            host.Handle(decoded); voice.SelectObject(views[0].ObjectId);
            host.Handle(new HostEvent(HostEventKind.Welcome) {DocumentId=Guid.NewGuid().ToString("N"),OpenEpoch=Guid.NewGuid().ToString("N")});
            Check(voice.SelectedObjectId==null,"new document/epoch cannot inherit old selected UUID");
            Debug.Log("VOICE_OBJECT_SELECTION_CHECKS PASS both_controller_mesh_rays trigger_select_no_drag persistent_target public_arm_menu_clear UI_screen_occlusion grip_preserved dwell focus disconnect document_epoch native_invariant");
        }
        finally
        {
            // Fixture never enables a Host, mic, Player or capture helper.
            foreach(var go in Resources.FindObjectsOfTypeAll<GameObject>())
                if(go!=null && !existing.Contains(go) && !EditorUtility.IsPersistent(go)) UnityEngine.Object.DestroyImmediate(go);
        }
    }

    public static void Windows()
    {
        Run();
        P2Checks.Windows();
        Debug.Log("VOICE_SELECTION_BUILD_RESULT Succeeded errors=0 cumulative_P2_P1=True");
    }
}

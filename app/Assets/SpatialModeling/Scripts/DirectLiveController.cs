using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.XR;

namespace SpatialModeling
{
    // Controller input compiles bounded parameters; the host alone changes native
    // geometry. Every parameter is cumulative from the immutable gesture start.
    public sealed class DirectLiveController
    {
        public const int MaximumSelectionSegments=512;
        readonly HostScene scene;
        readonly PreviewInteraction preview;
        readonly PreviewSpatialDrawing drawing;
        readonly Action<string> selectCommitted;
        public readonly NativeSpatialSelection Selection = new NativeSpatialSelection();
        public readonly LiveModelEditSession Session = new LiveModelEditSession();
        readonly Dictionary<string,WorkspaceObjectView> views = new Dictionary<string,WorkspaceObjectView>();
        readonly Dictionary<string,Matrix4x4> maps = new Dictionary<string,Matrix4x4>();
        sealed class ScaleContact { public WorkspaceSurfaces.Surface Surface; public Vector3 NativePoint; }
        readonly Dictionary<string,ScaleContact> scaleContacts=new Dictionary<string,ScaleContact>();
        readonly List<Vector3> knifePath = new List<Vector3>();
        readonly List<LineRenderer> handles = new List<LineRenderer>();
        readonly List<LineRenderer> selectionLines = new List<LineRenderer>();
        readonly DirectRotationHandles rotationHandles = new DirectRotationHandles();
        readonly DirectTranslationHandles translationHandles=new DirectTranslationHandles();
        readonly LiveScaleFeedback scaleFeedback=new LiveScaleFeedback();
        readonly DirectToolGuides toolGuides=new DirectToolGuides();
        readonly List<Transform> scaleEnds=new List<Transform>();
        DirectToolGuides.Frame guideFrame;
        int[] gestureIndices=Array.Empty<int>();
        Vector3 gesturePivot,metricDirectionNative;
        Vector3? hoverPoint,snapPoint;
        int hoverIndex=-1;
        string hoverComponent,pressBlocked;
        bool attempted,attemptReported,normalPicked,gestureNormalConstrained,nativeMirrored,controllerCancelled,gestureHandle;
        Vector3 normalPickNative;
        Vector3[] gestureAxes;
        Vector3 gestureDisplayPivot;
        DirectTranslationHandles.Frame translationPickFrame,translationGestureFrame;
        int translationAxis=-1;
        bool translationPickedArrow;
        DirectRotationHandles.Frame rotationPickFrame;
        DirectRotationHandles.Hit rotationPick;
        DirectRotationHandles.Gesture rotationGesture;
        int highlightedRotationAxis=-1;
        GameObject handleRoot;
        GameObject selectionRoot;
        Material handleMaterial;
        Material axisMaterial;
        WorkspaceObjectView picked;
        JObject frozenModel, operation;
        JArray targets;
        Matrix4x4 primaryMap, projection;
        Quaternion primaryNativeRotation;
        Ray firstRay;
        Ray lastRay;
        JObject lastParameters;
        Vector3 startPoint,currentPoint,commonPivot;
        Vector3? gizmoAxis;
        Vector3? gizmoPlaneNormal;
        bool[] gizmoConstraint;
        XRNode ownerHand;
        string context, identity, boundId;
        int pickedIndex=-1,gestureEpoch;
        string pickedComponent="object";
        float depth,nextUpdate,lastTransportAt,nextKeepAlive;
        bool enabled,held,moved,waiting,dirtySelection,terminalObserved;
        public bool Enabled => enabled;
        public bool Gesturing => held;
        public bool Busy => Session.Busy||waiting;
        public bool Available => (bool?)drawing.NativeState["model_edit"]?["live_supported"]==true;
        public bool HasLiveProtocol => Model?["live_supported"]!=null;
        public event Action<string> UnavailableAttempt;
        public event Action<string> BlockedAttempt;
        public string Notice { get; private set; } = "Choose a native Blender tool";
        JObject Model => drawing.NativeState["model_edit"] as JObject;
        public DirectLiveController(HostScene host,PreviewInteraction input,PreviewSpatialDrawing native,Action<string> committed)
        {scene=host;preview=input;drawing=native;selectCommitted=committed;Session.Configure(native.Session);Session.Changed+=Changed;}
        public void SetEnabled(bool value)
        {enabled=value;if(!value){Cancel("Editing mode ended");Selection.SetAdditive(false);HideHandles();}}
        string Identity()=>drawing.Session.RequestIdentity?.ToString(Formatting.None)??"";
        static string ToolContext(JObject model,bool objectSelection=false)
        {
            var value=new JObject();foreach(string name in new[] {"native_tool","mode","component"})value[name]=model?[name]?.DeepClone();
            // Object selection may intentionally remove or restore the native
            // active object. Its derived settings disappear/reappear with it.
            // The host still fences the complete native selection transaction;
            // do not cancel its own selection echo as an external tool change.
            if(!objectSelection)value["settings"]=model?["settings"]?.DeepClone();
            if((string)model?["mode"]=="EDIT_MESH")value["active_object_id"]=model["active_object_id"]?.DeepClone();
            // These are derived from the active geometry. An acknowledged own
            // rotation/selection legitimately changes them; the frozen operation
            // retains the original basis and pivot for the entire gesture.
            if(value["settings"] is JObject settings){settings.Remove("pivot_m");settings.Remove("orientation_matrix");settings.Remove("native_context_fingerprint");settings.Remove("native_context_fingerprint_unavailable");}
            return value.ToString(Formatting.None);
        }
        bool ObjectSelectionOperation => (bool?)operation?["selection_only"]==true&&(string)operation?["tool"]=="object.selection";
        public void Tick()
        {
            if(!HasLiveProtocol&&!Busy&&!held)return;
            if(!held&&!Session.Busy)
                Selection.ObserveNative(Model,drawing.Session.Objects,!dirtySelection);
            if(!held&&!Session.Busy&&!waiting&&dirtySelection&&picked!=null&&drawing.NativeStateCurrent)
                SynchronizeSelection();
            if(held||Session.Busy)
            {
                string cause=scene==null?"scene_missing":!scene.IsCurrent?"scene_stale":!scene.DisplayPlacementReady?"placement_not_ready":
                    !drawing.NativeStateCurrent?"native_state_stale":identity!=Identity()?"document_identity_changed":
                    context!=ToolContext(Model,ObjectSelectionOperation)?"native_tool_context_changed":drawing.NativeModalActive?"native_modal_active":null;
                if(cause==null&&held&&picked!=null&&!DirectModelEditMath.SameMatrix(primaryMap,picked.NativeToDisplayMatrix))cause="active_display_map_changed";
                if(cause==null)foreach(var entry in views)
                    if(entry.Value==null){cause="selected_view_missing";break;}
                    else if(entry.Value.LivePresentationConflict){cause="selected_presentation_conflict";break;}
                    else if(!DirectModelEditMath.SameMatrix(maps[entry.Key],entry.Value.NativeToDisplayMatrix)){cause="selected_display_map_changed";break;}
                if(cause==null&&scaleContacts.Count>0&&!ScaleContactsCurrent())cause="scale_contact_plane_changed";
                if(cause!=null)CancelWithCause("Native document, tool, settings, geometry or placement changed; cancelling live edit",cause);
            }
            if(Session.Busy&&Time.unscaledTime-lastTransportAt>10f){lastTransportAt=Time.unscaledTime;Session.Timeout();}
            if(held&&Session.Active&&Time.unscaledTime>=nextKeepAlive)
            {nextKeepAlive=Time.unscaledTime+4f;Session.KeepAlive();}
            if(enabled&&!held&&!Busy){DrawHandles();DrawSelection();Notice=ToolLabel();}
            else
            {
                HideHandles();
                if(enabled&&held&&rotationGesture!=null)rotationHandles.Draw(rotationGesture.Frozen,rotationGesture.Axis);
                if(enabled&&held&&translationGestureFrame!=null)translationHandles.Draw(translationGestureFrame,translationAxis);
                if(enabled&&held&&ToolOf(frozenModel).EndsWith(".scale",StringComparison.Ordinal))DrawLinearHandles("mesh.scale",gestureDisplayPivot,gestureAxes);
            }
            if(scaleFeedback.Visible)scaleFeedback.Draw(currentPoint,Camera.main);
            DrawGuides();
        }
        public void Receive(JObject message)
        {
            string type=(string)message?["type"];
            if((type=="scene.update"||type=="scene.snapshot")&&(held||Session.Busy))
            {
                bool own=Session.OwnsEcho(message);
                if(!own&&message?["payload"]?["objects"] is JArray changed)
                    foreach(JObject obj in changed)
                        if(views.ContainsKey((string)obj["id"])&&(long?)obj["generation"]!=(long?)drawing.Session.Objects[(string)obj["id"]]?["generation"])
                            Cancel("An unrelated native update changed a live target");
            }
            Session.Receive(message);
            if(type=="welcome"||type=="connection.closed")Cancel("Native connection changed");
        }
        void Changed()
        {
            lastTransportAt=Time.unscaledTime;
            if(scaleFeedback.Visible)scaleFeedback.Accept(Session.AcknowledgedParameters);
            if(Session.Active&&boundId==null)
            {
                boundId=Session.EditSessionId;
                foreach(var view in views.Values)if(view!=null)view.BeginLivePresentation(boundId,drawing.Session.ActorId);
            }
            if(!Session.Busy&&!terminalObserved&&operation!=null)
            {
                if(attempted&&!controllerCancelled&&Session.Phase!="committed")Refuse(false,Session.Notice);
                terminalObserved=true;
                foreach(var view in views.Values)if(view!=null&&boundId!=null)view.EndLivePresentation(boundId,Session.Phase=="committed");
                boundId=null;held=waiting=false;rotationGesture=null;translationGestureFrame=null;scaleContacts.Clear();scaleFeedback.Hide();
                if(Session.Phase=="committed")
                {
                    dirtySelection=false;
                    string final=(string)Session.AppliedSelection?["id"];
                    if(!string.IsNullOrEmpty(final))selectCommitted?.Invoke(final);
                }
                Selection.InvalidateIntent();Notice=Session.Notice;
            }
        }
        void SynchronizeSelection()
        {
            if(!Available){dirtySelection=false;return;}
            var requested=Selection.Snapshot();var admitted=Selection.Targets();
            if(!admitted.OfType<JObject>().Any(row=>(string)row["id"]==picked.ObjectId)
                &&drawing.Session.Objects.TryGetValue(picked.ObjectId,out var pickRecord))
                admitted.Add(new JObject { ["id"]=picked.ObjectId,["generation"]=pickRecord["generation"] });
            if(admitted.Count==0){dirtySelection=false;return;}
            targets=admitted;
            views.Clear();maps.Clear();foreach(JObject row in targets)
            {var view=FindView((string)row["id"]);if(view!=null){views[view.ObjectId]=view;maps[view.ObjectId]=view.NativeToDisplayMatrix;}}
            frozenModel=(JObject)Model.DeepClone();identity=Identity();context=ToolContext(frozenModel,Selection.Component=="object");
            operation=new JObject { ["tool"]=Selection.Component=="object"?"object.selection":"mesh.selection",
                ["native_tool"]=frozenModel["native_tool"],["mode"]=frozenModel["mode"],["target_id"]=picked.ObjectId,
                ["targets"]=new JArray(admitted.OfType<JObject>().Select(row=>(object)(string)row["id"])),
                ["selection"]=requested,["selection_only"]=true,["topology_token"]=frozenModel["topology_token"],
                ["settings"]=frozenModel["settings"]?.DeepClone()??new JObject() };
            terminalObserved=false;boundId=null;waiting=true;int requestedGesture=gestureEpoch;
            void BeginSelection()
            {
                if(requestedGesture!=gestureEpoch||!enabled)return;waiting=false;
                if(!ValidStart()){dirtySelection=false;Notice="Selection context changed; select again";return;}
                dirtySelection=false;
                if(!Session.Begin(operation,targets)){dirtySelection=false;Notice=Session.Notice;return;}
                Session.Update(new JObject());Session.Commit();
            }
            if(drawing.NativeCommandReady)BeginSelection();
            else preview.HandoffNativeCommand(BeginSelection,reason=>{if(requestedGesture==gestureEpoch){waiting=false;dirtySelection=false;Notice=reason;}},true);
        }
        public bool Route(XRNode hand,Ray ray,bool trigger,bool pressed,bool grip,Vector2 axis,float nearest,out float distance)
        {
            distance=0;if(!enabled&&!Busy)return false;
            if(held)
            {
                if(hand!=ownerHand)return false;distance=depth;
                if(grip){Cancel("Grip cancelled live editing; wait for native rollback, then release and re-grip to arrange");return Session.Busy;}
                currentPoint=ray.GetPoint(depth);
                lastRay=ray;
                rotationGesture?.Update(ray);
                if(trigger)
                {
                    if(Mathf.Abs(axis.y)>.2f){depth=Mathf.Max(.08f,depth+axis.y*Time.unscaledDeltaTime*.5f);currentPoint=ray.GetPoint(depth);}
                    if(!attempted&&(rotationGesture!=null?Mathf.Abs(rotationGesture.AngleDegrees)>=.8f:Vector3.Distance(startPoint,currentPoint)>=.003f))
                    {attempted=true;StartMovement();}
                    if(moved&&!waiting&&Session.Busy&&Time.unscaledTime>=nextUpdate)
                    {QueueParameters(ray);nextUpdate=Time.unscaledTime+.035f;}
                    Notice=waiting?"Releasing native input; keep holding the trigger":Session.Busy?Session.Notice:Notice;
                    return true;
                }
                held=false;
                if(!moved)
                {
                    scaleFeedback.Hide();
                    if(attempted||!Available||pressBlocked!=null){translationGestureFrame=null;rotationGesture=null;return true;}
                    if(translationGestureFrame!=null){translationGestureFrame=null;Notice="Hold a coloured Move arrow and aim along its axis";return true;}
                    if(rotationGesture!=null){rotationGesture=null;Notice="Hold a coloured rotation ring and move around it to rotate";return true;}
                    if(gestureHandle){Notice="Hold the visible tool handle and move to edit; tap the model body to change selection";return true;}
                    Selection.Pick(picked.ObjectId,picked.Generation,pickedComponent,pickedIndex,(string)frozenModel["topology_token"],false);
                    dirtySelection=true;Selection.InvalidateIntent();
                    if(pickedComponent=="object")
                    {
                        if(Selection.ObjectIds.Count==0)FindFirstVoice()?.ClearObjectSelection();
                        else selectCommitted?.Invoke(Selection.ActiveId);
                    }
                    Notice="Selected "+Selection.ObjectIds.Count+" object(s), "+Selection.Indices.Count+" "+pickedComponent+" element(s) · SHIFT: add/remove";
                    return true;
                }
                if(waiting||!Session.Active||Session.Sequence==0)
                {Cancel("Released before acknowledged live preview; no edit committed");return true;}
                QueueParameters(ray);
                if(Session.Active&&moved){Session.Commit();Notice="Finishing native edit · one Undo on acknowledgement";}
                return true;
            }
            if(Session.Busy)
            {Notice=Session.Notice;distance=4;return true;}
            if(waiting){distance=4;return true;}
            if(grip)return false;
            var view=scene.PickObject(ray,out float hitDistance);
            string routeTool=(string)Model?["tool"]??CanonicalTool((string)Model?["native_tool"],(string)Model?["component"])??"";
            bool ownMoveFence=view!=null&&view.ObjectId==Selection.ActiveId&&Mathf.Abs(hitDistance-nearest)<.0005f
                &&(routeTool.EndsWith(".translate",StringComparison.Ordinal)||routeTool.EndsWith(".scale",StringComparison.Ordinal)||routeTool=="mesh.extrude");
            float moveArrowLimit=nearest;
            if(ownMoveFence)
            {
                // Handles render over their own selected mesh, including a
                // thick model whose front is far from its tool pivot. Admit
                // that visible handle within the existing 4m interaction range;
                // every independent surface still remains an occlusion fence.
                moveArrowLimit=4f;
                if(preview.RaycastUiOnly(ray,out float previewUiDistance))moveArrowLimit=Mathf.Min(moveArrowLimit,previewUiDistance);
                var blender=UnityEngine.Object.FindFirstObjectByType<BlenderScreen>();
                if(blender!=null&&blender.RaycastSurface(ray,out float menuDistance))moveArrowLimit=Mathf.Min(moveArrowLimit,menuDistance);
                if(scene.Table!=null)
                {
                    if(scene.Table.RaycastControls(ray,out float handMenuDistance))moveArrowLimit=Mathf.Min(moveArrowLimit,handMenuDistance);
                    if(scene.Table.Guide!=null&&scene.Table.Guide.Raycast(ray,out float guideDistance))moveArrowLimit=Mathf.Min(moveArrowLimit,guideDistance);
                }
                var workspace=scene.GetComponent<WorkspaceArrangement>();
                if(workspace?.Surfaces!=null&&workspace.Surfaces.RaycastLevel(ray,out float planeDistance)!=null)moveArrowLimit=Mathf.Min(moveArrowLimit,planeDistance);
                foreach(var other in scene.ObjectViews)
                {
                    if(other==null||other==view||!other.gameObject.activeInHierarchy)continue;
                    var collider=other.GetComponent<MeshCollider>();
                    if(collider!=null&&collider.enabled&&collider.Raycast(ray,out var obstruction,moveArrowLimit))
                        moveArrowLimit=Mathf.Min(moveArrowLimit,obstruction.distance);
                }
            }
            bool handleHit=TryHandle(ray,nearest,out var handleAxis,out var constraint,out float handleDistance,moveArrowLimit);
            bool rotationRing=handleHit&&((string)Model?["tool"]??"").EndsWith(".rotate",StringComparison.Ordinal);
            bool ownMoveArrow=handleHit&&(translationPickedArrow||normalPicked||routeTool.EndsWith(".scale",StringComparison.Ordinal))&&ownMoveFence;
            if(handleHit&&(view==null||handleDistance<=hitDistance+.015f||(rotationRing||ownMoveArrow)&&view.ObjectId==Selection.ActiveId))
            {view=FindView(Selection.ActiveId);hitDistance=handleDistance;}
            else handleHit=false;
            if(view==null||hitDistance>nearest+.0005f&&!ownMoveArrow){hoverPoint=null;hoverIndex=-1;return false;}
            distance=hitDistance;Notice=ToolLabel();
            hoverPoint=null;hoverIndex=-1;hoverComponent=null;
            if(Model!=null&&view.ObjectId==(string)Model["active_object_id"]&&(string)Model["mode"]=="EDIT_MESH"
                &&DirectModelEditMath.TryPick(Model,view.NativeToDisplayMatrix,ray,.012f,out int hover,out _,out var hoverAt))
            {hoverPoint=hoverAt;hoverIndex=hover;hoverComponent=(string)Model["component"];}
            if(!pressed)return true;
            if(!drawing.NativeStateCurrent||Model==null){Notice="Wait for current native Blender tool state";return true;}
            picked=view;ownerHand=hand;frozenModel=(JObject)Model.DeepClone();primaryMap=view.NativeToDisplayMatrix;primaryNativeRotation=view.NativeRotation;
            pickedComponent=(string)frozenModel["component"]??"object";pickedIndex=-1;
            pressBlocked=null;attempted=attemptReported=controllerCancelled=false;snapPoint=null;
            bool mesh=(string)frozenModel["mode"]=="EDIT_MESH";
            if(mesh)
            {
                bool existingHandle=handleHit&&Selection.ActiveId==view.ObjectId&&Selection.Component==pickedComponent&&Selection.Indices.Count>0;
                bool knife=(string)frozenModel["tool"]=="mesh.knife";
                bool validPick=existingHandle;
                if(existingHandle)pickedIndex=Selection.Indices.Last();
                else if(knife)validPick=TryKnifeStart(ray,out pickedIndex);
                else validPick=DirectModelEditMath.TryPick(frozenModel,primaryMap,ray,.012f,out pickedIndex,out _,out _);
                if((string)frozenModel["active_object_id"]!=view.ObjectId||!validPick)
                {pressBlocked="Aim at a visible native "+pickedComponent+" on the active Blender object";Notice=pressBlocked;}
            }
            depth=hitDistance;startPoint=currentPoint=ray.GetPoint(depth);firstRay=ray;
            lastRay=ray;lastParameters=null;
            gizmoConstraint=handleHit?constraint:null;
            gestureHandle=handleHit;
            bool plane=handleHit&&constraint!=null&&constraint.Count(value=>value)==2;
            gizmoAxis=handleHit&&!plane?handleAxis:(Vector3?)null;gizmoPlaneNormal=plane?handleAxis:(Vector3?)null;
            rotationGesture=handleHit&&rotationRing?new DirectRotationHandles.Gesture(rotationPickFrame,rotationPick,ray):null;
            translationGestureFrame=handleHit&&translationPickedArrow?translationPickFrame:null;
            gestureNormalConstrained=handleHit&&normalPicked;
            nativeMirrored=view.NativeScale.x*view.NativeScale.y*view.NativeScale.z<0;
            var viewRight=Vector3.Cross(Vector3.up,ray.direction).normalized;if(viewRight.sqrMagnitude<.1f)viewRight=Vector3.right;
            metricDirectionNative=gestureNormalConstrained?normalPickNative:primaryMap.inverse.MultiplyVector(viewRight).normalized;
            gestureIndices=Selection.ActiveId==view.ObjectId&&Selection.Component==pickedComponent?Selection.Indices.ToArray():Array.Empty<int>();
            if(gestureIndices.Length==0&&pickedIndex>=0)gestureIndices=new[]{pickedIndex};
            gesturePivot=primaryMap.inverse.MultiplyPoint3x4(SelectionPivotDisplay());
            gestureDisplayPivot=SelectionPivotDisplay();gestureAxes=new[]{Axis(0),Axis(1),Axis(2)};
            if(((string)frozenModel["tool"]??"").EndsWith(".scale",StringComparison.Ordinal)&&(bool?)frozenModel["available"]==true)scaleFeedback.Begin();
            else scaleFeedback.Hide();
            context=ToolContext(frozenModel);identity=Identity();operation=null;targets=null;
            views.Clear();maps.Clear();scaleContacts.Clear();knifePath.Clear();boundId=null;terminalObserved=false;
            held=true;moved=waiting=false;gestureEpoch++;Selection.InvalidateIntent();return true;
        }
        VoiceUiAdapter FindFirstVoice()=>UnityEngine.Object.FindFirstObjectByType<VoiceUiAdapter>();
        string ToolLabel()
        {
            if((bool?)Model?["available"]!=true)return (string)Model?["reason"]??"Choose a native tool";
            string selected=Selection.Component=="object"?Selection.ObjectIds.Count+" object(s)":Selection.Indices.Count+" "+Selection.Component+" element(s)";
            string instruction=((string)Model["tool"]??"").EndsWith(".rotate",StringComparison.Ordinal)?"hold a coloured ring + move around it: rotate":"hold + aim: live edit";
            return ((string)Model["tool"]??(string)Model["native_tool"])+" · "+selected+" selected · trigger tap: select · "+instruction+" · grip: cancel / arrange";
        }
        WorkspaceObjectView FindView(string id)
        {foreach(var view in scene.ObjectViews)if(view!=null&&view.ObjectId==id)return view;return null;}
        void StartMovement()
        {
            string tool=ToolOf(frozenModel);
            string canonical=CanonicalTool((string)frozenModel["native_tool"],pickedComponent);
            if(canonical==null||!Available&&(string)frozenModel["mode"]!="EDIT_MESH")
            {Refuse(true,(string)frozenModel["reason"]??"This Blender tool is not available for direct 3D editing. Use the Blender view.");return;}
            if(!Available||!SupportedOperation(tool))
            {Refuse(false,(string)frozenModel["reason"]??"Choose mesh Edit mode and the appropriate vertex, edge or face selection mode in Blender for this tool.");return;}
            if(tool.EndsWith(".selection",StringComparison.Ordinal))
            {Refuse(true,"Spatial box, lasso and circle sweep selection is not available yet. Use trigger taps + SHIFT to select multiple elements, or use the Blender 2D view.");return;}
            if((bool?)frozenModel["available"]!=true)
            {string reason=(string)frozenModel["reason"]??"Native tool unavailable";Refuse(UnavailableReason(reason),reason);return;}
            if(pressBlocked!=null){Refuse(false,pressBlocked);return;}
            var prospective=Selection.ActiveId==picked.ObjectId&&Selection.Component==pickedComponent&&
                (Selection.Contains(picked.ObjectId,pickedComponent,pickedIndex)||Selection.Additive)?Selection.Indices.ToList():new List<int>();
            if(pickedComponent!="object"&&!prospective.Contains(pickedIndex))prospective.Add(pickedIndex);
            if(!ValidateComponents(tool,prospective,out string blocked)){Refuse(false,blocked);return;}
            Selection.Pick(picked.ObjectId,picked.Generation,pickedComponent,pickedIndex,(string)frozenModel["topology_token"],true);
            gestureIndices=Selection.Indices.ToArray();
            targets=Selection.Targets();foreach(JObject target in targets)
            {
                var view=FindView((string)target["id"]);if(view==null){Refuse(false,"A selected floating object is unavailable. Wait for the current Blender scene, then select again.");Cancel(Notice);return;}
                views[view.ObjectId]=view;maps[view.ObjectId]=view.NativeToDisplayMatrix;
            }
            commonPivot=SelectionPivotDisplay();
            gesturePivot=primaryMap.inverse.MultiplyPoint3x4(commonPivot);
            gestureDisplayPivot=commonPivot;gestureAxes=new[]{Axis(0),Axis(1),Axis(2)};
            CaptureScaleContacts(tool);
            var settings=frozenModel["settings"] is JObject nativeSettings?(JObject)nativeSettings.DeepClone():new JObject();
            if((string)frozenModel["native_tool"]=="builtin.extrude_individual")settings["individual"]=true;
            if(gizmoConstraint!=null)settings["constraint_axis"]=new JArray(gizmoConstraint);
            if(gestureNormalConstrained)settings["constraint_axis"]=new JArray(false,false,false);
            operation=new JObject { ["tool"]=tool,["native_tool"]=frozenModel["native_tool"],["mode"]=frozenModel["mode"],
                ["target_id"]=picked.ObjectId,["targets"]=new JArray(Selection.ObjectIds),
                ["selection"]=new JObject { ["component"]=pickedComponent,["indices"]=new JArray(Selection.Indices) },
                ["topology_token"]=frozenModel["topology_token"],["settings"]=settings };
            Debug.Log("P25_LIVE_GESTURE tool="+DiagnosticFlag(tool)+" handle="+(translationGestureFrame!=null?"move_axis":gestureHandle?"tool_handle":"body")
                +" constraint="+(gizmoConstraint==null?"native":string.Concat(gizmoConstraint.Select(value=>value?"1":"0"))));
            var displayMaps=new JObject();foreach(var pair in maps)displayMaps[pair.Key]=MatrixArray(pair.Value);
            operation["display_maps"]=displayMaps;
            var camera=Camera.main;
            projection=camera!=null?camera.projectionMatrix*camera.worldToCameraMatrix*primaryMap*SwapMatrix():Matrix4x4.identity;
            AddKnifePoint(firstRay);moved=true;Selection.InvalidateIntent();int requestedGesture=gestureEpoch;
            void Begin()
            {
                if(!held||requestedGesture!=gestureEpoch)return;waiting=false;
                if(!ValidStart()){Refuse(false,"Native context changed during input handoff. Wait for the current Blender scene and try again.");Cancel(Notice);return;}
                if(!Session.Begin(operation,targets)){Refuse(false,Session.Notice);Cancel(Session.Notice);return;}
                QueueParameters(lastRay);
            }
            if(drawing.NativeCommandReady)Begin();
            else
            {waiting=true;preview.HandoffNativeCommand(Begin,reason=>{if(requestedGesture==gestureEpoch){Refuse(false,reason);Cancel(reason);}},true);}
        }
        static bool SupportedOperation(string tool)
        {
            return new[]{"object.translate","object.rotate","object.scale","object.selection","mesh.translate","mesh.rotate","mesh.scale","mesh.selection",
                "mesh.extrude","mesh.inset","mesh.bevel","mesh.loop_cut","mesh.knife","mesh.merge","mesh.dissolve","mesh.delete"}.Contains(tool);
        }
        static bool UnavailableReason(string reason)
        {
            string text=(reason??"").ToLowerInvariant();
            return text.Contains("unsupported tool")||text.Contains("unsupported feature")||text.Contains("not implemented")||text.Contains("not available yet");
        }
        void Refuse(bool unavailable,string reason)
        {
            if(string.IsNullOrWhiteSpace(reason))reason=unavailable?"This Blender feature is not available for direct 3D editing. Use the Blender 2D view.":"Choose a compatible tool, selection and settings in Blender, then try again.";
            reason=new string(reason.Where(c=>!char.IsControl(c)||c=='\n').ToArray());
            Notice=reason;scaleFeedback.Hide();
            if(attemptReported)return;attemptReported=true;
            if(unavailable)UnavailableAttempt?.Invoke(reason);else BlockedAttempt?.Invoke(reason);
        }
        bool ValidateComponents(string tool,IReadOnlyList<int> indices,out string reason)
        {
            reason=null;if(!tool.StartsWith("mesh.",StringComparison.Ordinal))return true;
            if((string)frozenModel["mode"]!="EDIT_MESH"){reason="Switch Blender to mesh Edit mode before using this tool on the floating model.";return false;}
            string collection=pickedComponent=="vertex"?"vertices":pickedComponent=="edge"?"edges":pickedComponent=="face"?"faces":null;
            var geometry=collection==null?null:frozenModel[collection] as JArray;
            if(geometry==null||indices.Count==0||indices.Any(index=>!geometry.OfType<JObject>().Any(item=>(int?)item["index"]==index)))
            {reason="Select visible native mesh elements before editing. Refresh the Blender view if the selection changed.";return false;}
            bool individual=(string)frozenModel["native_tool"]=="builtin.extrude_individual"||(bool?)frozenModel["settings"]?["individual"]==true;
            if((tool=="mesh.inset"||tool=="mesh.extrude"&&individual)&&pickedComponent!="face")
            {reason="Select faces in Blender for "+(tool=="mesh.inset"?"Inset Faces":"Extrude Individual Faces")+".";return false;}
            if(tool=="mesh.extrude"&&individual)
            {
                var settings=frozenModel["settings"];
                if(settings?["constraint_axis"] is JArray constraints&&constraints.Values<bool>().Any(value=>value)||
                    (bool?)settings?["use_snap"]==true||((float?)settings?["proportional_radius_m"]??0)>0)
                {reason="Individual face extrusion uses each face normal. Turn off axis constraints, snapping and proportional editing for this gesture, then transform separately.";return false;}
            }
            if(tool=="mesh.bevel"&&(string)frozenModel["settings"]?["offset_type"]=="PERCENT")
            {reason="Choose a distance based Bevel width in Blender (Offset, Width, Depth or Absolute), or use the Blender view for percentage bevels.";return false;}
            if(tool=="mesh.merge")
            {
                if(pickedComponent!="vertex"||indices.Count<2){reason="Merge needs at least two selected vertices. Use vertex selection and SHIFT to add vertices first.";return false;}
                string variant=(string)frozenModel["settings"]?["variant"]??"CENTER";
                if((variant=="FIRST"||variant=="LAST")&&(bool?)frozenModel["selection"]?["order_complete"]!=true)
                {reason="Merge "+variant+" needs a complete ordered Blender vertex selection. Select the destination in Blender or choose Center / Collapse / By Distance.";return false;}
            }
            if(tool=="mesh.loop_cut")
            {
                if(pickedComponent!="edge"||indices.Count!=1){reason="Loop Cut needs exactly one selected edge on a visible quad ring. Select one edge first.";return false;}
                var guide=DirectToolGuides.Build(new DirectToolGuides.Frame{Tool=tool,Component=pickedComponent,Model=frozenModel,Indices=indices.ToArray(),Map=primaryMap});
                if(!guide.Valid||!string.IsNullOrEmpty(guide.Limitation)){reason=string.IsNullOrEmpty(guide.Limitation)?"Choose an edge with a continuous quad ring for Loop Cut.":guide.Limitation;return false;}
            }
            return true;
        }
        bool ValidStart()
        {
            if(!drawing.NativeCommandReady||identity!=Identity()||context!=ToolContext(Model,ObjectSelectionOperation))return false;
            foreach(JObject target in targets)
                if(!drawing.Session.Objects.TryGetValue((string)target["id"],out var record)||(long?)record["generation"]!=(long?)target["generation"])return false;
            return true;
        }
        void QueueParameters(Ray ray)
        {
            var parameters=Parameters(ray);
            if(parameters!=null&&!JToken.DeepEquals(parameters,lastParameters)&&Session.Update(parameters))lastParameters=(JObject)parameters.DeepClone();
        }
        public JObject Parameters(Ray ray)
        {
            if(operation==null)return null;
            string tool=(string)operation["tool"];
            var settings=operation["settings"] as JObject??new JObject();
            Vector3 displayDelta=currentPoint-startPoint;
            if(gizmoAxis.HasValue)displayDelta=Vector3.Project(displayDelta,gizmoAxis.Value);
            if(gizmoPlaneNormal.HasValue)displayDelta=Vector3.ProjectOnPlane(displayDelta,gizmoPlaneNormal.Value);
            Vector3 native=primaryMap.inverse.MultiplyVector(displayDelta);
            if(tool.EndsWith(".translate",StringComparison.Ordinal)||tool=="mesh.extrude")
            {
                snapPoint=null;
                var value=new JObject { ["translation_m"]=DirectModelEditMath.ToWire(native) };
                if(tool=="mesh.extrude")
                {
                    value["individual"]=(bool?)settings["individual"]??false;
                    if ((bool)value["individual"]) value["normal_distance_m"]=Vector3.Dot(native,metricDirectionNative);
                }
                var result=PerTarget(value,(map)=>new JObject { ["translation_m"]=DirectModelEditMath.ToWire(map.inverse.MultiplyVector(displayDelta)) });
                if((bool?)settings["use_snap"]==true&&(bool?)settings["use_snap_translate"]!=false&&TrySnap(ray,settings,out var snap,out var normal))
                {
                    result["snap_point_m"]=DirectModelEditMath.ToWire(snap);
                    snapPoint=primaryMap.MultiplyPoint3x4(snap);
                    result["snap_target"]=(string)settings["snap_target"]??"CLOSEST";
                    if((bool?)settings["use_snap_align_rotation"]==true&&normal.HasValue)
                    {result["snap_align_rotation"]=true;result["snap_normal"]=DirectModelEditMath.ToWire(normal.Value);}
                    if(result["per_target"] is JObject branches)foreach(var branch in branches.Properties())
                    {
                        branch.Value["snap_point_m"]=DirectModelEditMath.ToWire(snap);branch.Value["snap_target"]=result["snap_target"].DeepClone();
                        if(result["snap_normal"]!=null){branch.Value["snap_normal"]=result["snap_normal"].DeepClone();branch.Value["snap_align_rotation"]=true;}
                    }
                }
                return result;
            }
            if(tool.EndsWith(".rotate",StringComparison.Ordinal))
            {
                Quaternion displayRotation=Quaternion.FromToRotation(firstRay.direction,ray.direction);
                if(gizmoAxis.HasValue)
                    displayRotation=Quaternion.AngleAxis(ScalarDrag(currentPoint-startPoint)*180f,gizmoAxis.Value);
                return PerTarget(RotationFor(primaryMap,displayRotation),map=>RotationFor(map,displayRotation));
            }
            if(tool.EndsWith(".scale",StringComparison.Ordinal))
            {
                float amount=gizmoAxis.HasValue&&gizmoConstraint!=null&&gizmoConstraint.Count(value=>value)==1?
                    Vector3.Dot(displayDelta,gizmoAxis.Value):ScalarDrag(displayDelta);
                float factor=Mathf.Exp(Mathf.Clamp(amount*3,-4.6f,4.6f));
                var selected=gizmoConstraint??(settings["constraint_axis"] as JArray)?.Values<bool>().ToArray();
                if(selected==null||selected.Length!=3||!selected.Any(value=>value))selected=new[] {true,true,true};
                var scale=new JArray(selected[0]?factor:1,selected[1]?factor:1,selected[2]?factor:1);
                var value=ScaleFor(picked.ObjectId,primaryMap,scale,false);
                if(pickedComponent=="object"&&maps.Count>1)
                {var branches=new JObject();foreach(var entry in maps)branches[entry.Key]=ScaleFor(entry.Key,entry.Value,scale,true);value["per_target"]=branches;}
                return value;
            }
            if(tool=="mesh.inset")return new JObject { ["thickness_m"]=native.magnitude,["depth_m"]=0,
                ["individual"]=(bool?)settings["individual"]??false,["outset"]=(bool?)settings["outset"]??false,
                ["even_offset"]=(bool?)settings["even_offset"]??true,["relative_offset"]=(bool?)settings["relative_offset"]??false,
                ["boundary"]=(bool?)settings["boundary"]??true };
            if(tool=="mesh.bevel")return new JObject { ["width_m"]=native.magnitude,
                ["segments"]=(int?)settings["segments"]??1,["profile"]=(float?)settings["profile"]??.5f,
                ["vertices"]=settings["affect"]!=null?(string)settings["affect"]=="VERTICES":pickedComponent=="vertex",["clamp_overlap"]=(bool?)settings["clamp_overlap"]??true,
                ["offset_type"]=(string)settings["offset_type"]??"OFFSET" };
            if(tool=="mesh.loop_cut")return new JObject { ["cuts"]=(int?)settings["cuts"]??1,["slide"]=LoopSlide(native) };
            if(tool=="mesh.knife")
            {
                if(!AddKnifePoint(ray)||knifePath.Count<2)return null;
                return new JObject { ["path_m"]=new JArray(knifePath.Select(p=>(object)DirectModelEditMath.ToWire(p))),
                    ["projection"]=MatrixArray(projection),["cut_through"]=(bool?)settings["cut_through"]??false,
                    ["selected_only"]=(bool?)settings["selected_only"]??false };
            }
            // Menu operations arrive as explicitly armed native intent, never as
            // an inferred/replayed last executed Blender operator.
            if(tool=="mesh.merge")return new JObject { ["variant"]=(string)settings["variant"]??"CENTER",["distance_m"]=(float?)settings["distance_m"]??.0001f };
            if(tool=="mesh.dissolve")return new JObject { ["variant"]=(string)settings["variant"]??"AUTO",["angle_limit"]=(float?)settings["angle_limit"]??.0872665f };
            if(tool=="mesh.delete")return new JObject { ["domain"]=(string)settings["domain"]??(pickedComponent=="vertex"?"VERTS":pickedComponent=="edge"?"EDGES":"FACES") };
            return null;
        }
        JObject PerTarget(JObject primary,Func<Matrix4x4,JObject> compile)
        {
            if(pickedComponent!="object"||maps.Count<2)return primary;
            var values=new JObject();foreach(var entry in maps)values[entry.Key]=compile(entry.Value);
            primary["per_target"]=values;return primary;
        }
        void CaptureScaleContacts(string tool)
        {
            scaleContacts.Clear();if(pickedComponent!="object"||!tool.EndsWith(".scale",StringComparison.Ordinal))return;
            var arrangement=scene!=null?scene.GetComponent<WorkspaceArrangement>():null;
            if(arrangement==null||!arrangement.AssistEnabled||arrangement.Surfaces==null)return;
            foreach(var entry in views)
            {
                var view=entry.Value;var mesh=view.GetComponent<MeshFilter>()?.sharedMesh;
                if(mesh==null||!mesh.isReadable)continue;
                var points=new List<Vector3>();foreach(var vertex in mesh.vertices)points.Add(view.transform.TransformPoint(vertex));
                if(WorkspaceArrangement.TryScaleContact(points,arrangement.Surfaces.Surfaces,out var surface,out var contact))
                    scaleContacts[entry.Key]=new ScaleContact{Surface=WorkspaceArrangement.FreezeScaleSurface(surface),NativePoint=maps[entry.Key].inverse.MultiplyPoint3x4(contact)};
            }
        }
        bool ScaleContactsCurrent()
        {
            var arrangement=scene!=null?scene.GetComponent<WorkspaceArrangement>():null;
            if(arrangement==null||!arrangement.AssistEnabled||arrangement.Surfaces==null)return false;
            foreach(var contact in scaleContacts.Values)
            {bool found=false;foreach(var surface in arrangement.Surfaces.Surfaces)if(WorkspaceArrangement.SameScaleSurface(contact.Surface,surface)){found=true;break;}if(!found)return false;}
            return true;
        }
        JObject ScaleFor(string id,Matrix4x4 map,JArray scale,bool branch)
        {
            var value=new JObject{["scale"]=scale.DeepClone()};
            if(scaleContacts.TryGetValue(id,out var contact))value["pivot_m"]=DirectModelEditMath.ToWire(contact.NativePoint);
            else if(branch)
                value["pivot_m"]=(string)operation?["settings"]?["pivot"]=="INDIVIDUAL_ORIGINS"&&views.TryGetValue(id,out var view)
                    ?DirectModelEditMath.ToWire(view.NativePosition):NativePivot(map);
            return value;
        }
        JObject RotationFor(Matrix4x4 map,Quaternion displayRotation)
        {
            if(rotationGesture!=null)
                return new JObject { ["rotation"]=DirectModelEditMath.ToWire(rotationGesture.NativeRotationFor(map)),["pivot_m"]=NativePivot(map) };
            var settings=operation?["settings"] as JObject;
            bool[] constraints=gizmoConstraint??(settings?["constraint_axis"] as JArray)?.Values<bool>().ToArray();
            int constrained=constraints?.Count(value=>value)??0;
            Quaternion rotation;
            if(constrained==1||constrained==2)
            {
                int axis=Array.FindIndex(constraints,value=>constrained==1?value:!value);
                Vector3 displayAxis=gizmoAxis??FrozenAxis(axis);
                var nativeAxis=map.inverse.MultiplyVector(displayAxis).normalized;
                float angle=ScalarDrag(currentPoint-startPoint)*180f*(map.determinant<0?-1f:1f);
                rotation=Quaternion.AngleAxis(angle,nativeAxis);
            }
            else
            {
                var from=map.inverse.MultiplyVector(firstRay.direction).normalized;
                var to=map.inverse.MultiplyVector(displayRotation*firstRay.direction).normalized;
                rotation=Quaternion.FromToRotation(from,to);
            }
            return new JObject { ["rotation"]=DirectModelEditMath.ToWire(rotation),["pivot_m"]=NativePivot(map) };
        }
        Vector3 FrozenAxis(int index)
        {
            var settings=operation?["settings"] as JObject;
            Vector3 basis=index==0?Vector3.right:index==1?Vector3.forward:Vector3.up;
            if((string)settings?["orientation"]=="LOCAL")basis=primaryNativeRotation*basis;
            if(settings?["orientation_matrix"] is JArray matrix&&matrix.Count==9)
                basis=DirectModelEditMath.ToUnity(new JArray(matrix[index],matrix[3+index],matrix[6+index]));
            return primaryMap.MultiplyVector(basis).normalized;
        }
        JArray NativePivot(Matrix4x4 map)
        {
            var settings=operation?["settings"] as JObject;
            if(settings?["pivot_m"] is JArray pivot)return (JArray)pivot.DeepClone();
            if((string)settings?["pivot"]=="INDIVIDUAL_ORIGINS")
                foreach(var pair in maps)if(DirectModelEditMath.SameMatrix(pair.Value,map)&&views.TryGetValue(pair.Key,out var view))
                    return DirectModelEditMath.ToWire(view.NativePosition);
            return DirectModelEditMath.ToWire(map.inverse.MultiplyPoint3x4(commonPivot));
        }
        Vector3 SelectionPivotDisplay()
        {
            var view=FindView(Selection.ActiveId);if(view==null)return picked!=null?picked.transform.position:Vector3.zero;
            var model=held&&frozenModel!=null?frozenModel:Model;
            if(model?["settings"]?["pivot_m"] is JArray nativePivot)return view.NativeToDisplayMatrix.MultiplyPoint3x4(DirectModelEditMath.ToUnity(nativePivot));
            if(Selection.Component!="object"&&model?["vertices"] is JArray points)
            {
                var ids=new HashSet<int>();
                if(Selection.Component=="vertex")ids.UnionWith(Selection.Indices);
                else if(model[Selection.Component=="edge"?"edges":"faces"] is JArray components)
                    foreach(JObject item in components)if(Selection.Indices.Contains((int)item["index"])&&item["vertices"] is JArray verts)ids.UnionWith(verts.Values<int>());
                Vector3 total=Vector3.zero;int count=0;
                foreach(JObject point in points)if(ids.Contains((int)point["index"]))
                {total+=view.NativeToDisplayMatrix.MultiplyPoint3x4(DirectModelEditMath.ToUnity((JArray)point["position"]));count++;}
                if(count>0)return total/count;
            }
            if((string)model?["settings"]?["pivot"]=="ACTIVE_ELEMENT"||(string)model?["settings"]?["pivot"]=="INDIVIDUAL_ORIGINS")return view.transform.position;
            Vector3 sum=Vector3.zero;int objects=0;Bounds bounds=default;bool haveBounds=false;
            foreach(string id in Selection.ObjectIds)
            {
                var item=FindView(id);if(item==null)continue;sum+=item.transform.position;objects++;
                var renderer=item.GetComponent<Renderer>();if(renderer==null)continue;
                if(!haveBounds){bounds=renderer.bounds;haveBounds=true;}else bounds.Encapsulate(renderer.bounds);
            }
            if((string)model?["settings"]?["pivot"]=="BOUNDING_BOX_CENTER"&&haveBounds)return bounds.center;
            return objects>0?sum/objects:view.transform.position;
        }
        float ScalarDrag(Vector3 delta)
        {var right=Vector3.Cross(Vector3.up,firstRay.direction).normalized;if(right.sqrMagnitude<.1f)right=Vector3.right;return Vector3.Dot(delta,right+Vector3.up);}
        public static float MetricDrag(Matrix4x4 map,Vector3 displayDelta,Vector3 aim)
        {
            if(displayDelta.sqrMagnitude<1e-12f)return 0;
            var right=Vector3.Cross(Vector3.up,aim).normalized;if(right.sqrMagnitude<.1f)right=Vector3.right;
            // The sign/intent lives in the controller view plane, while length
            // is measured in native metres after the frozen inverse map once.
            return map.inverse.MultiplyVector(displayDelta).magnitude*Vector3.Dot(displayDelta.normalized,right+Vector3.up);
        }
        public static Vector3 PerpendicularPoint(Vector3 a,Vector3 b,Vector3 origin)
        {var edge=b-a;return a+edge*Mathf.Clamp01(Vector3.Dot(origin-a,edge)/Mathf.Max(edge.sqrMagnitude,1e-12f));}
        float LoopSlide(Vector3 nativeDelta)
        {
            if(frozenModel["edges"] is JArray edges&&frozenModel["vertices"] is JArray points)
                foreach(JObject edge in edges)if((int)edge["index"]==pickedIndex&&edge["vertices"] is JArray ids&&ids.Count==2)
                {
                    Vector3? a=null,b=null;foreach(JObject point in points)
                    {if((int)point["index"]==(int)ids[0])a=DirectModelEditMath.ToUnity((JArray)point["position"]);if((int)point["index"]==(int)ids[1])b=DirectModelEditMath.ToUnity((JArray)point["position"]);}
                    if(a.HasValue&&b.HasValue){var direction=b.Value-a.Value;return Mathf.Clamp(Vector3.Dot(nativeDelta,direction)/Mathf.Max(direction.sqrMagnitude,1e-10f)*2,-.999f,.999f);}
                }
            return 0;
        }
        bool TrySnap(Ray ray,JObject settings,out Vector3 nativePoint,out Vector3? nativeNormal)
        {
            nativePoint=default;nativeNormal=null;Vector3 bestNative=default;Vector3? bestNormal=null;float best=.015f,bestFace=float.PositiveInfinity;
            var elements=settings["snap_elements"] as JArray??new JArray("VERTEX");
            bool wantsVertex=elements.Values<string>().Contains("VERTEX"),wantsEdge=elements.Values<string>().Any(v=>v=="EDGE"||v=="EDGE_MIDPOINT"||v=="EDGE_PERPENDICULAR"),
                wantsFace=elements.Values<string>().Any(v=>v=="FACE"||v=="FACE_NEAREST");
            bool found=false;
            foreach(var view in scene.ObjectViews)
            {
                if(view==null||!view.gameObject.activeInHierarchy)continue;
                bool self=views.ContainsKey(view.ObjectId);
                if(self&&((bool?)settings["use_snap_self"]!=true||pickedComponent=="object"))continue;
                var geometry=(Model?["snap_geometry"] as JArray)?.OfType<JObject>().FirstOrDefault(item=>(string)item["id"]==view.ObjectId);
                if((bool?)geometry?["in_edit_mode"]==true&&(bool?)settings["use_snap_edit"]==false)continue;
                if((bool?)geometry?["in_edit_mode"]!=true&&(bool?)settings["use_snap_nonedit"]==false)continue;
                if((bool?)settings["use_snap_selectable"]==true&&(bool?)geometry?["selectable"]==false)continue;
                var mesh=view.GetComponent<MeshFilter>()?.sharedMesh;if(mesh==null)continue;
                var collider=view.GetComponent<MeshCollider>();var verts=mesh.vertices;var nativeMap=view.NativeToDisplayMatrix.inverse;
                bool Visible(Vector3 p)
                {
                    var delta=p-ray.origin;float length=delta.magnitude;
                    return collider==null||!collider.Raycast(new Ray(ray.origin,delta.normalized),out var obstruction,length-.00002f);
                }
                void Candidate(Vector3 p)
                {
                    float depth=Vector3.Dot(p-ray.origin,ray.direction.normalized);if(depth<=0||depth>20)return;
                    float miss=Vector3.Distance(p,ray.GetPoint(depth));
                    if(miss<=best&&Visible(p))
                    {
                        best=miss;bestNative=nativeMap.MultiplyPoint3x4(p);found=true;bestNormal=null;
                        if(collider!=null&&collider.Raycast(new Ray(ray.origin,(p-ray.origin).normalized),out var normalHit,Vector3.Distance(p,ray.origin)+.0001f))
                            bestNormal=view.NativeToDisplayMatrix.transpose.MultiplyVector(normalHit.normal).normalized;
                    }
                }
                var nativePoints=new Dictionary<int,Vector3>();
                if(geometry?["vertices"] is JArray actualVertices)foreach(JObject point in actualVertices)
                    nativePoints[(int)point["index"]]=DirectModelEditMath.ToUnity((JArray)point["position"]);
                var excluded=new HashSet<int>();
                if(self)
                {
                    if(pickedComponent=="vertex")excluded.UnionWith(Selection.Indices);
                    else if(frozenModel[pickedComponent=="edge"?"edges":"faces"] is JArray components)
                        foreach(JObject item in components)if(Selection.Indices.Contains((int)item["index"])&&item["vertices"] is JArray ids)
                            excluded.UnionWith(ids.Values<int>());
                }
                if(wantsVertex)
                {
                    if(nativePoints.Count>0)foreach(var point in nativePoints)if(!excluded.Contains(point.Key))Candidate(view.NativeToDisplayMatrix.MultiplyPoint3x4(point.Value));
                    else if(!self)for(int i=0;i<Mathf.Min(verts.Length,32768);i++)Candidate(view.transform.TransformPoint(verts[i]));
                }
                if(wantsEdge)
                {
                    // Exact native edge endpoints; render triangulation diagonals
                    // are never invented as Blender snap targets.
                    if(geometry?["edges"] is JArray actualEdges)foreach(JObject edge in actualEdges)
                        if(edge["vertices"] is JArray ids&&ids.Count==2&&nativePoints.TryGetValue((int)ids[0],out var first)&&nativePoints.TryGetValue((int)ids[1],out var second)
                            &&!excluded.Contains((int)ids[0])&&!excluded.Contains((int)ids[1]))
                        {
                            var a=view.NativeToDisplayMatrix.MultiplyPoint3x4(first);var b=view.NativeToDisplayMatrix.MultiplyPoint3x4(second);
                            if(elements.Values<string>().Contains("EDGE_MIDPOINT"))Candidate((a+b)*.5f);
                            if(elements.Values<string>().Contains("EDGE_PERPENDICULAR"))
                            {
                                // Perpendicular is geometric in Blender world
                                // metres, not in the distorted inspection view.
                                var origin=nativeMap.MultiplyPoint3x4(commonPivot);
                                Candidate(view.NativeToDisplayMatrix.MultiplyPoint3x4(PerpendicularPoint(first,second,origin)));
                            }
                            if(!elements.Values<string>().Contains("EDGE"))continue;
                            var v=b-a;var d=ray.direction.normalized;var offset=a-ray.origin;float along=Vector3.Dot(v,d),den=v.sqrMagnitude-along*along;
                            float t=den>1e-10f?Mathf.Clamp01((along*Vector3.Dot(offset,d)-Vector3.Dot(offset,v))/den):0;
                            Candidate(a+v*t);
                        }
                }
                if(wantsFace&&collider!=null&&collider.Raycast(ray,out var hit,20)&&hit.distance<bestFace)
                {
                    if((bool?)settings["use_snap_backface_culling"]==true&&Vector3.Dot(hit.normal,ray.direction)>=0)continue;
                    bestNative=nativeMap.MultiplyPoint3x4(hit.point);bestNormal=view.NativeToDisplayMatrix.transpose.MultiplyVector(hit.normal).normalized;
                    found=true;best=0;bestFace=hit.distance;
                }
            }
            nativePoint=bestNative;nativeNormal=bestNormal;
            return found;
        }
        bool AddKnifePoint(Ray ray)
        {
            if(frozenModel==null)return false;var model=(JObject)frozenModel.DeepClone();model["component"]="face";
            if(!DirectModelEditMath.TryPick(model,primaryMap,ray,.012f,out _,out _,out var hit))return true;
            var native=primaryMap.inverse.MultiplyPoint3x4(hit);
            if(knifePath.Count>0&&Vector3.Distance(knifePath[knifePath.Count-1],native)<.001f)return true;
            if(knifePath.Count>=128)
            {Refuse(false,"Knife stroke is too long; use a shorter stroke");CancelWithCause(Notice,"knife_sample_limit");return false;}
            knifePath.Add(native);return true;
        }
        bool TryKnifeStart(Ray ray,out int componentIndex)
        {
            componentIndex=-1;var surface=(JObject)frozenModel.DeepClone();surface["component"]="face";
            if(!DirectModelEditMath.TryPick(surface,primaryMap,ray,.012f,out int face,out var vertices,out _))return false;
            if(Selection.ActiveId==picked.ObjectId&&Selection.Component==pickedComponent&&Selection.Indices.Count>0)
            {componentIndex=Selection.Indices.Last();return true;}
            if(pickedComponent=="face"){componentIndex=face;return true;}
            if(pickedComponent=="vertex"){componentIndex=vertices.FirstOrDefault();return vertices.Length>0;}
            if(frozenModel["edges"] is JArray edges)foreach(JObject edge in edges)
                if(edge["vertices"] is JArray ids&&ids.Count==2&&vertices.Contains((int)ids[0])&&vertices.Contains((int)ids[1]))
                {componentIndex=(int)edge["index"];return true;}
            return false;
        }
        public void Cancel(string reason)
        {CancelWithCause(reason,"request");}
        void CancelWithCause(string reason,string cause)
        {
            if(attempted&&cause!="request")Refuse(false,reason);
            controllerCancelled=true;
            if(held||Busy||waiting)
                Debug.Log("P25_LIVE_CANCEL cause="+cause+" phase="+DiagnosticFlag(Session.Phase)+" tool="+DiagnosticFlag((string)Model?["tool"])
                    +" native="+DiagnosticFlag((string)Model?["native_tool"])+" mode="+DiagnosticFlag((string)Model?["mode"])
                    +" held="+held+" waiting="+waiting+" active="+Session.Active+" enabled="+enabled+" current="+drawing.NativeStateCurrent
                    +" placement="+(scene!=null&&scene.DisplayPlacementReady)+" modal="+drawing.NativeModalActive);
            gestureEpoch++;Selection.InvalidateIntent();held=waiting=moved=false;
            rotationGesture=null;
            scaleContacts.Clear();
            translationGestureFrame=null;scaleFeedback.Hide();
            if(Session.Busy)Session.Cancel(reason);
            Notice=Session.Busy?Session.Notice:reason;HideHandles();
        }
        static string DiagnosticFlag(string value)
        {return string.IsNullOrEmpty(value)?"none":new string(value.Where(c=>char.IsLetterOrDigit(c)||c=='.'||c=='_').Take(64).ToArray());}
        public bool TryVisual(XRNode hand,Ray ray,out Vector3 point)
        {point=default;if(!held||hand!=ownerHand)return false;point=ray.GetPoint(depth);return true;}
        public bool TryVisualAim(Ray ray,out float distance)
        {
            distance=float.PositiveInfinity;if(!enabled)return false;
            var view=scene.PickObject(ray,out float meshDistance);
            // A visual query must never replace a captured arrow/normal/ring
            // with the other hand's hover while a gesture or its ACK is live.
            bool handle=false;float handleDistance=0;
            if(!held&&!Busy)handle=TryHandle(ray,20,out _,out _,out handleDistance);
            if(view!=null)distance=meshDistance;if(handle)distance=Mathf.Min(distance,handleDistance);
            return !float.IsPositiveInfinity(distance);
        }
        public void Dispose()
        {Cancel("Controller owner disposed");Session.Changed-=Changed;rotationHandles.Dispose();translationHandles.Dispose();scaleFeedback.Dispose();toolGuides.Dispose();if(handleRoot!=null)Release(handleRoot);if(selectionRoot!=null)Release(selectionRoot);if(handleMaterial!=null)Release(handleMaterial);if(axisMaterial!=null)Release(axisMaterial);}
        public static string CanonicalTool(string native,string component)
        {
            string suffix=native=="builtin.move"?"translate":native=="builtin.rotate"?"rotate":native=="builtin.scale"?"scale":
                native=="builtin.inset_faces"||native=="builtin.inset"?"inset":native=="builtin.bevel"?"bevel":native=="builtin.loop_cut"?"loop_cut":
                native=="builtin.knife"?"knife":new[]{"builtin.extrude_region","builtin.extrude_region_move","builtin.extrude_individual"}.Contains(native)?"extrude":
                native=="spatial_modeling.merge"?"merge":native=="spatial_modeling.dissolve"?"dissolve":native=="spatial_modeling.delete"?"delete":
                new[]{"builtin.select","builtin.select_box","builtin.select_lasso","builtin.select_circle"}.Contains(native)?"selection":null;
            return suffix==null?null:(component=="object"?"object.":"mesh.")+suffix;
        }
        static string ToolOf(JObject model)
        {string tool=(string)model?["tool"];return string.IsNullOrEmpty(tool)?CanonicalTool((string)model?["native_tool"],(string)model?["component"])??"":tool;}
        static Matrix4x4 SwapMatrix(){var m=Matrix4x4.identity;m[1,1]=m[2,2]=0;m[1,2]=m[2,1]=1;return m;}
        static JArray MatrixArray(Matrix4x4 m){var a=new JArray();for(int r=0;r<4;r++)for(int c=0;c<4;c++)a.Add(m[r,c]);return a;}
        static void Release(UnityEngine.Object obj){if(Application.isPlaying)UnityEngine.Object.Destroy(obj);else UnityEngine.Object.DestroyImmediate(obj);}
        void HideHandles(){rotationHandles.Hide();translationHandles.Hide();toolGuides.Hide();if(handleRoot!=null)handleRoot.SetActive(false);if(selectionRoot!=null)selectionRoot.SetActive(false);}
        DirectTranslationHandles.Frame TranslationFrame(WorkspaceObjectView view)
        {
            var pivot=SelectionPivotDisplay();var camera=Camera.main;
            return new DirectTranslationHandles.Frame(pivot,new[]{Axis(0),Axis(1),Axis(2)},camera!=null?camera.transform.position:pivot+Vector3.back);
        }
        DirectRotationHandles.Frame RotationFrame(WorkspaceObjectView view)
        {
            var pivot=SelectionPivotDisplay();var camera=Camera.main;
            float radius=.12f;
            foreach(string id in Selection.ObjectIds)
            {
                var selected=FindView(id);if(selected==null)continue;
                var mesh=selected.GetComponent<MeshFilter>()?.sharedMesh;
                if(mesh!=null)
                {
                    var bounds=mesh.bounds;
                    for(int corner=0;corner<8;corner++)
                    {
                        var local=bounds.center+Vector3.Scale(bounds.extents,new Vector3((corner&1)==0?-1:1,(corner&2)==0?-1:1,(corner&4)==0?-1:1));
                        radius=Mathf.Max(radius,Vector3.Distance(pivot,selected.transform.TransformPoint(local))+.035f);
                    }
                }
                else
                {
                    var renderer=selected.GetComponent<Renderer>();if(renderer==null)continue;
                    radius=Mathf.Max(radius,Vector3.Distance(pivot,renderer.bounds.center)+renderer.bounds.extents.magnitude+.035f);
                }
            }
            return new DirectRotationHandles.Frame(view.NativeToDisplayMatrix,pivot,new[]{Axis(0),Axis(1),Axis(2)},camera!=null?camera.transform.position:pivot+Vector3.back,radius);
        }
        Vector3 Axis(int index)
        {
            var view=FindView(Selection.ActiveId);var settings=Model?["settings"] as JObject;
            Vector3 basis=index==0?Vector3.right:index==1?Vector3.forward:Vector3.up;
            if((string)settings?["orientation"]=="LOCAL"&&view!=null)basis=view.NativeRotation*basis;
            if(settings?["orientation_matrix"] is JArray matrix&&matrix.Count==9)
                basis=DirectModelEditMath.ToUnity(new JArray(matrix[index],matrix[3+index],matrix[6+index]));
            return view!=null?view.NativeToDisplayMatrix.MultiplyVector(basis).normalized:basis;
        }
        void DrawGuides()
        {
            bool captured=held||moved&&Busy;
            var model=captured?frozenModel:Model;var view=captured?picked:FindView(Selection.ActiveId);
            if(!enabled||!drawing.NativeStateCurrent||!scene.IsCurrent||!scene.DisplayPlacementReady||view==null||model==null||!Available||!held&&Busy&&!moved)
            {guideFrame=null;toolGuides.Hide();return;}
            string tool=ToolOf(model);
            if(!SupportedOperation(tool)){guideFrame=null;toolGuides.Hide();return;}
            var ack=captured&&moved&&Session.Busy?Session.AcknowledgedParameters:null;
            var settings=(captured?operation?["settings"]:model["settings"]) as JObject??model["settings"] as JObject;
            guideFrame=new DirectToolGuides.Frame{Tool=tool,Component=captured?pickedComponent:Selection.Component,Model=model,
                Map=captured?primaryMap:view.NativeToDisplayMatrix,Pivot=captured?gesturePivot:view.NativeToDisplayMatrix.inverse.MultiplyPoint3x4(SelectionPivotDisplay()),
                Indices=captured?gestureIndices.ToArray():Selection.Indices.ToArray(),KnifePath=captured?knifePath.ToArray():Array.Empty<Vector3>(),
                Acknowledged=ack,Held=held,Waiting=captured&&(waiting||ack==null||!JToken.DeepEquals(lastParameters,ack)),
                NativeObjectMirrored=captured?nativeMirrored:view.NativeScale.x*view.NativeScale.y*view.NativeScale.z<0,
                ExtrudeNormalConstrained=captured&&gestureNormalConstrained,Radius=(float?)settings?["proportional_radius_m"],
                HoverPoint=captured?null:hoverPoint,HoverIndex=captured?-1:hoverIndex,HoverComponent=captured?null:hoverComponent,
                SnapPoint=captured?snapPoint:null,IntentLabel=IntentLabel(tool,captured)};
            toolGuides.Draw(guideFrame,Camera.main);
        }
        string IntentLabel(string tool,bool captured)
        {
            if(tool=="mesh.inset"||tool=="mesh.bevel")return "Distance from the grab start: move away to increase, return to reduce · native mm after ACK";
            if(tool=="mesh.extrude")
            {
                bool individual=(string)(captured?frozenModel:Model)?["native_tool"]=="builtin.extrude_individual";
                if(captured&&gestureNormalConstrained)return individual?
                    "Outward extends / inward reverses by the same native distance along each face's own normal":
                    "Region follows grabbed face normal · outward extends / inward reverses · frozen native basis";
                if(individual)return "Grab a yellow normal, or drag right to extend / left to reverse along each face normal";
                return "XYZ arrows: axis movement · Region follows grabbed face normal · body drag moves freely";
            }
            if(tool.EndsWith(".scale",StringComparison.Ordinal))return "Cube end: outward grows, inward shrinks · body / plane: right or up grows";
            if(tool=="mesh.knife")return "Cyan path: controller stroke preview, not cut geometry · amounts below require Blender ACK";
            return "Release: one native Undo step · grip: cancel and restore";
        }
        bool TryNormalHandle(WorkspaceObjectView view,Ray ray,float limit,out Vector3 direction,out float distance)
        {
            direction=default;distance=limit;
            var model=Model;if(Selection.Component!="face"||!(model?["vertices"] is JArray vertices)||!(model["faces"] is JArray faces))return false;
            var points=vertices.OfType<JObject>().ToDictionary(item=>(int)item["index"],item=>DirectModelEditMath.ToUnity((JArray)item["position"]));
            var normals=new List<(Vector3 centre,Vector3 normal)>();bool mirrored=view.NativeScale.x*view.NativeScale.y*view.NativeScale.z<0;
            foreach(JObject face in faces)if(Selection.Indices.Contains((int)face["index"])&&face["vertices"] is JArray ids&&ids.Count>=3&&ids.Values<int>().All(points.ContainsKey))
            {
                var path=ids.Values<int>().Select(id=>points[id]).ToArray();Vector3 centre=Vector3.zero,normal=Vector3.zero,origin=path[0];
                foreach(var p in path)centre+=p;centre/=path.Length;
                for(int i=0;i<path.Length;i++)normal+=Vector3.Cross(path[i]-origin,path[(i+1)%path.Length]-origin);
                if(normal.sqrMagnitude>1e-16f)normals.Add((centre,normal.normalized*(mirrored?1:-1)));
            }
            if(normals.Count==0)return false;
            bool found=false;
            foreach(var value in normals.Take(24))
            {
                var at=view.NativeToDisplayMatrix.MultiplyPoint3x4(value.centre);var axis=view.NativeToDisplayMatrix.MultiplyVector(value.normal).normalized;
                if(Mathf.Abs(Vector3.Dot(axis,ray.direction.normalized))>.96f)continue;
                if(RaySegment(ray,at+axis*.015f,at+axis*.11f,out float miss,out float depth)&&miss<=Mathf.Clamp(depth*.006f,.01f,.018f)&&depth<distance)
                {found=true;distance=depth;direction=axis;normalPickNative=value.normal;}
            }
            return found;
        }
        bool TryHandle(Ray ray,float nearest,out Vector3 axis,out bool[] constraint,out float distance,float moveArrowLimit=-1)
        {
            translationPickedArrow=normalPicked=false;
            axis=default;constraint=null;distance=nearest;
            var view=FindView(Selection.ActiveId);string tool=ToolOf(Model);
            if(view==null||(bool?)Model?["available"]!=true||!(tool.EndsWith(".translate")||tool.EndsWith(".rotate")||tool.EndsWith(".scale")||tool=="mesh.extrude"))return false;
            if(tool.EndsWith(".rotate",StringComparison.Ordinal))
            {
                rotationPickFrame=RotationFrame(view);
                bool ring=DirectRotationHandles.TryPick(rotationPickFrame,ray,nearest,out rotationPick);
                highlightedRotationAxis=ring?rotationPick.Axis:-1;
                if(!ring)return false;
                axis=rotationPickFrame.DisplayAxis(rotationPick.Axis);constraint=new[]{rotationPick.Axis==0,rotationPick.Axis==1,rotationPick.Axis==2};
                distance=rotationPick.Distance;return true;
            }
            Vector3 pivot=SelectionPivotDisplay();bool hit=false;
            float axisLimit=moveArrowLimit>0?moveArrowLimit:nearest;
            if(tool=="mesh.extrude"&&TryNormalHandle(view,ray,axisLimit,out var normalDirection,out float normalDepth))
            {normalPicked=true;axis=normalDirection;distance=normalDepth;return true;}
            bool move=tool.EndsWith(".translate",StringComparison.Ordinal)||tool=="mesh.extrude";
            if(tool=="mesh.extrude"&&(string)Model["native_tool"]=="builtin.extrude_individual")return false;
            if(move)
            {
                translationPickFrame=TranslationFrame(view);
                if(DirectTranslationHandles.TryPick(translationPickFrame,ray,moveArrowLimit>0?moveArrowLimit:nearest,out var pickedArrow))
                {translationAxis=pickedArrow.Axis;translationPickedArrow=hit=true;distance=pickedArrow.Distance;axis=translationPickFrame.Axis(translationAxis);constraint=new[]{translationAxis==0,translationAxis==1,translationAxis==2};}
                // The visible arrow wins its hit. A nearer plane intersection
                // along the same oblique ray must not silently replace its axis.
                if(hit)return true;
            }
            else for(int i=0;i<3;i++)
            {
                Vector3 direction=Axis(i),a=pivot+direction*.025f,b=pivot+direction*.11f;
                // An end-on axis overlaps the free-move center; it must not
                // silently turn an ordinary body drag into a depth constraint.
                if(Mathf.Abs(Vector3.Dot(direction,ray.direction.normalized))>.96f)continue;
                bool cube=new Bounds(b,Vector3.one*.022f).IntersectRay(ray,out float cubeDepth)&&cubeDepth>0&&cubeDepth<axisLimit;
                if(cube||RaySegment(ray,a,b,out float miss,out float depth)&&miss<.008f&&depth<axisLimit)
                {
                    float at=cube?cubeDepth:Vector3.Dot(b-ray.origin,ray.direction.normalized);
                    if(!cube)RaySegment(ray,a,b,out _,out at);
                    if(!hit||at<distance){distance=at;axis=direction;constraint=new[] {i==0,i==1,i==2};hit=true;}
                }
            }
            if(!tool.EndsWith(".rotate"))for(int normal=0;normal<3;normal++)
            {
                var n=Axis(normal);var plane=new Plane(n,pivot);
                if(!plane.Raycast(ray,out float depth)||depth<0||depth>Mathf.Min(distance,nearest))continue;
                var offset=ray.GetPoint(depth)-pivot;int first=(normal+1)%3,second=(normal+2)%3;
                float u=Vector3.Dot(offset,Axis(first)),v=Vector3.Dot(offset,Axis(second));
                if(u>=.025f&&u<=.05f&&v>=.025f&&v<=.05f)
                {distance=depth;axis=n;constraint=new[] {normal!=0,normal!=1,normal!=2};hit=true;translationPickedArrow=false;}
            }
            return hit;
        }
        static bool RaySegment(Ray ray,Vector3 a,Vector3 b,out float miss,out float depth)
        {
            var v=b-a;var d=ray.direction.normalized;var o=a-ray.origin;float l=v.sqrMagnitude,t=Vector3.Dot(v,d),den=l-t*t;
            float u=den>1e-10f?Mathf.Clamp01((t*Vector3.Dot(o,d)-Vector3.Dot(o,v))/den):0;
            var at=a+v*u;depth=Vector3.Dot(at-ray.origin,d);miss=Vector3.Distance(at,ray.GetPoint(depth));return depth>0;
        }
        void DrawHandles()
        {
            var view=FindView(Selection.ActiveId);string tool=ToolOf(Model);
            if(view==null||(bool?)Model?["available"]!=true||!(tool.EndsWith(".translate")||tool.EndsWith(".rotate")||tool.EndsWith(".scale")||tool=="mesh.extrude")){HideHandles();return;}
            if(tool.EndsWith(".rotate",StringComparison.Ordinal))
            {translationHandles.Hide();if(handleRoot!=null)handleRoot.SetActive(false);rotationHandles.Draw(RotationFrame(view),highlightedRotationAxis);return;}
            rotationHandles.Hide();
            bool move=tool.EndsWith(".translate",StringComparison.Ordinal)||tool=="mesh.extrude"&&(string)Model["native_tool"]!="builtin.extrude_individual";
            if(move)translationHandles.Draw(TranslationFrame(view),translationAxis);else translationHandles.Hide();
            if(tool=="mesh.extrude"&&!move){if(handleRoot!=null)handleRoot.SetActive(false);return;}
            DrawLinearHandles(tool,SelectionPivotDisplay(),new[]{Axis(0),Axis(1),Axis(2)});
        }
        void DrawLinearHandles(string tool,Vector3 pivot,Vector3[] axes)
        {
            if(axes==null||axes.Length!=3)return;
            bool scale=tool.EndsWith(".scale",StringComparison.Ordinal);
            if(handleRoot==null)
            {
                handleRoot=new GameObject("Native tool axes · no alternate modeling menu");
                axisMaterial=new Material(Shader.Find("UI/Default")??Shader.Find("Universal Render Pipeline/Unlit")){name="Native axis / Scale cube overlay",renderQueue=4000};
                axisMaterial.SetInt("unity_GUIZTestMode",(int)UnityEngine.Rendering.CompareFunction.Always);
                if(axisMaterial.HasProperty("_ZTest"))axisMaterial.SetInt("_ZTest",(int)UnityEngine.Rendering.CompareFunction.Always);
                if(axisMaterial.HasProperty("_ZWrite"))axisMaterial.SetInt("_ZWrite",0);
                foreach(var colour in new[] {Color.red,Color.green,Color.blue,new Color(1,1,0),new Color(0,1,1),new Color(1,0,1)})
                {
                    var obj=new GameObject("Native constraint axis");obj.transform.SetParent(handleRoot.transform,false);
                    var line=obj.AddComponent<LineRenderer>();line.sharedMaterial=axisMaterial;line.useWorldSpace=true;line.positionCount=2;line.widthMultiplier=.003f;
                    line.startColor=line.endColor=colour;handles.Add(line);
                }
                for(int i=0;i<3;i++)
                {
                    var cube=GameObject.CreatePrimitive(PrimitiveType.Cube);cube.name="Native "+"XYZ"[i]+" Scale cube";cube.transform.SetParent(handleRoot.transform,false);
                    var collider=cube.GetComponent<Collider>();if(collider!=null){collider.enabled=false;Release(collider);}
                    cube.GetComponent<Renderer>().sharedMaterial=axisMaterial;
                    var colour=new MaterialPropertyBlock();colour.SetColor("_BaseColor",i==0?Color.red:i==1?Color.green:Color.blue);colour.SetColor("_Color",i==0?Color.red:i==1?Color.green:Color.blue);
                    cube.GetComponent<Renderer>().SetPropertyBlock(colour);scaleEnds.Add(cube.transform);
                }
            }
            handleRoot.SetActive(true);for(int i=0;i<3;i++)
            {
                handles[i].gameObject.SetActive(scale);handles[i].SetPosition(0,pivot+axes[i]*.025f);handles[i].SetPosition(1,pivot+axes[i]*.11f);
                scaleEnds[i].gameObject.SetActive(scale);scaleEnds[i].position=pivot+axes[i]*.11f;scaleEnds[i].rotation=Quaternion.identity;scaleEnds[i].localScale=Vector3.one*.022f;
            }
            for(int normal=0;normal<3;normal++)
            {
                var line=handles[3+normal];line.gameObject.SetActive(!tool.EndsWith(".rotate"));line.positionCount=5;
                var a=axes[(normal+1)%3];var b=axes[(normal+2)%3];var p=pivot;
                line.SetPositions(new[] {p+a*.025f+b*.025f,p+a*.05f+b*.025f,p+a*.05f+b*.05f,p+a*.025f+b*.05f,p+a*.025f+b*.025f});
            }
        }
        void DrawSelection()
        {
            if(Selection.ObjectIds.Count==0){if(selectionRoot!=null)selectionRoot.SetActive(false);return;}
            var segments=new List<Vector3[]>();
            foreach(string id in Selection.ObjectIds)
            {
                if(segments.Count>=MaximumSelectionSegments)break;
                var view=FindView(id);if(view==null)continue;
                if(Selection.Component=="object")
                {
                    var mesh=view.GetComponent<MeshFilter>()?.sharedMesh;if(mesh==null)continue;var bounds=mesh.bounds;
                    var corners=new Vector3[8];for(int i=0;i<8;i++)corners[i]=view.transform.TransformPoint(bounds.center+Vector3.Scale(bounds.extents,
                        new Vector3((i&1)==0?-1:1,(i&2)==0?-1:1,(i&4)==0?-1:1)));
                    for(int i=0;i<8;i++)foreach(int bit in new[]{1,2,4})if((i&bit)==0&&segments.Count<MaximumSelectionSegments)segments.Add(new[]{corners[i],corners[i|bit]});
                    continue;
                }
                if(!(Model?["vertices"] is JArray vertices))continue;
                var positions=vertices.OfType<JObject>().ToDictionary(v=>(int)v["index"],v=>view.NativeToDisplayMatrix.MultiplyPoint3x4(DirectModelEditMath.ToUnity((JArray)v["position"])));
                if(Selection.Component=="vertex")foreach(int index in Selection.Indices)
                {
                    if(segments.Count+3>MaximumSelectionSegments)break;
                    if(!positions.TryGetValue(index,out var p))continue;
                    foreach(var axis in new[]{Vector3.right,Vector3.up,Vector3.forward})segments.Add(new[]{p-axis*.003f,p+axis*.003f});
                }
                else if(Model[Selection.Component=="edge"?"edges":"faces"] is JArray components)
                    foreach(JObject item in components)if(Selection.Indices.Contains((int)item["index"])&&item["vertices"] is JArray ids)
                    {
                        if(segments.Count>=MaximumSelectionSegments)break;
                        var path=ids.Values<int>().Where(positions.ContainsKey).Select(index=>positions[index]).ToList();
                        if(Selection.Component=="face"&&path.Count>2)path.Add(path[0]);if(path.Count>1)segments.Add(path.ToArray());
                    }
            }
            if(selectionRoot==null)selectionRoot=new GameObject("Acknowledged spatial selection");
            if(handleMaterial==null)handleMaterial=new Material(Shader.Find("Universal Render Pipeline/Unlit")??Shader.Find("UI/Default"));
            while(selectionLines.Count<segments.Count)
            {
                var obj=new GameObject("Selected native element");obj.transform.SetParent(selectionRoot.transform,false);
                var line=obj.AddComponent<LineRenderer>();line.sharedMaterial=handleMaterial;line.useWorldSpace=true;line.widthMultiplier=.0015f;
                line.startColor=line.endColor=new Color(1f,.7f,.15f,1);selectionLines.Add(line);
            }
            selectionRoot.SetActive(true);for(int i=0;i<selectionLines.Count;i++)
            {var line=selectionLines[i];line.gameObject.SetActive(i<segments.Count);if(i<segments.Count){line.positionCount=segments[i].Length;line.SetPositions(segments[i]);}}
        }
    }
}

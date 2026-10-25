using System;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.XR;
using UnityEngine.XR;
using UnityEngine.XR.Interaction.Toolkit.Inputs;

namespace SpatialModeling
{
    // Both Touch controllers: tracked grip visuals, aim rays, UI trigger and grip placement.
    // This is inspection only. Native editing is a separate, later mode.
    [DefaultExecutionOrder(100)]
    public sealed class WorkspaceInteraction : MonoBehaviour
    {
        public bool MoveIndividualParts { get; private set; }
        public bool HasTrackedHands { get; private set; }
        public string Instruction { get; private set; } = "Point at the screen or build · hold grip to move";
        public bool IsHolding => left?.target != null || right?.target != null;

        Hand left, right;
        Material material;
        HostScene scene;
        BlenderScreen screen;
        WorkspaceArrangement arrangement;
        VoiceUiAdapter voice;
        public string PointedObjectId => right?.pointed?.ObjectId ?? left?.pointed?.ObjectId;
        Transform pairTarget;
        Vector3 pairVector, pairMidpoint, pairScale, pairOffset;
        Quaternion pairFrame, pairRotation;
        readonly LiveScaleFeedback pairScaleFeedback=new LiveScaleFeedback();
        Vector3 pairFeedbackBaseline;
        bool loggedTracking;
        Transform trackingOrigin;
        int renderedFrame = -1;

        sealed class Hand : IDisposable
        {
            public XRNode node;
            public GameObject visual;
            public LineRenderer ray;
            public Transform tip,body;
            public InputAction gripPose, aimPose;
            public string poseSource;
            public InputControl previousGripControl;
            public int poseControlSwitches;
            public bool hasHit;
            public float pointerDistance;
            public bool gripDown, triggerDown, armed;
            public Transform target;
            public WorkspaceObjectView part;
            public WorkspaceObjectView pointed;
            public Pose rayRelative;
            public Transform rawAim, stableAim;
            public bool aimInitialized;
            public Vector3 localContact;
            public int timingFrames, slowFrames;
            public double timingSeconds, previousPoseTime;
            public float maximumFrameTime, largestRawStep, largestGripStep, largestGripTurn, largestDisplayStep;
            public Vector3 previousRawPosition;
            public Pose previousHandPose;
            public float depth;
            public Quaternion rotationOffset=Quaternion.identity;
            public Quaternion placementRotation=Quaternion.identity;
            public bool preserveRotation;
            public Vector3 rotationAxis=Vector3.up;
            public bool turnLatched, stickDown, freePlacement, alignRequested;
            public Color color;
            public void Dispose()
            {
                gripPose.Dispose(); aimPose.Dispose();
                if (rawAim != null) UnityEngine.Object.Destroy(rawAim.gameObject);
                if (stableAim != null) UnityEngine.Object.Destroy(stableAim.gameObject);
            }
        }

        void OnEnable()
        {
            var shader = Shader.Find("Universal Render Pipeline/Unlit");
            if (shader == null) shader = Shader.Find("UI/Default");
            material = new Material(shader);
            left = CreateHand(XRNode.LeftHand, "LeftHand", GlassTheme.LeftMetal);
            right = CreateHand(XRNode.RightHand, "RightHand", GlassTheme.RightMetal);
            scene = FindFirstObjectByType<HostScene>();
            screen = FindFirstObjectByType<BlenderScreen>();
            arrangement = FindFirstObjectByType<WorkspaceArrangement>();
            voice = FindFirstObjectByType<VoiceUiAdapter>();
            renderedFrame = -1;
            Application.onBeforeRender += BeforeRender;
        }

        Hand CreateHand(XRNode node, string usage, Color color)
        {
            var h = new Hand { node = node, color = color };
            h.visual = new GameObject(usage + " tracked controller");
            h.visual.transform.SetParent(transform, false);
            h.body=GlassController.Create(h.visual.transform,node).transform;
            var block=new MaterialPropertyBlock();block.SetColor("_BaseColor",color);block.SetColor("_Color",color);
            var rayObject = new GameObject(usage + " aim ray", typeof(LineRenderer));
            rayObject.transform.SetParent(h.visual.transform, false);
            h.ray = rayObject.GetComponent<LineRenderer>();
            h.ray.sharedMaterial = material;
            h.ray.useWorldSpace = true;
            h.ray.positionCount = 2;
            h.ray.startWidth = 0.003f;
            h.ray.endWidth = 0.0015f;
            h.ray.startColor = h.ray.endColor = color;
            var tip = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            tip.name = "Pointer target";
            var tipCollider=tip.GetComponent<Collider>();tipCollider.enabled=false;
            if(Application.isPlaying)Destroy(tipCollider);else DestroyImmediate(tipCollider);
            h.tip = tip.transform;
            h.tip.SetParent(h.visual.transform, false);
            h.tip.localScale = Vector3.one * 0.012f;
            tip.GetComponent<Renderer>().sharedMaterial = material;
            tip.GetComponent<Renderer>().SetPropertyBlock(block);
            h.gripPose = new InputAction(usage + " grip pose", InputActionType.Value,
                "<XRController>{" + usage + "}/devicePose", expectedControlType: "Pose");
            h.aimPose = new InputAction(usage + " aim pose", InputActionType.Value,
                "<XRController>{" + usage + "}/{Pointer}", expectedControlType: "Pose");
            h.gripPose.Enable();
            h.aimPose.Enable();
            h.rawAim = new GameObject(usage + " raw aim").transform;
            h.stableAim = new GameObject(usage + " stabilized aim").transform;
            h.rawAim.SetParent(transform, false);
            h.stableAim.SetParent(transform, false);
            h.visual.SetActive(false);
            return h;
        }

        void OnDisable()
        {
            pairScaleFeedback.Dispose();
            Application.onBeforeRender -= BeforeRender;
            Release(left);
            Release(right);
            left?.Dispose(); right?.Dispose();
            if (left?.visual != null) Destroy(left.visual);
            if (right?.visual != null) Destroy(right.visual);
            if (material != null) Destroy(material);
            HasTrackedHands = false;
            if (left != null) left.pointed = null;
            if (right != null) right.pointed = null;
            voice?.SetControllerPointer(null);
        }

        void LateUpdate()
        {
            if (Camera.main == null || screen == null || scene == null) return;
            trackingOrigin = Camera.main.transform.parent;
            bool leftTracked = TryReadHand(left, out var leftGrip, out _);
            scene.Table?.UpdateLeftHandMenu(leftGrip, Camera.main.transform.position, leftTracked);
            screen.ClearControllerHover();
            Physics.SyncTransforms();
            Instruction = arrangement!=null ? arrangement.Instruction : "Point at screen or build · grip: move · trigger: select";
            HasTrackedHands = UpdateHand(left, right) | UpdateHand(right, left);
            if (voice == null) voice = FindFirstObjectByType<VoiceUiAdapter>();
            voice?.SetControllerPointer(PointedObjectId);
            if(!IsHolding) arrangement?.HideGuide();
            if (HasTrackedHands != loggedTracking)
            {
                loggedTracking = HasTrackedHands;
                Debug.Log("WORKSPACE_CONTROLLER_TRACKING active=" + HasTrackedHands);
            }
            screen.SetInteractionNotice(Instruction);
        }

        bool UpdateHand(Hand h, Hand other)
        {
            var device = InputDevices.GetDeviceAtXRNode(h.node);
            if (!TryReadHand(h, out var hand, out var aim))
            {
                pairScaleFeedback.Hide();
                PreviewInteraction.Current?.TrackingLost(h.node);
                Release(h);
                h.visual.SetActive(false);
                h.armed = false;
                h.gripDown = h.triggerDown = false;
                h.aimInitialized = false;
                h.pointed = null;
                return false;
            }
            if (!h.aimInitialized)
            {
                h.stableAim.SetPositionAndRotation(aim.position, aim.rotation);
                h.aimInitialized = true;
            }
            // Hit the same stabilized ray the wearer sees. Raw input is retained
            // only as the existing manipulation stabilizer's input.
            aim = new Pose(h.stableAim.position, h.stableAim.rotation);
            var ray = new Ray(aim.position, aim.rotation * Vector3.forward);
            device.TryGetFeatureValue(UnityEngine.XR.CommonUsages.grip, out float grip);
            device.TryGetFeatureValue(UnityEngine.XR.CommonUsages.trigger, out float trigger);
            device.TryGetFeatureValue(UnityEngine.XR.CommonUsages.primary2DAxis, out Vector2 axis);
            bool gripNow = grip > (h.gripDown ? 0.25f : 0.65f);
            bool triggerNow = trigger > (h.triggerDown ? 0.25f : 0.65f);
            if (!gripNow && !triggerNow) h.armed = true;
            bool gripPressed = h.armed && gripNow && !h.gripDown;
            bool triggerPressed = h.armed && triggerNow && !h.triggerDown;
            h.gripDown = gripNow; h.triggerDown = triggerNow;
            device.TryGetFeatureValue(UnityEngine.XR.CommonUsages.primary2DAxisClick,out bool stickNow);
            bool stickPressed=stickNow&&!h.stickDown; h.stickDown=stickNow;
            return RouteHand(h, other, aim, ray, gripNow, triggerNow, gripPressed, triggerPressed, axis, stickPressed);
        }

        // One ray/input owner: tests exercise this same routing used by both live hands.
        bool RouteHand(Hand h, Hand other, Pose aim, Ray ray, bool gripNow, bool triggerNow,
            bool gripPressed, bool triggerPressed, Vector2 axis, bool stickPressed)
        {
            h.pointed = null;
            float distance = 4f;
            var hitPart = scene.PickObject(ray, out float partDistance);
            bool hitScreen = screen.RaycastSurface(ray, out float screenDistance);
            if (hitPart != null) distance = partDistance;
            bool screenFirst = hitScreen && (hitPart == null || screenDistance <= partDistance);
            if (screenFirst) distance = screenDistance;

            var table = scene.Table;
            float tableDistance = 4f;
            bool tableHit = table != null && table.RaycastControls(ray, out tableDistance);
            bool tableFirst = tableHit && tableDistance < distance;
            if (tableFirst) distance = tableDistance;
            float levelDistance=float.PositiveInfinity;
            var level=arrangement!=null?arrangement.Surfaces.RaycastLevel(ray,out levelDistance):null;
            bool levelFirst=level!=null && levelDistance<distance;
            if(levelFirst) distance=levelDistance;

            // Optional P2.5 consumes only UI/drawing gestures. Existing held aim
            // mapping and P2 placement controls keep their original writers.
            var preview = PreviewInteraction.Current;
            float previewDistance = 0;
            bool previewRouted = preview != null && h.target == null && !(table != null && table.IsPointing)
                && preview.RouteControllerHand(h.node, ray, h.armed && triggerNow,
                gripNow || h.target != null || (table != null && table.IsPointing), axis,
                Mathf.Min(Mathf.Min(hitPart != null ? partDistance : 4f, tableHit ? tableDistance : 4f),
                    level != null ? levelDistance : 4f), out previewDistance, h.stickDown);
            if (previewRouted)
            {
                distance = previewDistance;
                if (!tableHit || previewDistance < tableDistance) tableFirst = false;
                if (level != null && previewDistance < levelDistance) levelFirst = false;
            }

            if (h.target != null)
            {
                if (!gripNow || (h.target == screen.Placement && (!screen.Visible || !BlenderScreen.CanGrabScreen(screen.PositionLocked)))
                    || (table != null && h.target == table.Menu && !table.Menu.gameObject.activeInHierarchy)) Release(h);
                else
                {
                    if(triggerPressed) h.alignRequested=true;
                    if(stickPressed) h.freePlacement=!h.freePlacement;
                    if(Mathf.Abs(axis.x)<.3f) h.turnLatched=false;
                    if(arrangement!=null && !h.turnLatched && Mathf.Abs(axis.x)>.7f)
                    {
                        h.turnLatched=true;
                        h.rotationOffset=Quaternion.AngleAxis(Mathf.Sign(axis.x)*15,h.rotationAxis)*h.rotationOffset;
                    }
                    h.depth = AdvanceDepth(h.depth, axis.y, Time.unscaledDeltaTime);
                    if (arrangement==null && h.target == screen.Placement && Mathf.Abs(axis.x) > 0.2f)
                        screen.Resize(Mathf.Exp(axis.x * Time.unscaledDeltaTime * 0.65f));
                    distance = Mathf.Max(Vector3.Distance(aim.position, h.target.position), 0.15f);
                    Instruction = h.part != null ? "Aim to move " + h.part.name + " · release grip: place"
                        : table != null && h.target == table.Menu ? "Aim to move menu · stick: distance · release grip: place"
                        : h.target == screen.Placement ? "Aim to move screen · stick: distance / size · release grip: place"
                        : "Aim to move whole build · release grip: place";
                    if(arrangement!=null) Instruction=arrangement.Surfaces.IsLevel(h.target)
                        ? "Aim: move plane independently · stick: rotate/distance · release: place · Align: Manage planes"
                        : "Aim: move · stick: rotate/distance · trigger: align to guide · stick click: "+(h.freePlacement?"surface help":"free placement");
                }
            }
            else if(levelFirst)
            {
                Instruction="Grip the visible level · aim to position · release to place";
                if(gripPressed && (other?.target==level || !Conflicts(other?.target,level)))
                    Begin(h,level,null,aim,ray.GetPoint(distance));
            }
            else if (tableFirst)
            {
                table.HoverController(ray, triggerPressed && !gripNow);
                Instruction = "Trigger: select menu button · grip menu, move, release to place";
                if (gripPressed && (other?.target==table.Menu || !Conflicts(other?.target, table.Menu)))
                {
                    table.PinMenu();
                    Begin(h, table.Menu, null, aim, ray.GetPoint(distance));
                }
            }
            else if (table != null && table.IsPointing)
            {
                if (triggerNow) table.PointAt(ray);
                Instruction = "Hold trigger and aim at the table position · Place Table to confirm";
            }
            else if (previewRouted)
            {
                Instruction = preview.Notice;
            }
            else if (screenFirst)
            {
                bool button = screen.HoverController(ray, triggerPressed);
                Instruction = button ? "Trigger: select button" : "Grip: move screen · stick while held: distance / size";
                if (gripPressed && BlenderScreen.CanGrabScreen(screen.PositionLocked)
                    && (other?.target==screen.Placement || !Conflicts(other?.target, screen.Placement))) Begin(h, screen.Placement, null, aim, ray.GetPoint(distance));
            }
            else if (hitPart != null)
            {
                if (!gripNow && !IsHolding)
                {
                    h.pointed = hitPart;
                    if (voice == null) voice = FindFirstObjectByType<VoiceUiAdapter>();
                    if (triggerPressed) voice?.SelectControllerObject(hitPart.ObjectId);
                }
                var target = MoveIndividualParts ? hitPart.transform : scene.Placement;
                Instruction = "Trigger: select " + hitPart.name + " without moving · " +
                    (MoveIndividualParts ? "grip: arrange part" : "grip: move whole build");
                if (gripPressed && (other?.target==target || !Conflicts(other?.target, target))) Begin(h, target, MoveIndividualParts ? hitPart : null, aim, ray.GetPoint(distance));
            }
            h.hasHit = previewRouted || levelFirst || tableFirst || hitScreen || hitPart != null;
            h.pointerDistance = distance;
            return true;
        }

        public void ForgetVoicePointer()
        {
            foreach (var h in new[] { left, right })
                if (h != null) { h.pointed = null; h.armed = false; }
        }

        // Read position, orientation and validity from one Input System pose state.
        // Do not fall back to stale legacy tracking when a bound pose loses tracking.
        bool TryReadHand(Hand h, out Pose hand, out Pose aim)
        {
            hand = aim = default;
            if (!TryReadControllerPair(h.gripPose, h.aimPose, h.previousGripControl,
                    out var local, out var localAim, out var control, out var aimControl))
            {
                if (h.poseSource != "unavailable")
                    Debug.Log("WORKSPACE_POSE_SOURCE hand=" + h.node + " source=unavailable valid_same_device_grip_and_aim_required=true");
                h.poseSource = "unavailable";
                return false;
            }
            if (h.previousGripControl != null && h.previousGripControl != control)
            {
                h.poseControlSwitches++;
                PreviewInteraction.Current?.TrackingLost(h.node);
                Release(h); // A replacement device must not inherit an old device's hold offset.
                h.aimInitialized = false;
                h.armed = false;
                h.previousPoseTime = 0;
            }
            h.previousGripControl = control;
            string source = control.path + " aim=" + aimControl.path + " device=" + control.device.deviceId;
            if (h.poseSource != source)
            {
                h.poseSource = source;
                Debug.Log("WORKSPACE_POSE_SOURCE hand=" + h.node + " source=" + source
                    + " grip_controls=" + h.gripPose.controls.Count + " aim_controls=" + h.aimPose.controls.Count + " stage=before_render");
            }
            hand = ToWorldPose(trackingOrigin, local);
            aim = ToWorldPose(trackingOrigin, localAim);
            return true;
        }

        // Both values must come from one tracked device. In particular, a missing aim
        // is not the grip orientation: OpenXR defines distinct poses for these jobs.
        public static bool TryReadControllerPair(InputAction gripAction, InputAction aimAction,
            InputControl preferredGrip, out Pose grip, out Pose aim,
            out InputControl gripControl, out InputControl aimControl)
        {
            grip = aim = default;
            gripControl = aimControl = null;
            // Keep a valid source stable rather than switching with action magnitude.
            for (int pass = 0; pass < 2; pass++)
            foreach (var candidate in gripAction.controls)
            {
                if ((pass == 0) != (candidate == preferredGrip)) continue;
                if (!TryReadControllerPose(candidate, out var gripPose)) continue;
                foreach (var pointer in aimAction.controls)
                {
                    if (pointer.device != candidate.device || !TryReadControllerPose(pointer, out var aimPose)) continue;
                    grip = gripPose; aim = aimPose;
                    gripControl = candidate; aimControl = pointer;
                    return true;
                }
            }
            return false;
        }

        public static bool TryGetTrackedPose(PoseState sample, out Pose pose)
        {
            var required = InputTrackingState.Position | InputTrackingState.Rotation;
            pose = new Pose(sample.position, sample.rotation);
            return sample.isTracked && (sample.trackingState & required) == required;
        }

        // OpenXR profiles may register either the Input System PoseState control
        // or the older OpenXR Pose control, even in the same installed package set.
        // Read the actual typed control; asking every action for PoseState throws
        // for Meta Touch Plus profiles that still expose the OpenXR Pose struct.
        public static bool TryReadControllerPose(InputControl control, out Pose pose)
        {
            if (control is UnityEngine.InputSystem.XR.PoseControl current)
                return TryGetTrackedPose(current.ReadValue(), out pose);
            if (control is UnityEngine.XR.OpenXR.Input.PoseControl legacy)
            {
                var sample = legacy.ReadValue();
                pose = new Pose(sample.position, sample.rotation);
                var required = InputTrackingState.Position | InputTrackingState.Rotation;
                return sample.isTracked && (sample.trackingState & required) == required;
            }
            pose = default;
            return false;
        }

        // The camera's TrackedPoseDriver consumes the Input System before-render
        // update. Follow the same latest pose here, once per frame, after that update.
        // Button edges, UI hit testing and stick integration stay in LateUpdate.
        [BeforeRenderOrder(100)]
        void BeforeRender()
        {
            if (renderedFrame == Time.frameCount || screen == null || scene == null || Camera.main == null) return;
            renderedFrame = Time.frameCount;
            bool leftTracked = TryReadHand(left, out var leftGrip, out _);
            scene.Table?.UpdateLeftHandMenu(leftGrip, Camera.main.transform.position, leftTracked);
            double now = Time.realtimeSinceStartupAsDouble;
            UpdatePair();
            RenderHand(left, now);
            RenderHand(right, now);
        }

        void RenderHand(Hand h, double now)
        {
            if (!TryReadHand(h, out var hand, out var aim))
            {
                pairScaleFeedback.Hide();
                PreviewInteraction.Current?.TrackingLost(h.node);
                Release(h);
                h.visual.SetActive(false);
                h.armed = false;
                h.aimInitialized = false;
                return;
            }
            h.visual.SetActive(true);
            h.visual.transform.SetPositionAndRotation(hand.position, hand.rotation);
            h.rawAim.SetPositionAndRotation(aim.position, aim.rotation);
            if (!h.aimInitialized)
            {
                h.stableAim.SetPositionAndRotation(aim.position, aim.rotation);
                h.aimInitialized = true;
            }
            float elapsed = h.previousPoseTime > 0 ? (float)(now - h.previousPoseTime) : Time.unscaledDeltaTime;
            h.previousPoseTime = now;
            float distance = h.target != null ? Vector3.Distance(aim.position, h.target.TransformPoint(h.localContact)) : h.pointerDistance;
            var endpointBefore = h.target != null ? h.target.TransformPoint(h.localContact)
                : h.stableAim.position + h.stableAim.forward * Mathf.Max(0.15f, distance);
            StabilizeRay(ref h.stableAim, h.rawAim, endpointBefore, distance, elapsed);
            if (h.target != null && h.target!=pairTarget)
            {
                var desired = FollowRay(aim, h.rayRelative, h.depth);
                h.timingFrames++;
                h.timingSeconds += elapsed;
                h.maximumFrameTime = Mathf.Max(h.maximumFrameTime, elapsed);
                if (elapsed > 0.025f) h.slowFrames++;
                h.largestRawStep = Mathf.Max(h.largestRawStep, Vector3.Distance(desired.position, h.previousRawPosition));
                h.largestGripStep = Mathf.Max(h.largestGripStep, Vector3.Distance(hand.position, h.previousHandPose.position));
                h.largestGripTurn = Mathf.Max(h.largestGripTurn, Quaternion.Angle(hand.rotation, h.previousHandPose.rotation));
                h.previousRawPosition = desired.position;
                h.previousHandPose = hand;
                var pose = FollowPlacementRay(new Pose(h.stableAim.position, h.stableAim.rotation), h.rayRelative,
                    h.depth,h.preserveRotation,h.placementRotation,h.rotationOffset);
                var unconstrained=pose;
                if(arrangement!=null) pose=arrangement.Apply(h.target,new Pose(h.target.position,h.target.rotation),pose,h.alignRequested,h.freePlacement);
                if(arrangement!=null) h.rotationAxis=arrangement.RotationAxis;
                if(h.alignRequested || (arrangement!=null && arrangement.Surfaces.IsLevel(h.target)
                    && (Quaternion.Angle(unconstrained.rotation,pose.rotation)>.01f || Vector3.Distance(unconstrained.position,pose.position)>.0001f)))
                {
                    RebasePlacement(h,new Pose(h.stableAim.position,h.stableAim.rotation),pose);
                }
                h.alignRequested=false;
                h.largestDisplayStep = Mathf.Max(h.largestDisplayStep, Vector3.Distance(h.target.position, pose.position));
                h.target.SetPositionAndRotation(pose.position, pose.rotation);
                if(scene.Table!=null && h.target==scene.Table.Menu)
                    scene.Table.FaceMenuTowardUser(Camera.main.transform.position);
                h.part?.RememberArrangement();
                if (h.timingSeconds >= 2) LogGrabTiming(h);
            }
            // Derive all visuals AFTER the existing stabilizer and object update.
            // A held point follows the actual smooth grab contact, never a second
            // raw ray or a nearer unrelated surface that could make it skip.
            Physics.SyncTransforms(); // Menu, pair and held transforms may have moved since LateUpdate.
            var currentRay = new Ray(h.stableAim.position, h.stableAim.forward);
            float pointerDistance = 4f;
            bool hit = h.target != null;
            Vector3 endpoint;
            var direct=PreviewInteraction.Current?.DirectEditing;
            Vector3 directEndpoint=default;
            bool directGesture=direct!=null&&direct.TryGestureVisual(h.node,currentRay,out directEndpoint);
            if(h.target!=null)
            {
                endpoint=h.target.TransformPoint(h.localContact);
                pointerDistance=Vector3.Distance(currentRay.origin,endpoint);
            }
            else if(directGesture)
            {
                endpoint=directEndpoint;
                pointerDistance=Vector3.Distance(currentRay.origin,endpoint);
                hit=true;
            }
            else
            {
                void Near(bool found, float d) { if (found && d >= 0 && d <= pointerDistance) { pointerDistance = d; hit = true; } }
                var pointed = scene.PickObject(currentRay, out float objectDistance);
                Near(pointed != null, objectDistance);
                Near(screen.RaycastSurface(currentRay, out float screenDistance), screenDistance);
                if (scene.Table != null) Near(scene.Table.RaycastControls(currentRay, out float menuDistance), menuDistance);
                if (arrangement != null) Near(arrangement.Surfaces.RaycastLevel(currentRay, out float levelDistance) != null, levelDistance);
                if (PreviewInteraction.Current != null) Near(PreviewInteraction.Current.RaycastVisual(currentRay, out float previewDistance), previewDistance);
                endpoint=currentRay.GetPoint(pointerDistance);
            }
            var visualForward=endpoint-currentRay.origin;
            var visualRotation=visualForward.sqrMagnitude>.000001f
                ? Quaternion.LookRotation(visualForward,h.stableAim.up):h.stableAim.rotation;
            if(h.body!=null)h.body.SetPositionAndRotation(currentRay.origin,visualRotation);
            h.pointerDistance = pointerDistance;
            h.hasHit = hit;
            h.ray.SetPosition(0, currentRay.origin);
            h.ray.SetPosition(1, endpoint);
            h.tip.position = endpoint;
            h.tip.gameObject.SetActive(h.hasHit || h.target != null);
            var color = h.target != null || h.hasHit ? Color.green : h.color;
            h.ray.startColor = h.ray.endColor = color;
        }

        static bool Conflicts(Transform held, Transform candidate) => held != null && candidate != null
            && (held == candidate || candidate.IsChildOf(held) || held.IsChildOf(candidate));

        void Begin(Hand hand, Transform target, WorkspaceObjectView part, Pose pose, Vector3 contact)
        {
            if(left.target!=target && right.target!=target) arrangement?.Remember(target);
            hand.target = target;
            hand.part = part;
            hand.depth = 0f;
            hand.rotationOffset=Quaternion.identity;
            hand.placementRotation=target.rotation;
            // Arrange a model/level by aiming, without wrist pitch/roll tilting it.
            // Screen/menu keep their accepted legacy mapping; sticks/two hands rotate deliberately.
            hand.preserveRotation=arrangement!=null && ((scene!=null && target==scene.Placement) || part!=null || arrangement.Surfaces.IsLevel(target));
            hand.rotationAxis=Vector3.up;
            hand.freePlacement=hand.alignRequested=hand.turnLatched=false;
            hand.rayRelative = RelativeRayPose(pose, new Pose(target.position, target.rotation));
            // Raw hit testing must not inherit the previous frame's filtered aim
            // at pickup. Start manipulation at the displayed contact with no snap.
            if (hand.stableAim != null) hand.stableAim.SetPositionAndRotation(pose.position, pose.rotation);
            hand.localContact = target.InverseTransformPoint(contact);
            hand.timingFrames = hand.slowFrames = 0;
            hand.poseControlSwitches = 0;
            hand.timingSeconds = hand.maximumFrameTime = hand.largestRawStep = hand.largestGripStep = hand.largestGripTurn = hand.largestDisplayStep = 0;
            hand.previousPoseTime = Time.realtimeSinceStartupAsDouble;
            hand.previousRawPosition = target.position;
            hand.previousHandPose = pose;
            Debug.Log("WORKSPACE_GRAB_BEGIN " + target.name + " inspection_only mapping=unity_stabilized_far_ray");
        }

        public static Quaternion TwoHandFrame(Pose a,Pose b)
        {
            var forward=b.position-a.position;
            if(forward.sqrMagnitude<.0025f) return a.rotation;
            var up=a.rotation*Vector3.up+b.rotation*Vector3.up;
            if(Vector3.Cross(forward,up).sqrMagnitude<.001f) up=a.rotation*Vector3.forward;
            if(Vector3.Cross(forward,up).sqrMagnitude<.001f) up=Vector3.up;
            return Quaternion.LookRotation(forward,up);
        }
        void UpdatePair()
        {
            bool shared=left.target!=null && left.target==right.target;
            if(!shared || !TryReadHand(left,out var a,out _) || !TryReadHand(right,out var b,out _)
                // Reading a replacement device can release a hold. Recheck ownership
                // after those reads before applying any two-hand transform.
                || left.target==null || left.target!=right.target)
            {
                pairScaleFeedback.Hide();
                if(pairTarget!=null)
                {
                    foreach(var hand in new[]{left,right})
                        if(hand.target!=null && TryReadHand(hand,out _,out var aim) && hand.target!=null)
                        {
                            hand.stableAim.SetPositionAndRotation(aim.position,aim.rotation);
                            RebasePlacement(hand,aim,new Pose(hand.target.position,hand.target.rotation));
                        }
                    pairTarget=null;
                }
                return;
            }
            var vector=b.position-a.position;
            if(vector.magnitude<.05f) return;
            var midpoint=(a.position+b.position)*.5f;
            var frame=TwoHandFrame(a,b);
            if(pairTarget!=left.target)
            {
                pairTarget=left.target; pairVector=vector; pairMidpoint=midpoint;
                pairFrame=frame; pairRotation=pairTarget.rotation; pairScale=pairTarget.localScale;
                pairFeedbackBaseline=pairTarget.localScale;
                pairOffset=pairTarget.position-midpoint;
            }
            float ratio=left.part!=null ? 1f : Mathf.Clamp(vector.magnitude/pairVector.magnitude,.25f,4f);
            var turn=frame*Quaternion.Inverse(pairFrame);
            var pose=new Pose(midpoint+turn*(pairOffset*ratio),turn*pairRotation);
            var unconstrained=pose;
            var previousScale=pairTarget.lossyScale;
            pairTarget.localScale=pairScale*ratio;
            if(pairTarget==scene.Placement) scene.Table.RememberDisplayScale();
            if(arrangement!=null) pose=arrangement.Apply(pairTarget,new Pose(pairTarget.position,pairTarget.rotation),pose,
                left.alignRequested||right.alignRequested,left.freePlacement||right.freePlacement,previousScale);
            if(left.alignRequested||right.alignRequested || (arrangement!=null && arrangement.Surfaces.IsLevel(pairTarget)
                && (Quaternion.Angle(unconstrained.rotation,pose.rotation)>.01f || Vector3.Distance(unconstrained.position,pose.position)>.0001f)))
            {
                pairVector=vector; pairFrame=frame; pairRotation=pose.rotation;
                pairOffset=pose.position-midpoint; pairScale=pairTarget.localScale;
            }
            left.alignRequested=right.alignRequested=false;
            pairTarget.SetPositionAndRotation(pose.position,pose.rotation);
            pairScaleFeedback.ShowDisplayScale(DisplayScaleFactors(pairTarget.localScale,pairFeedbackBaseline));
            pairScaleFeedback.Draw(midpoint,Camera.main);
            if(scene.Table!=null && pairTarget==scene.Table.Menu && Camera.main!=null)
                scene.Table.FaceMenuTowardUser(Camera.main.transform.position);
            left.part?.RememberArrangement(); right.part?.RememberArrangement();
            Instruction="Two hands: rotate and resize · release one: continue moving · release both: place";
        }

        static void Release(Hand hand)
        {
            if (hand == null) return;
            if (hand.target != null)
            {
                LogGrabTiming(hand);
                hand.part?.RememberArrangement();
                Debug.Log("WORKSPACE_GRAB_END " + hand.target.name + " inspection_only");
            }
            hand.target = null;
            hand.part = null;
        }

        static void LogGrabTiming(Hand hand)
        {
            if (hand.timingFrames >= 15 && hand.timingSeconds > 0)
                Debug.Log($"WORKSPACE_DRAG_TIMING wall_fps={hand.timingFrames / hand.timingSeconds:F1} max_wall_frame_ms={hand.maximumFrameTime * 1000:F1} frames_over25ms={hand.slowFrames}/{hand.timingFrames} max_raw_step_mm={hand.largestRawStep * 1000:F1} max_grip_step_mm={hand.largestGripStep * 1000:F1} max_grip_turn_deg={hand.largestGripTurn:F2} max_display_step_mm={hand.largestDisplayStep * 1000:F1} pose_control_switches={hand.poseControlSwitches} mapping=unity_stabilized_far_ray stage=before_render");
            hand.timingFrames = hand.slowFrames = 0;
            hand.poseControlSwitches = 0;
            hand.timingSeconds = hand.maximumFrameTime = hand.largestRawStep = hand.largestGripStep = hand.largestGripTurn = hand.largestDisplayStep = 0;
        }

        public void CancelGrabs() { pairScaleFeedback.Hide();Release(left); Release(right); PreviewInteraction.Current?.DirectEditing?.Cancel("Placement or tracking changed"); }
        public static Vector3 DisplayScaleFactors(Vector3 current,Vector3 original)=>new Vector3(
            Mathf.Abs(original.x)>1e-10f?current.x/original.x:1,
            Mathf.Abs(original.y)>1e-10f?current.y/original.y:1,
            Mathf.Abs(original.z)>1e-10f?current.z/original.z:1);
        public void TogglePartMode() { CancelGrabs(); MoveIndividualParts = !MoveIndividualParts; }
        public void ResetArrangement() { CancelGrabs(); scene?.ResetObjectArrangement(); }
        public static Pose ToWorldPose(Transform origin, Pose local) => origin == null ? local
            : new Pose(origin.TransformPoint(local.position), origin.rotation * local.rotation);
        public static Pose RelativeRayPose(Pose aim, Pose target) => new Pose(
            Quaternion.Inverse(aim.rotation) * (target.position - aim.position), Quaternion.Inverse(aim.rotation) * target.rotation);
        public static Pose FollowRay(Pose aim, Pose relative, float depth) => new Pose(
            aim.position + aim.rotation * (relative.position + Vector3.forward * depth), aim.rotation * relative.rotation);
        public static float AdvanceDepth(float depth, float axis, float elapsed) =>
            Mathf.Abs(axis) > .2f ? depth + axis * elapsed : depth;
        public static Pose FollowPlacementRay(Pose aim,Pose relative,float depth,bool preserveRotation,
            Quaternion placementRotation,Quaternion explicitRotation)
        {
            var pose=FollowRay(aim,relative,depth); // Accepted far-ray POSITION mapping stays intact.
            pose.rotation=explicitRotation*(preserveRotation?placementRotation:pose.rotation);
            return pose;
        }
        static void RebasePlacement(Hand hand,Pose aim,Pose target)
        {
            hand.rayRelative=RelativeRayPose(aim,target); hand.placementRotation=target.rotation;
            hand.depth=0; hand.rotationOffset=Quaternion.identity;
        }

        // Use Unity XRI's endpoint-aware ray stabilization BEFORE mapping a distant
        // target. These are InteractionAttachController's default stabilization
        // values and its distance multiplier, without momentum or velocity scaling.
        // Filtering the already-amplified target or removing aim motion changes the UX.
        public static void StabilizeRay(ref Transform stable, Transform raw, Vector3 endpoint, float distance, float dt)
        {
            if (!(dt > 0)) return;
            float multiplier = 1f + Mathf.Max(0f, distance);
            XRTransformStabilizer.ApplyStabilization(ref stable, raw, (Unity.Mathematics.float3)endpoint,
                0.25f * multiplier, 20f * multiplier, dt);
        }
    }
}

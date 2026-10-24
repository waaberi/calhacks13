using System;
using SpatialModeling;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;
using UnityEngine.InputSystem.XR;
using UnityEngine.XR;

public static class WorkspaceChecks
{
    public static void Run()
    {
        var root = new GameObject("Inspection invariant checks");
        try
        {
            var hand = new Pose(new Vector3(1, 1.2f, -2), Quaternion.Euler(10, 70, 5));
            var target = new Pose(new Vector3(-0.4f, 0.7f, 0.8f), Quaternion.Euler(20, 35, 10));
            var relative = WorkspaceInteraction.RelativeRayPose(hand, target);
            var initial = WorkspaceInteraction.FollowRay(hand, relative, 0);
            Near(initial.position, target.position, "Grab must not snap on press");
            Rotation(initial.rotation, target.rotation, "Grab must preserve initial orientation");
            var translated = WorkspaceInteraction.FollowRay(new Pose(hand.position + Vector3.up * 0.3f, hand.rotation), relative, 0);
            Near(translated.position, target.position + Vector3.up * 0.3f, "Hand translation must move held item equally");
            var depth = WorkspaceInteraction.FollowRay(hand, relative, 0.5f);
            Near(depth.position - initial.position, hand.rotation * Vector3.forward * 0.5f, "Depth must follow controller direction");

            root.transform.SetPositionAndRotation(new Vector3(0.2f, 0.9f, 1), Quaternion.Euler(0, 40, 0));
            root.transform.localScale = Vector3.one * 5;
            var first = new GameObject("First part").AddComponent<WorkspaceObjectView>();
            var second = new GameObject("Second part").AddComponent<WorkspaceObjectView>();
            first.transform.SetParent(root.transform, false);
            second.transform.SetParent(root.transform, false);
            var nativeFirst = new Vector3(-0.02f, 0.01f, 0);
            var nativeSecond = new Vector3(0.02f, 0.015f, 0);
            first.SetNativePose(nativeFirst, Quaternion.identity, Vector3.one);
            second.SetNativePose(nativeSecond, Quaternion.identity, Vector3.one);
            var secondBefore = second.transform.localPosition;
            float separation = Vector3.Distance(first.transform.position, second.transform.position);
            root.transform.SetPositionAndRotation(new Vector3(-0.3f, 1.2f, 0.8f), Quaternion.Euler(0, 110, 0));
            Check(Mathf.Abs(Vector3.Distance(first.transform.position, second.transform.position) - separation) < 0.0001f,
                "Whole-build placement must preserve inter-part dimensions");
            Near(first.NativePosition, nativeFirst, "Whole-build placement must not alter native position");
            Near(second.NativePosition, nativeSecond, "Whole-build placement must not alter another native position");

            first.transform.localPosition += new Vector3(0.04f, 0.02f, 0.03f);
            first.transform.localRotation = Quaternion.Euler(0, 30, 0);
            first.RememberArrangement();
            var offset = first.PositionOffset;
            var newNative = nativeFirst + Vector3.right * 0.01f;
            first.SetNativePose(newNative, Quaternion.Euler(0, 10, 0), Vector3.one);
            Near(first.transform.localPosition, newNative + offset, "Live native update must preserve view offset");
            Near(second.transform.localPosition, secondBefore, "Individual arrangement must not move another part");
            first.ResetArrangement();
            Near(first.transform.localPosition, newNative, "Reset must use current native position, not obsolete snapshot");
            Rotation(first.transform.localRotation, Quaternion.Euler(0, 10, 0), "Reset must restore current native rotation");
            Near(first.transform.localScale, Vector3.one, "Arrangement must preserve native scale");
            var local = new Pose(new Vector3(0.2f, 0.1f, -0.3f), Quaternion.Euler(0, 20, 0));
            var world = WorkspaceInteraction.ToWorldPose(root.transform, local);
            Near(root.transform.InverseTransformPoint(world.position), local.position, "Controller tracking origin must be respected");
            CheckGrabSmoothing();
            CheckFarGrabRegression();
            CheckCaptureRequestLanes();
            Check(BlenderScreen.CaptureIsFresh(99900, 100000, 100000), "Fresh pixels and heartbeat must be accepted");
            Check(!BlenderScreen.CaptureIsFresh(1, 100000, 100000), "A fresh server heartbeat must never certify frozen pixels");
            Check(!BlenderScreen.CaptureIsFresh(95000, 95001, 100000), "Stale pixels/server must be rejected");
            Check(!BlenderScreen.CaptureIsFresh(110000, 110001, 100000), "Future-dated pixels must not bypass freshness");
            Check(BlenderScreen.CaptureIsFresh(98000, 100000, 100000), "A real static-window refresh within2s is valid");
            Debug.Log("CAPTURE_FRESHNESS_CHECK PASS fresh-heartbeat/frozen-pixels rejected; real fresh pixels required");
            var startup = new HostScene.StartupFacingGate();
            Check(!startup.Ready(Vector3.forward, false, 0), "Untracked startup must not place the workspace");
            Check(!startup.Ready(new Vector3(0, -0.78f, -0.63f), true, 1), "Putting-on-headset downward pose must not fix placement behind the user");
            Check(!startup.Ready(Vector3.back, true, 2), "First tracked facing sample must settle");
            Check(!startup.Ready(Vector3.forward, true, 2.2), "Turning around during startup must restart settling");
            Check(!startup.Ready(Vector3.forward, true, 2.6), "A changing startup pose must not pass early");
            Check(startup.Ready(Vector3.forward, true, 2.8), "Steady forward facing must allow initial placement");
            Check(!startup.Ready(Vector3.forward, false, 3), "Tracking loss must reset initial-facing readiness");
            Debug.Log("STARTUP_FACING_CHECK PASS downward/turning/untracked rejected; settled tracked facing accepted");
            CheckControllerPoseFormats();
            var trackedSample = new PoseState(true, InputTrackingState.Position | InputTrackingState.Rotation,
                local.position, local.rotation, Vector3.zero, Vector3.zero);
            Check(WorkspaceInteraction.TryGetTrackedPose(trackedSample, out var coherentPose), "A fully tracked pose must be usable");
            Near(coherentPose.position, local.position, "A coherent sample must preserve grip position");
            Rotation(coherentPose.rotation, local.rotation, "A coherent sample must preserve grip rotation");
            trackedSample.isTracked = false;
            Check(!WorkspaceInteraction.TryGetTrackedPose(trackedSample, out _), "Lost tracking must freeze/release rather than consume stale pose");
            trackedSample.isTracked = true;
            trackedSample.trackingState = InputTrackingState.Rotation;
            Check(!WorkspaceInteraction.TryGetTrackedPose(trackedSample, out _), "Rotation-only tracking must not teleport the held item");
            Debug.Log("WORKSPACE_CHECKS PASS: no-snap grab, pose/depth/origin mapping, rigid assembly, native/view separation, live update, reset");
        }
        finally { UnityEngine.Object.DestroyImmediate(root); }
    }

    static void CheckCaptureRequestLanes()
    {
        var lanes = new CaptureRequestLanes();
        int first = lanes.Begin(0), second = lanes.Begin(1);
        Check(lanes.ConditionalTag(null) == null, "New capture must request actual pixels");
        Check(lanes.Observe(0, first, "\"1\"", 99900, 100000, 100000) == CaptureRequestLanes.Decision.Continue,
            "Fresh headers must reserve a frame before body completion");
        Check(lanes.ConditionalTag("\"0\"") == "\"1\"", "Second slot must use the in-flight frame tag");
        Check(lanes.Observe(1, second, "\"1\"", 99900, 100000, 100000) == CaptureRequestLanes.Decision.Duplicate,
            "Both slots must not decode the same fresh frame");
        lanes.Presented(first, 99900, "\"1\""); lanes.End(0, first);
        Check(lanes.Observe(1, second, "\"0\"", 99800, 100000, 100000) == CaptureRequestLanes.Decision.Duplicate,
            "Already displayed/older pixels must be discarded before decoding");
        lanes.Reset();
        Check(!lanes.IsCurrent(first) && lanes.ConditionalTag(null) == null,
            "Unavailable/reset must clear claims and invalidate old requests");
        lanes.Presented(first, 100050, "late old body");
        Check(lanes.ConditionalTag(null) == null, "An invalidated body cannot reserve or present pixels");
        Check(lanes.Observe(0, first, "\"1\"", 99900, 100000, 100000) == CaptureRequestLanes.Decision.Invalidated,
            "Old request headers cannot reclaim a restarted capture");
        int fresh = lanes.Begin(0);
        Check(lanes.Observe(0, fresh, "stale", 1, 100000, 100000) == CaptureRequestLanes.Decision.Pending,
            "Fresh heartbeat cannot reserve stale pixels");
        Check(lanes.Observe(0, fresh, "future", 110000, 110001, 100000) == CaptureRequestLanes.Decision.Pending,
            "Future capture timestamps cannot reserve a slot");
        Check(lanes.ConditionalTag(null) == null, "Invalid metadata cannot create a conditional request");
        Check(lanes.Observe(0, fresh, "\"1\"", 100050, 100100, 100100) == CaptureRequestLanes.Decision.Continue,
            "A reset must allow retrying the same tag after a failed body");
        lanes.End(0, first);
        int other = lanes.Begin(1);
        Check(lanes.Observe(1, other, "\"1\"", 100050, 100100, 100100) == CaptureRequestLanes.Decision.Duplicate,
            "Old completion cannot release a new epoch's claim");
        Check(lanes.Observe(1, other, "\"1\"", 100051, 100100, 100100) == CaptureRequestLanes.Decision.Continue,
            "Reused tag with different actual pixels/time is not the same in-flight frame");
        Check(lanes.Observe(0, fresh, "\"0\"", 100040, 100100, 100100) == CaptureRequestLanes.Decision.Continue,
            "An older pending body may finish without replacing the reserved newest tag");
        Check(lanes.ConditionalTag(null) == "\"1\"", "Late older headers cannot roll reservation back");
        Debug.Log("CAPTURE_REQUEST_LANES_CHECK PASS bounded headers, duplicates, epoch/reset and stale/future pixels");
    }

    static void CheckFarGrabRegression()
    {
        var rawObject = new GameObject("Raw ray regression");
        var stableObject = new GameObject("Stable ray regression");
        try
        {
            var raw = rawObject.transform; var stable = stableObject.transform;
            foreach (float distance in new[] { 0.25f, 1.02f, 2f, 4f })
            {
                var aim = new Pose(Vector3.zero, Quaternion.identity);
                var item = new Pose(Vector3.forward * distance, Quaternion.identity);
                var relative = WorkspaceInteraction.RelativeRayPose(aim, item);
                var pointed = WorkspaceInteraction.FollowRay(new Pose(Vector3.zero, Quaternion.Euler(0, 20, 0)), relative, 0);
                Check(pointed.position.x > distance * 0.3f,
                    "Pointing the controller must MOVE the distant item, not merely rotate it in place");
                raw.SetPositionAndRotation(Vector3.zero, Quaternion.Euler(0, 20, 0));
                stable.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
                var shown = item;
                for (int i = 0; i < 72; i++)
                {
                    WorkspaceInteraction.StabilizeRay(ref stable, raw, shown.position, distance, 1f / 72);
                    shown = WorkspaceInteraction.FollowRay(new Pose(stable.position, stable.rotation), relative, 0);
                }
                Check(shown.position.x > pointed.position.x * 0.9f,
                    "Unity ray stabilization must preserve deliberate aim-based placement at distance " + distance);
            }
            foreach (int rate in new[] { 72, 90, 120 })
            {
                float dt = 1f / rate, rawSteps = 0, displaySteps = 0, maxDisplayStep = 0;
                var item = new Pose(Vector3.forward * 1.02f, Quaternion.identity);
                var relative = WorkspaceInteraction.RelativeRayPose(Pose.identity, item);
                raw.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
                stable.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
                var shown = item; var previousRaw = item.position;
                for (int i = 1; i <= rate * 3; i++)
                {
                    float angle = 2.84f * Mathf.Sin(i * dt * 2 * Mathf.PI * 24);
                    raw.SetPositionAndRotation(Vector3.right * (0.0016f * Mathf.Sin(i * dt * 2 * Mathf.PI * 24)),
                        Quaternion.Euler(0, angle, 0));
                    var desired = WorkspaceInteraction.FollowRay(new Pose(raw.position, raw.rotation), relative, 0);
                    var previous = shown;
                    WorkspaceInteraction.StabilizeRay(ref stable, raw, shown.position, 1.02f, dt);
                    shown = WorkspaceInteraction.FollowRay(new Pose(stable.position, stable.rotation), relative, 0);
                    if (i > rate)
                    {
                        rawSteps += (desired.position - previousRaw).sqrMagnitude;
                        displaySteps += (shown.position - previous.position).sqrMagnitude;
                        maxDisplayStep = Mathf.Max(maxDisplayStep, Vector3.Distance(shown.position, previous.position));
                    }
                    previousRaw = desired.position;
                }
                float ratio = Mathf.Sqrt(displaySteps / rawSteps);
                Check(ratio < 0.35f, "The real Unity stabilized ray must suppress amplified target jitter at " + rate);
                Debug.Log($"FAR_RAY_REGRESSION PASS rate={rate} displayed_step_ratio={ratio:F3} max_display_step_mm={maxDisplayStep * 1000:F2} aim_moves_target=True implementation=XRTransformStabilizer");
            }
        }
        finally { UnityEngine.Object.DestroyImmediate(rawObject); UnityEngine.Object.DestroyImmediate(stableObject); }
    }

    static void CheckControllerPoseFormats()
    {
        // Regression for the real Meta Touch Plus exception: the name PoseControl
        // does not mean its value type is always Input System PoseState.
        InputSystem.RegisterLayout<UnityEngine.InputSystem.XR.PoseControl>("WorkspaceCurrentPose");
        InputSystem.RegisterLayout<UnityEngine.XR.OpenXR.Input.PoseControl>("WorkspaceLegacyPose");
        foreach (var format in new[] { "Current", "Legacy" })
        {
            string layout = "Workspace" + format + "ControllerCheck";
            InputSystem.RegisterLayout("{\"name\":\"" + layout + "\",\"extend\":\"XRController\",\"controls\":["
                + "{\"name\":\"devicePose\",\"layout\":\"Workspace" + format + "Pose\",\"offset\":128},"
                + "{\"name\":\"pointer\",\"layout\":\"Workspace" + format + "Pose\",\"offset\":256,\"usages\":[\"Pointer\"]}]}");
            var device = InputSystem.AddDevice(layout);
            try
            {
                InputSystem.SetDeviceUsage(device, "LeftHand");
                using var grip = new InputAction("test grip", InputActionType.Value,
                    "<" + layout + ">{LeftHand}/devicePose", expectedControlType: "Pose");
                using var aim = new InputAction("test aim", InputActionType.Value,
                    "<" + layout + ">{LeftHand}/{Pointer}", expectedControlType: "Pose");
                grip.Enable(); aim.Enable();
                Check(grip.controls.Count == 1 && aim.controls.Count == 1, "Grip and pointer usage bindings must resolve for " + format);
                var expected = new Pose(new Vector3(0.2f, 1.1f, -0.4f), Quaternion.Euler(20, 40, 10));
                foreach (var control in new[] { grip.controls[0], aim.controls[0] })
                {
                    // Both controls have the same wire-state offsets, although their
                    // C# value types differ. Write a full state, including the bitfield.
                    var state = new PoseState(true, InputTrackingState.Position | InputTrackingState.Rotation,
                        expected.position, expected.rotation, Vector3.zero, Vector3.zero);
                    InputState.Change(control, state);
                    Check(WorkspaceInteraction.TryReadControllerPose(control, out var pose), "Typed pose reader must accept " + format);
                    Near(pose.position, expected.position, "Typed pose reader must preserve " + format + " position");
                    Rotation(pose.rotation, expected.rotation, "Typed pose reader must preserve " + format + " orientation");
                    state.isTracked = false;
                    InputState.Change(control, state);
                    Check(!WorkspaceInteraction.TryReadControllerPose(control, out _), "Tracking loss must reject " + format + " pose");
                }
                Debug.Log("CONTROLLER_POSE_FORMAT_CHECK PASS format=" + format + " type=" + grip.controls[0].valueType.Name);
            }
            finally { InputSystem.RemoveDevice(device); InputSystem.RemoveLayout(layout); }
        }
        InputSystem.RemoveLayout("WorkspaceCurrentPose");
        InputSystem.RemoveLayout("WorkspaceLegacyPose");
    }

    static void CheckGrabSmoothing()
    {
        foreach (int rate in new[] { 72, 90, 120 })
        {
            float dt = 1f / rate;
            var filter = new GrabPoseSmoother();
            var initial = new Pose(new Vector3(0, 1, 1.5f), Quaternion.Euler(0, 179, 0));
            filter.Reset(initial);
            Near(filter.Value.position, initial.position, "Filter pickup must not move the displayed item");
            Rotation(filter.Value.rotation, initial.rotation, "Filter pickup must not rotate the displayed item");
            float rawSquared = 0, filteredSquared = 0, rawAngularSquared = 0, filteredAngularSquared = 0;
            for (int i = 1; i <= rate * 3; i++)
            {
                float noise = Mathf.Sin(i * dt * 2f * Mathf.PI * 24f);
                var sample = new Pose(initial.position + Vector3.right * (0.004f * noise),
                    Quaternion.AngleAxis(0.4f * noise, Vector3.up) * initial.rotation);
                var value = filter.Step(sample, dt);
                if (i <= rate) continue; // Ignore filter initialization in steady-state measurements.
                rawSquared += (sample.position - initial.position).sqrMagnitude;
                filteredSquared += (value.position - initial.position).sqrMagnitude;
                rawAngularSquared += Mathf.Pow(PreciseAngularDistance(sample.rotation, initial.rotation), 2);
                filteredAngularSquared += Mathf.Pow(PreciseAngularDistance(value.rotation, initial.rotation), 2);
            }
            float positionRatio = Mathf.Sqrt(filteredSquared / rawSquared);
            float rotationRatio = Mathf.Sqrt(filteredAngularSquared / rawAngularSquared);
            Check(positionRatio < 0.35f, "Stationary hand jitter must be reduced by at least65percent at " + rate + "Hz");
            Check(rotationRatio < 0.35f, "Wrist jitter must be reduced by at least65percent at " + rate + "Hz");

            filter.Reset(initial);
            float maximumLag = 0;
            for (int i = 1; i <= rate * 2; i++)
            {
                var desired = new Pose(initial.position + Vector3.right * (0.5f * i * dt), initial.rotation);
                var value = filter.Step(desired, dt);
                Check(value.position.x <= desired.position.x + 0.0001f, "Drag smoothing must not overshoot the hand");
                maximumLag = Mathf.Max(maximumLag, desired.position.x - value.position.x);
            }
            Check(maximumLag < 0.035f, "A deliberate0.5m/s drag must not trail by more than35mm");
            var settledTarget = new Pose(initial.position + Vector3.right, initial.rotation);
            for (int i = 0; i < rate / 2; i++) filter.Step(settledTarget, dt);
            Check(Vector3.Distance(filter.Value.position, settledTarget.position) < 0.001f, "A held item must settle within1mm");
            var placed = filter.Value;
            filter.Step(new Pose(Vector3.one * 100, Quaternion.identity), 0);
            Near(filter.Value.position, placed.position, "A zero-time frame must not move the item");
            var secondItem = new Pose(Vector3.left, Quaternion.Euler(10, -179, 20));
            filter.Reset(secondItem);
            Near(filter.Value.position, secondItem.position, "Regrab must discard previous target momentum");
            var antipodal = secondItem.rotation;
            antipodal = new Quaternion(-antipodal.x, -antipodal.y, -antipodal.z, -antipodal.w);
            Rotation(filter.Step(new Pose(secondItem.position, antipodal), dt).rotation, secondItem.rotation,
                "Equivalent quaternion signs must not create a rotation jump");
            filter.Reset(initial);
            float angularLag = 0;
            for (int i = 1; i <= rate * 2; i++)
            {
                var turn = new Pose(initial.position, Quaternion.AngleAxis(90f * i * dt, Vector3.up) * initial.rotation);
                angularLag = Mathf.Max(angularLag, PreciseAngularDistance(filter.Step(turn, dt).rotation, turn.rotation));
            }
            Check(angularLag < 6f, "Deliberate rotation must stay responsive across the180degree boundary");
            Debug.Log($"GRAB_SMOOTHING_CHECK rate={rate} position_jitter_ratio={positionRatio:F3} rotation_jitter_ratio={rotationRatio:F3} max_lag_m={maximumLag:F4}");
        }
    }

    // Quaternion.Angle rounds very small differences to zero. RMS jitter measurements
    // need the actual residual angle, including changes below its dot-product tolerance.
    static float PreciseAngularDistance(Quaternion a, Quaternion b)
    {
        var delta = a * Quaternion.Inverse(b);
        return 2f * Mathf.Atan2(new Vector3(delta.x, delta.y, delta.z).magnitude, Mathf.Abs(delta.w)) * Mathf.Rad2Deg;
    }

    static void Check(bool value, string message) { if (!value) throw new Exception(message); }
    static void Near(Vector3 actual, Vector3 expected, string message) => Check(Vector3.Distance(actual, expected) < 0.0001f, message);
    static void Rotation(Quaternion actual, Quaternion expected, string message) => Check(Quaternion.Angle(actual, expected) < 0.05f, message);
}

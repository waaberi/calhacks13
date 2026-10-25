using System;
using System.Reflection;
using SpatialModeling;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;
using UnityEngine.InputSystem.XR;
using UnityEngine.XR;

public static class ControllerPoseChecks
{
    static void Check(bool value, string message)
    {
        if (!value) throw new Exception("Controller pair: " + message);
    }

    public static void Run()
    {
        InputSystem.RegisterLayout<UnityEngine.InputSystem.XR.PoseControl>("PairCurrentPose");
        InputSystem.RegisterLayout<UnityEngine.XR.OpenXR.Input.PoseControl>("PairLegacyPose");
        try
        {
            foreach (string format in new[] { "Current", "Legacy" }) CheckFormat(format);
        }
        finally
        {
            InputSystem.RemoveLayout("PairCurrentPose");
            InputSystem.RemoveLayout("PairLegacyPose");
        }
        Debug.Log("CONTROLLER_PAIR_CHECKS PASS same_device distinct_aim missing_aim mixed_device tracking_loss recovery source_stability formats=2 physical_fit=UNVERIFIED");
    }

    static void SetPose(InputControl control, Vector3 position, Quaternion rotation, bool tracked = true)
    {
        // The two supported pose formats share the wire-state layout. This is the
        // same concrete input-control route used by production, not a pose mock.
        InputState.Change(control, new PoseState(tracked,
            tracked ? InputTrackingState.Position | InputTrackingState.Rotation : InputTrackingState.None,
            position, rotation, Vector3.zero, Vector3.zero));
    }

    static void CheckFormat(string format)
    {
        string layout = "Pair" + format + "Controller";
        InputSystem.RegisterLayout("{\"name\":\"" + layout + "\",\"extend\":\"XRController\",\"controls\":["
            + "{\"name\":\"devicePose\",\"layout\":\"Pair" + format + "Pose\",\"offset\":128},"
            + "{\"name\":\"pointer\",\"layout\":\"Pair" + format + "Pose\",\"offset\":256,\"usages\":[\"Pointer\"]}]}");
        var first = InputSystem.AddDevice(layout);
        var second = InputSystem.AddDevice(layout);
        try
        {
            InputSystem.SetDeviceUsage(first, "LeftHand");
            InputSystem.SetDeviceUsage(second, "LeftHand");
            using var grip = new InputAction("pair grip", InputActionType.Value,
                "<" + layout + ">{LeftHand}/devicePose", expectedControlType: "Pose");
            using var aim = new InputAction("pair aim", InputActionType.Value,
                "<" + layout + ">{LeftHand}/{Pointer}", expectedControlType: "Pose");
            using var absent = new InputAction("absent aim", InputActionType.Value,
                "<" + layout + ">{RightHand}/{Pointer}", expectedControlType: "Pose");
            grip.Enable(); aim.Enable(); absent.Enable();
            Check(grip.controls.Count == 2 && aim.controls.Count == 2, "actual usage bindings resolve " + format);
            var firstGrip = first["devicePose"];
            var firstAim = first["pointer"];
            var secondGrip = second["devicePose"];
            var secondAim = second["pointer"];
            var angle = Quaternion.Euler(31, 24, 9);
            SetPose(firstGrip, new Vector3(.1f, 1, .2f), Quaternion.identity);
            SetPose(firstAim, new Vector3(.13f, 1.02f, .22f), angle);
            SetPose(secondGrip, new Vector3(2, 1, 2), Quaternion.identity);
            SetPose(secondAim, new Vector3(2, 1, 2), Quaternion.identity);
            Check(WorkspaceInteraction.TryReadControllerPair(grip, aim, firstGrip,
                out var g, out var a, out var gc, out var ac), "valid pair " + format);
            Check(gc == firstGrip && ac == firstAim, "preferred device kept stable");
            Check(Vector3.Distance(g.position, new Vector3(.1f, 1, .2f)) < .0001f
                && Quaternion.Angle(a.rotation, angle) < .01f, "distinct grip and aim values retained");
            Check(!WorkspaceInteraction.TryReadControllerPair(grip, absent, firstGrip,
                out _, out _, out _, out _), "missing aim never becomes grip");
            SetPose(firstAim, Vector3.zero, Quaternion.identity, false);
            SetPose(secondGrip, Vector3.zero, Quaternion.identity, false);
            Check(!WorkspaceInteraction.TryReadControllerPair(grip, aim, firstGrip,
                out _, out _, out _, out _), "tracked grip A plus tracked aim B cannot form pair");
            SetPose(secondGrip, Vector3.one, Quaternion.identity);
            Check(WorkspaceInteraction.TryReadControllerPair(grip, aim, firstGrip,
                out _, out _, out gc, out ac) && gc == secondGrip && ac == secondAim,
                "only complete replacement pair selected");
            CheckTwoHandReplacement(grip, aim, firstGrip, secondGrip);
            SetPose(firstAim, Vector3.zero, angle);
            Check(WorkspaceInteraction.TryReadControllerPair(grip, aim, secondGrip,
                out _, out _, out gc, out _) && gc == secondGrip, "recovery does not steal active source");
            SetPose(firstGrip, Vector3.zero, Quaternion.identity, false);
            SetPose(secondGrip, Vector3.zero, Quaternion.identity, false);
            Check(!WorkspaceInteraction.TryReadControllerPair(grip, aim, secondGrip,
                out _, out _, out _, out _), "grip tracking loss rejects otherwise valid aim");
        }
        finally
        {
            InputSystem.RemoveDevice(first);
            InputSystem.RemoveDevice(second);
            InputSystem.RemoveLayout(layout);
        }
    }

    static void CheckTwoHandReplacement(InputAction grip, InputAction aim,
        InputControl oldGrip, InputControl replacementGrip)
    {
        // Invoke the real UpdatePair/ReadHand/Release/handoff path: resolver-only
        // checks missed stale shared ownership after ReadHand changed the source.
        var owner = new GameObject("Two-hand replacement check");
        owner.SetActive(false);
        var target = new GameObject("Held plane");
        var stable = new GameObject("Surviving hand stable aim");
        var previousPreview = PreviewInteraction.Current;
        try
        {
            var interaction = owner.AddComponent<WorkspaceInteraction>();
            var preview = owner.AddComponent<PreviewInteraction>();
            typeof(PreviewInteraction).GetProperty("Current").GetSetMethod(true).Invoke(null, new object[] { preview });
            var previewPrivate = BindingFlags.Instance | BindingFlags.NonPublic;
            typeof(PreviewInteraction).GetField("inputEnabled", previewPrivate).SetValue(preview, true);
            typeof(PreviewInteraction).GetField("triggerWasDown", previewPrivate).SetValue(preview, true);
            var type = typeof(WorkspaceInteraction);
            var handType = type.GetNestedType("Hand", BindingFlags.NonPublic);
            object replaced = Activator.CreateInstance(handType, true);
            object surviving = Activator.CreateInstance(handType, true);
            foreach (var hand in new[] { replaced, surviving })
            {
                handType.GetField("gripPose").SetValue(hand, grip);
                handType.GetField("aimPose").SetValue(hand, aim);
                handType.GetField("target").SetValue(hand, target.transform);
            }
            handType.GetField("previousGripControl").SetValue(replaced, oldGrip);
            handType.GetField("node").SetValue(replaced, XRNode.RightHand);
            handType.GetField("node").SetValue(surviving, XRNode.LeftHand);
            handType.GetField("previousGripControl").SetValue(surviving, replacementGrip);
            handType.GetField("stableAim").SetValue(surviving, stable.transform);
            type.GetField("left", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(interaction, replaced);
            type.GetField("right", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(interaction, surviving);
            var pair = type.GetField("pairTarget", BindingFlags.Instance | BindingFlags.NonPublic);
            pair.SetValue(interaction, target.transform);
            target.transform.SetPositionAndRotation(new Vector3(3, 2, 1), Quaternion.Euler(0, 23, 0));
            var before = new Pose(target.transform.position, target.transform.rotation);
            type.GetMethod("UpdatePair", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(interaction, null);
            Check(!(bool)typeof(PreviewInteraction).GetField("inputEnabled", previewPrivate).GetValue(preview)
                && (bool)typeof(PreviewInteraction).GetField("triggerWasDown", previewPrivate).GetValue(preview)
                && (bool)typeof(PreviewInteraction).GetField("endAfterRelease", previewPrivate).GetValue(preview),
                "controller replacement suspends native input, requires a fresh trigger release and retains release acknowledgement barrier");
            Check(handType.GetField("target").GetValue(replaced) == null, "source replacement releases old hold");
            Check(ReferenceEquals(handType.GetField("target").GetValue(surviving), target.transform), "surviving hand keeps hold");
            Check(pair.GetValue(interaction) == null, "stale pair cleared after source replacement");
            Check(Vector3.Distance(target.transform.position, before.position) < .0001f
                && Quaternion.Angle(target.transform.rotation, before.rotation) < .01f,
                "replacement freezes object before surviving-hand rebase");
            Debug.Log("P225_CONTROLLER_OWNERSHIP_CHECK PASS real paired-device replacement releases P2 hold and suspends P25 input with acknowledgement barrier");
        }
        finally
        {
            typeof(PreviewInteraction).GetProperty("Current").GetSetMethod(true).Invoke(null, new object[] { previousPreview });
            // Inactive owner never enabled or owned these externally scoped actions.
            UnityEngine.Object.DestroyImmediate(owner);
            UnityEngine.Object.DestroyImmediate(target);
            UnityEngine.Object.DestroyImmediate(stable);
        }
    }
}

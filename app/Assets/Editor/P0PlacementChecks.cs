using System;
using SpatialModeling;
using UnityEngine;

// Run with -batchmode -executeMethod P0PlacementChecks.Run. No headset required.
public static class P0PlacementChecks
{
    public static void Run()
    {
        var eye = new Vector3(4f, 1.7f, -3f);
        foreach (var yaw in new[] { 0f, 90f, 120f, 180f, 270f })
        {
            var gaze = Quaternion.Euler(25f, yaw, 0f) * Vector3.forward;
            Require(HostScene.TryGetDisplayPose(eye, gaze, 1f, 0.35f, out var position, out var rotation), "valid gaze rejected");
            var delta = position - eye;
            var horizontal = Vector3.ProjectOnPlane(delta, Vector3.up);
            Require(Mathf.Abs(horizontal.magnitude - 1f) < 0.0001f, "distance is not one meter");
            Require(Vector3.Dot(horizontal.normalized, Vector3.ProjectOnPlane(gaze, Vector3.up).normalized) > 0.9999f, "display is not in front of current heading");
            Require(Mathf.Abs(delta.y + 0.35f) < 0.0001f, "incorrect eye-relative height");
            Require(Vector3.Dot(rotation * Vector3.up, Vector3.up) > 0.9999f, "display tilts with gaze");
            // A native 10mm X change at display scale 5 remains 50mm in display
            // space for every heading; recenter must neither rescale nor reflect it.
            var a = position + rotation * (new Vector3(-0.020f, 0.010f, 0f) * 5f);
            var b = position + rotation * (new Vector3(-0.010f, 0.010f, 0f) * 5f);
            Require(Mathf.Abs(Vector3.Distance(a, b) - 0.05f) < 0.0001f, "native delta distorted");
        }
        Require(!HostScene.TryGetDisplayPose(eye, Vector3.up, 1f, 0.35f, out _, out _), "vertical gaze must wait");
        Require(!HostScene.TryGetDisplayPose(eye, Vector3.zero, 1f, 0.35f, out _, out _), "missing gaze must wait");
        Debug.Log("P0_PLACEMENT_CHECKS PASS: five headings including 120/180deg; distance, height, upright orientation, movement scale and invalid gaze");
    }

    static void Require(bool condition, string message)
    {
        if (!condition) throw new Exception("P0 placement regression: " + message);
    }
}

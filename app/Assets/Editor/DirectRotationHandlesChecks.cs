using System;
using SpatialModeling;
using UnityEngine;

public static class DirectRotationHandlesChecks
{
    static void Check(bool value, string reason) { if (!value) throw new Exception("DIRECT_ROTATION_HANDLES: " + reason); }
    static void Near(float actual, float expected, string reason) => Check(Mathf.Abs(actual - expected) < .05f, reason + " (" + actual + ", expected " + expected + ")");

    public static void Run()
    {
        PickingAndOcclusion(); FrozenAngularDrag(); EdgeOnDrag(); VisualGeometry();
        Debug.Log("DIRECT_ROTATION_HANDLES_CHECK PASS RGB-rings/arrowheads/ray-tolerance/nearest-fence/negative-nonuniform-map/frozen-native-pivot/angular-wrap/edge-on-tangent; physical acceptance pending");
    }
    static Vector3[] Axes(Matrix4x4 map, Quaternion orientation) => new[] {
        map.MultiplyVector(orientation * Vector3.right).normalized,
        map.MultiplyVector(orientation * Vector3.forward).normalized,
        map.MultiplyVector(orientation * Vector3.up).normalized
    };
    static void PickingAndOcclusion()
    {
        var map = Matrix4x4.identity;
        var frame = new DirectRotationHandles.Frame(map, Vector3.zero, Axes(map, Quaternion.identity), new Vector3(0, 0, -1));
        Check(frame.Valid, "valid native frame");
        for (int axis = 0; axis < 3; axis++)
        {
            Vector3 at = frame.Point(axis, .63f), normal = frame.NativeAxis(axis);
            var ray = new Ray(at + normal * .2f, -normal);
            Check(DirectRotationHandles.TryPick(frame, ray, .21f, out var hit), "the visible ring itself is trigger pickable " + axis);
            Check(hit.Axis == axis, "a ring chooses the matching native constraint " + axis);
            Check(!DirectRotationHandles.TryPick(frame, ray, .17f, out _), "nearer unrelated UI can fence ring interaction " + axis);
            Check(!DirectRotationHandles.TryPick(frame, new Ray(at + normal * .2f, normal), 10, out _), "ring behind the controller ray is refused " + axis);
        }
        Check(DirectRotationHandles.PickTolerance(2) > DirectRotationHandles.PickTolerance(.4f), "headset distance expands angular hit tolerance");
        Check(!new DirectRotationHandles.Frame(Matrix4x4.Scale(new Vector3(0, 1, 1)), Vector3.zero, Axes(map, Quaternion.identity), Vector3.back).Valid, "singular presentation cannot emit an invalid rotation");
    }
    static void FrozenAngularDrag()
    {
        foreach (var scale in new[] { Vector3.one, new Vector3(-2f, .4f, 3f) })
        foreach (int axis in new[] { 0, 1, 2 })
        {
            Matrix4x4 map = Matrix4x4.TRS(new Vector3(1, 2, -1), Quaternion.Euler(19, 53, -27), scale);
            Vector3 pivot = map.MultiplyPoint3x4(new Vector3(.04f, -.07f, .1f));
            Quaternion orientation = Quaternion.Euler(13, -32, 22);
            var frame = new DirectRotationHandles.Frame(map, pivot, Axes(map, orientation), new Vector3(0, 1, -2));
            Vector3 normal = map.inverse.transpose.MultiplyVector(frame.NativeAxis(axis)).normalized;
            Vector3 eye = pivot + normal * 2f;
            var firstPoint = frame.Point(axis, .5f);
            var initial = new Ray(eye, (firstPoint - eye).normalized);
            var gesture = new DirectRotationHandles.Gesture(frame, new DirectRotationHandles.Hit { Axis = axis, Distance = Vector3.Distance(eye, firstPoint), Point = firstPoint }, initial);
            for (int step = 1; step <= 18; step++)
            {
                var point = frame.Point(axis, .5f + step * 25f * Mathf.Deg2Rad);
                Check(gesture.Update(new Ray(eye, (point - eye).normalized)), "angular native plane remains valid");
            }
            Near(gesture.AngleDegrees, 450f, "angular accumulation crosses +/-180 without reversing, including reflected arrangement");
            var expected = Quaternion.AngleAxis(450f, frame.NativeAxis(axis));
            Check(Quaternion.Angle(gesture.NativeRotationFor(map), expected) < .05f, "primary target reflection is converted exactly once");
            var targetMap = Matrix4x4.TRS(Vector3.one, Quaternion.Euler(2, 41, -6), new Vector3(1, 2, 3));
            Vector3 targetAxis = targetMap.inverse.MultiplyVector(map.MultiplyVector(frame.NativeAxis(axis))).normalized;
            var targetExpected = Quaternion.AngleAxis(450f * Mathf.Sign(map.determinant) * Mathf.Sign(targetMap.determinant), targetAxis);
            Check(Quaternion.Angle(gesture.NativeRotationFor(targetMap), targetExpected) < .05f, "multi-selection targets respect their own native-to-display basis");
            Check(Vector3.Distance(frame.DisplayPivot, pivot) < .000001f, "frame keeps immutable native pivot throughout gesture");
        }
    }
    static void EdgeOnDrag()
    {
        Matrix4x4 map = Matrix4x4.identity;
        var frame = new DirectRotationHandles.Frame(map, Vector3.zero, Axes(map, Quaternion.identity), Vector3.back);
        Vector3 point = frame.Point(0, 0), eye = point - Vector3.forward;
        var ray = new Ray(eye, Vector3.forward);
        var gesture = new DirectRotationHandles.Gesture(frame, new DirectRotationHandles.Hit { Axis = 0, Distance = 1f, Point = point }, ray);
        Vector3 tangent = frame.Tangent(0, frame.NativeRadial(0, 0));
        var updated = new Ray(eye + tangent * .5f, Vector3.forward);
        Check(gesture.Update(updated), "edge-on ring remains usable without unstable plane intersections");
        Near(gesture.AngleDegrees, .5f * Mathf.Rad2Deg, "edge-on tangent motion has the native rotation sign");
        Check(gesture.Update(ray), "returning to start is allowed"); Near(gesture.AngleDegrees, 0, "cumulative tangent parameters return exactly to baseline");
    }
    static void VisualGeometry()
    {
        using (var visual = new DirectRotationHandles())
        {
            Matrix4x4 map = Matrix4x4.identity;
            var frame = new DirectRotationHandles.Frame(map, Vector3.zero, Axes(map, Quaternion.identity), Vector3.back);
            visual.Draw(frame, 1);
            var root = GameObject.Find("Native Blender rotation rings");
            Check(root != null, "production ring renderer exists");
            var lines = root.GetComponentsInChildren<LineRenderer>();
            Check(lines.Length == 9, "three rings and two directional arrows per axis");
            int closed = 0, arrows = 0;
            foreach (var line in lines)
            {
                Check(line.useWorldSpace && line.widthMultiplier >= .004f, "headset-visible world geometry");
                if (line.positionCount == DirectRotationHandles.Segments + 1)
                {
                    closed++; Check(Vector3.Distance(line.GetPosition(0), line.GetPosition(line.positionCount - 1)) < .00001f, "ring has no visible seam");
                }
                else if (line.positionCount == 3) arrows++;
            }
            Check(closed == 3 && arrows == 6, "each native axis has a complete circle and arrowheads");
            visual.Hide(); Check(!root.activeSelf, "ending editing hides all rings without affecting existing move/scale handles");
        }
        Check(GameObject.Find("Native Blender rotation rings") == null, "visual lifetime disposes its root");
    }
}

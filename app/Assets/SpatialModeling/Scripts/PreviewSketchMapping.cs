using UnityEngine;

namespace SpatialModeling
{
    // Native coordinates are meters, right handed and Z up. Display placement
    // is removed before the Blender frame conversion, exactly once.
    public static class PreviewSketchMapping
    {
        static Vector3 Swap(Vector3 p) => new Vector3(p.x, p.z, p.y);
        static bool Finite(float f) => !float.IsNaN(f) && !float.IsInfinity(f);
        static bool Finite(Vector3 p) => Finite(p.x) && Finite(p.y) && Finite(p.z);

        public static bool TryMapRay(Ray worldRay, Matrix4x4 displayLocalToWorld,
            Vector3 planeOriginBlenderMeters, Quaternion planeRotationBlender,
            out Vector2 sketchMeters, out Vector3 worldHit)
        {
            sketchMeters = default; worldHit = default;
            for (int i = 0; i < 16; i++) if (!Finite(displayLocalToWorld[i])) return false;
            if (!Finite(planeOriginBlenderMeters) || !Finite(worldRay.origin) || !Finite(worldRay.direction)
                || worldRay.direction.sqrMagnitude < 1e-8f || Mathf.Abs(displayLocalToWorld.determinant) < 1e-12f) return false;
            float qlength = Quaternion.Dot(planeRotationBlender, planeRotationBlender);
            if (!Finite(qlength) || Mathf.Abs(qlength - 1f) > 0.002f) return false;
            var inverse = displayLocalToWorld.inverse;
            var origin = displayLocalToWorld.MultiplyPoint3x4(Swap(planeOriginBlenderMeters));
            var normal = inverse.transpose.MultiplyVector(Swap(planeRotationBlender * Vector3.forward)).normalized;
            var ray = new Ray(worldRay.origin, worldRay.direction.normalized);
            var plane = new Plane(normal, origin);
            if (!plane.Raycast(ray, out float distance) || distance < 0 || distance > 20f) return false;
            worldHit = ray.GetPoint(distance);
            var nativeWorld = Swap(inverse.MultiplyPoint3x4(worldHit));
            var local = Quaternion.Inverse(planeRotationBlender) * (nativeWorld - planeOriginBlenderMeters);
            if (!Finite(local) || Mathf.Abs(local.x) > 1000f || Mathf.Abs(local.y) > 1000f) return false;
            sketchMeters = new Vector2(local.x, local.y);
            return true;
        }

        public static Vector3 WorldPoint(Vector2 point, Matrix4x4 displayLocalToWorld,
            Vector3 planeOriginBlenderMeters, Quaternion planeRotationBlender)
        {
            var native = planeOriginBlenderMeters + planeRotationBlender * new Vector3(point.x, point.y, 0);
            return displayLocalToWorld.MultiplyPoint3x4(Swap(native));
        }
    }
}

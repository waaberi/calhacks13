using System;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpatialModeling
{
    /// <summary>Native-axis rotation rings. Geometry and gesture math use the same frozen frame.</summary>
    public sealed class DirectRotationHandles : IDisposable
    {
        public const int Segments = 96;
        const float Tau = Mathf.PI * 2f;
        readonly LineRenderer[] rings = new LineRenderer[3];
        readonly LineRenderer[] arrows = new LineRenderer[6];
        readonly Material[] materials = new Material[3];
        GameObject root;
        static readonly Color[] Colours = {
            new Color(1f, .16f, .12f, 1f), new Color(.18f, 1f, .22f, 1f), new Color(.18f, .48f, 1f, 1f)
        };

        public sealed class Frame
        {
            public readonly Matrix4x4 NativeToDisplay, DisplayToNative;
            public readonly Vector3 NativePivot, DisplayPivot;
            public readonly float Radius, Width;
            readonly Vector3[] axes = new Vector3[3], first = new Vector3[3], second = new Vector3[3];
            public bool Valid { get; private set; }

            // displayAxes are Blender's current X/Y/Z orientation, after the
            // existing native-to-display placement conversion exactly once.
            public Frame(Matrix4x4 map, Vector3 displayPivot, Vector3[] displayAxes, Vector3 eye, float minimumRadius = .12f)
            {
                NativeToDisplay = map; DisplayToNative = map.inverse;
                DisplayPivot = displayPivot; NativePivot = DisplayToNative.MultiplyPoint3x4(displayPivot);
                float distance = Vector3.Distance(eye, displayPivot);
                // The comfort size may be capped; selection clearance must not
                // be capped or enlarged/scaled models swallow their own gizmo.
                Radius = Mathf.Max(minimumRadius, Mathf.Clamp(distance * .065f, .10f, .28f));
                Width = Mathf.Clamp(distance * .0025f, .004f, .008f);
                if (displayAxes == null || displayAxes.Length != 3 || Mathf.Abs(map.determinant) < 1e-12f) return;
                for (int i = 0; i < 3; i++)
                {
                    axes[i] = DisplayToNative.MultiplyVector(displayAxes[i]).normalized;
                    if (!Finite(axes[i]) || axes[i].sqrMagnitude < .99f) return;
                    Vector3 seed = Mathf.Abs(Vector3.Dot(axes[i], Vector3.up)) < .8f ? Vector3.up : Vector3.right;
                    first[i] = Vector3.Cross(axes[i], seed).normalized;
                    second[i] = Vector3.Cross(axes[i], first[i]).normalized;
                    float stretch = Mathf.Max(map.MultiplyVector(first[i]).magnitude, map.MultiplyVector(second[i]).magnitude);
                    if (stretch < 1e-8f || float.IsInfinity(stretch) || float.IsNaN(stretch)) return;
                }
                Valid = true;
            }
            public Vector3 NativeAxis(int axis) => axes[axis];
            public Vector3 DisplayAxis(int axis) => NativeToDisplay.MultiplyVector(axes[axis]).normalized;
            public Vector3 NativeRadial(int axis, float radians) => first[axis] * Mathf.Cos(radians) + second[axis] * Mathf.Sin(radians);
            // Normalize in display space so reflection/nonuniform inspection
            // transforms cannot squash one side back inside the selection.
            // Inverting these points still gives the exact native rotation plane.
            public Vector3 Point(int axis, float radians) => DisplayPivot + NativeToDisplay.MultiplyVector(NativeRadial(axis, radians)).normalized * Radius;
            public Vector3 Tangent(int axis, Vector3 nativeRadial)
            {
                Vector3 direction = NativeToDisplay.MultiplyVector(nativeRadial);
                Vector3 derivative = NativeToDisplay.MultiplyVector(Vector3.Cross(axes[axis], nativeRadial));
                float length = direction.magnitude;
                if (length < 1e-8f) return Vector3.zero;
                return Radius * (derivative / length - direction * (Vector3.Dot(direction, derivative) / (length * length * length)));
            }
        }

        public struct Hit
        {
            public int Axis;
            public float Distance;
            public Vector3 Point;
        }

        public sealed class Gesture
        {
            public readonly Frame Frozen;
            public readonly int Axis;
            readonly bool planeDrag;
            readonly float startDepth;
            readonly Vector3 startPoint, tangent;
            Vector3 previousRadial;
            public float AngleDegrees { get; private set; }

            public Gesture(Frame frame, Hit hit, Ray ray)
            {
                if (frame == null || !frame.Valid || hit.Axis < 0 || hit.Axis > 2) throw new ArgumentException("Invalid rotation ring frame");
                Frozen = frame; Axis = hit.Axis; startDepth = hit.Distance; startPoint = ray.GetPoint(startDepth);
                var nativeHit = frame.DisplayToNative.MultiplyPoint3x4(hit.Point) - frame.NativePivot;
                previousRadial = Vector3.ProjectOnPlane(nativeHit, frame.NativeAxis(Axis)).normalized;
                tangent = frame.Tangent(Axis, previousRadial);
                var nativeDirection = frame.DisplayToNative.MultiplyVector(ray.direction).normalized;
                planeDrag = Mathf.Abs(Vector3.Dot(nativeDirection, frame.NativeAxis(Axis))) > .12f
                    && PlaneRadial(ray, out previousRadial);
            }

            bool PlaneRadial(Ray ray, out Vector3 radial)
            {
                radial = default;
                Vector3 origin = Frozen.DisplayToNative.MultiplyPoint3x4(ray.origin);
                Vector3 direction = Frozen.DisplayToNative.MultiplyVector(ray.direction);
                float denominator = Vector3.Dot(direction, Frozen.NativeAxis(Axis));
                if (Mathf.Abs(denominator) < 1e-7f) return false;
                float distance = Vector3.Dot(Frozen.NativePivot - origin, Frozen.NativeAxis(Axis)) / denominator;
                if (distance <= 0 || !Finite(distance)) return false;
                radial = Vector3.ProjectOnPlane(origin + direction * distance - Frozen.NativePivot, Frozen.NativeAxis(Axis));
                if (!Finite(radial) || radial.sqrMagnitude < 1e-12f) return false;
                radial.Normalize(); return true;
            }

            public bool Update(Ray ray)
            {
                if (planeDrag)
                {
                    if (!PlaneRadial(ray, out var radial)) return false;
                    float step = Mathf.Atan2(Vector3.Dot(Frozen.NativeAxis(Axis), Vector3.Cross(previousRadial, radial)), Vector3.Dot(previousRadial, radial)) * Mathf.Rad2Deg;
                    AngleDegrees = Mathf.Clamp(AngleDegrees + step, -36000f, 36000f); previousRadial = radial;
                }
                else
                {
                    // An edge-on ring has no stable ray/rotation-plane
                    // intersection. Its visible tangent remains draggable.
                    if (tangent.sqrMagnitude < 1e-12f) return false;
                    AngleDegrees = Mathf.Clamp(Vector3.Dot(ray.GetPoint(startDepth) - startPoint, tangent) / tangent.sqrMagnitude * Mathf.Rad2Deg, -36000f, 36000f);
                }
                return true;
            }

            public Quaternion NativeRotationFor(Matrix4x4 targetMap)
            {
                Vector3 axis = targetMap.inverse.MultiplyVector(Frozen.NativeToDisplay.MultiplyVector(Frozen.NativeAxis(Axis))).normalized;
                // Angles are measured in native coordinates. Only a different
                // target presentation's reflection changes their handedness.
                float handedness = Mathf.Sign(Frozen.NativeToDisplay.determinant) * Mathf.Sign(targetMap.determinant);
                return Quaternion.AngleAxis(AngleDegrees * handedness, axis);
            }
        }

        public static float PickTolerance(float depth) => Mathf.Clamp(depth * .009f, .009f, .025f);
        public static bool TryPick(Frame frame, Ray ray, float nearest, out Hit hit)
        {
            hit = default;
            if (frame == null || !frame.Valid || nearest <= 0 || ray.direction.sqrMagnitude < 1e-10f) return false;
            bool found = false; float bestScore = float.PositiveInfinity;
            for (int axis = 0; axis < 3; axis++)
            for (int i = 0; i < Segments; i++)
            {
                Vector3 a = frame.Point(axis, Tau * i / Segments), b = frame.Point(axis, Tau * (i + 1) / Segments);
                if (!ClosestSegment(ray, a, b, out float depth, out float miss, out var point) || depth > nearest) continue;
                float tolerance = PickTolerance(depth), score = miss / tolerance;
                if (score > 1f || (found && score > bestScore + .015f)
                    || (found && Mathf.Abs(score - bestScore) <= .015f && depth >= hit.Distance)) continue;
                found = true; bestScore = score; hit = new Hit { Axis = axis, Distance = depth, Point = point };
            }
            return found;
        }

        static bool ClosestSegment(Ray ray, Vector3 a, Vector3 b, out float depth, out float miss, out Vector3 point)
        {
            Vector3 d = ray.direction.normalized, segment = b - a, offset = a - ray.origin;
            float along = Vector3.Dot(segment, d), denominator = segment.sqrMagnitude - along * along;
            float amount = denominator > 1e-12f ? Mathf.Clamp01((along * Vector3.Dot(offset, d) - Vector3.Dot(offset, segment)) / denominator) : 0;
            point = a + segment * amount; depth = Vector3.Dot(point - ray.origin, d);
            miss = Vector3.Distance(point, ray.origin + d * depth); return depth > 0;
        }

        public void Draw(Frame frame, int highlighted = -1)
        {
            if (frame == null || !frame.Valid) { Hide(); return; }
            EnsureVisuals(); root.SetActive(true);
            for (int axis = 0; axis < 3; axis++)
            {
                Color colour = axis == highlighted ? new Color(1f, .85f, .18f, 1f) : Colours[axis];
                // UI/Default consumes LineRenderer vertex colour; URP/Unlit
                // needs its material base colour explicitly when used as fallback.
                if (materials[axis].HasProperty("_BaseColor")) materials[axis].SetColor("_BaseColor", colour);
                var ring = rings[axis]; ring.widthMultiplier = frame.Width * (axis == highlighted ? 1.5f : 1f);
                ring.startColor = ring.endColor = colour;
                for (int i = 0; i <= Segments; i++) ring.SetPosition(i, frame.Point(axis, Tau * i / Segments));
                for (int side = 0; side < 2; side++)
                {
                    float angle = .65f + side * Mathf.PI;
                    Vector3 tip = frame.Point(axis, angle + .13f), tail = frame.Point(axis, angle - .06f);
                    Vector3 radial = (frame.Point(axis, angle) - frame.DisplayPivot).normalized;
                    float size = Mathf.Clamp(frame.Radius * .085f, .009f, .022f);
                    var arrow = arrows[axis * 2 + side]; arrow.widthMultiplier = ring.widthMultiplier;
                    arrow.startColor = arrow.endColor = colour;
                    arrow.SetPositions(new[] { tail + radial * size, tip, tail - radial * size });
                }
            }
        }

        void EnsureVisuals()
        {
            if (root != null) return;
            root = new GameObject("Native Blender rotation rings");
            Shader shader = Shader.Find("UI/Default") ?? Shader.Find("Universal Render Pipeline/Unlit");
            for (int axis = 0; axis < 3; axis++)
            {
                var material = new Material(shader) { name = "Native rotation " + "XYZ"[axis], renderQueue = 4000 };
                material.SetInt("unity_GUIZTestMode", (int)CompareFunction.Always);
                if (material.HasProperty("_ZTest")) material.SetInt("_ZTest", (int)CompareFunction.Always);
                if (material.HasProperty("_ZWrite")) material.SetInt("_ZWrite", 0);
                materials[axis] = material;
                rings[axis] = Line("Native " + "XYZ"[axis] + " rotation ring", material, Segments + 1);
                for (int side = 0; side < 2; side++) arrows[axis * 2 + side] = Line("Rotation direction arrow", material, 3);
            }
        }
        LineRenderer Line(string name, Material material, int count)
        {
            var obj = new GameObject(name); obj.transform.SetParent(root.transform, false);
            var line = obj.AddComponent<LineRenderer>(); line.sharedMaterial = material; line.useWorldSpace = true;
            line.positionCount = count; line.numCapVertices = 4; line.numCornerVertices = 4;
            line.shadowCastingMode = ShadowCastingMode.Off; line.receiveShadows = false; return line;
        }
        public void Hide() { if (root != null) root.SetActive(false); }
        public void Dispose()
        {
            if (root != null) Release(root); foreach (var material in materials) if (material != null) Release(material);
            root = null;
        }
        static bool Finite(float value) => !float.IsNaN(value) && !float.IsInfinity(value);
        static bool Finite(Vector3 value) => Finite(value.x) && Finite(value.y) && Finite(value.z);
        static void Release(UnityEngine.Object obj) { if (Application.isPlaying) UnityEngine.Object.Destroy(obj); else UnityEngine.Object.DestroyImmediate(obj); }
    }
}

using UnityEngine;

namespace SpatialModeling
{
    // Adaptive low-pass filter in world space. Filter signed velocity first so
    // alternating hand tremor cannot masquerade as fast, deliberate movement.
    public sealed class GrabPoseSmoother
    {
        const float RestCutoffHz = 3f;
        const float VelocityCutoffHz = 1f;
        const float MaximumCutoffHz = 20f;
        Pose previousInput;
        Vector3 velocity, angularVelocity;
        bool initialized;
        public Pose Value { get; private set; }

        public void Reset(Pose displayedPose)
        {
            Value = previousInput = displayedPose;
            velocity = angularVelocity = Vector3.zero;
            initialized = true;
        }

        public Pose Step(Pose desiredPose, float deltaTime)
        {
            if (!initialized) { Reset(desiredPose); return Value; }
            if (!(deltaTime > 0f)) return Value;

            float velocityBlend = Blend(VelocityCutoffHz, deltaTime);
            velocity = Vector3.Lerp(velocity, (desiredPose.position - previousInput.position) / deltaTime, velocityBlend);
            var change = desiredPose.rotation * Quaternion.Inverse(previousInput.rotation);
            change.ToAngleAxis(out float angle, out var axis);
            if (angle > 180f) angle -= 360f;
            var angular = Mathf.Abs(angle) < 0.0001f ? Vector3.zero : axis * (angle / deltaTime);
            angularVelocity = Vector3.Lerp(angularVelocity, angular, velocityBlend);
            previousInput = desiredPose;

            float positionCutoff = Mathf.Min(MaximumCutoffHz, RestCutoffHz + 8f * velocity.magnitude);
            float rotationCutoff = Mathf.Min(MaximumCutoffHz, RestCutoffHz + 0.06f * angularVelocity.magnitude);
            Value = new Pose(Vector3.Lerp(Value.position, desiredPose.position, Blend(positionCutoff, deltaTime)),
                Quaternion.Slerp(Value.rotation, desiredPose.rotation, Blend(rotationCutoff, deltaTime)));
            return Value;
        }

        static float Blend(float cutoff, float deltaTime) => 1f - Mathf.Exp(-2f * Mathf.PI * cutoff * deltaTime);
    }
}

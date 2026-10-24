using UnityEngine;

namespace SpatialModeling
{
    // Inspection placement is local to this viewer. It never becomes a host command.
    public sealed class WorkspaceObjectView : MonoBehaviour
    {
        public string ObjectId { get; set; }
        public string NativeParentId { get; set; }
        public long Generation { get; set; }
        public Vector3 NativePosition { get; private set; }
        public Quaternion NativeRotation { get; private set; } = Quaternion.identity;
        public Vector3 PositionOffset { get; private set; }
        public Quaternion RotationOffset { get; private set; } = Quaternion.identity;

        public void SetNativePose(Vector3 position, Quaternion rotation, Vector3 scale)
        {
            NativePosition = position;
            NativeRotation = rotation;
            transform.localScale = scale;
            ApplyArrangement();
        }

        public void RememberArrangement()
        {
            PositionOffset = transform.localPosition - NativePosition;
            RotationOffset = transform.localRotation * Quaternion.Inverse(NativeRotation);
        }

        public void RestoreArrangement(Vector3 position, Quaternion rotation)
        {
            PositionOffset = position;
            RotationOffset = rotation;
            ApplyArrangement();
        }

        public void ResetArrangement() => RestoreArrangement(Vector3.zero, Quaternion.identity);

        void ApplyArrangement()
        {
            transform.localPosition = NativePosition + PositionOffset;
            transform.localRotation = RotationOffset * NativeRotation;
        }
    }
}

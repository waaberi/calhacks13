using UnityEngine;

namespace SpatialModeling
{
    // RawImage UVs are bottom-up; Windows pointer coordinates are top-down.
    // Map through the displayed crop, rather than the enclosing screen canvas.
    public static class PreviewInputMapping
    {
        static bool Finite(float x) => !float.IsNaN(x) && !float.IsInfinity(x);
        public static bool TryMap(Rect imageRect, Rect uvRect, Vector2 local, out Vector2 normalizedTopLeft)
        {
            normalizedTopLeft = default;
            if (!Finite(local.x) || !Finite(local.y) || !Finite(imageRect.x) || !Finite(imageRect.y)
                || !Finite(imageRect.width) || !Finite(imageRect.height) || imageRect.width <= 0 || imageRect.height <= 0
                || !Finite(uvRect.x) || !Finite(uvRect.y) || !Finite(uvRect.width) || !Finite(uvRect.height)
                || uvRect.width <= 0 || uvRect.height <= 0 || uvRect.x < 0 || uvRect.y < 0
                || uvRect.xMax > 1.00001f || uvRect.yMax > 1.00001f
                || local.x < imageRect.xMin || local.x > imageRect.xMax
                || local.y < imageRect.yMin || local.y > imageRect.yMax) return false;
            float x = (local.x - imageRect.xMin) / imageRect.width;
            float y = (local.y - imageRect.yMin) / imageRect.height;
            normalizedTopLeft = new Vector2(uvRect.x + x * uvRect.width, 1 - (uvRect.y + y * uvRect.height));
            return true;
        }

        public static bool CanRoute(bool enabled, bool fresh, bool primary, bool gripping, bool hit)
            => enabled && fresh && primary && !gripping && hit;

        public static bool FrameMatches(string displayedInstance, long displayedGeneration, string helperInstance, long helperGeneration)
            => !string.IsNullOrEmpty(displayedInstance) && displayedGeneration >= 0 && helperGeneration >= 0
                && displayedInstance == helperInstance && displayedGeneration == helperGeneration;
    }
}

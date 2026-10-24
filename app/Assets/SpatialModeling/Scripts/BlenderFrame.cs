using UnityEngine;

namespace SpatialModeling
{
    // Blender's frame (right-handed, Z up) to Unity's (left-handed, Y up): the one place that converts,
    // as contracts/README.md "Blender to Unity" specifies. The way back (commands) is the same swap.
    static class BlenderFrame
    {
        // Positions, normals, location and scale: wire [x, y, z].
        public static Vector3 Point(float x, float y, float z) => new Vector3(x, z, y);

        // Wire rotation [w, x, y, z]. The swap is a mirror, so the vector part changes sign.
        public static Quaternion Rotation(float w, float x, float y, float z) => new Quaternion(-x, -z, -y, w);

        // The mirror also reverses every triangle: a, b, c becomes a, c, b.
        public static void FlipTriangles(int[] t)
        {
            for (int i = 0; i + 2 < t.Length; i += 3) (t[i + 1], t[i + 2]) = (t[i + 2], t[i + 1]);
        }
    }
}

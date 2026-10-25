using System;
using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // This preference belongs only to the Blender view, never to the handheld menu
    // or the room compositor. A missing preference starts with solid readable UI.
    public sealed class BlenderViewAppearance : MonoBehaviour
    {
        public const string PreferenceKey = "SpatialModeling.BlenderView.Opaque";
        public const float TransparentPreviewAlpha = .86f;
        public static bool Opaque => PlayerPrefs.GetInt(PreferenceKey, 1) == 1;
        public static event Action Changed;

        public static void SetOpaque(bool opaque)
        {
            PlayerPrefs.SetInt(PreferenceKey, opaque ? 1 : 0);
            PlayerPrefs.Save();
            Changed?.Invoke();
        }

        public static void ToggleOpaque() => SetOpaque(!Opaque);
        void OnEnable() { Changed += Apply; Apply(); }
        void OnDisable() { Changed -= Apply; }

        public void Apply()
        {
            foreach (var graphic in GetComponentsInChildren<Graphic>(true))
            {
                // Captured pixels use Unity's native UI shader, not the glass
                // material. Keep the image solid in opaque mode too.
                if (graphic is RawImage)
                {
                    var tint = graphic.color;
                    tint.a = Opaque ? 1f : TransparentPreviewAlpha;
                    graphic.color = tint;
                }
                graphic.SetVerticesDirty();
            }
        }
    }
}

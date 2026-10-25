using System;
using System.Reflection;
using SpatialModeling;
using UnityEngine;
using UnityEngine.UI;

// Exercise the actual production screen factory, dynamically added preview UI,
// shader metadata and captured-pixel alpha; keep user preferences unchanged.
public static class BlenderViewAppearanceChecks
{
    const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static void Check(bool value, string reason) { if (!value) throw new Exception("BLENDER_APPEARANCE: " + reason); }
    static UIVertex Vertex(RoundedGlassImage image)
    {
        using (var mesh = new VertexHelper())
        {
            typeof(RoundedGlassImage).GetMethod("OnPopulateMesh", Private, null, new[]{typeof(VertexHelper)}, null).Invoke(image, new object[] { mesh });
            var vertex = new UIVertex(); mesh.PopulateUIVertex(ref vertex, 0); return vertex;
        }
    }
    public static void Run()
    {
        bool had = PlayerPrefs.HasKey(BlenderViewAppearance.PreferenceKey);
        int saved = PlayerPrefs.GetInt(BlenderViewAppearance.PreferenceKey);
        var owner = new GameObject("Inactive Blender appearance factory"); owner.SetActive(false);
        var camera = new GameObject("Appearance check camera", typeof(Camera));
        var menu = new GameObject("Unrelated handheld fixture", typeof(RectTransform), typeof(Canvas));
        GameObject canvas = null;
        try
        {
            PlayerPrefs.DeleteKey(BlenderViewAppearance.PreferenceKey);
            Check(BlenderViewAppearance.Opaque, "new preference defaults opaque");
            var screen = owner.AddComponent<BlenderScreen>();
            typeof(BlenderScreen).GetMethod("BuildUi", Private).Invoke(screen, new object[] { camera.GetComponent<Camera>() });
            canvas = screen.Placement.gameObject;
            var scope = canvas.GetComponent<BlenderViewAppearance>();
            Check(scope != null && menu.GetComponent<BlenderViewAppearance>() == null, "only Blender owns scope");
            // Edit-time checks must drive the ordinary Player lifecycle explicitly.
            typeof(BlenderViewAppearance).GetMethod("OnDisable", Private).Invoke(scope, null);
            typeof(BlenderViewAppearance).GetMethod("OnEnable", Private).Invoke(scope, null);
            var preview = canvas.GetComponentInChildren<RawImage>(true);
            Check(preview.color.a == 1, "live captured pixels start fully opaque");
            // PreviewInteraction builds its UI later, under this same root.
            var late = GlassTheme.Action(canvas.transform, "Late preview input action", Vector2.zero, new Vector2(240, 80), null);
            var control = late.GetComponent<RoundedGlassImage>();
            var untouched = GlassTheme.Panel(menu.transform, "Handheld glass", Vector2.zero, new Vector2(240, 80)).GetComponent<RoundedGlassImage>();
            var before = Vertex(untouched);
            var opaque = Vertex(control);
            Check(opaque.color.a == 255 && opaque.uv1.w == -1, "late preview button forces solid shader path");
            BlenderViewAppearance.SetOpaque(false);
            Check(Mathf.Abs(preview.color.a - BlenderViewAppearance.TransparentPreviewAlpha) < .0001f, "toggle applies to captured pixels immediately");
            var transparent = Vertex(control);
            if (!GlassTheme.HighContrast && !GlassTheme.ReducedTransparency)
                Check(transparent.uv1.w != -1 && transparent.color.a < 255, "toggle restores glass control shader path");
            var after = Vertex(untouched);
            Check(before.color.Equals(after.color) && before.uv1 == after.uv1, "handheld appearance remains identical");
            BlenderViewAppearance.ToggleOpaque();
            late.GetComponent<GlassControl>().Selected = true; late.GetComponent<GlassControl>().Refresh();
            Check(preview.color.a == 1 && Vertex(control).uv1.w == -1, "toggle survives selected/hover control refresh");
            Check(PlayerPrefs.GetInt(BlenderViewAppearance.PreferenceKey) == 1, "choice saved for next session");
            Debug.Log("BLENDER_VIEW_APPEARANCE_CHECK PASS opaque_default captured_pixels late_preview_buttons solid_shader_path saved_toggle handheld_unchanged no_passthrough_change");
        }
        finally
        {
            if (canvas != null)
                typeof(BlenderViewAppearance).GetMethod("OnDisable", Private).Invoke(canvas.GetComponent<BlenderViewAppearance>(), null);
            if (had) PlayerPrefs.SetInt(BlenderViewAppearance.PreferenceKey, saved);
            else PlayerPrefs.DeleteKey(BlenderViewAppearance.PreferenceKey);
            PlayerPrefs.Save();
            if (canvas != null) UnityEngine.Object.DestroyImmediate(canvas);
            UnityEngine.Object.DestroyImmediate(owner); UnityEngine.Object.DestroyImmediate(camera); UnityEngine.Object.DestroyImmediate(menu);
        }
    }
}

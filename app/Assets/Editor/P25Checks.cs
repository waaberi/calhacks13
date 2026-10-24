using System;
using SpatialModeling;
using UnityEngine;

// Edit-time deterministic checks only. No input injection, network or runtime launch.
public static class P25Checks
{
    static void Check(bool value, string why)
    {
        if (!value) throw new Exception("P2.5: " + why);
    }

    static void Mapped(Rect image, Rect uv, Vector2 point, Vector2 expected, string why)
    {
        Check(PreviewInputMapping.TryMap(image, uv, point, out var actual), why + " maps");
        Check(Vector2.Distance(actual, expected) < .00001f, why + " has expected native coordinates");
    }

    public static void Run()
    {
        RunMapping(message => Debug.Log(message));
        RunSpatial(message => Debug.Log(message));
    }

    // The same actual mapping gate can run under the bundled managed runtime,
    // without Unity native initialization, by supplying Console.WriteLine.
    public static void RunMapping(Action<string> report)
    {
        var image = new Rect(-900, -550, 1800, 1100);
        var full = new Rect(0, 0, 1, 1);
        Mapped(image, full, Vector2.zero, new Vector2(.5f, .5f), "full window centre");
        Mapped(image, full, new Vector2(-900, -550), new Vector2(0, 1), "bottom-left image corner");
        Mapped(image, full, new Vector2(900, 550), new Vector2(1, 0), "top-right image corner");
        var crop = new Rect(.25f, .2f, .5f, .5f);
        Mapped(image, crop, Vector2.zero, new Vector2(.5f, .55f), "panned magnified centre");
        Mapped(image, crop, new Vector2(-900, -550), new Vector2(.25f, .8f), "magnified bottom-left");
        Mapped(image, crop, new Vector2(900, 550), new Vector2(.75f, .3f), "magnified top-right");
        // Non-centred image rect prevents an implicit assumption that the pivot is always .5.
        Mapped(new Rect(100, 200, 800, 400), full, new Vector2(300, 500), new Vector2(.25f, .25f), "offset image pivot");
        foreach (var point in new[] { new Vector2(-901, 0), new Vector2(901, 0),
            new Vector2(0, -551), new Vector2(0, 551), new Vector2(float.NaN, 0),
            new Vector2(float.PositiveInfinity, 0) })
            Check(!PreviewInputMapping.TryMap(image, full, point, out _), "outside/nonfinite point cannot click native UI");
        Check(!PreviewInputMapping.TryMap(new Rect(0, 0, 0, 10), full, Vector2.zero, out _), "zero-width image refuses input");
        Check(!PreviewInputMapping.TryMap(image, new Rect(0, 0, 0, 1), Vector2.zero, out _), "zero-width crop refuses input");
        Check(!PreviewInputMapping.TryMap(image, new Rect(-.1f, 0, 1, 1), Vector2.zero, out _), "crop outside source refuses input");
        Check(!PreviewInputMapping.TryMap(image, new Rect(0, 0, float.NaN, 1), Vector2.zero, out _), "nonfinite crop refuses input");
        // Exhaust all input-routing combinations. Only the explicitly active, fresh,
        // right/primary hand over the image without a grip can issue native pointer input.
        for (int bits = 0; bits < 32; bits++)
        {
            bool enabled = (bits & 1) != 0, fresh = (bits & 2) != 0,
                primary = (bits & 4) != 0, gripping = (bits & 8) != 0, hit = (bits & 16) != 0;
            bool expected = bits == 23; // enabled + fresh + primary + image hit; no grip.
            Check(PreviewInputMapping.CanRoute(enabled, fresh, primary, gripping, hit) == expected,
                "native routing requires current image and one hand, and excludes panel grabbing");
        }
        report("P25_MAPPING_CHECK PASS full-window/UV-crop/pan/pivot/finite/edge/stale/grip/hand routing; native runtime acceptance=False");
    }

    public static void RunSpatial(Action<string> report)
    {
        Check(PreviewSketchMapping.TryMapRay(new Ray(new Vector3(.1f, 1, .06f), Vector3.down),
            Matrix4x4.identity, Vector3.zero, Quaternion.identity, out var native, out var hit),
            "native XY plane can receive a world-space controller ray");
        Check(Vector2.Distance(native, new Vector2(.1f, .06f)) < .00001f
            && Vector3.Distance(hit, new Vector3(.1f, 0, .06f)) < .00001f,
            "Z-up metres convert once to Unity Y-up without changing 100x60mm dimensions");
        // Independently calculated: 90 degrees around world Y, scale 5/7/3 and
        // translation (2,.8,-1). The source plane origin is native (.03,-.02,.04).
        var display = new Matrix4x4(new Vector4(0, 0, -5, 0), new Vector4(0, 7, 0, 0),
            new Vector4(3, 0, 0, 0), new Vector4(2, .8f, -1, 1));
        var origin = new Vector3(.03f, -.02f, .04f);
        var expectedWorld = new Vector3(2.12f, 1.08f, -1.65f);
        Check(PreviewSketchMapping.TryMapRay(new Ray(expectedWorld + Vector3.up * 2, Vector3.down),
            display, origin, Quaternion.identity, out native, out hit), "rotated and magnified display accepts ray");
        Check(Vector2.Distance(native, new Vector2(.1f, .06f)) < .00001f
            && Vector3.Distance(hit, expectedWorld) < .00001f,
            "table translation, rotation and nonuniform magnification never become native sketch units");
        Check(Vector3.Distance(PreviewSketchMapping.WorldPoint(new Vector2(.1f, .06f), display,
            origin, Quaternion.identity), expectedWorld) < .00001f, "native result is displayed at independently expected world point");
        float half = .70710678118f;
        var x90 = new Quaternion(half, 0, 0, half);
        Check(PreviewSketchMapping.TryMapRay(new Ray(new Vector3(.1f, .06f, 1), Vector3.back),
            Matrix4x4.identity, Vector3.zero, x90, out native, out _)
            && Vector2.Distance(native, new Vector2(.1f, .06f)) < .00001f,
            "rotated native workplane uses its actual basis, rather than always projecting onto a horizontal table");
        Check(!PreviewSketchMapping.TryMapRay(new Ray(Vector3.up, Vector3.right), Matrix4x4.identity,
            Vector3.zero, Quaternion.identity, out _, out _), "parallel aim cannot author a point");
        Check(!PreviewSketchMapping.TryMapRay(new Ray(Vector3.up, Vector3.up), Matrix4x4.identity,
            Vector3.zero, Quaternion.identity, out _, out _), "plane behind the controller cannot author a point");
        Check(!PreviewSketchMapping.TryMapRay(new Ray(Vector3.up, Vector3.down), Matrix4x4.zero,
            Vector3.zero, Quaternion.identity, out _, out _), "singular display never invents native geometry");
        Check(!PreviewSketchMapping.TryMapRay(new Ray(new Vector3(float.NaN, 1, 0), Vector3.down),
            Matrix4x4.identity, Vector3.zero, Quaternion.identity, out _, out _), "invalid tracking point cannot author geometry");
        Check(!PreviewSketchMapping.TryMapRay(new Ray(Vector3.up, Vector3.down), Matrix4x4.identity,
            Vector3.zero, new Quaternion(0, 0, 0, 0), out _, out _), "invalid native workplane orientation refuses drawing");
        report("P25_SPATIAL_MAPPING_CHECK PASS native-axis/metres/known-world-point/display-scale/native-rotated-plane/parallel/behind/singular/nonfinite; physical drawing acceptance=False");
    }
}

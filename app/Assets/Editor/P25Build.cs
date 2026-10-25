using System;
using System.IO;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.XR.OpenXR;
using UnityEngine.XR.OpenXR.Features;

// Explicit separate build entry. Never launches a Player, Blender or capture helper.
public static class P25Build
{
    public static void Windows()
    {
        var output = Environment.GetEnvironmentVariable("CALHACKS_P25_BUILD_PATH");
        if (string.IsNullOrWhiteSpace(output) || !Path.IsPathRooted(output)
            || !string.Equals(Path.GetExtension(output), ".exe", StringComparison.OrdinalIgnoreCase))
            throw new Exception("Set CALHACKS_P25_BUILD_PATH to an absolute external .exe path.");
        output = Path.GetFullPath(output);
        var parent = new DirectoryInfo(Path.GetDirectoryName(output));
        for (var directory = parent; directory != null; directory = directory.Parent)
            if (File.Exists(Path.Combine(directory.FullName, ".git"))
                || Directory.Exists(Path.Combine(directory.FullName, ".git"))
                || directory.Name.StartsWith("OneDrive", StringComparison.OrdinalIgnoreCase))
                throw new Exception("P2.5 build output must be outside Git worktrees and OneDrive.");
        Directory.CreateDirectory(parent.FullName);
        var xrBaseline = PreserveFrozenP2XrFeatures();
        P25Checks.Run();
        var previous = Environment.GetEnvironmentVariable("CALHACKS_P2_BUILD_PATH");
        var previousP1 = Environment.GetEnvironmentVariable("CALHACKS_P1_BUILD_PATH");
        try
        {
            Environment.SetEnvironmentVariable("CALHACKS_P2_BUILD_PATH", output);
            // Real P2 placement/arrangement, P1 aim/controller/freshness, and visual gates.
            P2Checks.Windows();
            VerifyFrozenP2XrFeatures(xrBaseline);
        }
        finally
        {
            Environment.SetEnvironmentVariable("CALHACKS_P2_BUILD_PATH", previous);
            Environment.SetEnvironmentVariable("CALHACKS_P1_BUILD_PATH", previousP1);
        }
        // Mandatory final gate. Its synthetic Input System player updates must
        // not initialize buffers before the existing controller-pose gates.
        // An artifact without this success and the final P25 marker is rejected.
        P25Checks.RunKeyboardIsolation();
        Debug.Log("P25_BUILD_RESULT Succeeded errors=0 cumulative_P1_P2=True runtime_acceptance=False");
    }

    static Dictionary<string, bool> PreserveFrozenP2XrFeatures()
    {
        string path = Environment.GetEnvironmentVariable("CALHACKS_P225_XR_BASELINE");
        if (string.IsNullOrEmpty(path)) return null;
        if (!Path.IsPathRooted(path) || !File.Exists(path))
            throw new Exception("P225: frozen P2 XR baseline must be an existing absolute JSON file");
        var expected = JObject.Parse(File.ReadAllText(path)).ToObject<Dictionary<string, bool>>();
        var settings = OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Standalone);
        var features = settings.GetFeatures<OpenXRFeature>();
        if (expected == null || expected.Count != features.Length)
            throw new Exception("P225: imported XR feature inventory differs from frozen P2");
        int restored = 0;
        foreach (var feature in features)
        {
            if (!expected.TryGetValue(feature.name, out bool enabled))
                throw new Exception("P225: unexpected XR feature " + feature.name);
            if (feature.enabled != enabled) { feature.enabled = enabled; restored++; EditorUtility.SetDirty(feature); }
        }
        AssetDatabase.SaveAssets();
        VerifyFrozenP2XrFeatures(expected);
        Debug.Log("P225_XR_BASELINE_RESTORED PASS frozen_features=" + expected.Count + " sdk_generated_flags_restored=" + restored);
        return expected;
    }

    static void VerifyFrozenP2XrFeatures(Dictionary<string, bool> expected)
    {
        if (expected == null) return;
        var features = OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Standalone).GetFeatures<OpenXRFeature>();
        if (features.Length != expected.Count) throw new Exception("P225: XR inventory changed during build");
        foreach (var feature in features)
            if (!expected.TryGetValue(feature.name, out bool enabled) || feature.enabled != enabled)
                throw new Exception("P225: frozen P2 XR feature regressed: " + feature.name);
        Debug.Log("P225_XR_BASELINE_CHECK PASS exact_accepted_P2_standalone_flags=" + expected.Count);
    }
}

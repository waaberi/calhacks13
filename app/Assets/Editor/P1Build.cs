using System;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.XR.OpenXR;
using UnityEngine.Rendering.Universal;
using Meta.XR;

public static class P1Build
{
    public static void Windows()
    {
        var output = Environment.GetEnvironmentVariable("CALHACKS_P1_BUILD_PATH");
        if (string.IsNullOrEmpty(output)) throw new Exception("Set CALHACKS_P1_BUILD_PATH to an output EXE outside the repository.");
        WorkspaceChecks.Run();
        ControllerPoseChecks.Run();
        RoomSetupChecks.Run();
        // Protect accepted clarity and room visibility while changing interaction.
        // Deliberate future baseline changes must update this gate and physical evidence.
        var pipeline = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>("Assets/Settings/PC_RPAsset.asset");
        if (pipeline == null || !Mathf.Approximately(pipeline.renderScale, 1f) || pipeline.msaaSampleCount != 4
            || !pipeline.allowPostProcessAlphaOutput || !PlayerSettings.preserveFramebufferAlpha)
            throw new Exception("P1 visual baseline regressed: require render scale1,MSAA4,alpha output/framebuffer preservation.");
        Debug.Log("P1_VISUAL_BASELINE PASS render_scale=1 msaa=4 alpha_output=True preserve_alpha=True");
        var xr = OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Standalone);
        var meta = xr.GetFeature<MetaXRFeature>();
        if (meta == null) throw new Exception("Meta XR OpenXR feature was not imported.");
        meta.enabled = true;
        EditorUtility.SetDirty(xr);
        // Meta's optional developer agent is not part of the product. Its generated
        // settings can contain a machine address/token even when disabled.
        var agent = AssetDatabase.LoadMainAssetAtPath("Assets/Resources/DevAgentSettings.asset");
        if (agent != null)
        {
            var settings = new SerializedObject(agent);
            settings.FindProperty("enabled").boolValue = false;
            settings.FindProperty("serverAddress").stringValue = "127.0.0.1";
            settings.FindProperty("accessToken").stringValue = "";
            settings.ApplyModifiedPropertiesWithoutUndo();
        }
        AssetDatabase.SaveAssets();
        var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions {
            scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray(),
            locationPathName = output, target = BuildTarget.StandaloneWindows64,
            options = Environment.GetEnvironmentVariable("CALHACKS_P1_DEVELOPMENT") == "1"
                ? BuildOptions.Development : BuildOptions.None
        });
        Debug.Log("P1_BUILD_RESULT " + report.summary.result + " errors=" + report.summary.totalErrors);
        if (report.summary.result != BuildResult.Succeeded || report.summary.totalErrors != 0)
            throw new Exception("P1 Windows build failed or reported build errors");
    }
}

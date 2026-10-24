using System;
using System.Linq;
using Meta.XR;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.Build;
using UnityEditor.SceneManagement;
using UnityEditor.XR.Management;
using UnityEditor.XR.Management.Metadata;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.XR.Management;
using UnityEngine.XR.OpenXR;

public static class QuestRoomSetupBuild
{
    // Invoke only in a serialized Android build pass. The wrapper backs up/restores
    // project settings so this separate companion cannot change the PC render baseline.
    public static void Android()
    {
        string output=Environment.GetEnvironmentVariable("CALHACKS_ROOM_SETUP_APK");
        if(string.IsNullOrEmpty(output)) throw new Exception("Set CALHACKS_ROOM_SETUP_APK outside the repository");
        RoomSetupChecks.Run();
        var perTarget=XRGeneralSettingsPerBuildTarget.XRGeneralSettingsForBuildTarget(BuildTargetGroup.Android);
        if(perTarget==null)
        {
            var container=AssetDatabase.LoadAssetAtPath<XRGeneralSettingsPerBuildTarget>("Assets/XR/XRGeneralSettingsPerBuildTarget.asset");
            perTarget=ScriptableObject.CreateInstance<XRGeneralSettings>();
            perTarget.Manager=ScriptableObject.CreateInstance<XRManagerSettings>();
            AssetDatabase.AddObjectToAsset(perTarget,container);AssetDatabase.AddObjectToAsset(perTarget.Manager,container);
            container.SetSettingsForBuildTarget(BuildTargetGroup.Android,perTarget);
        }
        perTarget.InitManagerOnStart=true;
        if(!XRPackageMetadataStore.AssignLoader(perTarget.Manager,"UnityEngine.XR.OpenXR.OpenXRLoader",BuildTargetGroup.Android))
            throw new Exception("Could not configure Android OpenXR loader");
        var openxr=OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Android);
        var meta=openxr.GetFeature<MetaXRFeature>();
        if(meta==null) throw new Exception("Android Meta OpenXR feature missing");
        meta.enabled=true;
        foreach(var feature in openxr.GetFeatures())
            if(feature!=null && feature.GetType().Name.Contains("Touch")) feature.enabled=true;
        PlayerSettings.SetApplicationIdentifier(NamedBuildTarget.Android,"com.calhacks13.roomsetup");
        PlayerSettings.productName="Room Setup";
        PlayerSettings.SetScriptingBackend(NamedBuildTarget.Android,ScriptingImplementation.IL2CPP);
        PlayerSettings.Android.targetArchitectures=AndroidArchitecture.ARM64;
        PlayerSettings.Android.minSdkVersion=AndroidSdkVersions.AndroidApiLevel29;
        PlayerSettings.Android.targetSdkVersion=(AndroidSdkVersions)36;
        PlayerSettings.SetGraphicsAPIs(BuildTarget.Android,new[]{GraphicsDeviceType.Vulkan});
        PlayerSettings.defaultInterfaceOrientation=UIOrientation.LandscapeLeft;
        PlayerSettings.preserveFramebufferAlpha=true;
        var config=OVRProjectConfig.CachedProjectConfig;
        config.sceneSupport=OVRProjectConfig.FeatureSupport.Required;
        config.anchorSupport=OVRProjectConfig.AnchorSupport.Enabled;
        config.insightPassthroughSupport=OVRProjectConfig.FeatureSupport.Required;
        OVRProjectConfig.CommitProjectConfig(config);
        var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
        string path="Assets/Scenes/QuestRoomSetup.unity";
        EditorSceneManager.SaveScene(scene,path);AssetDatabase.SaveAssets();
        var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions {scenes=new[]{path},locationPathName=output,
            target=BuildTarget.Android,options=BuildOptions.None});
        Debug.Log("QUEST_ROOM_SETUP_BUILD "+report.summary.result+" errors="+report.summary.totalErrors);
        if(report.summary.result!=BuildResult.Succeeded || report.summary.totalErrors!=0)
            throw new Exception("Quest room setup APK build failed or reported build errors");
    }
}

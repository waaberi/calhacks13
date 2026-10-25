using UnityEngine;
public static class GlassBuild
{
    public static void Windows()
    {
        GlassChecks.Run();
        GlassStabilityChecks.Run();
        GlassControllerChecks.Run();
        GlassEventRaycastChecks.Run();
        HandheldMenuChecks.Run();
        BlenderViewAppearanceChecks.Run();
        LiveModelEditSessionChecks.Run();
        P25Build.Windows();
        CombinedGlassChecks.Run();
        VoiceCompositionChecks.Run();
        VoiceDialogChecks.Run();
        DirectModelEditingChecks.Run();
        DirectToolAvailabilityChecks.Run();
        Debug.Log("DIRECT_EDIT_VOICE_INTEGRATION_BUILD PASS native_tool_controller_bridge complete_voice_composition cumulative_combined=True candidate_launched=False physical_acceptance=False");
        Debug.Log("P3_GLASS_BUILD_RESULT Succeeded cumulative_P1_P2_P25=True physical_acceptance=False");
    }
}

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
        KeyboardPassthroughChecks.Run();
        P25Build.Windows();
        CombinedGlassChecks.Run();
        Debug.Log("P3_GLASS_BUILD_RESULT Succeeded cumulative_P1_P2_P25=True physical_acceptance=False");
    }
}

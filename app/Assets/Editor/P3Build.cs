using System;
using System.IO;
using UnityEngine;

public static class P3Build
{
    public static void Windows()
    {
        var output = Environment.GetEnvironmentVariable("CALHACKS_P3_BUILD_PATH");
        if (string.IsNullOrEmpty(output) || !Path.IsPathRooted(output)) throw new Exception("Set CALHACKS_P3_BUILD_PATH to an absolute output EXE outside the repository");
        var repo = Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
        var full = Path.GetFullPath(output);
        if (full.StartsWith(repo + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new Exception("P3 build output must remain outside the repository");
        P2Checks.Run();
        NativeEditingChecks.Run();
        NativeHandChecks.Run();
        Debug.Log("P3_NATIVE_MENU_CHECKS PASS receipt correlation, stale drafts, cancellation, late permissions, owner conflict and scene admission");
        Environment.SetEnvironmentVariable("CALHACKS_P1_BUILD_PATH", full);
        P1Build.Windows(); // Real Unity ray/controller/startup/freshness checks and accepted graphics baseline.
        Debug.Log("P3_BUILD_RESULT PASS cumulative P2/native/P1 checks and Windows build");
    }
}

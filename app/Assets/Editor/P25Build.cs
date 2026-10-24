using System;
using System.IO;
using UnityEngine;

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
        P25Checks.Run();
        var previous = Environment.GetEnvironmentVariable("CALHACKS_P2_BUILD_PATH");
        var previousP1 = Environment.GetEnvironmentVariable("CALHACKS_P1_BUILD_PATH");
        try
        {
            Environment.SetEnvironmentVariable("CALHACKS_P2_BUILD_PATH", output);
            // Real P2 placement/arrangement, P1 aim/controller/freshness, and visual gates.
            P2Checks.Windows();
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
}

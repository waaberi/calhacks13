using System;
using System.Reflection;
using SpatialModeling;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.XR;

public static class NativeHandChecks
{
    const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static void Check(bool ok, string text) { if (!ok) throw new Exception("P3 handedness: " + text); }
    public static void Run()
    {
        bool original = WorkspaceHandPreference.Left;
        var go = new GameObject("P3 inactive hand-binding checks"); go.SetActive(false);
        InputAction toggle = null, magnify = null, pan = null;
        try
        {
            var screen = go.AddComponent<BlenderScreen>();
            var scene = go.AddComponent<HostScene>();
            toggle = Action("toggle", "/primaryButton", "<Keyboard>/f2");
            magnify = Action("magnify", "/thumbstickClicked", "<Keyboard>/z");
            pan = Action("pan", "/thumbstick", "<Keyboard>/upArrow");
            typeof(BlenderScreen).GetField("toggle", Private).SetValue(screen, toggle);
            typeof(BlenderScreen).GetField("magnify", Private).SetValue(screen, magnify);
            typeof(BlenderScreen).GetField("panAction", Private).SetValue(screen, pan);
            foreach (bool left in new[] { false, true, false })
            {
                WorkspaceHandPreference.SetLeft(left);
                typeof(BlenderScreen).GetMethod("RebindHandShortcuts", Private).Invoke(screen, null);
                typeof(HostScene).GetMethod("ConfigureRecenter", Private).Invoke(scene, null);
                string primary = left ? "LeftHand" : "RightHand";
                Check(WorkspaceHandPreference.Primary == (left ? XRNode.LeftHand : XRNode.RightHand), "preferred pointer hand did not change");
                Check(WorkspaceHandPreference.MenuHand == (left ? XRNode.RightHand : XRNode.LeftHand), "held menu must move to the other hand");
                Check(PlayerPrefs.GetString("SpatialModeling.PrimaryHand") == (left ? "Left" : "Right"), "hand preference was not persisted");
                foreach (var action in new[] { toggle, magnify, pan })
                {
                    Check(action.enabled, "hot rebind disabled an existing action");
                    Check(action.bindings[0].effectivePath.Contains(primary), "screen/magnify/pan retained the old controller binding");
                    Check(action.bindings[1].effectivePath.StartsWith("<Keyboard>"), "hand setting changed a keyboard shortcut");
                }
                var recenter = (InputAction)typeof(HostScene).GetField("recenterAction", Private).GetValue(scene);
                Check(recenter.bindings[0].effectivePath.Contains(primary) && recenter.bindings.Count == 2, "recenter did not move consistently with the preferred hand");
                Check(recenter.bindings[1].effectivePath == "<Keyboard>/r", "recenter lost keyboard fallback");
                recenter.Dispose(); typeof(HostScene).GetField("recenterAction", Private).SetValue(scene, null);
            }
        }
        finally
        {
            WorkspaceHandPreference.SetLeft(original);
            toggle?.Dispose(); magnify?.Dispose(); pan?.Dispose();
            UnityEngine.Object.DestroyImmediate(go);
        }
        Debug.Log("P3_HAND_BINDING_CHECK PASS persisted hand, preferred pointer, held menu, screen/magnify/pan/recenter shortcuts and keyboard preservation");
    }
    static InputAction Action(string name, string path, string keyboard)
    { var a = new InputAction(name); a.AddBinding("<XRController>{RightHand}" + path); a.AddBinding(keyboard); a.Enable(); return a; }
}

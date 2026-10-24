using System.Reflection;
using UnityEngine;

namespace SpatialModeling
{
    // An explicit bounded test pose reaches the real table action without a headset.
    // This is software integration evidence, never physical placement acceptance.
    public static class NativeSmokeWorkspace
    {
        public static bool Place(HostScene scene)
        {
            if (scene == null || scene.Table == null) return false;
            scene.Table.SeedFromHead(new Vector3(0, 1.65f, 0), Vector3.forward);
            var controls = Object.FindObjectsByType<TableAction>(FindObjectsInactive.Include, FindObjectsSortMode.None);
            bool found = false;
            foreach (var control in controls) if (control.name == "Place Table") found = true;
            // Inactive XR can prevent Table.Update from creating controls. Create the same
            // production panel, then invoke its registered Place Table callback.
            if (!found) typeof(TablePlacement).GetMethod("CreatePanel", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(scene.Table, null);
            foreach (var control in Object.FindObjectsByType<TableAction>(FindObjectsInactive.Include, FindObjectsSortMode.None))
                if (control.name == "Place Table") { control.Invoke(); return scene.Table.IsPlaced && scene.Placement.gameObject.activeInHierarchy; }
            return false;
        }

        public static int ActiveModelRenderers(HostScene scene)
        {
            int count = 0;
            foreach (var view in scene.ObjectViews)
                if (view != null && view.gameObject.activeInHierarchy && view.TryGetComponent<MeshRenderer>(out var renderer) && renderer.enabled && view.GetComponent<MeshFilter>().sharedMesh != null) count++;
            return count;
        }
    }
}

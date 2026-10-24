using System;
using System.Reflection;
using SpatialModeling;
using UnityEditor;
using UnityEngine;

public static class NativePanelChecks
{
    const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static void Check(bool ok, string text) { if (!ok) throw new Exception("P3 control panels: " + text); }
    public static void Run()
    {
        var go = new GameObject("P3 inactive panel checks"); go.SetActive(false);
        try
        {
            var scene = go.AddComponent<HostScene>();
            typeof(HostScene).GetField("objectMaterial", Private).SetValue(scene,
                AssetDatabase.LoadAssetAtPath<Material>("Assets/SpatialModeling/Materials/HostObject.mat"));
            typeof(HostScene).GetMethod("Awake", Private).Invoke(scene, null);
            var table = scene.Table;
            var bridge = go.AddComponent<NativeEditBridge>();
            var menu = go.AddComponent<WorkspaceNativeMenu>();
            typeof(WorkspaceNativeMenu).GetField("bridge", Private).SetValue(menu, bridge);
            typeof(WorkspaceNativeMenu).GetField("workspace", Private).SetValue(menu, scene);
            var nativePanel = new GameObject("native test panel", typeof(RectTransform)).GetComponent<RectTransform>();
            nativePanel.SetParent(go.transform, false);
            typeof(WorkspaceNativeMenu).GetField("panel", Private).SetValue(menu, nativePanel);
            var present = typeof(WorkspaceNativeMenu).GetMethod("UpdatePresentation", Private);
            var show = typeof(WorkspaceNativeMenu).GetMethod("SetVisible", Private);
            table.SeedFromHead(new Vector3(0, 1.65f, 0), Vector3.forward);
            typeof(TablePlacement).GetMethod("CreatePanel", Private).Invoke(table, null);
            var panel = (Transform)typeof(TablePlacement).GetField("panel", Private).GetValue(table);
            Check(panel.GetComponent<UnityEngine.UI.Image>() != null && panel.GetComponent<UnityEngine.UI.Image>().color.a >= 0.99f
                && panel.GetComponent<Canvas>().sortingOrder > 0, "table controls need opaque backing and ordering above the live screen");
            table.SetControlsSuppressed(true);
            Check(panel.gameObject.activeSelf && !table.IsPlaced, "native menu must never hide initial Place Table");
            Check(!(bool)present.Invoke(menu, null) && !nativePanel.gameObject.activeSelf && panel.gameObject.activeSelf, "actual native menu must wait for initial placement");
            table.Place();
            var pose = new Pose(scene.Placement.position, scene.Placement.rotation);
            var size = scene.Placement.localScale;
            Check((bool)present.Invoke(menu, null) && nativePanel.gameObject.activeSelf && !panel.gameObject.activeSelf && scene.Placement.gameObject.activeSelf, "placed table controls must yield to actual native menu while model remains visible");
            var action = panel.GetComponentsInChildren<TableAction>(true)[0];
            Check(!table.RaycastControls(new Ray(action.transform.position - action.transform.forward, action.transform.forward), out _), "hidden table controls must not intercept controller rays");
            table.BeginMove();
            Check(!(bool)present.Invoke(menu, null) && !nativePanel.gameObject.activeSelf && panel.gameObject.activeSelf, "Move/Cancel/confirmation must preempt the native menu");
            table.CancelMove();
            Check((bool)present.Invoke(menu, null) && !panel.gameObject.activeSelf, "returning to native menu must not overlap table controls");
            show.Invoke(menu, new object[] { false });
            Check(panel.gameObject.activeSelf && !nativePanel.gameObject.activeSelf, "Arrange view / hidden native menu must restore table controls");
            show.Invoke(menu, new object[] { true });
            Check(menu.Visible && menu.SelectingNative && nativePanel.gameObject.activeSelf && !panel.gameObject.activeSelf, "one menu toggle must restore native Select/Edit and exclusive panel visibility");
            table.ConfirmTrackingReset();
            Check(!(bool)present.Invoke(menu, null) && table.NeedsSeed && !table.IsPlaced, "tracking reset must wait for a fresh pose without showing native controls");
            table.SeedFromHead(new Vector3(0, 1.65f, 0), Vector3.forward);
            Check(!(bool)present.Invoke(menu, null) && panel.gameObject.activeSelf && table.State == TablePlacement.PlacementState.ConfirmTrackingReset, "fresh pose must reveal confirmation controls without auto-placing");
            table.Place();
            Check((bool)present.Invoke(menu, null) && nativePanel.gameObject.activeSelf && !panel.gameObject.activeSelf, "explicit Place after tracking reset must restore native menu alone");
            Check(Vector3.Distance(scene.Placement.position, pose.position) < 1e-6f
                && Quaternion.Angle(scene.Placement.rotation, pose.rotation) < 1e-4f
                && Vector3.Distance(scene.Placement.localScale, size) < 1e-6f, "panel visibility must never change table placement or scale");
        }
        finally { UnityEngine.Object.DestroyImmediate(go); }
        Debug.Log("P3_PANEL_VISIBILITY_CHECK PASS initial Place preserved; native/table panels exclusive; move/cancel accessible; placement unchanged");
    }
}

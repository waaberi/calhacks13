using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using SpatialModeling;
using UnityEditor;
using UnityEngine;
using UnityEngine.UI;

// Actual compact-menu collider/callback checks. No Player, host, socket or XR startup.
public static class SettingsMenuChecks
{
    const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static void Check(bool value, string why) { if (!value) throw new Exception("Settings menu: " + why); }
    static void Invoke(object target, string method)
        => target.GetType().GetMethod(method, Private).Invoke(target, null);
    static void Near(Vector3 actual, Vector3 expected, string why)
        => Check(Vector3.Distance(actual, expected) < .0001f, why);
    static TableAction Action(TablePlacement table, string name)
        => table.Menu.GetComponentsInChildren<TableAction>().Single(a => a.name == name);
    static void Click(TablePlacement table, string name)
    {
        var action = Action(table, name);
        var ray = CombinedGlassChecks.ControlRay(action.GetComponent<RectTransform>(), .25f);
        Physics.SyncTransforms();
        Check(table.RaycastControls(ray, out float distance) && distance > 0, name + " has a discoverable physical collider");
        Check(table.HoverController(ray, true), name + " dispatches through the shared controller route");
    }
    static void PoseUnchanged(TablePlacement table, Pose pose)
    {
        Check(!table.MenuDocked && table.Menu.gameObject.activeInHierarchy, "menu remains pinned and visible across page rebuild");
        Near(table.Menu.position, pose.position, "menu page change preserves world position");
        Check(Quaternion.Angle(table.Menu.rotation, pose.rotation) < .001f, "menu page change preserves world heading");
    }
    static void Preview(TablePlacement table, WorkspaceArrangement arrangement, Camera camera, string filename)
    {
        string directory = Environment.GetEnvironmentVariable("CALHACKS_SETTINGS_PREVIEW_DIR");
        // Render verification always runs; the environment variable only enables saved PNGs.
        // Populate the same heading used by Update without invoking live XR/input readiness.
        var title = (Text)typeof(TablePlacement).GetField("title", Private).GetValue(table);
        title.text = (string)typeof(TablePlacement).GetMethod("MenuHeading", Private).Invoke(table, new object[] { arrangement });
        var pose = new Pose(camera.transform.position, camera.transform.rotation);
        var oldTarget = camera.targetTexture;
        int mask = camera.cullingMask;
        bool orthographic = camera.orthographic;
        float size = camera.orthographicSize;
        var target = new RenderTexture(1280, 1280, 24) { antiAliasing = 4 };
        var pixels = new Texture2D(1280, 1280, TextureFormat.RGB24, false);
        var previous = RenderTexture.active;
        var layers = table.Menu.GetComponentsInChildren<Transform>(true).ToDictionary(t => t, t => t.gameObject.layer);
        try
        {
            foreach (var item in layers.Keys) item.gameObject.layer = 31;
            camera.cullingMask = 1 << 31;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(.12f, .15f, .18f, 1);
            camera.stereoTargetEye = StereoTargetEyeMask.None;
            camera.orthographic = true; camera.orthographicSize = .20f;
            camera.transform.SetPositionAndRotation(table.Menu.position - table.Menu.forward * .6f, table.Menu.rotation);
            Canvas.ForceUpdateCanvases();
            camera.targetTexture = target; target.Create(); camera.Render();
            RenderTexture.active = target; pixels.ReadPixels(new Rect(0, 0, 1280, 1280), 0, 0); pixels.Apply();
            if (!string.IsNullOrEmpty(directory))
            {
                Directory.CreateDirectory(directory);
                File.WriteAllBytes(Path.Combine(directory, filename), pixels.EncodeToPNG());
            }
            var rendered = pixels.GetPixels32();
            int visibleText = rendered.Count(p => p.r > 170 && p.g > 170 && p.b > 170);
            Check(visibleText > 600, "real menu camera render contains readable foreground text");
            // Check every action independently; other labels must not hide a blank button.
            foreach (var action in table.Menu.GetComponentsInChildren<TableAction>())
            {
                var label = action.GetComponentInChildren<Text>();
                if (label == null) continue; // Settings uses a procedural gear instead of text.
                Check(label.text == action.name && label.enabled && label.gameObject.activeInHierarchy,
                    "action text exists, is enabled and matches its callback: " + action.name);
                var labelCorners = new Vector3[4]; label.rectTransform.GetWorldCorners(labelCorners);
                var labelViewport = labelCorners.Select(camera.WorldToViewportPoint).ToArray();
                int labelLeft = Mathf.Clamp(Mathf.FloorToInt(labelViewport.Min(v => v.x) * 1280), 0, 1279);
                int labelRight = Mathf.Clamp(Mathf.CeilToInt(labelViewport.Max(v => v.x) * 1280), 0, 1280);
                int labelBottom = Mathf.Clamp(Mathf.FloorToInt(labelViewport.Min(v => v.y) * 1280), 0, 1279);
                int labelTop = Mathf.Clamp(Mathf.CeilToInt(labelViewport.Max(v => v.y) * 1280), 0, 1280);
                int labelPixels = 0;
                for (int y = labelBottom; y < labelTop; y++) for (int x = labelLeft; x < labelRight; x++)
                {
                    var pixel = rendered[y * 1280 + x];
                    if (pixel.r > 170 && pixel.g > 170 && pixel.b > 170) labelPixels++;
                }
                Debug.Log("SETTINGS_ACTION_RENDER " + filename + " action=" + action.name + " text_pixels=" + labelPixels);
                Check(labelPixels > 100, "action label visibly renders inside its own rectangle: " + action.name + " pixels=" + labelPixels);
            }
            // Whole-menu text is insufficient: v1 rendered all labels but no gear.
            // Sample only the actual transformed gear rectangle, excluding all labels.
            var gearRect = Action(table, "Settings").GetComponent<RectTransform>();
            Check(gearRect.GetComponent<CanvasRenderer>() != null, "custom gear has a native CanvasRenderer");
            var corners = new Vector3[4]; gearRect.GetWorldCorners(corners);
            var viewport = corners.Select(camera.WorldToViewportPoint).ToArray();
            int left = Mathf.Clamp(Mathf.FloorToInt(viewport.Min(v => v.x) * 1280), 0, 1279);
            int right = Mathf.Clamp(Mathf.CeilToInt(viewport.Max(v => v.x) * 1280), 0, 1280);
            int bottom = Mathf.Clamp(Mathf.FloorToInt(viewport.Min(v => v.y) * 1280), 0, 1279);
            int top = Mathf.Clamp(Mathf.CeilToInt(viewport.Max(v => v.y) * 1280), 0, 1280);
            int gearPixels = 0; var quadrant = new int[4];
            for (int y = bottom; y < top; y++) for (int x = left; x < right; x++)
            {
                var pixel = rendered[y * 1280 + x];
                if (pixel.r <= 170 || pixel.g <= 170 || pixel.b <= 170) continue;
                gearPixels++;
                quadrant[(x >= (left + right) / 2 ? 1 : 0) + (y >= (bottom + top) / 2 ? 2 : 0)]++;
            }
            Check(gearPixels > 400 && quadrant.All(count => count > 30),
                "Settings gear itself visibly renders in all four quadrants; bright gear pixels=" + gearPixels);
            Debug.Log("SETTINGS_GEAR_RENDER PASS " + filename + " gear_pixels=" + gearPixels + " quadrants=" + string.Join(",", quadrant));
        }
        finally
        {
            foreach (var item in layers) if (item.Key != null) item.Key.gameObject.layer = item.Value;
            camera.transform.SetPositionAndRotation(pose.position, pose.rotation);
            camera.targetTexture = oldTarget; camera.cullingMask = mask;
            camera.orthographic = orthographic; camera.orthographicSize = size;
            RenderTexture.active = previous; target.Release();
            UnityEngine.Object.DestroyImmediate(target); UnityEngine.Object.DestroyImmediate(pixels);
        }
    }
    public static void Run()
    {
        var container = new GameObject("Settings menu checks - inactive no-runtime fixture");
        container.SetActive(false);
        var cameraObject = new GameObject("Settings menu check camera", typeof(Camera));
        cameraObject.tag = "MainCamera";
        cameraObject.transform.SetPositionAndRotation(new Vector3(0, 1.65f, 0), Quaternion.Euler(0, 31, 0));
        TablePlacement table = null;
        WorkspaceSurfaces surfaces = null;
        try
        {
            var arrangement = container.AddComponent<WorkspaceArrangement>(); Invoke(arrangement, "Awake");
            surfaces = arrangement.Surfaces;
            table = container.AddComponent<TablePlacement>();
            var display = new GameObject("Physical display fixture"); display.transform.SetParent(container.transform, false);
            table.Initialize(display.transform, AssetDatabase.LoadAssetAtPath<Material>("Assets/SpatialModeling/Materials/HostObject.mat"));
            table.SeedFromHead(cameraObject.transform.position, cameraObject.transform.forward); table.Place();
            table.UpdateLeftHandMenu(new Pose(new Vector3(-.3f, 1.15f, .3f), Quaternion.Euler(0, 20, 0)), cameraObject.transform.position, true);
            table.PinMenu();
            var menuPose = new Pose(table.Menu.position, table.Menu.rotation);
            Check(!surfaces.ShowDetected && surfaces.AutomaticEnabled, "room visualization defaults hidden while automatic surfaces remain enabled");
            var gear = Action(table, "Settings").GetComponent<RectTransform>();
            var menuRect = table.Menu.GetComponent<RectTransform>().rect;
            Check(gear.anchoredPosition.x > 0 && gear.anchoredPosition.y < 0
                && menuRect.Contains(gear.anchoredPosition + gear.rect.min)
                && menuRect.Contains(gear.anchoredPosition + gear.rect.max), "gear is wholly inside the bottom-right menu corner");
            Check(gear.GetComponent<SettingsGearGraphic>() != null, "gear uses a real graphic independent of font glyph support");
            Preview(table, arrangement, cameraObject.GetComponent<Camera>(), "01-arrange.png");
            Click(table, "Settings"); Check(table.SettingsOpen, "gear opens Settings"); PoseUnchanged(table, menuPose);
            Click(table, "Show room geometry");
            Check(surfaces.ShowDetected && surfaces.AutomaticEnabled, "show geometry changes visualization without disabling automatic data");
            PoseUnchanged(table, menuPose);
            Click(table, "Show room geometry");
            Check(!surfaces.ShowDetected && surfaces.AutomaticEnabled, "hide geometry leaves automatic surfaces enabled");
            table.Adjust(0, 0, 1, 0, Vector3.zero, Vector3.forward);
            var displayPose = new Pose(table.Display.position, table.Display.rotation);
            Check(!table.IsActualSize && table.ScaleLabel.Contains("2×"), "inspection magnification is explicit");
            Check(!table.Menu.GetComponentsInChildren<TableAction>(true).Any(a=>a.name=="Actual size")
                &&!table.Menu.GetComponentsInChildren<Text>(true).Any(t=>t.text.Contains("Actual size")||t.text.Contains("1:1")),
                "requested Actual size action and scale status are absent from handheld Settings");
            table.RestoreActualSize();
            Check(table.IsActualSize && table.ScaleLabel == "Actual size · 1:1", "retained scale API restores truthful physical scale");
            Near(table.Display.localScale, Vector3.one, "Actual size removes magnification");
            Near(table.Display.position, displayPose.position, "Actual size preserves workspace position");
            Check(Quaternion.Angle(table.Display.rotation, displayPose.rotation) < .001f, "Actual size preserves workspace heading");
            Preview(table, arrangement, cameraObject.GetComponent<Camera>(), "02-settings.png");
            Click(table, "Back to arrange"); PoseUnchanged(table, menuPose);
            // Exercise the actual user-facing creation callbacks, including repeated orientation.
            for (int i = 0; i < 7; i++)
            {
                string action = i % 2 == 0 ? "Add horizontal plane" : "Add vertical plane";
                Click(table, action);
                Check(surfaces.PlaneTargets.Count == i + 1, "each add action creates a distinct plane");
                var plane = surfaces.PlaneTargets[i];
                Check(i % 2 == 0 ? plane.forward.y > .999f : Mathf.Abs(plane.forward.y) < .001f && plane.up.y > .999f,
                    "horizontal/vertical labels match actual gravity-constrained plane orientation");
            }
            Check(surfaces.PlaneTargets.Distinct().Count() == 7, "multiple same-orientation planes coexist");
            var corrected = surfaces.PlaneTargets[0];
            var detected = (List<WorkspaceSurfaces.Surface>)typeof(WorkspaceSurfaces).GetField("detected", Private).GetValue(surfaces);
            var detectedPose = new Pose(corrected.position - Vector3.up * .04f, corrected.rotation);
            detected.Add(new WorkspaceSurfaces.Surface { Name = "Desk", Id = Guid.NewGuid(), Pose = detectedPose, Size = Vector2.one });
            Click(table, "Manage planes");
            Click(table, "Align " + surfaces.PlaneLabel(corrected));
            Near(corrected.position, detectedPose.position + Vector3.up * .003f, "explicit menu alignment applies the detected surface once");
            var manual = new Pose(corrected.position + Vector3.up * .06f, corrected.rotation);
            var independent = arrangement.Apply(corrected, new Pose(corrected.position, corrected.rotation), manual, false, false);
            Near(independent.position, manual.position, "after explicit menu alignment, ordinary manual correction remains independent from the nearby scan");
            corrected.SetPositionAndRotation(independent.position, independent.rotation);
            Click(table, "Back to arrange");
            var originals = surfaces.PlaneTargets.ToDictionary(t => t, t => new Pose(t.position, t.rotation));
            Click(table, "Manage planes"); PoseUnchanged(table, menuPose);
            Check(table.Menu.GetComponentsInChildren<TableAction>().Count(a => a.name.StartsWith("Delete ", StringComparison.Ordinal)) == 3,
                "plane management bounds the first page to three deletable entries");
            Click(table, "Next planes"); Click(table, "Next planes");
            var last = surfaces.PlaneTargets[6];
            var lastDelete = "Delete " + surfaces.PlaneLabel(last);
            Check(Action(table, lastDelete) != null, "pagination exposes the seventh plane's individual delete");
            Preview(table, arrangement, cameraObject.GetComponent<Camera>(), "03-planes-last-page.png");
            Click(table, lastDelete);
            Check(last == null && surfaces.PlaneTargets.Count == 6, "individual Delete removes only its selected plane");
            foreach (var remaining in surfaces.PlaneTargets)
            {
                Near(remaining.position, originals[remaining].position, "deleting one plane preserves every other plane position");
                Check(Quaternion.Angle(remaining.rotation, originals[remaining].rotation) < .001f, "deleting one plane preserves every other plane orientation");
            }
            PoseUnchanged(table, menuPose);
            // The deleted final page must clamp to the remaining valid page.
            Check(table.Menu.GetComponentsInChildren<TableAction>().Count(a => a.name.StartsWith("Delete ", StringComparison.Ordinal)) == 3,
                "deleting the last page clamps pagination without stranding remaining planes");
            Click(table, "Previous planes");
            var first = surfaces.PlaneTargets[0]; Click(table, "Delete " + surfaces.PlaneLabel(first));
            Check(first == null && surfaces.PlaneTargets.Count == 5, "first-page delete also selects only its own plane");
            Click(table, "Back to arrange");
            Click(table, "Settings"); Click(table, "Settings");
            Check(!table.SettingsOpen, "gear toggles Settings back to Arrange"); PoseUnchanged(table, menuPose);
            Debug.Log("SETTINGS_MENU_CHECKS PASS actual collider dispatch, bottom-right graphic gear, hidden default with automatic surfaces retained, requested Actual size action/status absent with scale API retained, multiple horizontal/vertical planes, individual deletion, pagination and pinned-menu pose retention");
        }
        finally
        {
            if (table != null) Invoke(table, "OnDestroy");
            if (surfaces != null) Invoke(surfaces, "OnDestroy");
            UnityEngine.Object.DestroyImmediate(container); UnityEngine.Object.DestroyImmediate(cameraObject);
        }
    }
}

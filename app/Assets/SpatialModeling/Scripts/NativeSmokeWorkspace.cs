using System.Reflection;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

namespace SpatialModeling
{
    // An explicit bounded test pose reaches the real table action without a headset.
    // This is software integration evidence, never physical placement acceptance.
    public static class NativeSmokeWorkspace
    {
        public static bool Seed(HostScene scene)
        {
            if (scene == null || scene.Table == null) return false;
            var camera = Camera.main;
            if (camera == null) return false;
            var softwareEye = camera.transform.position;
            var forward = Vector3.ProjectOnPlane(camera.transform.forward, Vector3.up).normalized;
            if (forward.sqrMagnitude < 0.5f || softwareEye.sqrMagnitude > 1000000f) return false;
            scene.Table.SeedFromHead(softwareEye, forward);
            Debug.Log($"P3_SMOKE_SOFTWARE_POSE eye={softwareEye:F3} forward={forward:F3}; actual table callback, no physical acceptance");
            var controls = Object.FindObjectsByType<TableAction>(FindObjectsInactive.Include, FindObjectsSortMode.None);
            bool found = false;
            foreach (var control in controls) if (control.name == "Place Table") found = true;
            // Inactive XR can prevent Table.Update from creating controls. Create the same
            // production panel, then invoke its registered Place Table callback.
            if (!found) typeof(TablePlacement).GetMethod("CreatePanel", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(scene.Table, null);
            return true;
        }

        public static bool Place(HostScene scene)
        {
            if (!Seed(scene)) return false;
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

        public static bool Capture(string path)
        {
            var camera = Camera.main;
            if (camera == null) return false;
            const int width = 1920, height = 1080;
            var previous = RenderTexture.active;
            var previousTarget = camera.targetTexture;
            float aspect = camera.aspect;
            RenderTexture target = null, resolved = null;
            Texture2D pixels = null;
            try
            {
                Canvas.ForceUpdateCanvases();
                target = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32) { antiAliasing = 4 };
                target.Create();
                camera.aspect = (float)width / height;
                // Hidden/inactive-XR windows may have no screenshot swapchain. Render the
                // actual production camera and world canvases through the installed URP.
                var request = new UniversalRenderPipeline.SingleCameraRequest { destination = target };
                if (!RenderPipeline.SupportsRenderRequest(camera, request)) return false;
                RenderPipeline.SubmitRenderRequest(camera, request);
                resolved = RenderTexture.GetTemporary(width, height, 0, RenderTextureFormat.ARGB32);
                Graphics.Blit(target, resolved);
                RenderTexture.active = resolved;
                pixels = new Texture2D(width, height, TextureFormat.RGBA32, false);
                pixels.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                pixels.Apply(false);
                File.WriteAllBytes(path, pixels.EncodeToPNG());
                Debug.Log($"P3_SMOKE_CAMERA_CAPTURE actual_camera={camera.name} eye={camera.transform.position:F3} size={width}x{height} msaa=4 path={path}; software render, not XR-eye acceptance");
                return File.Exists(path) && new FileInfo(path).Length > 1000;
            }
            catch (System.Exception error)
            { Debug.LogError("P3 actual camera capture failed: " + error.Message); return false; }
            finally
            {
                camera.aspect = aspect;
                camera.targetTexture = previousTarget;
                RenderTexture.active = previous;
                if (resolved != null) RenderTexture.ReleaseTemporary(resolved);
                if (target != null) { target.Release(); Object.Destroy(target); }
                if (pixels != null) Object.Destroy(pixels);
            }
        }
    }
}

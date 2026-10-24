using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Experimental.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.XR;
using UnityEngine.XR.OpenXR;

namespace SpatialModeling
{
    // Meta compositor underlay; no raw room-camera images are read or stored by this app.
    public sealed class WorkspacePassthrough : MonoBehaviour
    {
        public bool Supported { get; private set; }
        public bool Active { get; private set; }
        public string State { get; private set; } = "Checking room view…";
        OVRManager manager;
        OVRPassthroughLayer layer;
        Camera view;
        CameraClearFlags originalClear;
        Color originalBackground;
        bool originalPostProcessing;
        bool originalHdr;
        bool requested = true;
        bool ownsManager, attemptLive, savedView;
        readonly PassthroughReadinessGate readiness = new PassthroughReadinessGate();
        readonly List<XRDisplaySubsystem> displays = new List<XRDisplaySubsystem>();

        void OnEnable() => StartCoroutine(WaitForReady(readiness.Enable()));

        bool DisplayReady(out string waiting)
        {
            bool runtime = !string.IsNullOrEmpty(OpenXRRuntime.version);
            bool capability = runtime && OpenXRRuntime.IsExtensionEnabled("XR_FB_passthrough");
            displays.Clear(); SubsystemManager.GetSubsystems(displays);
            bool running = false; foreach (var display in displays) running |= display.running;
            int width = XRSettings.eyeTextureWidth, height = XRSettings.eyeTextureHeight;
            bool camera = Camera.main != null;
            waiting = !runtime ? "Room view waiting for XR runtime"
                : !capability ? "Room view unavailable over this Link connection"
                : !running || width <= 0 || height <= 0 ? "Room view waiting for an active headset display"
                : "Room view waiting for a tracked camera";
            return PassthroughReadinessGate.InputsReady(runtime, capability, running, width, height, camera);
        }

        void Waiting(string state)
        {
            if (State != state) Debug.Log("WORKSPACE_PASSTHROUGH " + state);
            State = state;
        }

        IEnumerator WaitForReady(int ticket)
        {
            while (readiness.IsCurrent(ticket))
            {
                bool ready = DisplayReady(out var waiting);
                bool begin = readiness.TryBegin(ticket, ready);
                if (!ready) { Suspend(); Waiting(waiting); }
                else if (begin) yield return Initialize(ticket);
                // A failed attempt is not repeated while the same display stays
                // ready. A real readiness transition or re-enable permits retry.
                yield return new WaitForSecondsRealtime(0.25f);
            }
        }

        IEnumerator Initialize(int ticket)
        {
            if (!readiness.IsCurrent(ticket)) yield break;
            if (!DisplayReady(out var waiting))
            { readiness.TryBegin(ticket, false); Suspend(); Waiting(waiting); yield break; }
            view = Camera.main;
            originalClear = view.clearFlags;
            originalBackground = view.backgroundColor;
            originalHdr = view.allowHDR;
            var data = view.GetUniversalAdditionalCameraData();
            originalPostProcessing = data.renderPostProcessing;
            savedView = attemptLive = true;
            Waiting("Room view starting");
            if (manager == null) manager = FindAnyObjectByType<OVRManager>();
            if (manager == null) { ownsManager = true; manager = gameObject.AddComponent<OVRManager>(); }
            else if (ownsManager) manager.enabled = true;
            manager.isInsightPassthroughEnabled = true;
            if (layer == null)
            {
                var layerObject = new GameObject("Real room passthrough underlay");
                layerObject.SetActive(false);
                layerObject.transform.SetParent(transform, false);
                layer = layerObject.AddComponent<OVRPassthroughLayer>();
                layer.textureOpacity = 1f;
                layer.passthroughLayerResumed.AddListener(_ => Debug.Log("WORKSPACE_PASSTHROUGH layer_presented=True"));
            }
            layer.hidden = !requested;
            layer.gameObject.SetActive(true);
            float until = Time.realtimeSinceStartup + 10;
            while (readiness.IsCurrent(ticket) && DisplayReady(out _)
                && !OVRManager.IsInsightPassthroughInitialized() && Time.realtimeSinceStartup < until) yield return null;
            if (!readiness.IsCurrent(ticket)) yield break;
            if (!DisplayReady(out waiting))
            { readiness.TryBegin(ticket, false); Suspend(); Waiting(waiting); yield break; }
            if (!OVRManager.IsInsightPassthroughInitialized())
            {
                Suspend();
                State = "Room view could not start over Link";
                Debug.LogWarning("WORKSPACE_PASSTHROUGH initialization failed; opaque view preserved");
                yield break;
            }
            Supported = true;
            Apply();
            yield return new WaitForEndOfFrame();
            if (!readiness.IsCurrent(ticket)) yield break;
            if (!DisplayReady(out waiting))
            { readiness.TryBegin(ticket, false); Suspend(); Waiting(waiting); yield break; }
            displays.Clear();
            SubsystemManager.GetSubsystems(displays);
            foreach (var display in displays)
                if (display.running)
                for (int i = 0; i < display.GetRenderPassCount(); i++)
                {
                    display.GetRenderPass(i, out var pass);
                    Debug.Log("WORKSPACE_PASSTHROUGH eye_format=" + pass.renderTargetDesc.graphicsFormat
                        + " alpha=" + GraphicsFormatUtility.HasAlphaChannel(pass.renderTargetDesc.graphicsFormat)
                        + " preserve_alpha=" + Graphics.preserveFramebufferAlpha + " camera_hdr=" + view.allowHDR);
                }
        }

        public void Toggle() { if (Supported) { requested = !requested; Apply(); } }

        void Apply()
        {
            if (view == null || layer == null || manager == null) return;
            layer.hidden = !requested;
            view.clearFlags = requested ? CameraClearFlags.SolidColor : originalClear;
            view.backgroundColor = requested ? Color.clear : originalBackground;
            // URP's packed 32-bit HDR format has no alpha. The compositor needs
            // an alpha-bearing eye buffer for the real-room underlay to show.
            view.allowHDR = requested ? false : originalHdr;
            view.GetUniversalAdditionalCameraData().renderPostProcessing = requested ? false : originalPostProcessing;
            Active = requested;
            State = Active ? "Room view on" : "Room view off";
            Debug.Log("WORKSPACE_PASSTHROUGH active=" + Active);
        }

        void OnDisable()
        {
            readiness.Disable();
            StopAllCoroutines();
            Suspend();
        }

        void Suspend()
        {
            Supported = Active = false;
            if (!attemptLive && !savedView) return;
            if (layer != null) { layer.hidden = true; layer.gameObject.SetActive(false); }
            if (manager != null)
            {
                manager.isInsightPassthroughEnabled = false;
                if (ownsManager) manager.enabled = false;
            }
            if (savedView && view != null)
            {
                view.clearFlags = originalClear;
                view.backgroundColor = originalBackground;
                view.allowHDR = originalHdr;
                view.GetUniversalAdditionalCameraData().renderPostProcessing = originalPostProcessing;
            }
            attemptLive = savedView = false;
            view = null;
        }

        void OnDestroy()
        {
            if (layer != null) Destroy(layer.gameObject);
            if (ownsManager && manager != null) Destroy(manager);
        }
    }

    // Pure admission state: capability alone cannot start Meta without an eye
    // target. Only a new real readiness epoch or component enable retries once.
    public sealed class PassthroughReadinessGate
    {
        int epoch;
        bool enabled, attempted;
        public static bool InputsReady(bool runtime, bool capability, bool displayRunning,
            int eyeWidth, int eyeHeight, bool camera) =>
            runtime && capability && displayRunning && eyeWidth > 0 && eyeHeight > 0 && camera;
        public int Enable() { enabled = true; attempted = false; return ++epoch; }
        public void Disable() { enabled = attempted = false; epoch++; }
        public bool IsCurrent(int ticket) => enabled && ticket == epoch;
        public bool TryBegin(int ticket, bool ready)
        {
            if (!IsCurrent(ticket)) return false;
            if (!ready) { attempted = false; return false; }
            if (attempted) return false;
            attempted = true;
            return true;
        }
    }
}

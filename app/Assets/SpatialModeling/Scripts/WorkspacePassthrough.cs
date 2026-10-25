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

        IEnumerator Start()
        {
            float until = Time.realtimeSinceStartup + 15;
            while (OpenXRRuntime.version == "" && Time.realtimeSinceStartup < until) yield return null;
            // Missing capability must leave a working opaque scene, not a fake black "passthrough".
            Supported = OpenXRRuntime.IsExtensionEnabled("XR_FB_passthrough");
            if (!Supported)
            {
                State = "Room view unavailable over this Link connection";
                Debug.Log("WORKSPACE_PASSTHROUGH unsupported: XR_FB_passthrough not enabled");
                yield break;
            }
            view = Camera.main;
            if (view == null) { State = "Room view unavailable: no tracked camera"; Supported = false; yield break; }
            originalClear = view.clearFlags;
            originalBackground = view.backgroundColor;
            originalHdr = view.allowHDR;
            var data = view.GetUniversalAdditionalCameraData();
            originalPostProcessing = data.renderPostProcessing;
            // Meta's feature initializes native session/presence independently.
            // Creating OVRManager during IDLE can start origin-space churn before
            // the session has tracking or attached actions. Do not fall through.
            State="Waiting for an active, worn Link headset";
            while(!WorkspaceSurfaces.RoomHeadReady()) yield return null;
            manager = FindAnyObjectByType<OVRManager>();
            if (manager == null) manager = gameObject.AddComponent<OVRManager>();
            manager.isInsightPassthroughEnabled = true;
            var layerObject = new GameObject("Real room passthrough underlay");
            layerObject.SetActive(false);
            layerObject.transform.SetParent(transform, false);
            layer = layerObject.AddComponent<OVRPassthroughLayer>();
            layer.textureOpacity = 1f;
            layer.passthroughLayerResumed.AddListener(_ => Debug.Log("WORKSPACE_PASSTHROUGH layer_presented=True"));
            layerObject.SetActive(true);
            until = Time.realtimeSinceStartup + 10;
            while (!OVRManager.IsInsightPassthroughInitialized() && Time.realtimeSinceStartup < until) yield return null;
            if (!OVRManager.IsInsightPassthroughInitialized())
            {
                manager.isInsightPassthroughEnabled = false;
                layer.hidden = true;
                Supported = false;
                State = "Room view could not start over Link";
                Debug.LogWarning("WORKSPACE_PASSTHROUGH initialization failed; opaque view preserved");
                yield break;
            }
            Apply();
            yield return new WaitForEndOfFrame();
            var displays = new List<XRDisplaySubsystem>();
            SubsystemManager.GetSubsystems(displays);
            foreach (var display in displays)
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
            StopAllCoroutines();
            if (layer != null) layer.hidden = true;
            if (manager != null) manager.isInsightPassthroughEnabled = false;
            if (view != null)
            {
                view.clearFlags = originalClear;
                view.backgroundColor = originalBackground;
                view.allowHDR = originalHdr;
                view.GetUniversalAdditionalCameraData().renderPostProcessing = originalPostProcessing;
            }
            Active = false;
        }
    }
}

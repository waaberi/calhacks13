using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR;

namespace SpatialModeling
{
    public partial class VoiceUiAdapter
    {
        public string SelectedObjectId { get; private set; }
        public bool SelectingObject { get; private set; }
        LineRenderer selectionOutline;
        Material selectionMaterial;
        readonly List<KeyValuePair<string, string>> targetNames = new List<KeyValuePair<string, string>>();

        string ObjectName(string id)
        {
            if (id == null || host == null || !host.HasCurrentScene) return null;
            host.GetShownObjects(targetNames);
            foreach (var item in targetNames) if (item.Key == id) return item.Value;
            return null;
        }

        public string ObjectTargetLabel => SelectingObject
            ? "Select object: aim at 3D model, press front trigger"
            : "Selected: " + (ObjectName(SelectedObjectId) ?? "none") +
              " · Pointing: " + (ObjectName(pointerId) ?? "none");

        bool ControllerTargetingReady => Application.isEditor ||
            (XRSettings.isDeviceActive && OVRPlugin.initialized && OVRPlugin.userPresent && OVRPlugin.hasVrFocus);

        // Called once per frame from the same stabilized controller rays that draw the pointer.
        // Keep calling for a stationary target: VoiceSession's pending-target dwell needs time to advance.
        public void SetControllerPointer(string id)
        {
            if (!ControllerTargetingReady || ObjectName(id) == null) id = null;
            if (pointerId != id) Debug.Log("VOICE_POINTER target=" + (id ?? "none") + " source=controller");
            pointerId = id;
            Handle(session.SetPointerTarget(id));
        }

        public void BeginObjectSelection()
        {
            SelectingObject = true;
            Note("Aim at a 3D object and press the front trigger. Selection does not move it.");
        }

        // Selection is local intent only. This never starts a grip, moves a Transform or sends a select mutation.
        public bool SelectObject(string id)
        {
            if (ObjectName(id) == null) return false;
            SelectedObjectId = id;
            SelectingObject = false;
            Debug.Log("VOICE_SELECTION target=" + id + " name=" + ObjectName(id) + " drag=False");
            Note("Selected: " + ObjectName(id));
            Handle(session.SetSelection(new[] { id }));
            return true;
        }

        public bool SelectControllerObject(string id)
        {
            if (!ControllerTargetingReady || ObjectName(id) == null) return false;
            if (SelectedObjectId != id) return SelectObject(id);
            string name = ObjectName(id);
            ClearObjectSelection();
            Note("Deselected: " + name);
            Debug.Log("VOICE_SELECTION target=none previous=" + id + " reason=trigger_toggle drag=False");
            return true;
        }

        public void ClearObjectSelection()
        {
            SelectedObjectId = null;
            SelectingObject = false;
            Handle(session.SetSelection(Array.Empty<string>()));
            if (selectionOutline != null) selectionOutline.enabled = false;
        }

        public void ResetObjectTargeting()
        {
            ClearObjectSelection();
            pointerId = null;
            session.SetPointerTarget(null);
            FindFirstObjectByType<WorkspaceInteraction>()?.ForgetVoicePointer();
        }

        void SuspendObjectTargeting()
        {
            pointerId = null;
            session.SetPointerTarget(null);
            SelectingObject = false;
            CancelPressed();
            FindFirstObjectByType<WorkspaceInteraction>()?.ForgetVoicePointer();
        }

        void LateUpdate()
        {
            if (host == null) return;
            string shown = SelectedObjectId ?? pointerId;
            if (ObjectName(shown) == null || host.Placement == null || !host.Placement.gameObject.activeInHierarchy ||
                !host.TryGetBounds(shown, out var bounds))
            {
                if (selectionOutline != null) selectionOutline.enabled = false;
                return;
            }
            if (selectionOutline == null)
            {
                var go = new GameObject("Voice object selection outline", typeof(LineRenderer));
                go.transform.SetParent(transform, false);
                selectionOutline = go.GetComponent<LineRenderer>();
                selectionMaterial = new Material(Shader.Find("Universal Render Pipeline/Unlit"));
                selectionOutline.sharedMaterial = selectionMaterial;
                selectionOutline.useWorldSpace = true;
                selectionOutline.positionCount = 16;
                selectionOutline.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                selectionOutline.receiveShadows = false;
            }
            bounds.Expand(.004f);
            var lo = bounds.min; var hi = bounds.max;
            var corners = new[] {
                new Vector3(lo.x,lo.y,lo.z), new Vector3(hi.x,lo.y,lo.z),
                new Vector3(hi.x,hi.y,lo.z), new Vector3(lo.x,hi.y,lo.z),
                new Vector3(lo.x,lo.y,hi.z), new Vector3(hi.x,lo.y,hi.z),
                new Vector3(hi.x,hi.y,hi.z), new Vector3(lo.x,hi.y,hi.z)
            };
            int[] path = { 0,1,2,3,0,4,5,6,7,4,5,1,2,6,7,3 };
            for (int i = 0; i < path.Length; i++) selectionOutline.SetPosition(i, corners[path[i]]);
            Color color = SelectedObjectId != null ? new Color(1f,.8f,.08f) : new Color(.1f,.9f,1f);
            selectionMaterial.SetColor("_BaseColor", color);
            selectionOutline.startColor = selectionOutline.endColor = color;
            selectionOutline.startWidth = selectionOutline.endWidth = .0015f;
            selectionOutline.enabled = true;
        }

        void DisposeObjectTargeting()
        {
            OVRManager.VrFocusLost -= SuspendObjectTargeting;
            OVRManager.HMDUnmounted -= SuspendObjectTargeting;
            if (selectionMaterial != null)
            {
                if (Application.isPlaying) Destroy(selectionMaterial); else DestroyImmediate(selectionMaterial);
            }
        }
    }
}

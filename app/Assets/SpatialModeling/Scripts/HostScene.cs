using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.InputSystem;
using UnityEngine.XR;
using UnityEngine.UI;

namespace SpatialModeling
{
    // P0 (#11): connects to the host add-on (or the fake host), draws the scene it sends,
    // and shows the connection state from the contract's table (contracts/README.md, Connecting).
    public class HostScene : MonoBehaviour
    {
        [Header("Host connection (localhost only)")]
        [SerializeField] string host = "127.0.0.1";
        [SerializeField] int port = 8765;
        [Tooltip("Shown to the other participants. Empty: \"VR user\".")]
        [SerializeField] string userName = "";

        [Header("Display only. Never changes the native model.")]
        [SerializeField] Vector3 rootPosition = new Vector3(0f, 1f, 1.5f);
        [SerializeField] float displayScale = 5f;
        [Tooltip("Initial placement is relative to the tracked headset, never Blender coordinates.")]
        [SerializeField] float viewingDistance = 1f;
        [SerializeField] float belowEyeHeight = 0.35f;
        [Tooltip("URP Lit material shared by every object; each object's color is set per renderer.")]
        [SerializeField] Material objectMaterial;

        enum Status { Connecting, Connected, NotResponding, Disconnected, VersionMismatch }

        const long NotRespondingMs = 6000;
        static readonly int BaseColorId = Shader.PropertyToID("_BaseColor");

        readonly Dictionary<string, GameObject> objects = new Dictionary<string, GameObject>();
        HostLink link;
        Transform root;
        MaterialPropertyBlock block;
        Material fallbackMaterial;
        GUIStyle style;
        InputAction recenterAction;
        bool placed, recenterRequested;
        GameObject statusPanel;
        Text headsetStatus;

        bool opened;        // a socket has opened at least once
        bool connected;     // welcome and snapshot have arrived on this connection
        bool haveScene;     // we are showing a scene, current or stale
        string socketError = "", hostError = "", hostErrorCode = "", documentName = "";
        long revision;
        Status status = Status.Connecting;

        void Awake()
        {
            root = new GameObject("HostSceneRoot").transform;
            root.position = rootPosition;
            root.localScale = Vector3.one * displayScale;
            root.gameObject.SetActive(false); // Wait for an actual tracked pose, not the startup origin.
            block = new MaterialPropertyBlock();
        }

        void OnEnable()
        {
            recenterAction = new InputAction("Recenter view", InputActionType.Button);
            recenterAction.AddBinding("<XRController>{RightHand}/secondaryButton"); // B on Quest
            recenterAction.AddBinding("<XRController>{LeftHand}/secondaryButton");  // Y on Quest
            recenterAction.AddBinding("<Keyboard>/r");
            recenterAction.performed += _ => RequestRecenter();
            recenterAction.Enable();
            var name = string.IsNullOrWhiteSpace(userName) ? "VR user" : userName.Trim();
            link = new HostLink(host, port, new JObject
            {
                ["role"] = "vr",
                ["name"] = name,
                ["app"] = new JObject { ["name"] = "SpatialModeling", ["version"] = Application.version }
            });
        }

        void OnDisable()
        {
            recenterAction?.Dispose();
            recenterAction = null;
            link?.Stop();   // its thread exits and posts nothing more, so a re-enable can't run two
            link = null;
            connected = false;
        }

        void OnDestroy()
        {
            ClearScene();
            if (root != null) Destroy(root.gameObject);
            if (statusPanel != null) Destroy(statusPanel);
            if (fallbackMaterial != null) Destroy(fallbackMaterial);
        }

        void Update()
        {
            if (link == null) return;
            while (link.Events.TryDequeue(out var e)) Handle(e);

            if (link.SocketOpen && link.SilenceMs > NotRespondingMs) status = Status.NotResponding;
            else if (link.SocketOpen) status = connected ? Status.Connected : Status.Connecting;
            else if (hostErrorCode == "unsupported_version") status = Status.VersionMismatch;
            else status = opened || haveScene ? Status.Disconnected : Status.Connecting;
        }

        public void RequestRecenter() => recenterRequested = true;

        void LateUpdate()
        {
            var camera = Camera.main;
            if (camera == null) return;
            UpdateHeadsetStatus(camera);
            // Place once after head tracking starts. Looking/walking and scene reconnects
            // must not move an already placed model. B/Y explicitly requests a new placement.
            if (placed && !recenterRequested) return;
            if (XRSettings.enabled || XRSettings.isDeviceActive)
            {
                var head = InputDevices.GetDeviceAtXRNode(XRNode.Head);
                if (!head.TryGetFeatureValue(UnityEngine.XR.CommonUsages.isTracked, out var tracked) || !tracked) return;
                if (head.TryGetFeatureValue(UnityEngine.XR.CommonUsages.userPresence, out var present) && !present) return;
            }
            else if (!Application.isFocused) return;

            if (!TryGetDisplayPose(camera.transform.position, camera.transform.forward,
                    viewingDistance, belowEyeHeight, out var position, out var rotation)) return;
            root.SetPositionAndRotation(position, rotation);
            root.gameObject.SetActive(true);
            placed = true;
            recenterRequested = false;
            Debug.Log($"HostScene placement: head={camera.transform.position:F3} forward={camera.transform.forward:F3} root={position:F3}; display only");
        }

        void UpdateHeadsetStatus(Camera camera)
        {
            if (headsetStatus == null)
            {
                // IMGUI is only visible on the monitor. A world-space canvas is rendered
                // by both headset eyes, so a stale scene cannot silently look connected.
                statusPanel = new GameObject("Blender connection status", typeof(RectTransform), typeof(Canvas), typeof(Image));
                statusPanel.transform.SetParent(camera.transform, false);
                statusPanel.transform.localPosition = new Vector3(0f, 0.10f, 1f);
                statusPanel.transform.localScale = Vector3.one * 0.001f;
                var rect = statusPanel.GetComponent<RectTransform>();
                rect.sizeDelta = new Vector2(950f, 190f);
                var canvas = statusPanel.GetComponent<Canvas>();
                canvas.renderMode = RenderMode.WorldSpace;
                canvas.worldCamera = camera;
                var background = statusPanel.GetComponent<Image>();
                background.color = new Color(0.015f, 0.02f, 0.03f, 0.94f);
                background.raycastTarget = false;
                var label = new GameObject("Status", typeof(RectTransform), typeof(Text));
                label.transform.SetParent(statusPanel.transform, false);
                var textRect = label.GetComponent<RectTransform>();
                textRect.anchorMin = Vector2.zero;
                textRect.anchorMax = Vector2.one;
                textRect.offsetMin = new Vector2(20f, 12f);
                textRect.offsetMax = new Vector2(-20f, -12f);
                headsetStatus = label.GetComponent<Text>();
                headsetStatus.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                headsetStatus.fontSize = 32;
                headsetStatus.alignment = TextAnchor.MiddleCenter;
                headsetStatus.raycastTarget = false;
            }
            headsetStatus.color = status == Status.Connected ? Color.white : new Color(1f, 0.7f, 0.25f);
            switch (status)
            {
                case Status.Connected:
                    headsetStatus.text = $"Blender connected — revision {revision}\nB / Y: Recenter view";
                    break;
                case Status.NotResponding:
                    headsetStatus.text = "Blender is not responding\nScene is stale — edits disabled";
                    break;
                case Status.VersionMismatch:
                    headsetStatus.text = "App and Blender add-on versions do not match\nEdits disabled";
                    break;
                default:
                    headsetStatus.text = haveScene
                        ? "Disconnected from Blender — reconnecting…\nLast scene is stale — edits disabled"
                        : "Connecting to Blender…\nWaiting for a complete scene";
                    break;
            }
        }

        public static bool TryGetDisplayPose(Vector3 eye, Vector3 gaze, float distance,
            float belowEye, out Vector3 position, out Quaternion rotation)
        {
            var forward = Vector3.ProjectOnPlane(gaze, Vector3.up);
            position = eye;
            rotation = Quaternion.identity;
            if (forward.sqrMagnitude < 0.001f) return false; // Looking straight up/down: wait.
            forward.Normalize();
            position = eye + forward * Mathf.Clamp(distance, 0.5f, 2f)
                - Vector3.up * Mathf.Clamp(belowEye, 0f, 0.75f);
            rotation = Quaternion.LookRotation(forward, Vector3.up);
            return true;
        }

        void OnGUI()
        {
            string stale = haveScene ? "\nShowing the last scene (stale). Edits are disabled." : "";
            string reason = hostError.Length > 0 ? hostError : socketError;
            string text;
            switch (status)
            {
                case Status.Connected: text = $"Connected to {documentName} - revision {revision}"; break;
                case Status.NotResponding: text = "Blender is not responding. Edits are disabled."; break;
                case Status.VersionMismatch: text = $"This app and the Blender add-on don't match.\n{hostError}"; break;
                case Status.Disconnected: text = $"Disconnected. Reconnecting...{stale}\n{reason}"; break;
                default: text = $"Connecting to Blender at {host}:{port} ...{stale}\n{(link != null && link.SocketOpen ? "" : reason)}"; break;
            }
            if (style == null) style = new GUIStyle(GUI.skin.label) { fontSize = 26 };
            style.normal.textColor = status == Status.Connected ? Color.white : new Color(1f, 0.6f, 0.2f);
            GUI.Label(new Rect(20, 20, 1400, 200), text, style);
            if (GUI.Button(new Rect(20, 230, 300, 48), "Recenter view (B / Y / R)")) RequestRecenter();
        }

        void Handle(HostEvent e)
        {
            switch (e.Kind)
            {
                case HostEventKind.Opened: opened = true; socketError = ""; break;
                case HostEventKind.Closed: connected = false; socketError = e.Text; break;
                case HostEventKind.Welcome: hostError = hostErrorCode = ""; documentName = e.Text; break;
                case HostEventKind.Error:
                    hostErrorCode = e.Code;
                    hostError = $"{e.Text} ({e.Code})";
                    Debug.LogWarning("Host error: " + hostError);
                    break;
                case HostEventKind.Warning: Debug.LogWarning("HostScene: " + e.Text); break;
                case HostEventKind.Scene:
                    Debug.Log($"HostScene received {(e.Snapshot ? "snapshot" : "update")} revision={e.Revision} objects={e.Objects.Count} removed={e.Removed.Count}");
                    if (e.Snapshot) ClearScene();
                    if (e.Revision.HasValue) revision = e.Revision.Value;
                    foreach (var id in e.Removed) Remove(id);
                    foreach (var r in e.Objects)
                    {
                        try { ApplyObject(r); }
                        catch (System.Exception ex) { Debug.LogWarning($"HostScene: couldn't draw {r.Id}: {ex.Message}"); }
                    }
                    if (e.Snapshot) connected = haveScene = true;
                    break;
            }
        }

        // ---------- drawing ----------

        Material ObjectMaterial
        {
            get
            {
                if (objectMaterial != null) return objectMaterial;
                if (fallbackMaterial == null)
                {
                    Debug.LogError("HostScene: assign Object Material (URP Lit). Players don't include a default material.");
                    var shader = Shader.Find("Universal Render Pipeline/Lit");
                    if (shader != null) fallbackMaterial = new Material(shader);
                }
                return fallbackMaterial;
            }
        }

        void ApplyObject(ObjectRecord r)
        {
            if (!objects.TryGetValue(r.Id, out var go))
            {
                go = new GameObject(r.Id, typeof(MeshFilter), typeof(MeshRenderer));   // selection colliders come in P2
                go.transform.SetParent(root, false);
                go.GetComponent<MeshRenderer>().sharedMaterial = ObjectMaterial;
                objects[r.Id] = go;
            }
            go.name = r.Name;
            go.SetActive(r.Visible);

            // Wire transforms are world space, so objects stay flat under the display root.
            if (r.HasTransform)
            {
                go.transform.localPosition = r.Position;
                go.transform.localRotation = r.Rotation;
                go.transform.localScale = r.Scale;
                Debug.Log($"HostScene object {r.Name}: local={r.Position:F4} world={go.transform.position:F4} root={root.position:F3}");
            }

            var mf = go.GetComponent<MeshFilter>();
            var mr = go.GetComponent<MeshRenderer>();
            if (r.HasMesh)
            {
                if (mf.sharedMesh != null) Destroy(mf.sharedMesh);
                mf.sharedMesh = r.Mesh != null ? BuildMesh(r.Mesh, r.Name) : null;
                mr.enabled = r.Mesh != null;
            }

            if (r.Color.HasValue)
            {
                // The wire color is linear; a vector reaches the shader unconverted.
                var c = r.Color.Value;
                if (QualitySettings.activeColorSpace == ColorSpace.Gamma) c = c.gamma;
                block.Clear();
                block.SetVector(BaseColorId, c);
                mr.SetPropertyBlock(block);
            }
            else mr.SetPropertyBlock(null);   // no material: the shared material's own color
        }

        static Mesh BuildMesh(MeshData d, string name)
        {
            var mesh = new Mesh { name = name };
            if (d.Positions.Length > 65535) mesh.indexFormat = IndexFormat.UInt32;
            mesh.vertices = d.Positions;
            mesh.triangles = d.Indices;
            if (d.Normals != null) mesh.normals = d.Normals;
            else mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }

        void Remove(string id)
        {
            if (!objects.TryGetValue(id, out var go)) return;
            var mf = go.GetComponent<MeshFilter>();
            if (mf != null && mf.sharedMesh != null) Destroy(mf.sharedMesh);
            Destroy(go);
            objects.Remove(id);
        }

        void ClearScene()
        {
            foreach (var id in new List<string>(objects.Keys)) Remove(id);
        }
    }
}

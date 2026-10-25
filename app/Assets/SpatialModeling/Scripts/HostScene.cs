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
    public partial class HostScene : MonoBehaviour
    {
        [Header("Host connection (localhost only)")]
        [SerializeField] string host = "127.0.0.1";
        [SerializeField] int port = 8765;
        [Tooltip("Shown to the other participants. Empty: \"VR user\".")]
        [SerializeField] string userName = "";

        [Header("Display only. Never changes the native model.")]
        [SerializeField] Vector3 rootPosition = new Vector3(0f, 1f, 1.5f);
        [Tooltip("Initial placement is relative to the tracked headset, never Blender coordinates.")]
        [SerializeField] float viewingDistance = 1f;
        [SerializeField] float belowEyeHeight = 0.35f;
        [Tooltip("URP Lit material shared by every object; each object's color is set per renderer.")]
        [SerializeField] Material objectMaterial;

        enum Status { Connecting, Connected, NotResponding, Disconnected, VersionMismatch, ConfigurationError }

        const long NotRespondingMs = 6000;
        static readonly int BaseColorId = Shader.PropertyToID("_BaseColor");

        readonly Dictionary<string, GameObject> objects = new Dictionary<string, GameObject>();
        public Transform Placement => root;
        public int ObjectCount => objects.Count;
        public bool IsCurrent => status == Status.Connected;
        public string ConnectionText => IsCurrent
            ? $"Connected to {documentName} — revision {revision}"
            : $"{status} — last scene is stale; native edits disabled";
        public string DocumentId => documentId;
        public string OpenEpoch => openEpoch;
        public long Revision => revision;
        public TablePlacement Table => table;
        public Material ObjectDisplayMaterial => ObjectMaterial;
        public IEnumerable<WorkspaceObjectView> ObjectViews
        {
            get { foreach (var go in objects.Values) if (go != null) yield return go.GetComponent<WorkspaceObjectView>(); }
        }
        public bool DisplayPlacementReady => placed && !recenterRequested;
        public Pose PlacementHeadPose { get; private set; }
        readonly StartupFacingGate startupFacing = new StartupFacingGate();
        string documentId = "", openEpoch = "";
        TablePlacement table;
        internal HostLink Link => link;
        internal event System.Action<HostEvent> HostEventReceived;
        HostLink link;
        Transform root;
        MaterialPropertyBlock block;
        Material fallbackMaterial;
        GUIStyle style;
        InputAction recenterAction;
        bool placed, recenterRequested;
        string placementReadiness = "";
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
            // The host has already converted Blender lengths to metres. A
            // Unity world unit is one metre; no serialized demo enlargement.
            root.localScale = Vector3.one;
            root.gameObject.SetActive(false); // Wait for an actual tracked pose, not the startup origin.
            block = new MaterialPropertyBlock();
            table = GetComponent<TablePlacement>() ?? gameObject.AddComponent<TablePlacement>();
            table.Initialize(root, ObjectMaterial);
        }

        internal static bool TryResolvePort(string configured, int fallback, out int resolved)
        {
            resolved = fallback;
            if (configured != null && configured.Length > 0 &&
                !int.TryParse(configured, System.Globalization.NumberStyles.None,
                    System.Globalization.CultureInfo.InvariantCulture, out resolved)) return false;
            return resolved >= 1 && resolved <= 65535;
        }

        void OnEnable()
        {
            OVRManager.HMDUnmounted += InvalidateUnconfirmedPlacement;
            OVRManager.VrFocusLost += InvalidateUnconfirmedPlacement;
            // Explicit isolated-test/deployment configuration must never fall
            // back to a different native session after a typo. No LAN endpoint.
            if (!TryResolvePort(System.Environment.GetEnvironmentVariable("CALHACKS_HOST_PORT"), port, out int connectionPort)
                || !System.Net.IPAddress.TryParse(host, out var address) || !System.Net.IPAddress.IsLoopback(address))
            {
                hostError = "Invalid local host configuration: CALHACKS_HOST_PORT must be 1–65535 and host must be loopback";
                status = Status.ConfigurationError;
                Debug.LogError(hostError);
                return;
            }
            Debug.Log($"HostScene loopback endpoint {host}:{connectionPort}");
            recenterAction = new InputAction("Recenter view", InputActionType.Button);
            recenterAction.AddBinding("<XRController>{RightHand}/secondaryButton"); // B on Quest
            recenterAction.AddBinding("<XRController>{LeftHand}/secondaryButton");  // Y on Quest
            recenterAction.AddBinding("<Keyboard>/r");
            recenterAction.performed += context =>
            {
                if (!(context.control?.device is Keyboard && PreviewInteraction.BlocksDesktopShortcuts)) RequestRecenter();
            };
            recenterAction.Enable();
            var name = string.IsNullOrWhiteSpace(userName) ? "VR user" : userName.Trim();
            link = new HostLink(host, connectionPort, new JObject
            {
                ["role"] = "vr",
                ["name"] = name,
                ["app"] = new JObject { ["name"] = "SpatialModeling", ["version"] = Application.version }
            });
        }

        void OnDisable()
        {
            OVRManager.HMDUnmounted -= InvalidateUnconfirmedPlacement;
            OVRManager.VrFocusLost -= InvalidateUnconfirmedPlacement;
            recenterAction?.Dispose();
            recenterAction = null;
            link?.Stop();   // its thread exits and posts nothing more, so a re-enable can't run two
            link = null;
            connected = false;
        }

        static void ReleaseObject(UnityEngine.Object value)
        {
            if (value == null) return;
            if (Application.isPlaying) Destroy(value);
            else DestroyImmediate(value);
        }

        void OnDestroy()
        {
            ClearScene();
            if (root != null) ReleaseObject(root.gameObject);
            if (statusPanel != null) ReleaseObject(statusPanel);
            if (fallbackMaterial != null) ReleaseObject(fallbackMaterial);
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

        public void RequestRecenter() => RequestPlacement(true);

        public void RequestTrackedPlacement() => RequestPlacement(false);

        void RequestPlacement(bool explicitUserRequest)
        {
            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
            placed = false;
            // XR-origin callbacks are automatic, including at initial session
            // startup. Only an actual user B/Y/button request may skip settling.
            recenterRequested = explicitUserRequest;
            startupFacing.Ready(Vector3.forward, false, Time.realtimeSinceStartupAsDouble);
            table?.ConfirmTrackingReset();
            FindFirstObjectByType<BlenderScreen>()?.RequestRecenter();
        }

        static readonly bool DesktopPlayer = System.Array.IndexOf(System.Environment.GetCommandLineArgs(), "--desktop") >= 0;

        // Tracked does not mean worn: Link can retain a valid pose on a desk.
        // Missing userPresence must not silently certify that the user is ready.
        public static bool HeadsetAllowsPlacement(bool xrActive, bool tracked,
            bool presenceKnown, bool worn, bool vrFocused)
            => xrActive && tracked && presenceKnown && worn && vrFocused;

        public void InvalidateUnconfirmedPlacement()
        {
            startupFacing.Ready(Vector3.forward, false, Time.realtimeSinceStartupAsDouble);
            // A confirmed table is world-anchored. Ordinary removal/focus loss
            // must not silently recenter an arrangement the user already placed.
            if (table == null || table.IsPlaced) return;
            placed = false;
            recenterRequested = false;
            table.InvalidateSeed();
            FindFirstObjectByType<BlenderScreen>()?.RequestRecenter();
        }

        void PlacementReadiness(string state)
        {
            if (placementReadiness == state) return;
            placementReadiness = state;
            Debug.Log("WORKSPACE_PLACEMENT_READINESS " + state);
        }

        void LateUpdate()
        {
            var camera = Camera.main;
            if (camera == null) return;
            UpdateHeadsetStatus(camera);
            // Place once after head tracking starts. Looking/walking and scene reconnects
            // must not move an already placed model. B/Y explicitly requests a new placement.
            var headPose = new Pose(camera.transform.position, camera.transform.rotation);
            bool xr = XRSettings.enabled || XRSettings.isDeviceActive;
            if (xr)
            {
                var head = InputDevices.GetDeviceAtXRNode(XRNode.Head);
                bool tracked = head.TryGetFeatureValue(UnityEngine.XR.CommonUsages.isTracked, out var tracking) && tracking;
                bool inputPresenceKnown = head.TryGetFeatureValue(UnityEngine.XR.CommonUsages.userPresence, out var inputPresent);
                bool metaReady = OVRPlugin.initialized;
                bool metaPresent = metaReady && OVRPlugin.userPresent;
                bool focused = metaReady && OVRPlugin.hasVrFocus;
                bool worn = (inputPresenceKnown || metaReady) && (!inputPresenceKnown || inputPresent)
                    && (!metaReady || metaPresent);
                bool ready = HeadsetAllowsPlacement(true, tracked, inputPresenceKnown || metaReady, worn, focused);
                PlacementReadiness($"xr=True tracked={tracked} presence_known={inputPresenceKnown || metaReady} worn={worn} vr_focused={focused}");
                if (!ready) { InvalidateUnconfirmedPlacement(); return; }
                // Read the tracked head directly: the camera can still contain its
                // startup transform in the first frame that tracking becomes valid.
                if (!head.TryGetFeatureValue(UnityEngine.XR.CommonUsages.devicePosition, out Vector3 headPosition)
                    || !head.TryGetFeatureValue(UnityEngine.XR.CommonUsages.deviceRotation, out Quaternion headRotation))
                { InvalidateUnconfirmedPlacement(); return; }
                headPose = WorkspaceInteraction.ToWorldPose(camera.transform.parent, new Pose(headPosition, headRotation));
            }
            // A desktop Player (no headset: headless checks, laptop demos) opts in with --desktop and
            // places once its window has focus, like the editor. VR Players keep waiting for the headset.
            else if (!(Application.isEditor || DesktopPlayer) || !Application.isFocused)
            {
                // A Windows VR Player must never commit the desktop/default
                // camera while its XR loader or Link session is still starting.
                PlacementReadiness("xr=False waiting_for_headset=True");
                InvalidateUnconfirmedPlacement();
                return;
            }
            if (placed && !recenterRequested && (table == null || !table.NeedsSeed)) return;
            if (xr && !recenterRequested && !startupFacing.Ready(headPose.rotation * Vector3.forward, true,
                    Time.realtimeSinceStartupAsDouble)) return;

            if (!TryGetDisplayPose(headPose.position, headPose.rotation * Vector3.forward,
                    viewingDistance, belowEyeHeight, out var position, out var rotation)) return;
            // Share the accepted settled head pose with the live screen. Table
            // preview is visible first; model visibility requires explicit Place.
            table.SeedFromHead(headPose.position, headPose.rotation * Vector3.forward);
            placed = true;
            recenterRequested = false;
            PlacementHeadPose = headPose;
            Debug.Log($"HostScene placement: head={headPose.position:F3} forward={headPose.rotation * Vector3.forward:F3} table={root.position:F3} yaw={root.eulerAngles.y:F2}; shared_tracked_head=True readiness=[{placementReadiness}]");
        }

        // Wait until the wearer is looking ahead steadily, rather than capturing
        // the downward/backward orientation while the headset is being put on.
        // Explicit B/Y recenter bypasses this startup-only settling delay.
        public sealed class StartupFacingGate
        {
            double since = -1;
            Vector3 reference;
            public bool Ready(Vector3 gaze, bool trackedAndPresent, double now)
            {
                var flat = Vector3.ProjectOnPlane(gaze, Vector3.up);
                if (!trackedAndPresent || Mathf.Abs(gaze.normalized.y) > 0.6f || flat.sqrMagnitude < 0.01f)
                { since = -1; return false; }
                flat.Normalize();
                if (since < 0 || Vector3.Angle(reference, flat) > 4f)
                { reference = flat; since = now; return false; }
                return now - since >= 0.5;
            }
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
            var screen = FindFirstObjectByType<BlenderScreen>();
            bool screenVisible = screen != null && screen.Visible;
            // Keep host warnings readable without covering the P1 live window.
            statusPanel.transform.localPosition = screenVisible ? new Vector3(0f, -0.62f, 1.4f) : new Vector3(0f, 0.10f, 1f);
            statusPanel.GetComponent<RectTransform>().sizeDelta = screenVisible ? new Vector2(1400f, 130f) : new Vector2(950f, 190f);
            headsetStatus.color = status == Status.Connected ? Color.white : new Color(1f, 0.7f, 0.25f);
            switch (status)
            {
                case Status.Connected:
                    headsetStatus.text = $"Blender connected — revision {revision}\nB / Y: Recenter view";
                    break;
                case Status.NotResponding:
                    headsetStatus.text = "Blender is not responding\nScene is stale — edits disabled";
                    break;
                case Status.ConfigurationError:
                    headsetStatus.text = hostError + "\nConnection not attempted; edits disabled";
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
            if (screen != null)
            {
                screen.SetHostNotice(status == Status.Connected ? "" : headsetStatus.text);
                statusPanel.SetActive(false); // Connection/capture status belongs inside the Blender view.
            }
            else statusPanel.SetActive(true);
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
            if (FindFirstObjectByType<BlenderScreen>() != null) return;
            string stale = haveScene ? "\nShowing the last scene (stale). Edits are disabled." : "";
            string reason = hostError.Length > 0 ? hostError : socketError;
            string text;
            switch (status)
            {
                case Status.Connected: text = $"Connected to {documentName} - revision {revision}"; break;
                case Status.NotResponding: text = "Blender is not responding. Edits are disabled."; break;
                case Status.ConfigurationError: text = hostError + "\nConnection not attempted."; break;
                case Status.VersionMismatch: text = $"This app and the Blender add-on don't match.\n{hostError}"; break;
                case Status.Disconnected: text = $"Disconnected. Reconnecting...{stale}\n{reason}"; break;
                default: text = $"Connecting to Blender at {host}:{port} ...{stale}\n{(link != null && link.SocketOpen ? "" : reason)}"; break;
            }
            if (style == null) style = new GUIStyle(GUI.skin.label) { fontSize = 26 };
            style.normal.textColor = status == Status.Connected ? Color.white : new Color(1f, 0.6f, 0.2f);
            GUI.Label(new Rect(20, 20, 1400, 200), text, style);
            if (GUI.Button(new Rect(20, 230, 300, 48), "Recenter view (B / Y / R)")) RequestRecenter();
        }

        void HandleCore(HostEvent e)
        {
            switch (e.Kind)
            {
                case HostEventKind.Opened: opened = true; socketError = ""; break;
                case HostEventKind.Closed:
                    connected = false; socketError = e.Text;
                    Debug.Log("P2_SCENE_STALE connection_closed; last scene is not current");
                    break;
                case HostEventKind.Welcome:
                    hostError = hostErrorCode = "";
                    documentName = e.Text;
                    break;
                case HostEventKind.Error:
                    hostErrorCode = e.Code;
                    hostError = $"{e.Text} ({e.Code})";
                    Debug.LogWarning("Host error: " + hostError);
                    break;
                case HostEventKind.Warning: Debug.LogWarning("HostScene: " + e.Text); break;
                case HostEventKind.InvalidScene:
                    connected = false;
                    status = Status.NotResponding;
                    link?.Reconnect();
                    break;
                case HostEventKind.Scene:
                    if (!e.Snapshot && (!connected || e.DocumentId != documentId || e.OpenEpoch != openEpoch ||
                        !e.Revision.HasValue || e.Revision < revision || e.Revision > revision + 1))
                    {
                        Debug.LogWarning("HostScene: ignored an update without a matching fresh snapshot");
                        connected = false;
                        status = Status.NotResponding;
                        link?.Reconnect();
                        break;
                    }
                    bool missingMesh = false;
                    foreach (var record in e.Objects)
                        if (!record.HasMesh && (e.Snapshot || !objects.ContainsKey(record.Id))) missingMesh = true;
                    if (missingMesh)
                    {
                        Debug.LogWarning("HostScene: incomplete object mesh; requesting a fresh snapshot");
                        connected = false;
                        status = Status.NotResponding;
                        link?.Reconnect();
                        break;
                    }
                    if (e.Snapshot)
                    {
                        // Reuse objects/arrangements on reconnect to the same native
                        // document. Never reuse offsets in a new document epoch.
                        if (documentId != e.DocumentId || openEpoch != e.OpenEpoch)
                        {
                            FindFirstObjectByType<WorkspaceInteraction>()?.CancelGrabs();
                            ClearScene();
                            table.RequirePlacement();
                            table.RestoreActualSize();
                            InvalidateUnconfirmedPlacement();
                        }
                        documentId = e.DocumentId;
                        openEpoch = e.OpenEpoch;
                        var incoming = new HashSet<string>();
                        foreach (var record in e.Objects) incoming.Add(record.Id);
                        foreach (var id in new List<string>(objects.Keys))
                            if (!incoming.Contains(id)) Remove(id);
                    }
                    if (e.Revision.HasValue) revision = e.Revision.Value;
                    foreach (var id in e.Removed) Remove(id);
                    bool applied = true;
                    foreach (var r in e.Objects)
                    {
                        try { ApplyObject(r); }
                        catch (System.Exception ex) { applied = false; Debug.LogWarning($"HostScene: couldn't draw {r.Id}: {ex.Message}"); }
                    }
                    if (!applied)
                    {
                        connected = false;
                        status = Status.NotResponding;
                        link?.Reconnect();
                    }
                    else if (e.Snapshot) { connected = haveScene = true; status = Status.Connected; }
                    Debug.Log($"P2_SCENE_APPLIED snapshot={e.Snapshot} revision={revision} objects={objects.Count} removed={e.Removed.Count} current={connected}");
                    break;
            }
            HostEventReceived?.Invoke(e);
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
                go = new GameObject(r.Id, typeof(MeshFilter), typeof(MeshRenderer), typeof(MeshCollider), typeof(WorkspaceObjectView));
                go.transform.SetParent(root, false);
                go.GetComponent<MeshRenderer>().sharedMaterial = ObjectMaterial;
                objects[r.Id] = go;
            }
            go.name = r.Name;
            var view = go.GetComponent<WorkspaceObjectView>();
            view.ObjectId = r.Id;
            view.NativeParentId = r.ParentId;
            view.Generation = r.Generation;
            go.SetActive(r.Visible);

            // Wire transforms are world space, so objects stay flat under the display root.
            if (r.HasTransform)
            {
                view.SetNativePose(r.Position, r.Rotation, r.Scale);
                Debug.Log($"HostScene object {r.Name}: local={r.Position:F4} world={go.transform.position:F4} root={root.position:F3}");
            }

            var mf = go.GetComponent<MeshFilter>();
            var mr = go.GetComponent<MeshRenderer>();
            if (r.HasMesh)
            {
                go.GetComponent<MeshCollider>().sharedMesh = null;
                if (mf.sharedMesh != null) ReleaseObject(mf.sharedMesh);
                mf.sharedMesh = r.Mesh != null ? BuildMesh(r.Mesh, r.Name) : null;
                go.GetComponent<MeshCollider>().sharedMesh = mf.sharedMesh;
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

        public WorkspaceObjectView PickObject(Ray ray, out float distance)
        {
            distance = 4f;
            WorkspaceObjectView picked = null;
            foreach (var go in objects.Values)
            {
                if (go == null || !go.activeInHierarchy) continue;
                var collider = go.GetComponent<MeshCollider>();
                if (collider != null && collider.sharedMesh != null && collider.Raycast(ray, out var hit, distance))
                {
                    distance = hit.distance;
                    picked = go.GetComponent<WorkspaceObjectView>();
                }
            }
            return picked;
        }

        public void ResetObjectArrangement()
        {
            foreach (var go in objects.Values) if (go != null) go.GetComponent<WorkspaceObjectView>()?.ResetArrangement();
            table.ResetView();
            RequestRecenter();
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
            objects.Remove(id);
            if (go == null) return; // Unity may destroy child objects before OnDestroy during exit.
            var mf = go.GetComponent<MeshFilter>();
            var collider = go.GetComponent<MeshCollider>();
            if (collider != null) collider.sharedMesh = null;
            if (mf != null && mf.sharedMesh != null) ReleaseObject(mf.sharedMesh);
            ReleaseObject(go);
        }

        void ClearScene()
        {
            foreach (var id in new List<string>(objects.Keys)) Remove(id);
        }
    }
}

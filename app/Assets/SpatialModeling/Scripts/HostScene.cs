using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpatialModeling
{
    // P0 (#11): connects to the host add-on (or the fake host), draws the scene it sends,
    // and shows the connection state from the contract's table (contracts/README.md, Connecting).
    [RequireComponent(typeof(TablePlacement))]
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
        [Tooltip("URP Lit material shared by every object; each object's color is set per renderer.")]
        [SerializeField] Material objectMaterial;

        enum Status { Connecting, Connected, NotResponding, Disconnected, VersionMismatch }

        const long NotRespondingMs = 6000;
        static readonly int BaseColorId = Shader.PropertyToID("_BaseColor");

        readonly Dictionary<string, GameObject> objects = new Dictionary<string, GameObject>();
        public Transform Placement => root;
        public int ObjectCount => objects.Count;
        public bool IsCurrent => status == Status.Connected;
        public string ConnectionText => status == Status.Connected
            ? $"Connected to {documentName} — revision {revision}"
            : $"{status} — last scene is stale; native edits disabled";
        string documentId = "", openEpoch = "";
        TablePlacement table;
        HostLink link;
        Transform root;
        MaterialPropertyBlock block;
        Material fallbackMaterial;
        GUIStyle style;

        bool opened;        // a socket has opened at least once
        bool connected;     // welcome and snapshot have arrived on this connection
        bool haveScene;     // we are showing a scene, current or stale
        string socketError = "", hostError = "", hostErrorCode = "", documentName = "";
        long revision;
        Status status = Status.Connecting;

        static void ReleaseObject(UnityEngine.Object value)
        {
            if (value == null) return;
            if (Application.isPlaying) Destroy(value);
            else DestroyImmediate(value);
        }

        void Awake()
        {
            root = new GameObject("HostSceneRoot").transform;
            root.position = rootPosition;
            root.localScale = Vector3.one * displayScale;
            block = new MaterialPropertyBlock();
            table = GetComponent<TablePlacement>() ?? gameObject.AddComponent<TablePlacement>();
            table.Initialize(root);
        }

        void OnEnable()
        {
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
            link?.Stop();   // its thread exits and posts nothing more, so a re-enable can't run two
            link = null;
            connected = false;
        }

        void OnDestroy()
        {
            ClearScene();
            if (root != null) ReleaseObject(root.gameObject);
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
        }

        internal void Handle(HostEvent e)
        {
            switch (e.Kind)
            {
                case HostEventKind.Opened: opened = true; socketError = ""; break;
                case HostEventKind.Closed: connected = false; socketError = e.Text; break;
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
                    link?.Reconnect();
                    break;
                case HostEventKind.Scene:
                    if (!e.Snapshot && (!connected || e.DocumentId != documentId || e.OpenEpoch != openEpoch ||
                        !e.Revision.HasValue || e.Revision < revision || e.Revision > revision + 1))
                    {
                        Debug.LogWarning("HostScene: ignored an update without a matching fresh snapshot");
                        connected = false;
                        link?.Reconnect();
                        break;
                    }
                    if (e.Snapshot)
                    {
                        // Reuse existing IDs and per-part view offsets on reconnect.
                        // A different native document requires placement confirmation.
                        if (documentId != e.DocumentId)
                        {
                            ClearScene();
                            table.RequirePlacement();
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
            }

            var mf = go.GetComponent<MeshFilter>();
            var mr = go.GetComponent<MeshRenderer>();
            if (r.HasMesh)
            {
                var collider = go.GetComponent<MeshCollider>();
                collider.sharedMesh = null;
                if (mf.sharedMesh != null) ReleaseObject(mf.sharedMesh);
                mf.sharedMesh = r.Mesh != null ? BuildMesh(r.Mesh, r.Name) : null;
                collider.sharedMesh = mf.sharedMesh;
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
            var collider = go.GetComponent<MeshCollider>();
            if (collider != null) collider.sharedMesh = null;
            if (mf != null && mf.sharedMesh != null) ReleaseObject(mf.sharedMesh);
            ReleaseObject(go);
            objects.Remove(id);
        }

        void ClearScene()
        {
            foreach (var id in new List<string>(objects.Keys)) Remove(id);
        }
    }
}

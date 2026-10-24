using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // Viewer-only wire bounds and owner labels. Never changes native or display mesh materials.
    public sealed class NativeOwnershipOverlay : MonoBehaviour
    {
        public readonly struct DisplayTarget
        {
            public readonly string Id;
            public readonly Bounds WorldBounds;
            public DisplayTarget(string id, Bounds bounds) { Id = id; WorldBounds = bounds; }
        }
        // Additional rendered data can participate without becoming generic editable objects.
        public Func<IEnumerable<DisplayTarget>> AdditionalTargets;
        public bool HasVisibleTarget(string id) => overlays.TryGetValue(id, out var o)
            && o.go.activeInHierarchy && o.line.enabled && o.line.gameObject.activeInHierarchy && o.label.isActiveAndEnabled;
        sealed class Overlay
        {
            public GameObject go;
            public LineRenderer line;
            public Text label;
            public Transform labelRoot;
        }
        WorkspaceNativeMenu menu;
        HostScene scene;
        Material material;
        readonly Dictionary<string, Overlay> overlays = new Dictionary<string, Overlay>();
        static readonly int[] Edges = {0,1,1,3,3,2,2,0,0,4,4,5,5,1,5,7,7,3,7,6,6,2,6,4};

        void OnEnable()
        {
            menu = GetComponent<WorkspaceNativeMenu>();
            scene = FindAnyObjectByType<HostScene>();
            if (scene == null || scene.ObjectDisplayMaterial == null)
            { Debug.LogError("P3 ownership overlay needs the scene-referenced display material"); enabled = false; return; }
            material = new Material(scene.ObjectDisplayMaterial);
            material.color = new Color(1f, 0.18f, 0.63f);
            menu.SettingsExtras = Settings;
            menu.OwnershipNotice = Notice;
        }
        void Settings(WorkspaceNativeMenu m)
        {
            m.ButtonAt("Exclusive", 24, 485, 425, () => { m.Session.Mode = "exclusive"; m.Refresh(); });
            m.ButtonAt("Shared", 485, 485, 425, () => { m.Session.Mode = "shared"; m.Refresh(); });
            m.ContentLabel("Exclusive reserves the document during Apply.\nShared reserves the target and related data during Apply.", 562, 72);
        }
        string Notice()
        {
            if (!menu.Session.Ready || !menu.Session.SceneCurrent)
                return "Editing mode: " + menu.Session.Mode + " · Ownership unknown while the native scene is stale";
            var names = new HashSet<string>();
            foreach (JObject lease in menu.Session.Leases)
                if ((string)lease["owner"]?["actor_id"] != menu.Session.ActorId)
                    names.Add((string)lease["owner"]?["name"] ?? "Another participant");
            string result = "Editing mode: " + menu.Session.Mode;
            if (names.Count > 0)
                result += (menu.Session.Busy || menu.Session.Draft != null ? " · Two people are editing: " : " · Editing: ") + string.Join(", ", names);
            return result;
        }
        void LateUpdate()
        {
            if (scene == null || menu == null) return;
            var wanted = new HashSet<string>();
            if (menu.Session.Ready && menu.Session.SceneCurrent) foreach (var view in scene.ObjectViews)
            {
                if (view == null || !view.gameObject.activeInHierarchy) continue;
                string owner = menu.Session.ConflictOwner(view.ObjectId);
                if (owner == null) continue;
                var filter = view.GetComponent<MeshFilter>();
                if (filter == null || filter.sharedMesh == null) continue;
                wanted.Add(view.ObjectId);
                if (!overlays.TryGetValue(view.ObjectId, out var o)) overlays[view.ObjectId] = o = Create();
                var b = filter.sharedMesh.bounds;
                var points = new Vector3[8];
                for (int i = 0; i < 8; i++) points[i] = view.transform.TransformPoint(b.center + Vector3.Scale(b.extents * 1.02f,
                    new Vector3((i & 1) == 0 ? -1 : 1, (i & 2) == 0 ? -1 : 1, (i & 4) == 0 ? -1 : 1)));
                // A continuous walk follows every box edge without filling faces.
                var walk = new Vector3[Edges.Length]; for (int i = 0; i < Edges.Length; i++) walk[i] = points[Edges[i]];
                o.line.positionCount = walk.Length; o.line.SetPositions(walk);
                var bounds = view.GetComponent<Renderer>().bounds;
                o.labelRoot.position = bounds.center + Vector3.up * (bounds.extents.y + 0.03f);
                if (Camera.main != null) o.labelRoot.rotation = Quaternion.LookRotation(o.labelRoot.position - Camera.main.transform.position, Vector3.up);
                o.label.text = owner + " is editing";
            }
            if (menu.Session.Ready && menu.Session.SceneCurrent && AdditionalTargets != null)
                foreach (var target in AdditionalTargets())
                {
                    string owner = menu.Session.ConflictOwner(target.Id);
                    if (owner == null) continue;
                    wanted.Add(target.Id);
                    if (!overlays.TryGetValue(target.Id, out var o)) overlays[target.Id] = o = Create();
                    var bounds = target.WorldBounds;
                    var extents = bounds.extents + Vector3.one * 0.003f;
                    var points = new Vector3[8];
                    for (int i = 0; i < 8; i++) points[i] = bounds.center + Vector3.Scale(extents,
                        new Vector3((i & 1) == 0 ? -1 : 1, (i & 2) == 0 ? -1 : 1, (i & 4) == 0 ? -1 : 1));
                    var walk = new Vector3[Edges.Length]; for (int i = 0; i < Edges.Length; i++) walk[i] = points[Edges[i]];
                    o.line.positionCount = walk.Length; o.line.SetPositions(walk);
                    o.labelRoot.position = bounds.center + Vector3.up * (extents.y + 0.03f);
                    if (Camera.main != null) o.labelRoot.rotation = Quaternion.LookRotation(o.labelRoot.position - Camera.main.transform.position, Vector3.up);
                    o.label.text = owner + " is editing";
                }
            var remove = new List<string>(); foreach (var id in overlays.Keys) if (!wanted.Contains(id)) remove.Add(id);
            foreach (var id in remove) { overlays[id].go.SetActive(false); Destroy(overlays[id].go); overlays.Remove(id); }
        }
        Overlay Create()
        {
            var o = new Overlay { go = new GameObject("Temporary ownership overlay") };
            o.line = o.go.AddComponent<LineRenderer>(); o.line.sharedMaterial = material;
            o.line.useWorldSpace = true; o.line.startWidth = o.line.endWidth = 0.0015f;
            var label = new GameObject("Actual owner", typeof(RectTransform), typeof(Canvas));
            label.transform.SetParent(o.go.transform, false); o.labelRoot = label.transform;
            label.GetComponent<Canvas>().renderMode = RenderMode.WorldSpace;
            label.GetComponent<RectTransform>().sizeDelta = new Vector2(600, 70); label.transform.localScale = Vector3.one * 0.00045f;
            var text = new GameObject("Owner", typeof(RectTransform), typeof(Text)); text.transform.SetParent(label.transform, false);
            var r = text.GetComponent<RectTransform>(); r.anchorMin = Vector2.zero; r.anchorMax = Vector2.one; r.offsetMin = r.offsetMax = Vector2.zero;
            o.label = text.GetComponent<Text>(); o.label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            o.label.fontSize = 30; o.label.alignment = TextAnchor.MiddleCenter; o.label.color = new Color(1, 0.28f, 0.69f);
            return o;
        }
        void OnDisable()
        {
            foreach (var o in overlays.Values) if (o.go != null) Destroy(o.go);
            overlays.Clear();
            if (material != null) Destroy(material);
            if (menu != null) { menu.SettingsExtras = null; menu.OwnershipNotice = null; }
        }
    }
}

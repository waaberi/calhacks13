using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // Controls bind to native entity/constraint IDs. Lines below render only host-solved coordinates.
    public sealed class NativeSketchEditor : MonoBehaviour
    {
        WorkspaceNativeMenu menu;
        HostScene scene;
        Material material;
        NativeOwnershipOverlay ownership;
        readonly Dictionary<string, GameObject> geometry = new Dictionary<string, GameObject>();
        readonly Dictionary<string, JObject> validSketches = new Dictionary<string, JObject>();
        int entityA, entityB = 1, dimension;
        string shown = "";
        Text details;
        JObject Sketch => menu.Session.Sketches.TryGetValue(menu.Session.SelectedId, out var s) ? s : null;

        void OnEnable()
        {
            menu = GetComponent<WorkspaceNativeMenu>(); scene = FindAnyObjectByType<HostScene>();
            if (scene == null || scene.ObjectDisplayMaterial == null)
            { Debug.LogError("P3 solved sketch display needs the scene-referenced display material"); enabled = false; return; }
            material = new Material(scene.ObjectDisplayMaterial);
            material.color = new Color(0.2f, 0.95f, 0.9f);
            menu.BuildSketchPage = _ => Home();
            menu.Session.Changed += Changed;
            ownership = GetComponent<NativeOwnershipOverlay>();
            if (ownership != null) ownership.AdditionalTargets = OwnershipTargets;
        }
        IEnumerable<NativeOwnershipOverlay.DisplayTarget> OwnershipTargets()
        {
            foreach (var pair in geometry)
            {
                if (pair.Value == null || !pair.Value.activeInHierarchy) continue;
                bool found = false; Bounds bounds = default;
                foreach (var line in pair.Value.GetComponentsInChildren<LineRenderer>())
                    if (line.isActiveAndEnabled && line.positionCount > 1)
                    { if (!found) { bounds = line.bounds; found = true; } else bounds.Encapsulate(line.bounds); }
                if (found) yield return new NativeOwnershipOverlay.DisplayTarget(pair.Key, bounds);
            }
        }
        void Changed()
        {
            if (details != null && menu.Page == "sketch") details.text = Describe();
            // Native geometry is retained while stale but never described as live.
            string current = new JArray(menu.Session.Sketches.Values).ToString();
            if (shown != current) { shown = current; RebuildGeometry(); }
        }
        public void Home()
        {
            if (!menu.Session.SketchAvailable) { menu.ShowError("Sketch is disabled until Blender confirms its native CAD adapter is available"); return; }
            if (Sketch == null) menu.CycleTarget(true);
            menu.ClearPage("sketch", "Sketch · native constrained CAD");
            menu.ButtonAt("Next sketch", 24, 0, 275, () => { menu.CycleTarget(true); entityA = 0; entityB = 1; dimension = 0; Home(); });
            menu.ButtonAt("New sketch", 333, 0, 275, Planes);
            menu.ButtonAt("Back", 642, 0, 275, menu.Home);
            menu.ButtonAt("Line", 24, 85, 275, () => Shape("line"));
            menu.ButtonAt("Rectangle", 333, 85, 275, () => Shape("rectangle"));
            menu.ButtonAt("Circle", 642, 85, 275, () => Shape("circle"));
            menu.ButtonAt("Next entity A", 24, 170, 275, () => { entityA++; Changed(); });
            menu.ButtonAt("Next entity B", 333, 170, 275, () => { entityB++; Changed(); });
            menu.ButtonAt("Next dimension", 642, 170, 275, () => { dimension++; Changed(); });
            details = menu.ContentLabel(Describe(), 255, 150);
            string[] kinds = { "coincident", "horizontal", "vertical", "fixed", "distance", "angle", "diameter" };
            for (int i = 0; i < kinds.Length; i++)
            {
                string kind = kinds[i]; menu.ButtonAt(kind, 24 + (i % 3) * 309, 420 + (i / 3) * 85, 275, () => Constrain(kind));
            }
            menu.ButtonAt("Edit dimension", 333, 590, 584, EditDimension);
            menu.Refresh();
        }
        string Describe()
        {
            var sketch = Sketch;
            if (sketch == null) return "No native sketch selected. Choose New sketch and a plane.";
            string status = (string)sketch["solver"]?["status"];
            string label = status == "fully_constrained" ? "Fully constrained" : status == "conflicting" ? "Conflicting" : "Under-constrained";
            string rejected = (string)menu.Session.LastReceipt?["target"] == menu.Session.SelectedId
                && (string)menu.Session.LastReceipt?["solver"]?["status"] == "conflicting" ? " · Last attempt conflicting; valid result retained" : "";
            return label + " · freedom " + (sketch["solver"]?["dof"]?.ToString() ?? "unknown") + rejected
                + "\nA: " + EntityName(Entity(entityA)) + " · B: " + EntityName(Entity(entityB))
                + "\nDimension: " + DimensionLabel(Dimension());
        }
        JObject Entity(int index)
        {
            var a = Sketch?["entities"] as JArray;
            return a != null && a.Count > 0 ? a[index % a.Count] as JObject : null;
        }
        internal void SmokeChoose(string first, string second = null, string constraint = null)
        {
            if (Sketch?["entities"] is JArray a) for (int i = 0; i < a.Count; i++)
            { if ((string)a[i]["id"] == first) entityA = i; if ((string)a[i]["id"] == second) entityB = i; }
            int index = 0;
            if (Sketch?["constraints"] is JArray c) foreach (var d in c)
                if (d["value"] != null) { if ((string)d["id"] == constraint) dimension = index; index++; }
            Changed();
        }
        static string EntityName(JObject entity)
        {
            if (entity == null) return "None";
            string id = (string)entity["id"] ?? "";
            return (string)entity["kind"] + " " + id.Substring(0, Math.Min(id.Length, 6));
        }
        JObject Dimension()
        {
            var dims = new List<JObject>();
            if (Sketch?["constraints"] is JArray constraints) foreach (JObject c in constraints) if (c["value"] != null) dims.Add(c);
            return dims.Count > 0 ? dims[dimension % dims.Count] : null;
        }
        static string DimensionLabel(JObject d)
        {
            if (d == null) return "None";
            bool angle = (string)d["kind"] == "angle";
            double value = (double)d["value"] * (angle ? 180 / Math.PI : 1000);
            return (string)d["kind"] + " " + value.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture) + (angle ? "°" : " mm");
        }
        void Planes()
        {
            menu.ClearPage("sketch-plane", "Choose native sketch plane");
            var planes = new[] { "XY", "XZ", "YZ" };
            for (int i = 0; i < planes.Length; i++)
            {
                string plane = planes[i]; menu.ButtonAt(plane, 24 + i * 309, 20, 275, () =>
                {
                    if (!menu.Session.BeginDraft("sketch.create", new JObject { ["plane"] = plane }, false)) return;
                    menu.ClearPage("sketch-create", "Create sketch on " + plane);
                    menu.ContentLabel("Apply creates an editable native sketch. Geometry appears after Blender solves and confirms it.", 20, 160);
                    Confirm(() => (JObject)menu.Session.Draft["args"].DeepClone());
                });
            }
            menu.ButtonAt("Back", 24, 610, 886, Home);
        }
        bool Draft(string op, string title)
        {
            if (Sketch == null) { menu.ShowError("Select a native sketch first"); return false; }
            if (!menu.Session.BeginDraft(op, new JObject(), true)) return false;
            menu.ClearPage("sketch-tool", title);
            return true;
        }
        void Shape(string kind)
        {
            if (!Draft("sketch.add_" + kind, "Create " + kind + " · sketch coordinates in mm")) return;
            menu.ContentLabel(kind == "circle" ? "Center U / V and radius (mm)" : "Start/corner U / V and end/opposite U / V (mm)", 0, 65);
            menu.Field("U", "0", 24, 75); menu.Field("V", "0", 333, 75);
            if (kind == "circle") menu.Field("Radius", "10", 642, 75);
            else { menu.Field("End U", "100", 24, 175); menu.Field("End V", "60", 333, 175); }
            menu.Keypad(300);
            Confirm(() => kind == "circle" ? new JObject { ["center"] = menu.Values(0, 2, 0.001), ["radius"] = menu.Number(2) * 0.001 }
                : kind == "line" ? new JObject { ["start"] = menu.Values(0, 2, 0.001), ["end"] = menu.Values(2, 2, 0.001) }
                : new JObject { ["corner"] = menu.Values(0, 2, 0.001), ["opposite"] = menu.Values(2, 2, 0.001) });
        }
        void Constrain(string kind)
        {
            var a = Entity(entityA); var b = Entity(entityB);
            if (a == null) { menu.ShowError("Choose an entity before constraining it"); return; }
            bool pair = kind == "coincident" || kind == "angle";
            if (pair && (b == null || (string)b["id"] == (string)a["id"])) { menu.ShowError("Choose two different native entities"); return; }
            var entities = pair ? new JArray(a["id"], b["id"]) : new JArray(a["id"]);
            if (!Draft("sketch.constrain", "Constraint · " + kind)) return;
            bool numeric = kind == "distance" || kind == "diameter" || kind == "angle";
            menu.ContentLabel(EntityName(a) + (pair ? " + " + EntityName(b) : "") + "\n" + (numeric ? (kind == "angle" ? "Angle in degrees" : "Length / distance / diameter in mm") : "Native geometric rule; Blender validates entity types and solves."), 0, 150);
            if (numeric) { menu.Field("Value", kind == "angle" ? "90" : "10", 24, 170); menu.Keypad(300); }
            Confirm(() => { var args = new JObject { ["kind"] = kind, ["entities"] = entities.DeepClone() }; if (numeric) args["value"] = menu.Number(0) * (kind == "angle" ? Math.PI / 180 : 0.001); return args; });
        }
        void EditDimension()
        {
            var d = Dimension();
            if (d == null) { menu.ShowError("Select an existing native dimension first"); return; }
            if (!Draft("sketch.set_dimension", "Edit native dimension")) return;
            bool angle = (string)d["kind"] == "angle";
            string id = (string)d["id"];
            menu.ContentLabel(DimensionLabel(d) + "\nNew " + (angle ? "degrees" : "millimeters") + " drive the native solver.", 0, 140);
            menu.Field("Value", ((double)d["value"] * (angle ? 180 / Math.PI : 1000)).ToString("0.###", System.Globalization.CultureInfo.InvariantCulture), 24, 170);
            menu.Keypad(300);
            Confirm(() => new JObject { ["constraint"] = id, ["value"] = menu.Number(0) * (angle ? Math.PI / 180 : 0.001) });
        }
        void Confirm(Func<JObject> args)
        {
            menu.ButtonAt("Apply", 24, 610, 425, () =>
            {
                try { if (menu.Session.Draft == null) { menu.ShowError("Draft expired; choose the tool again"); return; } menu.Session.Draft["args"] = args(); menu.Session.Apply(); }
                catch (FormatException e) { menu.ShowError(e.Message); }
            });
            menu.ButtonAt("Cancel / Back", 485, 610, 425, () => { menu.Session.Cancel(); Home(); });
        }
        void RebuildGeometry()
        {
            foreach (var pair in menu.Session.Sketches)
                if ((string)pair.Value["solver"]?["status"] != "conflicting") validSketches[pair.Key] = (JObject)pair.Value.DeepClone();
            var removed = new List<string>(); foreach (var id in validSketches.Keys) if (!menu.Session.Sketches.ContainsKey(id)) removed.Add(id);
            foreach (var id in removed) validSketches.Remove(id);
            foreach (var go in geometry.Values) if (go != null) Destroy(go);
            geometry.Clear();
            if (scene == null || scene.Placement == null) return;
            foreach (var pair in validSketches)
            {
                var sketch = pair.Value;
                // Refused constraints do not replace these records; the host's last valid scene remains visible.
                if ((string)sketch["solver"]?["status"] == "conflicting") continue;
                var plane = sketch["plane"] as JObject; if (plane == null) continue;
                var loc = plane["location"] as JArray; var rot = plane["rotation"] as JArray; if (loc == null || rot == null) continue;
                var root = new GameObject("Native solved sketch " + (string)sketch["name"]);
                root.transform.SetParent(scene.Placement, false);
                root.transform.localPosition = BlenderFrame.Point((float)loc[0], (float)loc[1], (float)loc[2]);
                root.transform.localRotation = BlenderFrame.Rotation((float)rot[0], (float)rot[1], (float)rot[2], (float)rot[3]);
                geometry[pair.Key] = root;
                var points = new Dictionary<string, Vector2>();
                if (!(sketch["entities"] is JArray entities)) continue;
                foreach (JObject e in entities) if ((string)e["kind"] == "point" && e["at"] is JArray at) points[(string)e["id"]] = new Vector2((float)at[0], (float)at[1]);
                foreach (JObject e in entities)
                {
                    string kind = (string)e["kind"]; Vector3[] vertices = null;
                    if (kind == "line" && e["points"] is JArray endpoints && points.TryGetValue((string)endpoints[0], out var a) && points.TryGetValue((string)endpoints[1], out var b))
                        vertices = new[] { BlenderFrame.Point(a.x, a.y, 0), BlenderFrame.Point(b.x, b.y, 0) };
                    if (kind == "circle" && points.TryGetValue((string)e["center"], out var center))
                    {
                        vertices = new Vector3[65]; float radius = (float)e["radius"];
                        for (int i = 0; i < vertices.Length; i++) { float t = i * Mathf.PI * 2 / 64; vertices[i] = BlenderFrame.Point(center.x + Mathf.Cos(t) * radius, center.y + Mathf.Sin(t) * radius, 0); }
                    }
                    if (vertices == null) continue;
                    var line = new GameObject("Solved " + kind).AddComponent<LineRenderer>(); line.transform.SetParent(root.transform, false);
                    line.sharedMaterial = material; line.useWorldSpace = false; line.positionCount = vertices.Length; line.SetPositions(vertices);
                    line.startWidth = line.endWidth = 0.0004f;
                }
            }
        }
        void OnDisable()
        {
            if (ownership != null) ownership.AdditionalTargets = null;
            if (menu != null) { menu.Session.Changed -= Changed; menu.BuildSketchPage = null; }
            foreach (var go in geometry.Values) if (go != null) Destroy(go); geometry.Clear();
            if (material != null) Destroy(material);
        }
    }
}

using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.XR;

namespace SpatialModeling
{
    // Native Blender owns tools, geometry, permissions and history. This adapter
    // only picks base topology and draws a disposable orange controller draft.
    public sealed class DirectModelEditing : MonoBehaviour
    {
        public bool Active { get; private set; }
        public bool Gesturing => held;
        public event Action<string> SelectionCommitted;
        public string Notice { get; private set; } = "Choose Edit model, then a tool in Blender";
        public string ContextLabel
        {
            get
            {
                var m = drawing?.NativeState["model_edit"] as JObject;
                if (drawing == null || !drawing.NativeStateCurrent) return "Waiting for current Blender tool state";
                if ((bool?)m?["available"] != true) return (string)m?["reason"] ?? "Direct tool unavailable; native 2D editing remains available";
                return ((string)m["mode"] == "OBJECT" ? "Object" : (string)m["component"]) + " · " + ((string)m["native_tool"] ?? "").Replace("builtin.", "")
                    + " · trigger + aim: native edit · release: one Undo · grip: arrange";
            }
        }

        HostScene scene;
        PreviewInteraction preview;
        PreviewSpatialDrawing drawing;
        WorkspaceObjectView target;
        JObject frozenModel;
        string frozenContext, frozenIdentity, objectId, ownRequestId;
        long generation, revision;
        int[] indices;
        readonly List<int> vertices = new List<int>();
        readonly Dictionary<int, Vector3> nativePoints = new Dictionary<int, Vector3>();
        Matrix4x4 nativeToDisplay;
        Quaternion displayRotation;
        Vector3 startPoint, currentPoint, pivot;
        Ray initialRay;
        float depth, pendingAt;
        bool held, moved, waiting, released, submitted;
        int gesture;
        XRNode hand;
        JObject delta;
        GameObject ghost;
        Material ghostMaterial;
        readonly List<LineRenderer> lines = new List<LineRenderer>();

        public void Initialize(HostScene host, PreviewInteraction owner, PreviewSpatialDrawing native)
        {
            if (drawing != null) drawing.BeforeNativeSessionMessage -= BeforeMessage;
            scene = host; preview = owner; drawing = native;
            if (drawing != null) drawing.BeforeNativeSessionMessage += BeforeMessage;
        }
        public void SetActive(bool enabled)
        {
            if (!enabled) Cancel("Arrange space · grip arranges the display; native preview editing remains available");
            Active = enabled;
            if (drawing != null) drawing.DirectModelToolsActive = enabled;
            if (enabled) Notice = "Choose Move / Rotate / Scale in Blender, then trigger and aim at the floating model";
        }
        void OnDisable() => Cancel("Direct edit cancelled because input is unavailable");
        void OnDestroy()
        {
            if (drawing != null) drawing.BeforeNativeSessionMessage -= BeforeMessage;
            ClearGhost();
            if (ghostMaterial != null) ReleaseObject(ghostMaterial);
        }
        void Update()
        {
            if ((held && moved) || submitted)
            {
                if (submitted && drawing.Session.NativeCommandExecuting)
                {
                    if (Time.unscaledTime - pendingAt > 10f)
                    { drawing.Session.Timeout(); submitted = false; ClearGhost(); Notice = drawing.Session.Notice; }
                    return;
                }
                if (submitted && !drawing.Session.Busy)
                {
                    var receipt = drawing.Session.LastReceipt;
                    if (receipt != null && (string)receipt["request_id"] == ownRequestId && (string)receipt["outcome"] == "applied")
                    {
                        string finalId = (string)receipt["selection"]?["id"];
                        if (!string.IsNullOrEmpty(finalId))
                        {
                            drawing.Session.Select(finalId);
                            FindFirstObjectByType<VoiceUiAdapter>()?.SelectObject(finalId);
                            SelectionCommitted?.Invoke(finalId);
                        }
                    }
                    submitted = false; ownRequestId = null; ClearGhost(); Notice = drawing.Session.Notice; return;
                }
                if (!ContextCurrent()) Cancel("Blender document, geometry, tool or placement changed; local edit cancelled");
                else if (submitted && drawing.Session.Busy && Time.unscaledTime - pendingAt > 10f)
                { drawing.Session.Timeout(); submitted = false; ClearGhost(); Notice = drawing.Session.Notice; }
                else if (submitted && !drawing.Session.Busy)
                { submitted = false; ClearGhost(); Notice = drawing.Session.Notice; }
            }
        }
        void BeforeMessage(JObject message)
        {
            if (!held && !submitted) return;
            string type = (string)message["type"];
            var payload = message["payload"] as JObject;
            // Cancel an acquisition before NativeEditSession can send on a late grant.
            if (type == "lease.granted" && !ContextCurrent()) Cancel("Native tool context changed before permission arrived");
            if (type == "welcome" || type == "connection.closed") Cancel("Blender connection changed; local edit cancelled");
            if ((type == "scene.snapshot" || type == "scene.update") && payload != null)
            {
                bool changed = false;
                if (payload["removed"] is JArray removed) foreach (var id in removed) changed |= (string)id == objectId;
                if (payload["objects"] is JArray objects) foreach (JObject obj in objects)
                    if ((string)obj["id"] == objectId && (long?)obj["generation"] != generation) changed = true;
                // A committed update is the expected end of our submitted edit;
                // do not cancel its receipt or mistake its new geometry for failure.
                if (changed && (!submitted || drawing.Session.AwaitingPermission)) Cancel("Native target changed during the gesture; local preview discarded");
                if (changed && submitted && !drawing.Session.Busy) ClearGhost();
            }
        }
        string Identity() => drawing?.Session.RequestIdentity?.ToString(Newtonsoft.Json.Formatting.None) ?? "";
        static string Context(JObject model)
        {
            if (model == null) return "";
            var value = new JObject();
            foreach (string key in new[] { "available", "reason", "native_tool", "mode", "component", "active_object_id", "generation", "topology_token" })
                value[key] = model[key]?.DeepClone();
            return value.ToString(Newtonsoft.Json.Formatting.None);
        }
        bool ContextCurrent()
        {
            if (!Active || scene == null || !scene.IsCurrent || !scene.DisplayPlacementReady || target == null
                || !target.gameObject.activeInHierarchy || drawing == null || !drawing.NativeStateCurrent
                || drawing.NativeModalActive || Identity() != frozenIdentity || target.Generation != generation
                || Context(drawing.NativeState["model_edit"] as JObject) != frozenContext) return false;
            return DirectModelEditMath.SameMatrix(nativeToDisplay, DirectModelEditMath.NativeToDisplay(target));
        }

        // Called by the existing stabilized preview route. Grips always yield to
        // the accepted arrange mapping. Nothing here reads a raw controller pose.
        public bool RouteHand(XRNode inputHand, Ray ray, bool trigger, bool pressed, bool grip,
            Vector2 axis, float nearest, out float distance)
        {
            distance = 0;
            if (!Active || scene == null || drawing == null) return false;
            if (held)
            {
                if (inputHand != hand) return false;
                distance = depth;
                if (grip) { Cancel("Grip arranges the model; direct draft cancelled"); return false; }
                currentPoint = ray.GetPoint(depth);
                if (trigger)
                {
                    if (Mathf.Abs(axis.y) > .2f)
                    { depth = Mathf.Max(.08f, depth + axis.y * Time.unscaledDeltaTime * .5f); currentPoint = ray.GetPoint(depth); }
                    if (!moved && Vector3.Distance(currentPoint, startPoint) >= .003f) BeginMovement();
                    if (moved && !waiting && !submitted) UpdateDraft(ray);
                    return true;
                }
                released = true;
                if (!moved)
                {
                    string selected = objectId; Cancel("Trigger selected the native object without moving it");
                    FindFirstObjectByType<VoiceUiAdapter>()?.SelectControllerObject(selected);
                    return true;
                }
                if (waiting) { Cancel("Released before Blender input cleanup finished; no edit sent. Trigger again when ready"); return true; }
                if (!ContextCurrent() || !drawing.NativeCommandReady || delta == null)
                { Cancel("Direct edit context unavailable; no native edit sent"); return true; }
                UpdateDraft(ray);
                if (!DirectModelEditMath.MeaningfulDelta(delta))
                { Cancel("No tool change in this gesture; native geometry unchanged"); return true; }
                var args = new JObject {
                    ["native_tool"] = frozenModel["native_tool"], ["mode"] = frozenModel["mode"],
                    ["component"] = frozenModel["component"], ["indices"] = new JArray(indices),
                    ["topology_token"] = frozenModel["topology_token"], ["delta"] = delta.DeepClone()
                };
                // Explicit original revision and generation are frozen in the draft.
                drawing.Session.Select(objectId);
                if (!drawing.Session.BeginDraft("object.spatial_edit", args, true))
                { Cancel(drawing.Session.Notice); return true; }
                drawing.Session.Draft["base_revision"] = revision;
                drawing.Session.Draft["target"]["generation"] = generation;
                if (!drawing.ApplyDirectModelDraft()) { Cancel(drawing.Session.Notice); return true; }
                held = false; submitted = true; pendingAt = Time.unscaledTime;
                ownRequestId = drawing.Session.LastSubmittedId;
                Notice = "Waiting for Blender geometry and one-gesture Undo receipt";
                return true;
            }
            if (grip || submitted) return false;
            var picked = scene.PickObject(ray, out var pickedDistance);
            if (picked == null || pickedDistance > nearest + .0005f) return false;
            distance = pickedDistance;
            Notice = ContextLabel;
            if (!pressed) return true;
            target = picked; hand = inputHand; objectId = picked.ObjectId; generation = picked.Generation;
            revision = drawing.Session.Revision; frozenIdentity = Identity();
            frozenModel = drawing.NativeState["model_edit"] is JObject model ? (JObject)model.DeepClone() : new JObject();
            frozenContext = Context(frozenModel); nativeToDisplay = DirectModelEditMath.NativeToDisplay(picked);
            displayRotation = picked.transform.parent.rotation * picked.RotationOffset;
            initialRay = ray; depth = pickedDistance; startPoint = currentPoint = ray.GetPoint(depth);
            indices = Array.Empty<int>(); vertices.Clear(); nativePoints.Clear(); delta = null;
            held = true; moved = waiting = released = false; gesture++;
            if ((string)frozenModel["mode"] == "EDIT_MESH")
            {
                if ((string)frozenModel["active_object_id"] != objectId
                    || !DirectModelEditMath.TryPick(frozenModel, nativeToDisplay, ray, .012f, out var component, out var selectedVertices, out var point))
                { frozenModel["available"] = false; frozenModel["reason"] = "Aim at a visible native mesh vertex / edge / face"; }
                else
                {
                    indices = new[] { component }; vertices.AddRange(selectedVertices);
                    depth = Vector3.Dot(point - ray.origin, ray.direction.normalized);
                    startPoint = currentPoint = ray.GetPoint(depth);
                }
            }
            pivot = picked.transform.position;
            if (frozenModel["vertices"] is JArray points)
                foreach (JObject point in points)
                    if (point["position"] is JArray p && p.Count == 3)
                        nativePoints[(int)point["index"]] = DirectModelEditMath.ToUnity(p);
            if (vertices.Count > 0)
            {
                pivot = Vector3.zero;
                foreach (int index in vertices) pivot += nativeToDisplay.MultiplyPoint3x4(nativePoints[index]);
                pivot /= vertices.Count;
            }
            return true;
        }
        void BeginMovement()
        {
            if ((bool?)frozenModel["available"] != true || !ContextCurrent())
            { Notice = (string)frozenModel["reason"] ?? "Direct tool unavailable; choose a supported tool in Blender"; return; }
            if (!DirectModelEditMath.SupportedTool((string)frozenModel["native_tool"]))
            { Notice = "This tool remains available in the 2D preview. Direct editing supports Move, Rotate, Scale and face Extrude Region"; return; }
            moved = true;
            if (drawing.NativeCommandReady) return;
            waiting = true; int requestGesture = gesture;
            preview.HandoffNativeCommand(() =>
            {
                if (!held || released || gesture != requestGesture) return;
                waiting = false;
                if (!ContextCurrent()) Cancel("Native tool or target changed during input cleanup; trigger again");
                else Notice = "Input released · orange is local preview · release trigger to commit once";
            }, reason => { if (gesture == requestGesture) Cancel(reason); }, true);
        }
        void UpdateDraft(Ray ray)
        {
            if (!ContextCurrent()) { Cancel("Native tool context changed; local edit cancelled"); return; }
            string tool = (string)frozenModel["native_tool"];
            CalculateTransform(ray, currentPoint, out var translation, out var rotation, out var scale);
            if (tool == "builtin.move" || tool.StartsWith("builtin.extrude_region", StringComparison.Ordinal))
                delta = new JObject { ["translation"] = DirectModelEditMath.ToWire(translation) };
            else if (tool == "builtin.rotate")
            {
                var nativeRotation = Quaternion.Inverse(displayRotation) * rotation * displayRotation;
                delta = new JObject { ["rotation"] = DirectModelEditMath.ToWire(nativeRotation) };
            }
            else
                delta = new JObject { ["scale"] = new JArray(scale.x, scale.y, scale.z) };
            RenderGhost(translation, rotation, scale, tool.StartsWith("builtin.extrude_region", StringComparison.Ordinal));
            Notice = "Orange LOCAL preview · " + tool.Replace("builtin.", "") + " · release: commit once · grip / Escape: cancel";
        }
        // Shared command/visual math. The visual caller supplies a newer point
        // but must never replace the frozen draft, queued delta or input state.
        void CalculateTransform(Ray ray, Vector3 point, out Vector3 translation, out Quaternion rotation, out Vector3 scale)
        {
            string tool = (string)frozenModel["native_tool"];
            var offset = point - startPoint;
            translation = Vector3.zero; rotation = Quaternion.identity; scale = Vector3.one;
            if (tool == "builtin.move" || tool.StartsWith("builtin.extrude_region", StringComparison.Ordinal))
                translation = nativeToDisplay.inverse.MultiplyVector(offset);
            else if (tool == "builtin.rotate") rotation = Quaternion.FromToRotation(initialRay.direction, ray.direction);
            else
            {
                var right = Vector3.Cross(Vector3.up, initialRay.direction).normalized;
                if (right.sqrMagnitude < .1f) right = Vector3.right;
                float factor = Mathf.Exp(Mathf.Clamp(Vector3.Dot(offset, right + Vector3.up) * 3f, -4.6f, 4.6f));
                scale = Vector3.one * factor;
            }
        }
        public bool TryVisualAim(Ray ray, out float distance)
        {
            distance = depth;
            if (!Active) return false;
            return scene != null && scene.PickObject(ray, out distance) != null;
        }
        // Rendering uses the current existing stabilized ray for this hand. A
        // nearer unchanged native mesh must not truncate its held draft contact.
        public bool TryGestureVisual(XRNode inputHand, Ray ray, out Vector3 endpoint)
        {
            endpoint = default;
            if (!Active || !held || inputHand != hand) return false;
            endpoint = ray.GetPoint(depth);
            if (moved && !waiting && !submitted && ContextCurrent())
            {
                CalculateTransform(ray, endpoint, out var translation, out var rotation, out var scale);
                RenderGhost(translation, rotation, scale,
                    ((string)frozenModel["native_tool"]).StartsWith("builtin.extrude_region", StringComparison.Ordinal));
            }
            return true;
        }
        public void Cancel(string reason = "Local direct edit cancelled; native geometry unchanged")
        {
            gesture++; held = waiting = moved = released = false;
            bool executing = submitted && drawing != null && drawing.Session.NativeCommandExecuting;
            if (submitted && drawing != null && drawing.Session.Busy) drawing.Session.Cancel();
            submitted = executing; if (!executing) ownRequestId = null;
            ClearGhost(); target = null; delta = null;
            Notice = executing ? drawing.Session.Notice : reason;
        }
        static void ReleaseObject(UnityEngine.Object value)
        { if (Application.isPlaying) Destroy(value); else DestroyImmediate(value); }
        void ClearGhost()
        {
            if (ghost != null) { ghost.SetActive(false); ReleaseObject(ghost); }
            ghost = null; lines.Clear();
        }
        void EnsureGhost()
        {
            if (ghost != null) return;
            if (ghostMaterial == null)
            {
                var shader = Shader.Find("Universal Render Pipeline/Unlit") ?? Shader.Find("UI/Default");
                ghostMaterial = new Material(shader); ghostMaterial.color = new Color(1f, .38f, .04f, 1f);
            }
            ghost = new GameObject("LOCAL model draft · uncommitted orange preview");
        }
        void RenderGhost(Vector3 nativeTranslation, Quaternion displayDeltaRotation, Vector3 scale, bool extrude)
        {
            EnsureGhost();
            var segments = new List<Vector3[]>();
            Vector3 Move(Vector3 original)
            {
                var display = nativeToDisplay.MultiplyPoint3x4(original);
                return pivot + displayDeltaRotation * Vector3.Scale(display - pivot, scale)
                    + nativeToDisplay.MultiplyVector(nativeTranslation);
            }
            if ((string)frozenModel["mode"] == "EDIT_MESH" && frozenModel["edges"] is JArray edges)
            {
                var selected = new HashSet<int>(vertices);
                foreach (JObject edge in edges)
                {
                    var ids = edge["vertices"] as JArray;
                    if (ids == null || ids.Count != 2 || !nativePoints.TryGetValue((int)ids[0], out var a) || !nativePoints.TryGetValue((int)ids[1], out var b)) continue;
                    bool first = selected.Contains((int)ids[0]), second = selected.Contains((int)ids[1]);
                    if (!first && !second) continue;
                    segments.Add(new[] { first ? Move(a) : nativeToDisplay.MultiplyPoint3x4(a), second ? Move(b) : nativeToDisplay.MultiplyPoint3x4(b) });
                }
                if (extrude) foreach (int id in vertices) segments.Add(new[] { nativeToDisplay.MultiplyPoint3x4(nativePoints[id]), Move(nativePoints[id]) });
                // A lone vertex has no guaranteed edge; show a visible local cross.
                foreach (int id in vertices)
                {
                    Vector3 p = Move(nativePoints[id]);
                    segments.Add(new[] { p - Vector3.right * .004f, p + Vector3.right * .004f });
                    segments.Add(new[] { p - Vector3.up * .004f, p + Vector3.up * .004f });
                }
            }
            else
            {
                var mesh = target.GetComponent<MeshFilter>()?.sharedMesh;
                if (mesh != null)
                {
                    var points = mesh.vertices; var tris = mesh.triangles;
                    var nativePose = Matrix4x4.TRS(target.NativePosition, target.NativeRotation, target.transform.localScale);
                    int count = Mathf.Min(tris.Length, 18000);
                    for (int i = 0; i + 2 < count; i += 3)
                        segments.Add(new[] { Move(nativePose.MultiplyPoint3x4(points[tris[i]])), Move(nativePose.MultiplyPoint3x4(points[tris[i+1]])), Move(nativePose.MultiplyPoint3x4(points[tris[i+2]])), Move(nativePose.MultiplyPoint3x4(points[tris[i]])) });
                }
            }
            while (lines.Count < segments.Count)
            {
                var obj = new GameObject("Local native-tool outline"); obj.transform.SetParent(ghost.transform, false);
                var line = obj.AddComponent<LineRenderer>(); line.sharedMaterial = ghostMaterial; line.useWorldSpace = true; line.widthMultiplier = .0015f;
                lines.Add(line);
            }
            for (int i = 0; i < lines.Count; i++)
            { lines[i].gameObject.SetActive(i < segments.Count); if (i < segments.Count) { lines[i].positionCount = segments[i].Length; lines[i].SetPositions(segments[i]); } }
        }
    }

    public static class DirectModelEditMath
    {
        public static Vector3 ToUnity(JArray p) => new Vector3((float)p[0], (float)p[2], (float)p[1]);
        public static JArray ToWire(Vector3 p) => new JArray(p.x, p.z, p.y);
        public static JArray ToWire(Quaternion p) => new JArray(p.w, -p.x, -p.z, -p.y);
        public static Matrix4x4 NativeToDisplay(WorkspaceObjectView view)
            => view.transform.localToWorldMatrix * Matrix4x4.TRS(view.NativePosition, view.NativeRotation, view.transform.localScale).inverse;
        public static bool SameMatrix(Matrix4x4 a, Matrix4x4 b)
        { for (int i = 0; i < 16; i++) if (Mathf.Abs(a[i] - b[i]) > .00001f) return false; return true; }
        public static bool SupportedTool(string tool) => tool == "builtin.move" || tool == "builtin.rotate" || tool == "builtin.scale"
            || tool == "builtin.extrude_region" || tool == "builtin.extrude_region_move";
        public static bool MeaningfulDelta(JObject delta)
        {
            if (delta?["translation"] is JArray t) return ToUnity(t).sqrMagnitude > 1e-12f;
            if (delta?["rotation"] is JArray r) return Mathf.Abs((float)r[0]) < .9999999f;
            if (delta?["scale"] is JArray s) return Mathf.Abs((float)s[0]-1f)+Mathf.Abs((float)s[1]-1f)+Mathf.Abs((float)s[2]-1f) > .000001f;
            return false;
        }
        static bool Triangle(Ray ray, Vector3 a, Vector3 b, Vector3 c, out float depth)
        {
            depth = 0; var edge1 = b - a; var edge2 = c - a; var p = Vector3.Cross(ray.direction, edge2);
            float det = Vector3.Dot(edge1, p); if (Mathf.Abs(det) < 1e-9f) return false;
            float inv = 1f / det; var v = ray.origin - a; float u = Vector3.Dot(v, p) * inv;
            if (u < -.00001f || u > 1.00001f) return false;
            var q = Vector3.Cross(v, edge1); float w = Vector3.Dot(ray.direction, q) * inv;
            if (w < -.00001f || u + w > 1.00001f) return false;
            depth = Vector3.Dot(edge2, q) * inv; return depth > 0 && depth <= 20f;
        }
        static bool VisibleCandidate(Vector3 origin, Vector3 candidate, JArray triangles, Dictionary<int, Vector3> points)
        {
            var offset = candidate - origin; float distance = offset.magnitude;
            if (distance < .000001f || distance > 20f) return false;
            var ray = new Ray(origin, offset / distance);
            // Radius is a lateral usability tolerance only. Even a thin front
            // surface must occlude a rear component at the candidate's exact ray.
            float epsilon = Mathf.Max(.00001f, distance * .000001f);
            foreach (JObject triangle in triangles)
            {
                if (!(triangle["vertices"] is JArray ids) || ids.Count != 3 || !points.TryGetValue((int)ids[0], out var a)
                    || !points.TryGetValue((int)ids[1], out var b) || !points.TryGetValue((int)ids[2], out var c)) continue;
                if (Triangle(ray, a, b, c, out float depth) && depth < distance - epsilon) return false;
            }
            return true;
        }
        public static bool TryPick(JObject model, Matrix4x4 map, Ray ray, float radius,
            out int index, out int[] selectedVertices, out Vector3 hit)
        {
            index = -1; selectedVertices = Array.Empty<int>(); hit = default;
            if (!(model?["vertices"] is JArray list) || !(model["faces"] is JArray faces)) return false;
            var points = new Dictionary<int, Vector3>();
            foreach (JObject vertex in list) if (vertex["position"] is JArray position && position.Count == 3)
                points[(int)vertex["index"]] = map.MultiplyPoint3x4(ToUnity(position));
            float nearest = float.PositiveInfinity; int faceIndex = -1;
            // Blender's base-mesh tessellation preserves concave n-gons and exact face IDs.
            var triangles = model["triangles"] as JArray;
            if (triangles != null)
                foreach (JObject triangle in triangles)
                {
                    if (!(triangle["vertices"] is JArray ids) || ids.Count != 3 || !points.TryGetValue((int)ids[0], out var a)
                        || !points.TryGetValue((int)ids[1], out var b) || !points.TryGetValue((int)ids[2], out var c)) continue;
                    if (Triangle(ray,a,b,c,out float depth) && depth < nearest) { nearest = depth; faceIndex = (int)triangle["face"]; }
                }
            if (faceIndex < 0) return false;
            string component = (string)model["component"];
            if (component == "face")
            {
                foreach (JObject face in faces) if ((int)face["index"] == faceIndex)
                { index = faceIndex; selectedVertices = ((JArray)face["vertices"]).ToObject<int[]>(); hit = ray.GetPoint(nearest); return true; }
                return false;
            }
            float best = radius;
            if (component == "vertex")
                foreach (var vertex in points)
                {
                    float depth = Vector3.Dot(vertex.Value-ray.origin,ray.direction.normalized);
                    if (depth <= 0 || depth > 20f) continue;
                    float miss = Vector3.Distance(vertex.Value,ray.GetPoint(depth));
                    if (miss <= best && VisibleCandidate(ray.origin, vertex.Value, triangles, points))
                    { best = miss; index = vertex.Key; selectedVertices = new[] { index }; hit = vertex.Value; }
                }
            if (component == "edge" && model["edges"] is JArray edges)
                foreach (JObject edge in edges)
                {
                    if (!(edge["vertices"] is JArray ids) || ids.Count != 2 || !points.TryGetValue((int)ids[0],out var a) || !points.TryGetValue((int)ids[1],out var b)) continue;
                    var vector=b-a; var direction=ray.direction.normalized; var offset=a-ray.origin;
                    float length=vector.sqrMagnitude, alignment=Vector3.Dot(vector,direction), denominator=length-alignment*alignment;
                    float t=denominator>1e-10f?Mathf.Clamp01((alignment*Vector3.Dot(offset,direction)-Vector3.Dot(offset,vector))/denominator):0;
                    var at=a+vector*t; float depth=Vector3.Dot(at-ray.origin,direction);
                    if(depth<=0||depth>20f)continue;
                    float miss=Vector3.Distance(at,ray.GetPoint(depth));
                    if(miss<=best&&VisibleCandidate(ray.origin,at,triangles,points))
                    {best=miss;index=(int)edge["index"];selectedVertices=ids.ToObject<int[]>();hit=at;}
                }
            return index>=0;
        }
    }
}

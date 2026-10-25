using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace SpatialModeling
{
    // P2.5 is opt-in. Only typed native receipts publish committed geometry;
    // the orange preview below is a disposable local two-point draft.
    public sealed class PreviewSpatialDrawing : MonoBehaviour
    {
        public NativeEditSession Session { get; } = new NativeEditSession();
        public bool EnabledForInput { get; private set; }
        public bool ObjectToolsEnabled { get; private set; }
        public bool DirectModelToolsActive { get; set; }
        public event Action<JObject> BeforeNativeSessionMessage;
        NativeObjectTools objectTools;
        public NativeObjectTools ObjectTools => objectTools ?? (objectTools = new NativeObjectTools(Session));
        NativeNumericTools numeric;
        public NativeNumericTools Numeric => numeric ?? (numeric = new NativeNumericTools(Session, ObjectTools));
        public bool NativeUiTransitionPending => beginId != null || endId != null || wantNativeUi;
        public JObject NativeState { get; private set; } = new JObject();
        public bool IsNativeUiOwned => NativeStateCurrent && (bool?)NativeState["input_allowed"] == true
            && (string)NativeState["ui_session_id"] != null && !string.IsNullOrEmpty((string)NativeState["ui_session_id"]);
        public int NativeProcessId => NativeStateCurrent ? (int?)NativeState["process_id"] ?? 0 : 0;
        public bool NativeModalActive => (bool?)NativeState["modal_active"] ?? false;
        // A typed edit must wait for fresh native confirmation of lease release,
        // not merely for the local Input OFF flag or HTTP key-up acknowledgement.
        public bool NativeCommandReady => NativeStateCurrent && !NativeModalActive && !NativeUiTransitionPending
            && (NativeState["ui_owner"] == null || NativeState["ui_owner"].Type == JTokenType.Null)
            && (bool?)NativeState["ui_ending"] != true
            && string.IsNullOrEmpty((string)NativeState["ui_session_id"]);
        public string Tool => (string)NativeState["tool"] ?? "";
        public string StatusText => (ObjectToolsEnabled ? ObjectTools.TargetLabel + "\n" : TargetStatus) + status + "\n" + Session.Notice;
        public bool HasDraft => first.HasValue;
        public bool NativeStateCurrent => scene != null && scene.IsCurrent && Session.Ready && Session.SceneCurrent
            && Time.unscaledTime - stateAt < 2f;
        public bool ApplyDirectModelDraft()
        {
            if (!DirectModelToolsActive || !NativeCommandReady) return false;
            pendingAt = Time.unscaledTime;
            return Session.Apply();
        }

        HostScene scene;
        Material solvedMaterial, draftMaterial;
        readonly List<GameObject> solved = new List<GameObject>();
        GameObject draft;
        float nextQuery, stateAt = float.NegativeInfinity, pendingAt;
        string pendingSpatialContext = "", draftContext = "";
        bool spatialRequestPending;
        string status = "VR drawing is off · choose Draw in VR to start", draftSketch = "", beginId, endId;
        long draftGeneration;
        Vector2? first;
        Ray lastRay;
        bool haveRay, wantNativeUi, objectRequestPending;
        readonly SpatialSketchTarget target = new SpatialSketchTarget();
        string TargetStatus
        {
            get
            {
                if (target.MissingExplicitTarget) return "Spatial sketch removed/unavailable; choose a fresh target\n";
                if (target.WaitingForExplicitTarget) return "Waiting for confirmed native spatial target " + target.ExplicitId + "\n";
                if (target.ExplicitId.Length == 0) return "";
                string name = Session.Sketches.TryGetValue(target.ExplicitId, out var explicitSketch) ? (string)explicitSketch["name"] : target.ExplicitId;
                return "Spatial target: " + name + " · native preview target: " + ((string)NativeState["sketch_id"] ?? "none") + "\n";
            }
        }

        public void Initialize(HostScene hostScene, Material displayMaterial = null)
        {
            if (scene != null) scene.HostEventReceived -= Receive;
            scene = hostScene;
            if (scene == null) return;
            scene.HostEventReceived += Receive;
            Session.Send = msg => scene.Link?.SendEnvelope(msg);
            if (displayMaterial != null && solvedMaterial == null)
            {
                solvedMaterial = new Material(displayMaterial);
                solvedMaterial.color = new Color(0.12f, 0.95f, 0.82f);
                draftMaterial = new Material(displayMaterial);
                draftMaterial.color = new Color(1f, 0.55f, 0.1f);
            }
        }

        void OnEnable()
        {
            OVRManager.HMDUnmounted += LoseFocus;
            OVRManager.VrFocusLost += LoseFocus;
        }
        void OnDisable()
        {
            OVRManager.HMDUnmounted -= LoseFocus;
            OVRManager.VrFocusLost -= LoseFocus;
            SetEnabled(false);
        }
        void OnDestroy()
        {
            objectTools?.Dispose();
            numeric?.Dispose();
            if (scene != null) scene.HostEventReceived -= Receive;
            ClearSolved();
            if (solvedMaterial != null) Destroy(solvedMaterial);
            if (draftMaterial != null) Destroy(draftMaterial);
        }
        // The preview controller owns synthetic-release acknowledgement -> UI
        // session end ordering. This component only discards spatial drafts.
        void LoseFocus() { Cancel(); }

        public void SetEnabled(bool value)
        {
            if (value) ObjectToolsEnabled = false;
            EnabledForInput = value;
            Cancel();
            if (!value) target.Reset();
            if (value) { EndNativeUi(); nextQuery = 0; status = "Select a native sketch and Line, Circle or Corner Rectangle tool"; }
            else status = "VR drawing is off · Blender preview controls remain available";
        }

        public void BeginNativeUi()
        {
            ObjectToolsEnabled = false;
            Cancel(); EnabledForInput = false; wantNativeUi = true; nextQuery = 0;
            if (!Session.Ready || !Session.SceneCurrent || Session.Busy || Session.RequestIdentity == null)
            { status = "Wait for a current native scene and completed spatial receipt"; return; }
            if (beginId != null || IsNativeUiOwned) return;
            var msg = NativeEditSession.Envelope("preview.ui.begin", Session.RequestIdentity);
            beginId = (string)msg["id"]; pendingAt = Time.unscaledTime;
            Session.Send?.Invoke(msg); status = "Requesting native preview editing session";
        }

        public void EndNativeUi()
        {
            wantNativeUi = false;
            string token = (string)NativeState["ui_session_id"];
            if (string.IsNullOrEmpty(token) || Session.RequestIdentity == null || endId != null) return;
            var p = Session.RequestIdentity; p["ui_session_id"] = token;
            var msg = NativeEditSession.Envelope("preview.ui.end", p);
            endId = (string)msg["id"]; pendingAt = Time.unscaledTime;
            Session.Send?.Invoke(msg);
            // Stop admitting input immediately; native lease release may wait
            // for the modal tool's real completion/cancel event.
            NativeState["input_allowed"] = false;
            status = "Finishing native preview session; confirm/cancel any running Blender operation";
        }

        void Update()
        {
            if (scene == null) return;
            Session.SceneCurrent = scene.IsCurrent;
            if (!scene.IsCurrent || !scene.DisplayPlacementReady) CancelLocal();
            if ((EnabledForInput || ObjectToolsEnabled || DirectModelToolsActive || Session.Busy || wantNativeUi || beginId != null || endId != null || !string.IsNullOrEmpty((string)NativeState["ui_session_id"]))
                && Session.Ready && Time.unscaledTime >= nextQuery)
            { scene.Link?.Send("preview.state.query", new JObject()); nextQuery = Time.unscaledTime + 0.4f; }
            if (objectRequestPending && !ObjectContextCurrent()) Session.Cancel();
            ValidateSpatialContext();
            if (ObjectToolsEnabled && !ObjectContextCurrent()) numeric?.Invalidate();
            if ((Session.AwaitingPermission || Session.NativeCommandExecuting) && Time.unscaledTime - pendingAt > 10f) Session.Timeout();
            if ((beginId != null || endId != null) && Time.unscaledTime - pendingAt > 5f)
            {
                beginId = endId = null; wantNativeUi = false;
                NativeState["input_allowed"] = false;
                status = "Native UI acknowledgement missing; reconnect before editing";
                scene.Link?.Reconnect();
            }
            if (first.HasValue && haveRay) RenderDraft(lastRay);
            foreach (var go in solved) if (go != null) go.SetActive(scene.Placement.gameObject.activeInHierarchy);
        }

        void Receive(HostEvent e)
        {
            Session.SceneCurrent = scene != null && scene.IsCurrent;
            if (e.Kind == HostEventKind.Closed || e.Kind == HostEventKind.InvalidScene)
            {
                BeforeNativeSessionMessage?.Invoke(new JObject { ["type"]="connection.closed",["payload"]=new JObject { ["reason"]=e.Text??"Native scene unavailable" } });
                Session.Disconnect(e.Text ?? "Native scene unavailable");
                objectTools?.Reset(); ObjectToolsEnabled = objectRequestPending = false;
                numeric?.Invalidate();
                NativeState = new JObject(); stateAt = float.NegativeInfinity;
                target.Reset();
                beginId = endId = null; wantNativeUi = false; CancelLocal(); return;
            }
            if (e.Kind != HostEventKind.Message || e.RawMessage == null) return;
            var msg = e.RawMessage; var p = msg["payload"] as JObject;
            // A grant may arrive after native mode/focus/context changed. Cancel
            // while acquisition is still pending, before Receive can emit it.
            if (objectRequestPending && !ObjectContextCurrent()) Session.Cancel();
            ValidateSpatialContext();
            bool hadObjectRequest = objectRequestPending;
            BeforeNativeSessionMessage?.Invoke(msg);
            Session.Receive(msg);
            if (spatialRequestPending && !Session.Busy) spatialRequestPending = false;
            ObjectTools.Observe(msg);
            if (hadObjectRequest && !Session.Busy)
            { objectRequestPending = false; status = Session.Notice; }
            string type = (string)msg["type"];
            // A welcome starts a new admission/scene handshake. Never carry
            // the preceding connection's UI reservation through its snapshot.
            if (type == "welcome")
            { NativeState = new JObject(); stateAt = float.NegativeInfinity; target.Reset(); CancelLocal(); }
            if (Session.LastReceipt != null && JToken.DeepEquals(Session.LastReceipt, p) && target.Receive(msg, Session.Sketches))
                status = "New native sketch explicitly selected for spatial drawing; native desktop selection preserved";
            if (type == "preview.state" && p != null) SetNativeState(p);
            if ((type == "preview.ui.granted" && (string)msg["re"] == beginId)
                || (type == "preview.ui.ended" && (string)msg["re"] == endId))
            {
                foreach (var property in p.Properties()) NativeState[property.Name] = property.Value.DeepClone();
                if (type == "preview.ui.granted")
                {
                    beginId = null;
                    if (!wantNativeUi) EndNativeUi();
                    else status = "Native Blender preview input enabled";
                }
                else { endId = null; status = NativeModalActive ? "Finish/cancel the native modal tool before spatial drawing" : "Native preview session ended"; }
            }
            if (type == "error" && ((beginId != null && (string)msg["re"] == beginId) || (endId != null && (string)msg["re"] == endId)))
            { beginId = endId = null; status = (string)p?["message"] ?? "Native UI request refused"; wantNativeUi = false; }
            if (type == "scene.snapshot" || type == "scene.update")
            {
                if (first.HasValue && (!Session.Sketches.TryGetValue(draftSketch, out var s)
                    || (long?)s["generation"] != draftGeneration)) { CancelLocal(); status = "Native sketch changed; local draft cancelled"; }
                RebuildSolved();
            }
        }

        public void SetNativeState(JObject p)
        {
            var identity = Session.RequestIdentity;
            if (identity == null || p == null) return;
            foreach (string name in new[] { "session_id", "host_epoch", "document_id", "open_epoch" })
                if ((string)p[name] != (string)identity[name])
                {
                    if (objectRequestPending || spatialRequestPending) Session.Cancel();
                    numeric?.Invalidate();
                    NativeState = new JObject(); stateAt = float.NegativeInfinity;
                    target.Reset();
                    CancelLocal(); status = "Native tool state belongs to another session/document; preview input disabled"; return;
                }
            string before = NativeContext(NativeState);
            NativeState = (JObject)p.DeepClone(); stateAt = Time.unscaledTime;
            target.ObserveContext(NativeState);
            string after = NativeContext(p);
            Session.Mode = (string)p["editing_mode"] == "shared" ? "shared" : "exclusive";
            if (before != after) { CancelLocal(); if (spatialRequestPending) Session.Cancel(); }
            ValidateSpatialContext();
            if (objectRequestPending && !ObjectContextCurrent()) Session.Cancel();
            ValidateSpatialContext();
            if (!ObjectContextCurrent()) numeric?.Invalidate();
        }

        bool ObjectContextCurrent() => scene != null && scene.IsCurrent && scene.DisplayPlacementReady
            && NativeStateCurrent && (string)NativeState["mode"] == "OBJECT" && !NativeModalActive
            && !NativeUiTransitionPending && !(NativeState["ui_owner"] is JObject)
            && (bool?)NativeState["ui_ending"] != true && string.IsNullOrEmpty((string)NativeState["ui_session_id"]);

        public bool SetObjectToolsEnabled(bool value)
        {
            if (!value)
            { if (ObjectToolsEnabled) Cancel(); ObjectToolsEnabled = false; return true; }
            if (Session.Busy || NativeUiTransitionPending || NativeState["ui_owner"] is JObject
                || (bool?)NativeState["ui_ending"] == true || !string.IsNullOrEmpty((string)NativeState["ui_session_id"]))
            { status = "Wait for native input cleanup and the previous edit receipt"; return false; }
            SetEnabled(false); ObjectToolsEnabled = true; nextQuery = 0;
            status = "Choose a model target; steps change real Blender geometry. Undo is available.";
            return true;
        }

        public bool ApplyObjectAction(string action)
        {
            if (!ObjectToolsEnabled || !ObjectContextCurrent() || !Session.CanEdit || Session.Busy || Session.OutcomeUnknown)
            { status = "Model tools need a fresh editable native scene in Object Mode, with preview input ended"; return false; }
            CancelLocal();
            if (!ObjectTools.Stage(action) || !Session.Apply()) return false;
            objectRequestPending = true; pendingAt = Time.unscaledTime;
            status = "Waiting for Blender to confirm the model edit";
            return true;
        }
        public bool LoadNumeric(string mode)
        {
            if (!ObjectToolsEnabled || !ObjectContextCurrent()) { status = "Open Model tools with current native Object Mode first"; return false; }
            return Numeric.Load(mode);
        }
        public bool ApplyNumeric()
        {
            if (!ObjectToolsEnabled || !ObjectContextCurrent() || !Session.CanEdit || Session.Busy || Session.OutcomeUnknown)
            { numeric?.Invalidate(); status = "Wait for current native Object Mode and reload the numeric draft"; return false; }
            if (!Numeric.Stage() || !Session.Apply()) { status = Numeric.Notice; return false; }
            Numeric.Invalidate("Values submitted; wait for the native receipt, then reload");
            objectRequestPending = true; pendingAt = Time.unscaledTime;
            status = "Waiting for Blender to confirm the exact numeric edit";
            return true;
        }

        JObject ActiveSketch
        {
            get
            {
                return target.Resolve((string)NativeState["sketch_id"], "", Session.Sketches);
            }
        }
        static string NativeContext(JObject state)
        {
            var value = new JObject();
            foreach (string key in new[] { "sketch_id", "native_tool", "tool", "mode", "available", "reason", "unsupported_options", "editing_mode" })
                value[key] = state[key]?.DeepClone();
            return value.ToString(Newtonsoft.Json.Formatting.None);
        }
        string SpatialContext()
        {
            var sketch = ActiveSketch;
            return NativeContext(NativeState) + "/" + (string)sketch?["id"] + "/" + (long?)sketch?["generation"]
                + "/" + sketch?["plane"]?.ToString(Newtonsoft.Json.Formatting.None)
                + "/" + Session.Document["units"]?.ToString(Newtonsoft.Json.Formatting.None);
        }
        void ValidateSpatialContext()
        {
            bool current = NativeStateCurrent && EnabledForInput && scene != null && scene.DisplayPlacementReady
                && !NativeModalActive && !(NativeState["ui_owner"] is JObject) && (bool?)NativeState["ui_ending"] != true;
            if (first.HasValue && (!current || draftContext != SpatialContext()))
            { CancelLocal(); status = "Native drawing context changed; draft cancelled"; }
            if (spatialRequestPending && (!current || pendingSpatialContext != SpatialContext()))
            { Session.Cancel(); status = "Native drawing context changed; pending permission cancelled"; }
        }

        bool CanDraw()
        {
            bool allowed = CanDrawOnSketch(ActiveSketch, out string reason);
            if (!allowed && reason.Length != 0) status = reason;
            return allowed;
        }
        // Visual queries run again immediately before rendering. They must not
        // update target selection, tool status, lastRay or the local draft.
        JObject VisualSketch
        {
            get
            {
                if (target.MissingExplicitTarget) return null;
                string id = target.ExplicitId.Length != 0 ? target.ExplicitId : (string)NativeState["sketch_id"];
                return !string.IsNullOrEmpty(id) && Session.Sketches.TryGetValue(id, out var sketch) ? sketch : null;
            }
        }
        bool CanDrawOnSketch(JObject sketch, out string reason)
        {
            reason = "";
            if (!EnabledForInput || scene == null || !scene.IsCurrent || !scene.DisplayPlacementReady || !Session.Ready || !Session.CanEdit || Session.Busy || Session.OutcomeUnknown)
                return false;
            if (!NativeStateCurrent || (bool?)NativeState["available"] != true || (string)NativeState["mode"] != "OBJECT")
            { reason = "Wait for fresh native CAD tool state in Object Mode"; return false; }
            if (NativeModalActive || (bool?)NativeState["ui_ending"] == true || NativeState["ui_owner"] is JObject)
            { reason = "End native preview input and confirm/cancel its active tool first"; return false; }
            if (!string.IsNullOrEmpty((string)NativeState["reason"])) { reason = (string)NativeState["reason"]; return false; }
            if (NativeState["unsupported_options"] is JArray options && options.Count > 0)
            { reason = "Spatial drawing needs these native options off: " + string.Join(", ", options.ToObject<string[]>()); return false; }
            if (sketch == null)
            {
                reason = "Select or create a supported native planar sketch";
                if (NativeState["unsupported_sketches"] is JArray problems)
                    foreach (JObject problem in problems)
                        if ((string)problem["id"] == (string)NativeState["sketch_id"])
                            reason = "Native sketch unavailable to spatial tools: " + (string)problem["reason"];
                return false;
            }
            if (Tool != "line" && Tool != "circle" && Tool != "rectangle" && Tool != "select")
            { reason = "This native tool works in the preview; direct spatial input currently supports Line, Circle and Corner Rectangle"; return false; }
            return true;
        }

        static bool Frame(JObject sketch, out Vector3 origin, out Quaternion rotation)
        {
            origin = default; rotation = Quaternion.identity;
            if (!(sketch?["plane"]?["location"] is JArray l) || l.Count != 3
                || !(sketch["plane"]?["rotation"] is JArray q) || q.Count != 4) return false;
            origin = new Vector3((float)l[0], (float)l[1], (float)l[2]);
            rotation = new Quaternion((float)q[1], (float)q[2], (float)q[3], (float)q[0]);
            return true;
        }
        bool Map(Ray ray, out Vector2 point, out Vector3 hit)
            => MapOnSketch(ray, ActiveSketch, out point, out hit);
        bool MapOnSketch(Ray ray, JObject sketch, out Vector2 point, out Vector3 hit)
        {
            point = default; hit = default;
            return Frame(sketch, out var origin, out var rotation)
                && PreviewSketchMapping.TryMapRay(ray, scene.Placement.localToWorldMatrix, origin, rotation, out point, out hit);
        }
        public bool TryVisualAim(Ray ray, out Vector3 hit)
        {
            hit = default; var sketch = VisualSketch;
            return CanDrawOnSketch(sketch, out _) && MapOnSketch(ray, sketch, out _, out hit);
        }
        public bool TryAim(Ray ray, out Vector3 hit)
        {
            lastRay = ray; haveRay = true; hit = default;
            return CanDraw() && Map(ray, out _, out hit);
        }
        public bool Press(Ray ray)
        {
            if (!CanDraw() || !Map(ray, out var point, out _)) return false;
            var sketch = ActiveSketch; string id = (string)sketch["id"];
            if (Tool == "select") { SelectNearest(point, sketch); return true; }
            if (!first.HasValue)
            {
                first = point; draftSketch = id; draftGeneration = (long)sketch["generation"]; draftContext = SpatialContext();
                Session.Select(id); status = Tool == "circle" ? "Pick the radius point; orange geometry is a local draft" : "Pick the second point; orange geometry is a local draft";
                return true;
            }
            if (draftContext != SpatialContext() || draftSketch != id || draftGeneration != (long)sketch["generation"]) { Cancel(); return true; }
            var a = first.Value;
            float distance = Vector2.Distance(a, point);
            if (distance < 0.000001f || (Tool == "rectangle" && Mathf.Min(Mathf.Abs(a.x - point.x), Mathf.Abs(a.y - point.y)) < 0.000001f))
            { status = "Choose a nonzero shape, at least one micrometer on each required axis"; return true; }
            var args = Tool == "line" ? new JObject { ["start"] = XY(a), ["end"] = XY(point) }
                : Tool == "rectangle" ? new JObject { ["corner"] = XY(a), ["opposite"] = XY(point) }
                : new JObject { ["center"] = XY(a), ["radius"] = distance };
            string op = "sketch.add_" + Tool;
            string context = SpatialContext();
            CancelLocal(); Session.Select(id);
            if (Session.BeginDraft(op, args, true) && Session.Apply())
            { spatialRequestPending = true; pendingSpatialContext = context; pendingAt = Time.unscaledTime; status = "Waiting for native CAD Sketcher solver and receipt"; }
            return true;
        }
        static JArray XY(Vector2 p) => new JArray(p.x, p.y);
        // Legacy backend entry kept for compatibility, with no tool override.
        // The delivered app always follows the actual native Blender tool.
        public void SelectTool(string tool)
        { Cancel(); status = "Choose the drawing tool in Blender's CAD Sketcher interface"; }
        public void CreateSketch(string plane)
        {
            if (!EnabledForInput) { status = "Choose Draw in VR before creating a spatial sketch"; return; }
            if (plane != "XY" && plane != "XZ" && plane != "YZ") return;
            if (!SpatialSketchTarget.CanStartCreation(NativeStateCurrent, NativeState))
            { status = "Wait for fresh native CAD state in Object Mode before creating a spatial target"; return; }
            CancelLocal(); EndNativeUi();
            if (NativeState["ui_owner"] is JObject) { status = "Wait for native preview session to end, then create the sketch"; return; }
            if (Session.BeginDraft("sketch.create", new JObject { ["plane"] = plane }, false) && Session.Apply())
            { pendingAt = Time.unscaledTime; target.BeginCreate(Session.LastSubmittedId, NativeState); }
        }
        public void Undo() => History("history.undo");
        public void Redo() => History("history.redo");
        public void Save() => History("document.save");
        void History(string op)
        {
            Cancel();
            if (ObjectToolsEnabled && !ObjectContextCurrent()) { status = "Wait for current native Object Mode and completed preview cleanup"; return; }
            if (NativeState["ui_owner"] is JObject) { status = "Use native preview Undo/Redo while its editing session is active"; return; }
            if (Session.BeginDraft(op, new JObject(), false) && Session.Apply())
            { pendingAt = Time.unscaledTime; objectRequestPending = ObjectToolsEnabled; }
        }
        public void Cancel() { CancelLocal(); Session.Cancel(); }
        void CancelLocal() { first = null; haveRay = false; if (draft != null) Destroy(draft); draft = null; }

        public string SelectedEntityId { get; private set; } = "";
        void SelectNearest(Vector2 point, JObject sketch)
        {
            float best = 0.01f; SelectedEntityId = "";
            if (!(sketch["entities"] is JArray entities)) return;
            var points = Points(entities);
            foreach (JObject e in entities)
            {
                float distance = float.PositiveInfinity;
                string kind = (string)e["kind"];
                if (kind == "point" && points.TryGetValue((string)e["id"], out var at)) distance = Vector2.Distance(at, point);
                else if (kind == "line" && e["points"] is JArray ids && ids.Count == 2 && points.TryGetValue((string)ids[0], out var a) && points.TryGetValue((string)ids[1], out var b))
                { var delta = b - a; float t = delta.sqrMagnitude > 0 ? Mathf.Clamp01(Vector2.Dot(point - a, delta) / delta.sqrMagnitude) : 0; distance = Vector2.Distance(point, a + t * delta); }
                else if (kind == "circle" && points.TryGetValue((string)e["center"], out var center)) distance = Mathf.Abs(Vector2.Distance(point, center) - (float)e["radius"]);
                if (distance <= best) { best = distance; SelectedEntityId = (string)e["id"]; }
            }
            status = SelectedEntityId.Length == 0 ? "No native entity within 10 mm" : "Selected native entity " + SelectedEntityId;
        }
        static Dictionary<string, Vector2> Points(JArray entities)
        {
            var result = new Dictionary<string, Vector2>();
            foreach (JObject e in entities) if ((string)e["kind"] == "point" && e["at"] is JArray at && at.Count == 2)
                result[(string)e["id"]] = new Vector2((float)at[0], (float)at[1]);
            return result;
        }
        List<Vector2[]> Segments(string tool, Vector2 a, Vector2 b)
        {
            var result = new List<Vector2[]>();
            if (tool == "line") result.Add(new[] { a, b });
            else if (tool == "rectangle") result.Add(new[] { a, new Vector2(b.x, a.y), b, new Vector2(a.x, b.y), a });
            else if (tool == "circle")
            { var circle = new Vector2[65]; float radius = Vector2.Distance(a, b); for (int i = 0; i < circle.Length; i++) { float t = i * 2 * Mathf.PI / 64; circle[i] = a + radius * new Vector2(Mathf.Cos(t), Mathf.Sin(t)); } result.Add(circle); }
            return result;
        }
        void AddLine(GameObject root, Vector2[] points, JObject sketch, Material material)
        {
            if (!Frame(sketch, out var origin, out var rotation) || material == null) return;
            var go = new GameObject("Native sketch stroke"); go.transform.SetParent(root.transform, false);
            var line = go.AddComponent<LineRenderer>(); line.sharedMaterial = material;
            line.useWorldSpace = false; line.widthMultiplier = 0.0007f; line.positionCount = points.Length;
            for (int i = 0; i < points.Length; i++) line.SetPosition(i, PreviewSketchMapping.WorldPoint(points[i], Matrix4x4.identity, origin, rotation));
        }
        void RenderDraft(Ray ray)
        {
            if (!CanDraw() || !Map(ray, out var point, out _)) return;
            if (draft == null)
            {
                draft = new GameObject("Local draft · uncommitted"); draft.transform.SetParent(scene.Placement, false);
                foreach (var segment in Segments(Tool, first.Value, point)) AddLine(draft, segment, ActiveSketch, draftMaterial);
            }
            else if (Frame(ActiveSketch, out var origin, out var rotation))
            {
                var segments = Segments(Tool, first.Value, point);
                var lines = draft.GetComponentsInChildren<LineRenderer>();
                for (int j = 0; j < lines.Length && j < segments.Count; j++)
                {
                    var segment = segments[j]; lines[j].positionCount = segment.Length;
                    for (int i = 0; i < segment.Length; i++) lines[j].SetPosition(i, PreviewSketchMapping.WorldPoint(segment[i], Matrix4x4.identity, origin, rotation));
                }
            }
        }
        void ClearSolved() { foreach (var go in solved) if (go != null) Destroy(go); solved.Clear(); }
        void RebuildSolved()
        {
            ClearSolved();
            if (scene == null || solvedMaterial == null) return;
            foreach (var sketch in Session.Sketches.Values)
            {
                if (!(sketch["entities"] is JArray entities)) continue;
                var root = new GameObject("Native solved sketch " + (string)sketch["id"]); root.transform.SetParent(scene.Placement, false); solved.Add(root);
                var points = Points(entities);
                foreach (JObject e in entities)
                {
                    if ((string)e["kind"] == "line" && e["points"] is JArray ids && ids.Count == 2 && points.TryGetValue((string)ids[0], out var a) && points.TryGetValue((string)ids[1], out var b)) AddLine(root, new[] { a, b }, sketch, solvedMaterial);
                    if ((string)e["kind"] == "circle" && points.TryGetValue((string)e["center"], out var center))
                        foreach (var segment in Segments("circle", center, center + Vector2.right * (float)e["radius"])) AddLine(root, segment, sketch, solvedMaterial);
                }
            }
        }
    }
}

using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // Same production menu and CAD command bridge as the participant workflow.
    public sealed class NativeSketchSmoke : MonoBehaviour
    {
        WorkspaceNativeMenu menu; NativeSketchEditor editor; NativeEditSession session;
        string output; bool failed;
        HostLink ownershipPeer;
        JObject peerWelcome;
        string peerLease;
        Transform softwareCamera;
        Pose savedCameraPose;
        readonly JObject report = new JObject { ["physical_headset"] = "not tested", ["second_pc"] = "not tested", ["steps"] = new JArray() };
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install() { if (Array.Exists(Environment.GetCommandLineArgs(), a => a == "-p3-sketch-smoke")) new GameObject("Native CAD menu smoke").AddComponent<NativeSketchSmoke>(); }
        void Start()
        {
            output = Environment.GetEnvironmentVariable("P3_PLAYER_SMOKE_REPORT");
            int.TryParse(Environment.GetEnvironmentVariable("CALHACKS_HOST_PORT"), out var port);
            if (string.IsNullOrEmpty(output) || !Path.IsPathRooted(output) || port < 1024 || port == 8765) { WorkspaceShutdown.Quit(3); return; }
            StartCoroutine(Run());
        }
        void Update()
        {
            if (ownershipPeer == null) return;
            while (ownershipPeer.Events.TryDequeue(out var e)) if (e.RawMessage?["payload"] is JObject p)
            {
                if ((string)e.RawMessage["type"] == "welcome") peerWelcome = p;
                if ((string)e.RawMessage["type"] == "lease.granted") peerLease = (string)p["lease"]?["lease_id"];
            }
        }
        IEnumerator Run()
        {
            double until = Time.realtimeSinceStartupAsDouble + 30;
            while ((menu = FindAnyObjectByType<WorkspaceNativeMenu>()) == null && Time.realtimeSinceStartupAsDouble < until) yield return null;
            if (menu == null) { Fail("Native menu missing"); yield break; }
            editor = menu.GetComponent<NativeSketchEditor>(); session = menu.Session;
            while ((!session.Ready || !session.SceneCurrent) && Time.realtimeSinceStartupAsDouble < until) yield return null;
            if (!session.Ready || !session.SceneCurrent || !session.SketchAvailable) { Fail("Pinned native CAD capability is unavailable"); yield break; }
            var scene = FindAnyObjectByType<HostScene>();
            if (!NativeSmokeWorkspace.Place(scene)) { Fail("Real Place Table callback did not activate the solved-geometry root"); yield break; }
            report["placement"] = "Bounded software test pose and actual Place Table action; physical placement not tested";
            yield return NewSketch(); if (failed) yield break;
            string rectangle = session.SelectedId;
            SketchHome(); if (!Click("Rectangle") || !Click("Apply")) yield break;
            yield return Receipt("100x60 rectangle"); if (failed) yield break;
            var records = (JArray)session.Sketches[rectangle]["entities"];
            string corner = null, horizontal = null, vertical = null;
            var points = Points(records);
            foreach (var pair in points) if (pair.Value.sqrMagnitude < 1e-12f) corner = pair.Key;
            foreach (JObject entity in records)
                if ((string)entity["kind"] == "line" && entity["points"] is JArray endpoints)
                { var a = points[(string)endpoints[0]]; var b = points[(string)endpoints[1]]; if (Math.Abs(a.y - b.y) < 1e-6) horizontal = (string)entity["id"]; else vertical = (string)entity["id"]; }
            yield return Constrain("fixed", corner); if (failed) yield break;
            yield return Constrain("distance", horizontal, "100"); if (failed) yield break;
            string widthDimension = (string)session.LastReceipt["created"]?[0];
            yield return Constrain("distance", vertical, "60"); if (failed) yield break;
            if (!Extent(rectangle, 0.1, 0.06) || (string)session.Sketches[rectangle]["solver"]?["status"] != "fully_constrained") { Fail("Anchored 100x60 rectangle was not fully solved"); yield break; }
            SketchHome(); editor.SmokeChoose(horizontal, constraint: widthDimension);
            if (!Click("Edit dimension")) yield break; menu.SmokeNumber(0, "120"); if (!Click("Apply")) yield break;
            yield return Receipt("width120 height60"); if (failed) yield break;
            if (!Extent(rectangle, 0.12, 0.06)) { Fail("Width120 did not preserve height60"); yield break; }
            string valid = session.Sketches[rectangle]["entities"].ToString();
            yield return Constrain("distance", horizontal, "130", reject: true); if (failed) yield break;
            if ((string)session.LastReceipt?["error"]?["code"] != "solver_conflict" || valid != session.Sketches[rectangle]["entities"].ToString()) { Fail("Conflicting dimension did not preserve native last valid geometry"); yield break; }
            menu.Home(); if (!Click("Undo") || !Click("Apply")) yield break; yield return Receipt("undo dimension"); if (failed) yield break;
            if (!Extent(rectangle, 0.1, 0.06)) { Fail("Undo did not restore100x60"); yield break; }
            menu.Home(); if (!Click("Redo") || !Click("Apply")) yield break; yield return Receipt("redo dimension"); if (failed) yield break;
            if (!Extent(rectangle, 0.12, 0.06)) { Fail("Redo did not restore120x60"); yield break; }
            yield return PeerSketchOwnership(rectangle, widthDimension, horizontal); if (failed) yield break;
            yield return NewSketch(); if (failed) yield break;
            string circleSketch = session.SelectedId; SketchHome(); if (!Click("Circle") || !Click("Apply")) yield break;
            yield return Receipt("native circle"); if (failed) yield break;
            string circle = null; foreach (JObject e in (JArray)session.Sketches[circleSketch]["entities"]) if ((string)e["kind"] == "circle") circle = (string)e["id"];
            yield return Constrain("diameter", circle, "30"); if (failed) yield break;
            foreach (JObject e in (JArray)session.Sketches[circleSketch]["entities"]) if ((string)e["id"] == circle && Math.Abs((double)e["radius"] - 0.015) > 1e-6) { Fail("Diameter30 did not solve radius15mm"); yield break; }
            yield return NewSketch(); if (failed) yield break;
            string angleSketch = session.SelectedId; SketchHome(); if (!Click("Line")) yield break;
            menu.SmokeNumber(3, "0"); if (!Click("Apply")) yield break; yield return Receipt("angle baseline line"); if (failed) yield break;
            SketchHome(); if (!Click("Line")) yield break; menu.SmokeNumber(2, "50"); menu.SmokeNumber(3, "50"); if (!Click("Apply")) yield break;
            yield return Receipt("angle second line"); if (failed) yield break;
            var lines = new List<string>(); foreach (JObject e in (JArray)session.Sketches[angleSketch]["entities"]) if ((string)e["kind"] == "line") lines.Add((string)e["id"]);
            yield return Constrain("angle", lines[0], "90", lines[1]); if (failed) yield break;
            var anglePoints = Points((JArray)session.Sketches[angleSketch]["entities"]); var vectors = new List<Vector2>();
            foreach (JObject e in (JArray)session.Sketches[angleSketch]["entities"]) if ((string)e["kind"] == "line") { var ep = (JArray)e["points"]; vectors.Add(anglePoints[(string)ep[1]] - anglePoints[(string)ep[0]]); }
            if (Math.Abs(Vector2.Angle(vectors[0], vectors[1]) - 90) > 0.01) { Fail("90degree dimension did not change real solved line geometry"); yield break; }
            menu.Home(); if (!Click("Save") || !Click("Apply")) yield break; yield return Receipt("save editable sketches"); if (failed) yield break;
            report["sketches"] = new JArray(session.Sketches.Values); Write();
            yield return null; yield return null;
            int activeLines = 0; foreach (var line in scene.Placement.GetComponentsInChildren<LineRenderer>())
                if (line.enabled && line.gameObject.activeInHierarchy && line.positionCount > 1 && line.sharedMaterial != null) activeLines++;
            if (activeLines == 0) { Fail("Native solver records exist but no active solved-geometry line renderer is visible after placement"); yield break; }
            report["active_solved_line_renderers"] = activeLines;
            SketchHome(); yield return null;
            yield return VideoHold(); if (failed) yield break;
            if (!NativeSmokeWorkspace.Capture(Path.ChangeExtension(output, ".png"))) { Fail("Actual solved-sketch/menu camera capture failed"); yield break; }
            report["screenshot_source"] = "Actual production camera rendered through URP; software image, not XR eye acceptance";
            report["passed"] = true; Write();
            Debug.Log("P3_CAD_PLAYER_SMOKE PASS actual menu/native solver/100x60to120x60/conflict/UndoRedo/circle/angle/Save");
            yield return new WaitForSecondsRealtime(2); WorkspaceShutdown.Quit(0);
        }
        IEnumerator VideoHold()
        {
            // Opt-in test orchestration only. An external changing-pixel check
            // must supply its own evidence; releasing this hold is not a video pass.
            string release = Environment.GetEnvironmentVariable("P3_CAD_VIDEO_HOLD_FILE");
            if (string.IsNullOrEmpty(release)) yield break;
            if (!Path.IsPathRooted(release) || File.Exists(release))
            { Fail("CAD video hold requires a fresh absolute release-marker path"); yield break; }
            long revision = session.Revision;
            string sketches = new JArray(session.Sketches.Values).ToString();
            double started = Time.realtimeSinceStartupAsDouble;
            var hold = new JObject { ["state"] = "awaiting_release", ["release_file"] = release,
                ["maximum_seconds"] = 120, ["revision"] = revision,
                ["note"] = "View-only software hold; external live-pixel evidence required" };
            report["video_hold"] = hold; Write();
            Debug.Log("P3_CAD_VIDEO_HOLD_READY view-only; bounded120s; external actual pixel evidence required");
            while (!File.Exists(release) && Time.realtimeSinceStartupAsDouble - started < 120)
            {
                if (!session.Ready || !session.SceneCurrent || session.Revision != revision)
                { Fail("Native sketch state changed or became stale during the view-only video hold"); yield break; }
                yield return null;
            }
            if (!File.Exists(release)) { Fail("CAD video hold timed out waiting for its release marker"); yield break; }
            if (!session.Ready || !session.SceneCurrent || session.Revision != revision
                || sketches != new JArray(session.Sketches.Values).ToString())
            { Fail("Native sketch state changed or became stale during the view-only video hold"); yield break; }
            hold["state"] = "released";
            hold["elapsed_seconds"] = Time.realtimeSinceStartupAsDouble - started;
            hold["native_revision_and_sketch_records_unchanged"] = true; Write();
        }
        IEnumerator NewSketch() { menu.Home(); if (!Click("Sketch") || !Click("New sketch") || !Click("XY") || !Click("Apply")) yield break; yield return Receipt("create native XY sketch"); }
        IEnumerator PeerSketchOwnership(string sketch, string widthDimension, string horizontal)
        {
            const string name = "Sketch ownership test participant";
            int port = int.Parse(Environment.GetEnvironmentVariable("CALHACKS_HOST_PORT"));
            ownershipPeer = new HostLink("127.0.0.1", port, new JObject { ["role"] = "vr", ["name"] = name,
                ["app"] = new JObject { ["name"] = "Native sketch ownership smoke", ["version"] = Application.version } });
            double until = Time.realtimeSinceStartupAsDouble + 10;
            while (peerWelcome == null && Time.realtimeSinceStartupAsDouble < until) yield return null;
            if (peerWelcome == null) { Fail("Second local sketch editor did not join"); yield break; }
            var request = new JObject { ["session_id"] = peerWelcome["session_id"], ["host_epoch"] = peerWelcome["host_epoch"],
                ["document_id"] = peerWelcome["document"]["id"], ["open_epoch"] = peerWelcome["document"]["open_epoch"],
                ["actor_id"] = peerWelcome["actor_id"], ["mode"] = "shared", ["targets"] = new JArray(sketch) };
            ownershipPeer.SendEnvelope(NativeEditSession.Envelope("lease.acquire", request));
            var overlay = menu.GetComponent<NativeOwnershipOverlay>();
            until = Time.realtimeSinceStartupAsDouble + 10;
            while ((peerLease == null || session.ConflictOwner(sketch) != name || !overlay.HasVisibleTarget(sketch))
                && Time.realtimeSinceStartupAsDouble < until) yield return null;
            if (peerLease == null || session.ConflictOwner(sketch) != name || !overlay.HasVisibleTarget(sketch))
            { Fail("Whole-sketch lease did not produce an active actual-owner overlay on solved geometry"); yield break; }
            long revision = session.Revision;
            string geometry = session.Sketches[sketch]["entities"].ToString();
            SketchHome(); editor.SmokeChoose(horizontal, constraint: widthDimension);
            if (!Click("Edit dimension")) yield break; menu.SmokeNumber(0, "130"); if (!Click("Apply")) yield break;
            if (session.Busy || !session.Notice.Contains(name) || session.Revision != revision
                || session.Sketches[sketch]["entities"].ToString() != geometry)
            { Fail("Foreign whole-sketch ownership did not block the real dimension Apply without native mutation"); yield break; }
            yield return null;
            report["baseline_owner_render"] = OwnerRenderEvidence(name);
            if (!NativeSmokeWorkspace.Capture(Path.ChangeExtension(output, ".sketch-baseline.png")))
            { Fail("Baseline ownership camera diagnostic image missing"); yield break; }
            if (!ArrangeSoftwareTabletopView()) yield break;
            yield return null; yield return null;
            var ownerRender = OwnerRenderEvidence(name);
            report["arranged_owner_render"] = ownerRender;
            if ((int?)ownerRender["glyph_vertices"] <= 0 || (bool?)ownerRender["center_in_view"] != true
                || (bool?)ownerRender["video_plane_occludes_label"] != false)
            { Fail("Arranged actual-owner text has no glyph mesh, lies outside view, or is behind the video plane"); yield break; }
            if (!NativeSmokeWorkspace.Capture(Path.ChangeExtension(output, ".sketch-pink.png")))
            { Fail("Actual solved-sketch pink ownership camera image missing"); yield break; }
            report["whole_sketch_peer_owner"] = new JObject { ["name"] = name, ["sketch"] = sketch,
                ["image"] = Path.ChangeExtension(output, ".sketch-pink.png"), ["native_revision_unchanged"] = true };
            ownershipPeer.SendEnvelope(NativeEditSession.Envelope("lease.release", new JObject { ["lease_id"] = peerLease }));
            until = Time.realtimeSinceStartupAsDouble + 10;
            while ((session.ConflictOwner(sketch) != null || overlay.HasVisibleTarget(sketch))
                && Time.realtimeSinceStartupAsDouble < until) yield return null;
            if (session.ConflictOwner(sketch) != null || overlay.HasVisibleTarget(sketch))
            { Fail("Released sketch ownership did not clear its temporary overlay"); yield break; }
            report["whole_sketch_overlay_released"] = true;
            session.Cancel(); ownershipPeer.Stop(); ownershipPeer = null;
        }
        bool ArrangeSoftwareTabletopView()
        {
            var scene = FindAnyObjectByType<HostScene>();
            softwareCamera = Camera.main.transform;
            savedCameraPose = new Pose(softwareCamera.position, softwareCamera.rotation);
            softwareCamera.position = new Vector3(softwareCamera.position.x, 1.65f, softwareCamera.position.z);
            softwareCamera.rotation = Quaternion.LookRotation(new Vector3(0, -0.85f, 1.1f), Vector3.up);
            long revision = session.Revision;
            scene.Table.BeginMove();
            var actions = FindObjectsByType<TableAction>(FindObjectsInactive.Include, FindObjectsSortMode.None);
            TableAction closer = null, place = null;
            foreach (var action in actions) { if (action.name == "Closer") closer = action; if (action.name == "Place Table") place = action; }
            if (closer == null || place == null) { Fail("Real table Closer/Place controls missing for the software tabletop view"); return false; }
            closer.Invoke(); closer.Invoke(); closer.Invoke(); place.Invoke();
            if (!scene.Table.IsPlaced || session.Revision != revision) { Fail("Software table arrangement changed native revision or failed Place"); return false; }
            report["software_tabletop_view"] = new JObject {
                ["eye"] = Vec(softwareCamera.position), ["forward"] = Vec(softwareCamera.forward),
                ["height"] = scene.Table.Height, ["distance"] = scene.Table.Distance,
                ["size"] = scene.Table.Size, ["actions"] = "Actual Closer three times and Place Table callbacks",
                ["note"] = "Explicit bounded software tabletop viewpoint; no physical headset acceptance or native coordinate change" };
            return true;
        }
        static JArray Vec(Vector3 value) => new JArray(value.x, value.y, value.z);
        JObject OwnerRenderEvidence(string owner)
        {
            var result = new JObject();
            var camera = Camera.main;
            foreach (var text in FindObjectsByType<Text>(FindObjectsSortMode.None))
            {
                if (!text.isActiveAndEnabled || text.text != owner + " is editing") continue;
                var mesh = new Mesh(); text.canvasRenderer.GetMesh(mesh);
                var viewport = camera.WorldToViewportPoint(text.transform.position);
                result["glyph_vertices"] = mesh.vertexCount; Destroy(mesh);
                result["text"] = text.text; result["rect_size"] = new JArray(text.rectTransform.rect.width, text.rectTransform.rect.height);
                result["preferred_size"] = new JArray(text.preferredWidth, text.preferredHeight);
                result["world_position"] = Vec(text.transform.position); result["viewport_center"] = Vec(viewport);
                result["camera_position"] = Vec(camera.transform.position); result["camera_forward"] = Vec(camera.transform.forward);
                result["center_in_view"] = viewport.z > camera.nearClipPlane && viewport.x >= 0 && viewport.x <= 1 && viewport.y >= 0 && viewport.y <= 1;
                var line = text.GetComponentInParent<LineRenderer>();
                if (line != null) { result["overlay_bounds_center"] = Vec(line.bounds.center); result["overlay_bounds_extents"] = Vec(line.bounds.extents); result["overlay_width"] = line.startWidth; }
                var screen = FindAnyObjectByType<BlenderScreen>();
                bool occluded = false;
                if (screen != null && screen.Visible && screen.Placement is RectTransform rect)
                {
                    var ray = new Ray(camera.transform.position, text.transform.position - camera.transform.position);
                    if (new Plane(rect.forward, rect.position).Raycast(ray, out float distance))
                        occluded = distance > 0 && distance < Vector3.Distance(ray.origin, text.transform.position)
                            && rect.rect.Contains((Vector2)rect.InverseTransformPoint(ray.GetPoint(distance)));
                    result["video_plane_position"] = Vec(rect.position); result["video_plane_normal"] = Vec(rect.forward);
                }
                result["video_plane_occludes_label"] = occluded;
                break;
            }
            return result;
        }
        void SketchHome() { menu.Home(); Click("Sketch"); }
        IEnumerator Constrain(string kind, string first, string value = null, string second = null, bool reject = false)
        {
            SketchHome(); editor.SmokeChoose(first, second); if (!Click(kind)) yield break;
            if (value != null) menu.SmokeNumber(0, value); if (!Click("Apply")) yield break; yield return Receipt(kind, reject);
        }
        IEnumerator Receipt(string step, bool reject = false)
        {
            string expected = session.LastSubmittedId;
            double until = Time.realtimeSinceStartupAsDouble + 15;
            while (session.Busy && !session.OutcomeUnknown && Time.realtimeSinceStartupAsDouble < until) yield return null;
            ((JArray)report["steps"]).Add(new JObject { ["step"] = step, ["receipt"] = session.LastReceipt?.DeepClone() }); Write();
            if (session.Busy || session.OutcomeUnknown || expected == null || (string)session.LastReceipt?["request_id"] != expected
                || (string)session.LastReceipt?["outcome"] != (reject ? "rejected" : "applied")) Fail(step + ": " + session.Notice);
        }
        bool Extent(string sketch, double width, double height)
        {
            float minX = float.PositiveInfinity, maxX = float.NegativeInfinity, minY = minX, maxY = maxX;
            foreach (var p in Points((JArray)session.Sketches[sketch]["entities"]).Values) { minX = Math.Min(minX, p.x); maxX = Math.Max(maxX, p.x); minY = Math.Min(minY, p.y); maxY = Math.Max(maxY, p.y); }
            return Math.Abs(maxX - minX - width) < 1e-6 && Math.Abs(maxY - minY - height) < 1e-6;
        }
        static Dictionary<string, Vector2> Points(JArray entities) { var result = new Dictionary<string, Vector2>(); foreach (JObject e in entities) if ((string)e["kind"] == "point") result[(string)e["id"]] = new Vector2((float)e["at"][0], (float)e["at"][1]); return result; }
        bool Click(string title) { if (failed) return false; if (menu.SmokeClick(title)) return true; Fail("Missing usable menu control: " + title); return false; }
        void Write() { Directory.CreateDirectory(Path.GetDirectoryName(output)); File.WriteAllText(output, report.ToString()); }
        void Fail(string error) { failed = true; report["passed"] = false; report["error"] = error; if (output != null) Write(); Debug.LogError("P3_CAD_PLAYER_SMOKE FAIL " + error); ownershipPeer?.Stop(); WorkspaceShutdown.Quit(2); }
        void OnDestroy()
        {
            ownershipPeer?.Stop();
            if (softwareCamera != null) softwareCamera.SetPositionAndRotation(savedCameraPose.position, savedCameraPose.rotation);
        }
    }
}


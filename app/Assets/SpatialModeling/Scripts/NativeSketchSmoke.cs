using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace SpatialModeling
{
    // Same production menu and CAD command bridge as the participant workflow.
    public sealed class NativeSketchSmoke : MonoBehaviour
    {
        WorkspaceNativeMenu menu; NativeSketchEditor editor; NativeEditSession session;
        string output; bool failed;
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
                if (line.isActiveAndEnabled && line.gameObject.activeInHierarchy && line.positionCount > 1 && line.sharedMaterial != null) activeLines++;
            if (activeLines == 0) { Fail("Native solver records exist but no active solved-geometry line renderer is visible after placement"); yield break; }
            report["active_solved_line_renderers"] = activeLines; report["passed"] = true; Write();
            SketchHome(); ScreenCapture.CaptureScreenshot(Path.ChangeExtension(output, ".png"));
            Debug.Log("P3_CAD_PLAYER_SMOKE PASS actual menu/native solver/100x60to120x60/conflict/UndoRedo/circle/angle/Save");
            yield return new WaitForSecondsRealtime(2); WorkspaceShutdown.Quit(0);
        }
        IEnumerator NewSketch() { menu.Home(); if (!Click("Sketch") || !Click("New sketch") || !Click("XY") || !Click("Apply")) yield break; yield return Receipt("create native XY sketch"); }
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
        void Fail(string error) { failed = true; report["passed"] = false; report["error"] = error; if (output != null) Write(); Debug.LogError("P3_CAD_PLAYER_SMOKE FAIL " + error); WorkspaceShutdown.Quit(2); }
    }
}


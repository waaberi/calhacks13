using System;
using System.Collections;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace SpatialModeling
{
    // Opt-in isolated acceptance harness. Uses real menu callbacks, fields and production HostLink.
    // It must only be launched against tests/backend/p3_host_smoke.py, never a personal document.
    public sealed class NativeMenuSmoke : MonoBehaviour
    {
        WorkspaceNativeMenu menu;
        NativeEditSession session;
        readonly JObject report = new JObject { ["physical_headset"] = "not tested", ["second_pc"] = "not tested", ["steps"] = new JArray() };
        double deadline;
        string output;
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            if (Array.Exists(Environment.GetCommandLineArgs(), arg => arg == "-p3-native-smoke"))
                new GameObject("Isolated native menu smoke").AddComponent<NativeMenuSmoke>();
        }
        void Start()
        {
            output = Environment.GetEnvironmentVariable("P3_PLAYER_SMOKE_REPORT");
            int.TryParse(Environment.GetEnvironmentVariable("CALHACKS_HOST_PORT"), out var port);
            if (string.IsNullOrEmpty(output) || !Path.IsPathRooted(output) || port < 1024 || port == 8765)
            { Debug.LogError("P3 smoke requires explicit isolated port and absolute P3_PLAYER_SMOKE_REPORT"); WorkspaceShutdown.Quit(3); return; }
            StartCoroutine(Run());
        }
        IEnumerator Run()
        {
            deadline = Time.realtimeSinceStartupAsDouble + 30;
            while ((menu = FindAnyObjectByType<WorkspaceNativeMenu>()) == null && Time.realtimeSinceStartupAsDouble < deadline) yield return null;
            if (menu == null) { Fail("Native menu was not installed"); yield break; }
            session = menu.Session;
            while ((!session.Ready || !session.SceneCurrent) && Time.realtimeSinceStartupAsDouble < deadline) yield return null;
            if (!session.Ready || !session.SceneCurrent || !session.CanEdit) { Fail("No current editable isolated host scene"); yield break; }
            var scene = FindAnyObjectByType<HostScene>();
            if (!NativeSmokeWorkspace.Place(scene) || NativeSmokeWorkspace.ActiveModelRenderers(scene) == 0)
            { Fail("Software pose / real Place Table action did not reveal active native renderers"); yield break; }
            report["placement"] = "Bounded software test pose; actual Place Table callback and active model renderers; physical placement not tested";
            string[] shapes = { "Cube", "Sphere", "Cylinder" }; var ids = new string[3];
            for (int i = 0; i < shapes.Length; i++)
            {
                menu.Home(); if (!Click(shapes[i])) yield break;
                menu.SmokeNumber(0, (i * 30).ToString()); menu.SmokeNumber(1, "0"); menu.SmokeNumber(2, "0");
                if (!Click("Apply")) yield break;
                yield return Receipt("add " + shapes[i]); if (!Success()) yield break;
                ids[i] = session.SelectedId;
            }
            session.Select(ids[0]); menu.Home(); if (!Click("Move object")) yield break;
            long beforeCancel = session.Revision; if (!Click("Cancel / Back")) yield break;
            yield return new WaitForSecondsRealtime(0.25f);
            if (session.Revision != beforeCancel) { Fail("Cancel changed native revision"); yield break; }
            Step("Cancel", new JObject { ["revision_unchanged"] = true });
            if (!Click("Move object") || !Click("Apply")) yield break;
            yield return Receipt("move 10mm"); if (!Success()) yield break;
            var location = session.Objects[ids[0]]["transform"]?["location"] as JArray;
            if (location == null || Math.Abs((double)location[0] - 0.01) > 1e-6) { Fail("Native snapshot did not confirm +10mm X"); yield break; }
            menu.Home(); if (!Click("Rotate object") || !Click("Apply")) yield break;
            yield return Receipt("rotate 90deg"); if (!Success()) yield break;
            var rotation = session.Objects[ids[0]]["transform"]?["rotation"] as JArray;
            if (rotation == null || Math.Abs(Math.Abs((double)rotation[3]) - Math.Sqrt(0.5)) > 1e-4) { Fail("Native snapshot did not confirm 90deg Z"); yield break; }
            menu.Home(); if (!Click("Scale object")) yield break; menu.SmokeNumber(0, "1.5");
            if (!Click("Apply")) yield break; yield return Receipt("scale"); if (!Success()) yield break;
            // Submit an intentionally stale target through the same real Apply callback.
            menu.Home(); if (!Click("Move object")) yield break;
            session.Draft["target"]["generation"] = Math.Max(0, (long)session.Draft["target"]["generation"] - 1);
            if (!Click("Apply")) yield break; yield return Receipt("stale rejection", false); if (aborted) yield break;
            if ((string)session.LastReceipt?["outcome"] != "rejected") { Fail("Stale target was not rejected"); yield break; }
            session.Select(ids[2]); menu.Home(); if (!Click("Delete object") || !Click("Apply")) yield break;
            yield return Receipt("delete"); if (!Success()) yield break;
            if (session.Objects.ContainsKey(ids[2])) { Fail("Deleted object remained current"); yield break; }
            menu.Home(); if (!Click("Undo") || !Click("Apply")) yield break; yield return Receipt("undo delete"); if (!Success()) yield break;
            if (!session.Objects.ContainsKey(ids[2])) { Fail("Undo failed to restore native object"); yield break; }
            menu.Home(); if (!Click("Redo") || !Click("Apply")) yield break; yield return Receipt("redo delete"); if (!Success()) yield break;
            if (session.Objects.ContainsKey(ids[2])) { Fail("Redo did not remove native object"); yield break; }
            menu.Home(); if (!Click("Undo") || !Click("Apply")) yield break; yield return Receipt("restore cylinder"); if (!Success()) yield break;
            menu.Home(); if (!Click("Save") || !Click("Apply")) yield break; yield return Receipt("save"); if (!Success()) yield break;
            report["object_ids"] = new JArray(ids); report["document"] = session.Document.DeepClone();
            report["objects"] = new JArray(session.Objects.Values); report["source"] = Application.buildGUID;
            session.Select(ids[0]);
            menu.Home();
            yield return null;
            if (!NativeSmokeWorkspace.Capture(Path.ChangeExtension(output, ".png"))) { Fail("Actual placed-scene/menu camera capture failed"); yield break; }
            report["screenshot_source"] = "Actual production camera rendered through URP to1920x1080/MSAA4; software evidence, not XR eye capture";
            report["passed"] = true; Write();
            Debug.Log("P3_NATIVE_PLAYER_SMOKE PASS real menu/fields/leases/commands/native receipts/10mm/90deg/cancel/stale/history/save");
            yield return new WaitForSecondsRealtime(2); WorkspaceShutdown.Quit(0);
        }
        bool aborted;
        bool Click(string title) { if (menu.SmokeClick(title)) return true; Fail("Missing usable menu control: " + title); return false; }
        IEnumerator Receipt(string name, bool requireApplied = true)
        {
            string expected = session.LastSubmittedId;
            double until = Time.realtimeSinceStartupAsDouble + 15;
            while (session.Busy && !session.OutcomeUnknown && Time.realtimeSinceStartupAsDouble < until) yield return null;
            if (session.Busy || session.OutcomeUnknown || expected == null || (string)session.LastReceipt?["request_id"] != expected)
            { Fail(name + ": no matching definitive native receipt: " + session.Notice); yield break; }
            Step(name, session.LastReceipt);
            if (requireApplied && (string)session.LastReceipt?["outcome"] != "applied") Fail(name + ": " + session.Notice);
        }
        bool Success() => !aborted && (string)session.LastReceipt?["outcome"] == "applied";
        void Step(string name, JObject result) { ((JArray)report["steps"]).Add(new JObject { ["step"] = name, ["result"] = result?.DeepClone() }); Write(); }
        void Write() { Directory.CreateDirectory(Path.GetDirectoryName(output)); File.WriteAllText(output, report.ToString()); }
        void Fail(string error) { aborted = true; report["passed"] = false; report["error"] = error; if (output != null) Write(); Debug.LogError("P3_NATIVE_PLAYER_SMOKE FAIL " + error); WorkspaceShutdown.Quit(2); }
    }
}


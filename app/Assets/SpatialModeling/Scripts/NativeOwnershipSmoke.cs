using System;
using System.Collections;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UI;

namespace SpatialModeling
{
    // Real second protocol participant on this PC; does not claim a second-PC or native bypass pass.
    public sealed class NativeOwnershipSmoke : MonoBehaviour
    {
        WorkspaceNativeMenu menu; NativeEditSession session; HostLink peer;
        JObject welcome; string lease, output; bool failed;
        readonly JObject report = new JObject { ["second_pc"] = "not tested: two local participants", ["strict_native_locking"] = "not tested", ["physical_headset"] = "not tested" };
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install() { if (Array.Exists(Environment.GetCommandLineArgs(), a => a == "-p3-ownership-smoke")) new GameObject("Native ownership menu smoke").AddComponent<NativeOwnershipSmoke>(); }
        void Start()
        {
            output = Environment.GetEnvironmentVariable("P3_PLAYER_SMOKE_REPORT");
            int.TryParse(Environment.GetEnvironmentVariable("CALHACKS_HOST_PORT"), out var port);
            if (string.IsNullOrEmpty(output) || !Path.IsPathRooted(output) || port < 1024 || port == 8765) { WorkspaceShutdown.Quit(3); return; }
            StartCoroutine(Run(port));
        }
        void Update()
        {
            if (peer == null) return;
            while (peer.Events.TryDequeue(out var e)) if (e.RawMessage?["payload"] is JObject p)
            {
                if ((string)e.RawMessage["type"] == "welcome") welcome = p;
                if ((string)e.RawMessage["type"] == "lease.granted") lease = (string)p["lease"]?["lease_id"];
            }
        }
        IEnumerator Run(int port)
        {
            double until = Time.realtimeSinceStartupAsDouble + 30;
            while ((menu = FindAnyObjectByType<WorkspaceNativeMenu>()) == null && Time.realtimeSinceStartupAsDouble < until) yield return null;
            if (menu == null) { Fail("Menu missing"); yield break; }
            session = menu.Session;
            while ((!session.Ready || !session.SceneCurrent) && Time.realtimeSinceStartupAsDouble < until) yield return null;
            if (!session.Ready || !session.SceneCurrent || session.Objects.Count == 0) { Fail("No current native reference object"); yield break; }
            var scene = FindAnyObjectByType<HostScene>();
            if (!NativeSmokeWorkspace.Place(scene) || NativeSmokeWorkspace.ActiveModelRenderers(scene) == 0)
            { Fail("Real Place Table action did not expose active object renderers"); yield break; }
            report["placement"] = "Bounded software test pose and real Place Table callback; no physical placement pass";
            yield return null; // Let the real menu presentation react to explicit Place.
            menu.Home(); if (!Click("Pin menu")) yield break;
            var menuPanel = GameObject.Find("Native edit controls").transform;
            var pinnedPose = new Pose(menuPanel.position, menuPanel.rotation);
            var camera = Camera.main.transform;
            var softwareHand = new Pose(camera.TransformPoint(new Vector3(WorkspaceHandPreference.Left ? 0.2f : -0.2f, -0.15f, 0.55f)), camera.rotation);
            menu.UpdateMenuHand(WorkspaceHandPreference.MenuHand, softwareHand);
            yield return null;
            if (!menu.Pinned || Vector3.Distance(menuPanel.position, pinnedPose.position) > 1e-5f
                || Quaternion.Angle(menuPanel.rotation, pinnedPose.rotation) > 0.001f) { Fail("Pinned menu moved with the bounded software hand"); yield break; }
            if (!Click("Hold menu")) yield break;
            menu.UpdateMenuHand(WorkspaceHandPreference.MenuHand, softwareHand);
            yield return null;
            if (menu.Pinned || Vector3.Distance(menuPanel.position, pinnedPose.position) < 0.01f) { Fail("Held menu did not follow the bounded software hand"); yield break; }
            menu.TrackingLost(WorkspaceHandPreference.MenuHand); yield return null;
            report["menu_pin_hold_software_pose"] = true;
            string target = null; foreach (var id in session.Objects.Keys) { target = id; break; }
            peer = new HostLink("127.0.0.1", port, new JObject { ["role"] = "vr", ["name"] = "Ownership test participant", ["app"] = new JObject { ["name"] = "Native ownership smoke", ["version"] = "1" } });
            until = Time.realtimeSinceStartupAsDouble + 10;
            while (welcome == null && Time.realtimeSinceStartupAsDouble < until) yield return null;
            if (welcome == null) { Fail("Second local participant did not join"); yield break; }
            var identity = new JObject { ["session_id"] = welcome["session_id"], ["host_epoch"] = welcome["host_epoch"], ["document_id"] = welcome["document"]["id"], ["open_epoch"] = welcome["document"]["open_epoch"], ["actor_id"] = welcome["actor_id"], ["mode"] = "shared", ["targets"] = new JArray(target) };
            peer.SendEnvelope(NativeEditSession.Envelope("lease.acquire", identity));
            until = Time.realtimeSinceStartupAsDouble + 10;
            while ((lease == null || session.ConflictOwner(target) == null) && Time.realtimeSinceStartupAsDouble < until) yield return null;
            if (lease == null || session.ConflictOwner(target) != "Ownership test participant") { Fail("Actual participant lease was not broadcast to VR"); yield break; }
            yield return null; yield return null;
            bool label = false; foreach (var text in FindObjectsByType<Text>(FindObjectsSortMode.None)) if (text.isActiveAndEnabled && text.GetComponentInParent<Canvas>()?.isActiveAndEnabled == true && text.text == "Ownership test participant is editing") label = true;
            bool pink = false; foreach (var line in FindObjectsByType<LineRenderer>(FindObjectsSortMode.None))
                if (line.gameObject.name == "Temporary ownership overlay" && line.enabled && line.gameObject.activeInHierarchy && line.positionCount > 0 && line.sharedMaterial != null) pink = true;
            if (!label || !pink) { Fail("Active actual-owner world canvas / pink line renderer missing"); yield break; }
            report["real_owner_label"] = true; report["lease"] = lease;
            session.Select(target); menu.Home(); if (!Click("Move object") || !Click("Apply")) yield break;
            if (session.Busy || !session.Notice.Contains("Ownership test participant")) { Fail("Known conflict allowed a native command or hid owner"); yield break; }
            report["conflicting_apply_blocked"] = true;
            long revision = session.Revision;
            var before = scene.Placement.position; scene.Table.BeginMove(); scene.Table.Adjust(0.1f, 0.1f, 0, 10, new Vector3(0, 1.65f, 0), Vector3.forward);
            bool moved = Vector3.Distance(before, scene.Placement.position) > 0.01f; scene.Table.CancelMove();
            if (!moved || session.Revision != revision) { Fail("Inspection placement failed or changed native revision under another editor's lock"); yield break; }
            foreach (JObject l in session.Leases) if ((string)l["owner"]?["actor_id"] == session.ActorId) { Fail("Inspection acquired an editing lock"); yield break; }
            report["inspection_selection_table_move_without_native_lock"] = true;
            yield return null;
            if (!NativeSmokeWorkspace.Capture(Path.ChangeExtension(output, ".pink.png"))) { Fail("Actual placed ownership/menu camera capture failed"); yield break; }
            report["screenshot_source"] = "Actual production camera/placed geometry/owner overlay rendered through URP; no XR eye or physical acceptance";
            peer.SendEnvelope(NativeEditSession.Envelope("lease.release", new JObject { ["lease_id"] = lease }));
            until = Time.realtimeSinceStartupAsDouble + 10;
            while (session.ConflictOwner(target) != null && Time.realtimeSinceStartupAsDouble < until) yield return null;
            if (session.ConflictOwner(target) != null) { Fail("Released ownership remained active"); yield break; }
            session.Cancel(); menu.Home(); if (!Click("Settings") || !Click("Shared") || !Click("Back")) yield break;
            if (session.Mode != "shared") { Fail("Shared mode setting failed"); yield break; }
            if (!Click("Move object") || !Click("Apply")) yield break;
            string request = session.LastSubmittedId;
            until = Time.realtimeSinceStartupAsDouble + 15;
            while (session.Busy && Time.realtimeSinceStartupAsDouble < until) yield return null;
            if ((string)session.LastReceipt?["request_id"] != request || (string)session.LastReceipt?["outcome"] != "applied") { Fail("Edit after release was not confirmed by native Blender"); yield break; }
            report["write_after_release_receipt"] = session.LastReceipt.DeepClone();
            menu.Home(); if (!Click("Settings") || !Click("Exclusive") || !Click("Back")) yield break;
            if (session.Mode != "exclusive") { Fail("Exclusive mode setting failed"); yield break; }
            peer.Stop(); peer = null;
            report["passed"] = true; Write();
            Debug.Log("P3_OWNERSHIP_PLAYER_SMOKE PASS actual peer lease/name/pink overlay/conflict/inspection/release/modes/native write");
            yield return new WaitForSecondsRealtime(2); WorkspaceShutdown.Quit(0);
        }
        bool Click(string title) { if (failed) return false; if (menu.OwnershipSmokeClick(title)) return true; Fail("Missing menu control " + title); return false; }
        void Write() { Directory.CreateDirectory(Path.GetDirectoryName(output)); File.WriteAllText(output, report.ToString()); }
        void Fail(string error) { failed = true; report["passed"] = false; report["error"] = error; if (output != null) Write(); Debug.LogError("P3_OWNERSHIP_PLAYER_SMOKE FAIL " + error); peer?.Stop(); WorkspaceShutdown.Quit(2); }
        void OnDestroy() => peer?.Stop();
    }
}

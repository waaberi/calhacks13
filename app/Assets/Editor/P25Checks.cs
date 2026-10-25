using System;
using System.Collections.Generic;
using System.Reflection;
using Newtonsoft.Json.Linq;
using SpatialModeling;
using UnityEditor;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;
using UnityEngine.UI;

// Edit-time deterministic checks only. No input injection, network or runtime launch.
public static class P25Checks
{
    static void Check(bool value, string why)
    {
        if (!value) throw new Exception("P2.5: " + why);
    }

    static void Mapped(Rect image, Rect uv, Vector2 point, Vector2 expected, string why)
    {
        Check(PreviewInputMapping.TryMap(image, uv, point, out var actual), why + " maps");
        Check(Vector2.Distance(actual, expected) < .00001f, why + " has expected native coordinates");
    }

    public static void Run()
    {
        RunMapping(message => Debug.Log(message));
        RunTransport(message => Debug.Log(message));
        RunInputProtocol(message => Debug.Log(message));
        P25WindowChecks.Run(message => Debug.Log(message));
        P25ObjectChecks.Run(message => Debug.Log(message));
        P25ShortcutChecks.Run(message => Debug.Log(message));
        P25NumericChecks.Run(message => Debug.Log(message));
        RunTargets(message => Debug.Log(message));
        RunSpatial(message => Debug.Log(message));
        RunPreviewOcclusion();
        // Old alternate editing menus are retired. Their historical fixtures
        // remain preserved; test the delivered native-only surface instead.
        P25CommonUiChecks.RunNativeOnly();
        P25WindowUiChecks.Run();
    }

    public static void RunCumulativeEditor()
    {
        Run();
        P2Checks.Run();
        ArrangementChecks.Run();
        WorkspaceChecks.Run();
        // The synthetic player-update fixture must be the final Input System
        // consumer; legacy pose gates use the pristine Editor buffer directly.
        RunKeyboardIsolation();
        Debug.Log("P25_CUMULATIVE_EDITOR_CHECK PASS P25 plus unchanged P2/arrangement/P1 gates plus final keyboard isolation; no Player build or launch");
    }

    // The same actual mapping gate can run under the bundled managed runtime,
    // without Unity native initialization, by supplying Console.WriteLine.
    public static void RunMapping(Action<string> report)
    {
        var image = new Rect(-900, -550, 1800, 1100);
        var full = new Rect(0, 0, 1, 1);
        Mapped(image, full, Vector2.zero, new Vector2(.5f, .5f), "full window centre");
        Mapped(image, full, new Vector2(-900, -550), new Vector2(0, 1), "bottom-left image corner");
        Mapped(image, full, new Vector2(900, 550), new Vector2(1, 0), "top-right image corner");
        var crop = new Rect(.25f, .2f, .5f, .5f);
        Mapped(image, crop, Vector2.zero, new Vector2(.5f, .55f), "panned magnified centre");
        Mapped(image, crop, new Vector2(-900, -550), new Vector2(.25f, .8f), "magnified bottom-left");
        Mapped(image, crop, new Vector2(900, 550), new Vector2(.75f, .3f), "magnified top-right");
        // Non-centred image rect prevents an implicit assumption that the pivot is always .5.
        Mapped(new Rect(100, 200, 800, 400), full, new Vector2(300, 500), new Vector2(.25f, .25f), "offset image pivot");
        foreach (var point in new[] { new Vector2(-901, 0), new Vector2(901, 0),
            new Vector2(0, -551), new Vector2(0, 551), new Vector2(float.NaN, 0),
            new Vector2(float.PositiveInfinity, 0) })
            Check(!PreviewInputMapping.TryMap(image, full, point, out _), "outside/nonfinite point cannot click native UI");
        Check(!PreviewInputMapping.TryMap(new Rect(0, 0, 0, 10), full, Vector2.zero, out _), "zero-width image refuses input");
        Check(!PreviewInputMapping.TryMap(image, new Rect(0, 0, 0, 1), Vector2.zero, out _), "zero-width crop refuses input");
        Check(!PreviewInputMapping.TryMap(image, new Rect(-.1f, 0, 1, 1), Vector2.zero, out _), "crop outside source refuses input");
        Check(!PreviewInputMapping.TryMap(image, new Rect(0, 0, float.NaN, 1), Vector2.zero, out _), "nonfinite crop refuses input");
        // Exhaust all input-routing combinations. Only the explicitly active, fresh,
        // right/primary hand over the image without a grip can issue native pointer input.
        for (int bits = 0; bits < 32; bits++)
        {
            bool enabled = (bits & 1) != 0, fresh = (bits & 2) != 0,
                primary = (bits & 4) != 0, gripping = (bits & 8) != 0, hit = (bits & 16) != 0;
            bool expected = bits == 23; // enabled + fresh + primary + image hit; no grip.
            Check(PreviewInputMapping.CanRoute(enabled, fresh, primary, gripping, hit) == expected,
                "native routing requires current image and one hand, and excludes panel grabbing");
        }
        Check(PreviewInputMapping.FrameMatches("helper-A", 4, "helper-A", 4), "same displayed/helper capture identity can admit input");
        Check(!PreviewInputMapping.FrameMatches("helper-A", 3, "helper-A", 4), "old selected-window frame cannot operate the new capture target");
        Check(!PreviewInputMapping.FrameMatches("helper-A", 4, "helper-B", 4), "helper restart cannot reuse previous image identity");
        Check(!PreviewInputMapping.FrameMatches("", 0, "", 0), "missing image identity cannot authorize input");
        Check(!PreviewInputMapping.FrameMatches("helper-A", -1, "helper-A", -1), "unset frame generation cannot authorize input");
        report("P25_MAPPING_CHECK PASS full-window/UV-crop/pan/pivot/finite/edge/stale/grip/hand routing; native runtime acceptance=False");
    }

    public static void RunTransport(Action<string> report)
    {
        var transport = new PreviewInputTransportState();
        bool refused = false;
        try { transport.TakeSequence(); } catch (InvalidOperationException) { refused = true; }
        Check(refused, "no POST may be numbered before authoritative helper state");
        transport.Observe("helper-A", 1);
        Check(transport.TakeSequence() == 1, "first POST uses the helper's exact next number");
        transport.Unknown();
        refused = false;
        try { transport.TakeSequence(); } catch (InvalidOperationException) { refused = true; }
        Check(refused, "uncertain POST cannot advance to another action before a fresh GET");
        // The network may fail before the helper consumes the request. A later
        // cleanup release must use 1, even though local numbering reached 2.
        transport.Observe("helper-A", 1);
        Check(transport.TakeSequence() == 1, "unconsumed uncertain POST resets exactly to server sequence, rather than Math.Max");
        transport.Unknown();
        // The server may instead consume the same failed request. Its GET is
        // authoritative here as well; neither assumption permits mutation replay.
        transport.Observe("helper-A", 2);
        Check(transport.TakeSequence() == 2, "consumed uncertain POST continues at server's next number");
        transport.Observe("helper-B", 1);
        Check(transport.Session == "helper-B" && transport.TakeSequence() == 1,
            "new helper/session resets numbering without carrying a previous instance counter");
        foreach (var invalid in new[] { 0L, -1L })
        {
            refused = false;
            try { transport.Observe("helper-B", invalid); } catch (ArgumentException) { refused = true; }
            Check(refused, "invalid helper next sequence is refused");
        }
        report("P25_TRANSPORT_CHECK PASS unknown-barrier/authoritative-consumed-or-unconsumed-number/helper-restart; HTTP runtime not exercised");
    }

    public static void RunInputProtocol(Action<string> report)
    {
        var state = new JObject {
            ["enabled"] = true, ["ready"] = true, ["focused"] = true, ["release_error"] = false,
            ["session"] = "session-A", ["token"] = "test-token", ["next_seq"] = 1,
            ["helper_pid"] = 123, ["capture_generation"] = 4, ["capture_instance"] = "capture-A",
            ["capture_geometry"] = "geometry-A", ["reason"] = "",
            ["selection"] = new JObject { ["hwnd"] = 456, ["pid"] = 789 }, ["windows"] = new JArray()
        };
        Check(PreviewInputProtocol.TryState(state.ToString(), out var parsed) && (string)parsed["session"] == "session-A",
            "valid selected-window helper state is admitted");
        var disabled = (JObject)state.DeepClone();
        disabled["enabled"] = disabled["ready"] = disabled["focused"] = false;
        disabled["token"] = disabled["selection"] = disabled["capture_geometry"] = null;
        Check(PreviewInputProtocol.TryState(disabled.ToString(), out _), "disabled/no-window helper state remains readable for recovery");
        Check(PreviewInputProtocol.TryState("{\"enabled\":false,\"ready\":false,\"reason\":\"input_disabled\"}", out var captureOnly)
            && captureOnly["token"] == null && captureOnly["session"] == null,
            "capture-only helper setup response is readable without creating input credentials");
        Check(!PreviewInputProtocol.TryState("{\"enabled\":true,\"ready\":false,\"reason\":\"input_disabled\"}", out _),
            "compact state never admits an enabled input helper");
        foreach (var invalid in new[] {
            new JObject { ["next_seq"] = "not-a-number" }, new JObject { ["next_seq"] = 0 },
            new JObject { ["next_seq"] = true }, new JObject { ["ready"] = "true" },
            new JObject { ["focused"] = 1 }, new JObject { ["session"] = new JObject() },
            new JObject { ["token"] = "" }, new JObject { ["capture_generation"] = -1 },
            new JObject { ["selection"] = new JObject { ["hwnd"] = "456", ["pid"] = 789 } },
            new JObject { ["windows"] = new JArray("not-a-window") }, new JObject { ["release_error"] = "false" }
        })
        {
            var bad = (JObject)state.DeepClone();
            foreach (var property in invalid.Properties()) bad[property.Name] = property.Value.DeepClone();
            Check(!PreviewInputProtocol.TryState(bad.ToString(), out _), "wrong-typed/invalid helper state fails closed without stopping its reader");
        }
        var huge = (JObject)state.DeepClone();
        huge["next_seq"] = JToken.Parse("9223372036854775808");
        Check(!PreviewInputProtocol.TryState(huge.ToString(), out _), "out-of-range sequence cannot overflow the input owner");
        Check(PreviewInputProtocol.Acknowledged("{\"ok\":true,\"seq\":7}", 7), "matching explicit dispatch acknowledgement is accepted");
        foreach (var invalid in new[] { "{}", "{\"ok\":false,\"seq\":7}", "{\"ok\":\"true\",\"seq\":7}",
            "{\"ok\":true,\"seq\":8}", "{\"ok\":true,\"seq\":\"7\"}",
            "{\"ok\":true,\"seq\":9223372036854775808}", "not-json", "[]" })
            Check(!PreviewInputProtocol.Acknowledged(invalid, 7), "HTTP 200 without an exact positive acknowledgement never proves native release/focus");
        report("P25_INPUT_PROTOCOL_CHECK PASS typed-state/no-window/recovery/overflow/exact-ack; no OS input or native GUI");
    }

    public static void RunSpatial(Action<string> report)
    {
        Check(PreviewSketchMapping.TryMapRay(new Ray(new Vector3(.1f, 1, .06f), Vector3.down),
            Matrix4x4.identity, Vector3.zero, Quaternion.identity, out var native, out var hit),
            "native XY plane can receive a world-space controller ray");
        Check(Vector2.Distance(native, new Vector2(.1f, .06f)) < .00001f
            && Vector3.Distance(hit, new Vector3(.1f, 0, .06f)) < .00001f,
            "Z-up metres convert once to Unity Y-up without changing 100x60mm dimensions");
        // Independently calculated: 90 degrees around world Y, scale 5/7/3 and
        // translation (2,.8,-1). The source plane origin is native (.03,-.02,.04).
        var display = new Matrix4x4(new Vector4(0, 0, -5, 0), new Vector4(0, 7, 0, 0),
            new Vector4(3, 0, 0, 0), new Vector4(2, .8f, -1, 1));
        var origin = new Vector3(.03f, -.02f, .04f);
        var expectedWorld = new Vector3(2.12f, 1.08f, -1.65f);
        Check(PreviewSketchMapping.TryMapRay(new Ray(expectedWorld + Vector3.up * 2, Vector3.down),
            display, origin, Quaternion.identity, out native, out hit), "rotated and magnified display accepts ray");
        Check(Vector2.Distance(native, new Vector2(.1f, .06f)) < .00001f
            && Vector3.Distance(hit, expectedWorld) < .00001f,
            "table translation, rotation and nonuniform magnification never become native sketch units");
        Check(Vector3.Distance(PreviewSketchMapping.WorldPoint(new Vector2(.1f, .06f), display,
            origin, Quaternion.identity), expectedWorld) < .00001f, "native result is displayed at independently expected world point");
        float half = .70710678118f;
        var x90 = new Quaternion(half, 0, 0, half);
        Check(PreviewSketchMapping.TryMapRay(new Ray(new Vector3(.1f, .06f, 1), Vector3.back),
            Matrix4x4.identity, Vector3.zero, x90, out native, out _)
            && Vector2.Distance(native, new Vector2(.1f, .06f)) < .00001f,
            "rotated native workplane uses its actual basis, rather than always projecting onto a horizontal table");
        Check(!PreviewSketchMapping.TryMapRay(new Ray(Vector3.up, Vector3.right), Matrix4x4.identity,
            Vector3.zero, Quaternion.identity, out _, out _), "parallel aim cannot author a point");
        Check(!PreviewSketchMapping.TryMapRay(new Ray(Vector3.up, Vector3.up), Matrix4x4.identity,
            Vector3.zero, Quaternion.identity, out _, out _), "plane behind the controller cannot author a point");
        Check(!PreviewSketchMapping.TryMapRay(new Ray(Vector3.up, Vector3.down), Matrix4x4.zero,
            Vector3.zero, Quaternion.identity, out _, out _), "singular display never invents native geometry");
        Check(!PreviewSketchMapping.TryMapRay(new Ray(new Vector3(float.NaN, 1, 0), Vector3.down),
            Matrix4x4.identity, Vector3.zero, Quaternion.identity, out _, out _), "invalid tracking point cannot author geometry");
        Check(!PreviewSketchMapping.TryMapRay(new Ray(Vector3.up, Vector3.down), Matrix4x4.identity,
            Vector3.zero, new Quaternion(0, 0, 0, 0), out _, out _), "invalid native workplane orientation refuses drawing");
        report("P25_SPATIAL_MAPPING_CHECK PASS native-axis/metres/known-world-point/display-scale/native-rotated-plane/parallel/behind/singular/nonfinite; physical drawing acceptance=False");
    }

    public static void RunTargets(Action<string> report)
    {
        var a = new JObject { ["id"] = "native-A", ["name"] = "Previously active sketch" };
        var b = new JObject { ["id"] = "new-B", ["name"] = "Newly created sketch" };
        var c = new JObject { ["id"] = "native-C", ["name"] = "Later native choice" };
        var sketches = new Dictionary<string, JObject> { ["native-A"] = a, ["new-B"] = b, ["native-C"] = c };
        var nativeA = new JObject { ["sketch_id"] = "native-A", ["native_tool"] = "line", ["available"] = true, ["mode"] = "OBJECT" };
        Check(SpatialSketchTarget.CanStartCreation(true, nativeA), "fresh native Object Mode can start sketch creation");
        Check(!SpatialSketchTarget.CanStartCreation(false, nativeA), "stale native tool state cannot start sketch creation");
        var unavailable = (JObject)nativeA.DeepClone(); unavailable["available"] = false;
        Check(!SpatialSketchTarget.CanStartCreation(true, unavailable), "missing native CAD cannot create a sketch");
        var editMode = (JObject)nativeA.DeepClone(); editMode["mode"] = "EDIT_MESH";
        Check(!SpatialSketchTarget.CanStartCreation(true, editMode), "native edit mode cannot create a sketch under stale Object assumptions");
        Func<string, string, string, JObject> receipt = (request, outcome, op) => new JObject {
            ["type"] = "result", ["payload"] = new JObject { ["request_id"] = request,
                ["outcome"] = outcome, ["op"] = op, ["created"] = new JArray("new-B") } };
        var target = new SpatialSketchTarget();
        target.ObserveContext(nativeA);
        Check(target.Resolve("native-A", "new-B", sketches) == a, "ordinary native toolbar selection governs before a confirmed local creation");
        target.BeginCreate("create-B", nativeA);
        Check(!target.Receive(receipt("unrelated", "applied", "sketch.create"), sketches), "another command receipt cannot change the drawing target");
        Check(!target.Receive(receipt("create-B", "pending", "sketch.create"), sketches), "pending receipt cannot select uncommitted geometry");
        Check(target.Receive(receipt("create-B", "applied", "sketch.create"), sketches)
            && target.Resolve("native-A", "native-A", sketches) == b,
            "newly confirmed sketch B receives drawing even while native telemetry still names A");
        sketches.Remove("new-B");
        Check(target.Resolve("native-A", "native-A", sketches) == null && target.MissingExplicitTarget,
            "removing B cannot silently redirect the next stroke to A");
        target.ObserveContext(nativeA);
        Check(target.Resolve("native-A", "native-A", sketches) == null,
            "repeated unchanged native state cannot clear a removed-target refusal");
        target.ObserveContext(new JObject { ["sketch_id"] = "native-C", ["native_tool"] = "circle" });
        Check(target.Resolve("native-C", "native-A", sketches) == c, "genuine new native selection/tool context becomes the spatial target");
        target.Reset();
        target.BeginCreate("create-before-scene", nativeA);
        Check(target.Receive(receipt("create-before-scene", "applied", "sketch.create"), sketches)
            && target.Resolve("native-A", "native-A", sketches) == null && target.WaitingForExplicitTarget,
            "receipt before B's scene record waits for B instead of using A");
        sketches["new-B"] = b;
        Check(target.Resolve("native-A", "native-A", sketches) == b && !target.WaitingForExplicitTarget,
            "matching authoritative B scene record safely resolves the pending target");
        target.Reset();
        target.BeginCreate("rejected-create", nativeA);
        Check(!target.Receive(receipt("rejected-create", "rejected", "sketch.create"), sketches)
            && target.Resolve("native-A", "new-B", sketches) == a, "rejected creation preserves native targeting");
        target.BeginCreate("different-op", nativeA);
        Check(!target.Receive(receipt("different-op", "applied", "sketch.add_line"), sketches),
            "non-creation receipt cannot replace the drawing target");
        target.Reset();
        Check(target.Resolve("native-A", "new-B", sketches) == a, "leaving/resetting spatial mode restores ordinary native targeting");
        report("P25_SPATIAL_TARGET_CHECK PASS confirmed-new-sketch/stale-native-selection/late-scene-record/removed-target/native-switch/rejected-receipt; no native mutations");
    }

    public static void RunKeyboardIsolation()
    {
        // Input System 1.20.1 uses a separate Editor state buffer outside Play.
        // Its first wasPressedThisFrame read requires the player update-step
        // counter. The package's nonpersisted test flag runs real player input
        // updates in edit mode, independently of Game View focus; no Play/XR.
        const string playerUpdates = "RUN_PLAYER_UPDATES_IN_EDIT_MODE";
        var inputSettings = InputSystem.settings;
        bool previousPlayerUpdates = (bool)typeof(InputSettings).GetMethod("IsFeatureEnabled",
            BindingFlags.Instance | BindingFlags.NonPublic).Invoke(inputSettings, new object[] { playerUpdates });
        var currentProperty = typeof(PreviewInteraction).GetProperty("Current", BindingFlags.Static | BindingFlags.Public);
        var currentSetter = currentProperty.GetSetMethod(true);
        var previousCurrent = PreviewInteraction.Current;
        var enabledField = typeof(PreviewInteraction).GetField("inputEnabled", BindingFlags.Instance | BindingFlags.NonPublic);
        var endingField = typeof(PreviewInteraction).GetField("endAfterRelease", BindingFlags.Instance | BindingFlags.NonPublic);
        var previousKeyboard = Keyboard.current;
        int previousTableControls = UnityEngine.Object.FindObjectsByType<TableAction>(FindObjectsInactive.Include, FindObjectsSortMode.None).Length;
        var container = new GameObject("P25 synthetic keyboard isolation");
        container.SetActive(false); // No component OnEnable, networking, XR or helper start.
        var cameraObject = new GameObject("P25 isolation camera", typeof(Camera));
        cameraObject.tag = "MainCamera";
        var keyboard = InputSystem.AddDevice<Keyboard>("P25 test keyboard");
        var gamepad = InputSystem.AddDevice<Gamepad>("P25 test pan controller");
        PreviewInteraction preview = null;
        HostScene host = null;
        TablePlacement table = null;
        try
        {
            inputSettings.SetInternalFeatureFlag(playerUpdates, true);
            preview = container.AddComponent<PreviewInteraction>();
            currentSetter.Invoke(null, new object[] { preview });
            host = container.AddComponent<HostScene>();
            typeof(HostScene).GetField("objectMaterial", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(host,
                AssetDatabase.LoadAssetAtPath<Material>("Assets/SpatialModeling/Materials/HostObject.mat"));
            typeof(HostScene).GetMethod("Awake", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(host, null);
            table = container.GetComponent<TablePlacement>();
            table.SeedFromHead(new Vector3(0, 1.65f, 0), Vector3.forward);
            table.Place();
            var update = typeof(TablePlacement).GetMethod("Update", BindingFlags.Instance | BindingFlags.NonPublic);
            Action<Key> press = key =>
            {
                InputSystem.QueueStateEvent(keyboard, new KeyboardState());
                InputSystem.Update();
                InputSystem.QueueStateEvent(keyboard, new KeyboardState(key));
                InputSystem.Update();
                Check(keyboard[key].wasPressedThisFrame, "synthetic keyboard actually delivers a fresh key event: "
                    + key + " update=" + InputState.currentUpdateType + " pressed=" + keyboard[key].isPressed
                    + " updated=" + keyboard.wasUpdatedThisFrame);
                update.Invoke(table, null);
            };
            enabledField.SetValue(preview, true);
            Check(PreviewInteraction.BlocksDesktopShortcuts, "inactive test component represents admitted native input without starting its runtime");
            press(Key.M);
            Check(table.IsPlaced, "native M must not also begin moving the table");
            table.BeginMove();
            press(Key.Enter);
            Check(table.State == TablePlacement.PlacementState.Moving, "native Enter must not confirm a table move");
            press(Key.Escape);
            Check(table.State == TablePlacement.PlacementState.Moving, "native Escape must not cancel a table move");
            enabledField.SetValue(preview, false);
            press(Key.Escape);
            Check(table.IsPlaced, "unowned desktop Escape retains P2 cancel behavior");
            press(Key.M);
            Check(table.State == TablePlacement.PlacementState.Moving, "unowned desktop M retains P2 move behavior");
            press(Key.Enter);
            Check(table.IsPlaced, "unowned desktop Enter retains P2 confirm behavior");
            endingField.SetValue(preview, true);
            press(Key.M);
            Check(table.IsPlaced && PreviewInteraction.BlocksDesktopShortcuts,
                "pending synthetic-input cleanup keeps placement keyboard shortcuts blocked");
            endingField.SetValue(preview, false);

            using var pan = new InputAction("P25 actual composite pan", InputActionType.Value);
            pan.AddBinding("<Gamepad>/leftStick");
            pan.AddCompositeBinding("2DVector").With("Up", "<Keyboard>/upArrow")
                .With("Down", "<Keyboard>/downArrow").With("Left", "<Keyboard>/leftArrow").With("Right", "<Keyboard>/rightArrow");
            pan.Enable();
            InputSystem.QueueStateEvent(keyboard, new KeyboardState(Key.RightArrow));
            InputSystem.Update();
            Check(pan.activeControl?.device == keyboard && pan.ReadValue<Vector2>() == Vector2.right,
                "actual composite pan action receives the native keyboard arrow");
            enabledField.SetValue(preview, true);
            Check(BlenderScreen.ReadInspectionPan(pan) == Vector2.zero, "native keyboard arrows do not pan the captured image");
            enabledField.SetValue(preview, false);
            Check(BlenderScreen.ReadInspectionPan(pan) == Vector2.right, "unowned keyboard arrows still pan the captured image");
            InputSystem.QueueStateEvent(keyboard, new KeyboardState());
            InputSystem.QueueStateEvent(gamepad, new GamepadState { leftStick = Vector2.up });
            InputSystem.Update();
            enabledField.SetValue(preview, true);
            Check(pan.activeControl?.device == gamepad && BlenderScreen.ReadInspectionPan(pan).y > .9f,
                "native keyboard ownership preserves independent controller-axis pan input");
            Debug.Log("P25_KEYBOARD_ISOLATION_CHECK PASS actual TablePlacement.Update M/Enter/Escape admission and composite arrow/controller pan; no OS input injected");
        }
        finally
        {
            if (preview != null) enabledField.SetValue(preview, false);
            if (preview != null) endingField.SetValue(preview, false);
            currentSetter.Invoke(null, new object[] { previousCurrent });
            InputSystem.RemoveDevice(keyboard);
            InputSystem.RemoveDevice(gamepad);
            if (previousKeyboard != null && previousKeyboard.added) previousKeyboard.MakeCurrent();
            inputSettings.SetInternalFeatureFlag(playerUpdates, previousPlayerUpdates);
            // Unity does not invoke OnDestroy for a component that was never
            // active. Update created an external menu/preview; call its actual
            // cleanup explicitly so subsequent P2 gates see their own controls.
            if (table != null) typeof(TablePlacement).GetMethod("OnDestroy", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(table, null);
            if (host != null && host.Placement != null) UnityEngine.Object.DestroyImmediate(host.Placement.gameObject);
            UnityEngine.Object.DestroyImmediate(container);
            UnityEngine.Object.DestroyImmediate(cameraObject);
        }
        Check(UnityEngine.Object.FindObjectsByType<TableAction>(FindObjectsInactive.Include, FindObjectsSortMode.None).Length == previousTableControls,
            "keyboard fixture leaves no external TableAction controls for later gates");
    }

    public static void RunPreviewOcclusion()
    {
        var container = new GameObject("P25 inactive preview occlusion fixture");
        container.SetActive(false); // No OnEnable, native connection or HTTP owner.
        var imageObject = new GameObject("P25 actual RawImage hit plane", typeof(RectTransform), typeof(RawImage));
        try
        {
            var screen = container.AddComponent<BlenderScreen>();
            var preview = container.AddComponent<PreviewInteraction>();
            var image = imageObject.GetComponent<RawImage>();
            image.rectTransform.sizeDelta = new Vector2(2, 1);
            image.rectTransform.position = Vector3.forward * 2;
            image.uvRect = new Rect(0, 0, 1, 1);
            image.enabled = true;
            typeof(BlenderScreen).GetField("image", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(screen, image);
            typeof(PreviewInteraction).GetField("screen", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(preview, screen);
            var ray = new Ray(Vector3.zero, Vector3.forward);
            Check(!preview.RouteHand(UnityEngine.XR.XRNode.RightHand, ray, false, false,
                Vector2.zero, 1, out _), "closer level/control at one metre occludes the preview at two metres");
            Check(preview.RouteHand(UnityEngine.XR.XRNode.RightHand, ray, false, false,
                Vector2.zero, 3, out var distance) && Mathf.Abs(distance - 2) < .00001f,
                "visible preview consumes its hit before a farther level/control even with native input off");
            Check(!preview.RouteHand(UnityEngine.XR.XRNode.RightHand, ray, false, true,
                Vector2.zero, 3, out _), "grip remains available to P2 arrangement instead of preview input");
            Check(!preview.RouteHand(UnityEngine.XR.XRNode.LeftHand, ray, false, false,
                Vector2.zero, 3, out _), "unselected hand cannot consume the primary preview input route");
            Debug.Log("P25_PREVIEW_OCCLUSION_CHECK PASS actual RouteHand+RawImage nearest level/image/grip/hand routing; input disabled and no HTTP owner");
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(imageObject);
            UnityEngine.Object.DestroyImmediate(container);
        }
    }
}

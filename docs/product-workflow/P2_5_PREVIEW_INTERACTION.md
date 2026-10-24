# P2.5: full native Blender preview interaction and spatial drawing

This feature is developed on `codex/talia-p2-5-blender-interaction`, starting from P2 workspace arrangement `54bd597`. Its published surface/visible-level update `e880714` is forward-merged on this feature through `8937c95`; a closer movable level also bounds native preview input. P2 continues to own workspace layout, Arrange controls, room helpers, the left-hand setup menu and accepted grip/placement behavior. P2.5 consumes the actual preview image rectangle and existing stabilized ray. Main is not merged and P2's test runtime is not replaced. Review is tracked in [draft PR #140](https://github.com/waaberi/calhacks13/pull/140).

## What is implemented

With `CALHACKS_P25=1` or `--p25`, a separate control strip appears below the preview. The whole native captured image accepts controller input after **Focus Blender** obtains native editing permission and the helper confirms its exact selected window. Trigger presses/releases are native mouse down/up, so holding trigger performs a native drag. Choose left, right or middle mouse; use the stick for native scrolling while over the image. Double-click can be performed with two clicks or the virtual keyboard's explicit Double click action. Grip continues to arrange the preview rather than injecting a native edit. Tracking recovery requires releasing trigger before it can arm again.

The keyboard supports text/numbers/punctuation, Ctrl/Shift/Alt combinations, Enter/Escape/Tab/Backspace/Delete, arrows, Home/End, Page Up/Down, common numpad view keys, F3 search, Undo/Redo and Save. While native UI owns input, keyboard events do not also activate Unity's background recenter, magnification, visibility, placement or arrow-key panning shortcuts. Controller A/X and B/Y retain their P2 meanings. The keyboard is a temporary overlay; its gaps cannot click through to native buttons beneath it.

The preview provides native navigation to workspace tabs, editors, expanding panels, scrolling properties, menus/submenus, Outliner controls and viewport tools. These use Blender's real mouse/keyboard handling, with no small allowlist of custom button hotspots. It does not imply that every resulting native data type is supported in the separate Unity scene mirror.

**Draw in VR** ends the native input reservation after synthetic input release is acknowledged. Finish a native modal operation with Enter or Escape before switching. Choose an existing native sketch, or create XY/XZ/YZ through the native command path. Line uses two endpoints; Circle uses center and a radius point; Rectangle uses opposite sketch-plane corners. Orange geometry is an uncommitted local draft; cyan geometry comes from Blender's solved records. The existing native CAD Sketcher/slvs implementation owns geometry, constraints and history. Undo/Redo/Save in spatial mode use native transactions. A native toolbar choice also updates supported spatial tool intent through fresh state telemetry.

## Coverage and failures

**Model tools** opens a separate object-action overlay. It first finishes owned
preview input cleanup and waits for the native UI reservation to end. Previous
object / Next object explicitly chooses a synchronized native object; the panel
shows its name as the model target. This target is separate from spatial sketch
selection. A missing or removed target never redirects an action to another
object. Add selects its own confirmed created UUID, waiting for the exact scene
record if the receipt arrives first.

The overlay adds 18 native modeling actions:

| Buttons | Native result |
| --- | --- |
| Add cube / sphere / cylinder | Create at Blender world origin, with 20/50/100 mm bounding dimensions; cylinder diameter and depth are equal |
| Move X/Y/Z, positive and negative | Move the chosen native object by 1/10/100 mm along Blender world axes |
| Turn X/Y/Z, positive and negative | Rotate about the chosen object's origin by 15/45/90 degrees around Blender world axes |
| Scale down / up | Uniform factors 1/1.1 and 1.1, so the two operations are inverses |
| Delete target | Delete only the explicit native object; native Undo restores it |

Move step, Turn step and Primitive size cycle the displayed values. Defaults are
10 mm, 45 degrees and 50 mm. Native unit scale and viewer magnification do not
change these distances. The overlay includes native Undo, Redo, Save and Cancel
pending. Cancel can stop a pending permission request; after a command is
executing, wait for its receipt and use Undo. Saving an unsaved document reports
the native refusal rather than inventing a path.

These buttons use existing typed commands, permissions, receipts and history.
They require current editable native state in Object Mode, no running modal tool,
and completed preview-input cleanup. They work without CAD Sketcher; direct
spatial sketch drawing still requires it. If context changes while permission is
pending, the late grant is released without sending the edit. Overlay gaps absorb
input and cannot trigger Blender or spatial drawing behind the controls. The
[native command evidence](P2_5_OBJECT_ACTIONS_NATIVE.md) covers actual Blender
outcomes; headless callback checks and later physical acceptance remain separate.

A newly created sketch becomes the explicitly named spatial drawing target once Blender confirms it. The native preview can retain its previous selection; the status identifies both. Drawing waits for that new sketch's native scene record. Removing it refuses further clicks rather than redirecting them to an older sketch. Changing native sketch/tool context or leaving spatial mode clears this explicit choice.

The following are implemented routes, not a claim of completed native UI or headset acceptance. Real button coverage must be verified on the exact integrated runtime.

| Workflow group | Included operations | Current evidence |
| --- | --- | --- |
| Whole interface navigation | Workspace tabs, editor headers, panels, Properties tabs, Outliner scroll/expand/select | Generic input implementation; native UI trial pending |
| Buttons and menus | Left/right click, double click, hover, menus/submenus, checkboxes/dropdowns | Mocked native dispatch/geometry gates; native UI trial pending |
| Continuous controls | Trigger-held drags, sliders, viewport gizmos, middle mouse, vertical/horizontal scroll | Input lifecycle implementation; native UI trial pending |
| Keyboard and exact entry | Text/numeric fields, modifiers/shortcuts, navigation, F3, numpad view keys | Native event validation and client compilation; delivery trial pending |
| Native editing | Add/delete, transforms, modifier properties, visibility, rename and native tool operation | Actual background operations and synchronized outcomes passed; UI delivery remains pending |
| History and persistence | Native preview shortcuts and typed spatial Undo/Redo/Save | Actual background CAD Undo/Redo and fresh editable reopen passed |
| Direct spatial CAD | Line, rectangle, circle, native tool/active sketch synchronization | Actual native solver/persistence passed; controller gesture/headset trial pending |
| Auxiliary Blender windows | Explicit Next window among same-process GHOST Blender windows | Mocked switching/identity/closed-window recovery passed; actual pop-up trial pending |

Controls needing native modal interaction remain usable inside the preview where their normal mouse/keyboard sequence is available; arbitrary tools do not automatically gain a direct spatial gesture. Continuous Draw, Auto Constraints and Live Project Snaps are not silently reproduced by the bounded spatial adapter: its status explains that these options must be off. Non-GHOST Windows dialogs are not captured or controlled. Unsupported native entities/constraints/planes are reported and isolated from other scene objects/sketches rather than disconnecting the whole session.

When a workflow fails, classify it as image/pointer mapping, event/focus/context, modal gesture, auxiliary-window capture, native operation failure, or mirror/spatial support. Verify the actual native result; merely sending a click is not a pass. Add reproduction and exact source/build to issue #139. Fix general transport/context problems before per-tool adapters; targeted adapters must still invoke real native operations.

## Input integrity and recovery

Only an explicitly opted-in helper accepts input. It binds source pixels, selection generation, capture process instance and native geometry/DPI/process-start stamp. Unity admits input only for the displayed frame's matching identity/geometry and the same process as its current native document connection. Window resize, replacement, occlusion, lost focus, stale pixels, wrong owner or unavailable native state stops admission.

One HTTP owner serializes state reads and input events. After an uncertain delivery, it obtains the server's authoritative next sequence; it never blindly retries a model action. Release is separately idempotent cleanup. Native reservation ends only after release acknowledgement; an independent bounded cleanup component handles ordinary component disable. During application shutdown or helper loss, the helper watchdog and native connection/modal cleanup remain necessary; an unsuccessful cleanup does not prove release. A helper restart during held input requires checking native input/reconnecting rather than claiming old injected keys were released.

State fields are checked before they enter the input owner. Acknowledgement means explicit `ok:true` and the matching sequence, including during independent cleanup; HTTP 200 alone is insufficient. Failed held-input release blocks window focus. If the watchdog successfully releases an owned drag/modifier, its logical session changes so the client must start a fresh gesture. Rejected pre-dispatch events cannot manufacture key/button releases for input they never attempted. Headless HTTP and native-operation evidence is documented in the [verification results](P2_5_RESULTS.md) and [native workflow checks](P2_5_NATIVE_PREVIEW_WORKFLOWS.md); it does not prove actual menu/button delivery.

The native editing lane uses the existing exclusive lease as the host desktop actor, tracked by the requesting VR connection. It coordinates other supported edit routes and retains ownership across running native modal operations. This does not claim universal prevention of unrestricted native scripts/add-ons.

## Running later, after the P2 runtime handoff

The normal P2 launch stays unchanged. A P2.5 build requires this branch's add-on and helper. Do not point the new Player at P2's old add-on or silently reuse its old helper.

1. Prepare a new isolated Blender process/profile and a copied `.blend` document using this branch's `desktop-capture/bootstrap_p25.py`. Its exact command and private-profile setup are in the [capture helper instructions](../../desktop-capture/README.md). Use an explicitly separate native port, for example 8769. CAD Sketcher 0.32.1/slvs 3.2 is required for spatial CAD; generic preview input does not require CAD.
2. Start this branch's capture helper on a separate port, for example 8768, with `--enable-input`. Explicitly select the same Blender process/window as the native host. Neither desktop fallback nor implicit window selection is used.
3. `launch_p25.py --host-port 8769 --capture-port 8768 --diagnose` checks native document/process binding without input injection or Player launch.
4. After P2's Player has been handed off cleanly, use `launch_p25.py` with the same ports, `--player <P2.5 Windows EXE>` and a new external `--session-dir`. It refuses to launch while another SpatialModeling Player exists.
5. In VR choose Focus Blender, then use the whole image. Use the keyboard for input; finish/cancel native modal tools before Draw in VR.

Do not use the existing P2 headset session to validate this branch without coordination. Existing P2 menu acceptance is retained, not requested again. See [verification and remaining runtime gates](P2_5_RESULTS.md) and [spatial/native integration contract](P2_5_SPATIAL_BRIDGE.md).

The current Windows candidate is the complete external `artifacts/p25-preview-spatial-v9` directory, built from frozen app source `07db58c`, including P2 surfaces through `e880714`. Keep its executable, data directory and runtime dependencies together. The preceding v6/v7/v8 checkpoints remain preserved. All were built and checked without launching a Player. The headless pass verifies 9 actual Unity HTTP cases, 77 helper/control checks, 136 underlying native workflow assertions, and the cumulative Windows gates. Later P2 changes (`e1dae7e`/`aa9e864`) require selective integration after that work is ready. These software passes do not establish actual native button delivery or physical interaction acceptance.

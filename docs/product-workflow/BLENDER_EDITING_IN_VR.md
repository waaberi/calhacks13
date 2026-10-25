# Editing Blender from VR

Use Blender's existing view as the modeling menu. Choose a native tool there,
then use the controllers on the floating model to change its actual geometry.
The same controllers can still edit Blender's 2D viewport, menus and dialogs.
Both routes operate on the same document and native Undo history.

The current integration candidate is unlaunched until an explicit runtime switch.
Software verification does not establish headset, physical alignment or live
microphone/Gemini acceptance.

## Choose a tool, then edit the floating model

1. Choose **Edit model** beside the Blender view. Close its existing guide, or
   choose **Start Blender editing**. Enable **Input ON** to reach Blender's native
   toolbar and mode controls with the configured pointer hand.
2. Choose Object Mode and Move/Rotate/Scale, or select a mesh and choose Edit
   Mode with one vertex/edge/face selection mode. Use face mode for Extrude
   Region/Individual and Inset, and edge mode for Loop Cut. Finish any native
   modal operation before moving to the floating model.
3. Point at a visible floating object/component. A front-trigger tap selects or
   deselects without changing geometry. Use the existing keyboard's **SHIFT** to
   add/remove members. Drag an already selected member to edit the selection.
4. Hold the front trigger and aim. Keep holding while Input ON safely releases
   native window ownership. Once acknowledged, the held gesture changes real
   Blender geometry and updates the floating model live.
5. Release to finish one native Undo step. Escape, voice Cancel or grip cancels
   the held operation; wait for native rollback before another edit or re-grip.

After direct editing the button shows **3D edit ON · click Blender menu**. To choose
another tool, enable 2D input, or press the trigger once on the Blender image to
request it again. Wait for permission, release, then click the desired tool;
that initial press is never replayed. Manually switching Input OFF is respected
and retains Edit model and sticky spatial SHIFT. **Arrange space** ends direct
editing safely. Temporary tracking loss cancels/releases the current gesture,
while the selected Edit model mode waits for fresh tracking and released
trigger/grip before rearming. The configured pointer hand and existing grip/stick
arrangement controls are preserved.

Select Move/Rotate/Scale with Blender's toolbar icons; G/R/S instead begin native
2D modal operations. Check the floating status has changed to the chosen tool.
For Rotate, grab a red X, green Y or blue Z rotation ring with the front trigger
and sweep around the ring. Its arrowheads indicate the arc and the selected axis
highlights during the live edit. Release commits one Undo; grip/Escape cancels.

The floating axis/plane handles use the same trigger gesture. Transform
orientation, pivot, constraints, snapping and proportional properties are chosen
in Blender. Extrude Region supports native constraints, grid/surface snapping and
proportional movement of its new selection. Individual-normal extrusion refuses
combined snapped/constrained/proportional movement; use a separate Move afterward.
Inset, Bevel, Loop Cut and Knife use their supported native tool
properties; see the exact [direct tool table](DIRECT_MODEL_EDITING.md).

Knife is a held surface stroke: start on a visible face, trace at least two
distinct points, then release to complete it. Loop Cut uses one picked native
edge and its quad ring, with the configured number of cuts and controller slide.
For Merge, Dissolve and Delete, first select in 3D and wait for native selection
sync. Enable Input, choose the tool in Blender's Edit Mode toolbar and set its
native properties. Selecting the toolbar tool only arms it. Hold the trigger and
move on the floating selection to start; release gives one Undo, while Escape or
grip cancels/restores. Merge requires vertex mode and at least two vertices.
First/Last Merge uses captured native selection order, which need not preserve
controller tap order after synchronization. Native 2D viewport clicks, Mesh
menu/keyboard actions and confirmed voice recipes remain available.

## Keep editing the native 2D view

With **Input ON**, front trigger clicks/drags Blender's actual viewport, menus
and buttons. An idle ray aimed at the Blender image is routed to that image,
including when Edit model is active. A blocked or disabled image does not pass
the same trigger through to geometry behind it.

**Keyboard** supplies letters, numbers and modifiers. **Full keyboard** adds
function and numpad keys. Click the intended native editor before typing. G/R/S
start Blender's own move/rotate/scale; Tab changes mode; Enter confirms and Escape
cancels the native operation. Physical keyboard typing still follows the captured
Blender window's desktop focus. The manual real-keyboard opening and outline
have been removed; the VR keyboards and room passthrough remain available.

With **Lock screen position**, the side grip right-clicks over the native view.
Stick tilt scrolls/zooms; hold stick and tilt to pan. Outside a held direct edit,
grip retains its accepted VR display arrangement behavior. Grip does not become a
second modeling trigger.

**Draw in VR** remains the separate CAD sketch workflow: choose the native sketch
and Line, Circle or Corner Rectangle tool, then place the controller points on
that sketch plane. Existing numeric, preview, window/dialog and voice controls
remain available through their current UI.

## Native input handoff

Input ON owns the native preview writer. A direct or voice edit waits for held
synthetic keys/buttons to be released and acknowledged, the preview owner/token
to end, and fresh telemetry to confirm there is no modal or pending transition.
The next edit uses the ordinary native permission path after rechecking identity
and targets. It does not bypass the reservation or assume the computer is idle.

Finish/cancel a running native modal with Enter/Escape first. An early-released
controller gesture cannot launch later when cleanup finishes. A changed document,
target, native tool/settings or tracking context invalidates the relevant pending
intent. Commands already sent reconcile their actual receipt; an unknown result
is never automatically replayed.

## Voice and reviewed AI plans

The existing basic editing commands and command chains remain available. A chain
such as “add a cube, then move it twenty centimeters along x, then colour it blue”
is validated as a whole. “It” follows the actual resulting object. See
[VOICE_COMMAND_CHAINS.md](VOICE_COMMAND_CHAINS.md).

When the optional Gemini interpreter is configured, additional catalog tools can
be proposed as a typed plan. Review every page before the existing left-stick
confirmation. The model does not execute arbitrary Blender operators. Undo,
Redo, Cancel and Save remain separate controls. The exact recipe workflow and
catalog are in [LIVE_MODELING_AI.md](LIVE_MODELING_AI.md).

## Remaining headset checks after an authorized switch

- Choose a native tool in Blender, then see both Blender and the floating model
  change during a held direct gesture. Release, Undo, Redo, then cancel another
  held gesture and confirm restoration.
- Add/remove several objects/components with SHIFT; try native axis/plane
  constraints and the intended snapping/proportional settings.
- Confirm face Extrude/Inset, Bevel, one-edge Loop Cut/slide and a completed Knife
  surface stroke. Arm Merge/Dissolve/Delete in the Blender toolbar without an
  immediate edit, then test floating-model release/Undo and cancellation.
- Keep editing the 2D Blender viewport with the same controller controls. Confirm
  laptop-keyboard visibility and safe Input-ON handoff into a new voice edit.
- If AI is configured, review and confirm one new plan, clarify an incomplete
  request and cancel an unsent queued plan. Speech/service acceptance remains a
  separate physical check.

Retain the outstanding physical room alignment and controller visual correction
checks. These are new workflow checks, not a restart of accepted old P2 menus.

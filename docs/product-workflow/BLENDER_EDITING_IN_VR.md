# Editing Blender from VR

Choose **Edit model** beside the Blender view. This requests the existing native
Blender input session and opens a three-page guide in VR. Close the guide to reach
the captured Blender viewport and menus; choosing Edit model again reopens it.
Blender remains the modeling interface. There is no second geometry editor.

1. Enable Input and point at Blender's actual viewport. Front trigger selects;
   hold the trigger and aim to drag. Use Blender's native Object/Add menus and
   toolbar to transform or create geometry.
2. Select a mesh and choose Edit Mode in Blender's top-left mode menu. Use its
   vertex/edge/face selection controls and Mesh menu or toolbar to edit geometry.
3. **Keyboard** supplies letters/numbers and modifiers. **Full keyboard** adds
   function and numpad keys. Click the intended native editor before typing.
   Blender's G/R/S start move/rotate/scale; Tab changes mode. Enter confirms;
   Escape cancels. Keyboard input targets the selected captured Blender window.
4. **Lock screen position** enables side-grip right-click over the native view.
   Stick tilt scrolls/zooms; hold stick and tilt to pan. With the screen unlocked,
   grip retains the accepted VR screen arrangement behavior.
5. For direct sketch drawing, choose a CAD sketch and its Line, Circle or Corner
   Rectangle tool in Blender, then choose **Draw in VR**. The existing input
   release barrier ends the preview writer before two controller points create
   a typed native sketch edit on that sketch's plane.

Trigger selection of a floating 3D object supplies the voice target. Gripping that
object arranges its VR representation; it does not change native Blender geometry.
Use the native menus, direct sketch drawing, or existing voice commands for edits
that must change Blender. **Arrange space** ends native preview input safely.

## Switching from Input ON to a voice edit

Input ON reserves an ordinary exclusive native desktop lease. Sending a VR command
while retaining that writer previously conflicted with the same user's preview
reservation. The correction keeps native authority and serializes the handoff:

1. Freeze one explicit edit's arguments, session/document identity and original
   target generation. Reject concurrent handoffs and active native modals or
   pending drawing drafts/receipts.
2. Request synthetic held-input release from the capture helper. Retain the native
   reservation until the helper acknowledges cleanup.
3. End the native preview session and await fresh telemetry confirming no owner,
   token, ending state, transition or running modal.
4. Recheck identity and target generation, build with the current scene revision,
   and send once with the original request ID. A changed/deleted target, changed
   document/session, tracking loss, or eight-second timeout cancels the waiting
   intent. Never replay a rejected gesture or lost command.

Input remains OFF afterward; enable it to return to native menus. Finish or cancel
a running Blender operation with Enter/Escape before asking for another writer.
No automatic confirmation, modal cancellation, lease bypass, or file save occurs.

## Verification and remaining physical checks

`P25CommonUiChecks.RunEditingWorkflow` exercises the real guide callbacks and ray
occlusion, owner-release barrier, exactly-once callback, timeout/tracking/modal and
stale/token/ending/malformed-owner refusal. It also checks HostScene's actual
handoff context validator against changed/deleted targets and every native
identity field. `RunNativeOnly` invokes it in cumulative builds.

These checks do not inject OS input or establish headset/native GUI acceptance.
In the replacement build, confirm Edit model reaches Blender menus, a native mesh
edit visibly updates the floating 3D model, and an Input-ON voice edit safely
switches ownership and reaches a native receipt. Retain the existing physical room
alignment and controller visual confirmation gates; do not repeat accepted menu
tests or claim full phase/two-PC/production authority acceptance.

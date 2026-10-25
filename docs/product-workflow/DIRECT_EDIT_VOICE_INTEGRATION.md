# Direct model editing and voice expansion candidate

This candidate starts from combined glass v12 (`ef74f0f`) and semantically
integrates voice feature `182033e` plus a native controller editing bridge.
The original feature branches and the running v12 session are preserved. This
candidate is unlaunched until the human explicitly requests its runtime switch.

## Direct controller workflow

1. Choose the existing **Edit model** button. Use **Input ON** and the controllers
   in Blender's 2D view to select a native object and choose **Move**, **Rotate** or
   **Scale** from Blender's toolbar. Close the guide when finished reading it.
2. Aim at the floating object, hold the front trigger and aim/move to edit. On the
   first drag, keep holding while native input cleanup is acknowledged. Orange
   lines are the local draft. Release the trigger to commit one native edit.
3. For mesh edits, select the mesh in Blender, enter **Edit Mode** and choose
   exactly one vertex, edge or face selection mode. Select Move/Rotate/Scale or
   face **Extrude Region**. Aim at the corresponding visible floating component,
   then trigger-drag and release. The native mesh and synchronized model update.
4. Undo once reverses the whole successful gesture; Redo restores it. Grip or
   Escape cancels an uncommitted draft. Grip continues to arrange the VR display.
   A simple trigger click retains object selection/deselection without dragging.

Controller editing of the captured 2D Blender window remains available. Input
ON/OFF controls that native input method; it does not disable the explicitly
chosen direct-edit mode. Arrange space and headset/tracking loss end direct mode
and cancel uncommitted gestures. The existing pointer-hand choice is preserved.

The initial direct gesture supports one picked component at a time, uniform
scaling and aim-based rotation. Native tool state is authoritative. Unsupported
tools, modifiers/shape keys/shared meshes, multi-object Edit Mode, ambiguous
selection modes, snapping/proportional options and unrepresentable shear are
explicitly refused; those cases remain editable through the 2D Blender view.
See [native tool details](DIRECT_MODEL_EDITING.md) for exact limits.

## Voice commands

The complete voice expansion includes its native backend, wire contracts,
Unity receipt/selection routing, speech recognition and prompt audio. Existing
commands compose using “then”, “and then” or “and”; “it” follows the actual newly
created, duplicated or selected object. Parsing and clarification cover the
entire sequence before any prefix can execute. A sequence is atomic, with one
native Undo/Redo step and rollback on a refused step.

Try: “Add a cube, then move it twenty centimeters along x, then colour it blue,
then scale it down twenty percent.” Next: “Duplicate it ten centimeters along y,
then set its width twenty millimeters, then reset its rotation.” Signed scaling,
material restoration, dimensions and resets retain their isolated semantics.
Undo/Redo/Cancel/Save are separate utterances. Destructive sequences require
confirmation. Voice Object Mode modeling requires leaving mesh Edit Mode.

Preview input and direct gestures use the existing acknowledged release and
fresh native state barrier before another writer can edit. Actor, document,
session, generation, tool and topology protections remain in force. A timeout,
changed context or lost acknowledgement never triggers automatic replay.
See [voice integration notes](VOICE_INTEGRATION_NOTES.md).

## Preserved UI and acceptance boundaries

The larger curved handheld menu, wearer-facing held menu, Surface detection,
Blender-only opacity preference, real-keyboard passthrough window, hidden voice
transcription/popups, current room loader and accepted controller arrangement
mapping remain. Removed menu controls are not restored. Large/generated outputs
remain external. A complete matching Player/add-on/helper package is required;
the older running host cannot receive a DLL-only replacement for these changes.

Automated tests include real native object/mesh edits, prior-work-preserving
Undo/Redo, material-preserving manifold extrusion and post-live-write rollback,
voice chains/clarification/rollback/final selection, current Unity composition,
input handoff, capture and frozen XR regression gates. Exact results and skipped
hardware coverage are recorded in the delivery manifest. These are software
checks; new direct-edit/voice usability, room fit and controller appearance still
need human headset confirmation. No full phase, two-PC or #87/RC16 acceptance is
inferred. No PR, main merge, FPS work or accepted old-menu walkthrough is included.

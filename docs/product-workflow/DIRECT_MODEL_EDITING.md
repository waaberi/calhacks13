# Native Blender tools on the floating model

This integration adds a typed bridge from selected native Blender tools to
controller gestures on the floating model. Editing the Blender window with
controller mouse/keyboard input remains available. The two paths share the same
Blender document and native Undo history.

Choose the existing **Edit model** entry in VR, enable **Input ON**, then choose
the native mode and tool in Blender's 2D toolbar. Finish any native modal action.
The existing preview-input reservation must end and its acknowledged fresh state
must arrive before direct editing starts.
This is a release and reacquire of the existing authority, never a second writer.

Supported native tools are Move, Rotate and Scale in Object Mode; Move, Rotate
and Scale for mesh vertices, edges or faces in Edit Mode; and Extrude Region for
mesh faces. Choose exactly one native vertex/edge/face selection mode. In mesh
Edit Mode the floating target must be Blender's active mesh. In Object Mode the
controller can explicitly pick a different floating object while preserving the
native window's active object and selection.

Point at a floating object or the native mesh component, hold the existing
controller trigger gesture while the release acknowledgment arrives, move to
preview the edit in orange, and release to commit. The current controller route
picks one component per gesture and gesture scaling is uniform. The native typed
API also accepts bounded multiple-component selections and signed scale factors;
these extra API capabilities are not additional controller UI controls.

One completed controller gesture sends one `object.spatial_edit` command. The
host verifies actor/session/document, target generation, native tool, mode,
component mode, geometry token and the existing lease immediately before applying
it. Tool or topology changes during the gesture refuse the edit. A controller
preview does not mutate the native mesh. Undo/Redo use Blender's own history;
one successful release creates one step. Cancelled/refused gestures create none.

Move and face extrusion follow a world-space controller offset in meters.
Rotation uses a world-space quaternion around the object's origin or the picked
components' median. Scale follows native object axes around the same pivot;
signed factors allow mirroring and zero is refused. Parent transforms and scene
millimeter units are converted once. Mesh changes stage on a detached BMesh,
retain native custom data, commit to the existing Edit Mode mesh, and read back
before publication. A staging or readback failure restores the original mesh.

Mesh component picking uses exact base-mesh indices and Blender's own triangle
tessellation, including concave polygons. Evaluated display vertices are never
guessed to be editable base vertices. Visible modifiers, shape keys, shared/linked
mesh data, multiple simultaneous Edit Mode meshes, hidden picked components and
world shear are refused with an explanation. Existing 2D Blender interaction is
the route for these cases and for tools beyond the explicit list above.

Snapping, proportional editing, alternative transform pivots, origin/parent-only
transform options, locked object channels, Auto Merge and mesh mirror editing
are not silently approximated: disable the relevant option or use the Blender
panel. Native mesh caps are 8192 vertices, 16384 edges and 8192 faces, with up to
256 picked components in one command. Large or unsupported meshes remain usable
through the Blender window. This bridge does not reproduce every Blender tool,
Sculpt Mode, UV tools or arbitrary operators.

`tests/p25/native_direct_model_gate.py` runs only in a new factory Blender
process. It checks native authority handoff, live Edit Mode sync, transformed
parents/units, component edits, refusal/rollback and Undo/Redo preserving prior
native edits. Its results are software evidence. Headset controller usability
and the room/controller appearance still require the wearer's confirmation.

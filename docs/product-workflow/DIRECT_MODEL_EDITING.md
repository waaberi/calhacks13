# Live Blender tools on the floating model

Choose the tool in the existing Blender view, then edit the floating model with
the controllers. The Blender view remains the modeling menu. Controller editing
of that 2D view, its buttons, the existing keyboards and workspace arrangement
remain available.

This describes the current integration candidate. The candidate remains
unlaunched until an explicit runtime switch. Headset usability, physical room fit,
controller appearance and live microphone/Gemini acceptance remain pending.

## Start a direct edit

1. Choose **Edit model**. Its existing three-page guide opens; close it to reach
   Blender. Enable **Input ON** to select the native mode, tool and properties.
   Finish or cancel any running native modal with Enter/Escape.
2. In Object Mode, choose Move, Rotate or Scale. For mesh editing, choose Edit
   Mode and exactly one vertex, edge or face selection mode. Mesh gestures target
   Blender's active mesh. Choose face mode for Extrude Region, Extrude Individual
   or Inset; choose edge mode and one seed edge for Loop Cut.
3. Aim with the configured pointer hand. A front-trigger tap selects/deselects
   without dragging geometry. The existing keyboard's sticky **SHIFT** adds or
   removes objects/components. A drag beginning on an already selected member
   preserves the group. Wait for native selection acknowledgement before using
   that selection in Blender's menus or a voice request.
4. Hold the front trigger and aim to change the tool's amount. If Input is ON,
   keep holding while its acknowledged release completes. The actual Blender
   geometry and floating mesh update during the held gesture. These are native
   changes that remain cancellable, rather than an orange-only local draft.
5. Release after an acknowledged live update to commit one native Undo step.
   Blender Undo/Redo and the existing voice Undo/Redo use that same history.

After the automatic handoff, the input button shows **3D edit ON · click Blender menu**:
the native window writer is released, while the selected Edit model mode stays
on. To choose another Blender tool, enable 2D input, or press the trigger once
on the Blender image to request it again. Wait for permission, release, then
click the desired tool; the first press is never replayed as a delayed click.
Manually turning Input OFF is respected and still preserves explicit Edit model
mode and sticky spatial SHIFT. Arrange space ends this mode. Tracking loss or
headset suspension cancels the current gesture and releases ownership; the
selected mode can rearm only after fresh tracking and trigger/grip release.

Choose Move, Rotate or Scale using Blender's toolbar icons. The floating-model
status must show the corresponding native tool before beginning a gesture.
G/R/S start Blender's native 2D modal operation; they do not select the toolbar
tool for a floating-model gesture. Finish/cancel that modal before direct editing.

With Rotate selected, red X, green Y and blue Z rings with arrowheads surround
the selection. Aim at a coloured ring, hold the front trigger and sweep around
it to rotate about that native axis. The chosen ring highlights and stays fixed
at the starting pivot during the held edit. Release gives one native Undo step;
grip or Escape cancels and restores the start. Rotation rings follow Blender's
selected transform orientation and the same frozen native/display mapping.

## Direct gesture support

| Native tool | Native mode/selection | Controller action and captured properties |
| --- | --- | --- |
| Selection tools | Object Mode, or one mesh component mode | Trigger taps select/toggle. SHIFT adds/removes. Native box/lasso selection still works in the 2D view; there is no separate spatial box/lasso gesture. |
| Move | Objects; mesh vertices, edges or faces | Hold and aim for a displacement. Existing held-stick depth adjustment remains available. |
| Rotate | Objects; mesh vertices, edges or faces | Hold and change aim; an axis handle/native axis constraint produces rotation about that frozen native axis. |
| Scale | Objects; mesh vertices, edges or faces | Hold and aim for a positive scale factor. Axis/plane handles and native constraints restrict the affected axes. Signed mirroring is available through explicit voice/recipe factors, not a separate controller gesture. |
| Extrude Region | Mesh faces | Hold and aim for the extrusion displacement. Native constraints, grid/surface snapping and proportional movement apply to the newly extruded selection. |
| Extrude Individual | Mesh faces | Hold and aim for a signed distance along each face's native normal. A combined snapped/constrained/proportional transform is refused; use a separate Move afterward. |
| Inset | Mesh faces | Hold and aim for thickness. Captures native individual/boundary/even-offset/relative-offset/outset choices. Direct inset depth is zero; a typed recipe can specify a separate depth. |
| Bevel | Mesh vertices, edges or faces | Hold and aim for amount; preserves native Affect, segments, profile, overlap clamping and offset type. |
| Loop Cut | One native mesh edge beside visible quads | Hold and aim along the picked edge to slide the cut. Uses Blender's configured cut count and the actual opposite-edge quad ring. |
| Knife | Mesh surface; native vertex, edge or face mode | Start on a visible surface, hold and trace a surface path, then release to complete the stroke. At least two distinct samples are required. Captures the controller projection and native cut-through/selected-only choices. Selected-only Knife requires face selection. |
| Merge | At least two mesh vertices | Choose Merge in Blender's Edit Mode toolbar and set Center/First/Last/Cursor/By Distance plus distance where applicable. Hold the floating-model trigger and move to start the operation; release commits one Undo. |
| Dissolve | Mesh vertices, edges or faces | Choose Dissolve in Blender's Edit Mode toolbar. Captures selected-components or limited-by-angle mode and its angle. Hold trigger and move on the floating selection; release commits one Undo. |
| Delete | Mesh vertices, edges or faces | Choose Delete in Blender's Edit Mode toolbar and its component/domain property. Hold trigger and move on the floating selection; release commits one Undo. |

Selecting **Merge, Dissolve or Delete** in Blender's toolbar only arms that tool;
it makes no geometry change by itself. On the floating model, a tap still selects
without editing. Holding the trigger and moving starts its live operation; Escape
or grip cancels/restores, and release commits one Undo. The toolbar properties
remain in Blender, with no additional VR modeling menu. Native viewport clicks,
Mesh menu/keyboard actions and confirmed typed recipes remain available too.

Merge **At First/At Last** uses the captured ordered native selection. After native
selection synchronization, this is the order reported by Blender; controller tap
timing alone does not guarantee the endpoint. Verify the intended endpoint in
Blender, or use Center/By Distance when endpoint order is not established. A
previously executed native menu operator is never replayed as another edit.

## Selection and native settings

Multiple objects can be selected in Object Mode. Multiple vertices, edges or
faces can be selected on the one active Edit Mode mesh. Mixed component modes and
simultaneous editing of several meshes are outside this direct route. The native
selection is synchronized separately without a geometry Undo step.

The floating model shows the selected elements and native axis/plane handles.
Large selections keep their complete native index set and full selected count;
outline drawing uses a bounded pool of at most 512 segments. Sampling the visual
outline does not reduce the selection sent to Blender.

Move/Rotate/Scale capture Blender's orientation, pivot, axis constraints and
proportional settings. Extrude Region applies its native movement constraints,
grid/surface snap target and proportional movement to the new component selection.
The axes use the captured native basis, including a custom orientation. Move
supports native grid increments and eligible vertex, edge,
midpoint, perpendicular and face targets with the captured snapping filters;
face alignment uses the native target normal. Proportional transforms use the
native radius, falloff, connected and projected options. These are native
transform behaviors; this does not promise that every Blender option applies to
every topology tool. Individual-normal extrusion refuses a combined snapped,
constrained or proportional transform; perform the normal extrusion and a separate
Move instead. Inset, Bevel, Loop Cut, Knife and the three selectable mesh actions
use the properties listed above.

Native component picking uses Blender's base vertices, edges and tessellated face
IDs, with visibility checks. Display triangles split for rendering are not
mistaken for editable native indices. The gesture freezes each object's
native-to-display mapping so arranged, rotated, mirrored or nonuniformly scaled
views do not apply a second conversion. Native wire lengths are already meters,
including documents configured in millimeters.

## Live updates, history and cancellation

The live lifecycle is begin → acknowledged cumulative updates → commit/cancel.
One ordinary exclusive native lease owns the gesture. Each update is recomputed
from its immutable starting state, so topology is not repeatedly extruded or
bevelled on top of the previous preview. Only scene echoes tagged with that
session and actor are accepted as its own updates.

Preview updates do not create history entries. A successful release creates one
native Undo step for the final gesture. Redo restores that completed edit.
Selection-only synchronization creates no geometry history entry.

Escape, voice Cancel or grip requests cancellation and restoration of the
starting native state. Input remains reserved until the actual cleanup receipt.
Release and re-grip after rollback to arrange the VR display. Releasing while
input release or the first native update is still unacknowledged cancels the
gesture; it never becomes a delayed edit after the ACK. If an update may already
have reached Blender, wait for restoration rather than assuming it never ran.

A commit already sent to Blender must finish with its actual receipt. A timeout
or disconnect may report an unknown result; inspect the fresh model before
another edit. The client never automatically replays such a transaction.
Native tool/settings, identity, generation, unrelated geometry or placement
changes stop direct input and trigger the appropriate cancellation/conflict path.

## Bounds and other Blender workflows

The direct base mesh is bounded to 8,192 vertices, 16,384 edges and 8,192 faces;
live selections can contain up to 16,384 native component indices. Object live
operations admit at most 256 targets. Knife paths are bounded to 128 samples.
Loop Cut requires a compatible visible quad ring.

Visible modifiers, shape keys, shared/linked data, unsupported world shear,
hidden components, ambiguous native windows, locked transform channels,
origin/parent-only transforms, Auto Merge and native mesh mirror editing can
require the Blender panel instead. The availability message identifies a refusal;
it does not silently reinterpret the user's tool choices. Catalog recipes have
their own per-operation mode, data and size requirements.

For the wider typed catalog and reviewed AI workflow, see
[LIVE_MODELING_AI.md](LIVE_MODELING_AI.md). For native 2D controls and the complete
entry sequence, see [BLENDER_EDITING_IN_VR.md](BLENDER_EDITING_IN_VR.md).

## Verification

`LiveModelEditSessionChecks`, `LiveControllerChecks` and `DirectModelEditingChecks`
exercise actual client routes, acknowledgements, selection, cancellation and
display mapping. `tests/p25/native_live_modeling_gate.py`,
`native_modeling_tools_gate.py` and `native_knife_tools_gate.py` exercise native
behavior in isolated test sessions. Build manifests/logs establish the result of
each run; this document is not a headset or live-service acceptance record.

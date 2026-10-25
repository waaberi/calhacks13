# Live controller modeling and reviewed AI recipes

Blender's existing view remains the modeling menu. Pick its native mode, tool and
properties there, then edit the floating model directly with the configured
controller. The existing 2D controller mouse/keyboard workflow remains available.
See [BLENDER_EDITING_IN_VR.md](BLENDER_EDITING_IN_VR.md) for the entry sequence and
[DIRECT_MODEL_EDITING.md](DIRECT_MODEL_EDITING.md) for exact gesture support.

The current candidate is unlaunched until an explicit runtime switch. Native and
Unity software results belong in their run manifests; they do not establish
headset usability, real microphone recognition or a working Gemini API key/model.
Physical room alignment and controller visual confirmation remain pending.

Gemini service compatibility was verified separately with disposable factory
Blender scenes. The service rejects the catalog's large branching response
schema, so requests use JSON mode with the full catalog and an exact response
contract. The client validates the complete response against that same typed
schema locally before native preparation. Native validation, review, rollback,
expiry and one Undo/Redo remain mandatory. Invalid responses never execute a
valid prefix. HTTP errors are surfaced without an automatic model/thinking retry.

For local testing, the app can read a private key from
`%LOCALAPPDATA%/CalhacksVR/secrets/gemini.key`, outside the project/package.
`GEMINI_API_KEY_FILE` explicitly selects a private file and fails closed if it
cannot be read; otherwise `GEMINI_API_KEY` takes precedence over the default
private path. Never include keys in assets, packages, logs or version control.
The interpreter reads configuration at initialization, so saving a key alone
does not configure an already-running Player. Gemini receives the transcript,
native context and tool catalog; use disposable nonconfidential scenes on the
Free tier. Basic deterministic commands keep their existing local route.

## Two ways to request an edit

| Route | What chooses the operation | What executes it |
| --- | --- | --- |
| Live direct gesture | Blender's native toolbar/properties, then a trigger gesture on floating geometry | The host applies cumulative updates to actual Blender geometry while held. Release creates one native Undo step; Cancel restores the start. |
| Reviewed recipe | A complete spoken/typed request interpreted against the connected host's typed catalog | The native host validates the whole plan, asks for missing details or provides a review. The existing deliberate confirmation runs one stored plan with rollback and one Undo/Redo boundary. |
| Native 2D editing | Blender's own menus, keyboard, dialogs and viewport | Existing controller input acts on the captured native editor and its ordinary history. |

Direct gestures currently cover selection, Object/mesh Move/Rotate/Scale,
face Extrude Region/Individual, face Inset, Bevel, one-edge quad Loop Cut/slide,
surface-path Knife and the selectable Merge/Dissolve/Delete tools in Blender's
Edit Mode toolbar. For those three actions, choose native properties, then hold
the floating-model trigger and move to start; release gives one Undo, and Cancel
restores the start. Selecting the toolbar tool alone makes no geometry change.
Merge needs at least two vertices in vertex mode. First/Last Merge uses captured
native selection order, not a guarantee about controller tap order after native
sync. The native 2D viewport, Mesh menu/keyboard actions and confirmed typed
recipes remain available; no previously executed operator is replayed.

Multiobject selection works in Object Mode. Mesh component selection is on one
active native mesh, with one vertex/edge/face mode. Sticky SHIFT adds/removes;
dragging a selected member preserves the selection. Native transform axes/planes,
orientation, pivot, snapping and proportional properties remain in Blender.
Extrude Region applies native constraints, grid/surface targets and proportional
movement to its new selection. Individual-normal extrusion refuses a combined
snapped/constrained/proportional transform; follow it with a separate Move.
Other topology tools use their documented per-tool properties. Recipe coverage is wider
than the direct controller gesture set; an advertised typed operation does not
create a new controller gesture or modeling palette.

## Request, review, confirm

1. Finish/cancel any native modal or live controller gesture. Select the intended
   objects/components and wait for native selection acknowledgement. Choose the
   required mode in Blender before asking for a recipe; a plan does not silently
   switch modes to make its steps legal.
2. Use the existing push-to-talk control or typed voice-command field. State the
   entire edit, exact target, selection and required amounts. The interpreter
   receives the current host catalog and captured native context. A configured
   AI route handles new modeling requests and mesh-edit requests; familiar basic
   Object Mode commands retain the existing core/host route where applicable.
3. A missing target, amount, axis, component set or precise geometry path produces
   clarification. An unsupported clause refuses the whole plan. A valid prefix
   must not execute while the rest is unresolved. Clarification retains the
   original complete request and expires; repeat the complete edit after expiry.
4. Read the existing review panel. It lists ordered tools, actual targets,
   component counts and typed parameters, displaying metric values in millimeters.
   Say **next page** / **previous page** to review all pages. Every page must be
   visited before confirmation. A reviewed recipe expires after 120 seconds.
5. The existing **left stick click** confirms, provided the left grip is not held.
   Voice **Cancel** or Escape discards an unsubmitted plan. The confirmation uses
   the stored native plan, not a second model interpretation.
6. Wait for the actual native result. A successful whole recipe has one Undo
   step; Redo restores the whole sequence. Later steps can refer to actual earlier
   object/component outputs. Final selection follows the actual result.

Examples to review, rather than speech-acceptance claims:

- With native edge selection: “Bevel the selected edges two millimeters with
  three segments.”
- With native face selection: “Inset the selected faces two millimeters, then
  extrude the inner faces five millimeters along z.”
- With native vertex selection: “Merge the selected vertices by distance at
  one tenth of a millimeter.”
- In Object Mode: “Duplicate the selected object ten centimeters along y, then
  rename the copy Bracket copy.”

For Knife, prefer the controller surface stroke when the intended path is
spatial. The typed Knife operation requires an exact polyline and projection;
the interpreter must ask for missing geometry rather than inventing endpoints.
The same rule applies to exact rails, planes, bone names and external targets.

## Catalog coverage

The current source exposes 106 typed operations through `tool_catalog.catalog()`.
The catalog negotiated from the connected host is authoritative. Each descriptor
defines allowed native modes, component domains, required parameters, numeric
bounds, output handles and whether an operation is destructive. The table below
lists those IDs; it is not a claim that every possible Blender operation or every
scene configuration is supported.

| Family | Typed catalog IDs |
| --- | --- |
| Object transforms and selection | `object.translate`, `object.rotate`, `object.scale`, `object.selection` |
| Mesh transforms and selection | `mesh.translate`, `mesh.rotate`, `mesh.scale`, `mesh.selection` |
| Main mesh tools | `mesh.extrude`, `mesh.inset`, `mesh.bevel`, `mesh.loop_cut`, `mesh.knife`, `mesh.merge`, `mesh.dissolve`, `mesh.delete` |
| Mesh topology | `mesh.subdivide`, `mesh.fill`, `mesh.bridge`, `mesh.triangulate`, `mesh.split_edges`, `mesh.bisect`, `mesh.spin`, `mesh.poke`, `mesh.tris_to_quads`, `mesh.unsubdivide`, `mesh.solidify`, `mesh.symmetrize` |
| Mesh selection and movement | `mesh.select_region`, `mesh.slide_vertices`, `mesh.project_surface`, `mesh.smooth_vertices`, `mesh.flatten` |
| Mesh attributes | `mesh.recalculate_normals`, `mesh.flip_normals`, `mesh.face_material`, `mesh.face_smooth`, `mesh.edge_seam`, `mesh.edge_properties`, `mesh.sculpt_mask`, `mesh.face_set` |
| Object creation/data | `object.add`, `object.rename`, `object.duplicate`, `object.shade`, `object.parent`, `object.unparent`, `object.visibility`, `object.apply_transform`, `object.origin`, `object.delete` |
| Collections | `collection.create`, `collection.rename`, `collection.visibility`, `object.collection_link`, `object.collection_unlink` |
| Modifiers | `modifier.add`, `modifier.remove`, `modifier.apply`, `modifier.add_deform`, `modifier.configure`, `modifier.boolean` |
| Materials | `material.assign`, `material.principled`, `material.slot_remove` |
| UV layers | `uv.layer_add`, `uv.layer_remove`, `uv.layer_activate`, `uv.layer_copy` |
| UV edits | `uv.unwrap`, `uv.smart_project`, `uv.transform`, `uv.pin`, `uv.pack`, `uv.select_island`, `uv.weld`, `uv.average_islands_scale` |
| Vertex groups | `vertex_group.create`, `vertex_group.rename`, `vertex_group.remove`, `vertex_group.lock` |
| Weights | `weights.assign`, `weights.remove`, `weights.normalize`, `weights.smooth` |
| Curves | `curve.spline_add`, `curve.point_set`, `curve.spline_remove`, `curve.settings` |
| Pose/rig data | `rig.pose_transform`, `rig.pose_reset`, `rig.ik_add`, `rig.ik_update`, `rig.ik_remove`, `rig.bind_armature`, `rig.unbind_armature` |
| Animation | `animation.keyframe`, `animation.keyframe_delete`, `animation.frame`, `animation.pose_keyframe`, `animation.pose_keyframe_delete`, `animation.interpolation`, `animation.frame_range` |
| Scene object properties | `camera.settings`, `light.settings`, `text.settings` |

Mesh operations generally require native Edit Mode with the matching component
domain: Inset needs faces, Loop Cut one quad-ring edge, Merge vertices, and UV
edits faces with an appropriate UV layer. Region selection supports connected,
face-boundary and compatible edge-loop selection. Vertex slide requires exact
native rails. Transform recipes accept signed scale factors for mirroring and
reject zero scale.

Object/data, modifier, material, collection, curve and scene-property operations
generally require Object Mode. Pose transforms/reset and pose keyframes require
Pose Mode and an exact visible bone name. IK operations accept their descriptor's
Object/Pose modes. Weights use exact vertex handles and the allowed Object/Edit
Mode context. A sculpt mask/face-set data edit is not a direct freehand sculpt
brush, and typed pose editing is not a controller bone-grab UI.

The catalog is bounded. Recipes contain at most 24 ordered steps; captured
component sets are bounded to 16,384 indices. Individual tools additionally check
native data type, local/single-user ownership, geometry size, visible selection,
compatible modifier/constraint structure and required dependent objects. A tool
descriptor does not waive those native checks. Unsupported workflows remain
available in Blender's native 2D view.

## Authority, stale context and Cancel

AI output is data: allowlisted tool IDs and typed parameters. It cannot supply
Python, arbitrary RNA/operator paths, shell commands or a file-save action. The
host checks the whole plan against the advertised catalog and stages applicable
geometry before review. Execution rechecks session/document identity, revisions,
target generations, native selection, mode/tool/options and the captured native
context fingerprint. A selection or gesture that changes and returns to the same
visible state still invalidates a delayed AI reply through the client epoch.

Input ON uses the same acknowledged release barrier as direct editing. A queued
AI confirmation owns its exact unsent request token. Cancel, stale context or a
changed selection removes that token, and the late cleanup callback cannot send
the plan afterward. This does not cancel an unrelated deterministic voice/menu
command. The context is checked again at the final send boundary, even if native
cleanup finishes before the client's next update.

Once a transaction has been sent, Cancel cannot claim an unsent edit or an
invented rollback. The client waits for its actual applied/rejected/unknown
receipt. Native execution uses the existing exclusive authority, validates the
complete sequence and rolls back a failed sequence. Unknown outcomes are never
automatically replayed. Undo, Redo, Cancel and Save remain separate commands;
existing core phrases such as **undo that** and **redo that** stay outside Gemini.

## Local configuration and verification

With AI enabled and a current catalog, new modeling requests and complete
command chains go through Gemini, including ordinary object moves on X, Y or Z.
The full transcript is retained; vocabulary overlap with the basic grammar no
longer decides whether a request bypasses interpretation. Undo, Redo, Cancel,
Save, simple selection and an existing deterministic clarification stay local.
Without AI availability the deterministic path remains available.
Only an answer matching the active local question retains that route; a new
complete command, including polite or unfamiliar phrasing, starts a fresh
Gemini review rather than executing through an older pending command.

An active missing-axis question accepts spoken letter variants such as `why`
for Y and `zee` for Z, including explicit corrections such as `Z, I mean Y`.
These aliases apply only to that live question, retaining its amount and target;
an ambiguous answer or an additional command is never reduced to one axis.
Gemini receives the existing move/scale limits and explicit basic Add defaults
(a 5 cm primitive at the native origin for an unqualified Add). Typed move/scale
output is checked against those limits before the complete plan reaches review.
Rotation limits use explicit angular amounts from the retained user request
and clarification answers. Each turn must be nonzero and at most 360 degrees
in magnitude; signed full turns remain valid. A quaternion alone cannot reveal
the original turn count. A rotation without a recoverable explicit amount and
unit asks for clarification instead of guessing from its quaternion.
Unsupported trailing requests refuse the whole plan. Native validation, context
checks and the existing review/confirmation requirement still apply.

The client reads `GEMINI_API_KEY`, or the existing local `gemini_key.txt` lookup
beside the Player, in its persistent-data directory or working directory. The
source default model string is `gemini-3.5-flash-lite`; `GEMINI_MODEL` takes
precedence over the serialized model override. These are configuration values,
not evidence of live service availability. Do not include a key in the repository,
package or test evidence. Without an available configured interpreter/catalog,
the existing deterministic voice and native 2D workflows remain available.

Relevant checks include `AICancellationChecks`,
`tests/p25/AiControlManagedChecks.cs`,
`tests/p25/native_modeling_recipe_gate.py` and the catalog/recipe protocol tests.
Native tool, Knife, selection, live lease/history and existing combined-build
regressions are separate gates. The final manifest must identify exact source,
matching Player/add-on/package and observed results. No live API-key, spoken
headset or physical acceptance is inferred from compilation or fixture results.

After an authorized switch, check one live controller gesture and its
Undo/Redo/Cancel, a synchronized multiselection, a reviewed multi-step recipe,
clarification of a missing amount and cancellation while input release is pending.
Keep the running build and personal Blender sessions intact until that switch is
explicitly requested.

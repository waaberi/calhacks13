# Exact numeric transforms and common native modeling evidence

`tests/p25/native_modeling_workflows.py` distinguishes two verification methods:
real typed Commands/Leases/Editor transactions with native receipts, and real
`bpy` operators in an explicitly selected private VIEW_3D/WINDOW context. Its
result JSON labels every assertion with its method. Neither method proves shortcut
delivery, mouse/hover behavior, capture, Windows focus or headset interaction.

## Toolbar/sidebar follow-up: headless native route passes

The later user-requested panel investigation resolves the two synchronous
background failures recorded below. No P2.5 button mapping or native product
operation needed changing. A private controlled probe,
`evidence/p25-panel-motion-probe`, reproduced the immediate-read failure with
default animation and successful hide/show with Blender's Reduce Motion enabled.
The installed version is 5.2.2 LTS, build `d13f752e3b9c`. Its matching versioned
[RNA region update](https://github.com/blender/blender/blob/v5.2.2/source/blender/makesrna/intern/rna_space.cc#L828)
uses synchronous region updates when Reduce Motion is enabled. Otherwise the
overlapping-panel hide animation finishes through the displayed UI timer, which
the background test does not drive. The installed `wm.py` context toggle returns
CANCELLED for this non-Undo Screen property even after a successful native change.

The corrected fixture enables that preference only in the disposable background
process, invokes the same `wm.context_toggle` routes bound to T/N, and restores
original panel visibility and the preference in nested `finally` blocks. It does
not save preferences or change any product, helper or personal Blender setting.
Each panel starts both hidden and shown, toggles away and back, and checks that
the other panel stays unchanged. Exact native state, correct editor space,
eight completed transitions and all cleanup checks are mandatory assertions,
not optional observations.

Final evidence `evidence/p25-native-preview-panels-verified/` contains **60 required
assertions passed**: the original 26 installed-keymap/viewport checks and 34 panel
and fixture checks. All 31 shortcut bindings match, all eight panel transitions
reach their expected state, pending/optional failures are empty, and both native
process and runner exit zero. Private resource/TEMP paths and unchanged source
and bytecode fingerprints are verified. No key events were injected; actual
preview key delivery, visible animation/capture and VR remain separate gates.

Preserved attempts:

- `p25-native-preview-panels-synchronous`: native 60/60, runner exit 1 because
  concurrent pytest wrote a cache file in the monitored test directory. This
  establishes no overall isolation pass.
- `p25-native-preview-panels-final`: sequential 60/60 and isolation pass.
- `p25-native-preview-panels-verified`: final reporting/source version, 60/60 and
  isolation pass. The runner now distinguishes native success from overall
  failure: process/source/bytecode failure forces `outcome=failed, passed=false`.
  Nine pure outcome tests (within 32 P2.5 tests) and repository Ruff pass. The
  initial Ruff import-order failure and corrected log remain preserved.

The original animation-assumption failures and earlier reporting history below
remain unchanged. They are superseded for native headless panel semantics, not
converted into actual GUI/key/headset acceptance. Unity/app/backend sources are
unchanged, preserving the v11 candidate and its prior control/HTTP/build evidence.

## Exact modeling and common native operations

Final source-consistent background results on October 24, 2026:

| Scene units | Create | Fresh-process reopen | Actual typed receipts | External evidence directory |
| --- | --- | --- | --- | --- |
| 1 metre per unit | 90 passed | 7 passed | 33 + 2 | `p25-native-modeling-unit1-context` |
| .001 metre per unit | 90 passed | 7 passed | 33 + 2 | `p25-native-modeling-unit001-context` |

All four successful processes exited zero: **194 assertions and 70 typed command
receipts**. CAD Sketcher was disabled. Sources and source bytecode remained
unchanged; private resource/temporary paths were verified in both processes of
each run. Each directory contains its manifest, native logs, assertion/receipt
JSON, private profiles, saved `.blend` and independent persistence metadata.

The typed command cases cover cube, sphere and cylinder with custom signed
locations and independent dimensions; fractional signed absolute/relative moves;
absolute native Euler XYZ rotation; relative world-Y rotation of a nontrivially
rotated object; absolute nonuniform scale and independent-axis scale factors;
and another absolute rotation preserving that scale and the world position.

The numeric oracle uses analytic axis matrices and quaternion multiplication,
independent of Blender's Euler helper: for X=23°, Y=-37°, Z=61°, the native
rotation is `Rz * Ry * Rx`, with quaternion `qz * qy * qx`. Native world basis
columns are compared against the expected rotation times each scale component.
The second absolute rotation uses -11°, 28°, -53°. Both unit scales are checked
against requested meters, including negative and fractional positions.

Numeric/permission checks refuse malformed or out-of-range arguments, zero or
negative scale, nonfinite JSON, a zero quaternion, missing and stale native
targets, native Edit Mode, and a competing target lease without geometry changes.
An exact numeric request replay returns its original receipt and does not apply
again. Fresh reopening verifies complete mesh/transform/UUID persistence, another
exact numeric move, and typed Save with no remaining edit lease.

The separately labeled native operator workflows cover:

- Object Select All, Invert and Deselect; Duplicate/Delete with distinct UUIDs;
  Hide/Unhide reaching synchronized visibility.
- Apply Rotation/Scale preserving independently measured world-space native
  vertices; Shade Smooth changing the synchronized normal representation.
- Edit Mode selection, Extrude, Inset, Bevel and Subdivide creating actual native
  topology. Completed operations are also checked against synchronized geometry
  while Blender remains in Edit Mode, using independently counted BMesh faces and
  triangles.
- Merge and mesh-vertex Delete, followed by actual native Undo/Redo restoring the
  original UUID and complete pre-operation solid. The final saved model preserves
  the modeled solid, and the fresh process confirms it remains editable.

These operator tests provide explicit selections and parameters and execute in
Blender's native editor context. They do not prove the interactive modal shortcut
equivalents or loop-cut pointer workflow. Native Undo checkpoints are explicitly
pushed after background operations; automatic UI event-loop history boundaries
remain a separate runtime gate.

The first attempt, `p25-native-modeling-unit1-attempt1`, passed 66 assertions then
failed `object.hide_view_set.poll()` because a background script had no active
editor area. Its failure/log are preserved. The corrected fixture explicitly
overrides the existing factory scene's VIEW_3D/WINDOW context and records that
choice. No add-on or contract change was required, and the failure is not a
demonstrated native command or headset regression.

`tests/p25/run_native_modeling_workflows.py` reuses the established private
environment/output guards, clears inherited user-resource overrides, supplies
private Blender resources and TEMP/TMP/TMPDIR before startup, disables source
bytecode writes, runs BelowNormal with two Blender threads, and verifies source
fingerprints after both create/reopen phases. No GUI, OS input, sockets, Player,
headset, P2 resources, default ports, main changes or FPS work were involved.

## Installed shortcut bindings and background viewport navigation

`tests/p25/native_preview_navigation.py` reads all 31 shortcut keys and modifier
chords from the actual `PreviewShortcutCatalog.cs`, activates the installed
Blender 5.2.2 LTS default keymap using Blender's own preset loader, and matches
the resulting native keyconfig items against independently specified operator,
properties and editor/mode context. All **31 of 31 chords match**. Selection and
G/R/S bindings are also checked separately in Object Mode and Mesh contexts.
ESC/Enter match CANCEL/CONFIRM in the Transform Modal Map; this is a contextual
modal-map result, not a claim that every Blender modal tool handles these keys
identically. Customized user keymaps remain outside this evidence.

The same private background process runs actual viewport operators with an
explicit VIEW_3D/WINDOW override and smooth-view transitions disabled. The
independent state assertions passed for:

- Front/back/right/left/top/bottom: view quaternion rotates the view's back axis
  to each expected world cardinal axis, independently of operator return codes.
- Perspective/ortho: the native perspective mode changes in both directions.
- Frame All: two known cubes bound X from -3 to 5; the resulting view center is
  exactly the independent bounds midpoint (1, 0, 0).
- Frame Selected: selecting only the second cube centers the view at (4, 0, 0).
- Local View: the selected cube is included, the other cube is excluded, and
  leaving Local View restores the complete scene.

All 25 navigation assertions passed, alongside the combined 31-chord keymap
assertion. These methods establish native bindings and scripted native viewport
state changes. They do not establish injected-key delivery, mouse targeting,
hover, Windows focus, visible capture updates or headset behavior. Camera view
and the shading menu were checked for their default bindings only.

At that initial checkpoint, toolbar/sidebar results were **pending interactive
verification**; the later headless fixture correction above resolves their
native operation semantics. Their actual
native `wm.context_toggle` routes were invoked in the private editor, with
property checks after each toggle. Blender's installed `bl_operators/wm.py`
intentionally returns CANCELLED after modifying non-Undo Screen properties;
the test records that expected return separately from the observed property.
Two of eight panel assertions failed: the toolbar hide did not immediately
change `show_region_toolbar`, and the sidebar restore left `show_region_ui`
shown. The background process does not run a normal displayed region event
loop. The evidence establishes these synchronous background failures; it does
not establish a shortcut/helper/add-on defect or successful panel round trips.
No GUI or additional process was launched to resolve this limitation.

Evidence is preserved under the external
`C:/Users/talia/Documents/Codex/calhacks13-p0/evidence/` directory:

| Run | Actual result | Interpretation |
| --- | --- | --- |
| `p25-native-preview-navigation` | First probe: 29 matched, ESC/Enter inspection failed | Test predicate incorrectly treated native ANY-modifier `oskey=-1` as a required OS modifier; installed source bound both keys correctly. |
| `p25-native-preview-navigation-context` | 31 matched; 32 of 34 total assertions passed; gate remains failed | Six axis views, projection, framing and local view passed; two panel assertions remain pending as described above. |

The second run records the actual modal RNA entries: RET/CONFIRM and ESC/CANCEL
both have `any=true` and Ctrl/Shift/Alt/OSKey values of -1. The corrected matcher
honors that wildcard. Both runs preserved their result JSON, native log, exact
input/source hashes and manifest. Each verified private resources and
TEMP/TMP/TMPDIR and unchanged source/bytecode fingerprints. The runner
`tests/p25/run_native_preview_navigation.py` launches one fresh factory-startup
background process per invocation, BelowNormal with two threads and a bounded
timeout. Exactly two processes were used for this additional check; the earlier
four numeric/modeling processes were not rerun. No code in the add-on, contracts
or managed application changed for these checks.

After preserving these two runs, the runner's reporting was tightened without
launching another Blender process: required keymap/navigation assertions and
optional panel observations now have separate collections. A failed required
assertion has outcome `failed` (runner exit 1); successful required assertions
with unresolved panel/context observations have outcome `pending` (runner exit
2, `passed=false`); only a complete result has outcome `passed` (exit 0). Four
pure Python outcome tests passed, including a required failure accompanied by
optional pending observations. Ruff passed for both navigation scripts and this
outcome test. The archived native result retains its original 34-assertion failed
schema unchanged; the revised reporting code was not rerun in Blender. Its
separation corresponds to 26 required assertions passing and six of eight panel
observations passing in the preserved run, with two explicit pending failures.

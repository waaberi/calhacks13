# P2.5 native preview and spatial sketch bridge

This feature branch is independent of the active P2 hardware runtime. It adds an
optional input/drawing component; it does not change native coordinates to repair
placement, revise accepted grip dragging, or establish a physical acceptance pass.

## Integration API

`PreviewSpatialDrawing.Initialize(HostScene, Material)` binds the existing host
events and scene display root. It starts with spatial input disabled. The preview
controller owns trigger/grip routing and synthetic input cleanup.

| API | Meaning |
| --- | --- |
| `SetEnabled(true/false)`, `EnabledForInput` | Explicit spatial mode; no automatic takeover of P2. |
| `TryAim(Ray, out hit)`, `Press(Ray)` | Ray/plane hover and trigger point selection after preview/menu hit routing. |
| `SelectTool("line"/"circle"/"rectangle"/"select")` | Explicit bounded spatial adapter tool. Actual native toolbar selection is also read. |
| `CreateSketch("XY"/"XZ"/"YZ")` | Typed native planar sketch creation, in meters. |
| `Cancel()`, `Undo()`, `Redo()`, `Save()` | Discard local drafts or use the existing native transaction/history path. |
| `BeginNativeUi()`, `EndNativeUi()` | Request/release the connection-owned native desktop reservation. |
| `IsNativeUiOwned`, `NativeProcessId`, `NativeStateCurrent` | Admission checks for the Windows input bridge. |
| `NativeModalActive`, `NativeState`, `StatusText` | Actual native modal/tool/options/availability and failure feedback. |
| `Session`, `SelectedEntityId` | Native receipts/identity and local spatial selection using native entity UUIDs. |

The preview controller must release all owned synthetic input and receive its
acknowledgement before calling `EndNativeUi()`. Focus loss in the drawing component
only cancels local drafts. Switching to spatial mode must wait for native modal
completion/cancellation and reservation release. The same connected owner can
resume a retained UI reservation to send Enter/Escape; another writer cannot.
On transport loss the helper's owned-input watchdog and native disconnect cleanup
remain separate requirements; an HTTP failure is not evidence of input release.

## Actual reuse and coordinate authority

The native CAD adapter and command/receipt state machine are selectively reused
from the C implementation at `a3aa1fb`. P3 menu/ownership UI and unrelated C stack
changes are not imported. The existing validated command/lease path applies edits
on Blender's main thread, invokes the real pinned CAD Sketcher 0.32.1/slvs 3.2
solver, reads native geometry back, flushes scene deltas and pushes one Undo step.
There is no replacement solver in Unity.

`PreviewSketchMapping.TryMapRay` intersects the actual native sketch plane in the
displayed workspace. It removes the scene placement matrix, swaps Unity Y/Z back
to Blender Z-up, removes the native plane transform, and returns sketch-local
meters. Moving/rotating/scaling the table changes display placement only. It also
supports nonuniform invertible display transforms using an inverse-transpose
plane normal. Singular/nonfinite transforms, invalid quaternions, parallel or
behind-controller rays and out-of-bounds points are refused.

Orange preview geometry is an uncommitted two-point local draft. The second click
requests a real native line, corner rectangle or circle. Only native scene records
are rendered as solved geometry. A receipt rejection/unknown outcome never turns
the local draft into a committed object. Native generation/tool/active sketch
changes, disconnection and VR focus loss cancel stale local drafts.

## Coverage boundaries

All ordinary Blender buttons remain the preview input bridge's responsibility.
This spatial bridge adds line endpoints, circle center/radius and opposite corners
of an axis-aligned sketch rectangle. Rectangle horizontal/vertical constraints are
native CAD constraints. Selection identifies native points/lines/circles locally;
it is not claimed to replace Blender's own native selection UI or constraint menu.

Native toolbar tool IDs, active sketch UUIDs, selected native UUIDs, current mode
and relevant options are read from the actual pinned add-on. Continuous Draw,
Auto Constraints and Live Project Snaps are explicitly reported as unsupported
and must be turned off before these spatial gestures arm. Other native tools
remain usable through the preview; their spatial behavior is not fabricated.
No promise is made that an arbitrary native modal tool accepts these gestures.

Scaled/mirrored/sheared planes, native 3D sketches, unsupported native entities and
unsupported/reference constraints are omitted from the spatial sketch records and
reported through `unsupported_sketches`. Other native sketches and objects keep
syncing. The accepted baseline's per-object mesh isolation remains intact; the
older C whole-document disconnect-on-unsupported policy is deliberately absent.
Restoring a supported native plane allows that sketch to synchronize again.

## Native preview editing permission

`preview.ui.begin` validates current actor/session/document, editable local VR
admission, current leases and active native modal state. It reserves the existing
exclusive lease as the **host desktop actor**, because injected native mouse input
is desktop Blender work. A foreign VR lease would make the existing desktop gate
block that work. Other supported native commands conflict with this lease.

The requesting connection owns the reservation token; another connection cannot
release or resume it. Input is disabled immediately when ending. The reservation
persists across mouse release, disconnect and native modal operations until
Blender's real `Window.modal_operators` collection reports completion/cancellation.
The P3 input-gate observer is excluded. Missing modal introspection fails closed.
Existing host desktop reservations are not silently nested or adopted.

This is one document-wide preview editing lane, not a universal script/add-on
locking guarantee. The parent input controller separately checks capture PID,
native process/document identity, focus and fresh pixels before native input.

## Verification and remaining evidence

The new pure tests exercise host-desktop lease ownership, wrong identities,
read-only denial, foreign ownership, modal end/disconnect retention, same-owner
resume, expired reservation denial, option reporting and unsupported-sketch
isolation. Backend command/lease/session tests and schema examples exercise the
existing transport boundary without running Blender or a headset.

The first sketch dispatch run failed all three tests because the newly advertised
`capabilities` field had not yet been added to the strict welcome schema. The
additive capability schema fixes that failure; it was not a native solver failure.
The P2.5 extension's hierarchical message types and examples are now documented
and validated in the shared contracts.

`tests/p25/native_spatial_gate.py` is the isolated native gate, prepared for the
coordinator to run in a disposable background Blender with a copied pinned CAD
extension. It creates/solves native lines, rectangles and circles, verifies
constraints/dimension edits and rollback, checks unsupported-plane isolation, then
saves an editable copy. A fresh `--phase reopen` process verifies UUID/geometry
persistence and further native dimension editing. Native Undo/Redo are attempted
when that background context permits them; unavailable history is explicitly
reported and leaves the native history gate open (`--require-history` makes it
fail). It also records native modal introspection availability. These scripts
must not be run against the existing P2 host or any personal file.

No physical drawing, broad native UI coverage, pop-up interaction, live video or
P2 integration acceptance follows from the managed/pure test results. Those gates
require a later coordinated isolated build and the exact physical candidate.

# P2 local candidate — integration held for P1

This work is on `codex/talia-p2-local-completion`, based on fetched team `main`
`51d5176`. No push, merge, phase-pass tag, VR Player launch, or headset acceptance
is part of this work. Talia must confirm P1 is complete and approve P2 integration
before these changes enter her running app.

## Reused work

- Waaberi's merged P2 host implementation, contracts, coordinate conversion,
  snapshots, live updates, TLS-PSK helpers, and reconnect behavior from main.
- Jihyeon's existing `HostLink` background parser and `HostScene` mesh renderer.
- Talia's existing P1 `WorkspaceObjectView` native/inspection separation and
  `GrabPoseSmoother`. The copied view component gains parent-ID/generation metadata.
- The two Windows closed-port assertion timing fixes already reviewed in PR #122.
  The assertions still require `ConnectionRefusedError`; timeout remains failure.

## Local implementation

**Read-only second Blender (#43).** Client preferences now provide address, port,
TLS token, Connect and Disconnect. Connect refuses a personal file or nonempty
session. The client mirrors the real host into its own nonselectable collection,
using meters, stable IDs, evaluated meshes, colors and world transforms. Parent
IDs remain metadata; transforms are not applied twice. Transform-only updates
reuse meshes. No received data executes as Python and no client edit is sent.

The viewport and preferences distinguish connected/current data from a stale
scene. A dropped connection obtains a fresh snapshot; a different document epoch
requires an explicit new connection. Opening a file, switching role or disabling
the add-on stops the client and cleans up only owned mirror data. The P2 client
stays read-only even if the host advertises permission for later editing phases.

`tests/backend/check_snapshot.py` checks a saved snapshot against independently
recorded object IDs, meter positions and the expected host unit scale. It accepts
a wire envelope or a raw snapshot payload.

**Table setup (#45).** `TablePlacement` shows a preview and hides the model until
Place Table. It provides point-to-position, height, distance, size, yaw, Move,
Cancel, Recenter/confirm and Reset View. Both controllers can point and trigger
buttons; the stick changes distance/yaw. Enter places, M moves, R resets and
Escape cancels. Tracking-origin reset requires placement confirmation. These are
local inspection controls and have no native-command dependency.

**Receiver (#48).** Scene objects stay flat below one display parent because the
wire carries world transforms. Render meshes and selection colliders update
together. Meshes over 65,535 vertices use 32-bit indices. Object identity and local
arrangements persist through same-document snapshots. A new document requires
placement confirmation. Invalid/incomplete scenes or revision gaps trigger a fresh
connection rather than silently presenting a partial scene as current.

## Verification on Talia's PC

- Unity 6000.6.5f1: isolated Windows build succeeded, **zero build errors**. The
  executable is an unlaunched candidate, not a physically accepted VR build.
- Edit-time checks passed: parsing on a worker, real native 20 mm geometry,
  renderer/collider pairing, 32-bit mesh indices, stable IDs, two table poses,
  native/view separation, retained arrangements/placement through snapshots,
  Cancel, tracking-reset confirmation, corruption refusal and 14 control actions.
- Real Blender 5.2.2 in two isolated processes: TLS snapshot, IDs/units/20 mm
  dimensions, heartbeat, live move/add/delete, stale warning, reconnect snapshot,
  wrong-epoch refusal, refusal of a nonempty session, and cleanup passed. The
  actual Client preferences, connection operator and add-on lifecycle were used.
- Complete native snapshots before/after the initial read-only connection were
  identical. One native Undo still reverted just the host's marker and Redo
  restored it. Host-observed client traffic contained only `hello` and `ping`.
- Backend regression suite: **835 passed, 33 skipped, 3 deselected**. The existing
  full GUI host/gate checks were deliberately not run against occupied P1 ports;
  the new native test used ephemeral loopback ports and isolated preferences/temp
  folders. Skipped bpy/SpacetimeDB integrations do not become passes.
- Ruff passed for the changed Python code and test tools.

The initial native harness sampled Blender's dirty flag before its first event
loop settled; only that flag changed. The harness now establishes its baseline
before the client starts, after startup settles. An initial finish-ack ordering
error in the harness was corrected. Both failures remain in local evidence.

## Required later acceptance

No full P2 pass is claimed. After Talia confirms P1 completion and P2 integration:

1. Reconcile this receiver/table component with the final P1 `HostScene`, input,
   status display, view arrangements and tested tracking/drag behavior. Keep the
   P1 capture helper and native host intact until an approved combined build is ready.
2. Use the final accepted P1 XR/graphics settings. Batch-generated settings from
   this isolated authoring work are not a replacement for the tested P1 settings.
3. Verify physical pointer/button usability, comfortable table height/distance/
   size, two placements, rotation/zoom, tracking reset and reconnect in the headset.
4. Compare fresh native dimensions and actual Undo/Redo history around those
   physical table operations. Local component tests do not replace that trial.
5. Run the client on the real second PC and permitted event network. Two processes
   on this PC prove the software path, not peer connectivity or Lee's hardware.
6. Rerun earlier accepted functionality in the combined build, obtain team review,
   and only then consider the shared #52 gate and a passing tag.

## Repeatable non-VR checks

Use the project's Python 3.13 test environment:

```powershell
python -m pytest tests/backend -q -k 'not addon_in_gui_blender and not gate_in_gui_blender and not addon_in_bpy_module'
python tests/backend/run_p2_native.py --blender 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --output '<new evidence directory>'
```

For Unity, run a separate batch editor on this worktree with `-batchmode
-nographics -quit -executeMethod P2Checks.Windows`. Set `CALHACKS_P2_BUILD_PATH` to
an EXE outside the repository, and optionally `CALHACKS_P2_NATIVE_SNAPSHOT` to the
native test's `native-before.json`. Do not launch that EXE before the integration gate.

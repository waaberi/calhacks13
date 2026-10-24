# Bounded controlled Blender Client command

P3A adds one explicit **Move host object +10 mm X** operation. Open a separate
empty unsaved Blender, select Client role, connect its existing TLS mirror, then
open **3D View > Spatial > Controlled remote test**. Both the local test checkbox
and the host's **Let the Client role edit (test only)** preference must be on.
Both default off. Choose the current named host object and press Move once.

The ordinary P2 mirror remains read-only: no optimistic geometry changes, local
edit echo, material changes, or general P5 editing. The copied document/open
epoch, target ID and generation are checked against a fresh authenticated host
snapshot. The worker then acquires a shared lease and sends exactly one typed
`object.move` with `by: [0.01, 0, 0]` in meters. The host remains the native
authority and returns the receipt. A queued operator reports pending; accepted
appears only after a matching native receipt. Mirror geometry changes only by
the ordinary host scene update.

Cancel is available before native send. Cancellation and beginning send are an
atomic decision; after send, a receipt determines the outcome. Mirror disconnect
synchronously cancels an unsent draft. Currentness/target changes also cancel it
on the main-thread result timer. Late or timed-out grants cannot dispatch a
command, and closing the worker connection releases the permission. Native
execution continues under the host's existing disconnect/commit protections.
Lost acknowledgement produces unknown and disables further requests until a
different fresh mirror has been inspected and the user explicitly confirms it.
No native command is automatically retried.

Networking runs on a bounded worker without bpy calls; Blender preferences,
target capture, status updates and mirror application stay on the main thread.
The separate short-lived TLS command connection uses a separately authenticated
actor. Its ownership is visible under the actual authenticated participant name.

## Verification and limits

`test_remote_control.py` and `test_remote_state.py`: **25 passed**. These cover
real TLS framing/heartbeats, flag-off refusal, stale/missing/wrong targets, actual
lease at apply, one command, matching receipt, lost receipt, native unknown,
secret-safe errors, cancellation and delayed permission timeout.

Run the production integration proof with Python 3.13:

```powershell
python tests/backend/run_p3_client.py --blender /absolute/path/blender.exe --output /outside/workspace/evidence --scale .001
```

Repeat with `--scale 1.0`. Two actual Blender 5.2.2 processes passed both scales:
the real registered operator, actual add-on preferences, production P2 TLS
transport, state cache and mirror are used without state/prefs adapters. The
host flag-off welcome disables the actual operator and native command count is
zero. Flag-on performs exactly one leased native +10 mm X movement; native
positions, matching receipt and mirror agree. The actual Cancel operator and
mirror disconnect before delayed permission each send no second mutation.
Fresh mirror reconnect retains exactly one accepted move. Source SHA-256 values
are captured before and after each test. Each isolated host is closed and only
owned resources are removed.

Evidence runs `run-01-mm` and `run-02-m` preserve native host/client logs, full
host receipt/command reports and client assertion/source-hash reports outside
the repository under `p3-client-evidence`. The first run used normal Blender temp
recovery; the runner now isolates TEMP/TMP as well as Blender user resources.
No personal Blender file/window, original live Host, Unity, capture or XR was
modified. This is loopback software evidence, not a real second-PC/event-network
test, headset/keyboard acceptance, full P3A acceptance or full P5 editing.

Implementation reuses the native worker's `0553e73` controlled transport/UI,
adding production P2 registration/capability and cancellation/deadline handling.
It is prepared against reconciled P2 `31708f5`; cumulative integration must
include the final tested P2 predecessor and native receipt hardening separately.

## P3B presence hooks

The mirror transport forwards real `session.update` and `activity` payloads to
its bounded main-thread event queue. `remote_client.presence` stores the complete
authenticated participant and lease lists, the mirror welcome's actor ID, and
the most recent 32 activities. Each full session update atomically replaces the
previous lists. Names come from actual participants/lease owners.

`remote_client.ownership_state()` returns `(leases, actor_id, status)` for the
native ownership overlay; `participants()` exposes a copied full participant
list. All returned lease/name data is copied. A stale, unhealthy, disconnected or
not-yet-current mirror returns empty ownership and actor ID. Disconnect clears
participants, leases and activity. Presence updates never call `Mirror.apply`,
change scene currentness/revision, take a lease, or modify any saved material.
Malformed presence is discarded and controlled editing is disabled until a
fresh welcome; the independently valid read-only scene can remain visible.

The focused suite now passes **31 tests** including atomic presence replacement,
actual names, bad leases/duplicate participants, bounded activity and reconnect
clearing. Actual two-Blender run `run-03-b-mm` additionally verifies a real
native-host lease with owner name **Native Client Owner**, unchanged live mirror
revision/colors/materials during lease/release, real command activity, and empty
ownership after disconnect. Native ownership draw handlers and strict native
lock bypasses remain the native worker's separate checks; this hook does not
claim a visual, strict-lock, headset or second-PC pass.

## P3C solved sketches in the read-only Client

The former P2 Client ignored `payload.sketches` in both its cache and display,
while the native CAD adapter intentionally excludes those sketch display objects
from generic mesh records. A current-looking Client therefore omitted all CAD
geometry and editable sketch data. The C increment repairs both paths.

`SceneState.sketches` atomically retains complete UUID/generation, rigid plane,
solver status/DoF, solved point/line/circle entities and editable constraint
IDs/values. Snapshots replace all records; updates replace full changed records
and remove object/sketch IDs. Invalid IDs, duplicate/cross-kind IDs, missing
references, nonfinite geometry, invalid planes and regressing generations reject
the whole update. An invalid sketch cannot partially remove valid objects.

The mirror creates owned read-only Blender Curve objects keyed by each sketch
UUID. Lines use actual solved endpoints, circles use 128 segments at the exact
host-solved center/radius, and the rigid host plane places those meter coordinates
in world space. No Client constraint solver is installed or invoked. Complete
editable records are preserved as plain JSON in `spatial_modeling_sketch_record`;
document identity/units are preserved on the owned collection. JSON is never
executed. Geometry changes only from host snapshots, no local echo exists, and
the C code creates no materials. Ownership leases target the same sketch UUIDs.

Native serializer error code `failed` now retains its safe code and presents a
fixed local host-scene-unavailable/stale diagnosis; arbitrary host error text is
never displayed. Recovery still requires an authoritative fresh snapshot.

Verification: **46 focused tests pass**, including full editable preservation,
dimension/generation/removal, atomic failures and analytic circle tessellation.
The earlier P3A/B checks remain included; Ruff passes.

Actual pinned CAD Sketcher0.32.1/slvs3.2 Host and separate solver-free Blender
Client (`run-08-c-real`) passed baseline100x60mm, live120x60mm, circle20→30mm,
angle45→60degrees, actual rejected-width rollback, native Save, explicit mirror
reconnect and saved mirror JSON. A fresh solver-free Blender reopened that saved
mirror and preserved all3 full editable records exactly. No state/prefs adapters
were used. Focused real-host `run-11-c-faults` and final-source
`run-13-c-final-faults` passed full
sketch ownership/name, unsupported-frame serializer refusal/stale diagnosis,
cleared ownership, restored-frame/fresh-snapshot recovery, native sketch deletion
and reconnect. Inbound Client messages were only hello/ping. These focused fault
checks explicitly report dimension/native-reopen/mirror-reopen as not run.

The initial strict combined roundtrip **failed**: native host reopen in run08
changed the angle sketch's implicit origin point UUID and its synthetic fixed
constraint UUID. Native driving constraints, solved geometry and solver status
otherwise matched. Subsequent runs09/10 unexpectedly rejected the solvable native
45→60degree edit. Client checks did not ignore the mismatch or convert those
failed gates to passes. Runs06
and07 also retain a corrected harness error (the first native point was the
implicit origin, not the circle's referenced center). All raw failures remain.

Reproduce with `tests/backend/run_p3c_client.py --blender <executable> --output
<fresh-outside-folder> --extension <pinned-CAD_Sketcher>`. During independent
preparation, `--host-root <CAD-worktree>` selects the actual CAD implementation;
the cumulative branch uses its own source by default. Host bootstrap reuses the
CAD tests' isolated wheel extraction and registration, preserving personal
preferences. `--faults-only` runs the independent baseline/ownership/fault/delete
checks and explicitly makes no complete-roundtrip claim. The default keeps the
strict native full-record reopen equality assertion. No phase, strict native
lock, physical headset or real second-PC acceptance is established here.

### Complete strict roundtrip after the native cache fix

`run-14-c-native-cache-fix` passed the default complete check with Client source
`eada61ff1b2af6ffa98ca139764b6326980582c7` and native CAD source published as
`ed6c8f6b4b9a92d1bec79aa10ae8e3748afc7128`. The native adapter's SHA-256 was
`9dbb57f92b07a31ad36a4a94ebceabe584d51020a47734d4b45f6b8071982500`;
the full native production source hash map remained unchanged during this run.
The native fix uses the pinned dependency's public UUID-cache invalidation API
after staged native datablock changes and before editable record reads. Client
source and strict equality assertions were unchanged.

Both actual Host/Client process pairs passed: native100x60→120x60mm, diameter
20→30mm, measured angle45→60degrees, rejected constraint invariance and native
Save; fresh native host reopened exactly the same full entity/constraint IDs,
values, solved geometry/status and re-edited130x60mm into a fresh Client.
Both phases passed full-sketch ownership/names, serializer fault/stale/empty
ownership, fresh-snapshot recovery, native deletion and explicit reconnect.
Client inbound messages remained hello/ping only. A fifth, fresh solver-free
Blender reopened the saved mirror copy and all3 complete JSON records matched
exactly. Earlier failed runs remain preserved. This establishes these component
software gates, with cumulative build and physical/second-PC checks still owned
by the coordinator.

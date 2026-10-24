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

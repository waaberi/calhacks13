# Native editing validation

The inherited host command implementation is validated with actual Blender 5.2
instances; these checks do not establish headset or second-PC acceptance.

## P3A repeatable check

Set `P3A_BLENDER` to the Blender executable and optionally set
`P3A_EVIDENCE_ROOT` to a new output directory outside the source tree. Run
`python -m pytest tests/backend/test_p3a_native.py -q` with Python 3.13.
The opt-in check creates isolated preferences and ephemeral localhost/TLS ports.
It preserves the user's existing Blender windows and host listeners.

Both unit scales (1 and 0.001) passed: native cube, sphere and cylinder creation;
selection/active-object preservation; an actual 10 mm move and 90 degree
rotation; scale/delete; shared one-step Undo/Redo; stale/missing/invalid/changed
duplicate requests; receipt lookup; Save; and fresh Blender-process reopen.
An independent second Blender process connected through TLS loopback, was
refused with the test flag off, and made one controlled 10 mm host edit with
the flag on. Raw messages are checked against the wire schemas.

This controlled command test is separate from production remote editing UI,
two-computer networking, VR numeric entry, menu usability and physical tests.
Save on an unnamed file still requires the host's native Save As dialog first;
clients cannot choose arbitrary server filesystem paths.

## Opt-in Client move operator

The Spatial sidebar's Controlled remote test panel is disabled by default.
With a current P2 Client mirror and its connection preferences available, enable
the local test switch, choose the host object by its actual name, and request
one +10 mm X move. The host must also enable Client edits (test only).
`remote_control.py` creates a separate authenticated TLS connection, checks the
document/open epoch and target generation, obtains a shared reservation, sends
exactly one command and waits for the matching native receipt. It never changes
the local mirrored geometry directly. Ordinary P2 mirror traffic stays read-only.

Pending requests disable another move. A lost/invalid acknowledgement is unknown
and blocks further edits until the mirror reconnects, the user checks the scene,
and explicitly allows a new request. Neither the command nor an unknown outcome
is retried automatically. The native shared commit protects the lease through an
executing transaction even if this independent connection closes.

Fourteen transport tests passed, including TLS flag-off, wrong/stale/missing
target, conflicting lease, changed target after grant, lost/invalid receipt and
no automatic resend. A second actual Blender process invoked the registered
`bpy.ops.spatial_modeling.remote_move_test` entry point: local switch off, host
switch off, pending state and the applied native 10 mm result passed in both
unit scales. Only the P2 state/preferences interface was adapted in this bounded
test from an authenticated real snapshot; full cumulative P2 UI integration
remains the coordinator's separate check.

`tests/backend/p3_host_smoke.py` supplies a long-lived isolated real Blender host
for the Windows app/menu integration check. Set fresh output/resources paths and
an unused loopback port; `ready.json` identifies the host, `report.json` reads
actual native state, and `stop.signal` cleanly ends only that test host. It passed
startup, leased native add, numerical readback, Save and clean shutdown.

## Bounded receipt safety

The host formerly accepted an ID again after its receipt or missing-request
fence had been evicted. Receipt queries could trigger that eviction. It now
refuses every unseen command once any entry has been dropped, until a fresh
hosting session starts. Retained identical receipts still replay without a
second edit. The 10,000-entry bound is retained; no unbounded tombstone list is
introduced. A read-only participant can exhaust this shared history and cause
new edits to require a hosting-session restart. Save the document before
restarting. Use File > Save in host Blender; remote/VR Save commands are refused
after capacity exhaustion too. Reconnecting just the client does not reset the
safety boundary.

`tests/backend/test_receipt_capacity.py` exercises evicted applied IDs, evicted
query fences, new writes after capacity, and retained receipt replay. The
command suite plus this regression passed 77 tests on Python 3.13.

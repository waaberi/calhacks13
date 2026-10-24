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

## Bounded receipt safety

The host formerly accepted an ID again after its receipt or missing-request
fence had been evicted. Receipt queries could trigger that eviction. It now
refuses every unseen command once any entry has been dropped, until a fresh
hosting session starts. Retained identical receipts still replay without a
second edit. The 10,000-entry bound is retained; no unbounded tombstone list is
introduced. A read-only participant can exhaust this shared history and cause
new edits to require a hosting-session restart. Save the document before
restarting. Reconnecting just the client does not reset the safety boundary.

`tests/backend/test_receipt_capacity.py` exercises evicted applied IDs, evicted
query fences, new writes after capacity, and retained receipt replay. The
command suite plus this regression passed 77 tests on Python 3.13.

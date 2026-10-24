# Blender ownership and native lock boundary

The Blender add-on draws pink bounding outlines and the authenticated owner's
name for other participants' shared targets, including linked data. Exclusive
leases mark every displayed object. Release/disconnect removes the marks. The
draw handlers do not change object colors, materials, geometry or selection.
The Spatial sidebar shows active owners and a persistent bypass warning.

## Executed native tests

Actual Blender 5.2.2 GUI input simulation exercised default G/R/S, clear/mirror,
Delete, Apply/context menus, subdivision, Tab, Undo/Redo, sidebar and Properties
numeric fields, modifier clicks/hotkeys, transform gizmo and Tweak drags. Those
documented routes were refused before the state changed. A second object
sharing the same mesh was protected; independent objects remained editable.
Exclusive mode blocked add/duplicate, unrelated transforms/history and scene
unit fields. Release and disconnect restored the supported native inputs.
Backend tests also exercised heartbeat expiry, competing commits, linked data,
stale drafts, and disconnect/expiry during a transaction.

The first GUI run failed an unlocked modifier-hover assertion after Undo had
altered the test fixture. That failure is retained. A follow-up used an explicit
unlocked modifier fixture and searched for the real hover target; the remaining
unlock/disable routes then passed. This is a disclosed test-harness correction,
not a change to the production input gate.

The actual pink outline/name rendering was captured in a GUI screenshot after
21 executions of each draw callback, with no GPU callback errors. Material
assignments and object colors were equal before and after ownership display.

## Strict locking remains failed for unrestricted native routes

Four executed native routes changed protected state: Python/RNA location,
unwrapped native modifier operator, Python child deletion, and native scripted
Undo. The observer detected and reported these changes afterwards. That is a
failed prevention test for each route. Header menus, F3 search, custom mappings,
scripts and arbitrary other add-ons are outside the documented input gate.
Leaving a newly entered Edit Mode on the next timer tick is recovery; it is
not a universal pre-mutation guarantee. No strict or full P3B pass is claimed.

## Reconciliation admission fix

A real Blender sequence reproduced another defect: an unrestricted change to
leased Cube followed immediately by a typed change to independent Spare.
Commands' pre-write flush noticed the change, but only queued a later warning;
Spare was mutated and its applied result sent before a fresh snapshot.

The observer now freezes writes synchronously without recursively flushing.
The dispatcher must reconcile and send the fresh snapshot before admitting
another mutation. The real replay confirmed snapshot-before-apply ordering.
With an intentionally failing snapshot broadcast, the next command was refused
with `permission_denied`, Spare was unchanged and the dispatcher stayed frozen.
The original unauthorized Cube mutation still happened and remains a failed
strict gate.

Reproduce with GUI Blender, `--factory-startup --enable-event-simulate --python
tests/backend/p3b_bypass_race_check.py`. Set isolated `BLENDER_USER_RESOURCES`,
`P3B_LOCAL_PORT`, `P3B_LAN_PORT`, result/message output paths and
`P3B_EXPECT_RACE=0`; `P3B_BLOCK_SNAPSHOT=1` exercises failed reconciliation.
The companion `p3b_gate_complete_check.py` and `p3b_ownership_check.py` run the
native input and display checks. They use separate nondefault ports and never
touch the active host or personal Blender documents.

Physical two-person/headset and real second-PC tests remain pending.

The bounded lease-acquisition response cache had the same replay ambiguity as
the command receipt cache: a released acquisition could be replayed after
eviction and grant a fresh lease. A real socket regression with a three-entry
cache reproduced it. The host now refuses unseen acquisition IDs once any
response has been dropped. Existing leases remain releasable; new acquisitions
require a fresh hosting session. The native commit/timeout/disconnect rules
are unchanged.

# P2 reconciled with the accepted P1 workspace

The cumulative P2 feature branch is `codex/talia-p2-integrated`. It combines
published P1 `b532c641` with prepared P2 `47c6b6a`; their merge base is `ca03e83`.
Prepared P2 already includes upstream `51d5176`, including host leases, receipt
recovery and VoiceCore dependencies. These existing upstream changes are retained
deliberately. Their presence does not establish P3 or P4 acceptance.

## Integration decisions

The final P1 capture helper, endpoint-aware ray stabilization, typed controller
poses, before-render movement, settled shared startup, passthrough and graphics
settings are the baseline. P2 adds explicit table preview/Place, Move/Cancel,
height/distance/size/yaw, Recenter confirmation and Reset View. The preview waits
for the common settled head pose, and the native model stays hidden until Place.

Prepared P2's independent legacy controller loop, raw table rays, extra world-point
filter and unconditional stick writes have been removed. Table buttons and point
positioning use the existing P1 stabilized Pointer aim and trigger edges, with
nearest-hit dispatch. Grip-driven screen, whole-build and part movement retain the
accepted P1 mapping. Table movement and local arrangements never send native edits
or acquire editing leases. B/Y/R use the single existing recenter action.

The receiver reuses stable object IDs and local arrangements through valid
same-document/epoch updates and reconnect snapshots. A new native document epoch
clears local part offsets and requires table confirmation. An ordinary object
generation increase means a native edit and preserves its local inspection offset.
Meshes and selection colliders update together; transform-only updates reuse them.
Incomplete/corrupt objects, missing native transforms, invalid identity/units and
revision gaps become stale and trigger a fresh snapshot, rather than being shown
as a current partial scene. Native wire meters/radians are converted only in
BlenderFrame; display magnification remains on the local parent.

The Client remains read-only. It refuses a personal/nonempty session, mirrors only
owned data, sends hello/ping, detects stale/disconnected data and cleans up only its
own collection. New document epochs require explicit reconnection.

Additive HostScene event and HostLink envelope hooks support the later native-menu
integration without introducing native commands into P2. Request IDs are preserved
by SendEnvelope; consumers validate their own phase-specific payloads.

## Software verification

Before the cumulative Unity build:

- Python 3.13 backend: **835 passed, 33 skipped, 3 deselected**. The deselected
  existing fixed-port GUI tests do not run against occupied P1 services. Optional
  bpy/SpacetimeDB skips remain skips.
- Two actual isolated Blender 5.2.2 processes, ephemeral loopback/TLS: stable IDs,
  meter positions/mm units/20mm dimensions, live transform/add/delete, mesh reuse,
  heartbeat, stale/reconnect, wrong-epoch refusal and owned-data cleanup passed.
  Host traffic was hello/ping only. Read-only connect left the native snapshot and
  actual Undo/Redo behavior unchanged.
- Capture regressions: **11 passed**; Ruff passed. P1 capture source is unchanged.
- Independent source review found no blocking reconciliation defect. This review
  does not replace a build, frame-performance measurement or hardware acceptance.

Run `P2Checks.Windows` in this worktree's own Unity Library with
`CALHACKS_P2_BUILD_PATH` set outside the repository. Optional
`CALHACKS_P2_NATIVE_SNAPSHOT` points to the native harness's `native-before.json`.
P2Checks exercises actual table-button colliders and dispatch, preview/Place/Cancel,
two placements, native/view separation, generation/reconnect preservation,
epoch/corrupt/incomplete refusal, topology/collider updates and 32-bit meshes.
It then calls `P1Build.Windows` for the real Unity stabilization/intent/controller/
startup/freshness/native-view and visual-alpha baseline gates, plus SDK credential
sanitization. Windows build and exact final checkpoint results are recorded below
when available; an unperformed check is not a pass.

## Remaining acceptance

Physical comfort, binocular readability, both-controller usability, two actual
table placements/inspection operations, final live-video clarity and native Undo
history around those operations require the final integrated build and the wearer.
Tracking reset/reconnect and the real second-PC/event-network test remain explicit
acceptance checks. Two local Blender processes do not prove the latter.

No full P2 acceptance, issue closure, passing tag or main update follows from the
software checks. The accepted `p1-capture-recovery-v20` executable remains the
rollback artifact. Historical preparation notes in P2_LOCAL_RESULTS.md describe
the earlier isolated candidate; the overnight user instruction authorizes this
integration and supersedes that earlier hold.

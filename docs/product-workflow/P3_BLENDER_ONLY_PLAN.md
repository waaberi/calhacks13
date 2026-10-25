# P3 remaining work: Blender-only editing with direct VR drawing

Human scope revision, 2026-10-24. This supersedes the separate P3 editing-menu requirements in PHASE_PLAN.md and its historical coverage appendices. The preserved original planning/PHASE_PLAN.md remains historical. No P3 implementation is started by this planning update.

## Product contract

- Blender's captured native interface, including its add-on panels, is the only editing menu. Use its tools, numeric fields, CAD dimensions/constraints, history, file actions and editing-mode settings.
- Keep direct VR drawing of native planar lines, circles and rectangles. Choose the native sketch/plane/tool through Blender; gestures create real editable native geometry through the existing permission/transaction path.
- Remove or leave disabled duplicate VR Model tools, transform/dimension keypads, primitive palettes, constraint menus and the old P3 hand editing menu in the delivered app. Preserve reusable backend services and regression evidence. A hidden legacy implementation may remain for compatibility, but it must not be reachable as another editing menu.
- Keep P2 workspace arrangement/settings and its accepted controller behavior. These are not model-editing menus. Keep necessary preview pointer/scroll/keyboard input and minimal noninteractive selection, drawing, ownership/error feedback; these are not an alternate modeling toolbar. A keyboard may enter Blender text/numbers; it must not grow a second modeling palette.
- Do not remove right/left pointer support just because the old hand editing menu is retired. Handedness belongs to existing workspace/input settings; do not add another settings panel for editing.
- Native model edits and local workspace arrangement remain separate. Local placement/inspection must not change native dimensions, history or acquire an editing lock.
- Strict shared-edit prevention remains an unmet requirement, not silently replaced by post-change detection. No FPS target, other-phase build or main merge is introduced.

## Reuse before building

Refresh remote refs and live board/issues before choosing a base. Historical P3 stacks contain older P2 UI and placement; do not merge those stacks wholesale over final P2/P2.5. Build an evidence-backed coverage matrix and port only missing compatible changes.

| Existing work | Reuse | Remaining boundary |
| --- | --- | --- |
| Final P2 / #157 / PR158 | Placement, current-room mapping, settings/independent planes, controller handling, physical-size correction, capture/startup guards | Current owner retains runtime and physical acceptance |
| P2.5 / #139 / branch codex/talia-p2-5-blender-interaction | Full preview input, owned popups/dialog routing, native UI reservation, native sketch context and direct drawing | Retire duplicate modeling overlays; physical GUI/input/drawing acceptance remains separate |
| P2/P2.5 integration / codex/talia-p2-p25-integration | Combined foundation, matching native/helper/app versions and current tests | Read planning/p2_p25/STATUS.json; never infer completion from an earlier snapshot |
| P3A #53/#58/#60/#66; historical ec407ab | Native commands, receipts, history/save, controlled Client command, input/settings behavior | Old separate editing menu is superseded; verify actual current ancestry before porting |
| P3B #75/#77/#78/#80/#81/#87; historical 443129f | Leases, linked-data/history scopes, supported-route gate, names/pink ownership and conflict feedback | Newer PR149/160/161 may supersede older Client/overlay changes; confirm current review/merge state |
| P3C #128; historical a3aa1fb, CAD Sketcher 0.32.1 / slvs 3.2 | Native solver/adapter, typed sketch transactions, conflict rollback, whole-sketch leases, history and editable persistence | Reconcile with newer P2.5 context/unsupported-sketch isolation; preserve per-object syncing |

These references are discovery points, not proof of current integration or permission to change PRs. Preserve original component ownership; the future P3 chat owns only the remaining-work branch and coordinated handoff.

## P3A: edit through Blender in VR

Working result: use Blender's own interface from VR to create/select/transform/delete real objects, enter exact values, Undo/Redo and save/reopen.

Remaining implementation:

1. Audit the integrated preview route, then disable/remove all alternate VR modeling menus and their entry points without breaking workspace settings, preview keyboard, direct drawing or native services. Coordinate any overlapping P2.5 UI files instead of editing its active worktree.
2. Reuse preview pointer/scroll/drag/keyboard/dialog support. Fix only demonstrated gaps affecting ordinary Blender editing, including owned popups, focus/capture identity, held-button release, modal completion/cancel and stale/disconnect recovery. Do not claim support for unsupported OS dialogs without real evidence.
3. Preserve right/left pointer choice and readable selected-object/unit/error feedback inside Blender. The held/pinned requirement now concerns the movable Blender panel, not another editing menu.
4. Keep native history/save/receipts and the existing controlled Client route. Never treat an injected click or shortcut acknowledgement as proof that Blender changed correctly.

Acceptance: through the native interface create cube/sphere/cylinder, select/move/rotate/scale/delete, verify actual 10 mm and 90-degree changes, Cancel, Undo/Redo, Save and fresh reopen. Cover both pointer hands and panel placement. Actual GUI input, binocular readability/controller comfort and real second-PC evidence remain distinct from background/software tests. Previously accepted P2 menus are not reopened.

Task mapping: P3A-W-1..4 and M1-1..3 retain their native obligations and reuse existing results. P3A-M2-1..3 now mean native Blender preview/input and settings integration, with no separate editing menu. P3A-T-1..3 and RC02/RC10/RC15 test this revised workflow; no FPS criterion or old hand-menu acceptance is carried forward.

## P3B: ownership and safe concurrent editing

Working result: choose Exclusive/Shared in the Blender add-on; show names, pink ownership and warnings in Blender, with optional noninteractive VR feedback. Inspection remains available.

Remaining implementation:

1. Reuse existing leases/gate/overlays. Bring forward missing reviewed overlay and Client mirror fixes; match the actual participant name and connection/conflict state without altering saved materials.
2. Reconcile native-preview reservation (currently host-desktop exclusive), native UI actions and spatial drawing under one ownership policy. Test begin/end/modal/disconnect/late-grant and global-history/linked-data scopes. Do not put a foreign VR lease in front of injected desktop input and deadlock Blender's own gate.
3. Put editing-mode choice in Blender's add-on. Retire the duplicate VR mode selector while preserving ownership visibility and conflict refusals.
4. Address #80/#87: supported-input gating does not prevent unrestricted native scripts/operators/menu routes from changing authoritative state. Preserve failing reproductions and detect/reconcile unsupported changes; this is recovery, not a strict prevention pass.
5. Develop and test an isolated strict-authority prototype using a private authoritative Blender worker and a non-authoritative Blender UI mirror, reusing existing command/Client paths. The user-facing menu must remain Blender. Prove supported UI edits and direct drawing reach authority only through validated commands, and local bypasses cannot mutate authority. This does not establish full Blender tool coverage: enumerate unsupported routes, and do not silently disable ordinary native tools to claim success. If strict authority cannot coexist with the promised full native UI using the current adapter, record the concrete incompatibility and required product/architecture decision; continue all independent A/C work. No production architecture replacement or acceptance relaxation is authorized by this plan alone.

Acceptance: real Blender and VR actors, shared/exclusive choices, same/different objects, linked data/sketch/history conflicts, owner overlays, expiry/disconnect and fresh recovery. Strict RC16 remains failed until actual prevention is demonstrated against the preserved bypasses. A closed implementation/test issue is not phase acceptance.

Task mapping: P3B-W-1..3 and M1-1..3 retain native protections/Blender feedback/testing. P3B-M2-1 moves its editing-mode control into Blender; M2-2..3 retain noninteractive feedback and conflict admission. T-1..3 / RC04 / RC16 retain real concurrency and bypass gates.

## P3C: direct drawing plus native constrained CAD

Working result: choose a native plane/sketch/tool in Blender, draw directly in VR, then edit dimensions and geometric constraints through CAD Sketcher's own interface. Both routes operate on the same native entities.

Remaining implementation:

1. Reuse P2.5 spatial drawing and P3C solver/persistence. Reconcile native active sketch/plane/tool, explicit UUID/generation, units, solved geometry and selection. A context/identity change invalidates drafts; a removed target must never redirect drawing to another sketch.
2. Retain native line endpoints, circle center/radius and rectangle corners, plus draft/commit/cancel and permission-before-mutation. Use Blender for plane/tool selection, numeric values and constraints; add no custom VR CAD menu.
3. Verify editing a drawn entity/dimension in native CAD UI refreshes the same VR geometry, and new direct strokes join the intended sketch without resetting native selection/context unexpectedly.
4. Preserve last-valid solver rollback, under/fully/conflicting states, whole-sketch ownership, native one-step history and editable fresh reopen. Keep unrelated objects syncing when a particular sketch is unsupported. Unsupported native tools/options/planes must remain clearly reported; do not fabricate spatial support.
5. Fix demonstrated native framing/contrast or capture gaps with a bounded, reversible approach; do not alter personal preferences/files or silently save a new viewport over a user's work.

Acceptance: anchored H/V 100 x 60 mm rectangle, width changed to 120 mm with height unchanged, circle diameter and angle/distance example, free/fully constrained states, conflict refusal preserving the valid sketch, Undo/Redo and cold reopen/re-edit. Use the same owned native document for drawing, solver, history and capture evidence. Preserve existing coupling/sampling failures; new software results are not physical acceptance.

Task mapping: P3C-W-1..3 and M1-1..3 reuse native solver/transaction/persistence obligations; future voice compatibility is an interface requirement only, not P4 implementation. P3C-M2-1..3 now implement native Blender tool/context integration and direct gestures/rendering, without duplicate dimension/constraint menus. T-1..3 / RC17 retain numeric solver/history/reopen verification.

## Parallel execution and delivery gates

1. While P2 integration/physical testing continues: use an isolated codex/talia-p3-blender-only feature branch/worktree outside OneDrive; inventory current ancestry first. Inspect existing checkouts before creating any new one. Own private resources/TEMP/logs/ports and disposable documents. No interactive OS input, capture selection, Blender GUI, headset Player or existing host/helper changes.
2. Work in order: coverage matrix and menu consolidation; A preview/native gaps; B cooperative ownership integration and isolated strict-authority prototype; C native-context/drawing reconciliation. B's strict gap does not stop independent A/C work.
3. Run targeted meaningful native/software/Unity checks against the exact candidate. Background operator/keymap tests do not prove native GUI event delivery. Use private build outputs and coordinate CPU/build contention with the active owner.
4. Deliver a feature commit/branch, exact evidence/build manifest, failed/unsupported cases and a small integration checklist. Follow current publication restrictions: no main push/merge; no PR creation/update/ready/retarget/merge without explicit human approval. Verify feature publication if authorized; do not rewrite others' branches or existing uncommitted work.
5. When P2/P2.5 owner reports a stable handoff, reconcile final changes into the P3 branch and run combined software gates. Interactive/native GUI, active XR, actual headset drawing/readability and real two-PC tests require a coordinated runtime slot, not automatic takeover. No repeated accepted-menu tests or FPS work.
6. Record separate statuses for implemented, software-tested, published, reviewed, integrated, physical/two-PC accepted and full phase accepted. Do not claim all P3 finished while strict locking or hardware gates remain unresolved.

Canonical issues: A #66 (UI #60), B #87 (UI #81, Blender #78, bypass #80), C #128; coordination #133. Read/update the live project board at meaningful checkpoints without changing teammate ownership. Do not dispatch other chats from this planning task.

# Headset placement and orientation contract

Read this before changing startup, recenter, tracking-origin conversion, the table
preview or the Blender screen. Preserve accepted aim dragging, capture quality and
render/passthrough settings. This is placement correctness, not FPS work.

## Demonstrated regression

On October24,2026 the user tested P2 app sourcec491999, assembly SHA256
52af0c54253b9f1e01591d3a505ee324b7d3cf3f4c81b0496a67b71a115a3db5. The user reported
the table off to the left and Blender facing right instead of the current forward
view. The retained Player log places `HostScene placement` and
`P1_SCREEN_PLACEMENT` immediately after HMDUnmounted/VrFocusLost and before the next
HMDMounted event. Both displays shared the same pose, but that pose was captured
while the headset was removed. Sharing a stale pose does not fix orientation.

The old gate accepted tracking when the XRNode userPresence feature was absent.
Link can keep tracking a headset on a desk. The unconfirmed preview then kept its
old seed across removal/focus transitions. A separate desktop camera fallback
could also commit before XR was active. Earlier gaze-only tests did not cover this
lifecycle and therefore could not establish correct headset startup.
The automatic tracking-origin callback also called the immediate B/Y recenter
path, bypassing the startup-facing delay. It now requests tracked placement with
fresh settling instead. New-document snapshots invalidate an old preview seed.
The old log did not record the exact readiness branch, so missing presence and
the inactive-XR fallback are both covered without inventing which one ran.

## Required behavior

1. A standalone VR Player waits for active XR, tracking, known worn presence and
   **VR session focus**. Missing presence is unknown and must not be accepted.
   The Meta runtime's presence/focus supply the supported Quest/Link signals;
   an available XRNode presence=false also refuses placement. Desktop-window
   focus is not VR focus: Blender may keep desktop keyboard focus during use.
2. After readiness, wait for the current horizontal facing to settle for0.5seconds.
   Reject downward/vertical or turning samples. Automatic XR-origin callbacks
   must not impersonate explicit B/Y intent or skip this delay. Removal/focus loss restarts the
   settling interval; elapsed time from before removal cannot qualify a new pose.
3. Unconfirmed Preview/Move placement loses its seed and hides on readiness loss.
   On return, seed from the new worn/focused pose. Keep Move/Cancel's saved pose.
4. An explicitly confirmed Place stays world-anchored through head movement,
   ordinary removal/focus changes and same-document reconnect. Recenter, actual
   tracking-origin reset or a different document still require fresh placement.
5. Convert the tracked local head pose through the tracking origin exactly once.
   Table and screen consume the same committed world pose and horizontal heading.
   Do not independently capture their camera poses, add a second yaw conversion,
   flip the screen180degrees or change native Blender coordinates to compensate.
6. No desktop/default camera fallback is allowed in a standalone VR Player while
   XR starts. Editor-only desktop inspection is distinct from headset acceptance.

## Verification and handoff

### Left-hand menu and world placement

The P2 controls start at the tracked left controller, approximately 12cm wide at
standard text size: one third of the previous approximately 35cm docked menu.
They do not use a head-relative HUD offset. The shared typed controller-pose
reader supplies world coordinates, including the tracking origin exactly once.
While docked, the panel follows the left controller and faces the wearer. Missing
left tracking hides a docked panel rather than displaying a stale hand pose.

Point at the menu with either controller and hold grip to move it using the
accepted aim-driven placement mapping; release leaves it in world space. Trigger
activates buttons. Gripping restores the existing full-size world menu while
preserving its pose; release leaves it anchored. The redundant "Pin menu here"
button is removed. "Return to left hand" restores the smaller docked scale after
a fresh tracked sample. Repeated docking or tracking loss cannot repeatedly
shrink it, and accessibility text size applies to both scales. A pinned menu never follows
subsequent head/hand motion. The menu root is independent from the model/table;
menu placement must not change native data, table pose, or screen pose. Only the
explicit table controls, recenter/reset, or genuine tracking-origin reset can
change table placement. The physical trial must verify the small left-hand start,
grip/release placement, head/hand independence, readable controls, and table
invariance. Software checks do not establish this acceptance.

The Windows build runs WorkspaceChecks and P2Checks through the real code. Required
regressions include tracked-but-unworn, missing presence, unfocused XR, cold loader,
remount with a different heading, pending-preview invalidation, confirmed placement
preservation, and a translated/rotated tracking origin with common screen/table
heading. Keep all accepted P1 aim/controller/native/render/freshness checks intact.

The physical replacement check is startup while worn, removal before Place,
remount facing another direction, and explicit Place followed by a head turn.
Recenter is a separate recovery action; its success does not pass initial startup.
Record exact build source/hash, the user's observation and placement-readiness log.
Do not inherit physical acceptance from another build or label a mathematical test
as a physical pass. Preserve failed observations. The originalc491999 build is a
known failed startup candidate for this lifecycle, even though its earlier software
checks and other accepted interaction evidence remain valid.

Published successors need this fix explicitly integrated and verified before they
can claim the repaired lifecycle. A matching old DLL/ZIP or a documentation-only
new head never means an old binary contains the correction. No other phase or
main merge is authorized by this repair.

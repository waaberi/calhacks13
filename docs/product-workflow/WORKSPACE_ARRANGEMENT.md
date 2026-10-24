# Direct workspace arrangement

This is the user's new interaction redesign after accepting the P2 menu on
679fd04. Prior P2 acceptance is preserved. It does not authorize native P3 editing,
FPS work, or a main merge.

## Meta room alignment repair

Meta's saved Scene Model is the source of wall, floor and tabletop positions,
orientations and bounds. Do not substitute the startup-facing direction for an
available scene anchor. The user's actual captured room is used by the optional
`CALHACKS_ROOM_REPLAY` verification gate; keep that raw room evidence local.

The real capture exposed the missing-desk bug: SDK207's `GetClassifications`
explicitly no longer upgrades legacy DESK to TABLE, while its `Labels` getter
does. Normalize both names. The reference room has four such annotations;
three are tabletop surfaces, and one is almost coplanar with the floor. Exclude
that floor-height patch from desk selection using the actual same-room floor.
This recovers real desk bounds and headings instead of showing a guessed desk.

An adjusting guide within30cm of a matching finite Meta surface adopts that
surface's position and orientation. At adjacent/overlapping annotations, retain
the chosen source unless another is at least2.5cm nearer. This prevents switching
between overlapping tabletops. Wall guides can move onto perpendicular walls.
Automatic orientation/contact changes rebase both one-hand and two-hand holding,
so the next frame cannot restore an obsolete pickup orientation. Stick click
selects free adjustment; automatic attraction is bypassed but desk/floor remain
horizontal and walls upright. Model contact behavior remains unchanged.

When a desk is genuinely unscanned, its manual fallback is a circular horizontal
height level. It has no guessed rectangular desk-edge heading. A detected desk
uses its actual rectangular bounds. Label/handle contrast and world stationarity
are retained. The circular fallback is not reported as an automatically detected
desk.

The captured Meta and Unity head poses agreed within0.03mm in the recorded sample.
The repair therefore preserves the existing tracking origin. Replay verifies all
four actual wall corner sets against the SDK's anchor-plus-Rect convention, each
real guide's attachment/orientation, tabletop volume tops, and horizontal desk
constraints. A replay failure exposed overlapping-desk selection before source
preference was added; its failed log is retained. Software agreement with Meta
data is separate from human acceptance of the scan's fit to physical walls.

Optional room diagnostics run after placement/visual updates, once per load.
An advertised component can still have unreadable bounds; capture skips those
fields and cannot interrupt the frame. The initial diagnostic assumed readable
bounds and failed in the live Player; that failure and its correction are retained.
No raw room layout or precise machine/user data belongs in public issue evidence.

## Modes and controls

The top-left of the Blender preview's app-owned frame says **Arrange space**.
**Edit model — coming soon** is visibly disabled until native editing is integrated.
The mode strip remains accessible when the preview image is hidden.

- Grip and aim to move the preview, menu, or whole build. Release leaves it stationary.
- One-hand model/part/level placement keeps its pickup orientation while aim still
  moves its position. Wrist pitch/roll no longer tilts the model during placement.
  Stick and two hands deliberately rotate it. After explicit alignment or a two-hand
  handoff, continued one-hand movement keeps the newly chosen orientation.
- While held, flick the stick left/right for 15-degree rotation increments.
  Up/down changes distance. Stick click toggles free placement for that grab.
- Grab the same item with the second controller to rotate and resize it. Releasing
  one hand continues single-hand movement without returning to the pickup pose.
  Individual-part inspection can rotate but cannot resize native object transforms.
- A nearby surface gets a wire grid and an outlined proposed orientation. Motion
  toward it stops at contact; parallel motion and the user's orientation are retained.
  Trigger deliberately accepts the suggested alignment. There is no automatic
  attraction or forced alignment. Free placement or Surface help off bypasses it.
- Undo placement affects viewer placement only, preserving newer native generations.
  Recover workspace recenters the preview/build, restores model arrangements, and
  returns the small menu to the left hand. Native geometry/history is untouched.

The whole assembly moves together by default. The existing explicit one-part
inspection option remains available. Display magnification is separate from
Blender dimensions. The primary left-hand menu now has surface setup and recovery
actions; height/distance/rotation button menus are no longer the main workflow.

## Room surfaces

Existing Meta SDK OVRAnchor scene components provide tracked floor/wall planes and
desk/table bounds, when available over the current OpenXR/Link runtime. Load saved
OVRRoomLayout anchors, then their layout and container UUIDs (including furniture),
in batches of at most 50. Enable localization before using poses. Furniture volumes
use their gravity-facing top face, even if they also expose a vertical 2D plane.
Multiple saved rooms are filtered by the localized floor containing the wearer.
No new SDK
dependency, camera recording, fake room mesh, global setting change or native
Blender edit is involved. Room data is queried, not captured by this app. Space Setup
and spatial-data availability are prerequisites for automatic detected surfaces.

Run Space Setup on the headset outside Link first, including the desk/table. Link
cannot initiate that scan. On the PC, **Spatial Data over Meta Horizon Link** must
be enabled in the Link app's Developer settings. The app does not change this
privacy setting. Empty results can mean missing scan OR unavailable spatial-data
access, so never diagnose them as proof of no scan. Reload retries after setup;
focus/wear transitions also retry, with bounded retries when no surfaces localize.
See Meta's [scene-anchor flow](https://developers.meta.com/vr/documentation/unity/unity-scene-ovranchor/)
and [Link spatial-data permission](https://developers.meta.com/vr/documentation/unity/unity-spatial-data-perm/).

Discovery is the primary query. If it fails or returns no rooms, the app tries
the SDK's older FB query API exposed by Link. If no RoomLayout is returned, it
also queries real semantic scene elements, using both paths when needed. Child
UUID fetches have the same compatibility fallback. Each result/status/count is
logged separately. This widens compatibility; it cannot create a missing scene or
bypass permission. On Windows the SDK's Android permission helper always returns
true, so it cannot establish Link spatial-data access. Zero across these queries
means **no data received**, not a verified missing scan. Do not keep asking the
human to test level visibility to diagnose automatic detection.

Detected surfaces are visible green grids immediately, with separate desk/floor/wall
counts. **Show/hide detected** controls their outlines; **Auto detection on/off**
controls whether automatic surfaces participate in placement assistance.

Choose **Desk: adjust / add**, **Floor: adjust / add**, or **Wall: adjust / add**.
When that kind has a detected surface, its nearest actual pose and dimensions
become the amber adjustment grid in place. The corrected level overrides only
that anchor; other desks/walls remain available. When no surface of that kind is
available, a manual amber grid appears along the settled workspace forward.
Repeated selection keeps the existing correction instead of resetting it.
Point at its
grid or central label, hold grip, aim/move it into place, and release. Desk/floor
levels remain horizontal; wall levels remain vertical. Automatic guide placement
adopts nearby matching Meta surfaces. Stick click enables free adjustment, where
left/right changes yaw; up/down changes distance and two hands resize. The guide stays visible and stationary
after release, ready to regrab. No controller-touch marking or hidden trigger capture
is involved. An adjusted level overrides its automatic source, so that
inaccurate anchor cannot fight the correction. Clear manual levels restores those
automatic surfaces. Levels remain usable when automatic detection is switched off.
The level uses a retained unlit material, thick yellow border with a dark backing,
double-stroke grid, visible yellow grip sphere and large white instructions on a
dark label. Lighting cannot dim the reference. The label/handle keep a readable
physical size when the plane is resized; only the label turns toward the wearer.

Physical e880714 feedback: manual placement was possible, but the level was hard
to see and objects tilted during grip movement and at alignment. This failure
overrides the earlier visibility-only pass. The complete grip path now separates
aim-based position from model orientation; helper-only rotation tests were
insufficient. Horizontal alignment preserves projected heading while levelling.

Physical e1dae7e feedback: contrast is now visible, but the guide starts left and
is angled after moving in front; this remains a physical failure. BeginLevel used
click-time head gaze while the wearer looked at the left-hand menu. New guides
now use HostScene.PlacementHeadPose, the shared settled world-space facing used
by model/preview startup, with current eye position. Never seed a stationary room
guide from menu-click gaze, default world +Z, or a controller's wrist orientation.
Desk/floor normals remain gravity-up; walls remain upright. A preceding wall's
rotation axis is cleared before another placement. Grip translates with preserved
orientation; stick/two hands intentionally adjust yaw. Label billboarding does not
rotate the guide. Research references: [Meta constrained transforms](https://developers.meta.com/vr/documentation/unity/unity-isdk-constrained-grab-interactions/)
and [Arkio alignment/adjustment/lock workflow](https://feedback.arkio.is/en/help/articles/13485781240092-aligning-and-locking-your-scene-in-mixed-reality).

Surface and controller poses use the same tracking origin exactly once. A tracking
origin reset invalidates manual levels instead of keeping stale physical surfaces.
Invalid/untracked room anchors are excluded. Late async queries cannot resurrect
surfaces after reset/toggle/destruction. Contact/alignment ghosts appear while holding
an item near a known surface; the surface grids are visible independently. Placement uses the actual mesh bounds or panel rect,
including origin offsets and display scaling, rather than placing object centres
inside the physical surface.

Placements, undo history and manual levels last for this session. Cross-session
physical-room anchoring/persistence is not silently approximated with saved raw
world coordinates. New-document/epoch changes clear placement undo history.

## Verification and limits

ArrangementChecks covers no-attraction/no-forced-rotation contact, non-centred
geometry, finite surfaces, fast wall crossing, escape from an existing penetration,
explicit alignment, tracking-origin conversion, two-hand rotation, native-safe
Undo, SDK-size UUID batching, rotated furniture top faces, visible grabbable levels,
horizontal/vertical constraints, automatic-off fallback, stationary planes through
head movement and mode-strip access with the preview hidden. The cumulative
checks also exercise actual model/screen pickup policy, aim displacement with fixed
orientation, stick rotation, explicit alignment and two-hand rebase retention.
An optional real camera render verifies unlit contrast/text without scene lights.
Actual BeginLevel callbacks now cover side-menu gaze against settled workspace
facing, repeated adjustment preservation, and prior-wall rotation-axis isolation;
additional cases cover arbitrary room yaw and per-anchor correction extents.
P1/P2 movement/controller/readiness/native/render/freshness gates stay in force.

Software checks do not establish physical room-scan availability or exact headset
alignment. The accepted old P2 binary remains a rollback. This redesign needs
focused new-feature observation, not repeated testing of the old accepted menu.
For this repair, the actual room was received and replayed; physical acceptance
of the replacement remains distinct from that software verification. Do not
request another scan or repeat an old menu test as an alignment diagnostic.

# Direct workspace arrangement

This is the user's new interaction redesign after accepting the P2 menu on
679fd04. Prior P2 acceptance is preserved. It does not authorize native P3 editing,
FPS work, or a main merge.

## Modes and controls

The top-left of the Blender preview's app-owned frame says **Arrange space**.
**Edit model — coming soon** is visibly disabled until native editing is integrated.
The mode strip remains accessible when the preview image is hidden.

- Grip and aim to move the preview, menu, or whole build. Release leaves it stationary.
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
desk/table bounds, when available over the current OpenXR/Link runtime. No new SDK
dependency, camera recording, fake room mesh, global setting change or native
Blender edit is involved. Room data is queried, not captured by this app. Space Setup
and spatial-data availability are prerequisites for automatic detected surfaces.

If room data is missing, the menu states that and offers **Mark desk / Mark floor /
Mark wall**. Touch the intended surface with a controller and press trigger. Desk
and floor markers are horizontal; walls face into the room. Manually marked planes
are approximate finite helper patches, not a claim that the furniture was scanned.
Grip cancels marking. Reload room surfaces retries the read-only scene query.

Surface and controller poses use the same tracking origin exactly once. A tracking
origin reset invalidates manual marks instead of keeping stale physical surfaces.
Invalid/untracked room anchors are excluded. Guidance is visible only while holding
an item near a known surface. Placement uses the actual mesh bounds or panel rect,
including origin offsets and display scaling, rather than placing object centres
inside the physical surface.

Placements, undo history and manual marks last for this session. Cross-session
physical-room anchoring/persistence is not silently approximated with saved raw
world coordinates. New-document/epoch changes clear placement undo history.

## Verification and limits

ArrangementChecks covers no-attraction/no-forced-rotation contact, non-centred
geometry, finite surfaces, fast wall crossing, escape from an existing penetration,
explicit alignment, tracking-origin conversion, two-hand rotation, native-safe
Undo, manual marking and mode-strip access with the preview hidden. The cumulative
P1/P2 movement/controller/readiness/native/render/freshness gates stay in force.

Software checks do not establish physical room-scan availability or exact headset
alignment. The accepted old P2 binary remains a rollback. This redesign needs
focused new-feature observation, not repeated testing of the old accepted menu.

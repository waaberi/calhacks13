# Settings, manual planes and physical scale

This follow-up starts from the physically accepted P2 room-origin correction.
The common mapping remains `CurrentAppWorld * OriginToApp * SceneAnchor`, with
the relative origin recomputed each LateUpdate. Startup worn/focused/tracked
readiness and unique current-room polygon containment remain required. Hiding
geometry does not bypass those checks or stop saved-scene queries.

The bottom-right gear opens Settings. Room geometry starts hidden; **Show room
geometry** toggles its visualization. Automatic surfaces and Surface help are
separate controls. Environment setup loads saved room data or explains the
on-headset system setup route.

**Add horizontal plane** and **Add vertical plane** create separate, visibly
numbered manual planes. Horizontal planes stay level; vertical planes stay upright.
Grip/aim moves their position, sticks deliberately rotate/change distance and
two hands resize/rotate subject to the orientation constraint. A detected desk,
floor or wall can seed a plane, but ordinary grabs never attach it back to that
detected pose. **Manage planes** provides per-plane **Align** and **Delete**, with
pagination when needed. Align is a deliberate one-time projection onto a matching
nearby finite detected surface; subsequent movement remains independent. If no
matching surface is nearby, the menu says so.

A correction's source UUID only suppresses that detected functional surface.
Deleting the correction restores the original source when no other correction
still overrides it. Neither operation changes Meta's saved scan. An unseeded
manual plane has no detected-source override. Plane numbers remain stable until
deleted; labels, backing and handles remain visible independently of room-mesh
visualization. Manual planes are session calibration, not an automatic scan.

The earlier continuing 30cm auto-attachment and per-grab stick-click bypass are
superseded for manual planes. Ordinary model contact retains the accepted gentle
surface assistance and explicit alignment behavior.

Controller graphics use a neutral grip marker at the actual grip origin rather
than a falsely fitted capsule. Pointing requires tracked grip and aim poses from
the same Input System device. Missing aim cannot substitute the grip orientation.
Device replacement releases old holds, clears stale two-hand ownership and rebases
the surviving hand. The accepted stabilized aim-based displacement, tracking-origin
conversion and orientation-preserving one-hand object holds are unchanged.

Physical size uses the selective PR154 correction: default/new-document/reset
scale is 1:1. Inspection magnification is explicitly labelled; **Actual size**
restores metre scale without moving the workspace. Same-document reconnect
preserves chosen magnification. See [PHYSICAL_SCALE.md](PHYSICAL_SCALE.md).

## Different-room demo setup

At the venue, leave Link and open the installed Room Setup companion. Load the
venue's saved scene first. Use Meta's on-headset Space Setup only when no suitable
scene exists or the user chooses to update it, then reload and inspect the fit.
Close the companion, reconnect wired Link, and Load saved room in Environment
setup. PC spatial-data sharing must remain enabled. Briefly inspect room geometry,
then hide it for work; independent planes can correct local functional surfaces.

Saved semantic labels describe meaning; planes/polygons/boxes describe usable
surfaces and approximate furniture bounds; the reconstruction mesh contains more
detailed triangles. Visualization is an app choice. Scene receipt is not current
room membership or physical fit. The original-room physical pass does not certify
an unvisited venue. Never erase a scan or invent a global rotation to repair it.

## Software verification

P2Checks.Windows runs PhysicalScaleChecks, IndependentPlaneChecks and
SettingsMenuChecks plus the cumulative P2/arrangement/P1 gates. P1 includes
ControllerPoseChecks for both concrete OpenXR/Input System pose formats, missing
aim, mixed devices, replacement/recovery and actual two-hand source-switch cleanup.
Menu checks invoke real colliders/callbacks, including page rebuilds and deletion.
Optional settings previews are rendered through an actual camera for visual QA.

The private native-AppSpace and actual-room captures replay the accepted origin
composition with omission/inverse/double negative controls. Capture/launcher
regressions protect pixel freshness and selected-window identity. Software passes
do not replace final physical controller alignment, independent correction and
known-dimension/ruler confirmation in the integrated build.

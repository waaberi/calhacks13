# Meta environment setup

The previous compiled `1713a38` green-grid candidate **failed physical room fit**.
It reduced semantic bounds to rectangles. Matching those rectangles against the
same SDK data did not verify physical alignment. That failure remains authoritative.

## Supported route

Meta Space Setup is a system-owned, on-headset experience. Windows Quest Link can
load the saved scene, but cannot run Space Setup. The PC Blender application stays
on Windows. A separate **Room Setup** APK loads the existing room through MRUK and
offers Meta's `OVRScene.RequestSpaceSetup()` when the user chooses scan/update.
After finishing, return to Link and load the saved room in the PC application.
No room JSON or guessed coordinates are transferred between two tracking origins.

The companion uses the official MRUK207 camera rig, world locking and EffectMesh.
It starts with saved-room loading, without forcing another capture. A loads saved
data, X opens the actual system capture/setup, and Y finishes the companion. A
successful return from RequestSpaceSetup also happens on cancellation: it triggers
a reload, never a claim that a new scan completed. Spatial-data permission denial,
missing data and a received scene are distinct outcomes. No simulated room fallback
is configured.

In the PC menu, **Environment setup** offers Load saved room, the on-device handoff,
room geometry visibility, and existing visible surface corrections. Accepted
arrangement, controller input and Blender capture remain on their original paths.
The PC app must not call a desktop capture API and pretend that it scanned the room.

## Geometry and placement

The PC retains its accepted XR camera rig. The Core SDK's scene anchor pose and
`OVRBounded2D.TryGetBoundaryPoints` provide actual polygon outlines, including concave
floor boundaries. Those vertices go through the common tracking-origin conversion
once. Polygon-aware containment and nearest-edge placement replace bounding-box
containment where a boundary exists. Table functional planes are preferred when
horizontal; volume-derived support planes remain explicitly semantic approximations.

`OVRTriangleMesh` anchors are queried separately from RoomLayout/AnchorContainer:
the room container is not a guarantee that it contains the reconstruction mesh.
`TryGetMesh` already converts scene handedness and winding. The renderer preserves
its vertices and triangle order and follows the localized mesh anchor. Unsupported
mesh queries cannot discard otherwise valid room planes. Unlocalized meshes and
meshes from an unidentified room in a multi-room result are hidden.

Detected visualization renders supplied polygons and reconstruction triangles.
There is **no rectangular scan-outline fallback**. If detailed geometry is not
received, the app reports its actual polygon/mesh counts. Semantic bounds can still
support contact; they do not become an invented room reconstruction. The companion
also distinguishes a reconstruction mesh from semantic planes/bounds and renders a
translucent view so the actual room stays visible for comparison.

Visible amber levels remain optional per-anchor corrections or clearly labelled
manual levels. They do not constitute automatic scanning. Existing gravity-level
constraints, source hysteresis, grip-pose rebase, deliberate alignment, free placement
and gentle ordinary-object contact remain. No guessed global tracking rotation or
native Blender coordinate change repairs localization.

## Verification and acceptance

Automated checks cover concave boundaries, nearest edges, translated/rotated origins,
mesh vertex/winding preservation, invalid mesh indices and supported platform handoff.
The existing cumulative P1/P2/arrangement and capture/launcher checks remain required.
Recorded-room replays establish data consistency only. Old captures contain no
boundary vertices or reconstruction mesh and cannot validate the new detailed shape.

The independent reference is Meta's system setup plus the separate on-device MRUK
renderer. Observe that geometry against the actual room before comparing the PC
rendering of the same saved scene. If the companion fits but PC does not, investigate
the PC loading/localization/conversion path. If system setup and MRUK disagree,
investigate that separate localization path. Do not blame a scan or repeatedly ask
for rescans to conceal an application error. Use system update/setup only as the
user-directed supported flow when needed.

Data receipt, geometry rendering and physical fit are separate gates. No new physical
acceptance is implied by software tests. The original entire P2 menu is already
accepted; do not ask for another menu exercise. Keep room geometry private/local.
No FPS work, P2.5/other-phase implementation or main merge is included.

## Official references

- [Scene model and on-device Space Setup](https://developers.meta.com/vr/documentation/unity/unity-scene-build-mixed-reality/)
- [MRUK scene management](https://developers.meta.com/vr/documentation/unity/unity-mr-utility-kit-manage-scene-data/)
- [MRUK samples and EffectMesh](https://developers.meta.com/vr/documentation/unity/unity-mr-utility-kit-samples/)
- [Scene mesh and MRUK migration](https://developers.meta.com/vr/documentation/unity/unity-scene-migrate-mruk/)
- [Official Spatial SDK MRUK capture/reload reference](https://github.com/meta-quest/Meta-Spatial-SDK-Samples/blob/main/MrukSample/app/src/main/java/com/meta/spatial/samples/mruksample/anchor_mesh/MrukAnchorMeshSampleActivity.kt)

SDK207 explicitly disables the archived HiFi V2 model and falls back to V1. This
implementation does not promise that archived API. Quest3S supports the ordinary
scene reconstruction mesh, but actual runtime availability must be read back.

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

## Build and install the separate companion

Use `app/build_room_setup.py quest --editor <Unity-with-Android-support>
--output <new-outside-worktree-path>/RoomSetup.apk --log <outside-worktree-log>`.
The wrapper restores the tracked PC settings after the serialized build and rejects
a reused artifact path. A successful build must report zero errors. Keep generated
Unity/Android outputs outside the OneDrive source workspace.

`app/install_room_setup.ps1 -Adb <adb.exe> -Apk <RoomSetup.apk> -Launch` installs
only after ADB reports an authorized device and resolves the actual Android launch
activity. It does not uninstall an existing app on a signature mismatch. Leave Link
and run the companion on the headset; this does not replace the Windows Blender app.

Meta requires headset Developer Mode for this local APK deployment. Its current
supported setup path is the **Meta Horizon phone app → headset icon → paired Quest
→ Headset Settings → Developer Mode**. The developer account/team prerequisites
are described in Meta's device-setup guide. A USB file-access or Link prompt is
different from **Allow USB debugging**; accept the debugging prompt on the headset.

In this session, USB PID5010 exposed healthy Link interfaces but no ADB interface.
The installed, signed Meta driver already supported the correct ADB hardware ID;
restarting ADB did not repair detection. Enabling Developer Mode changed the USB
configuration to PID5013 and exposed the signed ADB interface immediately. ADB then
reported `unauthorized`, correctly requiring the headset's debugging confirmation.
This was a headset development prerequisite, not evidence of a Windows firewall or
driver failure, nor evidence about saved-room availability. Do not force a Link
interface onto an ADB driver or weaken firewall/security settings for this symptom.

The first Android build compiled the scene checks, C# and ARM64 libraries, then
failed on five Google/Maven artifact download timeouts. The exact official JARs
and POMs were downloaded in bounded HTTPS ranges and checked against publisher
SHA1 values; every complete JAR also passed ZIP CRC checks. A local Maven
repository supplied those five modules, and the same `:launcher:assembleRelease`
target used by Unity passed offline (119 tasks, exit 0). Copying artifact files
into Gradle's cache alone did not create its metadata, so that initial recovery
attempt failed. An interim root aggregate target also attempted an unnecessary
standalone Unity-library AAR whose app icon/name belong to the launcher; the
launcher target is the correct APK target. All failed logs are retained.

Verified companion APK SHA256:
`3d15562b08201cc755f54d7b4823792cc423b210e97479dc799dc2b09662c6a4`.
APK signature verification passed, package `com.calhacks13.roomsetup`, ARM64,
min SDK29 / target36, with scene and anchor permissions. This establishes a
built APK, not successful installation, room-data access or physical fit.

## Official references

- [Scene model and on-device Space Setup](https://developers.meta.com/vr/documentation/unity/unity-scene-build-mixed-reality/)
- [MRUK scene management](https://developers.meta.com/vr/documentation/unity/unity-mr-utility-kit-manage-scene-data/)
- [MRUK samples and EffectMesh](https://developers.meta.com/vr/documentation/unity/unity-mr-utility-kit-samples/)
- [Scene mesh and MRUK migration](https://developers.meta.com/vr/documentation/unity/unity-scene-migrate-mruk/)
- [Official Spatial SDK MRUK capture/reload reference](https://github.com/meta-quest/Meta-Spatial-SDK-Samples/blob/main/MrukSample/app/src/main/java/com/meta/spatial/samples/mruksample/anchor_mesh/MrukAnchorMeshSampleActivity.kt)
- [Developer Mode, Windows drivers and USB debugging setup](https://developers.meta.com/vr/documentation/native/android/mobile-device-setup/)
- [Official ADB connection troubleshooting](https://developers.meta.com/vr/documentation/native/android/ts-adb/)

SDK207 explicitly disables the archived HiFi V2 model and falls back to V1. This
implementation does not promise that archived API. Quest3S supports the ordinary
scene reconstruction mesh, but actual runtime availability must be read back.

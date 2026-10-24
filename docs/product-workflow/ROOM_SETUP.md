# Meta environment setup

The previous compiled `1713a38` green-grid candidate **failed physical room fit**.
It reduced semantic bounds to rectangles. Matching those rectangles against the
same SDK data did not verify physical alignment. That failure remains authoritative.

On returning to the original room, the independent on-device companion loaded the
actual reconstruction mesh and the user confirmed **aligned and stable**. The PC
`376f0f9` candidate then received ten polygons and one mesh, but **physically failed**:
the user reported geometry behind them, and a private captured view shows incorrect
registration. The failed PC Player was closed normally. Matching all eleven anchor
UUIDs requires accounting for native-log versus managed Guid byte order; after that
normalization both apps read the same saved anchors. This excludes a different saved
anchor set as the explanation, but does not yet diagnose the PC transform failure.

The later `fdbb1d6` camera-mapping candidate also **failed physical alignment**.
Its live official-SDK versus parent mapping differed by only0.331degrees and
9.26mm. That cannot explain the reported large room rotation. It is not a fix.

The optional MRUK reference-rig diagnostic on `e58039f` crashed before exporting
comparisons: repeated AppSpaceChange events exhausted native reference spaces
(`xrCreateReferenceSpace: XR_ERROR_LIMIT_REACHED`). It has been removed; the exact
cause of that churn is not established. Logs and the failed artifact are retained.

An opt-in `CALHACKS_ROOM_SPACE_PROBE` export compares each existing anchor through
direct `xrLocateSpace` in Unity's actual AppSpace against Core's native
Floor/Eye/Stage-origin wrapper. It creates no reference spaces and changes no
tracking state. The mesh API uses the OpenXR shim while Core's locatable wrapper
uses the native origin-based path; equality of head poses alone does not prove
that these paths locate scene anchors in the same reference space.

The live three-sample probe **confirmed the missing origin conversion**. All11
anchors' native Floor poses differed substantially from direct localization in
Unity's current AppSpace. The SDK's `GetTrackingTransformRelativePose(FloorLevel)`
premultiplied with those scene poses matches the independent direct poses across
all33 observations within0.253mm. Mesh handedness and head/camera poses were already
correct. This is a common reference-space mismatch, not a bad scan or a mesh-only
180degree rotation.

The repair uses `WorldAnchor = CurrentAppWorld * OriginToApp * SceneAnchor` for
both mesh and semantic surfaces. `CurrentAppWorld` is the accepted TrackedPoseDriver's
camera-parent frame, shared with head/controllers; `OriginToApp` is the public
SDK relative-origin getter, converted with ordinary `ToOVRPose()` and recomputed
each LateUpdate. It is neither inverted nor given another scene Y180 conversion.
The unnecessary asynchronous SDK camera/head subtraction from `fdbb1d6` is removed.
Camera, controls, mesh vertices and saved scan remain on their accepted paths.

`RoomSpaceReplayChecks` runs the production composition against all33 independent
native observations in both captured and rotated/translated world frames, including
UUID-matched actual boundary points. Omitted, inverted and doubled corrections must
all fail. Raw room captures remain local. Physical acceptance of the corrected
binary is still required; identifying and replaying the cause does not grant it.

## Current-room eligibility and demo relocation

A successful query is scene receipt, not proof the wearer is in that room. The
former singleton-room bypass could display a saved mesh while the headset was
outside its actual floor polygon. Automatic room rendering and contact now require
fresh tracked floor geometry, a worn/focused/tracked headset, a unique containing
room, and plausible floor-relative head height. Missing, stale, ambiguous or
outside-room data disables automatic room geometry/contact. Actual Boundary2D is
required; a rectangle is not a localization fallback. Unknown mesh ownership is
accepted only for a single mesh and a unique known room that independently passes
the same containment gate. These checks prevent stale-room use; they cannot prove
physical fit when the common anchor reference itself is wrong.

For a different demo venue, load that venue's existing scene on the headset first.
If no scene fits there, the user can choose Meta Space Setup on the headset, then
reload and inspect its fit before returning to Link for fresh localization. Do
not automatically erase or recapture a working scene. Meta warns that loaded
scenes may be distant or on another floor and recommends floor-polygon containment.
MRUK's `GetCurrentRoom()` can fall back to the previous/first room, so it alone
cannot establish current-room membership. See [Meta scene best practices](https://developers.meta.com/vr/documentation/native/scene-best-practices/)
and [MRUK scene loading](https://developers.meta.com/vr/documentation/unity/unity-mr-utility-kit-manage-scene-data/).

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

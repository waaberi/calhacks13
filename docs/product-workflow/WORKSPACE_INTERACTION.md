# Current status: smooth dragging, front startup and restored live clarity accepted

Talia confirmed screen/model aim-based dragging in v18, then "Yes, in front and smooth" for v19 startup and both controllers. V19's live-feed/clarity regression failed and was repaired separately in v20; Talia then confirmed "Yes, live and clear again". V20 keeps the accepted movement and startup code. The actual Unity XR Transform Stabilizer filters the ray before calculating held placement; the failed v17 center-rotation-only interaction must not return. See [DRAG_MOVEMENT_REGRESSION.md](DRAG_MOVEMENT_REGRESSION.md) for causes, rejected approaches, real implementation tests and capture/render guards. These subchecks do not pass the full phase. Feature-branch publication is authorized; main integration and native model editing remain separate.

# VR workspace arrangement

Talia requested these controls before continuing P1 testing. Source branch: [`codex/talia-p1-usb-screen`](https://github.com/waaberi/calhacks13/tree/codex/talia-p1-usb-screen). Publishing this branch does not merge it into main.

## Two separate modes

**Arrange view (implemented candidate):** move the live screen and arrange the whole build or one part in your environment. These placements belong to the VR viewer. They never send a native edit, change Blender dimensions or add to Blender Undo history.

**Edit model (later):** deliberate operations that move/edit actual Blender objects through the host command path, including permission checks, Apply/Cancel, conflict handling and Undo/Redo. Arrangement must never silently switch into this mode. This work does not implement or accept that later mode.

## Controllers

- Both tracked Touch controllers have a visible grip marker and aim ray. Green rays indicate a target.
- Point and squeeze **grip** to pick up the screen or model. Change controller aim to move it through space; release grip to place. Initial pickup preserves position without snapping.
- While holding the screen, use the stick vertically for distance and horizontally for size.
- Point at a button and press that controller's **trigger** to select it.
- **Arrange: whole build / one part** changes the model pickup target. Whole-build movement preserves part spacing. Per-part arrangement preserves the live native pose separately and adds only a local view offset.
- **Reset view** clears local per-part arrangements and recenters the whole build and screen. **B/Y** recenters without clearing per-part arrangements.
- **A/X** shows/hides the Blender screen. **Right stick click** cycles image magnification; tilt pans while magnified and not holding an item.
- Tracking loss releases a held item in place. Release controls before pickup resumes. Two hands cannot grab the same object or its parent/child simultaneously.

The image is still view-only: pointing at Blender pixels does not send desktop mouse clicks.

## Room / keyboard visibility

The app needs an actual passthrough compositor layer; removing the skybox alone is insufficient. The candidate uses pinned Meta XR Core SDK207.0.1 from Meta's official package registry, the Meta XR OpenXR feature, OVRManager and an OVRPassthroughLayer underlay. Its **Room view** button controls app passthrough when supported. The camera becomes transparent only after the passthrough layer initializes. Unsupported/failed initialization preserves the opaque scene with an honest unavailable status. The app does not read or record raw room-camera frames.

The earlier missing-extension/setup blocker is resolved: Talia completed developer account/team setup and enabled passthrough consent; Link exposes XR_FB_passthrough. Combined-v2 room visibility and both controllers physically passed. The accepted alpha fix is integrated: framebuffer alpha, URP alpha variants and a room-view camera buffer that retains alpha. V20 preserves it. Room-toggle/reconnect/soak and separate keyboard-readability acceptance are not established by the later movement/video answers. The [setup and rendering notes](PASSTHROUGH_SETUP.md) and [#124](https://github.com/waaberi/calhacks13/issues/124) retain evidence.

## Verification

The build runs real Unity far-ray intent/jitter tests at72/90/120Hz; both concrete controller pose formats and grip/Pointer binding checks; pickup/depth/origin, rigid assembly, native-view separation/reset, startup-facing and actual-pixel freshness tests. RenderScale1/MSAA4/alpha preservation are required gates. V20 Windows build has zero errors;11capture tests, smoke and controlled live-pixel checks pass. Physical movement/startup and restored live clarity are user-confirmed as above. Sustained40fps, wireless, later native editing and the complete P1/P2 gate are not independently passed here.

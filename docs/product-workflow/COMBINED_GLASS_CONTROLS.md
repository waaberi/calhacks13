# Combined glass controls follow-up

The handheld menu starts about 19.4 cm wide at standard text size, with a gentle
curve shared by its labels and pointer targets. Grip and aim to move it; while
held it faces the wearer. Release leaves it stationary. Return to left hand
restores the larger docked size. Display/menu changes never edit Blender data.

**Surface detection: ON/OFF** is on the handheld Arrange page. It controls the
existing surface placement assistance. Settings retains automatic room loading,
detected geometry and independent plane controls. The successfully loaded new
room scan is preserved; its physical fit still requires the wearer's observation.

**Settings > Blender view: opaque / transparent** changes the captured Blender
view and its surrounding buttons together. The saved preference starts opaque.
It does not change handheld-menu transparency or room passthrough.

**Edit model** opens real Blender input and a three-page guide. Its checkmark
reflects the active editing workflow. **Arrange space** ends that input safely.
See [Editing Blender from VR](BLENDER_EDITING_IN_VR.md) for native menu, mesh,
keyboard, controller and drawing steps. Input ON is the local user's own Blender
input method. A voice edit switches out of native input automatically after
cleanup; it must not be presented as a separate person working on the computer.
Protection against an actual foreign writer or an unfinished native modal remains.

## Seeing a real laptop keyboard

The real keyboard window uses the existing room passthrough. It is a manually
aligned opening, not automatic laptop recognition or keyboard tracking. It reads
no room-camera buffers and does not change the saved room scan or native model.

1. With room passthrough available and the headset worn/focused, the window starts
   below the workspace. It waits for settled placement and fresh tracking.
2. Grip its cyan handle and aim to align the opening over the real keyboard.
   Stick up/down changes distance. Two grips can rotate and resize it. Release
   leaves it in place. The clear opening itself does not steal native mouse input.
3. **Settings > Physical keyboard** turns it off/on or places it again. An origin
   reset hides it until explicitly placed again; headset readiness loss hides it.
4. Keep Windows keyboard focus on the captured Blender window when typing into
   Blender. The window reveals the real keys; it does not redirect physical keys.

No fake camera image or guessed automatic keyboard pose is displayed if room
passthrough is unavailable. Real keyboard legibility, physical placement, room
alignment and the latest controller visuals remain hardware confirmation gates.

## Verification

The cumulative Windows build includes real curved button dispatch, menu scale and
docking, scoped opaque shader/captured-pixel checks, an actual GPU alpha punch
through opaque foreground geometry, and native edit release/owner-state handoff
checks. Existing aim/stabilizer, controller formats, depth, startup, room replay,
capture freshness and XR render settings remain protected. These software checks
do not establish physical acceptance, two-PC operation or a full phase pass.

No PR changes, main merges or FPS work are part of this follow-up.

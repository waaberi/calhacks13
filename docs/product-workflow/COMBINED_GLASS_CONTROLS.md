# Combined glass controls follow-up

The handheld menu starts about 19.4 cm wide at standard text size, with a gentle
curve shared by its labels and pointer targets. Grip and aim to move it; while
held it faces the wearer. Release leaves it stationary. Return to left hand
restores the larger docked size. Display/menu changes never edit Blender data.

**Surface detection: ON/OFF** is on the handheld main page. It controls the
existing surface placement assistance. Settings retains automatic room loading,
detected geometry and independent plane controls. The successfully loaded new
room scan is preserved; its physical fit still requires the wearer's observation.

**Settings > Blender view: opaque / transparent** changes the captured Blender
view and its surrounding buttons together. The saved preference starts opaque.
It does not change handheld-menu transparency or room passthrough.

**Edit model** opens real Blender input and a three-page guide. Its checkmark
reflects the active editing workflow. **Arrange space** beside the Blender view
ends that input safely. The handheld menu omits the Arrange-space heading and
Actual-size action/status requested for removal.
See [Editing Blender from VR](BLENDER_EDITING_IN_VR.md) for native menu, mesh,
keyboard, controller and drawing steps. Input ON is the local user's own Blender
input method. A voice edit switches out of native input automatically after
cleanup; it must not be presented as a separate person working on the computer.
Protection against an actual foreign writer or an unfinished native modal remains.

## Typing

**Keyboard** and **Full keyboard** provide the existing VR keys and modifiers for
Blender's captured editors. A physical keyboard types into the captured Blender
window when that window has desktop focus. The manual physical-keyboard window,
outline, handle and Settings controls have been removed. Room passthrough remains
available through the existing room-view controls.

## Scaling on a surface

Native Scale shows its acknowledged multiplier while held (for example ×0.50 or
×2.00), including X/Y/Z when constrained. Two-hand arrangement resizing shows a
separate Display scale ratio. Move has red/green/blue native-axis arrows on the
floating selection; trigger-drag an arrow, release to commit, or grip/Escape to
cancel. Existing free Move, Rotate rings and Blender-view editing remain.

With Surface detection enabled, scaling an object already resting on a current
finite plane preserves its contact point. A desk-seated cylinder grows upward
from its base and remains seated when reduced. Direct Object Scale updates
Blender live and retains native Cancel/Undo/Redo. Two-hand arrangement scaling
keeps the contact while orientation is unchanged; deliberate rotation and free
placement retain the existing controls. Floating objects keep their normal pivot.

## Verification

The cumulative Windows build includes real curved button dispatch, menu scale and
docking, scoped opaque shader/captured-pixel checks, and native edit release/owner-state handoff
checks. Existing aim/stabilizer, controller formats, depth, startup, room replay,
capture freshness and XR render settings remain protected. These software checks
do not establish physical acceptance, two-PC operation or a full phase pass.

No PR changes, main merges or FPS work are part of this follow-up.

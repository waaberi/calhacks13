# P2.5 common modeling and preview controls

This expansion follows the user's selected priority: common modeling and preview
controls, tested headlessly on the P2.5 feature branch. There is no measured
percentage of Blender covered. Implementation, native operation results, keyboard
delivery and physical acceptance are separate evidence categories.

## New controls

**Model tools** now includes Exact move, Set position, Set rotation, Scale factors,
Set scale, Cube dimensions, Sphere dimensions and Cylinder dimensions. Choose an
axis, enter a decimal with the VR keypad and press Apply numbers. Opening or
editing the keypad changes only a local draft. Apply uses the existing native
permission, explicit-target, receipt and history path.

Move and position use millimeters along Blender world XYZ. Rotation uses native
Euler XYZ degrees, converted to native WXYZ quaternion order. Absolute position,
rotation and scale load the target's current native values, so editing one axis
preserves the other displayed axes. Euler values are one equivalent orientation;
near gimbal lock they need not match Blender's displayed Euler decomposition.
Custom primitive dimensions use XYZ bounding dimensions and create at the native
world origin; Set position can place the result afterward. Native scene units
and Unity inspection magnification do not change the entered physical values.

Coordinates accept -1,000,000 to 1,000,000 mm, dimensions 0.001 to 1,000,000 mm,
positive scale factors 0.001 to 1000, and angles -360,000 to 360,000 degrees. The
keypad uses invariant decimals, without exponent or comma input. Missing current
transform metadata blocks absolute-value loading. Identity, document, revision,
target or generation changes invalidate the draft until Reload numbers. Applying
also consumes its values; wait for the receipt and reload before another edit.

**Preview tools** adds two pages of 31 shortcuts: selection all/none/invert,
duplicate, Edit Mode, move/rotate/scale, extrude/inset/bevel/loop cut/merge,
hide/show, frame selected/all, six standard views, perspective, camera, local
view, shading, toolbar/sidebar, and confirm/cancel. First left-click the intended
Blender editor in the captured image. Editor-sensitive shortcuts move the native
pointer back to that point. This binds the chosen captured window and point; it
does not programmatically identify the Blender area type. Mesh operations require
fresh native mesh Edit Mode. Modal operations continue in Blender; use Enter or
Escape to finish before switching tools.

Shortcuts are admitted as complete batches. Locally held mouse/modifiers are
released before the chord and owned modifiers restored afterward. A stale capture,
changed native identity or overflowing input queue refuses the operation and
requires recovery rather than sending a partial chord.

**Full keyboard** adds F1–F12, numpad 0–9, decimal, divide, multiply, add, subtract,
Escape and Insert. Letters returns to the existing text keyboard. The overlays
absorb gaps and preserve nearer UI, grip/other-hand routing and desktop shortcut
ownership. They do not add OS text fields that could steal keyboard input.

## Concrete coverage checklist

| Workflow | Implemented route | Headless evidence | Remaining runtime check |
| --- | --- | --- | --- |
| Exact transforms and primitive dimensions | Eight actual keypad/open/apply callbacks and existing typed native commands | Current-value preload, independent quaternion/coordinate oracles, stale-draft refusals; actual native results at unit scales 1 and .001 | Controller usability and integrated native result |
| Common modeling | Selection, duplicate, mode, transform, mesh and hide/show shortcut buttons | All 31 callback/chord payloads; installed Blender 5.2 default keymap; actual background mesh operations | Actual key delivery in the clicked editor, modal mouse completion |
| View navigation | Frame all/selected, six axes, perspective, camera and local view shortcuts | Native view-axis directions, framing, perspective and local-view state; keymap binding | Actual native event delivery and camera context |
| Toolbar/sidebar | Native T/N shortcuts | Exact callbacks/chords/default keymap plus eight actual native hide/show/restore transitions; private headless fixture disables animation and restores its preference | Actual injected-key delivery and visible animated UI behavior |
| Extended keyboard | 29 additional keys plus existing letter page | Actual callbacks, helper validation/serialization and input lifecycle checks | Physical typing and native delivery |
| Whole captured Blender interface | Existing pointer, scroll, drag and keyboard route | Geometry/session/transport/occlusion regressions | Tabs, menus, fields, panels and auxiliary windows in actual native UI |
| Direct VR drawing | Existing line/circle/rectangle native sketch adapter | Preserved native solver/history/save-reopen and cumulative gates | Coordinated controller/headset trial after P2 is ready |

The [native modeling and navigation report](P2_5_NUMERIC_MODELING_NATIVE.md) records
methods, assertions and background limitations. The [verification report](P2_5_RESULTS.md)
records exact candidate provenance and cumulative gates. Sending a chord, matching
a keymap or calling a native operator is not proof of native GUI delivery.

Arbitrary Blender tools do not gain direct spatial gestures from this expansion.
The existing unsupported CAD options, unsupported mirror entities and non-GHOST
Windows dialogs remain bounded as described in the [interaction guide](P2_5_PREVIEW_INTERACTION.md).
P2's active runtime, later placement changes and physical acceptance remain with
their owners. No main merge or FPS work is authorized.

# Cumulative P3A software checkpoint

This branch contains tested P2 `4ad4247f754f2d8a2aa6699915fab92b3e221b15`,
which contains published P1 `3c1bdad`. P2's native/Unity source is unchanged
from its earlier tested `38f34ade` checkpoint; the later P1 propagation changes
only the separately tested capture helper/tests/docs. This branch adds P3A native
editing, the controlled Blender Client operation and their integration checks.
Sketch stays disabled until a real P3C host advertises its adapter.

## Interaction and native authority

The native menu creates cubes, spheres and cylinders; selects a named target;
and drafts numeric move, rotation, scale, delete, history and Save operations.
Lengths are entered in millimeters, angles in degrees and scale as factors.
Apply requests permission before sending one typed native transaction. Cancel
before send changes no native geometry. The original document revision and
target generation remain attached to the draft; stale edits are refused rather
than silently retargeted. Only the matching native receipt establishes success.
An unknown result disables editing until a fresh authoritative snapshot arrives;
the command is not automatically repeated. Bounded receipt exhaustion fails
closed, including for VR Save; recovery uses File > Save in host Blender before
restarting the hosting session.

Primary hand is right by default, persists between sessions and can switch to
left. Pointer, screen/magnify/pan/recenter shortcuts and the other menu hand
switch together. The menu supports held and pinned modes. Grip still arranges
the local screen/model view and does not edit Blender.

Initial Place Table, moving and tracking-reset confirmation retain priority.
Once placed, native editing and table inspection controls appear one at a time.
Arrange View restores the table controls; the other stick click or desktop F3
returns to native editing. Hidden table controls cannot intercept the ray.
Visibility changes leave table position, scale and native state unchanged.
Inspection controls have an opaque backing ordered above the live-screen UI.
Rejected scene admission immediately shows an orange stale-scene warning even
before the socket closes; unknown native outcomes retain their separate warning.

## Exact Windows/native evidence

Compiled source: `0056266e0460cef4e075c97448dbc877d736c7bb`.
Build output folder: `p3a-native-menu-final`, executable `SpatialModeling.exe`.
Runtime Assembly-CSharp SHA256:
`e1789149ea0b5d67beb3d8655695e57fceca201a6093c581580c981189f015f8`.
The Unity EXE launcher stub is shared across builds; it is not sufficient to
identify the application assembly.

The actual Windows build passed with zero errors and ran cumulative P2 checks,
native-state, persistent-hand and panel-transition checks, plus the real P1
72/90/120 Hz aim-displacement, both controller pose formats, no-snap/release,
startup/native-view/freshness and renderScale1/MSAA4/alpha guards. No capture
quality or accepted grip/aim mapping was reduced.

The actual Player connected to an isolated real Blender 5.2.2 host. Production
menu callbacks/fields, leases, typed commands and matching receipts completed:
cube/sphere/cylinder creation, Cancel, native 10 mm X move, native 90 degree Z
rotation, scale, stale-target rejection, delete, Undo/Redo, restoration and Save.
Independent native before/after records confirm the movement and rotation.
The actual Arrange/menu-return/reset/fresh-pose/Place callbacks leave native
revision unchanged. Actual production-camera images show the real models and
readable controls in both modes. These are software renders, not XR eye-buffer
or physical readability evidence. Intentional invalid smoke configuration exits
3; the successful Player and owned Blender both exit normally with code 0.

Coordinator verification on the cumulative backend: **855 passed, 38 skipped**.
Optional bpy, real-Blender, OpenSSL/Spacetime CLI checks remain recorded skips.
Separate explicit actual-Blender tests then passed both meter and millimeter
unit scales, including native transactions, receipt/replay safety, history,
Save/fresh reopen and schema validation. The real registered production Client
operator passed at both scales using the actual P2 preferences, TLS transport,
state cache and mirror: flag-off refuses, flag-on applies one leased native
10 mm move, Cancel/disconnect sends no second mutation, and reconnect retains
one accepted move. Two local processes do not establish a real second-PC pass.

The exact final binary passed the separate P1/P2 receiver/live-video/normal-close/
relaunch gate: native 10 mm movement, sphere add/delete, unchanged Undo history,
explicit stale connection loss and fresh reconnect, followed by 251 viewport
changes in 252 samples, zero unavailable samples, maximum pixel age143ms and
full2560x1600/JPEG95/4:4:4. Normal window close exited0; relaunch of the same
binary passed ten toggles, magnification and fresh pixels, then exited0. Its
baseline inspection traffic remained hello/ping only. Observed peak texture
rate32.0fps did not satisfy sustained40fps. Earlier c15f7ba evidence and failed/
interrupted attempts remain preserved. The capture window and native command
host in these runs are separate explicitly selected isolated Blenders.
The final runtime uses promoted helper08fdb59 (published P1 head3c1bdad),
SHA256 `a46c15b31039dd375226525c66622a07ed83717da43bdd0f418be34407262c09`.
All22 capture/launcher tests passed again on the cumulative P2 successor.
Exact full-quality helper reliability passed300steady seconds after5s warmup,
with no steady unavailable/error/worker exceptions. Publication37.153fps,
2second bins30–43, still fails minimum40; it is not displayed/compositor FPS.

## Preserved failures and remaining acceptance

The original A smoke host incorrectly passed a C-only Session capability
argument; its startup TypeError is preserved and the A-only harness now omits
that argument. The next Player completed native edits but hidden-window
ScreenCapture produced no PNG. An opt-in actual URP camera render repaired the
evidence path without changing production graphics. Its first real image then
exposed native/table control overlap; the product handoff above corrects it.
A later reset smoke asserted controls before supplying a new tracked pose;
its failure is retained and the test now explicitly supplies a bounded software
pose before the real Place callback. Production tracking guards were retained.
Canonical findings and repair are on
[#53](https://github.com/waaberi/calhacks13/issues/53#issuecomment-6383578735)
and [#60](https://github.com/waaberi/calhacks13/issues/60#issuecomment-6383676827).

Headset startup/controllers/held-pinned usability, binocular clarity, keyboard
comfort, room passthrough, active-XR shutdown and sustained displayed rate remain
pending on this exact replacement. Earlier background screen/footer clutter in
the desktop inspection image is retained as a layout observation and led to the
opaque backing/ordering correction; physical comfort is not inferred. Human/team review, actual
second-PC/network acceptance and full phase acceptance are not established.
No phase-passing tag, main push or merge was performed. The physically accepted
`p1-capture-recovery-v20` artifact remains the rollback.

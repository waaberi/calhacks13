# Using the Blender preview as the menu

- **Focus Blender** requests an exclusive native UI reservation for the connected
  VR user. The helper verifies the selected window belongs to that Blender host.
- **Point anywhere in the preview.** The controller ray maps the displayed image,
  including magnification/crop, to the window's actual pixels and DPI. Blender
  handles its own tabs, menus, toolbar, sidebar, Properties, Outliner and editors.
  Each native button does not need a separate custom mapping.
- **Trigger clicks and drags.** Hold trigger to hold the selected left/right/middle
  mouse button; release to finish. The stick scrolls while pointing into the
  image. Grip retains workspace arrangement behavior.
- **Type and use shortcuts.** The VR keyboard supplies text, modifiers, navigation,
  function and numpad keys. Copy/Paste buttons send ordinary Ctrl+C/Ctrl+V to the
  focused native field/editor. Blender supplies its normal context-dependent
  behavior, tool options, Undo/Redo and dialogs.
- **Dialogs follow automatically.** A new active Blender-owned window replaces
  the image, including native Windows dialogs and menus with a verified ownership
  chain. Closing a nested dialog returns to its parent, then the main window.
  Popups drawn inside Blender's existing window remain part of that image.
- **Choose a window when needed.** Windows / dialogs lists six verified windows
  per page. Choose its title, or Back to Blender. Recovery controls remain visible
  when no fresh image is available. Choosing a window explicitly requests focus.
- **Window changes start a fresh gesture.** Queued clicks/text are discarded,
  held input is released, and input waits for matching new pixels plus an exact
  release acknowledgement. Release trigger before clicking again.
- **Draw in VR** finishes native UI input cleanup and switches to the existing
  native sketch path. Line, rectangle and circle drafts go through Blender's CAD
  solver/history. Finish or cancel a running native modal before switching modes.

## Window and input implementation

`window_family.py` follows a bounded live owner/parent/menu-owner chain to an
actual `blender.exe` GHOST window. Titles or executable names alone cannot admit
a non-Blender window. A brokered dialog may have its own PID; both its process
creation stamp and Blender's stamp are pinned independently. Owner changes,
recycled handles/processes, unrelated applications and another Blender process
cannot reuse the existing authorization.

The helper keeps a scope for the explicit local selection. Automatic and
authenticated in-family transitions preserve that scope while advancing capture
generation and input session. The Unity input owner retains only an actual
confirmed native reservation, bound to connection/document, owner token, helper
instance/token, scope and Blender lifetime. It does not replay the action that
opened or closed a dialog. Helper restart, native identity change, permission
loss, stale host or failed cleanup ends admission.

Graphics Capture remains the normal backend. An opted-in owned non-GHOST
dialog/menu can fall back to selected-window PrintWindow after WGC start failure
or callback stall. Each successful read supplies actual pixels; metadata alone
never refreshes the image. Ownership and geometry are rechecked after reading.
Black/failed/late frames remain unavailable. Default P1/P2 capture-only behavior
does not acquire this fallback or broaden its window selection.

Native OS dialogs can block Blender's timer. While a joined connection holds a
confirmed native UI reservation, the server may answer only its built-in,
scene-free ping on the I/O thread. All edits, custom handlers and ordinary
unreserved requests still go through the main-thread queue. This keeps connection
health distinct from native tool telemetry; typed modeling/drawing still refuses
stale tool state. The reservation stays held until native modal cleanup finishes.
An already-open dialog that completely blocks the host before any reservation
can be granted still requires the host to resume before Focus can complete.

## Verification and integration

Headless checks exercise fake Win32 owner/focus/process/geometry reads, fake GDI
pixels and WGC failure paths, localhost HTTP sequencing, real Unity chooser/button
callbacks and real sender coroutines. They do not establish actual OS renderer
compatibility or injected-key delivery. Those need a native GUI trial on the
integrated app, followed by physical controller/headset checks. Arbitrary native
Blender data may remain outside the separate Unity scene mirror; generic preview
input does not expand that serialization contract.

The separate integration chat owns combining P2.5 with final P2 `2e9ede3` / PR158.
Preserve P2 placement, paired controller aim, Settings/manual planes, room
conversion and accepted capture/drag behavior. Use this branch's add-on and helper
with the app; the new optional window metadata is required for automatic trusted
continuation. Keep `CALHACKS_P25=1` and helper `--enable-input` explicit. Do not
substitute this older P2 ancestry for the finalized P2 app or merge into main.

See [P2.5 results](P2_5_RESULTS.md) for exact candidate/test provenance and
[preview interaction](P2_5_PREVIEW_INTERACTION.md) for all controls and launch setup.

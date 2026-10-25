# Native typed object actions verification

The optional P2.5 Model tools use the existing typed `object.*`, history and save
commands. `tests/p25/native_object_actions.py` verifies those actual host handlers,
leases, receipts and native Blender results in disposable background processes.
It does not infer button routing, Windows input, capture, focus or headset behavior
from successful native commands.

The test uses actual Session/Commands/Leases/Editor code. Its local dispatch object
only collects protocol responses; no socket/listener or existing host is used.
Every normal edit acquires the existing exclusive permission before its command
and releases it afterward. Native coordinates, dimensions and transforms are
measured independently. World rotations are checked against separately calculated
axis-rotation matrices, including composite turns.

Final results on October 24, 2026:

| Native units | Create | Fresh-process reopen | Native receipts | External evidence directory |
| --- | --- | --- | --- | --- |
| 1 metre per scene unit | 294 assertions passed | 7 passed | 148 + 3 | `p25-native-object-actions-unit1-final` |
| .001 metre per scene unit | 294 assertions passed | 7 passed | 148 + 3 | `p25-native-object-actions-unit001-final` |

All four fresh background Blender processes exited zero: **602 assertions and 302
actual command receipts**. CAD Sketcher was disabled for these runs, establishing
that these object commands do not require the sketch dependency. The runner also
supports an optional pinned CAD extension for a separately requested coexistence
check; it was not enabled in these results.

The verified command cases are:

- Cube, sphere and cylinder creation at each 20/50/100 mm size, at native world
  origin, with nine distinct stable native UUIDs and complete synchronized meshes.
- For every primitive, positive/negative 1/10/100 mm movement on each world axis,
  positive/negative 15/45/90 degree turns on each world axis, uniform scale 1.1 and
  its reciprocal, with all other native UUIDs unchanged.
- Composite rotations that distinguish world axes from local axes, and a world-X
  move after the object has been rotated.
- Exact request replay returning the stored receipt without another mutation;
  changed-payload reuse of its request ID being refused without geometry changes.
- Stale target generation, stale Undo revision, native Edit Mode, and a competing
  shared target lease being rejected, with native geometry unchanged.
- Delete affecting only the selected UUID; native Undo restoring its original
  UUID and geometry, Redo deleting it again, and a final Undo restoring it. This
  is exercised for cube, sphere and cylinder.
- Save refusing an unsaved document honestly, then native Save As of the isolated
  fixture followed by typed Save. A fresh process verifies all nine saved object
  UUIDs, evaluated meshes and transforms, preserves the document ID with a new
  open epoch, refuses the old epoch, and performs another typed target-specific
  move and Save.

The runner reuses the private environment and output guards from
`run_native_preview_workflows.py`. It sets private Blender resources/config/scripts/
data and all temporary directories before launch, disables source bytecode writes,
uses two Blender threads at BelowNormal priority, and checks actual native temporary
paths. Both source and source-bytecode fingerprints stayed unchanged through the
create/reopen pairs. No P2 resources, interactive document, GUI, OS input, Player,
headset, default network port, main branch or FPS work was involved.

Each evidence directory contains `manifest.json`, native process logs,
`object-*-result.json` including the actual receipts, private profiles, the saved
native fixture and independent persistence metadata. Earlier narrower successful
attempts are preserved. No backend or contract change was needed for this pass.

Example invocation with a new absolute external output directory:

```powershell
& '<bundled-python>/python.exe' tests/p25/run_native_object_actions.py `
  --blender '<Blender 5.2>/blender.exe' `
  --output '<new-external-evidence-directory>' `
  --unit-scale .001
```

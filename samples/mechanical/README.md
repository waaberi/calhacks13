# P0 mechanical reference

Use `p0_reference_v2.blend` for current integration tests. It preserves the same geometry and applies the blue/orange colors to both the viewport material and Principled Base Color. The original `p0_reference.blend` is preserved as historical v1 evidence; its shader colors were gray despite colored solid-viewport display.

Owner: Talia. `p0_reference.blend` contains a 20 x 20 x 20 mm cube and a cylinder with diameter 10 mm and height 30 mm. These are starter dimensions chosen for this workspace; the plan requires known millimeter dimensions but does not prescribe these primitive sizes. Talia can choose a different fixture in a new version.

The scene uses Metric, unit scale 1.0, and millimeter display. Geometry coordinates are meters: 20 mm is 0.020 Blender units. Z is up. Object scales are applied and equal to 1. This fixture does not decide the team's transport or Unity coordinate conversion.

Open the file in Blender, select an object, and press **N** in the viewport to inspect **Item > Dimensions**. Use **File > Save As** to make an editing copy first. Do not overwrite the baseline. The `fixture_id` custom properties are reference labels, not the application's stable object IDs.

To regenerate in PowerShell, run from the repository root and choose a new output if the baseline already exists:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python-exit-code 1 --python samples/mechanical/create_reference.py -- --output samples/mechanical/p0_reference_v2.blend
```

The generator defaults to v2 and refuses to overwrite any existing output. Choose another unused filename if regenerating. This creates a separate background process and preserves any open Blender window and unsaved work. Run the v2 native verification command in `acceptance/native-reference/README.md` after generation. The 100 x 60 mm constrained rectangle belongs to P3C; the primitive fixture does not claim a working CAD solver.

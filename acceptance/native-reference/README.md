# Native reference evidence

Current fixture: `samples/mechanical/p0_reference_v2.blend`. Its independent oracle is `expected_dimensions_v2.json`, and `p0-native-reference-v2.json` records 59 passing fresh-reopen checks, including viewport and shader colors. Verify it with:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup samples/mechanical/p0_reference_v2.blend --python-exit-code 1 --python acceptance/native-reference/verify_reference.py -- --expected acceptance/native-reference/expected_dimensions_v2.json --report acceptance/native-reference/p0-native-reference-v2.json
```

The v1 files below remain preserved as historical geometry evidence. Their original 37 checks did not test rendered material colors, which let a gray shader pass despite colored viewport display.

Owner: Talia. `expected_dimensions.json` is the independent measurement oracle for the baseline fixture. `p0-native-reference.json` records the actual save/fresh-reopen check and the exact .blend SHA-256. A fixture pass does not pass the full P0 team gate.

Run from the repository root in PowerShell:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup samples/mechanical/p0_reference.blend --python-exit-code 1 --python acceptance/native-reference/verify_reference.py
```

The verifier checks the native file, dimensions and positions in millimeters, applied scale, rotation, fixture labels and unit settings. It exits with an error if a check fails. It expects the unchanged baseline, so do not run it against a deliberately edited result and interpret the difference as an application bug.

Later native acceptance uses a copy: move the cube +10 mm on X (center X goes from -20 to -10 mm), rotate it +90 degrees about Z, test Undo/Redo, save and reopen. Because a cube is symmetric, inspect the numeric rotation; its silhouette alone cannot establish 90 degrees.

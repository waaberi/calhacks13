# Physical model size in VR

The default model display is **1:1**: one metre from Blender is one Unity world
metre. The host already multiplies local mesh positions and world translations by
Blender's scene Unit Scale (`scale_length`). The receiver must not multiply those
lengths by Unit Scale a second time, normalize them to a bounding box, or add the
former five-times demo enlargement. Native object scale factors still apply once.
Changing Blender's displayed length unit alone does not resize an object.

The old `HostScene.displayScale` field and its serialized `SampleScene` value are
removed. New documents and file epochs start at actual size. Same-document
reconnects retain the user's deliberately chosen inspection magnification.

Two-hand inspection resizing and the older size controls remain available. The
menu says **Actual size · 1:1** at physical size and **Inspection size · N×** while
magnified. **Actual size** in the Arrange space menu cancels held manipulation and
restores the metre scale without changing the workspace position or heading.
Reset View and Recover workspace also restore actual size. These are viewer
actions; they never resize or save the Blender design.

Physical size means the dimensions authored in the file. An artist's arbitrary
character scale does not establish a canonical human height. Do not shrink the
source, change its units, or use the separately prepared Kakashi tabletop copy to
claim that the application's scale bug is fixed.

## Verification

`tests/blender/export_physical_scale.py` runs in a private background Blender and
exports the actual host's geometry/transform records for metre, millimetre and
centimetre Unit Scales. Its independent oracle reads Blender's evaluated world
vertices directly. Cases include a 20×30×40 mm part and metre geometry with a
rotated/scaled parent, nonuniform/reflected object scale and a subdivision modifier.

`PhysicalScaleChecks.Run`, included in `P2Checks.Windows`, decodes these real
exports through HostLink, creates HostScene's actual meshes/transforms and compares
their rendered world bounds against that Blender oracle after workspace placement.
It also checks explicit magnification, the actual Actual size menu collider/action,
reset, same-document reconnect and new-document/file-epoch behavior. The tolerance
is 20 micrometres, accounting for the existing wire rounding and float transforms.
No Player, headset, interactive Blender, capture selection or native host is used.

Regenerate the checked-in fixture with the pinned Blender version:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --disable-autoexec --python tests/blender/export_physical_scale.py
```

Use private Blender user resources when running this command. Run the cumulative
Windows build and capture checks described in the existing regression guide.
Headset comparison with a physical ruler remains a separate confirmation after
the runtime owner integrates this branch; software dimensions alone do not certify
the headset's physical calibration or room alignment.

The existing wire protocol decomposes world transforms into translation, rotation
and scale. As documented in `contracts/README.md`, it cannot represent shear caused
by some rotated, nonuniformly scaled parent hierarchies. This viewer correction
does not remove that separate exporter limitation.

"""Fresh solver-free Blender verifies preserved full editable host JSON records."""
import json
import sys
from pathlib import Path

import bpy

output = Path(sys.argv[sys.argv.index("--") + 1])
bpy.ops.wm.open_mainfile(filepath=str(output / "mirror.blend"), load_ui=False)
expected = json.loads((output / "mirror-meta.json").read_text())
actual = {o["spatial_modeling_id"]: json.loads(o["spatial_modeling_sketch_record"])
          for o in bpy.data.objects if o.get("spatial_modeling_mirror_kind") == "host_solved_sketch"}
assert actual == expected
assert all(o.type == "CURVE" and o.hide_select and not o.data.materials
           for o in bpy.data.objects if o.get("spatial_modeling_mirror_kind"))
assert "CAD_Sketcher" not in sys.modules and "slvs" not in sys.modules
(output / "mirror-reopen-result.json").write_text(json.dumps({"passed": True,
    "sketches": len(actual), "full_entity_constraint_ids_values": "preserved", "local_solver": False}))

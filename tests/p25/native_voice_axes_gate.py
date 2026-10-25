"""True-background factory-only axis/chain kernel check; no listener or GUI.

Checks production whole-plan prevalidation then production native kernels.
Does not claim native Undo/lease/UI/headset acceptance.
"""
import argparse
import copy
import json
import math
import sys
import traceback
import uuid
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
from spatial_modeling import edits, modeling_recipe, modeling_tools, tool_catalog


def run():
    assert bpy.app.background, "Never open a GUI test window for this check"
    cube = bpy.data.objects["Cube"]
    untouched = bpy.data.objects["Camera"]
    cube["spatial_modeling_id"] = uuid.uuid4().hex
    oid = cube["spatial_modeling_id"]
    other_before = [list(row) for row in untouched.matrix_world]
    lookup = SimpleNamespace(find_object=lambda key: cube if key == oid else None,
                             object_id=lambda obj: obj["spatial_modeling_id"])
    editor = edits.Editor(lookup, lambda summary: lambda operation: operation)
    planner = modeling_recipe.Planner(tool_catalog.catalog(), tool_catalog.validate)
    context = {"document_id": uuid.uuid4().hex, "open_epoch": uuid.uuid4().hex,
               "revision": 1, "mode": "OBJECT", "native_tool": "", "topology_token": "",
               "options": {}, "native_selection": {}, "gesture_epoch": 0, "gesture_active": False,
               "selection": {"component": "object", "indices": [], "objects": [{"id": oid, "generation": 1}]},
               "objects": [{"id": oid, "name": "Cube", "generation": 1}]}

    def reset():
        cube.location = (0, 0, 0)
        cube.rotation_mode = "QUATERNION"
        cube.rotation_quaternion = (1, 0, 0, 0)
        cube.scale = (1, 1, 1)
        bpy.context.view_layer.update()

    def step(tool, params, number=1):
        return {"id": "s" + str(number), "tool": tool, "target": oid,
                "selection": {"component": "object", "indices": []}, "params": params}

    def prepare(steps):
        frozen = copy.deepcopy(context)
        _, candidate = planner.prepare({"decision": "propose", "steps": steps}, frozen, context, object())
        return candidate

    def execute(candidate):
        for entry in candidate["steps"]:
            modeling_tools.apply_step(editor, cube, entry["tool"], entry["params"], entry["selection"])

    checks = []
    for axis in range(3):
        reset()
        move = [0., 0., 0.]
        move[axis] = .1
        execute(prepare([step("object.translate", {"translation_m": move})]))
        assert (cube.matrix_world.translation - Vector(move)).length < 1e-6
        checks.append("native_move_" + "XYZ"[axis] + "_meters_exact")
        reset()
        direction = [0., 0., 0.]
        direction[axis] = 1.
        rotation = Quaternion(direction, math.pi / 2)
        execute(prepare([step("object.rotate", {"rotation": list(rotation)})]))
        assert abs(abs(cube.matrix_world.to_quaternion().dot(rotation)) - 1) < 1e-6
        checks.append("native_rotate_" + "XYZ"[axis] + "_quaternion_exact")
    reset()
    turn = Quaternion((0, 1, 0), math.pi / 4)
    execute(prepare([step("object.translate", {"translation_m": [.02, 0, 0]}),
                     step("object.rotate", {"rotation": list(turn)}, 2)]))
    assert (cube.matrix_world.translation - Vector((.02, 0, 0))).length < 1e-6
    assert abs(abs(cube.matrix_world.to_quaternion().dot(turn)) - 1) < 1e-6
    checks.append("two_step_move_then_rotate_preserves_order_and_translation")
    before = [list(row) for row in cube.matrix_world]
    try:
        prepare([step("object.translate", {"translation_m": [0, .1, 0]}), step("file.export", {}, 2)])
    except modeling_recipe.InvalidRecipe:
        pass
    else:
        raise AssertionError("Unsupported tail admitted")
    assert [list(row) for row in cube.matrix_world] == before
    assert [list(row) for row in untouched.matrix_world] == other_before
    checks.append("unsupported_tail_refused_before_any_prefix_and_other_object_unchanged")
    return {"passed": True, "checks": checks, "background": True, "blender": bpy.app.version_string,
            "gui_listener_user_model_service_calls": 0, "undo_lease_headset_acceptance": False}


args = argparse.ArgumentParser()
args.add_argument("--output", type=Path, required=True)
parsed = args.parse_args(sys.argv[sys.argv.index("--") + 1:])
try:
    result = run()
except Exception:
    result = {"passed": False, "error": traceback.format_exc(), "background": bpy.app.background}
parsed.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result))
if not result["passed"]:
    raise SystemExit(1)

"""Headless native document hashes ignore local viewport orbit, preserve all data edits."""
import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Quaternion

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
sys.path.insert(0, str(Path(__file__).parent))
from native_fixture import CUBE, MATERIAL, build_fixture
from spatial_modeling.native_sync.document import NativeDocument

out = Path(sys.argv[sys.argv.index("--") + 1])
out.mkdir(parents=True, exist_ok=True)
report = {"passed": False, "checks": [], "headless": bpy.app.background}
try:
    build_fixture()
    document = NativeDocument()
    captures = [document.capture(out / "checkpoint.blend") for _ in range(3)]
    assert len({item.document_hash for item in captures}) == 1
    report["checks"].append("three unchanged full original-data checkpoints have stable model fingerprint")
    view = next(area.spaces.active.region_3d for area in bpy.context.window.screen.areas if area.type == "VIEW_3D")
    view.view_rotation = Quaternion((.9238795, 0, 0, .3826834))
    view.view_location, view.view_distance = (.3, .2, .1), 8.75
    orbit = document.capture(out / "checkpoint.blend")
    assert orbit.sha256 != captures[-1].sha256
    assert orbit.document_hash == captures[-1].document_hash
    report["checks"].append("local viewport orbit changes transfer bytes but never model-change fingerprint")
    previous = orbit.document_hash
    cube = bpy.data.objects[CUBE]
    mutations = [
        ("native object transform", lambda: setattr(cube.location, "x", cube.location.x + .075)),
        ("UV coordinate", lambda: setattr(cube.data.uv_layers.active.data[0], "uv", (.43, .57))),
        ("material node value", lambda: setattr(bpy.data.materials[MATERIAL].node_tree.nodes["Principled BSDF"].inputs["Roughness"], "default_value", .28)),
        ("native custom property", lambda: cube.__setitem__("native_scalar", .91)),
        ("original shape-key geometry", lambda: setattr(cube.data.shape_keys.key_blocks[0].data[0].co, "x", .33)),
        ("generic point attribute", lambda: setattr(cube.data.attributes["NativeSync_Attribute"].data[0], "value", .79)),
    ]
    for label, mutate in mutations:
        mutate()
        captured = document.capture(out / "checkpoint.blend")
        assert captured.document_hash != previous, label + " was ignored"
        assert captured.document_hash == document.capture(out / "checkpoint.blend").document_hash, label + " is unstable"
        previous = captured.document_hash
        report["checks"].append(label + " changes model fingerprint and remains stable on repeat")
    report["passed"] = True
except Exception:  # noqa: BLE001 - retain native fingerprint verification failures
    report["error"] = traceback.format_exc()
finally:
    (out / "RESULT.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)

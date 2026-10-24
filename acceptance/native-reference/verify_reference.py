"""Check a freshly reopened P0 .blend against independent expected values."""

import argparse
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

import bpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", type=Path, default=Path(__file__).with_name("expected_dimensions.json"))
    parser.add_argument("--report", type=Path, default=Path(__file__).with_name("p0-native-reference.json"))
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    checks = []

    def check(label, actual, wanted, tolerance=None):
        passed = abs(actual - wanted) <= tolerance if tolerance is not None else actual == wanted
        checks.append({"check": label, "actual": actual, "expected": wanted, "passed": passed})

    scene = bpy.context.scene
    bpy.context.view_layer.update()
    check("fixture_version", scene.get("fixture_version"), expected["fixture_version"])
    check("Blender_version", ".".join(map(str, bpy.app.version)), expected["blender_version"])
    check("unit_system", scene.unit_settings.system, expected["unit_system"])
    check("unit_scale", scene.unit_settings.scale_length, expected["unit_scale"], 1e-9)
    check("display_length", scene.unit_settings.length_unit, expected["display_length"])
    check("mesh_names", sorted(o.name for o in scene.objects if o.type == "MESH"), sorted(o["name"] for o in expected["objects"]))
    tolerance = expected["tolerance_mm"]
    for fixture in expected["objects"]:
        obj = scene.objects.get(fixture["name"])
        check(fixture["name"] + ".exists", obj is not None, True)
        if obj is None:
            continue
        check(obj.name + ".type", obj.type, "MESH")
        check(obj.name + ".fixture_id", obj.get("fixture_id"), fixture["fixture_id"])
        readings = {
            "dimensions_mm": [v * scene.unit_settings.scale_length * 1000 for v in obj.dimensions],
            "location_mm": [v * scene.unit_settings.scale_length * 1000 for v in obj.location],
            "scale": list(obj.scale),
            "rotation_degrees": [math.degrees(v) for v in obj.rotation_euler],
        }
        for field, actual in readings.items():
            for axis, value, wanted in zip("XYZ", actual, fixture[field]):
                check(f"{obj.name}.{field}.{axis}", value, wanted, tolerance if field.endswith("_mm") else 1e-6)

        if "color_rgba_linear" in fixture:
            material = obj.active_material
            check(obj.name + ".material_exists", material is not None, True)
            if material is not None:
                shaders = [node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"] if material.node_tree else []
                check(obj.name + ".principled_shader_exists", bool(shaders), True)
                for channel, actual, wanted in zip("RGBA", material.diffuse_color, fixture["color_rgba_linear"]):
                    check(f"{obj.name}.viewport_color.{channel}", actual, wanted, 1e-6)
                if shaders:
                    base = shaders[0].inputs["Base Color"]
                    check(obj.name + ".base_color_is_unlinked", base.is_linked, False)
                    for channel, actual, wanted in zip("RGBA", base.default_value, fixture["color_rgba_linear"]):
                        check(f"{obj.name}.shader_color.{channel}", actual, wanted, 1e-6)

    blend = Path(bpy.data.filepath)
    check("saved_file_loaded", bool(bpy.data.filepath) and blend.is_file(), True)
    report = {
        "status": "PASSED" if all(c["passed"] for c in checks) else "FAILED",
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "scope": "Native P0 fixture reopened in a separate Blender process; no headset, app, bridge or CAD-solver acceptance.",
        "fixture": blend.name,
        "sha256": hashlib.sha256(blend.read_bytes()).hexdigest() if blend.is_file() else None,
        "blender_version": bpy.app.version_string,
        "checks": checks,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{report['status']}: {len(checks)} native checks; report: {args.report}")
    if report["status"] != "PASSED":
        for failure in checks:
            if not failure["passed"]:
                print(json.dumps(failure))
        raise RuntimeError("Native reference validation failed.")


if __name__ == "__main__":
    main()

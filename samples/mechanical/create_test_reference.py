"""Create or independently reopen a larger disposable copy of the P0 v2 fixture.

Run with Blender --background --factory-startup --python this_file -- --output NEW.blend.
Run the same command with --verify to reopen NEW.blend and write its JSON evidence.
The original dimensional-acceptance fixture is never saved or overwritten.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

SOURCE = Path(__file__).resolve().with_name("p0_reference_v2.blend")
FACTOR = 10.0
FIXTURES = (
    {
        "source_name": "Cube_20mm", "name": "Test_Cube_200mm",
        "source_id": "p0-cube-20mm", "id": "test-cube-200mm",
        "dimensions_m": (0.2, 0.2, 0.2), "location_m": (-0.2, 0.0, 0.1),
    },
    {
        "source_name": "Cylinder_D10_H30mm", "name": "Test_Cylinder_D100_H300mm",
        "source_id": "p0-cylinder-d10-h30mm", "id": "test-cylinder-d100-h300mm",
        "dimensions_m": (0.1, 0.1, 0.3), "location_m": (0.2, 0.0, 0.15),
    },
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def near(actual, expected):
    return all(math.isclose(a, b, rel_tol=0, abs_tol=0.000001) for a, b in zip(actual, expected))


def require_units(scene):
    units = scene.unit_settings
    require(units.system == "METRIC" and units.length_unit == "MILLIMETERS"
            and math.isclose(units.scale_length, 1.0), "Preserve one Blender unit = one meter.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true", help="Reopen the saved copy and write evidence.")
    parser.add_argument("--evidence", type=Path, help="Fresh JSON path; defaults to output.with_suffix('.json').")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    require(bpy.app.background and "--factory-startup" in sys.argv,
            "Use a separate --background --factory-startup Blender process.")
    source = SOURCE.resolve(strict=True)
    output = args.output.resolve()
    evidence = (args.evidence or output.with_suffix(".json")).resolve()
    require(source != output, "The original fixture cannot be the output.")
    require(output.suffix.lower() == ".blend", "Choose an explicit new .blend output.")
    original_sha = digest(source)

    if not args.verify:
        if output.exists():
            raise FileExistsError(f"Preserving existing output: {output}")
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=True)
        scene = bpy.context.scene
        require_units(scene)
        require(scene.get("fixture_version") == "p0-v2", "Expected the original P0 v2 fixture.")
        meshes = [obj for obj in scene.objects if obj.type == "MESH"]
        require({obj.name for obj in meshes} == {item["source_name"] for item in FIXTURES},
                "Unexpected source objects; do not silently scale another fixture.")
        for item in FIXTURES:
            obj = bpy.data.objects[item["source_name"]]
            require(obj.get("fixture_id") == item["source_id"], "Source fixture ID differs.")
            require(near(obj.dimensions, [value / FACTOR for value in item["dimensions_m"]])
                    and near(obj.location, [value / FACTOR for value in item["location_m"]])
                    and near(obj.scale, (1, 1, 1)), "Unexpected source dimensions/location/applied scale.")
            for vertex in obj.data.vertices:
                vertex.co *= FACTOR
            obj.data.update()
            obj.location *= FACTOR
            obj.name = item["name"]
            obj.data.name = item["name"] + "_Mesh"
            for material in obj.data.materials:
                material.name = item["name"] + "_Material"
            obj["fixture_id"] = item["id"]
            obj["source_fixture_id"] = item["source_id"]
            obj["expected_dimensions_mm"] = [value * 1000 for value in item["dimensions_m"]]
        scene.name = "Large_Disposable_Test_Reference"
        scene["fixture_version"] = "test-large-v1"
        scene["source_fixture_version"] = "p0-v2"
        scene["source_fixture_sha256"] = original_sha
        scene["test_scale_factor"] = FACTOR
        scene["reference_notes"] = "Disposable 10x test copy. One Blender unit = one meter; display in mm. Original P0 acceptance fixture preserved."
        notes = bpy.data.texts.get("REFERENCE_README") or bpy.data.texts.new("REFERENCE_README")
        notes.clear()
        notes.write(
            "Larger disposable test reference\n"
            "Cube: 200 x 200 x 200 mm. Cylinder: diameter 100 mm, height 300 mm.\n"
            "Geometry and object locations are 10x the preserved P0 v2 original.\n"
            "Metric, unit scale 1.0: coordinates are meters, Z is up.\n"
            "Blue cube and orange cylinder; applied object scale stays (1, 1, 1).\n"
            "Use this copy for interactive testing; it does not replace the original dimensional acceptance fixture.\n"
        )
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                space = area.spaces.active
                space.clip_start = 0.001
                space.clip_end = 100.0
                space.overlay.grid_scale = 0.1
                space.region_3d.view_location = Vector((0, 0, 0.15))
                space.region_3d.view_distance = 1.4
        bpy.context.view_layer.update()
        output.parent.mkdir(parents=True, exist_ok=True)
        require(not output.exists(), "Output appeared during generation; preserve it.")
        require(bpy.ops.wm.save_as_mainfile(filepath=str(output)) == {"FINISHED"}, "Save did not finish.")
        require(digest(source) == original_sha, "Original source changed during generation.")
        print(f"LARGE_TEST_REFERENCE_CREATED output={output} original_sha256={original_sha}")
        return

    require(output.is_file(), "The generated output must exist for independent reopen verification.")
    if evidence.exists():
        raise FileExistsError(f"Preserving existing verification evidence: {evidence}")
    bpy.ops.wm.open_mainfile(filepath=str(output), load_ui=True)
    scene = bpy.context.scene
    require_units(scene)
    require(scene.get("fixture_version") == "test-large-v1"
            and scene.get("source_fixture_sha256") == original_sha
            and scene.get("test_scale_factor") == FACTOR, "Saved fixture provenance differs.")
    objects = []
    require({obj.name for obj in scene.objects if obj.type == "MESH"} == {item["name"] for item in FIXTURES},
            "Reopened fixture has unexpected mesh objects.")
    for item in FIXTURES:
        obj = bpy.data.objects[item["name"]]
        require(near(obj.dimensions, item["dimensions_m"]) and near(obj.location, item["location_m"]),
                "Reopened dimensions/location differ: " + item["name"])
        require(near(obj.scale, (1, 1, 1)) and obj.get("fixture_id") == item["id"]
                and near(obj["expected_dimensions_mm"], [value * 1000 for value in item["dimensions_m"]]),
                "Reopened applied scale or dimension metadata differs: " + item["name"])
        require(abs(min((obj.matrix_world @ Vector(corner)).z for corner in obj.bound_box)) < 0.000001,
                "Larger model must still rest on Z=0.")
        objects.append({"name": obj.name, "fixture_id": obj["fixture_id"],
                        "dimensions_m": list(obj.dimensions), "location_m": list(obj.location),
                        "applied_scale": list(obj.scale), "expected_dimensions_mm": list(obj["expected_dimensions_mm"])})
    viewports = []
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                require(math.isclose(space.region_3d.view_distance, 1.4, abs_tol=0.000001)
                        and math.isclose(space.overlay.grid_scale, 0.1, abs_tol=0.000001)
                        and math.isclose(space.clip_start, 0.001, abs_tol=0.000001)
                        and math.isclose(space.clip_end, 100.0), "Saved viewport framing differs.")
                viewports.append({"distance_m": space.region_3d.view_distance,
                                  "grid_m": space.overlay.grid_scale,
                                  "clip_start_m": space.clip_start, "clip_end_m": space.clip_end})
    require(viewports, "The saved file must retain a framed 3D viewport.")
    require(digest(source) == original_sha, "Original source changed during reopen verification.")
    result = {"passed": True, "fresh_background_reopen": True, "blender": bpy.app.version_string,
              "source": str(source), "source_sha256": original_sha, "source_unchanged": True,
              "output": str(output), "output_sha256": digest(output), "scale_factor": FACTOR,
              "units": {"system": scene.unit_settings.system, "length": scene.unit_settings.length_unit,
                        "meters_per_blender_unit": scene.unit_settings.scale_length},
              "objects": objects, "viewports": viewports}
    evidence.parent.mkdir(parents=True, exist_ok=True)
    with evidence.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(f"LARGE_TEST_REFERENCE_CHECK PASS evidence={evidence}")


if __name__ == "__main__":
    main()

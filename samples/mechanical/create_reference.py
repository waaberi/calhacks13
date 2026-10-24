"""Create Talia's P0 fixture in a separate, factory-startup Blender process."""

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=Path(__file__).resolve().parent / "p0_reference_v2.blend",
    )
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    output = args.output.resolve()
    if not bpy.app.background:
        raise RuntimeError("Use a separate background Blender process with --factory-startup.")
    if output.exists():
        raise FileExistsError(f"Preserving existing reference: {output}. Choose a new --output.")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.name = "P0_Millimeter_Reference"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "MILLIMETERS"

    fixtures = [
        ("Cube_20mm", "p0-cube-20mm", (0.020, 0.020, 0.020), (-0.020, 0, 0.010), (0.12, 0.42, 0.80, 1)),
        ("Cylinder_D10_H30mm", "p0-cylinder-d10-h30mm", (0.010, 0.010, 0.030), (0.020, 0, 0.015), (0.95, 0.38, 0.10, 1)),
    ]
    for name, fixture_id, dimensions, location, color in fixtures:
        if name.startswith("Cube"):
            bpy.ops.mesh.primitive_cube_add(size=1, location=location)
        else:
            bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.005, depth=0.030, location=location)
        obj = bpy.context.object
        obj.name = name
        obj.data.name = name + "_Mesh"
        obj.dimensions = dimensions
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        obj["fixture_id"] = fixture_id
        obj["expected_dimensions_mm"] = [v * 1000 for v in dimensions]
        material = bpy.data.materials.new(name + "_Material")
        material.diffuse_color = color
        # Blender 5.2 creates a node material. Solid-view colors alone do not
        # change its rendered Base Color, which is what the host exports.
        shader = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
        shader.inputs["Base Color"].default_value = color
        obj.data.materials.append(material)
        obj.color = color

    scene["fixture_version"] = "p0-v2"
    scene["reference_notes"] = "1 Blender unit = 1 meter. Display in mm. Fixture IDs are test labels, not protocol IDs."
    notes = bpy.data.texts.new("REFERENCE_README")
    notes.write(
        "P0 reference v2\nCube: 20 x 20 x 20 mm. Cylinder: diameter 10 mm, height 30 mm.\n"
        "Viewport and Principled shader colors agree: blue cube and orange cylinder.\n"
        "Metric, unit scale 1.0; numeric coordinates are meters. Z is up.\n"
        "Use a copy for edits. Expected cube translation: +10 mm on X; rotation: +90 degrees on Z.\n"
        "The later 100 x 60 -> 120 x 60 mm CAD sketch is a separate solver acceptance test.\n"
    )
    bpy.ops.object.select_all(action="DESELECT")
    cube = bpy.data.objects["Cube_20mm"]
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.clip_start = 0.0001
                space.clip_end = 100
                space.overlay.grid_scale = 0.01
                space.shading.color_type = "MATERIAL"
                space.region_3d.view_location = Vector((0, 0, 0.015))
                space.region_3d.view_distance = 0.14
                space.region_3d.view_rotation = Quaternion((0.8805, 0.3647, 0.1159, 0.2798)).normalized()

    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    print(f"Created P0 reference with Blender {bpy.app.version_string}: {output}")


if __name__ == "__main__":
    main()

"""Extend existing CAD solver/history/cold-reopen gate with native UI policy/view checks."""

import argparse
import importlib
import json
import sys
from pathlib import Path

import bpy

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/p25"))
from native_spatial_gate import main as cad_gate


def main(args):
    assert bpy.app.background
    cad_gate(args)
    from spatial_modeling import blender_ui, preview_spatial, sketch
    blender_ui.register()
    try:
        metadata = json.loads((args.output / "editable.json").read_text())
        obj = sketch.find(metadata["rectangle"])
        bpy.context.scene.sketcher.active_sketch_object = obj
        # The pinned dependency deliberately skips its toolbar registration in
        # background mode. Invoke its real registration path in this private
        # fixture; this is native tool-state evidence, never GUI delivery.
        manager = importlib.import_module(sketch._adapter()._module().__name__ + ".workspacetools.manager")
        manager.enter_sketch_mode()
        bpy.context.scene.spatial_editing_mode = "SHARED"
        assert preview_spatial.editing_mode(bpy.context) == "shared"
        bpy.context.scene.spatial_editing_mode = "EXCLUSIVE"
        assert preview_spatial.editing_mode(bpy.context) == "exclusive"
        area = next(a for a in bpy.context.screen.areas if a.type == "VIEW_3D")
        region = next(r for r in area.regions if r.type == "WINDOW")
        with bpy.context.temp_override(area=area, region=region):
            record = sketch.snapshot()
            view = area.spaces.active.region_3d
            before = (tuple(view.view_location), view.view_distance, tuple(view.view_rotation), view.view_perspective)
            saved_file = Path(bpy.data.filepath).read_bytes()
            selection = [(o.name, o.select_get()) for o in bpy.context.scene.objects]
            assert bpy.ops.spatial_modeling.frame_native_sketch() == {"FINISHED"}
            assert view.view_distance < 1 / args.unit_scale
            vertices = blender_ui.preview_lines(bpy.context)
            assert len(vertices) == 8
            lengths = [(vertices[i] - vertices[i + 1]).length * args.unit_scale for i in range(0, 8, 2)]
            width = .13 if args.phase == "reopen" else .12
            assert all(min(abs(length - width), abs(length - .06)) < 1e-6 for length in lengths)
            assert sketch.snapshot() == record
            assert Path(bpy.data.filepath).read_bytes() == saved_file
            assert selection == [(o.name, o.select_get()) for o in bpy.context.scene.objects]
            assert bpy.ops.spatial_modeling.preview_contrast() == {"CANCELLED"}, "No GPU handler in headless validation"
            view.view_location, view.view_distance, view.view_rotation, view.view_perspective = before
            native_tools = {}
            for tool, expected in (("sketcher.slvs_add_line2d", "line"),
                                   ("sketcher.slvs_add_rectangle", "rectangle"),
                                   ("sketcher.slvs_add_circle2d", "circle")):
                assert bpy.ops.wm.tool_set_by_id(name=tool) == {"FINISHED"}
                state = preview_spatial.read_state(bpy.context)
                assert state["native_tool"] == tool and state["tool"] == expected
                assert state["sketch_id"] == metadata["rectangle"]
                native_tools[tool] = {"tool": state["tool"], "sketch_id": state["sketch_id"],
                                      "unsupported_options": state["unsupported_options"]}
        result = {"passed": True, "background_only": True, "phase": args.phase,
                  "native_tools": native_tools, "contrast_line_segments": len(vertices) // 2,
                  "contrast_gpu_render": "PENDING interactive/capture gate", "framing": "actual native operator; view-only invariance",
                  "geometry_file_selection_unchanged": True, "unit_scale": args.unit_scale}
        (args.output / f"ui-{args.phase}-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    finally:
        blender_ui.unregister()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--phase", choices=("create", "reopen"), required=True)
    parser.add_argument("--unit-scale", type=float, default=1)
    parser.add_argument("--require-history", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    main(args)

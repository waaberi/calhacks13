"""Native-only editing policy and reversible preview framing.

The unrestricted production desktop is cooperative, not a strict authority
boundary. Raw preview input always reserves the whole desktop document. Shared
mode applies to validated direct-drawing commands with whole-sketch leases.
"""

import math

import bpy
from mathutils import Vector

from . import host, sketch

_contrast_handle = None
_contrast_error = False


def preview_lines(context):
    """Read-only solved native points for a disposable high-contrast overlay."""
    obj = getattr(getattr(context.scene, "sketcher", None), "active_sketch_object", None)
    if obj is None:
        return []
    record = next((s for s in sketch.snapshot() if s["id"] == obj.get("spatial_modeling_id")), None)
    if record is None:
        return []
    scale = context.scene.unit_settings.scale_length
    points = {e["id"]: Vector((*e["at"], 0)) / scale
              for e in record["entities"] if e["kind"] == "point"}
    vertices = []
    for entity in record["entities"]:
        if entity["kind"] == "line":
            vertices.extend(obj.matrix_world @ points[p] for p in entity["points"])
        elif entity["kind"] == "circle":
            center, radius = points[entity["center"]], entity["radius"] / scale
            for i in range(64):
                for j in (i, i + 1):
                    angle = j * math.tau / 64
                    vertices.append(obj.matrix_world @ (center + Vector((math.cos(angle), math.sin(angle), 0)) * radius))
    return vertices


def _draw_contrast():
    global _contrast_error
    import gpu
    from gpu_extras.batch import batch_for_shader
    try:
        vertices = preview_lines(bpy.context)
        if not vertices or bpy.context.region is None:
            return
        shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        batch = batch_for_shader(shader, "LINES", {"pos": vertices})
        shader.bind()
        shader.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
        shader.uniform_float("lineWidth", 3.0)
        shader.uniform_float("color", (.1, .95, 1, 1))
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("LESS_EQUAL")
        batch.draw(shader)
    except Exception as exc:  # noqa: BLE001 - optional display must not break native editing
        if not _contrast_error:
            print("Spatial preview contrast unavailable:", type(exc).__name__)
            _contrast_error = True
    finally:
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")


class PreviewContrast(bpy.types.Operator):
    """Toggle a session-only overlay; never saves CAD colors or preferences"""

    bl_idname = "spatial_modeling.preview_contrast"
    bl_label = "Preview contrast on/off"

    def execute(self, context):
        global _contrast_handle
        if bpy.app.background:
            return {"CANCELLED"}
        if _contrast_handle is None:
            _contrast_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_contrast, (), "WINDOW", "POST_VIEW")
        else:
            bpy.types.SpaceView3D.draw_handler_remove(_contrast_handle, "WINDOW")
            _contrast_handle = None
        context.area.tag_redraw()
        return {"FINISHED"}


class FrameNativeSketch(bpy.types.Operator):
    """Frame the current native sketch without editing geometry or preferences"""

    bl_idname = "spatial_modeling.frame_native_sketch"
    bl_label = "Frame native sketch"

    @classmethod
    def poll(cls, context):
        group = getattr(context.scene, "sketcher", None)
        return context.area is not None and context.area.type == "VIEW_3D" and (
            getattr(group, "active_sketch_object", None) is not None)

    def execute(self, context):
        obj = context.scene.sketcher.active_sketch_object
        record = next((s for s in sketch.snapshot() if s["id"] == obj.get("spatial_modeling_id")), None)
        if record is None:
            self.report({"WARNING"}, "The native sketch is unavailable or unsupported")
            return {"CANCELLED"}
        # Solved points are in meters on the plane. Native view coordinates use
        # scene units. Include circle extrema rather than only their centers.
        scale = context.scene.unit_settings.scale_length
        points = {e["id"]: Vector((*e["at"], 0)) / scale
                  for e in record["entities"] if e["kind"] == "point"}
        bounds = list(points.values())
        for entity in record["entities"]:
            if entity["kind"] == "circle":
                center, radius = points[entity["center"]], entity["radius"] / scale
                bounds.extend(center + Vector(offset) * radius for offset in (
                    (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)))
        if not bounds:
            self.report({"INFO"}, "Draw geometry before framing this sketch")
            return {"CANCELLED"}
        world = [obj.matrix_world @ point for point in bounds]
        lo = Vector(tuple(min(p[i] for p in world) for i in range(3)))
        hi = Vector(tuple(max(p[i] for p in world) for i in range(3)))
        view = context.space_data.region_3d
        view.view_location = (lo + hi) * .5
        view.view_distance = max((hi - lo).length * 1.8, .01 / scale)
        # Face the native plane, using its own basis; do not guess a VR/world axis.
        view.view_rotation = obj.matrix_world.to_quaternion()
        view.view_perspective = "ORTHO"
        context.area.tag_redraw()
        return {"FINISHED"}


class NativeEditingPanel(bpy.types.Panel):
    bl_label = "Spatial editing"
    bl_idname = "SPATIAL_MODELING_PT_native_editing"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Spatial"

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "spatial_editing_mode", expand=True)
        layout.label(text="Shared: direct drawing reserves the whole sketch.")
        layout.label(text="Exclusive: direct drawing reserves the document.")
        layout.label(text="Native preview input always reserves the document.")
        layout.label(text="End preview input before another participant edits.")
        layout.label(text="Choose sketch, plane and drawing tool in CAD Sketcher.")
        layout.operator(FrameNativeSketch.bl_idname)
        layout.operator(PreviewContrast.bl_idname)
        layout.label(text="Framing and contrast are view-only; no preferences saved.")
        warning = layout.box()
        warning.label(text="Cooperative editing — strict prevention is unavailable", icon="ERROR")
        warning.label(text="Menu, F3, Outliner and scripts can bypass input gates.")
        warning.label(text="Post-change detection is recovery, not prevention.")
        for lease in host.displayed_leases():
            layout.label(text=f"{lease['owner']['name']} is editing ({lease['mode']})")


CLASSES = (FrameNativeSketch, PreviewContrast, NativeEditingPanel)


def register():
    bpy.types.Scene.spatial_editing_mode = bpy.props.EnumProperty(
        name="Direct drawing ownership", items=(
            ("EXCLUSIVE", "Exclusive", "Reserve the whole document for a direct drawing command"),
            ("SHARED", "Shared", "Reserve the whole sketch, including linked dependencies")),
        default="EXCLUSIVE")
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    global _contrast_handle
    if _contrast_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_contrast_handle, "WINDOW")
        _contrast_handle = None
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.spatial_editing_mode

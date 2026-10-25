"""Pink viewport ownership outlines, names and warnings without saved materials.

Draw handlers are installed only in interactive Blender. All geometry and text
come from current leases on every redraw: releasing a lease removes its mark.
The panel keeps a bypass warning visible because observing a write afterwards
does not establish strict protection.
"""

import blf
import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import gate, host, ownership_state
from . import sync as scene_sync

PINK = (1.0, 0.12, 0.52, 1.0)
EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
         (0, 4), (1, 5), (2, 6), (3, 7))
_handles = []


def source():
    """(leases, own actor, status) for Host or the optional P3 Client interface."""
    addon = bpy.context.preferences.addons.get(__package__)
    if addon is not None and addon.preferences.role == "CLIENT":
        from . import remote_client
        read = getattr(remote_client, "ownership_state", None)
        if read is not None:
            return read()
        state = getattr(remote_client, "state", None)
        return [], None, getattr(state, "status", "Connection lost — edits disabled")
    actor = host._session.host["actor_id"] if host._session is not None else None
    return host.current_leases(), actor, host.status


def _marks():
    """(object, owner names) for current leases. Does not assign IDs while drawing."""
    leases, actor, _ = source()
    objects = {o.get(scene_sync.ID_PROPERTY): o for o in bpy.context.view_layer.objects}
    objects.pop(None, None)
    marks = ownership_state.markers(leases, objects, actor)
    return [(objects[key], names) for key, names in marks.items() if objects[key].visible_get()]


def marked_objects():
    """Current native objects and owner labels."""
    return [(obj, ", ".join(names)) for obj, names in _marks()]


def _corners(obj):
    return [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]


def _draw_lines():
    objects = marked_objects()
    if not objects:
        return
    vertices = [corner for obj, _ in objects for corner in _corners(obj)]
    indices = [(a + i * 8, b + i * 8) for i in range(len(objects)) for a, b in EDGES]
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "LINES", {"pos": vertices}, indices=indices)
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.line_width_set(2.0)
    try:
        shader.bind()
        shader.uniform_float("color", PINK)
        batch.draw(shader)
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")


def _text(text, x, y, color=PINK, size=15):
    blf.position(0, x, y, 0)
    blf.size(0, size)
    blf.color(0, *color)
    blf.draw(0, text)


def _draw_names():
    context = bpy.context
    if context.region is None or context.region_data is None:
        return
    for obj, names in _marks():
        corners = _corners(obj)
        point = sum(corners, Vector()) / 8
        point.z = max(v.z for v in corners)
        screen = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, point)
        if screen is not None:
            _text(ownership_state.object_label(names), screen.x + 6, screen.y + 10)
    held, actor, status = source()
    notice = ownership_state.activity_text(held, actor)
    if notice:
        _text(notice, 20, 76)
    if gate.bypasses:
        _text("Lock bypass detected — verify the reconciled scene", 20, 55,
              (1.0, 0.55, 0.1, 1.0))
    lost = ownership_state.connection_text(status)
    if lost:
        _text(lost, 20, 34, (1.0, 0.55, 0.1, 1.0))


class SPATIAL_MODELING_PT_ownership(bpy.types.Panel):
    bl_label = "Editing and ownership"
    bl_idname = "SPATIAL_MODELING_PT_ownership"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Spatial"

    def draw(self, context):
        layout = self.layout
        held, actor, status = source()
        lost = ownership_state.connection_text(status)
        layout.label(text=lost or status, icon="ERROR" if lost else "NONE")
        notice = ownership_state.activity_text(held, actor)
        if notice:
            layout.label(text=notice, icon="INFO")
        for lease in held:
            scope = "whole document" if lease["mode"] == "exclusive" else (
                f"{len(lease['targets'])} object/sketch targets")
            layout.label(text=f"{lease['owner']['name']}: {scope}")
        if gate.bypasses:
            box = layout.box()
            box.alert = True
            box.label(text="Strict lock bypass detected", icon="ERROR")
            box.label(text="Check the fresh scene with the other editor.")
        layout.label(text="Looking and selecting stay available.")
        layout.label(text="Pink outlines are display only.")


def register():
    bpy.utils.register_class(SPATIAL_MODELING_PT_ownership)
    if not bpy.app.background:
        _handles.extend((
            bpy.types.SpaceView3D.draw_handler_add(_draw_lines, (), "WINDOW", "POST_VIEW"),
            bpy.types.SpaceView3D.draw_handler_add(_draw_names, (), "WINDOW", "POST_PIXEL"),
        ))


def unregister():
    for handle in _handles:
        bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
    _handles.clear()
    bpy.utils.unregister_class(SPATIAL_MODELING_PT_ownership)

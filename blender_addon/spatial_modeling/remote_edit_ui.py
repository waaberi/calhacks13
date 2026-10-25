"""Client-role editing UI (P5-M1-2/3): edits and Undo/Redo go to the host as requests.

The 3D View sidebar's Spatial tab shows a "Host edits" panel in Client role. Each
button sends one request (remote_client.send_edit); the read-only mirror changes
only when the host's scene.update arrives. While connected as a Client, Ctrl+Z and
Ctrl+Shift+Z send history.undo/redo to the host instead of undoing locally. When not
connected, the keys fall through to Blender's own Undo.
"""

import math

import bpy

from . import remote_client
from .remote_client.requests import EditBlocked

_enum_cache = []
_chosen = None  # host object ID picked in the Object field
_keymaps = []


def _prefs(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None else None


def _client(context):
    prefs = _prefs(context)
    return prefs is not None and prefs.role == "CLIENT"


def _connected():
    return remote_client._link is not None


def _targets(_self, _context):
    # Blender stores an enum's number, not its identifier. Numbering by list position
    # would silently switch the chosen object when the host adds, deletes or renames
    # one, so each object's number comes from its ID and stays the same.
    global _enum_cache
    state = remote_client.state
    _enum_cache = [("NONE", "Choose a host object", "", "NONE", 0)]
    if state.current:
        used = {0}
        for oid, record in sorted(state.objects.items(),
                                  key=lambda item: item[1].get("name") or ""):
            number = int(oid[:7], 16) + 1
            while number in used:
                number += 1
            used.add(number)
            _enum_cache.append((oid, record.get("name") or oid[:8], "Host object " + oid,
                                "NONE", number))
    return _enum_cache


def _choose(wm, _context):
    global _chosen
    _chosen = wm.spatial_edit_target  # always a listed item here


def _target(_context):
    # The chosen ID, not the enum: reading an enum whose object has gone logs a warning,
    # and the edit buttons' poll would do that on every redraw.
    record = remote_client.state.objects.get(_chosen) if _chosen else None
    return (_chosen, record.get("name") or _chosen[:8]) if record else (None, None)


def _number(value):
    return f"{value:g}"


class _Edit(bpy.types.Operator):
    """Base: send one request; report why if it can't be sent."""

    needs_target = True

    @classmethod
    def poll(cls, context):
        return _client(context) and remote_client.edit_blocked() is None and (
            not cls.needs_target or _target(context)[0] is not None)

    def request(self, context, target_name):  # returns (op, label, args)
        raise NotImplementedError

    def execute(self, context):
        target_id, target_name = _target(context)
        if self.needs_target and target_id is None:
            self.report({"WARNING"}, "Choose a host object first")
            return {"CANCELLED"}
        op, label, args = self.request(context, target_name)
        try:
            remote_client.send_edit(op, label, args, target_id if self.needs_target else None)
        except EditBlocked as e:
            self.report({"WARNING"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}  # sent; the panel shows the host's answer


class SPATIAL_OT_client_move(_Edit):
    """Ask the host to move the chosen object by this offset"""

    bl_idname = "spatial_modeling.client_move"
    bl_label = "Move"

    def request(self, context, name):
        mm = list(context.window_manager.spatial_edit_move)
        return ("object.move", f"Move {name} by ({', '.join(_number(v) for v in mm)}) mm",
                {"by": [v / 1000 for v in mm]})


class SPATIAL_OT_client_rotate(_Edit):
    """Ask the host to rotate the chosen object about a world axis"""

    bl_idname = "spatial_modeling.client_rotate"
    bl_label = "Rotate"

    def request(self, context, name):
        wm = context.window_manager
        axis, angle = wm.spatial_edit_axis, wm.spatial_edit_angle
        return ("object.rotate", f"Rotate {name} {_number(angle)}° about {axis}",
                {"by": {"axis": axis, "angle": math.radians(angle)}})


class SPATIAL_OT_client_scale(_Edit):
    """Ask the host to scale the chosen object along its own axes"""

    bl_idname = "spatial_modeling.client_scale"
    bl_label = "Scale"

    def request(self, context, name):
        factors = list(context.window_manager.spatial_edit_scale)
        return ("object.scale", f"Scale {name} by ({', '.join(_number(v) for v in factors)})",
                {"by": factors})


class SPATIAL_OT_client_delete(_Edit):
    """Ask the host to delete the chosen object"""

    bl_idname = "spatial_modeling.client_delete"
    bl_label = "Delete"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def request(self, context, name):
        return "object.delete", f"Delete {name}", {}


class SPATIAL_OT_client_add(_Edit):
    """Ask the host to add a primitive at the origin"""

    bl_idname = "spatial_modeling.client_add"
    bl_label = "Add"
    needs_target = False

    def request(self, context, _name):
        wm = context.window_manager
        size = wm.spatial_edit_add_size / 1000
        primitive = wm.spatial_edit_add.lower()
        return ("object.add", f"Add {primitive} ({_number(wm.spatial_edit_add_size)} mm)",
                {"primitive": primitive, "location": [0, 0, size / 2],
                 "dimensions": [size, size, size]})


class _History(_Edit):
    needs_target = False

    @classmethod
    def poll(cls, context):
        # While connected as a Client, always take the key so a local Undo never
        # rewinds the mirror; execute() explains when the request can't be sent.
        return _client(context) and _connected()

    def execute(self, context):
        if remote_client.state.document is None:
            self.report({"WARNING"}, "Waiting for a fresh host scene")
            return {"CANCELLED"}
        return super().execute(context)


class SPATIAL_OT_client_undo(_History):
    """Undo the newest change in the host's shared history"""

    bl_idname = "spatial_modeling.client_undo"
    bl_label = "Undo on host"

    def request(self, context, _name):
        return "history.undo", "Undo on host", {}


class SPATIAL_OT_client_redo(_History):
    """Redo in the host's shared history"""

    bl_idname = "spatial_modeling.client_redo"
    bl_label = "Redo on host"

    def request(self, context, _name):
        return "history.redo", "Redo on host", {}


class SPATIAL_OT_client_checked(bpy.types.Operator):
    """I've checked the fresh host scene; allow new edits again"""

    bl_idname = "spatial_modeling.client_checked"
    bl_label = "I checked the host scene"

    @classmethod
    def poll(cls, _context):
        return remote_client.state.current and any(
            r.state == "unknown" for r in remote_client.requests.requests.values())

    def execute(self, _context):
        remote_client.acknowledge_unknown()
        return {"FINISHED"}


class SPATIAL_PT_client_edits(bpy.types.Panel):
    bl_label = "Host edits"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Spatial"

    @classmethod
    def poll(cls, context):
        return _client(context)

    def draw(self, context):
        layout, wm = self.layout, context.window_manager
        reason = remote_client.edit_blocked()
        if reason:
            layout.label(text=reason, icon="ERROR")
        else:
            layout.label(text="Edits go to the host; this copy updates when it answers.",
                         icon="INFO")
            layout.label(text="Move (G), rotate (R), scale (S) or delete (X) objects directly.",
                         icon="OBJECT_DATA")
        if remote_client.live.error:
            layout.label(text=remote_client.live.error, icon="ERROR")
        if any(r.state == "unknown" for r in remote_client.requests.requests.values()):
            layout.operator(SPATIAL_OT_client_checked.bl_idname, icon="CHECKMARK")

        layout.prop(wm, "spatial_edit_target", text="Object")
        box = layout.box()
        box.prop(wm, "spatial_edit_move", text="Move (mm)")
        box.operator(SPATIAL_OT_client_move.bl_idname)
        row = box.row(align=True)
        row.prop(wm, "spatial_edit_axis", expand=True)
        box.prop(wm, "spatial_edit_angle", text="Angle (°)")
        box.operator(SPATIAL_OT_client_rotate.bl_idname)
        box.prop(wm, "spatial_edit_scale", text="Scale by")
        box.operator(SPATIAL_OT_client_scale.bl_idname)
        box.operator(SPATIAL_OT_client_delete.bl_idname, icon="TRASH")

        box = layout.box()
        row = box.row(align=True)
        row.prop(wm, "spatial_edit_add", text="")
        row.prop(wm, "spatial_edit_add_size", text="Size (mm)")
        box.operator(SPATIAL_OT_client_add.bl_idname, icon="ADD")

        row = layout.row(align=True)
        row.operator(SPATIAL_OT_client_undo.bl_idname, text="Undo", icon="LOOP_BACK")
        row.operator(SPATIAL_OT_client_redo.bl_idname, text="Redo", icon="LOOP_FORWARDS")

        lines = remote_client.requests.lines()
        if lines:
            col = layout.column(align=True)
            col.label(text="Requests (newest first):")
            for label, text, icon in lines:
                col.label(text=f"{label} — {text}", icon=icon)


CLASSES = (SPATIAL_OT_client_move, SPATIAL_OT_client_rotate, SPATIAL_OT_client_scale,
           SPATIAL_OT_client_delete, SPATIAL_OT_client_add, SPATIAL_OT_client_undo,
           SPATIAL_OT_client_redo, SPATIAL_OT_client_checked, SPATIAL_PT_client_edits)

PROPS = {
    "spatial_edit_target": lambda: bpy.props.EnumProperty(items=_targets, update=_choose,
                                                         options={"SKIP_SAVE"}),
    "spatial_edit_move": lambda: bpy.props.FloatVectorProperty(
        size=3, default=(10, 0, 0), soft_min=-1000, soft_max=1000, options={"SKIP_SAVE"}),
    "spatial_edit_axis": lambda: bpy.props.EnumProperty(
        items=[(a, a, f"World {a} axis") for a in "XYZ"], default="Z", options={"SKIP_SAVE"}),
    "spatial_edit_angle": lambda: bpy.props.FloatProperty(
        default=90, min=-360, max=360, options={"SKIP_SAVE"}),
    "spatial_edit_scale": lambda: bpy.props.FloatVectorProperty(
        size=3, default=(1, 1, 1), min=0.001, max=1000, options={"SKIP_SAVE"}),
    "spatial_edit_add": lambda: bpy.props.EnumProperty(
        items=[(p, p, "") for p in ("CUBE", "SPHERE", "CYLINDER")], default="CUBE",
        options={"SKIP_SAVE"}),
    "spatial_edit_add_size": lambda: bpy.props.FloatProperty(
        default=100, min=0.001, max=10000, options={"SKIP_SAVE"}),
}


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for name, make in PROPS.items():
        setattr(bpy.types.WindowManager, name, make())
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is not None:
        keymap = keyconfig.keymaps.new(name="Window", space_type="EMPTY")
        _keymaps.append((keymap, keymap.keymap_items.new(
            SPATIAL_OT_client_undo.bl_idname, "Z", "PRESS", ctrl=True)))
        _keymaps.append((keymap, keymap.keymap_items.new(
            SPATIAL_OT_client_redo.bl_idname, "Z", "PRESS", ctrl=True, shift=True)))


def unregister():
    global _chosen
    _chosen = None
    for keymap, item in _keymaps:
        keymap.keymap_items.remove(item)
    _keymaps.clear()
    for name in PROPS:
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

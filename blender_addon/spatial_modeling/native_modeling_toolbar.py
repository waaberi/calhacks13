"""Selectable native Edit Mode intents with ordinary Blender tool properties.

Selecting a tool only arms its intent. The floating-model controller path reads
the same properties; a click in Blender's native viewport retains native editing.
"""
import math

import bpy

MERGE = "spatial_modeling.merge"
DISSOLVE = "spatial_modeling.dissolve"
DELETE = "spatial_modeling.delete"
OPERATORS = {MERGE: "spatial_modeling.merge_tool", DISSOLVE: "spatial_modeling.dissolve_tool",
             DELETE: "spatial_modeling.delete_tool"}
_registered = False


def _allowed(context, operator):
    from . import host
    if context.mode != "EDIT_MESH" or context.active_object is None:
        operator.report({"ERROR"}, "Choose an active mesh in Blender Edit Mode")
        return False
    if host.may_write(context.objects_in_mode):
        operator.report({"WARNING"}, "Finish the owned VR edit before editing in the Blender view")
        return False
    return True


def _component(context):
    modes = list(context.tool_settings.mesh_select_mode)
    if modes.count(True) != 1:
        raise ValueError("Choose exactly one native vertex, edge or face selection mode")
    return ("vertex", "edge", "face")[modes.index(True)]


class SPATIALMODELING_OT_merge_tool(bpy.types.Operator):
    bl_idname = OPERATORS[MERGE]
    bl_label = "Merge selected"
    bl_description = "Merge the selected vertices; floating controllers use the same armed intent"
    bl_options = {"REGISTER", "UNDO"}  # noqa: RUF012 - Blender's class registration API
    variant: bpy.props.EnumProperty(name="Merge", items=[(v, label, "") for v, label in (
        ("CENTER", "At center"), ("FIRST", "At first"), ("LAST", "At last"),
        ("CURSOR", "At cursor"), ("DISTANCE", "By distance"))], default="CENTER")
    distance: bpy.props.FloatProperty(name="Distance", subtype="DISTANCE", unit="LENGTH", min=0, default=.0001)

    def execute(self, context):
        if not _allowed(context, self):
            return {"CANCELLED"}
        if self.variant == "DISTANCE":
            return bpy.ops.mesh.remove_doubles('EXEC_DEFAULT', False, threshold=self.distance)
        return bpy.ops.mesh.merge('EXEC_DEFAULT', False, type=self.variant)


class SPATIALMODELING_OT_dissolve_tool(bpy.types.Operator):
    bl_idname = OPERATORS[DISSOLVE]
    bl_label = "Dissolve selected"
    bl_description = "Dissolve selected components; floating controllers use the same armed intent"
    bl_options = {"REGISTER", "UNDO"}  # noqa: RUF012 - Blender's class registration API
    variant: bpy.props.EnumProperty(name="Dissolve", items=[("AUTO", "Selected components", ""),
        ("LIMITED", "Limited by angle", "")], default="AUTO")
    angle_limit: bpy.props.FloatProperty(name="Angle", subtype="ANGLE", min=0, max=math.pi, default=math.radians(5))

    def execute(self, context):
        if not _allowed(context, self):
            return {"CANCELLED"}
        if self.variant == "LIMITED":
            return bpy.ops.mesh.dissolve_limited('EXEC_DEFAULT', False, angle_limit=self.angle_limit)
        component = _component(context)
        operation = {"vertex": bpy.ops.mesh.dissolve_verts, "edge": bpy.ops.mesh.dissolve_edges,
                     "face": bpy.ops.mesh.dissolve_faces}[component]
        return operation('EXEC_DEFAULT', False)


class SPATIALMODELING_OT_delete_tool(bpy.types.Operator):
    bl_idname = OPERATORS[DELETE]
    bl_label = "Delete selected"
    bl_description = "Delete selected components; floating controllers use the same armed intent"
    bl_options = {"REGISTER", "UNDO"}  # noqa: RUF012 - Blender's class registration API
    domain: bpy.props.EnumProperty(name="Delete", items=[("AUTO", "Selected component type", ""),
        ("VERTS", "Vertices", ""), ("EDGES", "Edges", ""), ("FACES", "Faces", ""),
        ("ONLY_FACE", "Faces only", "")], default="AUTO")

    def execute(self, context):
        if not _allowed(context, self):
            return {"CANCELLED"}
        domain = self.domain if self.domain != "AUTO" else {"vertex": "VERT", "edge": "EDGE", "face": "FACE"}[_component(context)]
        domain = {"VERTS": "VERT", "EDGES": "EDGE", "FACES": "FACE"}.get(domain, domain)
        return bpy.ops.mesh.delete('EXEC_DEFAULT', False, type=domain)


class SPATIALMODELING_WST_merge(bpy.types.WorkSpaceTool):
    bl_idname = MERGE
    bl_label = "Merge"
    bl_description = "Arm Merge for the floating model, or click the Blender viewport to merge its selection"
    bl_space_type = "VIEW_3D"
    bl_context_mode = "EDIT_MESH"
    bl_icon = "ops.mesh.vertices_smooth"
    bl_widget = None
    bl_keymap = ((OPERATORS[MERGE], {"type": "LEFTMOUSE", "value": "PRESS"}, None),)

    def draw_settings(context, layout, tool):
        properties = tool.operator_properties(OPERATORS[MERGE])
        layout.prop(properties, "variant")
        if properties.variant == "DISTANCE":
            layout.prop(properties, "distance")


class SPATIALMODELING_WST_dissolve(bpy.types.WorkSpaceTool):
    bl_idname = DISSOLVE
    bl_label = "Dissolve"
    bl_description = "Arm Dissolve for the floating model, or click the Blender viewport to dissolve its selection"
    bl_space_type = "VIEW_3D"
    bl_context_mode = "EDIT_MESH"
    bl_icon = "ops.mesh.rip_edge"
    bl_widget = None
    bl_keymap = ((OPERATORS[DISSOLVE], {"type": "LEFTMOUSE", "value": "PRESS"}, None),)

    def draw_settings(context, layout, tool):
        properties = tool.operator_properties(OPERATORS[DISSOLVE])
        layout.prop(properties, "variant")
        if properties.variant == "LIMITED":
            layout.prop(properties, "angle_limit")


class SPATIALMODELING_WST_delete(bpy.types.WorkSpaceTool):
    bl_idname = DELETE
    bl_label = "Delete"
    bl_description = "Arm Delete for the floating model, or click the Blender viewport to delete its selection"
    bl_space_type = "VIEW_3D"
    bl_context_mode = "EDIT_MESH"
    bl_icon = "ops.curves.sculpt_delete"
    bl_widget = None
    bl_keymap = ((OPERATORS[DELETE], {"type": "LEFTMOUSE", "value": "PRESS"}, None),)

    def draw_settings(context, layout, tool):
        layout.prop(tool.operator_properties(OPERATORS[DELETE]), "domain")


CLASSES = (SPATIALMODELING_OT_merge_tool, SPATIALMODELING_OT_dissolve_tool, SPATIALMODELING_OT_delete_tool)
TOOLS = (SPATIALMODELING_WST_merge, SPATIALMODELING_WST_dissolve, SPATIALMODELING_WST_delete)


def register():
    global _registered
    if _registered:
        return
    registered_classes, registered_tools = [], []
    try:
        for cls in CLASSES:
            bpy.utils.register_class(cls)
            registered_classes.append(cls)
        previous = "builtin.knife"
        for tool in TOOLS:
            bpy.utils.register_tool(tool, after={previous}, separator=not registered_tools)
            registered_tools.append(tool)
            previous = tool.bl_idname
    except Exception:
        for tool in reversed(registered_tools):
            bpy.utils.unregister_tool(tool)
        for cls in reversed(registered_classes):
            bpy.utils.unregister_class(cls)
        raise
    _registered = True


def unregister():
    global _registered
    if not _registered:
        return
    # Release an active adapter before unregistering its keymap/classes; never
    # enter Edit Mode or change the user's document merely to unload the add-on.
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is None:
                continue
            with bpy.context.temp_override(window=window, area=area, region=region):
                current = window.workspace.tools.from_space_view3d_mode(bpy.context.mode, create=False)
                if current and current.idname in OPERATORS:
                    bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
    # Inactive mode caches are owned by Blender's tool system. unregister_tool
    # removes their definitions/keymaps; setup on an inactive cached RNA tool
    # is unsafe in Blender. Do not change native mode or touch those handles.
    for tool in reversed(TOOLS):
        bpy.utils.unregister_tool(tool)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _registered = False

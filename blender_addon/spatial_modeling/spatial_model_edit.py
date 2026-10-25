"""Typed native-tool to controller editing. Never evaluates a received operator.

Telemetry reads base-mesh indices, independently of the evaluated display mesh.
One release commits through commands.Editor and its existing authority/Undo path.
All mesh operations are staged on a detached BMesh before touching the document.
"""

import hashlib
import math
import re
import struct

TOOLS = {"builtin.move": "translation", "builtin.rotate": "rotation",
         "builtin.scale": "scale", "builtin.extrude_region": "translation",
         "builtin.extrude_region_move": "translation"}
LIVE_TOOLS = {**TOOLS, "builtin.extrude_individual": "translation",
              "builtin.inset": "thickness_m", "builtin.inset_faces": "thickness_m",
              "builtin.bevel": "width_m", "builtin.loop_cut": "slide",
              "builtin.knife": "path_m", "builtin.select_box": "selection",
              "builtin.select": "selection", "builtin.select_lasso": "selection",
              "spatial_modeling.merge": "merge", "spatial_modeling.dissolve": "dissolve",
              "spatial_modeling.delete": "delete"}
EXTRUDE = {"builtin.extrude_region", "builtin.extrude_region_move"}
MAX_VERTICES = 8192
MAX_EDGES = 16384
MAX_FACES = 8192
MAX_SELECTION = 256
TOKEN = re.compile(r"[0-9a-f]{64}\Z")


def validate_args(args):
    """Pure validation, shared by the command admission path and native editor."""
    required = {"native_tool", "mode", "component", "indices", "topology_token", "delta"}
    if not isinstance(args, dict) or set(args) != required:
        raise ValueError("args must contain native_tool, mode, component, indices, topology_token and delta")
    tool, mode, component = (args[name] for name in ("native_tool", "mode", "component"))
    if not isinstance(tool, str) or tool not in TOOLS:
        raise ValueError("Choose a supported native Move, Rotate, Scale or Extrude Region tool")
    if mode not in ("OBJECT", "EDIT_MESH") or component not in ("object", "vertex", "edge", "face"):
        raise ValueError("Spatial edits support Object Mode or mesh vertex/edge/face Edit Mode")
    if (mode == "OBJECT") != (component == "object"):
        raise ValueError("The component must match the native editing mode")
    if tool in EXTRUDE and (mode != "EDIT_MESH" or component != "face"):
        raise ValueError("Extrude Region requires mesh face selection mode")
    indices = args["indices"]
    if not isinstance(indices, list) or len(indices) > MAX_SELECTION:
        raise ValueError("indices must list at most 256 base-mesh component indices")
    if any(type(i) not in (int, float) or not math.isfinite(i)
           or i != int(i) or not 0 <= i < MAX_EDGES for i in indices):
        raise ValueError("indices must be nonnegative bounded integers")
    if len(set(indices)) != len(indices) or (not indices) != (component == "object"):
        raise ValueError("Object edits have no indices; mesh edits need unique component indices")
    if not isinstance(args["topology_token"], str) or not TOKEN.fullmatch(args["topology_token"]):
        raise ValueError("topology_token must be the latest 64-character native geometry token")
    key = TOOLS[tool]
    delta = args["delta"]
    if not isinstance(delta, dict) or set(delta) != {key}:
        raise ValueError(f"The selected native tool requires only delta.{key}")
    values = delta[key]
    if not isinstance(values, list) or len(values) != (4 if key == "rotation" else 3):
        raise ValueError(f"delta.{key} has the wrong vector size")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("Transform values must be finite numbers")
    if key == "rotation":
        if any(abs(v) > 1.000001 for v in values) or abs(sum(v*v for v in values) - 1) > .002:
            raise ValueError("rotation must be a unit quaternion [w, x, y, z]")
    elif key == "scale":
        if any(not .001 <= abs(v) <= 1000 for v in values):
            raise ValueError("Scale factors must have magnitude .001 to 1000; zero is refused")
    elif any(abs(v) > 1000 for v in values):
        raise ValueError("Translation must be within 1000 meters per axis")


def _tool(context):
    tools = []
    for window in context.window_manager.windows:
        if any(area.type == "VIEW_3D" for area in window.screen.areas):
            tool = window.workspace.tools.from_space_view3d_mode(context.mode, create=False)
            if tool is not None:
                tools.append(tool.idname)
    if len(set(tools)) != 1:
        return "", "Use one native Blender workspace with one active 3D tool."
    return tools[0], ""


def _component(context):
    if context.mode == "OBJECT":
        return "object"
    modes = list(context.tool_settings.mesh_select_mode)
    return ("vertex", "edge", "face")[modes.index(True)] if modes.count(True) == 1 else ""


def _unit(context):
    value = float(f"{context.scene.unit_settings.scale_length:.7g}")
    return value if value > 0 else 1.0


def _index(bm):
    for elements in (bm.verts, bm.edges, bm.faces):
        elements.ensure_lookup_table()
        elements.index_update()


def _ordered_selected_indices(bm, component):
    """Native selection order matters for Merge First/Last and active pivots."""
    values = {"vertex": bm.verts, "edge": bm.edges, "face": bm.faces}[component]
    selected = [element for element in values if element.select and not element.hide]
    selected_set = set(selected)
    history = [element for element in bm.select_history if element in selected_set]
    in_history = set(history)
    # Box/all selections may not create history entries. Preserve every selected
    # element, then append the known ordered clicks with the active element last.
    return [element.index for element in selected if element not in in_history] + [element.index for element in history]


def _selection_history_complete(bm, component):
    values = {"vertex": bm.verts, "edge": bm.edges, "face": bm.faces}[component]
    selected = {element for element in values if element.select and not element.hide}
    return len(selected) >= 2 and selected == {element for element in bm.select_history if element in selected}


def _limits(bm):
    if (len(bm.verts) > MAX_VERTICES or len(bm.edges) > MAX_EDGES
            or len(bm.faces) > MAX_FACES):
        raise ValueError("Direct mesh editing supports at most 8192 vertices, 16384 edges and 8192 faces; use the Blender panel for larger meshes.")
    if sum(len(face.verts) for face in bm.faces) > 65536:
        raise ValueError("This mesh has too many polygon corners for direct component picking; use the Blender panel.")


def _token(context, obj, tool, component, bm=None):
    digest = hashlib.sha256()
    digest.update(f"{tool}:{context.mode}:{component}:{obj.get('spatial_modeling_id', '')}".encode())
    for value in [*[value for row in obj.matrix_world for value in row], _unit(context)]:
        digest.update(struct.pack("!d", value))
    if bm is not None:
        for vertex in bm.verts:
            digest.update(struct.pack("!3d?", *vertex.co, vertex.hide))
        for edge in bm.edges:
            digest.update(struct.pack("!2I?", *(v.index for v in edge.verts), edge.hide))
        for face in bm.faces:
            digest.update(struct.pack("!I?", len(face.verts), face.hide))
            for vertex in face.verts:
                digest.update(struct.pack("!I", vertex.index))
    return digest.hexdigest()


def _editable_mesh(context, obj):
    if obj is None or obj.type != "MESH" or obj != context.active_object:
        raise ValueError("Choose the native active mesh in Blender Edit Mode first.")
    if len(getattr(context, "objects_in_mode", (obj,))) != 1:
        raise ValueError("Direct editing supports one native mesh in Edit Mode at a time.")
    if obj.library is not None or obj.data.library is not None:
        raise ValueError("Linked mesh data cannot be edited here.")
    if obj.data.users != 1:
        raise ValueError("This mesh is shared; make its data single-user in Blender before editing components.")
    if obj.data.shape_keys is not None:
        raise ValueError("Shape-key meshes require the Blender panel so the active key is explicit.")
    if any(mod.show_viewport for mod in obj.modifiers):
        raise ValueError("Disable viewport modifiers before direct mesh editing; evaluated display indices are not base-mesh indices.")
    if abs(obj.matrix_world.determinant()) < 1e-12:
        raise ValueError("The mesh or a parent has a singular transform.")
    _display_transform(obj)


def _display_transform(obj):
    """The existing synchronized world TRS display cannot represent world shear."""
    if any(not math.isfinite(value) for row in obj.matrix_world for value in row):
        raise ValueError("The object transform contains nonfinite coordinates.")
    axes = [obj.matrix_world.col[i].xyz for i in range(3)]
    if any(axis.length < 1e-10 for axis in axes):
        raise ValueError("The object or a parent has a zero or singular scale.")
    if any(abs(axes[i].normalized().dot(axes[j].normalized())) > 1e-5
           for i, j in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("A nonuniformly scaled parent shears this object; use the Blender panel because the floating model cannot represent that shear exactly.")


def _native_options(context, obj, tool, live=False):
    settings = context.tool_settings
    unsupported = []
    for name, label in (("use_snap", "Snapping"),
                        ("use_proportional_edit", "Proportional Editing"),
                        ("use_proportional_edit_objects", "Object Proportional Editing"),
                        ("use_transform_data_origin", "Affect Only Origins"),
                        ("use_transform_skip_children", "Affect Only Parents"),
                        ("use_transform_pivot_point_align", "Affect Only Locations"),
                        ("use_mesh_automerge", "Auto Merge")):
        if getattr(settings, name, False) and not (live and name in (
                "use_snap", "use_proportional_edit", "use_proportional_edit_objects")):
            unsupported.append(label)
    pivot = getattr(settings, "transform_pivot_point", "MEDIAN_POINT")
    if not live and pivot != "MEDIAN_POINT" and (tool != "builtin.move" or tool in EXTRUDE):
        unsupported.append(f"Pivot {pivot}")
    if context.mode == "EDIT_MESH" and any(getattr(obj.data, f"use_mirror_{axis}", False)
                                            for axis in "xyz"):
        unsupported.append("Mesh Mirror Editing")
    locks = {"builtin.move": "lock_location", "builtin.rotate": "lock_rotation",
             "builtin.scale": "lock_scale"}.get(tool)
    if context.mode == "OBJECT" and locks and any(getattr(obj, locks, ())):
        unsupported.append("Locked transform channels")
    if unsupported:
        raise ValueError("Use the Blender panel for these native options, or disable them before direct editing: "
                         + ", ".join(unsupported))


def _options(context, obj, tool):
    """Capture native tool choices; the controller never changes these settings."""
    settings = context.tool_settings
    unit = _unit(context)
    from mathutils import Matrix, Vector
    slot = context.scene.transform_orientation_slots[0]
    orientation = slot.type
    frame = Matrix.Identity(3)
    if slot.custom_orientation is not None:
        orientation = "CUSTOM"
        frame = slot.custom_orientation.matrix.copy()
    elif orientation == "LOCAL":
        frame = obj.matrix_world.to_3x3().normalized()
    elif orientation == "PARENT" and obj.parent is not None:
        frame = obj.parent.matrix_world.to_3x3().normalized()
    elif orientation == "CURSOR":
        frame = context.scene.cursor.matrix.to_3x3().normalized()
    elif orientation == "VIEW":
        area = next((a for w in context.window_manager.windows for a in w.screen.areas if a.type == "VIEW_3D"), None)
        if area is not None:
            frame = area.spaces.active.region_3d.view_matrix.inverted().to_3x3().normalized()
    elif orientation == "NORMAL" and context.mode == "EDIT_MESH":
        import bmesh
        bm = bmesh.from_edit_mesh(obj.data)
        normal = sum((face.normal for face in bm.faces if face.select and not face.hide), Vector())
        if normal.length < 1e-8:
            normal = sum((vert.normal for vert in bm.verts if vert.select and not vert.hide), Vector())
        if normal.length > 1e-8:
            normal = (obj.matrix_world.to_3x3().inverted().transposed() @ normal).normalized()
            frame = normal.to_track_quat('Z', 'Y').to_matrix()
    elif orientation == "GIMBAL":
        if obj.rotation_mode not in ("QUATERNION", "AXIS_ANGLE"):
            # Each Euler derivative axis is measured before its own rotation.
            euler = obj.rotation_euler
            axes = [Vector((1,0,0)),Vector((0,1,0)),Vector((0,0,1))]
            order = obj.rotation_mode
            matrices = {axis: Matrix.Rotation(euler['XYZ'.index(axis)],3,axis) for axis in 'XYZ'}
            accumulated = Matrix.Identity(3)
            for axis in reversed(order):
                i = 'XYZ'.index(axis)
                axes[i] = accumulated @ axes[i]
                accumulated = accumulated @ matrices[axis]
            frame = Matrix(axes).transposed()
            if obj.parent is not None:
                frame = obj.parent.matrix_world.to_3x3().normalized() @ frame
        else:
            frame = obj.matrix_world.to_3x3().normalized()
    result = {"orientation": orientation,
              "orientation_matrix": [v for row in frame for v in row],
              "pivot": settings.transform_pivot_point,
              "constraint_axis": [False, False, False],
              "use_snap": bool(settings.use_snap),
              "snap_elements": sorted(settings.snap_elements),
              "snap_target": settings.snap_target,
              "proportional_falloff": settings.proportional_edit_falloff,
              "connected": bool(settings.use_proportional_connected),
              "projected": bool(settings.use_proportional_projected),
              "proportional_radius_m": 0.0}
    for name in ("use_snap_self", "use_snap_edit", "use_snap_nonedit", "use_snap_selectable",
                 "use_snap_backface_culling", "use_snap_align_rotation", "use_snap_grid_absolute",
                 "use_snap_translate", "use_snap_rotate", "use_snap_scale"):
        if hasattr(settings, name):
            result[name] = bool(getattr(settings, name))
    proportional = settings.use_proportional_edit if context.mode == "EDIT_MESH" else settings.use_proportional_edit_objects
    native_props = None
    for window in context.window_manager.windows:
        native = window.workspace.tools.from_space_view3d_mode(context.mode, create=False)
        if native is None or native.idname != tool:
            continue
        operator = {"builtin.move": "transform.translate", "builtin.rotate": "transform.rotate",
                    "builtin.scale": "transform.resize", "builtin.bevel": "mesh.bevel",
                    "builtin.inset": "mesh.inset", "builtin.inset_faces": "mesh.inset",
                    "builtin.loop_cut": "mesh.loopcut_slide", "builtin.knife": "mesh.knife_tool",
                    "spatial_modeling.merge": "spatial_modeling.merge_tool",
                    "spatial_modeling.dissolve": "spatial_modeling.dissolve_tool",
                    "spatial_modeling.delete": "spatial_modeling.delete_tool"}.get(tool)
        if operator:
            native_props = native.operator_properties(operator)
        break
    if native_props is not None:
        if hasattr(native_props, "constraint_axis"):
            result["constraint_axis"] = list(native_props.constraint_axis)
        if proportional:
            result["proportional_radius_m"] = float(getattr(native_props, "proportional_size", 1.0)) * unit
        for source, target in (("segments", "segments"), ("profile", "profile"),
                               ("use_clamp_overlap", "clamp_overlap"), ("use_individual", "individual"),
                               ("use_even_offset", "even_offset"), ("use_relative_offset", "relative_offset"),
                               ("use_boundary", "boundary"), ("use_outset", "outset"),
                               ("offset_type", "offset_type"), ("affect", "affect"),
                               ("xray", "cut_through"), ("only_selected", "selected_only"),
                               ("angle_snapping", "angle_snapping"), ("angle_snapping_increment", "angle_snapping_increment")):
            if hasattr(native_props, source):
                result[target] = getattr(native_props, source)
        if tool == "builtin.loop_cut" and hasattr(native_props, "MESH_OT_loopcut"):
            result["cuts"] = int(native_props.MESH_OT_loopcut.number_cuts)
        if tool == "spatial_modeling.merge":
            result.update(variant=native_props.variant, distance_m=float(native_props.distance) * unit)
        elif tool == "spatial_modeling.dissolve":
            result.update(variant=native_props.variant, angle_limit=float(native_props.angle_limit))
        elif tool == "spatial_modeling.delete":
            domain = native_props.domain
            result["domain"] = domain if domain != "AUTO" else {"vertex": "VERTS", "edge": "EDGES", "face": "FACES"}.get(_component(context), "FACES")
    elif proportional:
        result["proportional_radius_m"] = unit
    if settings.transform_pivot_point == "CURSOR":
        result["pivot_m"] = list(context.scene.cursor.location * unit)
    elif settings.transform_pivot_point == "ACTIVE_ELEMENT" and obj is not None:
        if context.mode == "EDIT_MESH":
            import bmesh
            from mathutils import Vector
            bm = bmesh.from_edit_mesh(obj.data)
            active = bm.select_history.active
            if active is not None:
                position = active.co if isinstance(active, bmesh.types.BMVert) else sum((v.co for v in active.verts), Vector()) / len(active.verts)
                result["pivot_m"] = list((obj.matrix_world @ position) * unit)
        else:
            result["pivot_m"] = list(obj.matrix_world.translation * unit)
    if settings.use_snap and any(e in settings.snap_elements for e in ("INCREMENT", "GRID")):
        area = next((a for w in context.window_manager.windows for a in w.screen.areas if a.type == "VIEW_3D"), None)
        grid = area.spaces.active.overlay.grid_scale if area is not None else 1.0
        result["snap_increment_m"] = max(grid * unit, .000001)
    from . import modeling_extras
    try:
        result["native_context_fingerprint"] = modeling_extras.context_fingerprint(list(context.visible_objects))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        result["native_context_fingerprint_unavailable"] = str(exc)
    return result


def _snap_geometry(context, sync):
    """Exact evaluated native edge endpoints; render diagonals are not edges."""
    rows, skipped = [], []
    total_vertices = total_edges = 0
    depsgraph = context.evaluated_depsgraph_get()
    for obj in context.visible_objects:
        identity = obj.get("spatial_modeling_id", "")
        if obj.type != "MESH" or not identity:
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = None
        try:
            mesh = evaluated.to_mesh()
            if len(rows) >= 8 or total_vertices + len(mesh.vertices) > 8192 or total_edges + len(mesh.edges) > 16384:
                skipped.append({"id": identity, "reason": "native snap geometry exceeds bounded inspection size"})
                continue
            unit = _unit(context)
            vertices = [{"index": v.index, "position": list((evaluated.matrix_world @ v.co) * unit)} for v in mesh.vertices]
            if any(not math.isfinite(c) or abs(c) > 100000 for v in vertices for c in v["position"]):
                skipped.append({"id": identity, "reason": "native snap coordinates exceed finite bounds"})
                continue
            rows.append({"id": identity, "generation": (sync.generation(identity) or 0) if sync else 0,
                         "selectable": not obj.hide_select,
                         "selected": obj.select_get(), "in_edit_mode": obj.mode == "EDIT",
                         "vertices": vertices, "edges": [{"index": e.index, "vertices": list(e.vertices)} for e in mesh.edges]})
            total_vertices += len(mesh.vertices)
            total_edges += len(mesh.edges)
        finally:
            if mesh is not None:
                evaluated.to_mesh_clear()
    return rows, skipped


def read_state(context, sync=None):
    """Read native toolbar and exact base topology. No scene mutation or ID allocation."""
    state = {"available": False, "reason": "", "native_tool": "", "mode": context.mode,
             "component": "", "active_object_id": "", "generation": 0,
             "topology_token": "", "vertices": [], "edges": [], "faces": [], "triangles": [],
             "live_supported": context.mode in ("OBJECT", "EDIT_MESH"), "tool": "", "settings": {},
             "selection": {"component": "object", "indices": [], "objects": [], "active_id": ""}}
    try:
        tool, reason = _tool(context)
        component = _component(context) if context.mode in ("OBJECT", "EDIT_MESH") else ""
        state.update(native_tool=tool, component=component)
        obj = getattr(context, "active_object", None)
        if obj is None:
            # Selection is authoritative even without an active object. An
            # unavailable edit tool must not look like an omitted selection
            # field and leave a viewer's previous selected target latched.
            selected = {"component": component or "object", "indices": [],
                        "objects": [{"id": o.get("spatial_modeling_id", ""),
                                     "generation": (sync.generation(o.get("spatial_modeling_id", "")) or 0) if sync else 0}
                                    for o in getattr(context, "selected_objects", []) if o.get("spatial_modeling_id", "")],
                        "active_id": ""}
            selected["selection_token"] = hashlib.sha256(repr(selected).encode()).hexdigest()
            state["selection"] = selected
            state["selection_token"] = selected["selection_token"]
        if obj is not None:
            identity = obj.get("spatial_modeling_id", "")
            state["active_object_id"] = identity
            state["generation"] = (sync.generation(identity) or 0) if sync else 0
            state["settings"] = _options(context, obj, tool)
            selected_component = component or "object"
            indices = []
            if context.mode == "EDIT_MESH" and component:
                import bmesh
                bm = bmesh.from_edit_mesh(obj.data)
                _index(bm)
                indices = _ordered_selected_indices(bm, component)
            objects = [{"id": o.get("spatial_modeling_id", ""),
                        "generation": (sync.generation(o.get("spatial_modeling_id", "")) or 0) if sync else 0}
                       for o in context.selected_objects if o.get("spatial_modeling_id", "")]
            selection = {"component": selected_component, "indices": indices,
                         "objects": objects, "active_id": identity}
            if context.mode == "EDIT_MESH" and component:
                selection["order_complete"] = _selection_history_complete(bm, component)
            selection["selection_token"] = hashlib.sha256(repr(selection).encode()).hexdigest()
            state["selection"] = selection
            state["selection_token"] = selection["selection_token"]
            if context.mode not in ("OBJECT", "EDIT_MESH"):
                state["component"] = "object"
                state["topology_token"] = _token(context, obj, tool, "object")
        if reason:
            raise ValueError(reason)
        if tool not in LIVE_TOOLS:
            raise ValueError("Choose a Blender transform, Extrude, Inset, Bevel, Loop Cut, Knife or selection tool for Direct 3D editing.")
        if not component:
            raise ValueError("Use Object Mode or exactly one mesh vertex, edge or face selection mode.")
        if (tool in EXTRUDE or tool == "builtin.extrude_individual") and (context.mode != "EDIT_MESH" or component != "face"):
            raise ValueError("Extrude Region / Individual requires native mesh face selection mode.")
        if tool in ("builtin.inset", "builtin.inset_faces", "builtin.bevel", "builtin.loop_cut", "builtin.knife") and context.mode != "EDIT_MESH":
            raise ValueError("Choose Blender mesh Edit Mode for this mesh tool.")
        obj = context.active_object
        if obj is None:
            raise ValueError("Select an object in the Blender panel first.")
        _display_transform(obj)
        _native_options(context, obj, tool, live=True)
        from . import modeling_tools
        suffix = modeling_tools.NATIVE_TOOLS.get(tool, "selection")
        state["tool"] = ("object." if component == "object" else "mesh.") + suffix
        state["settings"] = _options(context, obj, tool)
        if state["settings"]["use_snap"]:
            state["snap_geometry"], state["snap_geometry_unavailable"] = _snap_geometry(context, sync)
        state["active_object_id"] = obj.get("spatial_modeling_id", "")
        if sync is not None:
            state["generation"] = sync.generation(state["active_object_id"]) or 0
        if context.mode == "EDIT_MESH":
            import bmesh
            _editable_mesh(context, obj)
            bm = bmesh.from_edit_mesh(obj.data)
            _index(bm)
            _limits(bm)
            unit = _unit(context)
            state["vertices"] = [{"index": v.index,
                                   "position": list((obj.matrix_world @ v.co) * unit)}
                                  for v in bm.verts if not v.hide]
            if any(not math.isfinite(value) or abs(value) > 100_000
                   for vertex in state["vertices"] for value in vertex["position"]):
                raise ValueError("The native mesh contains nonfinite or out-of-bounds world coordinates.")
            state["edges"] = [{"index": e.index, "vertices": [v.index for v in e.verts]}
                               for e in bm.edges if not e.hide]
            state["faces"] = [{"index": f.index, "vertices": [v.index for v in f.verts]}
                               for f in bm.faces if not f.hide]
            state["triangles"] = [{"face": tri[0].face.index,
                                    "vertices": [loop.vert.index for loop in tri]}
                                   for tri in bm.calc_loop_triangles() if not tri[0].face.hide]
            state["topology_token"] = _token(context, obj, tool, component, bm)
            indices = _ordered_selected_indices(bm, component)
        else:
            state["topology_token"] = _token(context, obj, tool, component)
            indices = []
        objects = [{"id": o.get("spatial_modeling_id", ""),
                    "generation": (sync.generation(o.get("spatial_modeling_id", "")) or 0) if sync else 0}
                   for o in context.selected_objects if o.get("spatial_modeling_id", "")]
        if context.mode == "EDIT_MESH":
            objects = [{"id": state["active_object_id"], "generation": state["generation"]}]
        selection = {"component": component, "indices": indices, "objects": objects,
                     "active_id": state["active_object_id"]}
        if context.mode == "EDIT_MESH":
            selection["order_complete"] = _selection_history_complete(bm, component)
        selection["selection_token"] = hashlib.sha256(repr(selection).encode()).hexdigest()
        state["selection"] = selection
        state["selection_token"] = selection["selection_token"]
        if tool == "spatial_modeling.merge":
            if component != "vertex":
                raise ValueError("Merge requires native vertex selection mode.")
            if state["settings"].get("variant") in ("FIRST", "LAST") and not _selection_history_complete(bm, component):
                raise ValueError("Merge First/Last needs ordered vertex picks. Select vertices individually, then hold to merge; box/all selection has no first or last.")
        state["available"] = True
    except (AttributeError, ReferenceError, RuntimeError, ValueError) as exc:
        state["reason"] = str(exc)
    return state


def _check_context(editor, obj, args):
    import bpy

    from .commands import Refused
    from .preview_spatial import modal_operators
    if modal_operators(bpy.context):
        raise Refused("failed", "Finish or cancel the native Blender modal operation before direct editing.")
    state = read_state(bpy.context, editor.sync)
    if not state["available"]:
        raise Refused("failed", state["reason"])
    if any(state[name] != args[name] for name in ("native_tool", "mode", "component", "topology_token")):
        raise Refused("stale_revision", "The native tool, mode or mesh changed during the gesture. Select again and retry.")
    if args["mode"] == "EDIT_MESH" and obj != bpy.context.active_object:
        raise Refused("failed", "Only the active native Edit Mode mesh can receive component edits.")


def apply(editor, obj, args):
    """Called inside Editor's normal command transaction; no extra Undo wrapper."""
    from .commands import Refused
    try:
        validate_args(args)
    except ValueError as exc:
        raise Refused("failed", str(exc)) from exc
    _check_context(editor, obj, args)
    try:
        _display_transform(obj)
        import bpy
        _native_options(bpy.context, obj, args["native_tool"])
    except ValueError as exc:
        raise Refused("failed", str(exc)) from exc
    if args["mode"] == "OBJECT":
        import bpy
        tool, delta = args["native_tool"], args["delta"]
        if tool == "builtin.move":
            done = editor._move(obj, {"by": delta["translation"]})
        elif tool == "builtin.rotate":
            done = _rotate_delta(obj, delta["rotation"])
        else:
            done = editor._scale(obj, {"by": delta["scale"]})
        bpy.context.view_layer.update()
        done.selection = {"id": editor.sync.object_id(obj)}
        return done
    return _mesh_apply(editor, obj, args)


def _rotate_delta(obj, values):
    """Apply a world turn without interpreting a reflected matrix as a rotation.

    Stripping the actual signed native scale preserves mirror channels. Parent
    nonuniformity can make the proposed channel matrix nonorthogonal; the normal
    exact readback then refuses and restores it instead of approximating shear.
    """
    from mathutils import Matrix, Quaternion

    from . import edits
    from .commands import Applied, Refused

    edits._check_transformable(obj)
    turn = Quaternion(values)
    if abs(turn.magnitude - 1) > .001:
        raise Refused("failed", "The controller rotation must be a unit quaternion.")
    turn.normalize()
    old = edits._world(obj)
    expected = turn.to_matrix().to_4x4() @ old.to_3x3().to_4x4()
    expected.translation = old.translation
    saved = edits._channels(obj)
    channel = edits._rotation(obj).to_matrix()
    signed_scale = [obj.scale[i] * obj.delta_scale[i] for i in range(3)]
    if any(abs(value) < 1e-10 for value in signed_scale):
        raise Refused("failed", "The object has a singular signed scale.")
    before = old.to_3x3() @ Matrix.Diagonal([1 / value for value in signed_scale]) @ channel.inverted()
    desired = before.inverted() @ turn.to_matrix() @ before @ channel
    edits._set_rotation(obj, desired.to_quaternion().normalized())
    edits._confirm(obj, expected, saved, "rotate")
    return Applied(f"Direct rotate {obj.name}")


def _mesh_apply(editor, obj, args):
    import bmesh
    import bpy
    from mathutils import Quaternion, Vector

    from .commands import Applied, Refused

    live = bmesh.from_edit_mesh(obj.data)
    _index(live)
    stage = live.copy()
    _index(stage)
    backup = bpy.data.meshes.new("__spatial_edit_rollback")
    pending = bpy.data.meshes.new("__spatial_edit_stage")
    history = [(type(element).__name__, element.index) for element in live.select_history]
    active_face = live.faces.active.index if live.faces.active is not None else None
    changed = False
    try:
        stage.to_mesh(backup)
        elements = {"vertex": stage.verts, "edge": stage.edges, "face": stage.faces}[args["component"]]
        indices = [int(i) for i in args["indices"]]
        if any(i >= len(elements) or elements[i].hide for i in indices):
            raise ValueError("A picked native component no longer exists or is hidden.")
        picked = [elements[i] for i in indices]
        vertices = set(picked if args["component"] == "vertex" else
                       (v for element in picked for v in element.verts))
        tool, delta = args["native_tool"], args["delta"]
        unit, world = _unit(bpy.context), obj.matrix_world.copy()
        inverse = world.inverted()
        if tool in EXTRUDE:
            # The native region kernel removes internal selected faces and keeps
            # material/custom data. No viewport-dependent executable operator.
            source_edges = {edge for face in picked for edge in face.edges}
            source_vertices = set(vertices)
            result = bmesh.ops.extrude_face_region(stage, geom=picked, use_keep_orig=False)
            vertices = {v for v in result["geom"] if isinstance(v, bmesh.types.BMVert)}
            if not vertices:
                raise ValueError("Blender could not extrude that face region.")
            # The standalone face-only BMesh kernel retains the source cap even
            # with use_keep_orig=False. Remove it just as a region extrusion
            # replaces the original surface; otherwise a closed cube acquires
            # an internal face and nonmanifold boundary edges. Remove only
            # newly-unused geometry from this source region, never other data.
            retained_caps = [face for face in picked if face.is_valid]
            if retained_caps:
                bmesh.ops.delete(stage, geom=retained_caps, context="FACES_ONLY")
            unused_edges = [edge for edge in source_edges if edge.is_valid and not edge.link_faces]
            if unused_edges:
                bmesh.ops.delete(stage, geom=unused_edges, context="EDGES")
            unused_vertices = [vertex for vertex in source_vertices
                               if vertex.is_valid and not vertex.link_edges]
            if unused_vertices:
                bmesh.ops.delete(stage, geom=unused_vertices, context="VERTS")
        if tool in ("builtin.move", *EXTRUDE):
            offset = inverse.to_3x3() @ (Vector(delta["translation"]) / unit)
            for vertex in vertices:
                vertex.co += offset
        elif tool == "builtin.rotate":
            pivot = sum((world @ v.co for v in vertices), Vector()) / len(vertices)
            rotation = Quaternion(delta["rotation"]).normalized()
            for vertex in vertices:
                vertex.co = inverse @ (pivot + rotation @ ((world @ vertex.co) - pivot))
        else:
            pivot = sum((v.co for v in vertices), Vector()) / len(vertices)
            factors = delta["scale"]
            for vertex in vertices:
                vertex.co = pivot + Vector([(vertex.co[i] - pivot[i]) * factors[i] for i in range(3)])
        _index(stage)
        _limits(stage)
        for vertex in stage.verts:
            position = (world @ vertex.co) * unit
            if any(not math.isfinite(v) or abs(v) > 100_000 for v in position):
                raise ValueError("The edit would put geometry outside the supported world bounds.")
        stage.normal_update()
        if _token(bpy.context, obj, tool, args["component"], stage) == args["topology_token"]:
            raise ValueError("The gesture did not change the mesh.")
        stage.to_mesh(pending)
        # Only now touch the native mesh. The backup includes material indices,
        # UV/custom layers and native component selection, not just positions.
        changed = True
        live.clear()
        live.from_mesh(pending)
        _index(live)
        _restore_history(live, history, active_face)
        bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
        obj.update_from_editmode()
        bpy.context.view_layer.update()
        actual = bmesh.from_edit_mesh(obj.data)
        _index(actual)
        if _token(bpy.context, obj, tool, args["component"], actual) != _token(bpy.context, obj, tool, args["component"], stage):
            raise ValueError("Blender did not retain the exact staged mesh edit.")
        return Applied(f"Direct {tool.removeprefix('builtin.')} {obj.name} {args['component']}",
                       selection={"id": editor.sync.object_id(obj)})
    except Exception as exc:
        if changed:
            live = bmesh.from_edit_mesh(obj.data)
            live.clear()
            live.from_mesh(backup)
            _index(live)
            _restore_history(live, history, active_face)
            bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
            obj.update_from_editmode()
            bpy.context.view_layer.update()
        if isinstance(exc, Refused):
            raise
        raise Refused("failed", f"Direct mesh edit refused; nothing changed. {exc}") from exc
    finally:
        stage.free()
        bpy.data.meshes.remove(backup)
        bpy.data.meshes.remove(pending)


def _restore_history(bm, history, active_face):
    collections = {"BMVert": bm.verts, "BMEdge": bm.edges, "BMFace": bm.faces}
    bm.select_history.clear()
    for kind, index in history:
        elements = collections.get(kind)
        if elements is not None and index < len(elements) and elements[index].select:
            bm.select_history.add(elements[index])
    if active_face is not None and active_face < len(bm.faces):
        bm.faces.active = bm.faces[active_face]

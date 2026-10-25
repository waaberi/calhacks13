"""One typed native modeling executor for reviewed recipes and live gestures."""

import copy
import math
import uuid
from contextlib import contextmanager

from . import tool_catalog

NATIVE_TOOLS = {
    "builtin.move": "translate", "builtin.rotate": "rotate", "builtin.scale": "scale",
    "builtin.extrude_region": "extrude", "builtin.extrude_region_move": "extrude",
    "builtin.extrude_individual": "extrude", "builtin.inset": "inset", "builtin.inset_faces": "inset",
    "builtin.bevel": "bevel", "builtin.loop_cut": "loop_cut", "builtin.knife": "knife",
    "spatial_modeling.merge": "merge", "spatial_modeling.dissolve": "dissolve", "spatial_modeling.delete": "delete",
}


def validate_step(tool, params, component=None):
    result = tool_catalog.validate(tool, params, component)
    if tool == "mesh.extrude" and result.get("individual", False) and "normal_distance_m" in result and _extrude_transform(result):
        raise ValueError("Individual-normal extrusion needs a separate snapped/constrained transform")
    return result


def _identity(editor, obj):
    identity = obj.get("spatial_modeling_id", "")
    if identity:
        return identity
    stage = getattr(editor.sync, "stage_object_id", None)
    return stage(obj) if stage is not None else editor.sync.object_id(obj)


def _normalize(operation, parameters):
    if not isinstance(operation, dict) or not isinstance(parameters, dict):
        raise ValueError("Live edits need a typed operation and cumulative parameters")  # noqa: TRY004
    tool = operation.get("tool", "")
    component = operation.get("selection", {}).get("component", operation.get("component", "object"))
    if tool in NATIVE_TOOLS:
        tool = NATIVE_TOOLS[tool]
    if "." not in tool:
        tool = ("object." if component == "object" else "mesh.") + tool
    params = copy.deepcopy(parameters.get("delta", parameters))
    aliases = {"translation": "translation_m", "thickness": "thickness_m", "depth": "depth_m",
               "offset": "width_m", "amount_m": "width_m", "number_cuts": "cuts", "factor": "slide",
               "path": "path_m"}
    for old, new in aliases.items():
        if old in params:
            params[new] = params.pop(old)
    if tool == "mesh.loop_cut":
        params.pop("edge_index", None)
    return tool, component, params


def validate_live(operation, parameters):
    parameters = copy.deepcopy(parameters)
    branches = parameters.pop("per_target", None)
    tool, component, params = _normalize(operation, parameters)
    selection = operation.get("selection", {"component": component, "indices": operation.get("indices", [])})
    indices = selection.get("indices", []) if isinstance(selection, dict) else None
    if (not isinstance(indices, list) or len(indices) > 16384 or
            any(type(i) not in (int, float) or not math.isfinite(i) or int(i) != i or i < 0 or i >= 16384 for i in indices)
            or len(set(indices)) != len(indices)):
        raise ValueError("Selection needs unique bounded native component indices")
    if component != "object" and not indices and tool != "mesh.selection":
        raise ValueError("Choose native components before starting this tool")
    if branches is not None:
        targets = operation.get("targets") or [operation.get("target_id")]
        ids = [target.get("id") if isinstance(target, dict) else target for target in targets]
        if not isinstance(branches, dict) or set(branches) != set(ids):
            raise ValueError("Per-target parameters must cover exactly the admitted objects")
        for branch in branches.values():
            validate_step(tool, branch, component)
        if not params:
            return branches
    return validate_step(tool, params, component)


def apply_live(editor, operation, parameters):
    from .commands import Applied
    parameters = copy.deepcopy(parameters)
    branches = parameters.pop("per_target", None)
    tool, component, params = _normalize(operation, parameters)
    selection = operation.get("selection") or {"component": component, "indices": operation.get("indices", [])}
    settings = operation.get("settings", {})
    params = _settings_params(tool, params, settings)
    targets = operation.get("targets") or [operation.get("target_id")]
    if not isinstance(targets, list) or not targets or len(targets) > 256:
        raise ValueError("Live editing needs captured native targets")
    results = []
    if tool == "object.selection":
        import bpy
        selected_ids = operation.get("selection", {}).get("objects", targets)
        selected_ids = [row.get("id") if isinstance(row, dict) else row for row in selected_ids]
        admitted = [row.get("id") if isinstance(row, dict) else row for row in targets]
        if set(selected_ids) - set(admitted):
            raise ValueError("Object selection must stay within the admitted targets")
        for item in bpy.context.view_layer.objects:
            item.select_set(item.get("spatial_modeling_id", "") in selected_ids)
        active_id = operation.get("selection", {}).get("active_id", selected_ids[-1] if selected_ids else "")
        bpy.context.view_layer.objects.active = editor.sync.find_object(active_id) if active_id else None
        return Applied("Native selection", selection={"id": active_id, "objects": selected_ids,
                                                       "component": "object", "indices": []})
    for target in targets:
        identity = target.get("id") if isinstance(target, dict) else target
        obj = editor.sync.find_object(identity)
        if obj is None:
            raise ValueError("The live target no longer exists")
        branch = _settings_params(tool, branches[identity], settings) if branches is not None else params
        results.append(apply_step(editor, obj, tool, branch, selection))
    selected = results[-1]["selection"]
    selected["objects"] = [r["selection"]["id"] for r in results]
    return Applied(f"{tool} {len(results)} target(s)", selection=selected)


def _settings_params(tool, params, settings):
    params = copy.deepcopy(params)
    if tool.rsplit(".", 1)[-1] in ("translate", "rotate", "scale", "extrude"):
        for key in ("orientation", "orientation_matrix", "constraint_axis", "pivot_m", "proportional_radius_m",
                    "proportional_falloff", "connected", "projected", "snap_increment_m", "snap_point_m", "snap_target"):
            if key not in params and key in settings:
                params[key] = settings[key]
    if tool == "mesh.extrude" and "individual" not in params and "individual" in settings:
        params["individual"] = settings["individual"]
    return params


def _extrude_transform(params):
    return (any(params.get("constraint_axis", [])) or params.get("proportional_radius_m", 0) > 0
            or any(key in params for key in ("snap_increment_m", "snap_point_m"))
            or params.get("snap_align_rotation", False))


@contextmanager
def native_context(obj, selected_objects=None):
    import bpy
    found = None
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                if region:
                    found = {"window": window, "area": area, "region": region}
                    break
        if found:
            break
    if found is None:
        raise ValueError("Open an existing Blender 3D View for this native tool")
    selected_objects = selected_objects or [obj]
    found.update(object=obj, active_object=obj, selected_objects=selected_objects,
                 selected_editable_objects=selected_objects)
    with bpy.context.temp_override(**found):
        yield


def _unit():
    import bpy
    return max(float(bpy.context.scene.unit_settings.scale_length), 1e-12)


@contextmanager
def _frozen_orientation(matrix):
    """Use Blender's native arbitrary-axis transform without leaving a UI preset."""
    import bpy
    slot = bpy.context.scene.transform_orientation_slots[0]
    before = slot.type
    name = "Spatial_" + uuid.uuid4().hex
    created = False
    try:
        status = bpy.ops.transform.create_orientation('EXEC_DEFAULT', False, name=name, use=False, overwrite=False)
        if status != {'FINISHED'}:
            raise ValueError("The native transform frame could not be created")
        created = True
        slot.type = name
        slot.custom_orientation.matrix = matrix
        yield name
    finally:
        if created:
            slot.type = name
            bpy.ops.transform.delete_orientation('EXEC_DEFAULT', False)
        slot.type = before


def _select_components(obj, selection):
    import bmesh

    from . import modeling_mesh
    bm = bmesh.from_edit_mesh(obj.data)
    if selection.get("indices") == []:
        modeling_mesh._clear_selection(bm)
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        return {"component": selection.get("component", "vertex"), "indices": []}
    domain, picked = modeling_mesh.elements(bm, selection)
    result = modeling_mesh.select(bm, domain, picked)
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return result


def _transform(editor, obj, tool, params, selection):
    import bpy
    from mathutils import Quaternion, Vector

    from . import spatial_model_edit
    domain = selection.get("component", "object")
    if domain == "object" and not any(k in params for k in ("pivot_m", "constraint_axis", "proportional_radius_m", "snap_point_m", "snap_increment_m")):
        if tool.endswith("translate"):
            editor._move(obj, {"by": params["translation_m"]})
        elif tool.endswith("rotate"):
            spatial_model_edit._rotate_delta(obj, params["rotation"])
        else:
            editor._scale(obj, {"by": params["scale"]})
        return selection
    if domain != "object":
        _select_components(obj, selection)
    args = {"orient_type": params.get("orientation", "GLOBAL"),
            "constraint_axis": tuple(params.get("constraint_axis", [False, False, False]))}
    radius = params.get("proportional_radius_m", 0)
    args.update(use_proportional_edit=radius > 0,
                proportional_size=max(radius / _unit(), .000011),
                proportional_edit_falloff=params.get("proportional_falloff", "SMOOTH"),
                use_proportional_connected=params.get("connected", False),
                use_proportional_projected=params.get("projected", False))
    if "pivot_m" in params and not tool.endswith("translate"):
        args["center_override"] = tuple(v / _unit() for v in params["pivot_m"])
    with native_context(obj):
        if tool.endswith("translate"):
            value = Vector(params["translation_m"])
            if "snap_increment_m" in params:
                step = params["snap_increment_m"]
                value = Vector([round(v / step) * step for v in value])
            if "snap_point_m" in params:
                if domain == "object":
                    origin = obj.matrix_world.translation * _unit()
                else:
                    import bmesh

                    from . import modeling_mesh
                    bm = bmesh.from_edit_mesh(obj.data)
                    _, picked = modeling_mesh.elements(bm, selection)
                    verts = set(picked if domain == "vertex" else (v for e in picked for v in e.verts))
                    origin = sum(((obj.matrix_world @ v.co) * _unit() for v in verts), Vector()) / len(verts)
                value = Vector(params["snap_point_m"]) - origin
            constraints = params.get("constraint_axis", [False, False, False])
            if any(constraints):
                if "orientation_matrix" in params:
                    from mathutils import Matrix
                    values = params["orientation_matrix"]
                    frame = Matrix([values[i:i+3] for i in range(0, 9, 3)])
                    local = frame.inverted() @ value
                    value = frame @ Vector([v if enabled else 0 for v, enabled in zip(local, constraints)])
                elif params.get("orientation", "GLOBAL") == "LOCAL":
                    axes = [obj.matrix_world.col[i].xyz.normalized() for i in range(3)]
                    value = sum((axis * value.dot(axis) for axis, enabled in zip(axes, constraints) if enabled), Vector())
                else:
                    value = Vector([v if enabled else 0 for v, enabled in zip(value, constraints)])
                # EXEC_DEFAULT consumes an already projected world displacement;
                # axis flags alone only constrain Blender's modal mouse mapping.
                args["constraint_axis"] = (False, False, False)
                args["orient_type"] = 'GLOBAL'
            if params.get("snap_align_rotation", False):
                args.update(snap=True, snap_elements={'FACE'}, snap_target=params.get("snap_target", "CLOSEST"),
                            snap_align=True, snap_normal=tuple(Vector(params["snap_normal"]).normalized()))
                if "snap_point_m" in params:
                    args["snap_point"] = tuple(v / _unit() for v in params["snap_point_m"])
            status = bpy.ops.transform.translate('EXEC_DEFAULT', False, value=tuple(value / _unit()), **args)
        elif tool.endswith("rotate"):
            quaternion = Quaternion(params["rotation"]).normalized()
            axis, angle = quaternion.to_axis_angle()
            # Axis-angle is a world rotation; native proportional/pivot semantics apply.
            orient = axis.to_track_quat('Z', 'Y').to_matrix()
            args.pop("orient_type", None)
            args.pop("constraint_axis", None)
            with _frozen_orientation(orient) as orientation:
                status = bpy.ops.transform.rotate('EXEC_DEFAULT', False, value=angle, orient_axis='Z',
                                                  orient_type=orientation, constraint_axis=(False, False, True), **args)
        else:
            status = bpy.ops.transform.resize('EXEC_DEFAULT', False, value=tuple(params["scale"]), **args)
    if status != {'FINISHED'}:
        raise ValueError("The native transform did not finish")
    bpy.context.view_layer.update()
    if tool.endswith("translate") and params.get("snap_align_rotation", False):
        destination = Vector(params["snap_normal"]).normalized()
        if domain == "object":
            normal = (obj.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
            if any(obj.lock_rotation):
                raise ValueError("Unlock native rotation channels before enabling snap alignment")
            spatial_model_edit._rotate_delta(obj, list(normal.rotation_difference(destination)))
        else:
            import bmesh

            from . import modeling_mesh
            bm = bmesh.from_edit_mesh(obj.data)
            _, picked = modeling_mesh.elements(bm, selection)
            vertices = set(picked if domain == "vertex" else (v for e in picked for v in e.verts))
            normal = sum((e.normal for e in picked), Vector()) if domain == "face" else sum((v.normal for v in vertices), Vector())
            normal = obj.matrix_world.to_3x3().inverted().transposed() @ normal
            if normal.length < 1e-8:
                raise ValueError("The selected geometry has no stable normal for snap alignment")
            pivot = sum(((obj.matrix_world @ v.co) * _unit() for v in vertices), Vector()) / len(vertices)
            rotate = {key: params[key] for key in ("proportional_radius_m", "proportional_falloff", "connected", "projected") if key in params}
            rotate.update(rotation=list(normal.normalized().rotation_difference(destination)), pivot_m=list(pivot))
            _transform(editor, obj, 'mesh.rotate', rotate, selection)
        bpy.context.view_layer.update()
    return selection


def _mesh(obj, tool, params, selection):
    import bmesh
    import bpy

    from . import modeling_mesh, spatial_model_edit
    spatial_model_edit._editable_mesh(bpy.context, obj)
    live = bmesh.from_edit_mesh(obj.data)
    stage = live.copy()
    backup = bpy.data.meshes.new("__spatial_modeling_backup")
    pending = bpy.data.meshes.new("__spatial_modeling_pending")
    changed = False
    try:
        live.to_mesh(backup)
        result = modeling_mesh.apply(stage, obj, tool, params, selection, _unit())
        stage.to_mesh(pending)
        changed = True
        live.clear()
        live.from_mesh(pending)
        modeling_mesh.index(live)
        # Result indices belong to the final detached topology, never the old picks.
        for output in result["outputs"].values():
            if isinstance(output, dict):
                output["id"] = obj.get("spatial_modeling_id", "")
        result["selection"]["id"] = obj.get("spatial_modeling_id", "")
        bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
        obj.update_from_editmode()
        bpy.context.view_layer.update()
        actual = bmesh.from_edit_mesh(obj.data)
        modeling_mesh.index(actual)
        if (len(actual.verts), len(actual.edges), len(actual.faces)) != (len(stage.verts), len(stage.edges), len(stage.faces)):
            raise ValueError("Native topology readback differs from the staged edit")
        if any((a.co - b.co).length > 1e-7 for a, b in zip(actual.verts, stage.verts)):
            raise ValueError("Native position readback differs from the staged edit")
        return result
    except Exception:
        if changed:
            live.clear()
            live.from_mesh(backup)
            bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
            obj.update_from_editmode()
        raise
    finally:
        stage.free()
        bpy.data.meshes.remove(backup)
        bpy.data.meshes.remove(pending)


def _object(editor, obj, tool, params):
    import bpy
    from mathutils import Vector
    unit = _unit()
    if tool == "object.add":
        done = editor._add(None, params, stage=True)
        return editor.sync.find_object(done.created[0]["id"] if isinstance(done.created[0], dict) else done.created[0])
    if obj is None or obj.library is not None:
        raise ValueError("Choose an editable local native object")
    if tool == "object.rename":
        obj.name = params["name"]
    elif tool == "object.duplicate":
        created = obj.copy()
        if obj.data is not None and not params.get("linked", False):
            created.data = obj.data.copy()
        if "spatial_modeling_id" in created:
            del created["spatial_modeling_id"]
        (obj.users_collection[0] if obj.users_collection else bpy.context.collection).objects.link(created)
        matrix = created.matrix_world.copy()
        matrix.translation += Vector(params.get("translation_m", [0, 0, 0])) / unit
        created.matrix_world = matrix
        _identity(editor, created)
        obj = created
    elif tool == "object.shade":
        if obj.type != "MESH":
            raise ValueError("Face shading requires a mesh")
        for face in obj.data.polygons:
            face.use_smooth = params["smooth"]
    elif tool == "object.parent":
        parent = editor.sync.find_object(params["parent_id"])
        if parent is None:
            raise ValueError("Choose an existing parent without a dependency cycle")
        cursor = parent
        while cursor is not None:
            if cursor == obj:
                raise ValueError("Choose an existing parent without a dependency cycle")
            cursor = cursor.parent
        world = obj.matrix_world.copy()
        obj.parent = parent
        if params.get("keep_transform", True):
            obj.matrix_world = world
    elif tool == "object.unparent":
        world = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = world
    elif tool == "object.visibility":
        obj.hide_set(not params["visible"])
        if "render" in params:
            obj.hide_render = not params["render"]
    elif tool == "object.delete":
        editor._delete(obj, {})
        return None
    elif tool == "modifier.add":
        if obj.type != "MESH":
            raise ValueError("This modifier needs a mesh")
        modifier = obj.modifiers.new(params["kind"].replace('_', ' ').title(), params["kind"])
        kind = params["kind"]
        if kind == "BEVEL":
            modifier.width = params.get("amount_m", .002) / unit
            modifier.segments = int(params.get("segments", 1))
        elif kind == "SOLIDIFY":
            modifier.thickness = params.get("amount_m", .002) / unit
        elif kind == "SUBSURF":
            modifier.levels = int(params.get("levels", 1))
        elif kind == "ARRAY":
            modifier.count = int(params.get("count", 2))
        elif kind == "DECIMATE":
            modifier.ratio = params.get("ratio", .5)
        elif kind == "MIRROR":
            modifier.use_axis = tuple(a == params.get("axis", "X") for a in "XYZ")
        elif kind == "WELD":
            modifier.merge_threshold = params.get("amount_m", .0001) / unit
    elif tool in ("modifier.remove", "modifier.apply"):
        modifier = obj.modifiers.get(params["name"])
        if modifier is None:
            raise ValueError("That modifier does not exist")
        if tool == "modifier.remove":
            obj.modifiers.remove(modifier)
        else:
            with native_context(obj):
                status = bpy.ops.object.modifier_apply('EXEC_DEFAULT', False, modifier=modifier.name)
            if status != {'FINISHED'}:
                raise ValueError("The native modifier did not apply")
    elif tool == "material.assign":
        if not hasattr(obj.data, "materials"):
            raise ValueError("This object has no native material slots")
        material = bpy.data.materials.get(params["name"])
        if material is not None and any(key in params for key in ("colour", "roughness", "metallic")):
            material = material.copy()
        if material is None:
            material = bpy.data.materials.new(params["name"])
        if "colour" in params:
            material.diffuse_color = params["colour"]
        if "roughness" in params:
            material.roughness = params["roughness"]
        if "metallic" in params:
            material.metallic = params["metallic"]
        if material.name not in obj.data.materials:
            obj.data.materials.append(material)
        obj.active_material_index = list(obj.data.materials).index(material)
    elif tool in ("uv.layer_add", "uv.layer_remove"):
        if obj.type != "MESH":
            raise ValueError("UV layers need a native mesh")
        if tool == "uv.layer_add":
            obj.data.uv_layers.new(name=params["name"])
        else:
            layer = obj.data.uv_layers.get(params["name"])
            if layer is None:
                raise ValueError("That UV layer does not exist")
            obj.data.uv_layers.remove(layer)
    elif tool in ("object.apply_transform", "object.origin"):
        with native_context(obj):
            if tool == "object.apply_transform":
                status = bpy.ops.object.transform_apply('EXEC_DEFAULT', False, location=params.get("location", False),
                        rotation=params.get("rotation", True), scale=params.get("scale", True), isolate_users=True)
            else:
                status = bpy.ops.object.origin_set('EXEC_DEFAULT', False, type='ORIGIN_'+params["kind"], center='MEDIAN')
        if status != {'FINISHED'}:
            raise ValueError("The native object operation did not finish")
    elif tool.startswith("animation."):
        if tool == "animation.frame":
            bpy.context.scene.frame_set(int(params["frame"]))
        else:
            animation = obj.animation_data
            if animation is not None and getattr(animation, "use_tweak_mode", False):
                raise ValueError("Finish the native NLA tweak session before this keyframe edit")
            if animation is not None and animation.action is not None:
                slot = getattr(animation, "action_slot", None)
                identifier = slot.identifier if slot is not None else None
                animation.action = animation.action.copy()
                if identifier is not None:
                    slot = next((s for s in animation.action.slots if s.identifier == identifier), None)
                    if slot is not None:
                        animation.action_slot = slot
            if tool == "animation.keyframe":
                obj.keyframe_insert(data_path=params["channel"], frame=params["frame"])
            elif not obj.keyframe_delete(data_path=params["channel"], frame=params["frame"]):
                raise ValueError("No matching keyframe exists")
    else:
        raise ValueError(f"No native executor for {tool}")
    bpy.context.view_layer.update()
    return obj


def apply_step(editor, target, tool, params, selection=None, outputs=None):
    import bpy
    if isinstance(target, str):
        target = editor.sync.find_object(target)
    selection = copy.deepcopy(selection or {"component": "object", "indices": []})
    params = validate_step(tool, params, selection.get("component", "object"))
    expected_modes = tool_catalog.descriptor(tool)["modes"]
    if bpy.context.mode not in expected_modes:
        raise ValueError(f"{tool} requires {'/'.join(expected_modes)}; choose that mode in Blender")
    from . import modeling_extras
    if tool in modeling_extras.OPERATIONS:
        return modeling_extras.apply_step(editor, target, tool, params, selection, outputs)
    if tool in ("mesh.selection", "object.selection"):
        if tool == "mesh.selection":
            result_selection = _select_components(target, selection)
        else:
            for item in bpy.context.view_layer.objects:
                item.select_set(item == target)
            bpy.context.view_layer.objects.active = target
            result_selection = selection
        result_selection["id"] = _identity(editor, target)
        return {"selection": result_selection, "outputs": {"selection": result_selection}}
    if tool.rsplit(".", 1)[-1] in ("translate", "rotate", "scale"):
        result_selection = _transform(editor, target, tool, params, selection)
        result_selection["id"] = _identity(editor, target)
        return {"selection": result_selection, "outputs": {"selection": result_selection, "object": {"id": result_selection["id"]}}}
    if tool == "mesh.knife":
        from . import modeling_knife
        return modeling_knife.apply(editor, target, params, selection)
    if tool == "mesh.extrude" and _extrude_transform(params):
        if params.get("individual", False) and "normal_distance_m" in params:
            raise ValueError("Individual-normal extrusion cannot combine a single snapped/constrained displacement; use Region or a separate transform")
        topology = copy.deepcopy(params)
        topology["translation_m"] = [0, 0, 0]
        result = _mesh(target, tool, topology, selection)
        _transform(editor, target, "mesh.translate", params, result["selection"])
        return result
    if tool.startswith("mesh."):
        return _mesh(target, tool, params, selection)
    if tool in ("uv.unwrap", "uv.smart_project", "uv.transform"):
        _select_components(target, selection)
        if tool == "uv.transform":
            import bmesh
            from mathutils import Matrix, Vector

            from . import modeling_mesh
            bm = bmesh.from_edit_mesh(target.data)
            _, faces = modeling_mesh.elements(bm, selection)
            uv = bm.loops.layers.uv.active
            if uv is None:
                raise ValueError("Create or choose a UV layer in Blender first")
            offset = Vector(params.get("translation", [0, 0]))
            scale = Vector(params.get("scale", [1, 1]))
            rotation = Matrix.Rotation(params.get("rotation", 0), 2)
            loops = [loop for face in faces for loop in face.loops]
            pivot = sum((loop[uv].uv for loop in loops), Vector((0, 0))) / len(loops)
            for loop in loops:
                point = loop[uv].uv - pivot
                loop[uv].uv = pivot + rotation @ Vector((point.x*scale.x, point.y*scale.y)) + offset
            bmesh.update_edit_mesh(target.data, loop_triangles=False, destructive=False)
        else:
            with native_context(target):
                status = (bpy.ops.uv.unwrap('EXEC_DEFAULT', False, method=params.get("method", "ANGLE_BASED"), margin=params.get("margin", .001))
                          if tool == "uv.unwrap" else bpy.ops.uv.smart_project('EXEC_DEFAULT', False,
                          angle_limit=params.get("angle_limit", 1.15192), island_margin=params.get("island_margin", .02)))
            if status != {'FINISHED'}:
                raise ValueError("The native UV operation did not finish")
        selection["id"] = _identity(editor, target)
        return {"selection": selection, "outputs": {"selection": selection}}
    obj = _object(editor, target, tool, params)
    selected = {"id": _identity(editor, obj), "component": "object", "indices": []} if obj else {}
    return {"selection": selected, "outputs": {"object": selected, "selection": selected}}


def stage_recipe(editor, compiled_steps, context):
    """Validate geometry recipes on detached meshes before presenting a plan."""
    import bmesh
    import bpy

    from . import modeling_mesh
    stages, results, summary, virtual, deferred = {}, {}, [], set(), []
    try:
        for step in compiled_steps:
            tool = step["tool"]
            target = step["target"]
            if isinstance(target, dict):
                target = results[target["step"]][target.get("output", "object")].get("id")
            obj = editor.sync.find_object(target) if target not in virtual else None
            selection = copy.deepcopy(step.get("selection") or context.get("selection", {}))
            if "step" in selection:
                selection = copy.deepcopy(results[selection["step"]][selection["output"]])
            component = selection.get("component", "object")
            params = validate_step(tool, step.get("params", {}), component)
            if bpy.context.mode not in tool_catalog.descriptor(tool)["modes"]:
                raise ValueError(f"{tool} is unavailable in the captured native mode")
            from . import modeling_extras
            if tool in modeling_extras.OPERATIONS:
                if target not in virtual and not selection.get("deferred"):
                    modeling_extras.preflight(editor, obj, tool, params, selection)
                results[step["id"]] = {"object": {"id": target}, "selection": selection}
                deferred.append(step["id"])
            elif tool == "object.add":
                target = "pending_" + step["id"]
                virtual.add(target)
                results[step["id"]] = {"object": {"id": target},
                                       "selection": {"id": target, "component": "object", "indices": []}}
            elif tool.startswith("mesh.") and tool not in ("mesh.translate", "mesh.rotate", "mesh.scale", "mesh.knife", "mesh.selection") and not selection.get("deferred") and not (tool == "mesh.extrude" and _extrude_transform(params)):
                if obj is None:
                    raise ValueError("The selected native mesh no longer exists")
                if target not in stages:
                    stages[target] = bmesh.from_edit_mesh(obj.data).copy()
                result = modeling_mesh.apply(stages[target], obj, tool, params, selection, _unit())
                for value in result["outputs"].values():
                    value["id"] = target
                results[step["id"]] = result["outputs"]
            else:
                if obj is None and target not in virtual:
                    raise ValueError("The native target no longer exists")
                if tool == "mesh.knife":
                    from . import modeling_knife
                    modeling_knife._view(params["projection"], params["path_m"], _unit())
                results[step["id"]] = {"object": {"id": target}, "selection": selection}
                for output in tool_catalog.descriptor(tool)["outputs"]:
                    if output in results[step["id"]]:
                        continue
                    domain = "face" if "faces" in output else "edge" if "edges" in output else "vertex" if "vertices" in output else component
                    results[step["id"]][output] = {"id": target, "component": domain, "deferred": True}
                if tool == "object.duplicate":
                    new_target = "pending_" + step["id"]
                    virtual.add(new_target)
                    results[step["id"]]["object"] = {"id": new_target}
                if tool.startswith(("mesh.", "uv.")):
                    deferred.append(step["id"])
            summary.append(tool.replace('.', ' '))
        return {"summary": "; then ".join(summary),
                "preview": {"deferred_native_preview_steps": deferred,
                            "mesh_counts": {key: {"vertices": len(bm.verts), "edges": len(bm.edges), "faces": len(bm.faces)} for key, bm in stages.items()}}}
    finally:
        for bm in stages.values():
            bm.free()

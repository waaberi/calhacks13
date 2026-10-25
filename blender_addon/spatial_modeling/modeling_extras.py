"""Native finishing operations with bounded targets and recipe rollback support.

The caller owns authority, document generations and the single native Undo
boundary. This module neither opens a document nor changes the user's mode.
"""

import copy
import hashlib
import json

from . import tool_catalog_extras as catalog

OPERATIONS = catalog.OPERATIONS
_IK_TAG = "spatial_modeling_ik"
_BIND_TAG = "spatial_modeling_armature_modifier"
_IK_FIELDS = ("chain_count", "influence", "iterations", "use_stretch", "use_rotation")
_MOD_FIELDS = {
    'BEVEL': {'width_m': ('width', 'length'), 'segments': ('segments', 'int'), 'profile': ('profile', None)},
    'SUBSURF': {'levels': ('levels', 'int'), 'render_levels': ('render_levels', 'int')},
    'SOLIDIFY': {'thickness_m': ('thickness', 'length'), 'offset': ('offset', None), 'rim': ('use_rim', None)},
    'ARRAY': {'count': ('count', 'int'), 'relative_offset': ('relative_offset_displace', None)},
    'DECIMATE': {'ratio': ('ratio', None)},
    'MIRROR': {'merge_distance_m': ('merge_threshold', 'length'), 'clipping': ('use_clip', None)},
    'WELD': {'merge_distance_m': ('merge_threshold', 'length')},
    'SMOOTH': {'factor': ('factor', None), 'iterations': ('iterations', 'int')},
    'SIMPLE_DEFORM': {'method': ('deform_method', None), 'axis': ('deform_axis', None),
                      'factor': ('factor', None), 'angle': ('angle', None)},
    'CAST': {'factor': ('factor', None)},
    'DISPLACE': {'amount_m': ('strength', 'length')},
    'EDGE_SPLIT': {'split_angle': ('split_angle', None)},
}


def validate_step(tool, params, component=None):
    return catalog.validate(tool, params, component)


def _unit():
    import bpy
    value = float(bpy.context.scene.unit_settings.scale_length)
    if not 1e-9 <= value <= 10000:
        raise ValueError("Native scene units are outside finite bounds")
    return value


def _identity(editor, obj):
    return (obj.get("spatial_modeling_id")
            or getattr(editor.sync, "stage_object_id", editor.sync.object_id)(obj))


def _local(obj, kind=None):
    if obj is None or obj.library or obj.override_library:
        raise ValueError("Choose a local editable native object")
    if kind and obj.type != kind:
        raise ValueError("This operation needs a native " + kind.lower())
    if obj.data and (obj.data.library or obj.data.override_library or obj.data.users != 1):
        raise ValueError("Make the target's data local and single-user before this edit")
    if obj.type == "MESH" and (obj.data.shape_keys or len(obj.data.vertices) > 16384):
        raise ValueError("This edit needs a bounded base mesh without shape keys")
    return obj


def _collection(name):
    import bpy
    collection = bpy.data.collections.get(name)
    if collection is None or collection.library or collection.override_library:
        raise ValueError("Choose an existing local collection")
    pending = [bpy.context.scene.collection]
    seen = set()
    while pending:
        current = pending.pop()
        if current == collection:
            return collection
        if current.as_pointer() not in seen:
            seen.add(current.as_pointer())
            pending.extend(current.children)
    raise ValueError("The collection is outside the current native scene")


def _bone(rig, name):
    _local(rig, 'ARMATURE')
    if len(rig.data.bones) > 64:
        raise ValueError('This rig exceeds the bounded native pose size')
    bone = rig.pose.bones.get(name)
    if bone is None or bone.bone.hide or getattr(bone, 'hide', False):
        raise ValueError('Choose an exact visible native bone')
    if bone.bone.hide_select or (bone.bone.collections and not any(c.is_visible_effectively for c in bone.bone.collections)):
        raise ValueError('The native bone is hidden or locked against selection')
    if rig.animation_data and rig.animation_data.drivers:
        raise ValueError('Driven rigs require their native driver workflow')
    return bone


def _owned_ik(rig):
    value = rig.get(_IK_TAG)
    constraints = [(bone, c) for bone in rig.pose.bones for c in bone.constraints]
    if value is None:
        if constraints:
            raise ValueError('Existing foreign bone constraints must remain in their native workflow')
        return None
    try:
        value = json.loads(value)
    except (TypeError, ValueError) as error:
        raise ValueError('The native IK ownership record is invalid') from error
    if not isinstance(value, dict) or set(value) != {'bone', 'name', 'target_id'} or len(constraints) != 1:
        raise ValueError('The native IK constraint structure changed')
    bone, constraint = constraints[0]
    if (bone.name != value['bone'] or constraint.name != value['name'] or constraint.type != 'IK'
            or not constraint.target or constraint.target.get('spatial_modeling_id') != value['target_id']):
        raise ValueError('The exact native IK association changed')
    return bone, constraint, value


def _rig_target(editor, rig, identity):
    target = editor.sync.find_object(identity)
    if target is None or target == rig or target.library or rig in _ancestors(target):
        raise ValueError('Choose an independent local IK target')
    if (any(getattr(m, 'object', None) == rig for m in target.modifiers)
            or any(getattr(c, 'target', None) == rig for c in target.constraints)):
        raise ValueError('The IK target depends on the rig and would create a native dependency cycle')
    return target


def _ancestors(obj):
    result = []
    current = obj.parent
    while current is not None and current not in result:
        result.append(current)
        current = current.parent
    return result


def _action_curves(action):
    seen = set()
    groups = []
    if hasattr(action, 'fcurves'):
        groups.append(action.fcurves)
    for layer in action.layers:
        for strip in layer.strips:
            groups.extend(bag.fcurves for bag in getattr(strip, 'channelbags', ()))
    for group in groups:
        for curve in group:
            if curve.as_pointer() not in seen:
                seen.add(curve.as_pointer())
                yield curve


def _bind_action(obj, action, slot_identifier=None):
    animation = obj.animation_data_create()
    animation.action = action
    if action is not None and slot_identifier:
        slot = next((s for s in action.slots if s.identifier == slot_identifier), None)
        if slot is not None:
            animation.action_slot = slot


def _private_action(obj):
    animation = obj.animation_data_create()
    if animation.action is not None:
        slot = animation.action_slot.identifier if animation.action_slot else None
        action = animation.action.copy()
        action.use_fake_user = False
        _bind_action(obj, action, slot)


def _selection_vertices(obj, selection):
    import bpy
    if bpy.context.mode == "EDIT_MESH":
        import bmesh

        from . import modeling_mesh
        bm = bmesh.from_edit_mesh(obj.data)
        domain, picked = modeling_mesh.elements(bm, selection)
        return bm, list(picked if domain == "vertex" else {v for e in picked for v in e.verts})
    indices = selection.get("indices", [])
    if selection.get("component") != "vertex" or not indices or len(indices) > 256 or len(set(indices)) != len(indices):
        raise ValueError("Choose exact native vertices")
    if any(type(i) not in (int, float) or int(i) != i or not 0 <= i < len(obj.data.vertices) for i in indices):
        raise ValueError("A selected native vertex no longer exists")
    vertices = [obj.data.vertices[int(i)] for i in indices]
    if any(v.hide for v in vertices):
        raise ValueError("Hidden vertices cannot be edited")
    return None, vertices


def preflight(editor, target, tool, params, selection=None, outputs=None):
    """Read-only admission usable before any recipe prefix is executed."""
    import bpy
    if isinstance(target, str):
        target = editor.sync.find_object(target)
    selection = selection or {"component": "object", "indices": []}
    params = catalog.validate(tool, params, selection.get("component", "object"))
    if bpy.context.mode not in catalog.descriptor(tool)["modes"]:
        raise ValueError(tool + " requires " + "/".join(catalog.descriptor(tool)["modes"]))
    _local(target)
    if tool.startswith(("uv.", "vertex_group.", "weights.", "mesh.")):
        _local(target, "MESH")
    if tool.startswith("curve."):
        _local(target, "CURVE")
        if len(target.data.splines) > 128 or sum(len(s.points) + len(s.bezier_points) for s in target.data.splines) > 4096:
            raise ValueError("Curve exceeds bounded editable point count")
    if tool.startswith(('camera.', 'light.', 'text.')):
        _local(target, {'camera': 'CAMERA', 'light': 'LIGHT', 'text': 'FONT'}[tool.split('.')[0]])
    if tool == 'camera.settings':
        start = params.get('clip_start_m', target.data.clip_start * _unit())
        end = params.get('clip_end_m', target.data.clip_end * _unit())
        if start >= end:
            raise ValueError('The camera near clip must precede its far clip')
    if tool == 'light.settings':
        kind = params.get('kind', target.data.type)
        allowed = {'radius_m': {'POINT', 'SPOT'}, 'spot_angle': {'SPOT'},
                   'spot_blend': {'SPOT'}, 'area_size_m': {'AREA'}}
        if any(key in params and kind not in kinds for key, kinds in allowed.items()):
            raise ValueError('Those light properties do not apply to the requested light type')
    if tool.startswith('modifier.'):
        _local(target, 'MESH')
        if tool == 'modifier.boolean':
            operand = editor.sync.find_object(params['operand_id'])
            if operand is None or operand == target or operand.type != 'MESH' or operand.hide_get():
                raise ValueError('Choose a different visible native mesh operand')
            if (target in _ancestors(operand)
                    or any(getattr(m, 'object', None) == target for m in operand.modifiers)
                    or any(getattr(c, 'target', None) == target for c in operand.constraints)):
                raise ValueError('The Boolean operand depends on its target')
            if len(target.modifiers) >= 64:
                raise ValueError('This object already has 64 native modifiers')
        elif tool == 'modifier.configure':
            modifier = target.modifiers.get(params['name'])
            if modifier is None or modifier.type not in _MOD_FIELDS:
                raise ValueError('Choose an existing supported native modifier')
            if set(params) - {'name'} - set(_MOD_FIELDS[modifier.type]):
                raise ValueError('Those parameters do not belong to this modifier kind')
        elif len(target.modifiers) >= 64:
            raise ValueError('This object already has 64 native modifiers')
        else:
            allowed = {'SIMPLE_DEFORM': {'method', 'axis', 'factor', 'angle'}, 'CAST': {'factor'},
                       'DISPLACE': {'amount_m'}, 'EDGE_SPLIT': {'angle'}}[params['kind']]
            if set(params) - {'kind'} - allowed:
                raise ValueError('Those parameters do not belong to this deform modifier')
    if tool.startswith(('rig.', 'animation.pose_')):
        if tool in ('rig.bind_armature', 'rig.unbind_armature'):
            _local(target, 'MESH')
            if tool == 'rig.bind_armature':
                rig = editor.sync.find_object(params['rig_id'])
                _local(rig, 'ARMATURE')
                if rig == target or target in _ancestors(rig) or any(m.type == 'ARMATURE' for m in target.modifiers):
                    raise ValueError('Binding needs an independent rig and no existing armature modifier')
                if not any(group.name in rig.data.bones for group in target.vertex_groups):
                    raise ValueError('Create exact bone-named vertex groups and weights before binding')
            else:
                name = target.get(_BIND_TAG, '')
                modifier = target.modifiers.get(name)
                if modifier is None or modifier.type != 'ARMATURE':
                    raise ValueError('This object has no owned armature binding')
        else:
            bone = _bone(target, params['bone'])
            if bpy.context.mode == 'POSE' and (bpy.context.object != target or len(bpy.context.objects_in_mode) != 1):
                raise ValueError('Use the existing active single native Pose rig')
            if tool.startswith('rig.pose_') and bone.constraints:
                raise ValueError('Pose this constrained bone through its native constraint workflow')
            if tool.startswith('rig.pose_'):
                reset = tool == 'rig.pose_reset'
                if ((reset or 'location_m' in params) and any(bone.lock_location)
                        or (reset or 'rotation' in params) and (any(bone.lock_rotation) or bone.lock_rotation_w and bone.lock_rotations_4d)
                        or (reset or 'scale' in params) and any(bone.lock_scale)):
                    raise ValueError('The requested pose channels are locked in Blender')
            if 'rotation' in params and abs(sum(v * v for v in params['rotation']) - 1) > .002:
                raise ValueError('The pose quaternion must be normalized [w,x,y,z]')
            if 'scale' in params and any(abs(v) < .001 for v in params['scale']):
                raise ValueError('Pose scale cannot be zero or nearly singular')
            if tool.startswith('rig.ik_'):
                existing = _owned_ik(target)
                if tool == 'rig.ik_add' and existing:
                    raise ValueError('Update or remove the existing owned IK before adding another')
                if tool != 'rig.ik_add' and (existing is None or existing[0] != bone):
                    raise ValueError('Choose the exact bone with the existing owned IK')
                if 'target_id' in params:
                    _rig_target(editor, target, params['target_id'])
    if tool.startswith('animation.'):
        if target.animation_data and target.animation_data.drivers:
            raise ValueError('Driven animation remains in its native driver workflow')
        if target.animation_data and target.animation_data.nla_tracks:
            raise ValueError('NLA animation remains in its native track workflow')
        action = target.animation_data.action if target.animation_data else None
        if action and (action.library or action.override_library):
            raise ValueError('Make the native action local before editing its keys')
        if tool == 'animation.interpolation' and (action is None or not any(c.data_path == params['channel'] for c in _action_curves(action))):
            raise ValueError('That native channel has no keyframes')
        if tool == 'animation.frame_range' and params['start'] > params['end']:
            raise ValueError('The animation range start must not exceed its end')
    if bpy.context.mode == "EDIT_MESH":
        from . import spatial_model_edit
        spatial_model_edit._editable_mesh(bpy.context, target)
    if tool.startswith("uv."):
        if tool not in ("uv.layer_copy", "uv.layer_activate"):
            import bmesh

            from . import modeling_mesh
            bm = bmesh.from_edit_mesh(target.data)
            modeling_mesh.elements(bm, selection)
            if bm.loops.layers.uv.active is None:
                raise ValueError("Choose an existing active UV layer in Blender")
        elif tool == "uv.layer_copy" and target.data.uv_layers.active is None:
            raise ValueError("Choose a UV layer to copy")
        elif tool == "uv.layer_activate" and target.data.uv_layers.get(params["name"]) is None:
            raise ValueError("That UV layer does not exist")
        if tool == "uv.layer_copy" and (len(target.data.uv_layers) >= 8 or target.data.uv_layers.get(params["name"])):
            raise ValueError("Use a new UV layer name with fewer than eight layers")
    if tool.startswith(("vertex_group.", "weights.")):
        group = target.vertex_groups.get(params.get("name", ""))
        if tool == "vertex_group.create":
            if group or len(target.vertex_groups) >= 64:
                raise ValueError("Use a new vertex group name with fewer than 64 groups")
        elif tool != "weights.normalize" and group is None:
            raise ValueError("That vertex group does not exist")
        if tool == "vertex_group.rename" and target.vertex_groups.get(params["new_name"]):
            raise ValueError("The new vertex group name is already used")
        if tool.startswith("weights."):
            _selection_vertices(target, selection)
            if group is not None and group.lock_weight:
                raise ValueError("The chosen vertex group is locked")
    if tool.startswith("material."):
        if target.data is None or not hasattr(target.data, "materials"):
            raise ValueError("This object has no native material slots")
        if tool == "material.slot_remove" and params["index"] >= len(target.data.materials):
            raise ValueError("The material slot no longer exists")
        if tool == "material.principled" and len(target.data.materials) >= 64 and not target.active_material:
            raise ValueError("This object already has 64 material slots")
    if tool.startswith(("collection.", "object.collection_")):
        if tool == "collection.create":
            if bpy.data.collections.get(params["name"]) or len(bpy.data.collections) >= 256:
                raise ValueError("Use a new collection name with fewer than 256 collections")
        else:
            collection = _collection(params["name"])
            if tool == "collection.rename" and bpy.data.collections.get(params["new_name"]):
                raise ValueError("The new collection name is already used")
            if tool == "object.collection_unlink" and (target.name not in collection.objects or len(target.users_collection) <= 1):
                raise ValueError("Unlink needs a current membership and must keep another collection")
    if tool == "curve.point_set" or tool == "curve.spline_remove":
        if params["spline"] >= len(target.data.splines):
            raise ValueError("The native spline no longer exists")
        spline = target.data.splines[int(params["spline"])]
        if tool == "curve.point_set" and params["point"] >= len(spline.bezier_points if spline.type == "BEZIER" else spline.points):
            raise ValueError("The native spline point no longer exists")
    if tool == "curve.spline_add" and (len(target.data.splines) >= 128 or sum(len(s.points) + len(s.bezier_points) for s in target.data.splines) + len(params["points_m"]) > 4096):
        raise ValueError("Adding these points would exceed the native curve bounds")
    if tool == "mesh.project_surface":
        surface = editor.sync.find_object(params["surface_id"])
        if surface is None or surface == target or surface.type != "MESH" or surface.hide_get():
            raise ValueError("Choose a different visible native mesh surface")
        if abs(surface.matrix_world.determinant()) < 1e-12 or abs(target.matrix_world.determinant()) < 1e-12:
            raise ValueError("Surface projection requires nonsingular native transforms")
    if tool.startswith("mesh."):
        _selection_vertices(target, selection)
        if tool == 'mesh.flatten' and sum(v * v for v in params['normal']) < 1e-12:
            raise ValueError('Flatten needs a nonzero world plane normal')
        if tool == 'mesh.solidify' and abs(params['thickness_m']) < 1e-8:
            raise ValueError('Solidify needs a nonzero metric thickness')
        if tool == 'mesh.symmetrize':
            import bmesh
            bm = bmesh.from_edit_mesh(target.data)
            if len(selection['indices']) != len(bm.verts) or any(v.hide for v in bm.verts):
                raise ValueError('Symmetrize requires deliberately selecting all vertices of the visible native mesh')
    return params


def _uv(obj, tool, params, selection):
    import bmesh
    import bpy

    from . import modeling_mesh, modeling_tools
    bm = bmesh.from_edit_mesh(obj.data)
    domain, faces = modeling_mesh.elements(bm, selection)
    uv = bm.loops.layers.uv.active
    if tool == "uv.pin":
        for face in faces:
            for loop in face.loops:
                loop[uv].pin_uv = params["pinned"]
    elif tool == "uv.weld":
        from mathutils import Vector
        vertices = {}
        for face in faces:
            for loop in face.loops:
                vertices.setdefault(loop.vert, []).append(loop)
        changes = []
        for loops in vertices.values():
            remaining = set(loops)
            while remaining:
                seed = min(remaining, key=lambda l: (l.face.index, l.vert.index))
                cluster, pending = {seed}, [seed]
                while pending:
                    point = pending.pop()[uv].uv
                    for candidate in remaining - cluster:
                        if (candidate[uv].uv - point).length <= params['limit']:
                            cluster.add(candidate)
                            pending.append(candidate)
                remaining -= cluster
                ordered = sorted(cluster, key=lambda l: (l.face.index, l.vert.index))
                pins = [loop[uv].uv.copy() for loop in ordered if loop[uv].pin_uv]
                if pins and any(tuple(p) != tuple(pins[0]) for p in pins):
                    raise ValueError('Pinned UV endpoints disagree; unpin deliberately before welding')
                destination = (pins[0] if pins else sum((l[uv].uv for l in ordered), Vector((0, 0))) / len(ordered)
                               if params.get('midpoint', True) else ordered[0][uv].uv.copy())
                changes.extend((loop, destination.copy()) for loop in ordered)
        for loop, destination in changes:
            loop[uv].uv = destination
    elif tool == "uv.select_island":
        expanded, pending = set(faces), list(faces)
        while pending:
            face = pending.pop()
            for loop in face.loops:
                edge = loop.edge
                if edge.seam or len(edge.link_faces) != 2:
                    continue
                other = next(f for f in edge.link_faces if f != face)
                if other.hide or other in expanded:
                    continue
                counterpart = next(l for l in other.loops if l.edge == edge)
                left = {loop.vert: tuple(loop[uv].uv), loop.link_loop_next.vert: tuple(loop.link_loop_next[uv].uv)}
                right = {counterpart.vert: tuple(counterpart[uv].uv), counterpart.link_loop_next.vert: tuple(counterpart.link_loop_next[uv].uv)}
                if left == right:
                    expanded.add(other)
                    pending.append(other)
        result = modeling_mesh.select(bm, domain, sorted(expanded, key=lambda f: f.index))
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        return result
    else:
        modeling_mesh.select(bm, domain, faces)
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        settings = bpy.context.scene.tool_settings
        sync = settings.use_uv_select_sync
        try:
            settings.use_uv_select_sync = True
            with modeling_tools.native_context(obj):
                if tool == "uv.pack":
                    status = bpy.ops.uv.pack_islands('EXEC_DEFAULT', False, rotate=params.get("rotate", True),
                                                    margin_method='FRACTION', margin=params["margin"])
                else:
                    status = bpy.ops.uv.average_islands_scale('EXEC_DEFAULT', False)
            if status != {'FINISHED'}:
                raise ValueError("The native UV operation did not finish")
        finally:
            settings.use_uv_select_sync = sync
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return selection


def _weight_maps(obj, bm):
    if bm is not None:
        layer = bm.verts.layers.deform.active
        return {index: dict(v[layer]) if layer else {} for index, v in enumerate(bm.verts)}
    return {v.index: {g.group: g.weight for g in v.groups} for v in obj.data.vertices}


def _write_weight(obj, bm, index, group, value):
    if bm is not None:
        layer = bm.verts.layers.deform.verify()
        weights = bm.verts[index][layer]
        if value > 0:
            weights[group] = value
        elif group in weights:
            del weights[group]
    elif value > 0:
        obj.vertex_groups[group].add([index], value, 'REPLACE')
    else:
        try:
            obj.vertex_groups[group].remove([index])
        except RuntimeError:
            pass


def _weights(obj, tool, params, selection):
    import bmesh
    bm, vertices = _selection_vertices(obj, selection)
    old = _weight_maps(obj, bm)
    group = obj.vertex_groups.get(params.get("name", ""))
    if tool == "weights.normalize":
        changes = []
        for vert in vertices:
            values = old[vert.index]
            locked = sum(v for g, v in values.items() if obj.vertex_groups[g].lock_weight)
            if locked > 1 + 1e-6:
                raise ValueError("Locked weights exceed one; normalization would alter locked groups")
            unlocked = {g: v for g, v in values.items() if not obj.vertex_groups[g].lock_weight}
            total = sum(unlocked.values())
            if total:
                changes.extend((vert.index, g, v * max(0, 1 - locked) / total) for g, v in unlocked.items())
    elif tool == "weights.smooth":
        adjacency = {i: set() for i in old}
        edges = bm.edges if bm is not None else obj.data.edges
        for edge in edges:
            a, b = (v.index for v in edge.verts) if bm is not None else edge.vertices
            adjacency[a].add(b)
            adjacency[b].add(a)
        weights = {i: values.get(group.index, 0) for i, values in old.items()}
        for _ in range(int(params["iterations"])):
            updated = dict(weights)
            for vert in vertices:
                neighbours = adjacency[vert.index]
                if neighbours:
                    mean = sum(weights[i] for i in neighbours) / len(neighbours)
                    updated[vert.index] += params["factor"] * (mean - weights[vert.index])
            weights = updated
        changes = [(v.index, group.index, weights[v.index]) for v in vertices]
    else:
        changes = []
        for vert in vertices:
            value = old[vert.index].get(group.index, 0)
            mode = params.get("mode", "REPLACE")
            weight = params.get("weight", 0)
            value = 0 if tool == "weights.remove" else min(1, value + weight) if mode == "ADD" else max(0, value - weight) if mode == "SUBTRACT" else weight
            changes.append((vert.index, group.index, value))
    for index, group_index, value in changes:
        _write_weight(obj, bm, index, group_index, value)
    if bm is not None:
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        obj.update_from_editmode()
    else:
        obj.data.update()


def _principled(obj, params):
    import bpy
    existing = obj.active_material
    material = existing.copy() if existing is not None else bpy.data.materials.new(params.get("name", "Material"))
    if "name" in params:
        material.name = params["name"]
    material.use_nodes = True
    tree = material.node_tree
    output = next((n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
    shader = (output.inputs['Surface'].links[0].from_node
              if output is not None and output.inputs['Surface'].is_linked else None)
    if shader is None or shader.type != 'BSDF_PRINCIPLED':
        # This changes only a new independent material, never the shared source.
        tree.nodes.clear()
        shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    fields = {"base_colour": "Base Color", "metallic": "Metallic", "roughness": "Roughness",
              "alpha": "Alpha", "ior": "IOR", "transmission": "Transmission Weight",
              "coat": "Coat Weight", "subsurface": "Subsurface Weight",
              "emission_colour": "Emission Color", "emission_strength": "Emission Strength"}
    for key, socket in fields.items():
        if key in params:
            for link in tuple(shader.inputs[socket].links):
                tree.links.remove(link)
            shader.inputs[socket].default_value = params[key]
    if "base_colour" in params:
        material.diffuse_color = params["base_colour"]
    if "metallic" in params:
        material.metallic = params["metallic"]
    if "roughness" in params:
        material.roughness = params["roughness"]
    if "alpha" in params:
        material.diffuse_color[3] = params["alpha"]
    if existing is None:
        obj.data.materials.append(material)
        obj.active_material_index = len(obj.data.materials) - 1
    else:
        obj.active_material = material


def _curve(obj, tool, params):
    from mathutils import Vector
    data = obj.data
    if tool == "curve.spline_add":
        kind = params["kind"]
        spline = data.splines.new(kind)
        points = spline.bezier_points if kind == "BEZIER" else spline.points
        points.add(len(params["points_m"]) - 1)
        for point, coords in zip(points, params["points_m"]):
            position = Vector(coords) / _unit()
            point.co = position if kind == "BEZIER" else (*position, 1)
            if kind == "BEZIER":
                point.handle_left_type = point.handle_right_type = 'AUTO'
        spline.use_cyclic_u = params.get("cyclic", False)
        if kind == "NURBS":
            spline.order_u = min(4, len(points))
            spline.use_endpoint_u = params.get("endpoint", True)
    elif tool == "curve.spline_remove":
        data.splines.remove(data.splines[int(params["spline"])])
    elif tool == "curve.point_set":
        spline = data.splines[int(params["spline"])]
        point = (spline.bezier_points if spline.type == "BEZIER" else spline.points)[int(params["point"])]
        position = Vector(params["position_m"]) / _unit()
        point.co = position if spline.type == "BEZIER" else (*position, point.co.w)
        if "tilt" in params:
            point.tilt = params["tilt"]
        if "radius" in params:
            point.radius = params["radius"]
        if "handle_type" in params and spline.type == "BEZIER":
            point.handle_left_type = point.handle_right_type = params["handle_type"]
    else:
        for key, attr in {"dimensions": "dimensions", "resolution": "resolution_u",
                          "bevel_resolution": "bevel_resolution", "fill_caps": "use_fill_caps",
                          "fill_mode": "fill_mode"}.items():
            if key in params:
                setattr(data, attr, int(params[key]) if key in ("resolution", "bevel_resolution") else params[key])
        for key, attr in (("bevel_depth_m", "bevel_depth"), ("extrude_m", "extrude")):
            if key in params:
                setattr(data, attr, params[key] / _unit())
    data.update_tag()


def _rig(editor, obj, tool, params):
    if tool == 'rig.bind_armature':
        modifier = obj.modifiers.new('Armature', 'ARMATURE')
        modifier.object = editor.sync.find_object(params['rig_id'])
        modifier.use_vertex_groups = True
        modifier.use_bone_envelopes = False
        obj[_BIND_TAG] = modifier.name
        return
    if tool == 'rig.unbind_armature':
        obj.modifiers.remove(obj.modifiers[obj[_BIND_TAG]])
        del obj[_BIND_TAG]
        return
    bone = _bone(obj, params['bone'])
    if tool.startswith('rig.pose_'):
        if tool == 'rig.pose_reset':
            bone.location = (0, 0, 0)
            bone.rotation_euler = (0, 0, 0)
            bone.rotation_quaternion = (1, 0, 0, 0)
            bone.rotation_axis_angle = (0, 0, 1, 0)
            bone.scale = (1, 1, 1)
        else:
            if 'location_m' in params:
                bone.location = tuple(v / _unit() for v in params['location_m'])
            if 'rotation' in params:
                from mathutils import Quaternion
                rotation = Quaternion(params['rotation']).normalized()
                if bone.rotation_mode == 'QUATERNION':
                    bone.rotation_quaternion = rotation
                elif bone.rotation_mode == 'AXIS_ANGLE':
                    axis, angle = rotation.to_axis_angle()
                    bone.rotation_axis_angle = (angle, *axis)
                else:
                    bone.rotation_euler = rotation.to_euler(bone.rotation_mode)
            if 'scale' in params:
                bone.scale = params['scale']
    elif tool == 'rig.ik_remove':
        _, constraint, _ = _owned_ik(obj)
        bone.constraints.remove(constraint)
        del obj[_IK_TAG]
    else:
        if tool == 'rig.ik_add':
            constraint = bone.constraints.new('IK')
            constraint.name = 'Spatial IK'
            constraint.iterations = 64
            constraint.use_stretch = False
            constraint.use_rotation = False
        else:
            _, constraint, _ = _owned_ik(obj)
        if 'target_id' in params:
            constraint.target = _rig_target(editor, obj, params['target_id'])
        if 'chain_count' in params:
            constraint.chain_count = int(params['chain_count'])
        if 'influence' in params:
            constraint.influence = params['influence']
        obj[_IK_TAG] = json.dumps({'bone': bone.name, 'name': constraint.name,
                                  'target_id': constraint.target.get('spatial_modeling_id')}, sort_keys=True)
    obj.update_tag(refresh={'OBJECT', 'DATA'})


def _animation(obj, tool, params):
    import bpy
    if tool == 'animation.frame_range':
        scene = bpy.context.scene
        scene.frame_start = int(params['start'])
        scene.frame_end = int(params['end'])
        if 'fps' in params:
            scene.render.fps = int(params['fps'])
        return
    _private_action(obj)
    if tool == 'animation.interpolation':
        for curve in _action_curves(obj.animation_data.action):
            if curve.data_path == params['channel']:
                for point in curve.keyframe_points:
                    point.interpolation = params['interpolation']
                    if 'handle_type' in params:
                        point.handle_left_type = point.handle_right_type = params['handle_type']
                curve.update()
    else:
        bone = obj.pose.bones[params['bone']]
        operation = bone.keyframe_insert if tool == 'animation.pose_keyframe' else bone.keyframe_delete
        if not operation(data_path=params['channel'], frame=params['frame'], group=bone.name):
            raise ValueError('The native pose keyframe operation had no matching result')


def _settings(obj, tool, params):
    data = obj.data
    if tool == 'camera.settings':
        mapping = {'projection': ('type', False), 'lens_mm': ('lens', False), 'sensor_width_mm': ('sensor_width', False),
                   'ortho_scale_m': ('ortho_scale', True), 'clip_start_m': ('clip_start', True), 'clip_end_m': ('clip_end', True)}
    elif tool == 'light.settings':
        if 'kind' in params:
            data.type = params['kind']
        mapping = {'colour': ('color', False), 'energy': ('energy', False), 'radius_m': ('shadow_soft_size', True),
                   'spot_angle': ('spot_size', False), 'spot_blend': ('spot_blend', False), 'area_size_m': ('size', True)}
    else:
        mapping = {'body': ('body', False), 'size_m': ('size', True), 'extrude_m': ('extrude', True),
                   'bevel_depth_m': ('bevel_depth', True), 'align_x': ('align_x', False), 'align_y': ('align_y', False),
                   'line_spacing': ('space_line', False)}
    for key, (attribute, metric) in mapping.items():
        if key in params:
            if not hasattr(data, attribute):
                raise ValueError('That property does not apply to the selected native data type')
            setattr(data, attribute, params[key] / _unit() if metric else params[key])
    data.update_tag()


def _modifier(obj, tool, params):
    if tool == 'modifier.boolean':
        raise ValueError('Boolean operands require the shared editor identity resolver')
    if tool == 'modifier.add_deform':
        modifier = obj.modifiers.new(params['kind'].replace('_', ' ').title(), params['kind'])
        values = {k: v for k, v in params.items() if k != 'kind'}
        if params['kind'] == 'EDGE_SPLIT' and 'angle' in values:
            values['split_angle'] = values.pop('angle')
    else:
        modifier = obj.modifiers[params['name']]
        values = {k: v for k, v in params.items() if k != 'name'}
    for key, value in values.items():
        attribute, kind = _MOD_FIELDS[modifier.type][key]
        setattr(modifier, attribute, value / _unit() if kind == 'length' else int(value) if kind == 'int' else value)


def _mesh(editor, obj, tool, params, selection):
    import bmesh
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    from . import modeling_mesh
    live = bmesh.from_edit_mesh(obj.data)
    stage = live.copy()
    backup = bpy.data.meshes.new("__spatial_extras_backup")
    pending = bpy.data.meshes.new("__spatial_extras_pending")
    changed = False
    try:
        live.to_mesh(backup)
        domain, picked = modeling_mesh.elements(stage, selection)
        verts = set(picked if domain == "vertex" else (v for e in picked for v in e.verts))
        result_domain, result_items = domain, picked
        if tool == "mesh.project_surface":
            surface = editor.sync.find_object(params["surface_id"])
            graph = bpy.context.evaluated_depsgraph_get()
            evaluated = surface.evaluated_get(graph)
            mesh = evaluated.to_mesh()
            try:
                if len(mesh.vertices) > 50000 or len(mesh.polygons) > 50000:
                    raise ValueError("The projection surface exceeds native bounds")
                coordinates = [(evaluated.matrix_world @ v.co) * _unit() for v in mesh.vertices]
                mesh.calc_loop_triangles()
                tree = BVHTree.FromPolygons(coordinates, [tuple(t.vertices) for t in mesh.loop_triangles], all_triangles=True)
                destinations = []
                inverse = obj.matrix_world.inverted()
                for vert in verts:
                    point, normal, _, _ = tree.find_nearest((obj.matrix_world @ vert.co) * _unit(), params["max_distance_m"])
                    if point is None or normal is None:
                        raise ValueError("Every selected vertex must hit the surface within the requested metric distance")
                    destinations.append((vert, inverse @ ((point + normal * params["normal_offset_m"]) / _unit())))
                for vert, destination in destinations:
                    vert.co = destination
            finally:
                evaluated.to_mesh_clear()
        elif tool == 'mesh.flatten':
            normal = Vector(params['normal']).normalized()
            world, unit = obj.matrix_world, _unit()
            pivot = (Vector(params['plane_point_m']) if 'plane_point_m' in params
                     else sum(((world @ v.co) * unit for v in verts), Vector()) / len(verts))
            inverse = world.inverted()
            for vert in verts:
                point = (world @ vert.co) * unit
                vert.co = inverse @ ((point - normal * (point - pivot).dot(normal) * params['factor']) / unit)
        elif tool == 'mesh.solidify':
            result = bmesh.ops.solidify(stage, geom=picked, thickness=params['thickness_m'] / _unit())
            result_domain = 'face'
            result_items = [e for e in result['geom'] if isinstance(e, bmesh.types.BMFace)]
        elif tool == 'mesh.symmetrize':
            bmesh.ops.symmetrize(stage, input=[*stage.verts, *stage.edges, *stage.faces],
                                 direction=params['direction'], dist=params['distance_m'] / _unit(), use_shapekey=False)
            result_domain, result_items = 'vertex', list(stage.verts)
        elif tool == "mesh.smooth_vertices":
            chosen = [v for v in verts if not params.get("preserve_boundary", True) or not v.is_boundary]
            for _ in range(int(params["iterations"])):
                bmesh.ops.smooth_vert(stage, verts=chosen, factor=params["factor"], use_axis_x=True, use_axis_y=True, use_axis_z=True)
        elif tool == "mesh.poke":
            result = bmesh.ops.poke(stage, faces=picked, offset=params["offset_m"] / _unit(), center_mode='MEAN_WEIGHTED')
            result_domain, result_items = "face", result["faces"]
        elif tool in ('mesh.sculpt_mask', 'mesh.face_set'):
            if tool == 'mesh.sculpt_mask':
                layer = stage.verts.layers.float.get('.sculpt_mask') or stage.verts.layers.float.new('.sculpt_mask')
            else:
                layer = stage.faces.layers.int.get('.sculpt_face_set') or stage.faces.layers.int.new('.sculpt_face_set')
            _, refreshed = modeling_mesh.elements(stage, selection)
            for element in refreshed:
                element[layer] = params['value']
        elif tool == "mesh.tris_to_quads":
            if any(len(f.verts) != 3 for f in picked):
                raise ValueError("Joining triangles needs selected native triangles")
            result = bmesh.ops.join_triangles(stage, faces=picked, angle_face_threshold=params["angle_limit"],
                        angle_shape_threshold=params["angle_limit"], cmp_seam=True, cmp_sharp=True,
                        cmp_uvs=params.get("preserve_uvs", True), cmp_vcols=True, cmp_materials=True)
            result_domain, result_items = "face", result["faces"]
        else:
            bmesh.ops.unsubdivide(stage, verts=list(verts), iterations=int(params["iterations"]))
            result_domain, result_items = "vertex", [v for v in stage.verts if v.select and not v.hide]
        modeling_mesh.index(stage)
        result_selection = modeling_mesh.select(stage, result_domain, result_items)
        stage.normal_update()
        stage.to_mesh(pending)
        changed = True
        live.clear()
        live.from_mesh(pending)
        modeling_mesh.index(live)
        bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
        obj.update_from_editmode()
        bpy.context.view_layer.update()
        return result_selection
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


def apply_step(editor, target, tool, params, selection=None, outputs=None):
    import bpy
    if isinstance(target, str):
        target = editor.sync.find_object(target)
    selection = copy.deepcopy(selection or {"component": "object", "indices": []})
    params = preflight(editor, target, tool, params, selection, outputs)
    if tool.startswith("mesh."):
        selection = _mesh(editor, target, tool, params, selection)
    elif tool in ("uv.pin", "uv.pack", "uv.select_island", "uv.weld", "uv.average_islands_scale"):
        selection = _uv(target, tool, params, selection)
    elif tool == "uv.layer_activate":
        target.data.uv_layers.active = target.data.uv_layers[params["name"]]
    elif tool == "uv.layer_copy":
        layer = target.data.uv_layers.new(name=params["name"], do_init=True)
        target.data.uv_layers.active = layer
    elif tool.startswith("vertex_group."):
        group = target.vertex_groups.get(params["name"])
        if tool == "vertex_group.create":
            target.vertex_groups.new(name=params["name"])
        elif tool == "vertex_group.remove":
            target.vertex_groups.remove(group)
        elif tool == "vertex_group.rename":
            group.name = params["new_name"]
        else:
            group.lock_weight = params["locked"]
    elif tool.startswith("weights."):
        _weights(target, tool, params, selection)
    elif tool == "material.principled":
        _principled(target, params)
    elif tool == "material.slot_remove":
        target.data.materials.pop(index=int(params["index"]))
    elif tool == "collection.create":
        bpy.context.scene.collection.children.link(bpy.data.collections.new(params["name"]))
    elif tool.startswith("collection."):
        collection = _collection(params["name"])
        if tool == "collection.rename":
            collection.name = params["new_name"]
        else:
            if "viewport" in params:
                collection.hide_viewport = not params["viewport"]
            if "render" in params:
                collection.hide_render = not params["render"]
    elif tool == "object.collection_link":
        collection = _collection(params["name"])
        if target.name not in collection.objects:
            collection.objects.link(target)
    elif tool == "object.collection_unlink":
        _collection(params["name"]).objects.unlink(target)
    elif tool.startswith("curve."):
        _curve(target, tool, params)
    elif tool.startswith('rig.'):
        _rig(editor, target, tool, params)
    elif tool.startswith('animation.'):
        _animation(target, tool, params)
    elif tool.startswith(('camera.', 'light.', 'text.')):
        _settings(target, tool, params)
    elif tool.startswith('modifier.'):
        if tool == 'modifier.boolean':
            modifier = target.modifiers.new('Boolean', 'BOOLEAN')
            modifier.object = editor.sync.find_object(params['operand_id'])
            modifier.operation, modifier.solver = params['operation'], params['solver']
        else:
            _modifier(target, tool, params)
    else:
        raise ValueError("No native finishing executor for " + tool)
    bpy.context.view_layer.update()
    selection["id"] = _identity(editor, target)
    return {"selection": selection, "outputs": {"selection": selection, "object": {"id": selection["id"]}}}


class ExtraBackup:
    """Additional state restored after the shared object/data recipe backup.

    Data geometry, UVs and curve splines belong to the shared backup. Materials
    are edited only through a new independent copy, so original node trees are
    never changed. This companion restores collection structure and vertex
    group definitions/weights that object-data replacement alone cannot restore.
    """

    def __init__(self, steps, editor):
        import bpy
        self.editor = editor
        self.collections = []
        self.objects = []
        self.restored = False
        self.closed = False
        tools = {step.get('tool', '') for step in steps}
        self.capture_collections = any(tool.startswith(('collection.', 'object.collection_')) for tool in tools)
        weight_targets = {step.get('target') for step in steps
                          if isinstance(step.get('target'), str)
                          and step.get('tool', '').startswith(('vertex_group.', 'weights.'))}
        material_targets = {step.get('target') for step in steps
                            if isinstance(step.get('target'), str)
                            and step.get('tool', '').startswith('material.')}
        pose_targets = {step.get('target') for step in steps
                        if isinstance(step.get('target'), str)
                        and (step.get('tool', '').startswith('rig.') or step.get('tool', '').startswith('animation.pose_'))}
        ik_targets = {step.get('target') for step in steps
                      if isinstance(step.get('target'), str) and step.get('tool', '').startswith('rig.ik_')}
        action_targets = {step.get('target') for step in steps
                          if isinstance(step.get('target'), str)
                          and step.get('tool', '').startswith('animation.')
                          and step.get('tool') not in ('animation.frame', 'animation.frame_range')}
        self.capture_frame = bool(tools & {'animation.frame_range', 'animation.frame'})
        self.before_actions = {a.session_uid for a in bpy.data.actions} if action_targets else None
        self.noop = not any((self.capture_collections, weight_targets, material_targets,
                             pose_targets, action_targets, self.capture_frame))
        if self.noop:
            return
        self.scene_uid = bpy.context.scene.session_uid
        self.filepath = bpy.data.filepath
        scene = bpy.context.scene
        self.frame = (scene.frame_start, scene.frame_end, scene.render.fps, scene.render.fps_base,
                      scene.frame_current, scene.frame_subframe) if self.capture_frame else None
        self.object_ids = {o.session_uid: o.get('spatial_modeling_id', '') for o in scene.objects}
        if self.capture_collections and (len(bpy.data.collections) > 256 or len(bpy.context.scene.objects) > 256):
            raise ValueError("Atomic finishing edits require a bounded native scene")
        self.collection_ids = {c.session_uid for c in bpy.data.collections} if self.capture_collections else set()
        for collection in bpy.data.collections if self.capture_collections else ():
            self.collections.append((collection, collection.name, collection.hide_viewport,
                                     collection.hide_render, tuple(collection.children)))
        self.root_children = tuple(bpy.context.scene.collection.children) if self.capture_collections else ()
        budget = 250000
        for obj in bpy.context.scene.objects:
            capture_groups = obj.type == 'MESH' and obj.get('spatial_modeling_id', '') in weight_targets
            capture_material = obj.get('spatial_modeling_id', '') in material_targets
            capture_pose = obj.type == 'ARMATURE' and obj.get('spatial_modeling_id', '') in pose_targets
            capture_action = obj.get('spatial_modeling_id', '') in action_targets
            capture_ik = obj.get('spatial_modeling_id', '') in ik_targets
            if not any((self.capture_collections, capture_groups, capture_material, capture_pose, capture_action)):
                continue
            groups = [(g.name, g.lock_weight) for g in obj.vertex_groups] if capture_groups else []
            if len(groups) > 64:
                raise ValueError("Atomic weight edits support at most 64 vertex groups per object")
            weights = []
            if obj.type == "MESH" and groups:
                if obj.data.is_editmode:
                    import bmesh
                    bm = bmesh.from_edit_mesh(obj.data)
                    from . import modeling_mesh
                    modeling_mesh.index(bm)
                    values = _weight_maps(obj, bm)
                    weights = sorted((i, sorted(v.items())) for i, v in values.items())
                else:
                    weights = [(v.index, [(g.group, g.weight) for g in v.groups]) for v in obj.data.vertices]
                budget -= sum(len(row) for _, row in weights)
                if budget < 0:
                    raise ValueError("Atomic weight snapshot exceeds its native bounds")
            self.objects.append({"uid": obj.session_uid, "id": obj.get("spatial_modeling_id", ""),
                                 "collections": tuple(obj.users_collection), "groups": groups,
                                 "capture_groups": capture_groups,
                                 "capture_material": capture_material,
                                 "pose": _pose_state(obj, capture_ik) if capture_pose else None,
                                 "capture_action": capture_action,
                                 "had_animation": obj.animation_data is not None,
                                 "action": obj.animation_data.action if obj.animation_data else None,
                                 "action_slot": (obj.animation_data.action_slot.identifier
                                                 if obj.animation_data and obj.animation_data.action_slot else None),
                                 "weights": weights, "active_group": obj.vertex_groups.active_index if groups else 0,
                                 "active_material": obj.active_material_index})

    def restore(self):
        import bpy
        if self.closed:
            raise ValueError("Atomic finishing backup is closed")
        if self.noop:
            self.restored = True
            return
        if bpy.context.scene.session_uid != self.scene_uid or bpy.data.filepath != self.filepath:
            raise ValueError("Native document changed; cross-document finishing rollback is forbidden")
        if bpy.context.mode != "OBJECT":
            raise ValueError("Restore the shared object/data backup before finishing metadata")
        live = {o.session_uid: o for o in bpy.context.scene.objects}
        for record in self.objects:
            obj = live.get(record["uid"]) or (self.editor.sync.find_object(record["id"]) if record["id"] else None)
            if obj is None:
                raise ValueError("A saved native object was not restored by the shared backup")
            if self.capture_collections:
                expected = record["collections"]
                for collection in expected:
                    if obj.name not in collection.objects:
                        collection.objects.link(obj)
                for collection in tuple(obj.users_collection):
                    if collection not in expected:
                        collection.objects.unlink(obj)
            if obj.type == "MESH" and record['capture_groups']:
                obj.vertex_groups.clear()
                for name, locked in record["groups"]:
                    group = obj.vertex_groups.new(name=name)
                    group.lock_weight = locked
                for index, weights in record["weights"]:
                    if index >= len(obj.data.vertices):
                        raise ValueError("The shared backup did not restore matching weight topology")
                    for group, weight in weights:
                        obj.vertex_groups[int(group)].add([int(index)], weight, 'REPLACE')
                if record["groups"]:
                    obj.vertex_groups.active_index = record["active_group"]
            if record['capture_material']:
                obj.active_material_index = record["active_material"]
            if record['pose'] is not None:
                remapped = dict(live)
                for uid, identity in self.object_ids.items():
                    candidate = self.editor.sync.find_object(identity) if identity else None
                    if candidate is not None:
                        remapped[uid] = candidate
                _restore_pose(obj, record['pose'], remapped)
            if record['capture_action']:
                if not record['had_animation']:
                    obj.animation_data_clear()
                else:
                    _bind_action(obj, record['action'], record['action_slot'])
        # New collections can reuse a name vacated by a renamed old collection.
        # Remove those exact new IDs before assigning the saved original names.
        if self.capture_collections:
            for collection in list(bpy.data.collections):
                if collection.session_uid not in self.collection_ids:
                    bpy.data.collections.remove(collection)
        # Restore exact original links and collection properties.
        for collection, name, viewport, render, children in self.collections:
            if collection.name != name:
                collection.name = name
            if collection.hide_viewport != viewport:
                collection.hide_viewport = viewport
            if collection.hide_render != render:
                collection.hide_render = render
            for child in children:
                if child.name not in collection.children:
                    collection.children.link(child)
            for child in tuple(collection.children):
                if child not in children:
                    collection.children.unlink(child)
        if self.capture_collections:
            root = bpy.context.scene.collection
            for child in self.root_children:
                if child.name not in root.children:
                    root.children.link(child)
            for child in tuple(root.children):
                if child not in self.root_children:
                    root.children.unlink(child)
            for collection in list(bpy.data.collections):
                if collection.session_uid not in self.collection_ids:
                    bpy.data.collections.remove(collection)
        bpy.context.view_layer.update()
        if self.frame is not None:
            scene = bpy.context.scene
            scene.frame_start, scene.frame_end, scene.render.fps, scene.render.fps_base = self.frame[:4]
            scene.frame_set(self.frame[4], subframe=self.frame[5])
        self.restored = True

    def close(self, restored=False):
        import bpy
        if self.before_actions is not None:
            for action in list(bpy.data.actions):
                if action.session_uid not in self.before_actions and action.users == 0:
                    bpy.data.actions.remove(action)
        self.closed = True


def _pose_state(obj, constraints=False):
    active = obj.data.bones.active
    return {'active': active.name if active else None,
            'bones': [{'name': bone.name, 'mode': bone.rotation_mode,
                       'location': tuple(bone.location), 'quaternion': tuple(bone.rotation_quaternion),
                       'euler': tuple(bone.rotation_euler), 'axis_angle': tuple(bone.rotation_axis_angle),
                       'scale': tuple(bone.scale), 'selected': bone.select,
                       'locks': [tuple(bone.lock_location), tuple(bone.lock_rotation), tuple(bone.lock_scale),
                                 bone.lock_rotation_w, bone.lock_rotations_4d],
                       'constraints': [(c.name, c.type, _constraint_values(c)) for c in bone.constraints]
                                      if constraints else None}
                      for bone in obj.pose.bones]}


def _constraint_values(constraint):
    import bpy
    result = {}
    for prop in constraint.bl_rna.properties:
        if prop.identifier in {'rna_type', 'name', 'type'} or prop.is_readonly or prop.type == 'COLLECTION':
            continue
        value = getattr(constraint, prop.identifier)
        result[prop.identifier] = (('__object_uid__', value.session_uid) if isinstance(value, bpy.types.Object)
                                   else tuple(value) if getattr(prop, 'is_array', False) else value)
    return result


def _restore_pose(obj, state, objects):
    from . import voice_sequence
    if {bone.name for bone in obj.pose.bones} != {row['name'] for row in state['bones']}:
        raise ValueError('The shared backup did not restore the native rig structure')
    for row in state['bones']:
        bone = obj.pose.bones[row['name']]
        bone.rotation_mode = row['mode']
        bone.location, bone.rotation_quaternion = row['location'], row['quaternion']
        bone.rotation_euler, bone.rotation_axis_angle, bone.scale = row['euler'], row['axis_angle'], row['scale']
        bone.select = row['selected']
        if row['constraints'] is not None:
            for current in list(bone.constraints):
                bone.constraints.remove(current)
            for name, kind, values in row['constraints']:
                constraint = bone.constraints.new(kind)
                constraint.name = name
                voice_sequence._restore_rna(constraint, values, objects)
    obj.data.bones.active = obj.data.bones.get(state['active']) if state['active'] else None
    obj.update_tag(refresh={'OBJECT', 'DATA'})


def context_fingerprint(objects=None):
    """Read-only native freshness beyond streamed geometry and object transforms.

    The host can include this digest in its captured AI context and compare it
    again before execution. No ID is assigned and no input or mode is changed.
    """
    import bpy
    scene = bpy.context.scene
    if objects is None:
        objects = list(bpy.context.selected_objects)
        if bpy.context.active_object is not None and bpy.context.active_object not in objects:
            objects.append(bpy.context.active_object)
    result = {'scene': scene.session_uid, 'mode': bpy.context.mode,
              'active': bpy.context.active_object.session_uid if bpy.context.active_object else None,
              'selection': sorted(o.session_uid for o in bpy.context.selected_objects),
              'frame': [scene.frame_current, scene.frame_subframe, scene.frame_start, scene.frame_end,
                        scene.render.fps, scene.render.fps_base], 'objects': [],
              'collections': [(c.session_uid, c.name, c.hide_viewport, c.hide_render,
                               sorted(child.session_uid for child in c.children),
                               sorted(o.session_uid for o in c.objects)) for c in bpy.data.collections]}
    for obj in sorted(objects, key=lambda o: o.session_uid):
        row = {'uid': obj.session_uid, 'data': obj.data.session_uid if obj.data else None,
               'active_material': obj.active_material_index}
        if obj.type == 'ARMATURE':
            row['rest'] = [(b.name, b.parent.name if b.parent else None, list(b.head_local), list(b.tail_local), b.hide,
                            b.hide_select, [(c.name, c.is_visible_effectively) for c in b.collections])
                           for b in obj.data.bones]
            pose = _pose_state(obj, True)
            for bone in pose['bones']:
                native = obj.pose.bones[bone['name']]
                bone['matrix'] = [list(row) for row in native.matrix]
                bone['constraints'] = [(name, kind, {key: _fingerprint_value(value) for key, value in values.items()})
                                       for name, kind, values in bone['constraints']]
            row['pose'] = pose
        if obj.type == 'MESH':
            row['groups'] = [(g.name, g.lock_weight) for g in obj.vertex_groups]
            if obj.data.is_editmode:
                import bmesh
                bm = bmesh.from_edit_mesh(obj.data)
                row['weights'] = _weight_maps(obj, bm)
                uv_names = bm.loops.layers.uv.keys()
                row['uv'] = [(name, [(list(l[layer].uv), l[layer].pin_uv)
                                    for f in bm.faces for l in f.loops])
                             for name in uv_names for layer in [bm.loops.layers.uv[name]]]
                row['active_uv'] = bm.loops.layers.uv.active.name if bm.loops.layers.uv.active else None
                mask, faceset = bm.verts.layers.float.get('.sculpt_mask'), bm.faces.layers.int.get('.sculpt_face_set')
                row['sculpt'] = ([v[mask] for v in bm.verts] if mask else None,
                                 [f[faceset] for f in bm.faces] if faceset else None)
            else:
                row['weights'] = _weight_maps(obj, None)
                row['uv'] = [(layer.name, [list(loop.uv) for loop in layer.data]) for layer in obj.data.uv_layers]
                row['active_uv'] = obj.data.uv_layers.active_index
        if obj.type == 'CURVE':
            row['splines'] = [(s.type, s.use_cyclic_u,
                               [(list(p.co), p.radius, p.tilt) for p in s.points],
                               [(list(p.co), list(p.handle_left), list(p.handle_right), p.handle_left_type,
                                 p.handle_right_type, p.radius, p.tilt) for p in s.bezier_points]) for s in obj.data.splines]
            row['curve'] = [obj.data.dimensions, obj.data.resolution_u, obj.data.bevel_depth,
                            obj.data.bevel_resolution, obj.data.extrude, obj.data.use_fill_caps, obj.data.fill_mode]
        if obj.type in ('CAMERA', 'LIGHT', 'FONT'):
            attrs = {'CAMERA': ('type', 'lens', 'sensor_width', 'ortho_scale', 'clip_start', 'clip_end'),
                     'LIGHT': ('type', 'color', 'energy', 'shadow_soft_size', 'spot_size', 'spot_blend', 'size'),
                     'FONT': ('body', 'size', 'extrude', 'bevel_depth', 'align_x', 'align_y', 'space_line')}[obj.type]
            row['settings'] = {name: _fingerprint_value(getattr(obj.data, name))
                               for name in attrs if hasattr(obj.data, name)}
        row['materials'] = []
        for slot in obj.material_slots:
            material = slot.material
            if material is None:
                row['materials'].append(None)
                continue
            item = {'uid': material.session_uid, 'link': slot.link, 'colour': list(material.diffuse_color),
                    'metallic': material.metallic, 'roughness': material.roughness}
            if material.node_tree is not None:
                tree = material.node_tree
                item['nodes'] = [(node.name, node.bl_idname,
                                   [(socket.identifier, _fingerprint_value(socket.default_value))
                                    for socket in node.inputs if hasattr(socket, 'default_value')]) for node in tree.nodes]
                item['links'] = [(link.from_node.name, link.from_socket.identifier,
                                  link.to_node.name, link.to_socket.identifier) for link in tree.links]
            row['materials'].append(item)
        action = obj.animation_data.action if obj.animation_data else None
        if action is not None:
            row['animation'] = [(curve.data_path, curve.array_index,
                                  [(list(k.co), k.interpolation, list(k.handle_left), list(k.handle_right),
                                    k.handle_left_type, k.handle_right_type) for k in curve.keyframe_points])
                                 for curve in _action_curves(action)]
        result['objects'].append(row)
    raw = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('The complete native modeling freshness context exceeds eight MiB')
    return hashlib.sha256(raw).hexdigest()


def _fingerprint_value(value):
    import bpy
    if isinstance(value, bpy.types.ID):
        return {'native_uid': value.session_uid}
    if isinstance(value, (list, tuple)):
        return [_fingerprint_value(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if not isinstance(value, (str, bool, int, float, type(None))) and hasattr(value, '__iter__'):
        return [_fingerprint_value(v) for v in value]
    return value

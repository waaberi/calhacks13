"""Native finishing operations with bounded targets and recipe rollback support.

The caller owns authority, document generations and the single native Undo
boundary. This module neither opens a document nor changes the user's mode.
"""

import copy

from . import tool_catalog_extras as catalog

OPERATIONS = catalog.OPERATIONS


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
        return {v.index: dict(v[layer]) if layer else {} for v in bm.verts}
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


def _mesh(editor, obj, tool, params, selection):
    import bmesh
    import bpy
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
        elif tool == "mesh.smooth_vertices":
            chosen = [v for v in verts if not params.get("preserve_boundary", True) or not v.is_boundary]
            for _ in range(int(params["iterations"])):
                bmesh.ops.smooth_vert(stage, verts=chosen, factor=params["factor"], use_axis_x=True, use_axis_y=True, use_axis_z=True)
        elif tool == "mesh.poke":
            result = bmesh.ops.poke(stage, faces=picked, offset=params["offset_m"] / _unit(), center_mode='MEAN_WEIGHTED')
            result_domain, result_items = "face", result["faces"]
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
        self.noop = not self.capture_collections and not weight_targets and not material_targets
        if self.noop:
            return
        self.scene_uid = bpy.context.scene.session_uid
        self.filepath = bpy.data.filepath
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
            if not self.capture_collections and not capture_groups and not capture_material:
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
        # Restore links first, then remove only collections created by this recipe.
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
        self.restored = True

    def close(self, restored=False):
        self.closed = True

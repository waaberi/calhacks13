"""Detached native BMesh kernels and exact resulting component references."""

import math


def index(bm):
    for items in (bm.verts, bm.edges, bm.faces):
        items.ensure_lookup_table()
        items.index_update()


def elements(bm, selection):
    index(bm)
    domain = selection.get("component", "")
    values = {"vertex": bm.verts, "edge": bm.edges, "face": bm.faces}.get(domain)
    indices = selection.get("indices", [])
    if values is None or not indices or len(indices) > 16384 or len(set(indices)) != len(indices):
        raise ValueError("Choose a nonempty exact native component selection")
    if any(type(i) not in (int, float) or int(i) != i or not 0 <= i < len(values) for i in indices):
        raise ValueError("A selected component no longer exists")
    picked = [values[int(i)] for i in indices]
    if any(e.hide for e in picked):
        raise ValueError("Hidden components cannot receive a spatial edit")
    return domain, picked


def ref(component, items):
    return {"component": component, "indices": sorted(e.index for e in items if e.is_valid and not e.hide)}


def _clear_selection(bm):
    bm.select_history.clear()
    bm.faces.active = None
    for items in (bm.faces, bm.edges, bm.verts):
        for item in items:
            item.select = False


def select(bm, component, items):
    items = [e for e in items if e.is_valid and not e.hide]
    _clear_selection(bm)
    for item in items:
        item.select_set(True)
    if items:
        for item in items:
            bm.select_history.add(item)
        if component == "face":
            bm.faces.active = items[-1]
    return {"component": component, "indices": [item.index for item in items]}


def ring(bm, edge):
    """Follow opposite edges in quads, with consistent cut/slide direction."""
    oriented = {edge: tuple(edge.verts)}
    queue = [edge]
    while queue:
        current = queue.pop()
        a, _b = oriented[current]
        for face in current.link_faces:
            if face.hide or len(face.verts) != 4:
                continue
            loop = next(loop for loop in face.loops if loop.edge == current)
            opposite = loop.link_loop_next.link_loop_next.edge
            if opposite.hide:
                continue
            # Adjacent face sides pair each original endpoint with the next rail.
            oa = next(v for v in opposite.verts if any(a in e.verts for e in v.link_edges if e in face.edges))
            ob = opposite.other_vert(oa)
            if opposite not in oriented:
                oriented[opposite] = (oa, ob)
                queue.append(opposite)
            elif oriented[opposite] != (oa, ob):
                raise ValueError("This edge ring has a conflicting slide orientation")
    if not any(len(face.verts) == 4 and not face.hide for face in edge.link_faces):
        raise ValueError("Loop cut needs an edge beside a visible quad")
    return oriented


def select_region(bm, picked, component, params):
    region = params["region"]
    if region == "BOUNDARY":
        if component != "face":
            raise ValueError("Boundary selection starts from faces")
        faces = set(picked)
        expanded = {e for f in faces for e in f.edges if sum(n in faces for n in e.link_faces) == 1}
        component = "edge"
    elif region == "EDGE_LOOP":
        if component != "edge" or len(picked) != 1:
            raise ValueError("Edge loop selection needs one seed edge")
        expanded, pending = set(picked), list(picked)
        while pending:
            edge = pending.pop()
            for vert in edge.verts:
                if vert.hide or len(vert.link_edges) != 4 or any(len(f.verts) != 4 for f in vert.link_faces):
                    continue
                candidates = [e for e in vert.link_edges if e != edge and not e.hide
                              and not any(f in e.link_faces for f in edge.link_faces)]
                if len(candidates) == 1 and candidates[0] not in expanded:
                    expanded.add(candidates[0])
                    pending.append(candidates[0])
    else:
        expanded, pending = set(picked), list(picked)
        while pending:
            item = pending.pop()
            neighbors = ([e.other_vert(item) for e in item.link_edges] if component == "vertex" else
                         [e for v in item.verts for e in v.link_edges] if component == "edge" else
                         [f for e in item.edges for f in e.link_faces])
            for item in neighbors:
                if not item.hide and item not in expanded:
                    expanded.add(item)
                    pending.append(item)
    mode = params.get("selection_mode", "REPLACE")
    if mode == "REPLACE":
        _clear_selection(bm)
    for item in expanded:
        item.select_set(not item.select if mode == "TOGGLE" else mode != "REMOVE")
    index(bm)
    values = {"vertex": bm.verts, "edge": bm.edges, "face": bm.faces}[component]
    return ref(component, [e for e in values if e.select])


def apply(bm, obj, tool, params, selection, unit):
    import bmesh
    from mathutils import Vector

    component, picked = elements(bm, selection)
    old_v, old_e, old_f = set(bm.verts), set(bm.edges), set(bm.faces)
    chosen_component, chosen = component, list(picked)
    outputs = {}
    scale = unit
    if tool == "mesh.extrude":
        source_edges = {e for f in picked for e in f.edges} if component == "face" else set()
        source_vertices = {v for e in picked for v in e.verts} if component != "vertex" else set(picked)
        if component == "face":
            if params.get("individual", False):
                result = bmesh.ops.extrude_discrete_faces(bm, faces=picked)
                chosen = result["faces"]
                moved = {v for f in chosen for v in f.verts}
                if "normal_distance_m" in params:
                    world = obj.matrix_world.to_3x3()
                    inverse = world.inverted()
                    normals = world.inverted().transposed()
                    for face in chosen:
                        face.normal_update()
                        normal = (normals @ face.normal).normalized()
                        offset = inverse @ (normal * (params["normal_distance_m"] / unit))
                        for vert in face.verts:
                            vert.co += offset
            else:
                result = bmesh.ops.extrude_face_region(bm, geom=picked, use_keep_orig=False)
                moved = {v for v in result["geom"] if isinstance(v, bmesh.types.BMVert)}
                retained = [f for f in picked if f.is_valid]
                if retained:
                    bmesh.ops.delete(bm, geom=retained, context="FACES_ONLY")
                unused = [e for e in source_edges if e.is_valid and not e.link_faces]
                if unused:
                    bmesh.ops.delete(bm, geom=unused, context="EDGES")
                unused = [v for v in source_vertices if v.is_valid and not v.link_edges]
                if unused:
                    bmesh.ops.delete(bm, geom=unused, context="VERTS")
                chosen = [f for f in bm.faces if f not in old_f and all(v in moved for v in f.verts)]
        elif component == "edge":
            result = bmesh.ops.extrude_edge_only(bm, edges=picked)
            moved = {v for v in result["geom"] if isinstance(v, bmesh.types.BMVert)}
            chosen = [e for e in bm.edges if all(v in moved for v in e.verts)]
        else:
            result = bmesh.ops.extrude_vert_indiv(bm, verts=picked)
            moved = set(result["verts"])
            chosen = list(moved)
        if not (component == "face" and params.get("individual", False) and "normal_distance_m" in params):
            offset = obj.matrix_world.to_3x3().inverted() @ (Vector(params["translation_m"]) / unit)
            for vert in moved:
                vert.co += offset
    elif tool == "mesh.inset":
        kwargs = {"faces": picked, "thickness": params["thickness_m"] / scale,
                  "depth": params.get("depth_m", 0) / scale,
                  "use_even_offset": params.get("even_offset", True),
                  "use_relative_offset": params.get("relative_offset", False)}
        if params.get("individual", False):
            result = bmesh.ops.inset_individual(bm, **kwargs)
        else:
            result = bmesh.ops.inset_region(bm, **kwargs, use_boundary=params.get("boundary", True),
                                          use_outset=params.get("outset", False))
        chosen = [f for f in picked if f.is_valid]
        index(bm)
        outputs["inner_faces"] = ref("face", chosen)
    elif tool == "mesh.bevel":
        vertices = params.get("vertices", component == "vertex")
        geom = picked
        if vertices and component != "vertex":
            geom = list({v for e in picked for v in e.verts})
        elif not vertices and component == "vertex":
            selected = set(picked)
            geom = [e for e in bm.edges if all(v in selected for v in e.verts)]
            if not geom:
                raise ValueError("Edge Bevel needs an edge or two adjacent selected vertices; choose vertex affect in Blender for a vertex bevel")
        elif component == "face":
            geom = list({e for face in picked for e in face.edges})
        result = bmesh.ops.bevel(bm, geom=geom, offset=params["width_m"] / scale,
                                segments=int(params.get("segments", 1)), profile=params.get("profile", .5),
                                affect="VERTICES" if vertices else "EDGES",
                                clamp_overlap=params.get("clamp_overlap", True),
                                offset_type=params.get("offset_type", "OFFSET"),
                                material=int(params.get("material_index", -1)))
        chosen_component, chosen = "face", list(result["faces"])
    elif tool == "mesh.loop_cut":
        if len(picked) != 1:
            raise ValueError("Loop cut needs exactly one seed edge")
        rails = ring(bm, picked[0])
        pairs = [(a.co.copy(), b.co.copy()) for a, b in rails.values()]
        bmesh.ops.subdivide_edges(bm, edges=list(rails), cuts=int(params.get("cuts", 1)), use_grid_fill=True)
        new_verts = [v for v in bm.verts if v not in old_v]
        slide = params.get("slide", 0)
        for v in new_verts:
            for a, b in pairs:
                delta = b - a
                t = (v.co - a).dot(delta) / delta.length_squared
                if -1e-5 <= t <= 1.00001 and (v.co - (a + delta*t)).length < 1e-5:
                    t += slide * (1-t if slide >= 0 else t)
                    v.co = a + delta*t
                    break
        chosen_component = "edge"
        chosen = [e for e in bm.edges if all(v in new_verts for v in e.verts)]
    elif tool == "mesh.merge":
        if len(picked) < 2:
            raise ValueError("Merge needs at least two vertices")
        variant = params.get("variant", "CENTER")
        if variant == "DISTANCE":
            bmesh.ops.remove_doubles(bm, verts=picked, dist=params.get("distance_m", .0001) / scale)
            chosen = [v for v in picked if v.is_valid]
        else:
            if variant == "CURSOR":
                import bpy
                center = obj.matrix_world.inverted() @ bpy.context.scene.cursor.location
            else:
                center = (picked[0].co.copy() if variant == "FIRST" else picked[-1].co.copy() if variant == "LAST"
                          else sum((v.co for v in picked), Vector()) / len(picked))
            bmesh.ops.pointmerge(bm, verts=picked, merge_co=center)
            chosen = [v for v in bm.verts if v in picked and v.is_valid]
    elif tool == "mesh.dissolve":
        if params.get("variant", "AUTO") == "LIMITED":
            verts = picked if component == "vertex" else list({v for e in picked for v in e.verts})
            edges = picked if component == "edge" else list({e for v in verts for e in v.link_edges})
            bmesh.ops.dissolve_limit(bm, angle_limit=params.get("angle_limit", .0872665),
                                     verts=verts, edges=edges, use_dissolve_boundaries=False)
        elif component == "vertex":
            bmesh.ops.dissolve_verts(bm, verts=picked, use_face_split=params.get("use_face_split", False), use_boundary_tear=False)
        elif component == "edge":
            bmesh.ops.dissolve_edges(bm, edges=picked, use_verts=params.get("use_verts", False), use_face_split=params.get("use_face_split", False))
        else:
            bmesh.ops.dissolve_faces(bm, faces=picked, use_verts=params.get("use_verts", False))
        chosen = [e for e in picked if e.is_valid]
    elif tool == "mesh.delete":
        domain = params.get("domain", {"vertex": "VERTS", "edge": "EDGES", "face": "FACES_ONLY"}[component])
        bmesh.ops.delete(bm, geom=picked, context="FACES_ONLY" if domain == "ONLY_FACE" else domain)
        chosen = []
    elif tool == "mesh.subdivide":
        result = bmesh.ops.subdivide_edges(bm, edges=picked, cuts=int(params.get("cuts", 1)),
                                          smooth=params.get("smooth", 0), use_grid_fill=True)
        chosen = [e for e in bm.edges if e not in old_e]
    elif tool == "mesh.fill":
        result = bmesh.ops.contextual_create(bm, geom=picked)
        chosen_component, chosen = "face", result["faces"]
    elif tool == "mesh.bridge":
        result = bmesh.ops.bridge_loops(bm, edges=picked, twist_offset=int(params.get("twist", 0)))
        chosen_component, chosen = "face", result["faces"]
    elif tool == "mesh.triangulate":
        result = bmesh.ops.triangulate(bm, faces=picked, quad_method="BEAUTY", ngon_method="BEAUTY")
        chosen = result["faces"]
    elif tool == "mesh.split_edges":
        bmesh.ops.split_edges(bm, edges=picked, use_verts=False)
        chosen = [e for e in bm.edges if e not in old_e]
    elif tool == "mesh.recalculate_normals":
        bmesh.ops.recalc_face_normals(bm, faces=picked)
        if params.get("inside", False):
            bmesh.ops.reverse_faces(bm, faces=picked)
    elif tool == "mesh.flip_normals":
        bmesh.ops.reverse_faces(bm, faces=picked)
    elif tool == "mesh.face_material":
        material_index = int(params["material_index"])
        if material_index >= len(obj.data.materials):
            raise ValueError("The material slot does not exist")
        for face in picked:
            face.material_index = material_index
    elif tool == "mesh.face_smooth":
        for face in picked:
            face.smooth = params["smooth"]
    elif tool == "mesh.edge_seam":
        for edge in picked:
            edge.seam = params["seam"]
    elif tool == "mesh.edge_properties":
        ids = [e.index for e in picked]
        for name, key in (("crease_edge", "crease"), ("bevel_weight_edge", "bevel_weight")):
            if key in params and bm.edges.layers.float.get(name) is None:
                bm.edges.layers.float.new(name)
        index(bm)
        picked = [bm.edges[i] for i in ids]
        for edge in picked:
            if "sharp" in params:
                edge.smooth = not params["sharp"]
            for name, key in (("crease_edge", "crease"), ("bevel_weight_edge", "bevel_weight")):
                if key in params:
                    edge[bm.edges.layers.float[name]] = params[key]
        chosen = picked
    elif tool == "mesh.select_region":
        selection = select_region(bm, picked, component, params)
        return {"selection": selection, "outputs": {"selection": selection}}
    elif tool == "mesh.slide_vertices":
        if len(params["rails"]) != len(picked):
            raise ValueError("Supply one neighboring rail vertex for each selected vertex")
        index(bm)
        destinations = []
        for v, target in zip(picked, params["rails"]):
            if not 0 <= target < len(bm.verts) or not any(e.other_vert(v).index == target for e in v.link_edges):
                raise ValueError("Every slide rail must share an existing edge with its source")
            destinations.append(v.co.lerp(bm.verts[int(target)].co, params["factor"]))
        for v, destination in zip(picked, destinations):
            v.co = destination
    elif tool == "mesh.bisect":
        world = obj.matrix_world
        point = world.inverted() @ (Vector(params["plane_point_m"]) / unit)
        normal = world.to_3x3().transposed() @ Vector(params["plane_normal"])
        if normal.length < 1e-8:
            raise ValueError("Bisect plane needs a nonzero normal")
        geom = set(picked)
        if component == "face":
            geom.update(e for f in picked for e in f.edges)
        geom.update(v for e in list(geom) if not isinstance(e, bmesh.types.BMVert) for v in e.verts)
        result = bmesh.ops.bisect_plane(bm, geom=list(geom), dist=1e-6, plane_co=point,
                                      plane_no=normal.normalized(), clear_inner=params.get("clear_inner", False),
                                      clear_outer=params.get("clear_outer", False))
        chosen_component = "edge"
        chosen = [e for e in result["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
    elif tool == "mesh.spin":
        world = obj.matrix_world
        center = world.inverted() @ (Vector(params["center_m"]) / unit)
        axis = world.to_3x3().inverted() @ Vector(params["axis"])
        if axis.length < 1e-8:
            raise ValueError("Spin needs a nonzero axis")
        result = bmesh.ops.spin(bm, geom=picked, cent=center, axis=axis.normalized(),
                                dvec=Vector(), angle=params["angle"], steps=int(params.get("steps", 8)),
                                use_duplicate=params.get("duplicate", False), space=world)
        chosen = [e for e in result["geom_last"] if isinstance(e, type(picked[0]))]
    else:
        raise ValueError(f"No detached mesh kernel for {tool}")
    index(bm)
    bm.normal_update()
    if len(bm.verts) > 8192 or len(bm.edges) > 16384 or len(bm.faces) > 8192:
        raise ValueError("The resulting mesh exceeds direct editing bounds")
    if any(not math.isfinite(c) or abs(c) > 100000 for v in bm.verts for c in (obj.matrix_world @ v.co) * unit):
        raise ValueError("The resulting mesh exceeds finite world bounds")
    new_v = [e for e in bm.verts if e not in old_v]
    new_e = [e for e in bm.edges if e not in old_e]
    new_f = [e for e in bm.faces if e not in old_f]
    outputs.update(new_vertices=ref("vertex", new_v), new_edges=ref("edge", new_e), new_faces=ref("face", new_f))
    outputs["boundary_edges"] = ref("edge", {e for f in new_f for e in f.edges
                                                 if sum(n in new_f for n in e.link_faces) == 1})
    result_selection = select(bm, chosen_component, chosen)
    outputs["selection"] = result_selection
    return {"selection": result_selection, "outputs": outputs}

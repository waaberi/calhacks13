"""Native projected polyline Knife with a frozen controller camera."""

from itertools import pairwise


def _view(projection, points, unit):
    from mathutils import Matrix, Vector
    matrix = Matrix([projection[i:i+4] for i in range(0, 16, 4)])
    rows = [matrix[i].xyz.copy() for i in range(4)]
    perspective = rows[3].length > 1e-8
    if perspective:
        forward = rows[3].normalized()
        right = (rows[0] - forward * rows[0].dot(forward)).normalized()
        back = -forward
        up = back.cross(right).normalized()
        coefficient = Matrix((rows[0], rows[1], rows[3]))
        if abs(coefficient.determinant()) < 1e-10:
            raise ValueError("The frozen Knife projection has no finite camera")
        origin = coefficient.inverted() @ Vector((-matrix[0][3], -matrix[1][3], -matrix[3][3]))
    else:
        right = rows[0].normalized()
        back = right.cross(rows[1]).normalized()
        if back.dot(rows[2]) > 0:
            back.negate()
        up = back.cross(right).normalized()
        origin = sum((Vector(p) for p in points), Vector()) / len(points) + back
    if any(v.length < .999 for v in (right, up, back)) or abs(right.dot(up)) > 1e-4:
        raise ValueError("The frozen Knife projection is not a valid camera")
    origin /= unit
    result = Matrix.Identity(4)
    for i, axis in enumerate((right, up, back)):
        for j in range(3):
            result[i][j] = axis[j]
        result[i][3] = -axis.dot(origin)
    return result, perspective, origin, back


def apply(editor, obj, params, selection):
    import bmesh
    import bpy
    from mathutils import Vector

    from . import modeling_mesh, modeling_tools, spatial_model_edit

    if bpy.app.background:
        raise ValueError("Native projected Knife requires an initialized Blender 3D View")
    spatial_model_edit._editable_mesh(bpy.context, obj)
    unit = modeling_tools._unit()
    path = params["path_m"]
    if any((Vector(a)-Vector(b)).length < 1e-7 for a, b in pairwise(path)):
        raise ValueError("Knife path samples must contain distinct points")
    view_matrix, perspective, origin, back = _view(params["projection"], path, unit)
    bm = bmesh.from_edit_mesh(obj.data)
    modeling_mesh.index(bm)
    old = (set(bm.verts), set(bm.edges), set(bm.faces))
    saved_hiding = [(e, bool(e.hide)) for values in (bm.verts, bm.edges, bm.faces) for e in values]
    backup = bpy.data.meshes.new("__spatial_knife_rollback")
    obj.update_from_editmode()
    bm.to_mesh(backup)
    selected_objects = list(bpy.context.selected_objects)
    cutter = cutter_mesh = None
    region = None
    saved_view = None
    changed = False
    try:
        if params.get("selected_only", False):
            if selection.get("component") != "face":
                raise ValueError("Selected-only Knife requires exact selected faces")
            _, picked = modeling_mesh.elements(bm, selection)
            picked = set(picked)
            for face in bm.faces:
                if face not in picked:
                    face.hide_set(True)
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        cutter_mesh = bpy.data.meshes.new("__spatial_knife_path")
        points = []
        for point in path:
            point = Vector(point) / unit
            # A small movement along the exact projection ray avoids coincident
            # cutter clipping while preserving the projected surface path.
            point += (origin-point) * .0001 if perspective else back * (.001 / unit)
            points.append(point)
        cutter_mesh.from_pydata(points, [(i, i+1) for i in range(len(points)-1)], [])
        cutter = bpy.data.objects.new("__spatial_knife_path", cutter_mesh)
        (obj.users_collection[0] if obj.users_collection else bpy.context.collection).objects.link(cutter)
        for item in bpy.context.selected_objects:
            if item != obj:
                item.select_set(False)
        cutter.select_set(True)
        with modeling_tools.native_context(obj, selected_objects=[obj, cutter]):
            region = bpy.context.region_data
            if region is None:
                raise ValueError("The existing native 3D View is not initialized")
            space = bpy.context.space_data
            saved_view = (region.view_matrix.copy(), region.view_perspective,
                          region.view_distance, region.view_location.copy(), region.view_rotation.copy(),
                          space, space.clip_start, space.clip_end)
            distances = [(Vector(point) / unit - origin).length for point in path]
            space.clip_start = min(space.clip_start, max(min(distances) * .01, .000001))
            space.clip_end = max(space.clip_end, max(distances) * 4 + 1)
            region.view_perspective = 'PERSP' if perspective else 'ORTHO'
            region.view_matrix = view_matrix
            region.update()
            changed = True
            status = bpy.ops.mesh.knife_project('EXEC_DEFAULT', False,
                                                 cut_through=params.get("cut_through", False))
            if status != {'FINISHED'}:
                raise ValueError("Native Knife did not finish")
        bm = bmesh.from_edit_mesh(obj.data)
        modeling_mesh.index(bm)
        new = [[e for e in values if e not in prior] for values, prior in zip((bm.verts, bm.edges, bm.faces), old)]
        if not new[0] and not new[1]:
            raise ValueError("The Knife path does not cross a visible native face")
        outputs = {key: modeling_mesh.ref(domain, values) for key, domain, values in
                   zip(("new_vertices", "new_edges", "new_faces"), ("vertex", "edge", "face"), new)}
        selected = modeling_mesh.select(bm, "edge", new[1])
        identity = editor.sync.object_id(obj)
        for value in [selected, *outputs.values()]:
            value["id"] = identity
        outputs["selection"] = selected
        bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
        obj.update_from_editmode()
        return {"selection": selected, "outputs": outputs}
    except Exception:
        if changed:
            bm = bmesh.from_edit_mesh(obj.data)
            bm.clear()
            bm.from_mesh(backup)
            bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
            obj.update_from_editmode()
        raise
    finally:
        if saved_view is not None and region is not None:
            _matrix, perspective_name, distance, location, rotation, space, near, far = saved_view
            space.clip_start, space.clip_end = near, far
            region.view_perspective = perspective_name
            region.view_distance = distance
            region.view_location = location
            region.view_rotation = rotation
            region.update()
        for item in list(bpy.context.selected_objects):
            if item != obj:
                item.select_set(False)
        for item in selected_objects:
            if item.name in bpy.context.view_layer.objects:
                item.select_set(True)
        for element, hidden in saved_hiding:
            if element.is_valid:
                element.hide = hidden
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        obj.update_from_editmode()
        if cutter is not None:
            bpy.data.objects.remove(cutter, do_unlink=True)
        if cutter_mesh is not None:
            bpy.data.meshes.remove(cutter_mesh)
        bpy.data.meshes.remove(backup)

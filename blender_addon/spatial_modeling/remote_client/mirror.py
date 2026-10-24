"""Apply replication only to an owned collection in a separate empty session."""

import json

import bpy
from mathutils import Matrix, Quaternion, Vector

OWNER = "spatial_readonly_mirror"
SKETCH_RECORD = "spatial_modeling_sketch_record"


class Mirror:
    def __init__(self):
        if bpy.data.filepath or any(not o.get(OWNER) for o in bpy.data.objects):
            raise ValueError("Open a separate unsaved, empty Blender session before connecting")
        self.collection = bpy.data.collections.new("Host scene — READ ONLY")
        bpy.context.scene.collection.children.link(self.collection)
        self.collection[OWNER] = True
        self.collection.hide_select = True
        self.objects = {}
        self.records = {}
        self.sketches = {}
        self.sketch_records = {}
        self.document = None

    def apply(self, state):
        bpy.context.scene.unit_settings.system = "METRIC"
        bpy.context.scene.unit_settings.scale_length = 1
        for oid in set(self.objects) - state.objects.keys():
            self._remove(oid)
        for oid, record in state.objects.items():
            obj = self.objects.get(oid)
            mesh_record = record.get("mesh")
            changed = mesh_record != self.records.get(oid, {}).get("mesh")
            # Blender cannot switch an Empty's data to a mesh (or vice versa).
            # Recreate only that owned object when its geometry type changes.
            if obj is not None and (obj.type == "MESH") != (mesh_record is not None):
                self._remove(oid)
                obj = None
            if obj is None:
                mesh = bpy.data.meshes.new(record.get("name", oid)) if mesh_record else None
                obj = bpy.data.objects.new(record.get("name", oid), mesh)
                obj[OWNER] = True
                obj["spatial_modeling_id"] = oid
                self.collection.objects.link(obj)
                self.objects[oid] = obj
                changed = True
            obj.name = record.get("name", oid)
            if mesh_record is not None and changed:
                mesh = obj.data
                mesh.clear_geometry()
                p, indices = mesh_record["positions"], mesh_record["indices"]
                mesh.from_pydata(list(zip(p[0::3], p[1::3], p[2::3], strict=True)), [],
                                 list(zip(indices[0::3], indices[1::3], indices[2::3], strict=True)))
                mesh.update()
                normals = mesh_record.get("normals")
                if normals:
                    mesh.normals_split_custom_set_from_vertices(
                        list(zip(normals[0::3], normals[1::3], normals[2::3], strict=True)))
            rgba = record.get("color") or [0.8, 0.8, 0.8, 1]
            obj.color = rgba
            if obj.type == "MESH":
                mat = obj.data.materials[0] if obj.data.materials else None
                if mat is None:
                    mat = bpy.data.materials.new("Host color")
                    mat[OWNER] = True
                    obj.data.materials.append(mat)
                mat.diffuse_color = rgba
                mat.use_nodes = True
                mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = rgba
            obj.hide_viewport = not record.get("visible", True)
            obj.hide_render = not record.get("visible", True)
            obj.hide_select = True
            # Preserve hierarchy metadata; world transforms stay flat, as in Unity.
            obj["remote_parent_id"] = record.get("parent") or ""
            transform = record["transform"]
            obj.matrix_world = Matrix.LocRotScale(Vector(transform["location"]),
                                                 Quaternion(transform["rotation"]),
                                                 Vector(transform["scale"]))
        self.records = state.objects.copy()
        for sid in set(self.sketches) - state.sketches.keys():
            self._remove_sketch(sid)
        for sid, record in state.sketches.items():
            self._apply_sketch(sid, record)
        self.sketch_records = state.sketches.copy()
        self.document = state.document.copy()
        self.collection["spatial_modeling_document"] = json.dumps(state.document, allow_nan=False)

    def _apply_sketch(self, sid, record):
        from .sketches import polylines
        obj = self.sketches.get(sid)
        if obj is None:
            curve = bpy.data.curves.new(record["name"], "CURVE")
            curve.dimensions = "3D"
            curve.resolution_u = 1
            curve.bevel_depth = .0001
            curve.bevel_resolution = 1
            obj = bpy.data.objects.new(record["name"], curve)
            obj[OWNER] = True
            obj["spatial_modeling_id"] = sid
            obj["spatial_modeling_mirror_kind"] = "host_solved_sketch"
            self.collection.objects.link(obj)
            self.sketches[sid] = obj
        if record != self.sketch_records.get(sid):
            obj.data.splines.clear()
            for points, cyclic in polylines(record):
                spline = obj.data.splines.new("POLY")
                spline.points.add(len(points) - 1)
                for point, co in zip(spline.points, points, strict=True):
                    point.co = (*co, 1)
                spline.use_cyclic_u = cyclic
            # Plain JSON preserves complete editable host records without
            # registering solver properties or executing data as Python.
            obj[SKETCH_RECORD] = json.dumps(record, sort_keys=True, allow_nan=False)
            obj["spatial_modeling_solver_status"] = record["solver"]["status"]
        obj.name = record["name"]
        obj.hide_select = True
        plane = record["plane"]
        obj.matrix_world = Matrix.LocRotScale(Vector(plane["location"]),
                                             Quaternion(plane["rotation"]), Vector((1, 1, 1)))

    def _remove_sketch(self, sid):
        obj = self.sketches.pop(sid)
        curve = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if curve.users == 0:
            bpy.data.curves.remove(curve)

    def _remove(self, oid):
        obj = self.objects.pop(oid)
        mesh = obj.data
        materials = list(mesh.materials) if mesh is not None else []
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        for mat in materials:
            if mat.get(OWNER) and mat.users == 0:
                bpy.data.materials.remove(mat)

    def clear(self):
        for oid in list(self.objects):
            self._remove(oid)
        for sid in list(self.sketches):
            self._remove_sketch(sid)
        if self.collection.name in bpy.data.collections:
            bpy.data.collections.remove(self.collection)

"""Blender objects as the wire describes them: object records and evaluated meshes.

See "Scene" in contracts/README.md. These are pure reads of Blender data on the
main thread; sync.py owns IDs, generations and revisions, and builds the
scene.snapshot and scene.update messages from what this module returns.

- record(): an object's fields except `generation` and `mesh`: name, type,
  parent, visibility, world transform and color. Cheap; sync.py compares it on
  every flush.
- evaluated_mesh(): the final geometry, as Blender shows it: after modifiers,
  with curves, surfaces, text and metaballs converted to a mesh. Read with
  foreach_get into numpy arrays, triangulated, in the object's local space in
  meters, split where normals differ. Objects without geometry (cameras,
  lights, empties and so on) have none.

Lengths are multiplied by the scene's Unit Scale (scale_length), so the wire
is always in meters: a 100 mm part is 0.1 whatever the scene settings.
Positions are rounded to 1 µm, normals and rotations to 6 decimals, and scale
factors to 6 significant digits, which hides float32 noise such as 0.99999994.
"""

import hashlib
import math

import bpy
import numpy as np

# Object types that evaluate to a mesh. Others (EMPTY, CAMERA, LIGHT, ARMATURE,
# LATTICE, SPEAKER, LIGHT_PROBE, GREASEPENCIL, CURVES, POINTCLOUD, VOLUME) send null.
GEOMETRY_TYPES = frozenset({"MESH", "CURVE", "SURFACE", "FONT", "META"})
DECIMALS = 6  # 1 µm for positions in meters


def current_scene():
    return bpy.context.scene or bpy.data.scenes[0]


def current_view_layer(scene):
    view_layer = bpy.context.view_layer
    if view_layer is None or view_layer.id_data != scene:
        view_layer = scene.view_layers[0]
    return view_layer


def _round(values, scale=1.0):
    """values * scale in float64, rounded to DECIMALS, with NaN and -0.0 turned into 0."""
    out = np.nan_to_num(values.astype(np.float64) * scale, nan=0.0, posinf=0.0, neginf=0.0)
    return np.round(out, DECIMALS) + 0.0  # -0.0 + 0.0 == 0.0


def _number(value, decimals=DECIMALS):
    return round(value, decimals) + 0.0 if math.isfinite(value) else 0.0


class Mesh:
    """An evaluated mesh as flat arrays, ready to send; `digest` tells two apart cheaply."""

    __slots__ = ("digest", "indices", "normals", "positions")

    def __init__(self, positions, normals, indices):
        self.positions = positions  # float64, meters, 3 per vertex
        self.normals = normals  # float64, 3 per vertex
        self.indices = indices  # int32, 3 per triangle, counter-clockwise from the front
        h = hashlib.blake2b(digest_size=16)
        for array in (positions, normals, indices):
            h.update(np.ascontiguousarray(array).data)
        self.digest = h.digest()

    @property
    def vertices(self):
        return len(self.positions) // 3

    @property
    def triangles(self):
        return len(self.indices) // 3

    def wire(self):
        """The `mesh` object of scene.snapshot.schema.json."""
        return {
            "positions": self.positions.tolist(),
            "normals": self.normals.tolist(),
            "indices": self.indices.tolist(),
        }


EMPTY_MESH = Mesh(np.zeros(0), np.zeros(0), np.zeros(0, np.int32))


def _read(collection, attribute, count, dtype):
    out = np.empty(count, dtype)
    collection.foreach_get(attribute, out)
    return out


def _attribute(mesh, name, field, count, dtype):
    """A built-in attribute as a flat array; the fastest way to read a mesh."""
    return _read(mesh.attributes[name].data, field, count, dtype)


def mesh_arrays(mesh, scale_length=1.0):
    """Triangulate a bpy.types.Mesh into a Mesh in meters, split where normals differ.

    Smooth meshes (normals on vertices) keep one wire vertex per used Blender
    vertex. Flat and mixed meshes get one wire vertex per distinct (vertex,
    normal) pair, comparing normals as they will be sent, so coplanar faces still
    share their vertices.
    """
    n_tris = len(mesh.loop_triangles)
    if n_tris == 0:
        return EMPTY_MESH
    n_verts, n_corners = len(mesh.vertices), len(mesh.loops)
    co = _attribute(mesh, "position", "vector", n_verts * 3, np.float32).reshape(-1, 3)
    corner_vert = _attribute(mesh, ".corner_vert", "value", n_corners, np.int32)
    tri_corners = _read(mesh.loop_triangles, "loops", n_tris * 3, np.int32)
    verts = corner_vert[tri_corners]  # vertex of each triangle corner
    domain = mesh.normals_domain
    if domain == "POINT":
        normals = _read(mesh.vertex_normals, "vector", n_verts * 3, np.float32).reshape(-1, 3)
        used = np.zeros(n_verts, bool)
        used[verts] = True  # leave out loose vertices
        new_index = np.cumsum(used, dtype=np.int64) - 1
        return Mesh(
            _round(co[used], scale_length).ravel(),
            _round(normals[used]).ravel(),
            new_index[verts].astype(np.int32),
        )
    if domain == "FACE":
        normals = _read(mesh.polygon_normals, "vector", len(mesh.polygons) * 3, np.float32)
        tri_faces = _read(mesh.loop_triangle_polygons, "value", n_tris, np.int32)
        owner = np.repeat(tri_faces, 3)  # each corner takes its face's normal
    else:  # CORNER: sharp edges or custom normals
        normals = _read(mesh.corner_normals, "vector", n_corners * 3, np.float32)
        owner = tri_corners
    # Number the distinct normals as they will be sent, then split each vertex by them.
    rounded = np.ascontiguousarray(_round(normals.reshape(-1, 3)))
    distinct, normal_of = np.unique(rounded.view(np.dtype((np.void, 24))).ravel(),
                                    return_inverse=True)
    keys = verts.astype(np.int64) * len(distinct) + normal_of.ravel()[owner]
    _, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
    return Mesh(
        _round(co[verts[first]], scale_length).ravel(),
        rounded[owner[first]].ravel(),
        inverse.astype(np.int32).ravel(),
    )


def evaluated_mesh(obj, depsgraph, scale_length=1.0):
    """The object's final geometry as a Mesh, or None if its type has no geometry."""
    if obj.type not in GEOMETRY_TYPES:
        return None
    evaluated = obj.evaluated_get(depsgraph)
    try:
        mesh = evaluated.to_mesh()
    except RuntimeError:  # "Object does not have geometry data"
        return None
    try:
        return EMPTY_MESH if mesh is None else mesh_arrays(mesh, scale_length)
    finally:
        evaluated.to_mesh_clear()


def transform(matrix_world, scale_length=1.0):
    """World `transform` (envelope.schema.json): location in meters, quaternion [w, x, y, z], scale.

    Decomposing the world matrix loses shear from a non-uniformly scaled parent.
    """
    location, rotation, scale = matrix_world.decompose()
    q = [rotation.w, rotation.x, rotation.y, rotation.z]
    length = math.sqrt(sum(c * c for c in q))
    if not (math.isfinite(length) and length > 0):  # a zero scale
        q, length = [1.0, 0.0, 0.0, 0.0], 1.0
    sign = -1.0 if q[0] < 0 else 1.0  # q and -q are the same rotation; keep w >= 0
    return {
        "location": [_number(c * scale_length) for c in location],
        "rotation": [_number(sign * c / length) for c in q],
        "scale": [float(f"{c:.6g}") + 0.0 if math.isfinite(c) else 0.0 for c in scale],
    }


def _linked_from(socket):
    links = socket.links if socket is not None and socket.is_linked else ()
    return links[0].from_node if links else None


def material_color(material):
    """Linear RGBA of the material's Base Color, or its viewport color if that is a texture."""
    rgba = list(material.diffuse_color)
    tree = material.node_tree
    output = tree.get_output_node("ALL") if tree is not None else None
    shader = _linked_from(output.inputs.get("Surface")) if output is not None else None
    if shader is not None:
        base = shader.inputs.get("Base Color") or shader.inputs.get("Color")
        if base is not None and not base.is_linked and len(getattr(base, "default_value", ())) == 4:
            rgba = list(base.default_value)
        alpha = shader.inputs.get("Alpha")
        if alpha is not None and not alpha.is_linked:
            rgba[3] = alpha.default_value
    return [_number(max(0.0, c)) for c in rgba]


def color(obj):
    """The first material's color, or None if the object has no material."""
    for slot in obj.material_slots:
        if slot.material is not None:
            return material_color(slot.material)
    return None


def record(obj, object_id, parent_id, view_layer, depsgraph, scale_length=1.0):
    """The object's wire fields except `generation` and `mesh`, in the schema's order."""
    return {
        "id": object_id,
        "name": obj.name,
        "type": obj.type,
        "parent": parent_id,
        "visible": obj.visible_get(view_layer=view_layer),
        "transform": transform(obj.evaluated_get(depsgraph).matrix_world, scale_length),
        "color": color(obj),
    }

"""Bounded modeling operations shared by controllers and reviewed AI recipes.

The catalog contains product intent, never received Python or RNA paths.
Lengths on the wire are meters; angles are radians.
"""

import copy
import math

try:
    from . import tool_catalog_extras
except ImportError:
    import tool_catalog_extras

VERSION = 1


def number(low=-1000, high=1000, default=None, integer=False):
    value = {"type": "integer" if integer else "number", "minimum": low, "maximum": high}
    if default is not None:
        value["default"] = default
    return value


def choice(*values, default=None):
    out = {"type": "string", "enum": list(values)}
    if default is not None:
        out["default"] = default
    return out


def vector(count=3, low=-1000, high=1000):
    return {"type": "array", "minItems": count, "maxItems": count,
            "items": number(low, high)}


BOOL = {"type": "boolean"}
TEXT = {"type": "string", "maxLength": 128}
LENGTH = number(.000001, 1000)
FRAME = choice("GLOBAL", "LOCAL", "NORMAL", "VIEW", "CURSOR", "GIMBAL", "PARENT", "CUSTOM", default="GLOBAL")
TRANSFORM = {"orientation": FRAME, "constraint_axis": {**vector(), "items": BOOL},
             "orientation_matrix": vector(9, -1.000001, 1.000001),
             "pivot_m": vector(), "snap_point_m": vector(), "snap_increment_m": LENGTH,
             "snap_normal": vector(3, -1, 1), "snap_align_rotation": BOOL,
             "snap_target": choice("CLOSEST", "CENTER", "MEDIAN", "ACTIVE"),
             "proportional_radius_m": number(0, 1000),
             "proportional_falloff": choice("SMOOTH", "SPHERE", "ROOT", "INVERSE_SQUARE",
                                             "SHARP", "LINEAR", "CONSTANT", "RANDOM"),
             "connected": BOOL, "projected": BOOL}

_ROWS = []


def _add(id_, components, parameters=None, required=(), outputs=(), destructive=False, modes=None):
    _ROWS.append({"id": id_, "modes": modes or (["OBJECT"] if components == ["object"] else ["EDIT_MESH"]),
                  "components": components, "parameters": {"type": "object", "properties": parameters or {},
                  "required": list(required), "additionalProperties": False},
                  "outputs": list(outputs), "destructive": destructive})


for domain in ("object", "mesh"):
    components = ["object"] if domain == "object" else ["vertex", "edge", "face"]
    for tool, key, values in (("translate", "translation_m", vector()),
                              ("rotate", "rotation", vector(4, -1.000001, 1.000001)),
                              ("scale", "scale", vector(3, -1000, 1000))):
        _add(f"{domain}.{tool}", components, {key: values, **TRANSFORM}, [key], ["selection"])

_add("object.add", ["object"], {"primitive": choice("cube", "sphere", "cylinder"),
     "location": vector(), "dimensions": vector(3, .000001, 1000)},
     ["primitive", "location", "dimensions"], ["object", "selection"])
_add("object.selection", ["object"], {}, [], ["selection"])
_add("mesh.selection", ["vertex", "edge", "face"], {}, [], ["selection"])

_add("mesh.extrude", ["vertex", "edge", "face"],
     {"translation_m": vector(), "individual": BOOL, "normal_distance_m": number(), **TRANSFORM}, ["translation_m"],
     ["new_vertices", "new_edges", "new_faces", "boundary_edges", "selection"])
_add("mesh.inset", ["face"], {"thickness_m": LENGTH, "depth_m": number(), "individual": BOOL,
     "boundary": BOOL, "even_offset": BOOL, "relative_offset": BOOL, "outset": BOOL},
     ["thickness_m"], ["inner_faces", "new_faces", "boundary_edges", "selection"])
_add("mesh.bevel", ["vertex", "edge", "face"], {"width_m": LENGTH, "segments": number(1, 64, 1, True),
     "profile": number(0, 1, .5), "vertices": BOOL, "clamp_overlap": BOOL,
     "offset_type": choice("OFFSET", "WIDTH", "DEPTH", "PERCENT", "ABSOLUTE"),
     "material_index": number(-1, 63, -1, True)}, ["width_m"],
     ["new_faces", "new_edges", "new_vertices", "selection"])
_add("mesh.loop_cut", ["edge"], {"cuts": number(1, 32, 1, True), "slide": number(-.999, .999, 0)},
     [], ["new_edges", "new_vertices", "selection"])
_add("mesh.knife", ["face", "edge", "vertex"],
     {"path_m": {"type": "array", "minItems": 2, "maxItems": 128, "items": vector()},
      "projection": {"type": "array", "minItems": 16, "maxItems": 16, "items": number(-1e9, 1e9)},
      "cut_through": BOOL, "selected_only": BOOL}, ["path_m", "projection"],
     ["new_edges", "new_vertices", "new_faces", "selection"])
_add("mesh.merge", ["vertex"], {"variant": choice("CENTER", "FIRST", "LAST", "CURSOR", "DISTANCE", default="CENTER"),
     "distance_m": LENGTH}, [], ["selection"], True)
_add("mesh.dissolve", ["vertex", "edge", "face"],
     {"variant": choice("AUTO", "LIMITED", default="AUTO"), "angle_limit": number(0, 3.141593, .0872665),
      "use_verts": BOOL, "use_face_split": BOOL}, [], ["selection"], True)
_add("mesh.delete", ["vertex", "edge", "face"],
     {"domain": choice("VERTS", "EDGES", "FACES", "ONLY_FACE", "FACES_ONLY", "EDGES_FACES")}, [], [], True)
_add("mesh.subdivide", ["edge"], {"cuts": number(1, 32, 1, True), "smooth": number(0, 1, 0)}, [], ["selection"])
_add("mesh.fill", ["edge"], {}, [], ["new_faces", "selection"])
_add("mesh.bridge", ["edge"], {"twist": number(-32, 32, 0, True)}, [], ["new_faces", "selection"])
_add("mesh.triangulate", ["face"], {}, [], ["new_faces", "selection"])
_add("mesh.split_edges", ["edge"], {}, [], ["new_edges", "selection"])
_add("mesh.recalculate_normals", ["face"], {"inside": BOOL}, [], ["selection"])
_add("mesh.flip_normals", ["face"], {}, [], ["selection"])
_add("mesh.face_material", ["face"], {"material_index": number(0, 63, integer=True)}, ["material_index"], ["selection"])
_add("mesh.face_smooth", ["face"], {"smooth": BOOL}, ["smooth"], ["selection"])
_add("mesh.edge_seam", ["edge"], {"seam": BOOL}, ["seam"], ["selection"])
_add("mesh.edge_properties", ["edge"], {"sharp": BOOL, "crease": number(0, 1), "bevel_weight": number(0, 1)}, [], ["selection"])
_add("mesh.select_region", ["vertex", "edge", "face"],
     {"region": choice("CONNECTED", "BOUNDARY", "EDGE_LOOP"),
      "selection_mode": choice("REPLACE", "ADD", "REMOVE", "TOGGLE", default="REPLACE")}, ["region"], ["selection"])
_add("mesh.slide_vertices", ["vertex"],
     {"rails": {"type": "array", "minItems": 1, "maxItems": 256, "items": number(0, 16384, integer=True)},
      "factor": number(-1, 1)}, ["rails", "factor"], ["selection"])
_add("mesh.bisect", ["vertex", "edge", "face"],
     {"plane_point_m": vector(), "plane_normal": vector(3, -1, 1), "clear_inner": BOOL, "clear_outer": BOOL},
     ["plane_point_m", "plane_normal"], ["new_edges", "selection"], True)
_add("mesh.spin", ["vertex", "edge", "face"],
     {"center_m": vector(), "axis": vector(3, -1, 1), "angle": number(-6.283186, 6.283186),
      "steps": number(1, 64, 8, True), "duplicate": BOOL}, ["center_m", "axis", "angle"], ["selection"])

for id_, props, required, destructive in (
    ("object.rename", {"name": TEXT}, ["name"], False),
    ("object.duplicate", {"translation_m": vector(), "linked": BOOL}, [], False),
    ("object.shade", {"smooth": BOOL}, ["smooth"], False),
    ("object.parent", {"parent_id": TEXT, "keep_transform": BOOL}, ["parent_id"], False),
    ("object.unparent", {}, [], False),
    ("object.visibility", {"visible": BOOL, "render": BOOL}, ["visible"], False),
    ("object.apply_transform", {"location": BOOL, "rotation": BOOL, "scale": BOOL}, [], False),
    ("object.origin", {"kind": choice("GEOMETRY", "CURSOR", "CENTER_OF_MASS", "CENTER_OF_VOLUME")}, ["kind"], False),
    ("object.delete", {}, [], True),
    ("modifier.add", {"kind": choice("BEVEL", "SUBSURF", "SOLIDIFY", "MIRROR", "ARRAY", "DECIMATE", "WELD", "TRIANGULATE", "WEIGHTED_NORMAL", "SMOOTH", "REMESH"),
                       "amount_m": LENGTH, "levels": number(0, 6, integer=True), "segments": number(1, 64, integer=True),
                       "count": number(1, 100, integer=True), "ratio": number(.001, 1),
                       "axis": choice("X", "Y", "Z")}, ["kind"], False),
    ("modifier.remove", {"name": TEXT}, ["name"], True),
    ("modifier.apply", {"name": TEXT}, ["name"], True),
    ("material.assign", {"name": TEXT, "colour": vector(4, 0, 1), "roughness": number(0, 1), "metallic": number(0, 1)}, ["name"], False),
    ("uv.layer_add", {"name": TEXT}, ["name"], False),
    ("uv.layer_remove", {"name": TEXT}, ["name"], True),
    ("animation.keyframe", {"channel": choice("location", "rotation_euler", "rotation_quaternion", "scale"), "frame": number(-100000, 100000, integer=True)}, ["channel", "frame"], False),
    ("animation.keyframe_delete", {"channel": choice("location", "rotation_euler", "rotation_quaternion", "scale"), "frame": number(-100000, 100000, integer=True)}, ["channel", "frame"], True),
    ("animation.frame", {"frame": number(-100000, 100000, integer=True)}, ["frame"], False),
):
    _add(id_, ["object"], props, required, ["object"], destructive)

_add("uv.unwrap", ["face"], {"method": choice("ANGLE_BASED", "CONFORMAL", "MINIMUM_STRETCH"),
     "margin": number(0, 1, .001)}, [], ["selection"])
_add("uv.smart_project", ["face"], {"angle_limit": number(0, 1.570797, 1.15192), "island_margin": number(0, 1, .02)}, [], ["selection"])
_add("uv.transform", ["face"], {"translation": vector(2), "scale": vector(2, -1000, 1000), "rotation": number(-6.283186, 6.283186)}, [], ["selection"])
_ROWS.extend(tool_catalog_extras.catalog())
_INDEX = {row["id"]: row for row in _ROWS}


def catalog():
    return copy.deepcopy(_ROWS)


def descriptor(tool):
    if tool not in _INDEX:
        raise ValueError(f"Unsupported modeling tool: {tool}")
    return copy.deepcopy(_INDEX[tool])


def _check(value, spec, path):
    kind = spec["type"]
    if kind in ("number", "integer"):
        if type(value) not in (int, float) or not math.isfinite(value) or (kind == "integer" and int(value) != value):
            raise ValueError(f"{path} must be a finite {kind}")
        if not spec.get("minimum", -math.inf) <= value <= spec.get("maximum", math.inf):
            raise ValueError(f"{path} is outside the allowed range")
    elif kind == "boolean":
        if type(value) is not bool:
            raise ValueError(f"{path} must be a boolean")
    elif kind == "string":
        if not isinstance(value, str) or not value.strip() or len(value) > spec.get("maxLength", 256):
            raise ValueError(f"{path} must be bounded nonempty text")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(f"{path} must be one of {spec['enum']}")
    elif kind == "array":
        if not isinstance(value, list) or not spec.get("minItems", 0) <= len(value) <= spec.get("maxItems", 256):
            raise ValueError(f"{path} has the wrong length")
        for i, item in enumerate(value):
            _check(item, spec["items"], f"{path}[{i}]")


def validate(tool, params, component=None):
    if tool in tool_catalog_extras.OPERATIONS:
        return tool_catalog_extras.validate(tool, params, component)
    row = descriptor(tool)
    if component is not None and component not in row["components"]:
        raise ValueError(f"{tool} needs {'/'.join(row['components'])} selection")
    spec = row["parameters"]
    if not isinstance(params, dict) or set(params) - set(spec["properties"]):
        raise ValueError(f"{tool} has unknown parameters")
    missing = set(spec["required"]) - set(params)
    if missing:
        raise ValueError(f"{tool} needs {', '.join(sorted(missing))}")
    out = copy.deepcopy(params)
    for key, value in params.items():
        _check(value, spec["properties"][key], key)
    for key, value in spec["properties"].items():
        if key not in out and "default" in value:
            out[key] = copy.deepcopy(value["default"])
    if tool.endswith(".scale") and any(abs(v) < .001 for v in out["scale"]):
        raise ValueError("Scale factors cannot be zero or have magnitude below .001")
    if tool.endswith(".rotate") and abs(sum(v*v for v in out["rotation"]) - 1) > .002:
        raise ValueError("Rotation must be a unit quaternion [w,x,y,z]")
    if out.get("snap_align_rotation") and ("snap_normal" not in out or sum(v*v for v in out["snap_normal"]) < 1e-10):
        raise ValueError("Snap rotation alignment needs a nonzero native surface normal")
    return out

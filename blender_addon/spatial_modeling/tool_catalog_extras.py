"""Typed finishing and data-edit operations for the native modeling service."""

import copy
import math


def number(low=-1000, high=1000, default=None, integer=False):
    spec = {"type": "integer" if integer else "number", "minimum": low, "maximum": high}
    if default is not None:
        spec["default"] = default
    return spec


def enum(*values, default=None):
    spec = {"type": "string", "enum": list(values)}
    if default is not None:
        spec["default"] = default
    return spec


def vector(size=3, low=-1000, high=1000):
    return {"type": "array", "minItems": size, "maxItems": size,
            "items": number(low, high)}


TEXT = {"type": "string", "minLength": 1, "maxLength": 128}
BOOL = {"type": "boolean"}
_ROWS = []


def add(tool, components, parameters, required=(), modes=None, destructive=False):
    _ROWS.append({"id": tool, "modes": modes or ["OBJECT"], "components": components,
                  "parameters": {"type": "object", "properties": parameters,
                                 "required": list(required), "additionalProperties": False},
                  "outputs": ["object", "selection"], "destructive": destructive})


add("uv.pin", ["face"], {"pinned": BOOL}, ["pinned"], ["EDIT_MESH"])
add("uv.pack", ["face"], {"margin": number(0, .5, .02), "rotate": BOOL}, modes=["EDIT_MESH"])
add("uv.select_island", ["face"], {}, modes=["EDIT_MESH"])
add("uv.weld", ["face"], {"limit": number(.000001, 1, .01), "midpoint": BOOL}, modes=["EDIT_MESH"])
add("uv.average_islands_scale", ["face"], {}, modes=["EDIT_MESH"])
add("uv.layer_activate", ["object"], {"name": TEXT}, ["name"])
add("uv.layer_copy", ["object"], {"name": TEXT}, ["name"])

add("vertex_group.create", ["object"], {"name": TEXT}, ["name"])
add("vertex_group.rename", ["object"], {"name": TEXT, "new_name": TEXT}, ["name", "new_name"])
add("vertex_group.remove", ["object"], {"name": TEXT}, ["name"], destructive=True)
add("vertex_group.lock", ["object"], {"name": TEXT, "locked": BOOL}, ["name", "locked"])
add("weights.assign", ["vertex"], {"name": TEXT, "weight": number(0, 1),
                                  "mode": enum("REPLACE", "ADD", "SUBTRACT", default="REPLACE")},
    ["name", "weight"], ["OBJECT", "EDIT_MESH"])
add("weights.remove", ["vertex"], {"name": TEXT}, ["name"], ["OBJECT", "EDIT_MESH"], True)
add("weights.normalize", ["vertex"], {}, modes=["OBJECT", "EDIT_MESH"])
add("weights.smooth", ["vertex"], {"name": TEXT, "factor": number(0, 1, .5),
                                  "iterations": number(1, 20, 1, True)},
    ["name"], ["OBJECT", "EDIT_MESH"])

add("material.principled", ["object"], {
    "name": TEXT, "base_colour": vector(4, 0, 1), "metallic": number(0, 1),
    "roughness": number(0, 1), "alpha": number(0, 1), "ior": number(1, 4),
    "transmission": number(0, 1), "coat": number(0, 1), "subsurface": number(0, 1),
    "emission_colour": vector(4, 0, 1), "emission_strength": number(0, 10000)})
add("material.slot_remove", ["object"], {"index": number(0, 63, integer=True)}, ["index"], destructive=True)

add("collection.create", ["object"], {"name": TEXT}, ["name"])
add("collection.rename", ["object"], {"name": TEXT, "new_name": TEXT}, ["name", "new_name"])
add("collection.visibility", ["object"], {"name": TEXT, "viewport": BOOL, "render": BOOL}, ["name"])
add("object.collection_link", ["object"], {"name": TEXT}, ["name"])
add("object.collection_unlink", ["object"], {"name": TEXT}, ["name"], destructive=True)

add("curve.spline_add", ["object"], {
    "kind": enum("POLY", "NURBS", "BEZIER", default="POLY"),
    "points_m": {"type": "array", "minItems": 2, "maxItems": 128, "items": vector()},
    "cyclic": BOOL, "endpoint": BOOL}, ["points_m"])
add("curve.point_set", ["object"], {
    "spline": number(0, 127, integer=True), "point": number(0, 4095, integer=True),
    "position_m": vector(), "radius": number(.000001, 1000), "tilt": number(-100, 100),
    "handle_type": enum("AUTO", "VECTOR", "ALIGNED", "FREE")}, ["spline", "point", "position_m"])
add("curve.spline_remove", ["object"], {"spline": number(0, 127, integer=True)}, ["spline"], destructive=True)
add("curve.settings", ["object"], {
    "dimensions": enum("2D", "3D"), "resolution": number(1, 64, integer=True),
    "bevel_depth_m": number(0, 100), "bevel_resolution": number(0, 8, integer=True),
    "extrude_m": number(0, 100), "fill_caps": BOOL,
    "fill_mode": enum("FULL", "BACK", "FRONT", "HALF")})

add("mesh.project_surface", ["vertex", "edge", "face"], {
    "surface_id": TEXT, "max_distance_m": number(.000001, 1000, .1),
    "normal_offset_m": number(-100, 100, 0)}, ["surface_id"], ["EDIT_MESH"])
add("mesh.smooth_vertices", ["vertex", "edge", "face"], {
    "factor": number(0, 1, .5), "iterations": number(1, 20, 1, True),
    "preserve_boundary": BOOL}, modes=["EDIT_MESH"])
add("mesh.poke", ["face"], {"offset_m": number(-100, 100, 0)}, modes=["EDIT_MESH"])
add("mesh.tris_to_quads", ["face"], {"angle_limit": number(0, math.pi, math.pi),
                                     "preserve_uvs": BOOL}, modes=["EDIT_MESH"])
add("mesh.unsubdivide", ["vertex"], {"iterations": number(1, 6, 1, True)}, modes=["EDIT_MESH"])

_INDEX = {row["id"]: row for row in _ROWS}
OPERATIONS = frozenset(_INDEX)


def catalog():
    return copy.deepcopy(_ROWS)


def descriptor(tool):
    if tool not in _INDEX:
        raise ValueError("Unsupported native finishing tool: " + str(tool))
    return copy.deepcopy(_INDEX[tool])


def _check(value, spec, name):
    kind = spec["type"]
    if kind in ("number", "integer"):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(name + " needs a finite number")
        if kind == "integer" and int(value) != value:
            raise ValueError(name + " needs an integer")
        if not spec["minimum"] <= value <= spec["maximum"]:
            raise ValueError(name + " is outside native bounds")
    elif kind == "boolean":
        if type(value) is not bool:
            raise ValueError(name + " needs a boolean")
    elif kind == "string":
        if not isinstance(value, str) or not value.strip() or "\x00" in value or len(value) > spec.get("maxLength", 128):
            raise ValueError(name + " needs bounded nonempty text")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(name + " has an unsupported choice")
    elif kind == "array":
        if not isinstance(value, list) or not spec["minItems"] <= len(value) <= spec["maxItems"]:
            raise ValueError(name + " has the wrong number of values")
        for index, item in enumerate(value):
            _check(item, spec["items"], name + "[" + str(index) + "]")
    else:
        raise ValueError("Unsupported parameter schema")


def validate(tool, params, component=None):
    row = descriptor(tool)
    if component is not None and component not in row["components"]:
        raise ValueError(tool + " needs " + "/".join(row["components"]) + " selection")
    spec = row["parameters"]
    if not isinstance(params, dict) or set(params) - set(spec["properties"]):
        raise ValueError(tool + " has unknown parameters")
    if set(spec["required"]) - set(params):
        raise ValueError(tool + " is missing required parameters")
    result = copy.deepcopy(params)
    for key, value in result.items():
        _check(value, spec["properties"][key], key)
    for key, value in spec["properties"].items():
        if key not in result and "default" in value:
            result[key] = copy.deepcopy(value["default"])
    return result

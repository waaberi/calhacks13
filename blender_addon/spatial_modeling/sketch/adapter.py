"""Bounded native CAD Sketcher 0.32.1 / slvs 3.2 bridge (main thread only).

No solver substitute, network, operators, Undo pushes or sync flushes live here.
The editor wraps apply() in the normal shared transaction and one native Undo step.
Edits stage a real Curves datablock with native constraint PropertyGroups. Rejection
restores the original datablock and dimension driver keys, before returning Refused.
"""

import importlib
import json
import math
import sys
import tomllib
import uuid
from importlib.metadata import version
from pathlib import Path

import bpy
from mathutils import Euler

from ..commands import Applied, Refused
from . import is_sketch

ID_PROPERTY = "spatial_modeling_id"
ALIASES = "spatial_modeling_constraint_entities"
FIXED = "spatial_modeling_fixed_constraints"
KINDS = {"coincident", "horizontal", "vertical", "distance", "angle", "diameter"}
MAX_ENTITIES = 512
MAX_CONSTRAINTS = 1024


def _module():
    for name, module in tuple(sys.modules.items()):
        if ((name == "CAD_Sketcher" or name.endswith(".CAD_Sketcher"))
                and module and hasattr(bpy.types.Curves, "sketch_constraints")):
            return module
    return None


def dependency_status():
    module = _module()
    if module is None:
        return {"available": False, "reason": "Enable CAD Sketcher 0.32.1 with slvs 3.2 in host Blender."}
    try:
        manifest = tomllib.loads(Path(module.__file__).with_name("blender_manifest.toml")
                                .read_text(encoding="utf-8"))
        importlib.import_module("slvs")  # verify the native extension actually loads
        solver_version = version("slvs")
        available = manifest["version"] == "0.32.1" and solver_version == "3.2"
        return {"available": available, "cad_sketcher": manifest["version"],
                "slvs": solver_version, "license": manifest["license"],
                "reason": "" if available else "Pinned CAD Sketcher 0.32.1 / slvs 3.2 required."}
    except (ImportError, OSError, ValueError, KeyError) as exc:
        return {"available": False, "reason": f"CAD dependency check failed: {exc}"}


def _api():
    status = dependency_status()
    if not status["available"]:
        raise Refused("failed", status["reason"])
    package = _module().__name__
    return {name: importlib.import_module(f"{package}.{path}") for name, path in (
        ("ref", "model.curve_ref"), ("sketch", "model.sketch_ref"),
        ("curves", "utilities.curve_data"), ("solver", "curve_solver"),
        ("global", "global_data"))}


def _unit():
    scale = float(f"{bpy.context.scene.unit_settings.scale_length:.7g}")
    return scale if scale > 0 else 1.0


def find(sketch_id):
    return next((obj for obj in bpy.context.view_layer.objects
                 if is_sketch(obj) and obj.get(ID_PROPERTY) == sketch_id), None)


def linked(ids):
    """Reserve all sketches sharing native data or depending on a leased plane."""
    selected = set(ids)
    out = set(selected)
    objects = list(bpy.context.view_layer.objects)
    for obj in objects:
        if not is_sketch(obj):
            continue
        plane = getattr(obj, "slvs_workplane", None) or obj.parent
        if (obj.get(ID_PROPERTY) in selected
                or plane is not None and plane.get(ID_PROPERTY) in selected
                or any(other.get(ID_PROPERTY) in selected and other.data == obj.data
                       for other in objects)):
            out.add(obj.get(ID_PROPERTY))
            if plane is not None:
                out.add(plane.get(ID_PROPERTY))
            out.update(other.get(ID_PROPERTY) for other in objects if other.data == obj.data)
    return sorted(value for value in out if value)


def _json(obj, key):
    return json.loads(obj.get(key, "{}"))


def _solver(sketch):
    if sketch.solver_state not in ("OKAY", "REDUNDANT_OK") or not sketch.geometry_solved:
        return {"status": "conflicting", "dof": None}
    dof = max(0, int(sketch.dof))
    return {"status": "fully_constrained" if dof == 0 else "free", "dof": dof}


def _check_frame(sketch):
    """The wire plane is rigid; refuse scale/shear instead of changing its meaning."""
    basis = sketch.plane_matrix.to_3x3()
    axes = [basis.col[i] for i in range(3)]
    if (any(abs(axis.length - 1) > 1e-6 for axis in axes)
            or any(abs(axes[i].dot(axes[j])) > 1e-6 for i, j in ((0, 1), (0, 2), (1, 2)))
            or abs(basis.determinant() - 1) > 1e-6):
        raise Refused("failed", f"Sketch {sketch.name} has unsupported scale, reflection or shear. "
                      "Restore a rigid unit-scale sketch plane in host Blender.")


def _record(obj, api):
    sketch = api["sketch"].Sketch(obj)
    _check_frame(sketch)
    data = obj.data
    unit = _unit()
    curve_ids = api["curves"].read_uuid_list(data, "curve_id")
    entities, fixed = [], []
    aliases = _json(obj, ALIASES)
    fixed_ids = _json(obj, FIXED)
    for cid in curve_ids:
        if not cid:
            continue
        ref = api["ref"].curve_ref(sketch, cid)
        if ref is None:
            continue
        if ref.is_point():
            entities.append({"id": cid, "kind": "point", "at": [float(x) * unit for x in ref.co]})
            if ref.fixed:
                fixed.append({"id": fixed_ids.get(cid, f"fixed_{cid}"), "kind": "fixed",
                              "entities": [cid]})
        elif ref.is_line() and ref.p1 and ref.p2:
            entities.append({"id": cid, "kind": "line",
                             "points": [ref.p1.curve_id, ref.p2.curve_id]})
        elif ref.is_circle() and ref.ct:
            entities.append({"id": cid, "kind": "circle", "center": ref.ct.curve_id,
                             "radius": float(ref.radius) * unit})
    constraints = list(fixed)
    for con in sketch.constraints.all:
        kind = con.type.lower()
        if kind not in KINDS or getattr(con, "is_reference", False):
            continue
        cid = con.constraint_uid
        refs = aliases.get(cid) or [getattr(con, f"curve_id_{i}", "") for i in (1, 2)]
        refs = [value for value in refs if value]
        entry = {"id": cid, "kind": kind, "entities": refs}
        if kind in ("distance", "angle", "diameter"):
            value = float(con.diameter if kind == "diameter" else con.value)
            entry["value"] = value if kind == "angle" else value * unit
        constraints.append(entry)
    matrix = sketch.plane_matrix
    return {"id": obj[ID_PROPERTY], "name": obj.name,
            "plane": {"location": [float(x) * unit for x in matrix.translation],
                      "rotation": list(matrix.to_quaternion())},
            "solver": _solver(sketch), "entities": entities, "constraints": constraints}


def snapshot():
    if not dependency_status()["available"]:
        return []
    api = _api()
    return [_record(obj, api) for obj in bpy.context.view_layer.objects
            if is_sketch(obj) and obj.get(ID_PROPERTY) and not obj.get("is_3d_sketch", False)]


def _bad(message):
    raise Refused("failed", message)


def _verified_geometry(record):
    """Read native geometry back independently of the solver's success flag.

    A satisfied slvs parameter alone must never claim that stored geometry moved.
    """
    entities = {entity["id"]: entity for entity in record["entities"]}

    def point(entity):
        return entity["at"]

    def line(entity):
        return [point(entities[cid]) for cid in entity["points"]]

    def near(actual, expected=0):
        return math.isclose(actual, expected, abs_tol=1e-8, rel_tol=1e-5)

    def point_line(at, segment):
        a, b = segment
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        return abs(dx * (a[1] - at[1]) - (a[0] - at[0]) * dy) / length if length else math.inf

    for con in record["constraints"]:
        kind = con["kind"]
        refs = [entities[cid] for cid in con["entities"]]
        if kind == "fixed":
            continue  # native fixed-point parameters belong to the solver's fixed group
        if kind in ("horizontal", "vertical"):
            a, b = line(refs[0]) if len(refs) == 1 else [point(ref) for ref in refs]
            axis = 1 if kind == "horizontal" else 0
            okay = near(a[axis] - b[axis])
        elif kind in ("distance", "coincident"):
            if len(refs) == 1:
                measured = math.dist(*line(refs[0]))
            elif refs[1]["kind"] == "line":
                measured = point_line(point(refs[0]), line(refs[1]))
            else:
                measured = math.dist(point(refs[0]), point(refs[1]))
            okay = near(measured, con.get("value", 0))
        elif kind == "diameter":
            okay = near(refs[0]["radius"] * 2, con["value"])
        elif kind == "angle":
            a, b = line(refs[0]), line(refs[1])
            u = [a[1][i] - a[0][i] for i in (0, 1)]
            v = [b[1][i] - b[0][i] for i in (0, 1)]
            lengths = math.hypot(*u) * math.hypot(*v)
            if lengths == 0:
                return False
            cosine = sum(u[i] * v[i] for i in (0, 1)) / lengths
            okay = near(math.acos(max(-1, min(1, cosine))), con["value"])
        else:
            continue
        if not okay:
            return False
    return True


def _applied(summary, created, solver):
    done = Applied(summary, created=created)
    done.solver = solver
    return done


def _refs(sketch, ids, api):
    refs = [api["ref"].curve_ref(sketch, cid) for cid in ids]
    if any(ref is None or not ref.valid for ref in refs):
        raise Refused("not_found", "That sketch entity no longer exists.")
    return refs


def _constraint(sketch, args, api):
    kind = args["kind"]
    ids = args["entities"]
    refs = _refs(sketch, ids, api)
    obj = sketch.target_object
    if kind == "fixed":
        if len(refs) != 1 or not refs[0].is_point():
            _bad("Fixed/anchored geometry requires one point.")
        if refs[0].fixed:
            _bad("That point is already anchored.")
        refs[0].fixed = True
        cid = uuid.uuid4().hex
        fixed = _json(obj, FIXED)
        fixed[ids[0]] = cid
        obj[FIXED] = json.dumps(fixed, sort_keys=True)
        return cid
    native_ids = list(ids)
    if kind in ("horizontal", "vertical"):
        if not (len(refs) == 1 and refs[0].is_line()
                or len(refs) == 2 and all(ref.is_point() for ref in refs)):
            _bad(f"{kind.title()} needs one line or two points.")
    elif kind == "coincident":
        if len(refs) != 2 or not refs[0].is_point() or not (refs[1].is_point() or refs[1].is_line()):
            _bad("Coincident needs a point and a point or line, in that order.")
    elif kind == "diameter":
        if len(refs) != 1 or not refs[0].is_circle():
            _bad("Diameter requires one circle.")
    elif kind == "angle":
        if len(refs) != 2 or not all(ref.is_line() for ref in refs):
            _bad("Angle requires two lines.")
    elif kind == "distance":
        if len(refs) == 1 and refs[0].is_line():
            native_ids = [refs[0].p1.curve_id, refs[0].p2.curve_id]
        elif not (len(refs) == 2 and refs[0].is_point()
                  and (refs[1].is_point() or refs[1].is_line())):
            _bad("Distance requires one line, two points, or a point followed by a line.")
    else:
        _bad("Unsupported sketch constraint.")
    kwargs = {f"curve_id_{i + 1}": value for i, value in enumerate(native_ids)}
    if "value" in args:
        kwargs["value"] = args["value"] / (1 if kind == "angle" else _unit())
    con = getattr(sketch.constraints, f"add_{kind}")(**kwargs)
    aliases = _json(obj, ALIASES)
    aliases[con.constraint_uid] = ids
    obj[ALIASES] = json.dumps(aliases, sort_keys=True)
    return con.constraint_uid


def _edit(op, sketch, args, api):
    ref = api["ref"]
    unit = _unit()
    def point(values):
        return ref.PointRef.create(sketch, [value / unit for value in values])
    if op == "sketch.add_line":
        if math.dist(args["start"], args["end"]) < 1e-6:
            _bad("A line must be at least 1 micrometer long.")
        p1, p2 = point(args["start"]), point(args["end"])
        line = ref.LineRef.create(sketch, p1, p2)
        return [p1.curve_id, p2.curve_id, line.curve_id]
    if op == "sketch.add_rectangle":
        a, b = args["corner"], args["opposite"]
        if min(abs(a[i] - b[i]) for i in (0, 1)) < 1e-6:
            _bad("Rectangle width and height must each be at least 1 micrometer.")
        points = [point(co) for co in (a, (b[0], a[1]), b, (a[0], b[1]))]
        lines = [ref.LineRef.create(sketch, points[i], points[(i + 1) % 4]) for i in range(4)]
        cons = [_constraint(sketch, {"kind": "horizontal" if i % 2 == 0 else "vertical",
                                    "entities": [line.curve_id]}, api)
                for i, line in enumerate(lines)]
        return [item.curve_id for item in (*points, *lines)] + cons
    if op == "sketch.add_circle":
        center = point(args["center"])
        circle = ref.CircleRef.create(sketch, center, args["radius"] / unit)
        return [center.curve_id, circle.curve_id]
    if op == "sketch.constrain":
        return [_constraint(sketch, args, api)]
    if op == "sketch.set_dimension":
        con = sketch.constraints.get_by_uid(args["constraint"])
        if con is None:
            raise Refused("not_found", "That dimension no longer exists.")
        kind = con.type.lower()
        if kind not in ("distance", "angle", "diameter") or con.is_reference:
            _bad("Choose a driving distance, angle or diameter dimension.")
        if kind == "angle" and args["value"] > math.pi:
            _bad("A sketch angle must be above zero and at most pi radians.")
        value = args["value"] / (1 if kind == "angle" else unit)
        if kind == "diameter" and con.setting:
            value /= 2
        con.value = value
        return []
    _bad("Unsupported sketch operation.")


def apply(op, target_id, args):
    api = _api()
    if op == "sketch.create":
        data = bpy.data.hair_curves.new("Sketch")
        obj = bpy.data.objects.new("Sketch", data)
        bpy.context.scene.collection.objects.link(obj)
        api["sketch"].stamp_sketch_props(obj)
        obj[ID_PROPERTY] = uuid.uuid4().hex
        angles = {"XY": (0, 0, 0), "XZ": (math.pi / 2, 0, 0),
                  "YZ": (math.pi / 2, 0, math.pi / 2)}
        obj.matrix_world = Euler(angles[args["plane"]]).to_matrix().to_4x4()
        obj["geometry_solved"] = True
        return _applied(f"Created {obj.name} on {args['plane']}", [obj[ID_PROPERTY]],
                        {"status": "fully_constrained", "dof": 0})
    obj = find(target_id) if isinstance(target_id, str) else target_id
    if not is_sketch(obj):
        raise Refused("not_found", "That planar CAD sketch no longer exists.")
    if obj.get("is_3d_sketch", False) or obj.library is not None or obj.data.library is not None:
        _bad("Only local editable planar sketches support these commands.")
    if obj.data.users > 1:
        _bad("This sketch shares native data. Make it single-user in host Blender before editing.")
    sketch = api["sketch"].Sketch(obj)
    _check_frame(sketch)
    original = obj.data
    staged = original.copy()
    saved_keys = {key: bpy.context.scene[key] for key in bpy.context.scene.keys()  # noqa: SIM118
                  if key.startswith("slvs:")}
    saved_props = {key: obj[key] for key in (ALIASES, FIXED, "solver_state", "dof", "geometry_solved") if key in obj}
    needs_solve = api["global"].needs_solve
    obj.data = staged
    try:
        created = _edit(op, sketch, args, api)
        if len(obj.data.curves) > MAX_ENTITIES or sum(1 for _ in sketch.constraints.all) > MAX_CONSTRAINTS:
            _bad("This bounded sketch supports at most 512 entities and 1024 constraints.")
        solver = api["solver"].CurveSolver(bpy.context, sketch)
        solved = solver.solve()
        handled = {con.constraint_uid for con in solver._constraint_by_handle.values()}
        missing = [con for con in sketch.constraints.all
                   if not getattr(con, "is_reference", False) and con.constraint_uid not in handled]
        if not solved or missing or not _verified_geometry(_record(obj, api)):
            error = Refused("solver_conflict", "The solver cannot satisfy that constraint. The sketch is unchanged.")
            error.solver = {"status": "conflicting", "dof": None}
            raise error
        result = _applied(f"{op.split('.')[-1].replace('_', ' ').title()}: {obj.name}",
                          created, _solver(sketch))
    except Exception:
        obj.data = original
        bpy.data.hair_curves.remove(staged)
        for key in tuple(bpy.context.scene.keys()):
            if key.startswith("slvs:") and key not in saved_keys:
                del bpy.context.scene[key]
        for key, value in saved_keys.items():
            bpy.context.scene[key] = value
        for key in (ALIASES, FIXED, "solver_state", "dof", "geometry_solved"):
            if key in saved_props:
                obj[key] = saved_props[key]
            elif key in obj:
                del obj[key]
        raise
    else:
        if original.users == 0:
            name = original.name
            bpy.data.hair_curves.remove(original)
            staged.name = name
        return result
    finally:
        api["global"].needs_solve = needs_solve

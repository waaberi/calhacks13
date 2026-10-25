"""The Blender side of commands: apply each op natively, read it back, commit it.

commands.py checks a command, then calls Editor.apply() on Blender's main
thread. Every op here:

- changes Blender data through bpy.data, not through operators, so the host's
  selection and active object stay as they are (selection is local to each
  client, see contracts/README.md);
- reads the result back from Blender (after a depsgraph update) and compares it
  with what was asked. If they differ, it restores what it changed and raises
  Refused, so nothing changed and no Undo step is pushed;
- is wrapped with host.undoable, so a confirmed change ends as exactly one
  named Undo step. Undo, Redo and Save push none.

Undo and Redo use Blender's own, shared history. To say what they undid, each
command's step also stores "<uuid> <summary>" in the scene's STEP_PROPERTY: if
Undo changes that marker, the step undone was that command; if not, it was a
change made directly in host Blender.

Units: numbers on the wire are meters and radians; Blender units are meters
divided by the scene's Unit Scale ("Identity, revisions and units" in
contracts/README.md).

Scene sync is sync.py: every edit ends with sync.flush() inside its Undo step,
so IDs given during the flush are part of it and every client has the
scene.update before the sender has the result; the flush's revision goes into
the receipt. generation(), find_object() and object_id() come from it too.

linked() tells leases.py what else a lease on some objects must cover (P3B).
"""

import logging
import math
import os
import uuid

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

from . import sketch
from .commands import SKETCH_OPS, Applied, Refused

STEP_PROPERTY = "spatial_modeling_step"  # on the scene: the last command's Undo step
PRIMITIVES = {"cube": "Cube", "sphere": "Sphere", "cylinder": "Cylinder"}
SEGMENTS = 32  # around a sphere or cylinder, as Blender's own Add menu
RINGS = 16
AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
EULER_MODES = ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX")
TOLERANCE = 1e-5  # relative; Blender keeps transforms as 32-bit floats
UNIT_QUATERNION = 1e-3  # how far from length 1 rotate.to may be
MAX_DISTANCE = 100_000.0  # meters from the origin a command may move an object
SCALE_LIMITS = (1e-6, 1e6)  # the scale factors a command may leave on an object
MODE_NAMES = {"EDIT_MESH": "Edit Mode", "SCULPT": "Sculpt Mode", "POSE": "Pose Mode"}

log = logging.getLogger(__name__)


class Editor:
    """commands.Commands' editor in Blender.

    sync: the sync module (tests pass a fake). undoable: host.undoable. document:
    the open document.Document, told about saves (see Document.saved).
    """

    def __init__(self, sync, undoable, document=None, voice=None):
        if voice is not None:
            voice.editor = self
        self.voice = voice  # voice_ops.Voice runs voice.run; without one it is refused
        self.sync = sync
        self.document = document
        self.supports_sketches = callable(getattr(sketch, "apply", None))
        commit = undoable(lambda done: done.summary)  # the Undo step is named after the edit
        self._ops = {
            op: commit(self._published(fn))
            for op, fn in (
                ("object.add", self._add),
                ("object.move", self._move),
                ("object.rotate", self._rotate),
                ("object.scale", self._scale),
                ("object.delete", self._delete),
                ("object.spatial_edit", self._spatial_edit),
                ("voice.run", self._voice_run),
            )
        }
        if self.supports_sketches:
            for op in SKETCH_OPS:
                def apply_sketch(target_id, args, operation=op):
                    return sketch.apply(operation, target_id, args)
                self._ops[op] = commit(self._published(apply_sketch))

    def command_targets(self, op, args, conn):
        return self.voice.command_targets(args, conn) if op == "voice.run" and self.voice else {}

    def flush(self):
        return self.sync.flush()

    def generation(self, object_id):
        return self.sync.generation(object_id)  # None: no such object

    def names(self, ids):
        """{ID: object name} for the IDs that are objects here (SpacetimeDB's `label` table)."""
        objects = ((i, self.sync.find_object(i)) for i in ids)
        return {i: obj.name for i, obj in objects if obj is not None}

    def linked(self, ids):
        """The IDs of the objects that changing the objects `ids` can change too.

        Followed transitively from each object: the other objects that share its
        data (a mesh or curve: editing it edits theirs), its children (their world
        transforms follow it; deleting it re-parents them), and the objects whose
        modifiers or constraints use it (a Boolean cutter, a Mirror or Array
        object, a constraint target, Geometry Nodes object inputs). IDs that
        aren't objects, such as sketches, add nothing: a sketch is leased by its ID.
        """
        start = [o for o in (self.sync.find_object(i) for i in ids) if o is not None]
        users, children, dependents = {}, {}, {}
        for obj in bpy.context.view_layer.objects:
            if obj.data is not None:
                users.setdefault(obj.data.session_uid, []).append(obj)
            if obj.parent is not None:
                children.setdefault(obj.parent.session_uid, []).append(obj)
            for used in _references(obj):
                dependents.setdefault(used.session_uid, []).append(obj)
        found = {o.session_uid: o for o in start}
        queue = list(start)
        while queue:
            obj = queue.pop()
            near = children.get(obj.session_uid, []) + dependents.get(obj.session_uid, [])
            if obj.data is not None:
                near += users.get(obj.data.session_uid, [])
            for other in near:
                if other.session_uid not in found:
                    found[other.session_uid] = other
                    queue.append(other)
        result = [self.sync.object_id(o) for o in found.values()]
        linked_sketches = getattr(sketch, "linked", None)
        if linked_sketches is not None:
            result.extend(i for i in linked_sketches([*ids, *result]) if i not in result)
        return result

    def apply(self, op, target_id, args):
        from . import live_edit
        live_edit.ensure_no_active()
        mode = bpy.context.mode
        spatial_mesh = (mode == "EDIT_MESH" and op == "object.spatial_edit" or
                        mode in ("EDIT_MESH", "POSE") and op in ("history.undo", "history.redo"))
        if mode != "OBJECT" and op == "voice.run" and self.voice is not None:
            recipe = getattr(self.voice, "is_recipe", None)
            spatial_mesh = callable(recipe) and recipe(args)
        if op != "document.save" and mode != "OBJECT" and not spatial_mesh:
            name = MODE_NAMES.get(mode, mode.replace("_", " ").title())
            raise Refused("failed", f"Host Blender is in {name}. Switch it to Object Mode first.")
        if op == "document.save":
            return self._save()
        try:
            if op in ("history.undo", "history.redo"):
                return self._history(undo=op == "history.undo")
            if op in SKETCH_OPS:
                if not self.supports_sketches:
                    raise Refused("failed", "Sketches aren't available on this host yet.")
                try:
                    return self._ops[op](target_id, args)
                except Refused:
                    raise
                except Exception:
                    self._incomplete(op)
                    raise
            return self._object_op(op, target_id, args)
        except Refused:
            raise  # nothing changed
        except Exception:
            self._edited()  # it may have changed
            raise

    def _object_op(self, op, target_id, args):
        obj = None
        if target_id is not None:
            obj = self.sync.find_object(target_id)
            if obj is None:
                raise Refused("not_found", "That object doesn't exist (any more).")
            is_sketch = getattr(sketch, "is_sketch", None)
            if is_sketch is not None and is_sketch(obj):
                raise Refused("failed", "Use the sketch tools to edit this native sketch.")
            if obj.library is not None:
                raise Refused("failed", f"{obj.name} is linked from another file, so it can't "
                              "be changed here.")
        try:
            done = self._ops[op](obj, args)
        except Refused:
            raise  # nothing changed
        except Exception:
            self._incomplete(op)
            raise
        return done

    def _edited(self):
        if self.document is not None:
            self.document.edited()

    def _published(self, fn):
        """fn, then mark the scene with its step (see the module docstring) and flush.

        undoable() pushes the step after this returns, so the flush's IDs are in it.
        """

        def run(obj, args):
            done = fn(obj, args)
            self._edited()  # the flush comes before the Undo step that sets is_dirty
            _scene()[STEP_PROPERTY] = f"{uuid.uuid4().hex} {done.summary}"
            done.revision = self.sync.flush()  # raises if serializing fails: unknown outcome
            return done

        return run

    def _incomplete(self, op):
        """An op failed halfway: keep whatever it changed in its own Undo step."""
        try:
            bpy.ops.ed.undo_push(message=f"Incomplete {op}")
        except Exception:
            log.exception("could not push an Undo step after %s failed", op)

    # Objects

    def _spatial_edit(self, obj, args):
        from . import spatial_model_edit
        return spatial_model_edit.apply(self, obj, args)

    def _add(self, _obj, args, stage=False):
        unit = _unit()
        kind = args["primitive"]
        size = [v / unit for v in args["dimensions"]]
        location = [v / unit for v in args["location"]]
        name = PRIMITIVES[kind]
        mesh = bpy.data.meshes.new(name)
        bm = bmesh.new()
        try:
            if kind == "cube":
                bmesh.ops.create_cube(bm, size=1.0)
            elif kind == "sphere":
                bmesh.ops.create_uvsphere(bm, u_segments=SEGMENTS, v_segments=RINGS, radius=0.5)
            else:
                bmesh.ops.create_cone(bm, cap_ends=True, segments=SEGMENTS, radius1=0.5,
                                      radius2=0.5, depth=1.0)
            low = [min(v.co[i] for v in bm.verts) for i in range(3)]
            high = [max(v.co[i] for v in bm.verts) for i in range(3)]
            for v in bm.verts:  # centered, and exactly `dimensions` across
                v.co = [(v.co[i] - (low[i] + high[i]) / 2) * size[i] / (high[i] - low[i])
                        for i in range(3)]
            bm.to_mesh(mesh)
        finally:
            bm.free()
        obj = bpy.data.objects.new(name, mesh)
        obj.location = location
        _collection().objects.link(obj)

        bpy.context.view_layer.update()
        expected = Matrix.Translation(location)
        if not (_same(obj.matrix_world, expected) and _close(obj.dimensions, size)):
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)
            raise Refused("failed", f"Blender didn't make the {kind} as asked. Nothing changed.")
        if not stage:
            self._edited()  # before object_id()'s flush
        if stage:
            from .sync import stage_object_id
            object_id = stage_object_id(obj)
        else:
            object_id = self.sync.object_id(obj)  # given now, inside this Undo step
        return Applied(f"Added {obj.name} ({_mm3(args['dimensions'])} mm)", created=[object_id])

    def _move(self, obj, args):
        _check_transformable(obj)
        unit = _unit()
        old = _world(obj)
        if "by" in args:
            delta = [v / unit for v in args["by"]]
        else:
            delta = [v / unit - old.translation[i] for i, v in enumerate(args["to"])]
        target = [old.translation[i] + delta[i] for i in range(3)]
        _check_distance(obj, target, unit)
        saved = _channels(obj)
        if obj.parent is None:  # world location = location + delta_location, exactly
            if "to" in args:
                obj.location = [v / unit - obj.delta_location[i] for i, v in enumerate(args["to"])]
            else:
                obj.location = [obj.location[i] + delta[i] for i in range(3)]
        else:
            obj.location = obj.location + _parent_space(obj).to_3x3().inverted() @ Vector(delta)
        expected = old.copy()
        expected.translation = target
        _confirm(obj, expected, saved, "move")
        if "by" in args:
            summary = _moved(obj.name, args["by"])
        else:
            summary = f"Moved {obj.name} to ({', '.join(_mm(v) for v in args['to'])}) mm"
        return Applied(summary)

    def _rotate(self, obj, args):
        _check_transformable(obj)
        old = _world(obj)
        world = old.to_quaternion()
        if "by" in args:
            axis, angle = args["by"]["axis"], args["by"]["angle"]
            turn = Quaternion(AXES[axis], angle)
            summary = f"Rotated {obj.name} {round(math.degrees(angle), 3):g}° about {axis}"
        else:
            wanted = Quaternion(args["to"])
            if abs(wanted.magnitude - 1) > UNIT_QUATERNION:
                raise Refused("failed", "args.to must be a unit quaternion [w, x, y, z].")
            wanted.normalize()
            turn = wanted @ world.inverted()
            summary = f"Set the rotation of {obj.name}"
        expected = turn.to_matrix().to_4x4() @ old.to_3x3().to_4x4()
        expected.translation = old.translation  # about the object's origin
        saved = _channels(obj)
        plain = obj.parent is None and _no_delta_rotation(obj)
        mode = obj.rotation_mode
        if plain and "by" in args and mode in EULER_MODES and mode[-1] == axis:
            euler = list(obj.rotation_euler)  # the outermost Euler axis: one exact addition
            euler["XYZ".index(axis)] += angle
            obj.rotation_euler = euler
        elif plain and "to" in args:
            _set_rotation(obj, wanted)
        elif plain:
            _set_rotation(obj, turn @ _rotation(obj))
        else:  # world rotation = before @ channel, before being the parent and delta rotation
            before = world @ _rotation(obj).inverted()
            _set_rotation(obj, before.inverted() @ turn @ world)
        _confirm(obj, expected, saved, "rotate")
        return Applied(summary)

    def _scale(self, obj, args):
        _check_transformable(obj)
        old = _world(obj)
        if "by" in args:
            factors = list(args["by"])
            summary = f"Scaled {obj.name} by {_factors(factors)}"
        else:
            lengths = [old.col[i].xyz.length for i in range(3)]  # the world scale factors
            if min(lengths) <= 0:
                raise Refused("failed", f"{obj.name} has a zero scale, so it can't be set.")
            factors = [args["to"][i] / lengths[i] for i in range(3)]
            summary = f"Set the scale of {obj.name} to {_factors(args['to'])}"
        if obj.parent is None and tuple(obj.delta_scale) == (1, 1, 1) and "to" in args:
            scale = [math.copysign(args["to"][i], obj.scale[i]) for i in range(3)]
        else:
            scale = [obj.scale[i] * factors[i] for i in range(3)]
        low, high = SCALE_LIMITS
        if not all(low <= abs(s) <= high for s in scale):
            raise Refused("failed", f"That would scale {obj.name} beyond {low:g} to {high:g}.")
        expected = old @ Matrix.Diagonal((*factors, 1.0))  # along the object's own axes
        saved = _channels(obj)
        obj.scale = scale
        _confirm(obj, expected, saved, "scale")
        return Applied(summary)

    def _delete(self, obj, _args):
        name = obj.name
        bpy.context.view_layer.update()
        children = [(child, child.matrix_world.copy()) for child in obj.children]
        for child, matrix in children:  # children stay where they are, as in the fake host
            child.parent = None
            child.matrix_world = matrix
        bpy.data.objects.remove(obj, do_unlink=True)
        if name in bpy.data.objects:
            raise RuntimeError(f"{name} is still there after deleting it")  # unknown outcome
        return Applied(f"Deleted {name}")

    def _voice_run(self, obj, args):
        if self.voice is None:
            raise Refused("failed", "This host doesn't take voice commands.")
        return self.voice.run(obj, args)  # voice_ops.py: selection kept, too heavy refused

    # History and file

    def _history(self, undo):
        operator, word = (bpy.ops.ed.undo, "undo") if undo else (bpy.ops.ed.redo, "redo")
        if not operator.poll():
            raise Refused("failed", f"There is nothing to {word} in Blender.")
        before = _scene().get(STEP_PROPERTY)
        selection = _selection()
        result = operator()
        if "FINISHED" not in result:
            raise Refused("failed", f"Blender didn't {word}.")
        self._edited()
        _restore_selection(selection)  # host selection isn't part of shared history
        after = _scene().get(STEP_PROPERTY)
        step = (before if undo else after) if before != after else None
        verb = "Undid" if undo else "Redid"
        if isinstance(step, str) and " " in step:
            done = Applied(f"{verb}: {step.split(' ', 1)[1]}")
        else:
            done = Applied(f"{verb} a change made in host Blender")
        done.revision = self.sync.flush()  # sync marked everything changed after the Undo
        return done

    def _save(self):
        path = bpy.data.filepath
        if not path:
            raise Refused("failed", "This file has never been saved. Save it once in host "
                          "Blender (File > Save As); clients can't choose where files go.")
        name = bpy.path.basename(path)
        before = _file_state(path)
        try:
            result = bpy.ops.wm.save_mainfile()
        except RuntimeError as e:  # Blender writes a temporary file first: the old one is intact
            raise Refused("failed", f"Blender couldn't save {name}: {e}") from e
        if "FINISHED" not in result:
            raise Refused("failed", f"Blender didn't save {name}.")
        after = _file_state(path)
        if after is None or after == before:  # read back: the file on disk must be new
            raise RuntimeError(f"Blender reported saving {name}, but the file didn't change")
        if self.document is not None:
            self.document.saved()  # bpy.data.is_dirty clears only after this tick
        done = Applied(f"Saved {name}")
        done.revision = self.sync.flush()  # sends the dirty flag; the revision stays
        return done


# Linked data


def _references(obj):
    """The objects obj's modifiers and constraints use (through Object or Collection fields)."""
    for item in (*obj.modifiers, *obj.constraints):
        values = _pointers(item)
        inputs = getattr(getattr(item, "properties", None), "inputs", None)
        if getattr(item, "type", None) == "NODES" and inputs is not None:
            values += [getattr(socket, "value", None) for socket in _pointers(inputs)]
        for value in values:
            if isinstance(value, bpy.types.Object) and value != obj:
                yield value
            elif isinstance(value, bpy.types.Collection):
                yield from (o for o in value.all_objects if o != obj)


def _pointers(struct):
    """The values of struct's pointer properties: Geometry Nodes inputs in Blender 5 are
    modifier.properties.inputs.<socket>.value."""
    return [getattr(struct, prop.identifier, None) for prop in struct.bl_rna.properties
            if prop.type == "POINTER" and prop.identifier != "rna_type"]


# Reading and writing transforms


def _file_state(path):
    """What changes when a file is written again: Blender replaces it by renaming."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size, st.st_ino


def _scene():
    return bpy.context.scene or bpy.data.scenes[0]


def _unit():
    """Meters per Blender unit: the Unit Scale as typed, 0.001 rather than its float32."""
    scale = float(f"{_scene().unit_settings.scale_length:.7g}")  # as document.units() reports
    return scale if scale > 0 else 1.0


def _collection():
    """Where Blender's own Add menu would put a new object."""
    layer = bpy.context.view_layer.active_layer_collection
    if layer is not None and not layer.exclude and layer.collection.library is None:
        return layer.collection
    return _scene().collection


def _check_transformable(obj):
    if any(c.enabled for c in obj.constraints):
        raise Refused("failed", f"{obj.name} has constraints, so Blender may not put it where "
                      "asked. Change it in host Blender.")
    if bpy.context.view_layer.objects.get(obj.name) != obj:
        raise Refused("failed", f"{obj.name} isn't in the view layer that host Blender shows.")


def _check_distance(obj, target, unit):
    if any(abs(v * unit) > MAX_DISTANCE for v in target):
        raise Refused("failed", f"That would move {obj.name} more than "
                      f"{MAX_DISTANCE / 1000:g} km from the origin.")


def _world(obj):
    bpy.context.view_layer.update()
    return obj.matrix_world.copy()


def _parent_space(obj):
    """W with matrix_world == W @ matrix_basis (constraints were ruled out)."""
    try:
        return obj.matrix_world @ obj.matrix_basis.inverted()
    except ValueError:  # a zero scale
        raise Refused("failed", f"{obj.name} or its parent has a zero scale.") from None


def _channels(obj):
    return (obj.location.copy(), obj.rotation_euler.copy(), obj.rotation_quaternion.copy(),
            tuple(obj.rotation_axis_angle), obj.scale.copy())


def _restore(obj, saved):
    (obj.location, obj.rotation_euler, obj.rotation_quaternion, obj.rotation_axis_angle,
     obj.scale) = saved


def _rotation(obj):
    """The object's own rotation channels as a quaternion."""
    mode = obj.rotation_mode
    if mode == "QUATERNION":
        return obj.rotation_quaternion.normalized()
    if mode == "AXIS_ANGLE":
        angle, *axis = obj.rotation_axis_angle
        return Quaternion(axis, angle)
    return obj.rotation_euler.to_quaternion()


def _set_rotation(obj, q):
    mode = obj.rotation_mode
    if mode == "QUATERNION":
        old = obj.rotation_quaternion
        obj.rotation_quaternion = -q if q.dot(old) < 0 else q
    elif mode == "AXIS_ANGLE":
        axis, angle = q.to_axis_angle()
        obj.rotation_axis_angle = (angle, *axis)
    else:
        obj.rotation_euler = q.to_euler(mode, obj.rotation_euler)  # closest to the old angles


def _no_delta_rotation(obj):
    return (tuple(obj.delta_rotation_euler) == (0, 0, 0)
            and tuple(obj.delta_rotation_quaternion) == (1, 0, 0, 0))


def _confirm(obj, expected, saved, verb):
    """Read the world matrix back; if it isn't what was asked, undo the change and refuse."""
    bpy.context.view_layer.update()
    if _same(obj.matrix_world, expected):
        return
    _restore(obj, saved)
    bpy.context.view_layer.update()
    raise Refused("failed", f"Blender can't {verb} {obj.name} exactly as asked (a driver, or a "
                  "parent scaled unevenly?). Nothing changed.")


def _close(values, wanted, tolerance=TOLERANCE):
    size = max(1.0, *(abs(v) for v in wanted))
    return all(abs(a - b) <= tolerance * size for a, b in zip(values, wanted, strict=True))


def _same(matrix, expected):
    rows = [x for row in matrix.to_3x3() for x in row]
    wanted = [x for row in expected.to_3x3() for x in row]
    return _close(rows, wanted) and _close(matrix.translation, expected.translation)


# Host selection


def _selection():
    layer = bpy.context.view_layer
    active = layer.objects.active
    return {o.name for o in layer.objects if o.select_get()}, active.name if active else None


def _restore_selection(selection):
    names, active = selection
    layer = bpy.context.view_layer
    for obj in layer.objects:
        selected = obj.name in names
        if obj.select_get() != selected:
            try:
                obj.select_set(selected)
            except RuntimeError:  # can't be selected here, for example hidden
                pass
    layer.objects.active = layer.objects.get(active) if active else None


# Summaries


def _mm(meters):
    text = f"{meters * 1000:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _mm3(values):
    return " x ".join(_mm(v) for v in values)


def _factors(values):
    return " x ".join(f"{round(v, 6):g}" for v in values)


def _moved(name, by):
    axes = [i for i in range(3) if by[i] != 0]
    if len(axes) == 1:
        return f"Moved {name} {_mm(by[axes[0]])} mm along {'XYZ'[axes[0]]}"
    return f"Moved {name} by ({', '.join(_mm(v) for v in by)}) mm"

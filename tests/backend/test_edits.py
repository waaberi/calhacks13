"""The real editor (edits.py) in Blender: every op over real sockets, read back natively.

Needs the bpy module (pip install bpy==5.2.2); skipped without it, as in CI. The
host runs in this process as host.py wires it, real scene sync (sync.py)
included, with Blender's main thread (this one) draining the server while
clients run on worker threads. Each test starts from Blender's factory scene,
whose objects get fixed IDs first so the tests can name them.

Edits the tests make directly in Blender are direct edits like any other: sync
gives them a new revision. So Blender.run() looks again before each command,
for the target's current generation and the current revision. Every message is
checked against contracts/schemas (Peer from test_commands.py).
"""

import contextlib
import ctypes
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("BLENDER_USER_RESOURCES", tempfile.mkdtemp(prefix="ch13-bpy-"))
bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "blender_addon"))

# isort: split
from mathutils import Matrix, Quaternion, Vector
from spatial_modeling import commands, document, edits, host, leases, server, session, sync
from test_commands import Peer, assert_rejected
from test_leases import acquire

pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")

CUBE = "c0be00000000400080000000000000c1"
CAMERA = "ca3e00000000400080000000000000c2"
LIGHT = "11900000000040008000000000000003"
SESSION_ID = "2f05d1eb3f1e4ce98dd998abf20cdd33"


def f32(x):
    """x as Blender stores it: a 32-bit float."""
    return struct.unpack("f", struct.pack("f", x))[0]


def undo_steps():
    """Blender's Undo stack as [(name, active)], oldest first.

    Python can't read it, so this captures what print_undo_steps() writes to C stdout.
    """
    sys.stdout.flush()
    with tempfile.TemporaryFile() as out:
        saved = os.dup(1)
        os.dup2(out.fileno(), 1)
        try:
            bpy.context.window_manager.print_undo_steps()
            ctypes.CDLL(None).fflush(None)
        finally:
            os.dup2(saved, 1)
            os.close(saved)
        out.seek(0)
        text = out.read().decode("utf-8", "replace")
    return [(name, "*" in flags)
            for flags, name in re.findall(r"\[(.{4})\]\s+\d+ \{\S+\} type='[^']*', name='(.*)'",
                                          text)]


def last_step():
    steps = undo_steps()
    return next(name for name, active in steps if active), len(steps)


class Spy:
    """sync.py, recording every call edits.py makes and how many Undo steps there were."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        real = getattr(sync, name)

        def call(*args):
            self.calls.append((name, len(undo_steps())))
            return real(*args)

        return call


class Blender:
    """A host on a free port in this process. call() runs client code while Blender drains."""

    def __init__(self, srv, sess, cmds, doc):
        self.srv, self.sess, self.cmds, self.doc = srv, sess, cmds, doc

    def call(self, fn, *args, timeout=15.0, **kwargs):
        box = []

        def run():
            try:
                box.append((True, fn(*args, **kwargs)))
            except BaseException as e:  # noqa: BLE001 - re-raised on this thread
                box.append((False, e))

        threading.Thread(target=run, daemon=True).start()
        deadline = time.monotonic() + timeout
        while not box:
            self.srv.drain()
            time.sleep(0.001)
            assert time.monotonic() < deadline, f"{fn.__name__} got no reply"
        ok, value = box[0]
        if not ok:
            raise value
        return value

    def peer(self, name="Talia"):
        peer = Peer(self.srv.port)
        self.call(peer.join, name)
        return peer

    def command(self, peer, op, target=None, args=None, **fields):
        """peer's command, as of now: the target's current generation, the current revision."""
        if isinstance(target, str):
            target = {"id": target, "generation": sync.generation(target)}
        fields.setdefault("base_revision", sync.flush())
        return peer.command(op, target, args, **fields)

    def ask(self, peer, msg):
        return self.call(peer.ask, msg)

    def run(self, peer, *args, **kwargs):
        """peer runs a command; returns its receipt."""
        return self.ask(peer, self.command(peer, *args, **kwargs))[1]["payload"]


def fresh_scene(scale_length=1.0):
    bpy.ops.wm.read_factory_settings(use_empty=False)
    for name, oid in (("Cube", CUBE), ("Camera", CAMERA), ("Light", LIGHT)):
        bpy.data.objects[name][sync.ID_PROPERTY] = oid  # sync keeps valid IDs
    units = bpy.context.scene.unit_settings
    if scale_length != 1.0:
        units.system, units.length_unit, units.scale_length = "METRIC", "MILLIMETERS", scale_length
    bpy.ops.ed.undo_push(message="Original")  # the bpy module starts without an Undo step


@contextlib.contextmanager
def blender(scale_length=1.0, spy=False, client_can_edit=False):
    fresh_scene(scale_length)
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, SESSION_ID,
                           client_can_edit=client_can_edit)
    sync.register()
    sync.start(doc, sess)
    heartbeat, server.HEARTBEAT_TIMEOUT = server.HEARTBEAT_TIMEOUT, 120.0  # the peers don't ping
    try:
        editor = edits.Editor(Spy() if spy else sync, host.undoable, doc)
        lses = leases.Leases(sess, editor)
        cmds = commands.Commands(sess, editor, leases=lses)
        srv = lses.attach(cmds.attach(sess.attach(server.Server(port=0))))
        srv.start()
        try:
            yield Blender(srv, sess, cmds, doc)
        finally:
            srv.stop()
    finally:
        server.HEARTBEAT_TIMEOUT = heartbeat
        sync.unregister()


def obj(oid):
    return next(o for o in bpy.data.objects if o.get(sync.ID_PROPERTY) == oid)


def selection():
    layer = bpy.context.view_layer
    active = layer.objects.active
    return sorted(o.name for o in layer.objects if o.select_get()), active and active.name


def world(o):
    bpy.context.view_layer.update()
    return o.matrix_world.copy()


def assert_matrix(m, expected, tolerance=1e-6):
    for i in range(4):
        for j in range(4):
            assert abs(m[i][j] - expected[i][j]) <= tolerance, (m, expected)


# Add


@pytest.mark.parametrize("scale_length", [1.0, 0.001], ids=["meters", "millimeters"])
@pytest.mark.parametrize("primitive, faces", [("cube", 6), ("sphere", 32 * 16),
                                              ("cylinder", 32 + 2)])
def test_add_makes_a_native_primitive_of_the_asked_size(primitive, faces, scale_length):
    with blender(scale_length) as b, b.peer() as talia:
        before, (_, steps) = selection(), last_step()
        args = {"primitive": primitive, "location": [0.01, -0.02, 0.005],
                "dimensions": [0.1, 0.06, 0.01]}
        receipt = b.run(talia, "object.add", args=args)
        assert receipt["outcome"] == "applied", receipt
        (new,) = receipt["created"]
        o = obj(new)
        name = {"cube": "Cube.001", "sphere": "Sphere", "cylinder": "Cylinder"}[primitive]
        assert o.name == name and o.type == "MESH" and len(o.data.polygons) == faces
        assert receipt["summary"] == f"Added {name} (100 x 60 x 10 mm)"
        unit = scale_length
        for got, meters in zip(o.dimensions, args["dimensions"], strict=True):
            assert abs(got * unit - meters) <= 1e-6 * meters, (tuple(o.dimensions), unit)
        assert tuple(o.location) == tuple(f32(v / unit) for v in args["location"])
        assert tuple(o.scale) == (1, 1, 1) and tuple(o.rotation_euler) == (0, 0, 0)
        assert o.users_collection[0] == bpy.context.view_layer.active_layer_collection.collection
        assert not o.select_get() and selection() == before, "the host's selection changed"
        assert last_step() == (receipt["summary"], steps + 1), "not exactly one Undo step"
        assert bpy.data.is_dirty


def test_an_added_object_can_be_edited_next():
    with blender() as b, b.peer() as talia:
        add = b.run(talia, "object.add", args={"primitive": "cube", "location": [0, 0, 0],
                                               "dimensions": [1, 1, 1]})
        target = {"id": add["created"][0], "generation": add["revision"]}
        assert b.run(talia, "object.move", target, {"by": [1, 0, 0]})["outcome"] == "applied"


# Move, rotate, scale


@pytest.mark.parametrize("scale_length", [1.0, 0.001], ids=["meters", "millimeters"])
def test_a_10_mm_move_is_exact(scale_length):
    with blender(scale_length) as b, b.peer() as talia:
        cube = obj(CUBE)
        cube.location = (0.02 / scale_length, 0, 0)
        start = cube.location.x
        receipt = b.run(talia, "object.move", CUBE, {"by": [0.01, 0, 0]})
        assert receipt["outcome"] == "applied" and receipt["summary"] == "Moved Cube 10 mm along X"
        assert cube.location.x == f32(start + 0.01 / scale_length)
        assert tuple(cube.location)[1:] == (0, 0)
        assert last_step()[0] == "Moved Cube 10 mm along X"


def test_move_to_sets_the_world_location():
    with blender(0.001) as b, b.peer() as talia:
        receipt = b.run(talia, "object.move", CUBE, {"to": [0.1, -0.05, 0.002]})
        assert receipt["summary"] == "Moved Cube to (100, -50, 2) mm"
        assert tuple(obj(CUBE).location) == (100, -50, 2)


def test_a_90_degree_rotation_is_exact():
    with blender() as b, b.peer() as talia:
        cube = obj(CUBE)
        receipt = b.run(talia, "object.rotate", CUBE,
                        {"by": {"axis": "Z", "angle": math.pi / 2}})
        assert receipt["summary"] == "Rotated Cube 90° about Z"
        assert tuple(cube.rotation_euler) == (0, 0, f32(math.pi / 2))
        exact = Matrix(((0, -1, 0, 0), (1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))
        assert_matrix(world(cube), exact, 1e-7)  # cos(float32(pi/2)) is -4.4e-8
        receipt = b.run(talia, "object.rotate", {"id": CUBE, "generation": receipt["revision"]},
                        {"by": {"axis": "Z", "angle": math.pi / 2}})
        assert tuple(cube.rotation_euler) == (0, 0, f32(f32(math.pi / 2) + math.pi / 2))


@pytest.mark.parametrize("mode", ["XYZ", "ZXY", "YZX", "QUATERNION", "AXIS_ANGLE"])
def test_rotate_turns_about_a_world_axis_through_the_origin(mode):
    with blender() as b, b.peer() as talia:
        cube = obj(CUBE)
        cube.location = (1, 2, 3)
        cube.rotation_mode = mode
        cube.rotation_euler = (0.3, 0.2, 0.1)
        cube.rotation_quaternion = Quaternion((0.9, 0.1, 0.3, 0.2)).normalized()
        cube.rotation_axis_angle = (0.5, 0, 0.6, 0.8)
        cube.scale = (1, 2, 3)
        old = world(cube)
        b.run(talia, "object.rotate", CUBE, {"by": {"axis": "X", "angle": 0.7}})
        turned = Matrix.Rotation(0.7, 4, "X") @ old.to_3x3().to_4x4()
        turned.translation = old.translation
        assert_matrix(world(cube), turned, 1e-5)
        assert cube.rotation_mode == mode


def test_rotate_to_sets_the_world_rotation():
    with blender() as b, b.peer() as talia:
        cube = obj(CUBE)
        cube.scale = (1, 2, 3)
        wanted = Quaternion((0, 0, 1), math.pi / 2)
        b.run(talia, "object.rotate", CUBE, {"to": list(wanted)})
        expected = wanted.to_matrix().to_4x4() @ Matrix.Diagonal((1, 2, 3, 1))
        assert_matrix(world(cube), expected, 1e-6)


def test_rotate_to_needs_a_unit_quaternion():
    with blender() as b, b.peer() as talia:
        _, steps = last_step()
        error = assert_rejected(b.run(talia, "object.rotate", CUBE, {"to": [0.5, 0, 0, 0]}),
                                "failed")
        assert "unit quaternion" in error["message"]
        assert last_step()[1] == steps and tuple(obj(CUBE).rotation_euler) == (0, 0, 0)


def test_scale_by_multiplies_and_scale_to_sets():
    with blender() as b, b.peer() as talia:
        cube = obj(CUBE)
        cube.scale = (2, 1, -1)
        receipt = b.run(talia, "object.scale", CUBE, {"by": [1, 1, 1.5]})
        assert receipt["summary"] == "Scaled Cube by 1 x 1 x 1.5"
        assert tuple(cube.scale) == (2, 1, -1.5)
        target = {"id": CUBE, "generation": receipt["revision"]}
        receipt = b.run(talia, "object.scale", target, {"to": [0.5, 3, 2]})
        assert receipt["summary"] == "Set the scale of Cube to 0.5 x 3 x 2"
        assert tuple(cube.scale) == (0.5, 3, -2), "the sign (a mirror) is kept"


def test_a_scale_that_runs_away_is_refused():
    with blender() as b, b.peer() as talia:
        obj(CUBE).scale = (2000, 1, 1)
        assert_rejected(b.run(talia, "object.scale", CUBE, {"by": [1000, 1, 1]}), "failed")
        assert tuple(obj(CUBE).scale) == (2000, 1, 1)


def test_a_child_moves_rotates_and_scales_in_world_space():
    with blender() as b, b.peer() as talia:
        parent, child = obj(CAMERA), obj(CUBE)
        parent.location, parent.rotation_euler, parent.scale = (1, 2, 3), (0.4, 0, 1.1), (2, 2, 2)
        child.parent = parent
        child.matrix_parent_inverse = Matrix.Translation((0.5, 0, 0))
        child.location = (0.2, 0.1, 0)
        old = world(child)
        revision = b.run(talia, "object.move", CUBE, {"by": [0.01, 0.02, 0.03]})["revision"]
        moved = world(child)
        assert (moved.translation - old.translation - Vector((0.01, 0.02, 0.03))).length < 1e-6
        assert_matrix(moved.to_3x3().to_4x4(), old.to_3x3().to_4x4())
        b.run(talia, "object.rotate", {"id": CUBE, "generation": revision},
              {"by": {"axis": "Z", "angle": 0.5}})
        turned = Matrix.Rotation(0.5, 4, "Z") @ moved.to_3x3().to_4x4()
        turned.translation = moved.translation
        assert_matrix(world(child), turned, 1e-5)


def test_a_change_blender_overrides_is_refused_and_undone():
    with blender() as b, b.peer() as talia:
        cube = obj(CUBE)
        driver = cube.driver_add("location", 0).driver
        driver.expression = "0.5"
        world(cube)
        _, steps = last_step()
        error = assert_rejected(b.run(talia, "object.move", CUBE, {"by": [1, 0, 0]}), "failed")
        assert "exactly as asked" in error["message"]
        assert abs(world(cube).translation.x - 0.5) < 1e-6 and last_step()[1] == steps


def test_an_object_with_constraints_is_refused():
    with blender() as b, b.peer() as talia:
        obj(CUBE).constraints.new("COPY_LOCATION").target = obj(CAMERA)
        assert_rejected(b.run(talia, "object.move", CUBE, {"by": [1, 0, 0]}), "failed")
        receipt = b.run(talia, "object.move", CAMERA, {"by": [1, 0, 0]})
        assert receipt["outcome"] == "applied"


def test_a_move_beyond_100_km_is_refused():
    with blender() as b, b.peer() as talia:
        obj(CUBE).location.x = 99_999.9
        assert_rejected(b.run(talia, "object.move", CUBE, {"by": [1, 0, 0]}), "failed")


# Delete


def test_delete_removes_the_object_and_keeps_its_children_in_place():
    with blender() as b, b.peer() as talia:
        parent, child = obj(CUBE), obj(CAMERA)
        parent.location, parent.rotation_euler = (1, 0, 0), (0, 0, 0.3)
        child.parent = parent
        before, kept = world(child), selection()
        receipt = b.run(talia, "object.delete", CUBE)
        assert receipt["outcome"] == "applied" and receipt["summary"] == "Deleted Cube"
        assert "Cube" not in bpy.data.objects and child.parent is None
        assert_matrix(world(child), before, 1e-6)
        assert selection()[0] == [n for n in kept[0] if n != "Cube"]
        assert_rejected(b.run(talia, "object.delete", {"id": CUBE, "generation": 1}), "not_found")


# Undo, Redo, deduplication


def test_one_undo_reverts_exactly_one_command_and_redo_reapplies_it():
    with blender() as b, b.peer() as talia:
        cube = obj(CUBE)
        first = b.run(talia, "object.move", CUBE, {"by": [0.01, 0, 0]})
        b.run(talia, "object.move", {"id": CUBE, "generation": first["revision"]},
              {"by": [0, 0.02, 0]})
        moved = tuple(cube.location)
        undo = b.run(talia, "history.undo")
        assert undo["outcome"] == "applied" and undo["summary"] == "Undid: Moved Cube 20 mm along Y"
        cube = obj(CUBE)  # Undo reloads Blender's data
        assert tuple(cube.location) == (f32(0.01), 0, 0)
        redo = b.run(talia, "history.redo")
        assert redo["summary"] == "Redid: Moved Cube 20 mm along Y"
        assert tuple(obj(CUBE).location) == moved
        assert [b.run(talia, "history.undo")["summary"] for _ in range(2)] == [
            "Undid: Moved Cube 20 mm along Y", "Undid: Moved Cube 10 mm along X"]
        assert tuple(obj(CUBE).location) == (0, 0, 0)
        assert_rejected(b.run(talia, "history.undo"), "failed")  # back at "Original"


def test_undo_of_an_add_and_a_delete():
    with blender() as b, b.peer() as talia:
        add = b.run(talia, "object.add", args={"primitive": "sphere", "location": [0, 0, 1],
                                               "dimensions": [1, 1, 1]})
        b.run(talia, "history.undo")
        assert "Sphere" not in bpy.data.objects
        b.run(talia, "history.redo")
        assert obj(add["created"][0]).name == "Sphere"
        b.run(talia, "object.delete", CUBE)
        b.run(talia, "history.undo")
        assert obj(CUBE).name == "Cube", "Undo of Delete brings the same ID back"


def test_undo_says_when_it_undid_an_edit_made_in_host_blender():
    with blender() as b, b.peer() as talia:
        b.run(talia, "object.move", CUBE, {"by": [0.01, 0, 0]})
        obj(LIGHT).location.z += 1  # at the host desktop
        bpy.ops.ed.undo_push(message="Move")
        assert b.run(talia, "history.undo")["summary"] == "Undid a change made in host Blender"
        assert b.run(talia, "history.undo")["summary"] == "Undid: Moved Cube 10 mm along X"
        assert b.run(talia, "history.redo")["summary"] == "Redid: Moved Cube 10 mm along X"
        assert b.run(talia, "history.redo")["summary"] == "Redid a change made in host Blender"


def test_undo_keeps_the_hosts_selection():
    with blender() as b, b.peer() as talia:
        b.run(talia, "object.move", CUBE, {"by": [0.01, 0, 0]})
        for o in bpy.data.objects:
            o.select_set(o.name == "Light")
        bpy.context.view_layer.objects.active = obj(LIGHT)
        b.run(talia, "history.undo")
        assert selection() == (["Light"], "Light")


def test_a_repeated_request_is_applied_once():
    with blender() as b, b.peer() as talia:
        msg = talia.command("object.move", CUBE, {"by": [0.01, 0, 0]})
        first = b.call(talia.ask, msg)[1]
        _, steps = last_step()
        again = b.call(talia.ask, json.loads(json.dumps(msg)))[1]
        assert again["payload"] == first["payload"]
        assert obj(CUBE).location.x == f32(0.01) and last_step()[1] == steps
        msg["payload"]["args"]["by"] = [0.02, 0, 0]
        assert_rejected(b.call(talia.ask, msg)[1]["payload"], "duplicate_request")
        assert obj(CUBE).location.x == f32(0.01)


def test_a_stale_target_is_refused_without_changing_blender():
    with blender() as b, b.peer() as talia:
        b.run(talia, "object.move", CUBE, {"by": [0.01, 0, 0]})
        error = assert_rejected(b.run(talia, "object.move", {"id": CUBE, "generation": 0},
                                      {"by": [0.01, 0, 0]}), "stale_revision")
        assert error["details"] == {"generation": 1}
        assert obj(CUBE).location.x == f32(0.01)


# Modes, Save


def test_edits_wait_for_object_mode():
    with blender() as b, b.peer() as talia:
        bpy.context.view_layer.objects.active = obj(CUBE)
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            for op, target in (("object.move", CUBE), ("history.undo", None)):
                args = {"by": [1, 0, 0]} if target else {}
                error = assert_rejected(b.run(talia, op, target, args), "failed")
                assert "Edit Mode" in error["message"]
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")
        assert obj(CUBE).location.x == 0


def test_save_needs_a_file_saved_once_at_the_host():
    with blender() as b, b.peer() as talia:
        error = assert_rejected(b.run(talia, "document.save"), "failed")
        assert "File > Save As" in error["message"]


REOPEN = """
import json, sys, bpy
bpy.ops.wm.open_mainfile(filepath=sys.argv[1])
print("RESULT " + json.dumps({o.get("spatial_modeling_id") or o.name: {
    "name": o.name, "location": list(o.location), "rotation": list(o.rotation_euler),
    "scale": list(o.scale), "dimensions": list(o.dimensions)} for o in bpy.data.objects}))
"""


def test_save_writes_the_file_clears_dirty_and_a_fresh_blender_reopens_the_edits(tmp_path):
    path = tmp_path / "assembly.blend"
    with blender() as b, b.peer() as talia:
        bpy.ops.wm.save_as_mainfile(filepath=str(path))  # Save As at the host desktop
        saved_at = path.stat().st_mtime_ns
        add = b.run(talia, "object.add", args={"primitive": "cylinder", "location": [0, 0, 0.02],
                                               "dimensions": [0.02, 0.02, 0.04]})
        revision = b.run(talia, "object.rotate", CUBE,
                         {"by": {"axis": "Z", "angle": math.pi / 2}})["revision"]
        b.run(talia, "object.move", {"id": CUBE, "generation": revision}, {"by": [0.01, 0, 0]})
        assert bpy.data.is_dirty
        _, steps = last_step()
        before, result = b.ask(talia, b.command(talia, "document.save"))
        receipt = result["payload"]
        assert receipt["outcome"] == "applied" and receipt["summary"] == "Saved assembly.blend"
        assert receipt["revision"] == 3
        # Background Blender never clears bpy.data.is_dirty after a save; GUI Blender does
        # on its next event loop (blender_check.py). The host reports the saved file as clean.
        assert before[-1]["payload"]["document"]["dirty"] is False
        assert b.doc.describe()["dirty"] is False
        assert path.stat().st_mtime_ns > saved_at and last_step()[1] == steps

    reopened = subprocess.run([sys.executable, "-c", REOPEN, str(path)], check=True,
                              capture_output=True, text=True, timeout=120)
    line = next(x for x in reopened.stdout.splitlines() if x.startswith("RESULT "))
    objects = json.loads(line.removeprefix("RESULT "))
    cube = objects[CUBE]
    assert cube["location"] == [f32(0.01), 0, 0]
    assert cube["rotation"] == [0, 0, f32(math.pi / 2)]
    cylinder = objects[add["created"][0]]
    assert cylinder["name"] == "Cylinder" and cylinder["location"] == [0, 0, f32(0.02)]
    assert all(abs(a - b) < 1e-7 for a, b in zip(cylinder["dimensions"], [0.02, 0.02, 0.04],
                                                  strict=True))


# Revisions and scene sync


def test_the_scene_update_before_the_result_has_the_change():
    with blender(0.001) as b, b.peer() as talia, b.peer("Jihyeon") as other:
        b.call(talia.expect, "session.update")
        before, result = b.ask(talia, b.command(talia, "object.move", CUBE, {"by": [0.01, 0, 0]}))
        receipt = result["payload"]
        (update,) = before
        (cube,) = update["payload"]["objects"]
        assert cube["id"] == CUBE and cube["generation"] == receipt["revision"] == 1
        assert cube["transform"]["location"] == [0.01, 0, 0], "meters on the wire"
        assert update["payload"]["document"]["dirty"] is True
        assert b.call(other.expect, "scene.update", "activity")[1]["payload"] == receipt
        undo = b.run(talia, "history.undo")
        assert sync.generation(CUBE) == undo["revision"] == 2
        assert sync.generation(LIGHT) == 0, "Undo changed only the Cube"


def test_every_flush_is_inside_the_commands_undo_step():
    with blender(spy=True) as b, b.peer() as talia:
        spy = b.cmds.editor.sync
        _, steps = last_step()
        spy.calls.clear()
        add = b.run(talia, "object.add", args={"primitive": "cube", "location": [0, 0, 0],
                                               "dimensions": [1, 1, 1]})
        assert ("object_id", steps) in spy.calls and spy.calls[-1] == ("flush", steps), spy.calls
        assert last_step() == (add["summary"], steps + 1), "the flush came after the Undo step"
        assert obj(add["created"][0]).name == "Cube.001"
        b.run(talia, "history.undo")
        b.run(talia, "history.redo")
        assert obj(add["created"][0]).name == "Cube.001", "the ID is part of the step"


def test_a_commands_dirty_flag_holds_until_the_next_tick():
    # A command's scene.update goes out before its Undo step sets is_dirty, and a save
    # clears is_dirty only on GUI Blender's next event loop (blender_check.py checks both).
    fresh_scene()
    doc = document.Document()
    doc.saved()
    assert doc.describe()["dirty"] is False
    doc.edited()
    assert doc.describe()["dirty"] is True
    doc.tick()
    assert doc.describe()["dirty"] is bpy.data.is_dirty


# Leases (P3B): linked data as Blender has it


def linked_scene():
    """Around the factory Cube: what a lease on it must also cover, and what it mustn't."""
    cube = bpy.data.objects["Cube"]
    collection = bpy.context.scene.collection

    def new(name, data=None):
        o = bpy.data.objects.new(name, data)
        collection.objects.link(o)
        return o

    twin = new("Twin", cube.data)  # a linked duplicate: the same mesh
    child = new("Child")
    child.parent = cube
    grandchild = new("Grandchild")
    grandchild.parent = child
    follower = new("Follower")
    follower.constraints.new("COPY_LOCATION").target = cube
    plate = new("Plate", bpy.data.meshes.new("Plate"))
    plate.modifiers.new("Cut", "BOOLEAN").object = cube  # the Cube cuts the plate
    mirrored = new("Mirrored", bpy.data.meshes.new("Mirrored"))
    mirrored.modifiers.new("Mirror", "MIRROR").mirror_object = child
    cutters = bpy.data.collections.new("Cutters")
    collection.children.link(cutters)
    tool = bpy.data.objects.new("Tool", bpy.data.meshes.new("Tool"))
    cutters.objects.link(tool)
    cube.modifiers.new("Tools", "BOOLEAN")
    cube.modifiers["Tools"].operand_type = "COLLECTION"
    cube.modifiers["Tools"].collection = cutters  # the Tool cuts the Cube, not the other way
    scattered = new("Scattered", bpy.data.meshes.new("Scattered"))
    tree = bpy.data.node_groups.new("Scatter", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    socket = tree.interface.new_socket("Instance", in_out="INPUT", socket_type="NodeSocketObject")
    nodes = scattered.modifiers.new("Scatter", "NODES")
    nodes.node_group = tree
    getattr(nodes.properties.inputs, socket.identifier).value = grandchild  # a GN object input
    twin_of_twin_user = new("Elsewhere", bpy.data.meshes.new("Elsewhere"))
    bpy.ops.ed.undo_push(message="Linked data")
    linked = {twin, child, grandchild, follower, plate, mirrored, scattered}
    return linked, {tool, twin_of_twin_user, bpy.data.objects["Camera"]}


def test_linked_data_is_shared_data_children_and_modifier_or_constraint_users():
    with blender() as b:
        linked, unlinked = linked_scene()
        sync.flush()
        ids = {sync.object_id(o): o.name for o in (*linked, *unlinked)}
        got = b.cmds.leases.covered([CUBE])
        assert got[0] == CUBE
        assert {ids.get(i, i) for i in got[1:]} == {o.name for o in linked}
        tool = next(i for i, name in ids.items() if name == "Tool")
        assert b.cmds.leases.covered([tool]) == [tool, CUBE, *b.cmds.leases.covered([CUBE])[1:]]


def test_leases_in_blender_cover_a_linked_duplicate_and_end_with_the_connection():
    with blender() as b:
        bpy.data.objects.new("Twin", bpy.data.objects["Cube"].data)
        bpy.context.scene.collection.objects.link(bpy.data.objects["Twin"])
        bpy.ops.ed.undo_push(message="Twin")
        talia, other = b.peer("Talia"), b.peer("Jihyeon")
        b.call(talia.expect, "session.update")
        twin = sync.object_id(bpy.data.objects["Twin"])
        _, reply = b.ask(talia, acquire(talia, "shared", [CUBE]))
        lease = reply["payload"]["lease"]
        assert reply["type"] == "lease.granted" and lease["targets"] == [CUBE, twin]
        b.call(other.expect, "session.update")
        x = bpy.data.objects["Twin"].location.x
        error = assert_rejected(b.run(other, "object.move", twin, {"by": [1, 0, 0]}),
                                "lease_conflict")
        assert error["details"]["lease"] == lease
        assert assert_rejected(b.run(other, "history.undo"), "lease_conflict")
        assert bpy.data.objects["Twin"].location.x == x
        assert b.run(other, "object.move", CAMERA, {"by": [1, 0, 0]})["outcome"] == "applied"
        b.call(talia.expect, "scene.update", "activity")
        talia.close()
        b.call(other.expect, "session.update")
        assert b.run(other, "object.move", twin, {"by": [1, 0, 0]})["outcome"] == "applied"
        assert bpy.data.objects["Twin"].location.x == x + 1

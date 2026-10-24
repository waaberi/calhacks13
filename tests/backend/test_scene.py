"""Scene serialization and live sync in real Blender: the bpy module, in this process.

Skipped without the bpy module (CI has none):
  /tmp/ch13-bpy/bin/pytest tests/backend/test_scene.py -s   # -s prints the measurements

Each test builds a scene with bpy and runs sync.py with a recorder standing in
for the session. Every message it broadcasts is checked against
contracts/schemas; meshes are checked against known dimensions and against
Blender's own world matrices, converted to Unity as contracts/README.md says.
"""

import json
import math
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import protocol
import pytest
from jsonschema import Draft202012Validator
from test_contracts import REGISTRY, SCHEMAS
from test_coordinates import to_unity_point, to_unity_rotation, to_unity_scale, trs

bpy = pytest.importorskip("bpy")
np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
sys.path.insert(0, str(ROOT / "contracts" / "fakes"))
# Only importable once bpy is: the add-on package, Blender's own modules and the fake host.
import bmesh
import fake_host
from mathutils import Matrix, Quaternion, Vector
from spatial_modeling import document, sync


def valid(msg):
    Draft202012Validator(SCHEMAS[msg["type"]], registry=REGISTRY).validate(msg)
    protocol.encode(msg)  # strict JSON that fits in a line
    return msg


class Recorder:
    """Stands in for Session: keeps every message sync broadcasts."""

    def __init__(self):
        self.sent = []

    def broadcast(self, msg, exclude=None):
        self.sent.append(valid(msg))

    def take(self):
        sent, self.sent = self.sent, []
        return sent


@pytest.fixture
def host():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sync.register()
    recorder = Recorder()
    doc = document.Document()
    sync.start(doc, recorder)
    yield SimpleNamespace(doc=doc, sent=recorder)
    sync.unregister()


def snapshot():
    """Join as a new client would: a valid scene.snapshot; returns {name: object}."""
    doc = sync.describe()
    msg = valid(protocol.message("scene.snapshot", sync.snapshot(doc)))
    assert msg["payload"]["document"]["revision"] == sync.flush()
    return {o["name"]: o for o in msg["payload"]["objects"]}


def update(host):
    """Flush and return the one scene.update payload it broadcast."""
    sync.flush()
    sent = host.sent.take()
    assert [m["type"] for m in sent] == ["scene.update"], sent
    return sent[0]["payload"]


def nothing_sent(host):
    revision = host.doc.revision
    assert sync.flush() == revision
    assert host.sent.take() == []


def set_units(scale_length, length_unit="MILLIMETERS"):
    units = bpy.context.scene.unit_settings
    units.system, units.length_unit, units.scale_length = "METRIC", length_unit, scale_length


def box(name, size, location=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def material(obj, rgba):
    mat = bpy.data.materials.new(obj.name)
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = rgba
    obj.data.materials.append(mat)
    return mat


def vertices(mesh):
    return np.array(mesh["positions"]).reshape(-1, 3), np.array(mesh["normals"]).reshape(-1, 3)


def triangles(mesh):
    return np.array(mesh["indices"]).reshape(-1, 3)


def bounds(mesh):
    p = vertices(mesh)[0]
    return p.min(axis=0).tolist(), p.max(axis=0).tolist()


def assert_counter_clockwise_from_the_front(mesh):
    p, n = vertices(mesh)
    for a, b, c in triangles(mesh):
        face = np.cross(p[b] - p[a], p[c] - p[a])
        if np.linalg.norm(face) > 1e-12:  # not a degenerate triangle at a pole
            assert np.dot(face, n[a] + n[b] + n[c]) > 0, (a, b, c)


@pytest.mark.parametrize("scale_length,unit,size,z", [
    (0.001, "MILLIMETERS", (100, 60, 10), 5),
    (1.0, "METERS", (0.1, 0.06, 0.01), 0.005),
    (0.01, "CENTIMETERS", (10, 6, 1), 0.5),
], ids=["mm", "m", "cm"])
def test_a_100_x_60_x_10_mm_box_is_0_1_x_0_06_x_0_01_m(host, scale_length, unit, size, z):
    set_units(scale_length, unit)
    box("Base plate", size, (0, 0, z))
    plate = snapshot()["Base plate"]
    assert plate["transform"] == {"location": [0, 0, 0.005], "rotation": [1, 0, 0, 0],
                                  "scale": [1, 1, 1]}
    mesh = plate["mesh"]
    assert bounds(mesh) == ([-0.05, -0.03, -0.005], [0.05, 0.03, 0.005])
    assert len(mesh["positions"]) == 24 * 3 and len(mesh["indices"]) == 12 * 3  # split per face
    p, n = vertices(mesh)
    assert sorted({tuple(v) for v in n}) == sorted(
        {(0, 0, 1), (0, 0, -1), (0, 1, 0), (0, -1, 0), (1, 0, 0), (-1, 0, 0)})
    assert all(np.dot(p[i], n[i]) > 0 for i in range(len(p)))  # normals point outwards
    assert_counter_clockwise_from_the_front(mesh)


def bracket():
    """The fake host's scene, built in Blender: millimeters, like contracts/examples."""
    set_units(0.001)
    plate = box("Base plate", (100, 60, 10), (0, 0, 5))
    material(plate, (0.8, 0.8, 0.8, 1))
    bpy.ops.mesh.primitive_cylinder_add(radius=10, depth=40, location=(20, 0, 30))
    shaft = bpy.context.active_object
    shaft.name = "Shaft"
    bpy.ops.object.shade_smooth()
    material(shaft, (0.25, 0.4, 0.8, 1))
    shaft.parent = plate
    shaft.matrix_parent_inverse = plate.matrix_world.inverted()
    bpy.ops.object.camera_add(location=(300, -300, 200))
    camera = bpy.context.active_object
    camera.rotation_mode = "QUATERNION"
    camera.rotation_quaternion = (0.775377, 0.502339, 0.208076, 0.321172)


def test_the_bracket_looks_like_the_fake_hosts(host):
    bracket()
    started = time.perf_counter()
    objects = snapshot()
    took = time.perf_counter() - started
    fake = {o["name"]: o for o in fake_host.initial_objects()}
    assert objects.keys() == fake.keys()
    for name, obj in objects.items():
        expected = fake[name]
        assert set(obj) == set(expected)
        assert (obj["type"], obj["visible"], obj["color"]) == (
            expected["type"], expected["visible"], expected["color"]), name
        assert obj["parent"] == (objects["Base plate"]["id"] if name == "Shaft" else None)
        for key in ("location", "rotation", "scale"):
            assert obj["transform"][key] == pytest.approx(expected["transform"][key], abs=2e-6)
        if expected["mesh"] is None:
            assert obj["mesh"] is None
        else:
            assert bounds(obj["mesh"]) == pytest.approx(bounds(expected["mesh"]), abs=1e-6)
            assert_counter_clockwise_from_the_front(obj["mesh"])
    msg = protocol.message("scene.snapshot", sync.snapshot(sync.describe()))
    size = len(protocol.encode(msg))
    print(f"\nbracket snapshot: {size} bytes, serialized in {took * 1e3:.1f} ms")


def test_a_100k_vertex_mesh_fits_and_takes_well_under_a_second(host):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=316, y_subdivisions=316, size=0.1)
    bpy.ops.object.shade_smooth()
    blender_vertices = len(bpy.context.active_object.data.vertices)
    assert blender_vertices >= 100_000
    started = time.perf_counter()
    sync.flush()
    flushed = time.perf_counter()
    msg = protocol.message("scene.snapshot", sync.snapshot(sync.describe()))
    line = protocol.encode(msg)
    encoded = time.perf_counter()
    mesh = msg["payload"]["objects"][0]["mesh"]
    assert len(mesh["positions"]) == 3 * blender_vertices  # smooth: no split
    print(f"\n{blender_vertices} vertices, {len(mesh['indices']) // 3} triangles: snapshot "
          f"{len(line) / 1e6:.2f} MB; evaluate + arrays {1e3 * (flushed - started):.0f} ms, "
          f"lists + JSON {1e3 * (encoded - flushed):.0f} ms")
    assert encoded - started < 2.0


def test_world_transforms_and_hierarchy(host):
    set_units(0.001)
    parent = box("Parent", (10, 10, 10), (100, 0, 0))
    parent.rotation_euler = (0.3, -0.2, 1.1)
    parent.scale = (2, 2, 2)
    child = box("Child", (5, 5, 5))
    child.parent = parent
    child.location = (10, 0, 0)
    child.rotation_euler = (0, 0.5, 0)
    objects = snapshot()
    assert objects["Child"]["parent"] == objects["Parent"]["id"]
    assert objects["Parent"]["parent"] is None
    for obj in (parent, child):
        loc, rot, scl = obj.matrix_world.decompose()
        t = objects[obj.name]["transform"]
        assert t["location"] == pytest.approx([c * 0.001 for c in loc], abs=1e-6)
        q = [rot.w, rot.x, rot.y, rot.z]
        q = q if q[0] >= 0 else [-c for c in q]
        assert t["rotation"] == pytest.approx(q, abs=1e-6)
        assert t["scale"] == pytest.approx(list(scl), rel=1e-6)
    names = [o for o in objects]
    assert names.index("Parent") < names.index("Child")  # parents come first


def test_in_unity_every_vertex_lands_where_blender_has_it(host):
    """Convert transform and mesh as contracts/README.md says; compare with Blender's own matrices."""
    set_units(0.001)
    rng = random.Random(7)
    for i in range(5):
        bpy.ops.mesh.primitive_monkey_add(location=[rng.uniform(-50, 50) for _ in range(3)])
        obj = bpy.context.active_object
        obj.name = f"Monkey {i}"
        obj.rotation_euler = [rng.uniform(-math.pi, math.pi) for _ in range(3)]
        obj.scale = [rng.uniform(0.5, 3) for _ in range(3)]
    for name, obj in snapshot().items():
        world = bpy.data.objects[name].matrix_world
        t, mesh = obj["transform"], obj["mesh"]
        unity = trs(to_unity_point(t["location"]), to_unity_rotation(t["rotation"]),
                    to_unity_scale(t["scale"]))
        local, _ = vertices(mesh)
        for v in local[::50]:
            expected = to_unity_point([c * 0.001 for c in world @ Vector(v / 0.001)])
            got = unity(to_unity_point(v))
            assert got == pytest.approx(expected, abs=2e-5), name


def test_objects_without_geometry_have_a_null_mesh(host):
    bpy.ops.object.camera_add()
    bpy.ops.object.light_add(type="SUN")
    bpy.ops.object.empty_add()
    bpy.ops.object.armature_add()
    objects = snapshot()
    assert {(o["type"], o["mesh"]) for o in objects.values()} == {
        ("CAMERA", None), ("LIGHT", None), ("EMPTY", None), ("ARMATURE", None)}


def test_meshes_are_evaluated_after_modifiers_and_curves_text_metaballs_converted(host):
    cube = box("Cube", (2, 2, 2))
    cube.modifiers.new("Subdivision", "SUBSURF").levels = 2
    bpy.ops.curve.primitive_bezier_circle_add()
    bpy.context.active_object.data.bevel_depth = 0.1
    bpy.ops.object.text_add()
    bpy.ops.object.metaball_add()
    bpy.ops.surface.primitive_nurbs_surface_sphere_add()
    objects = snapshot()
    assert len(objects["Cube"]["mesh"]["indices"]) == 6 * 16 * 2 * 3  # not 12 triangles
    for name, type_ in (("BézierCircle", "CURVE"), ("Text", "FONT"), ("Mball", "META"),
                        ("SurfSphere", "SURFACE")):
        assert objects[name]["type"] == type_
        assert len(objects[name]["mesh"]["indices"]) > 30, name
        assert_counter_clockwise_from_the_front(objects[name]["mesh"])


def test_vertices_are_split_only_where_normals_differ(host):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1)
    bpy.ops.object.shade_smooth()
    sphere = bpy.context.active_object
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=10, y_subdivisions=10, location=(5, 0, 0))
    grid = bpy.context.active_object  # flat, but coplanar faces share their vertices
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, location=(-5, 0, 0))
    bpy.ops.object.shade_auto_smooth()  # smooth sides, sharp caps
    objects = snapshot()
    smooth = objects[sphere.name]["mesh"]
    assert len(smooth["positions"]) == 3 * len(sphere.data.vertices)
    p, n = vertices(smooth)
    assert np.linalg.norm(n, axis=1) == pytest.approx(1, abs=1e-5)
    assert np.linalg.norm(p, axis=1) == pytest.approx(1, abs=1e-5)
    assert len(objects[grid.name]["mesh"]["positions"]) == 3 * len(grid.data.vertices)
    assert len(objects["Cylinder"]["mesh"]["positions"]) == 3 * (32 + 32 + 2 * 32)
    for obj in objects.values():
        assert_counter_clockwise_from_the_front(obj["mesh"])


def test_color_is_the_first_materials_base_color(host):
    plain = box("Plain", (1, 1, 1))
    red = box("Red", (1, 1, 1))
    material(red, (0.9, 0.1, 0.05, 1))
    red.data.materials[0].node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = 0.5
    textured = box("Textured", (1, 1, 1))
    mat = material(textured, (1, 1, 1, 1))
    mat.diffuse_color = (0.2, 0.3, 0.4, 1)
    nodes = mat.node_tree.nodes
    mat.node_tree.links.new(nodes.new("ShaderNodeTexChecker").outputs["Color"],
                            nodes["Principled BSDF"].inputs["Base Color"])
    objects = snapshot()
    assert objects[plain.name]["color"] is None
    assert objects[red.name]["color"] == pytest.approx([0.9, 0.1, 0.05, 0.5], abs=1e-6)
    assert objects[textured.name]["color"] == pytest.approx([0.2, 0.3, 0.4, 1], abs=1e-6)


def test_ids_are_stored_stable_and_unique(host):
    cube = box("Cube", (1, 1, 1))
    other = box("Other", (1, 1, 1))
    other[sync.ID_PROPERTY] = "not a uuid"
    first = snapshot()
    ids = {name: o["id"] for name, o in first.items()}
    assert cube[sync.ID_PROPERTY] == ids["Cube"] and other[sync.ID_PROPERTY] == ids["Other"]
    assert len(set(ids.values())) == 2 and all(len(i) == 32 for i in ids.values())
    cube.name = "Renamed"
    assert {o["id"] for o in snapshot().values()} == set(ids.values())
    assert sync.find_object(ids["Cube"]).name == "Renamed"
    assert sync.object_id(cube) == ids["Cube"]

    host.sent.take()
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj.name == "Renamed")
    bpy.context.view_layer.objects.active = cube
    bpy.ops.object.duplicate()
    copy = bpy.context.active_object
    bpy.ops.object.duplicate_move_linked()
    linked = bpy.context.active_object
    payload = update(host)
    added = {o["name"]: o for o in payload["objects"]}
    assert set(added) == {copy.name, linked.name} and payload["removed"] == []
    assert all(o["mesh"] is not None for o in added.values())
    new_ids = {o["id"] for o in added.values()}
    assert len(new_ids) == 2 and not new_ids & set(ids.values())
    assert cube[sync.ID_PROPERTY] == ids["Cube"], "the original lost its ID to its copy"
    assert copy[sync.ID_PROPERTY] == added[copy.name]["id"]


def test_direct_edits_become_scene_updates(host):
    bracket()
    sync.flush()
    assert host.sent.take() == [], "the scene as loaded is revision 0, not a change"
    assert host.doc.revision == 0
    objects = snapshot()
    plate, shaft, camera = (objects[n]["id"] for n in ("Base plate", "Shaft", "Camera"))
    nothing_sent(host)

    bpy.data.objects["Camera"].location.x = 10
    u = update(host)
    assert u["document"]["revision"] == 1 == host.doc.revision
    assert [(o["id"], o["generation"], o["transform"]["location"][0]) for o in u["objects"]] == [
        (camera, 1, 0.01)]
    assert "mesh" not in u["objects"][0] and u["removed"] == []
    nothing_sent(host)  # no echo, no loop

    bpy.data.objects["Base plate"].location.x = 10  # the child moves with it
    u = update(host)
    assert [o["id"] for o in u["objects"]] == [plate, shaft]
    assert u["objects"][1]["transform"]["location"] == [0.03, 0, 0.03]
    assert all("mesh" not in o for o in u["objects"])

    bpy.data.objects["Shaft"].name = "Axle"
    assert [(o["name"], "mesh" in o) for o in update(host)["objects"]] == [("Axle", False)]
    shaft_material = bpy.data.materials["Shaft"].node_tree.nodes["Principled BSDF"]
    shaft_material.inputs["Base Color"].default_value = (1, 0, 0, 1)
    assert [(o["color"], "mesh" in o) for o in update(host)["objects"]] == [([1, 0, 0, 1], False)]
    bpy.data.objects["Axle"].hide_set(True)
    assert [(o["visible"], "mesh" in o) for o in update(host)["objects"]] == [(False, False)]

    bpy.data.objects["Base plate"].modifiers.new("Bevel", "BEVEL")
    u = update(host)
    assert [o["id"] for o in u["objects"]] == [plate]
    assert len(u["objects"][0]["mesh"]["indices"]) > 36
    assert u["document"]["revision"] == 6 and sync.generation(plate) == 6
    assert sync.generation(camera) == 1

    bpy.data.objects.remove(bpy.data.objects["Camera"])
    u = update(host)
    assert (u["objects"], u["removed"]) == ([], [camera])
    assert sync.generation(camera) is None and sync.find_object(camera) is None

    bpy.ops.mesh.primitive_ico_sphere_add()
    u = update(host)
    assert [(o["name"], o["generation"], o["mesh"] is not None) for o in u["objects"]] == [
        ("Icosphere", 8, True)]


def test_edit_mode_changes_send_the_new_mesh(host):
    cube = box("Cube", (2, 2, 2))
    snapshot()
    bpy.ops.object.mode_set(mode="EDIT")
    mesh = bmesh.from_edit_mesh(cube.data)
    for v in mesh.verts:
        v.co.z *= 3
    bmesh.update_edit_mesh(cube.data)
    u = update(host)
    assert bounds(u["objects"][0]["mesh"])[1][2] == 3
    bpy.ops.object.mode_set(mode="OBJECT")
    nothing_sent(host)


def objects_by_name(payload):
    return {o["name"]: o for o in payload["objects"]}


def test_undo_and_redo_send_what_changed_and_ids_survive(host):
    cube = box("Cube", (2, 2, 2))
    bpy.ops.ed.undo_push(message="Add Cube")
    cube_id = snapshot()["Cube"]["id"]
    cube.location.x = 2
    bpy.ops.ed.undo_push(message="Move")
    assert objects_by_name(update(host))["Cube"]["transform"]["location"][0] == 2

    bpy.ops.ed.undo()
    u = update(host)
    assert [(o["id"], o["transform"]["location"][0], "mesh" in o) for o in u["objects"]] == [
        (cube_id, 0, False)]
    bpy.ops.ed.redo()
    assert [(o["id"], o["transform"]["location"][0]) for o in update(host)["objects"]] == [
        (cube_id, 2)]
    assert sync.find_object(cube_id).location.x == 2  # looked up again, not a stale pointer

    bpy.ops.mesh.primitive_uv_sphere_add()  # added in Blender, so its ID comes after the push
    bpy.ops.ed.undo_push(message="Add Sphere")
    sphere_id = objects_by_name(update(host))["Sphere"]["id"]
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj.name == "Cube")
    bpy.context.view_layer.objects.active = bpy.data.objects["Cube"]
    bpy.ops.object.duplicate()
    bpy.ops.ed.undo_push(message="Duplicate")
    copy_id = objects_by_name(update(host))["Cube.001"]["id"]

    bpy.ops.ed.undo()
    assert update(host)["removed"] == [copy_id]
    bpy.ops.ed.undo()
    assert update(host)["removed"] == [sphere_id]
    bpy.ops.ed.redo()
    u = update(host)
    assert [(o["id"], o["mesh"] is not None) for o in u["objects"]] == [(sphere_id, True)]
    bpy.ops.ed.redo()
    assert [o["id"] for o in update(host)["objects"]] == [copy_id]
    assert bpy.data.objects["Cube"][sync.ID_PROPERTY] == cube_id
    nothing_sent(host)


def test_a_unit_change_sends_a_fresh_snapshot(host):
    set_units(1.0, "METERS")
    box("Cube", (0.1, 0.1, 0.1))
    snapshot()
    set_units(0.001)
    sync.flush()
    [msg] = host.sent.take()
    assert msg["type"] == "scene.snapshot"
    revision = msg["payload"]["document"]["revision"]
    assert revision == 1 and msg["payload"]["document"]["units"]["scale_length"] == 0.001
    [cube] = msg["payload"]["objects"]
    assert cube["generation"] == revision and bounds(cube["mesh"])[1] == [0.00005] * 3


def test_save_sends_only_the_dirty_flag(host, tmp_path):
    box("Cube", (1, 1, 1))
    snapshot()
    bpy.data.objects["Cube"].location.x = 1
    bpy.ops.ed.undo_push(message="Move")
    assert bpy.data.is_dirty
    assert update(host)["document"]["dirty"] is True
    bpy.ops.wm.save_as_mainfile(filepath=str(tmp_path / "part.blend"))
    u = update(host)
    assert (u["objects"], u["removed"], u["document"]["revision"]) == ([], [], 1)
    assert u["document"]["name"] == "part.blend"
    # The bpy module keeps is_dirty set after saving (GUI Blender clears it; blender_check.py
    # checks that). Either way the host reports Blender's own flag.
    assert u["document"]["dirty"] is bpy.data.is_dirty


def test_a_drag_streams_a_few_small_updates(host):
    box("Moving", (1, 1, 1))
    box("Still", (1, 1, 1))
    moving_id = snapshot()["Moving"]["id"]
    obj = bpy.data.objects["Moving"]
    started = time.monotonic()
    for step in range(1, 51):  # 50 mouse moves in about half a second
        obj.location.x = step / 10
        bpy.context.evaluated_depsgraph_get()  # what Blender's event loop does after each
        sync.poll()
        time.sleep(0.01)
    took = time.monotonic() - started
    time.sleep(sync.MIN_INTERVAL)
    sync.poll()  # the last position goes out after the interval
    sent = host.sent.take()
    assert 3 <= len(sent) <= took / sync.MIN_INTERVAL + 2, len(sent)
    revisions = [m["payload"]["document"]["revision"] for m in sent]
    assert revisions == sorted(set(revisions))
    for msg in sent:
        [o] = msg["payload"]["objects"]
        assert o["id"] == moving_id and "mesh" not in o
        assert len(protocol.encode(msg)) < 1000
    assert sent[-1]["payload"]["objects"][0]["transform"]["location"][0] == 5


def test_a_mesh_too_large_for_one_line_is_sent_without_its_mesh(host, monkeypatch, capsys):
    monkeypatch.setattr(sync, "FIT_BYTES", 50_000)
    box("Small", (1, 1, 1))
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5)
    objects = snapshot()
    assert objects["Icosphere"]["mesh"] is None and objects["Small"]["mesh"] is not None
    assert "Icosphere's mesh (5120 triangles) is too large to send" in capsys.readouterr().out


def test_the_interface_for_commands(host):
    cube = box("Cube", (1, 1, 1))
    assert sync.flush() == 0
    cube_id = sync.object_id(cube)
    assert sync.find_object(cube_id) == cube and sync.generation(cube_id) == 0
    assert sync.find_object("0" * 32) is None and sync.generation("0" * 32) is None

    # A command handler: mutate, flush (scene.update to everyone), then reply with the revision.
    bpy.ops.mesh.primitive_cube_add(location=(3, 0, 0))
    created = sync.object_id(bpy.context.active_object)  # flushes: the clients get it now
    [msg] = host.sent.take()
    assert [o["id"] for o in msg["payload"]["objects"]] == [created]
    assert sync.flush() == 1 == msg["payload"]["document"]["revision"]
    assert host.sent.take() == []
    assert bpy.context.active_object[sync.ID_PROPERTY] == created  # in the Undo step pushed next


def test_stopped_sync_is_inert(host):
    sync.stop()
    assert sync.flush() == 0 and sync.generation("0" * 32) is None
    assert sync.snapshot({"x": 1}) == {"document": {"x": 1}, "objects": [], "sketches": []}
    sync.poll()
    with pytest.raises(RuntimeError):
        sync.describe()


def test_numbers_are_rounded_finite_json(host):
    obj = box("Cube", (1, 1, 1))
    obj.location = (1 / 3, 2 / 3, 1e-9)
    obj.rotation_euler = (0.1, 0.2, 0.3)
    obj.scale = (1 / 3, 1, 1)
    text = json.dumps(snapshot()["Cube"])
    t = json.loads(text)["transform"]
    assert t["location"] == [0.333333, 0.666667, 0]
    assert all(len(repr(c)) <= 9 for c in t["rotation"])
    assert t["scale"] == [0.333333, 1, 1]  # float32 noise (0.99999994) doesn't show
    expected = Matrix.LocRotScale(None, obj.matrix_world.to_quaternion(), None)
    got = Quaternion(t["rotation"]).to_matrix().to_4x4()
    assert max(abs(a - b) for r, s in zip(got, expected) for a, b in zip(r, s)) < 1e-5

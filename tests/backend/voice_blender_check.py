"""Voice operations in GUI Blender, through the host's real command path (voice_ops.py).

For every voice operation, a fresh Suzanne (set up as the operation needs) is the VR target
while the host desktop has the Camera selected and active. A VR client sends voice.resolve,
then the command voice.run. The check reads the result back from Blender, checks the message
order (scene.update, then result; another client gets scene.update and activity), that the host
desktop's selection and active object didn't change, and that one Undo (a history.undo
command) restores the scene. In Talia's P0 reference scene a voice add lands on top of the
selection, in the user's view; "add a modifier" asks Array, Mirror or Bevel and never Convert to
mesh; "hello" is rejected with nothing to say. Then results too heavy to sync are refused with
nothing changed, and an object that was heavy already may still get lighter.

  BLENDER_USER_RESOURCES=$(mktemp -d) ~/.local/bin/headless-run blender --factory-startup \\
      --python tests/backend/voice_blender_check.py
  BLENDER=/path/to/blender pytest tests/backend/test_blender.py -k voice

GUI Blender only: operators run from the add-on's timer, as on the demo PC. Exits 0 if every
check passed; blender_check.py's helpers install the add-on into BLENDER_USER_RESOURCES.
"""

import math
import random
import sys
import time
from pathlib import Path

import bmesh
import bpy

# isort: split
import addon_utils  # importable only after bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blender_check as bc
from ping_client import protocol

MOD = "object.modifier_add"
SUZANNE_TRIANGLES = 968


def scale_by_two(obj):
    obj.scale = (2, 2, 2)


def move_rotate_scale(obj):
    obj.location, obj.rotation_euler, obj.scale = (1, 0, 0), (0, 0, 0.5), (2, 2, 2)


def move(obj):
    obj.location = (1, 0, 0)


def smooth(obj):
    obj.data.shade_smooth()


def flip(obj):
    obj.data.flip_normals()


def mirror(obj):
    obj.modifiers.new("Mirror", "MIRROR")


def array_of_five(obj):
    obj.modifiers.new("Array", "ARRAY").count = 5


def array_of_two(obj):
    obj.modifiers.new("Array", "ARRAY").count = 2


# (what is said, the operator, its properties, modifier values set, set-up before)
TESTS = [
    ("add a monkey", "mesh.primitive_monkey_add", {}, {}, None),
    ("a monkey", "mesh.primitive_monkey_add", {}, {}, None),
    ("add a donut", "mesh.primitive_torus_add", {}, {}, None),
    ("add a cone", "mesh.primitive_cone_add", {}, {}, None),
    ("add a plane", "mesh.primitive_plane_add", {}, {}, None),
    ("add a cylinder", "mesh.primitive_cylinder_add", {}, {}, None),
    ("add a sphere", "mesh.primitive_uv_sphere_add", {}, {}, None),
    ("add an ico sphere", "mesh.primitive_ico_sphere_add", {}, {}, None),
    ("add a cube", "mesh.primitive_cube_add", {}, {}, None),
    ("add a camera", "object.camera_add", {}, {}, None),
    ("add a sun", "object.light_add", {"type": "SUN"}, {}, None),
    ("add an empty", "object.empty_add", {}, {}, None),
    ("add text", "object.text_add", {}, {}, None),
    ("shade smooth", "object.shade_smooth", {}, {}, None),
    ("shade flat", "object.shade_flat", {}, {}, smooth),
    ("auto smooth", "object.shade_auto_smooth", {}, {}, None),
    ("subdivide level two", MOD, {"type": "SUBSURF"}, {"levels": 2, "render_levels": 2}, None),
    ("make it smoother", MOD, {"type": "SUBSURF"}, {"levels": 1}, None),
    ("add a mirror modifier", MOD, {"type": "MIRROR"}, {"use_axis": [True, False, False]}, None),
    ("mirror on the z axis", MOD, {"type": "MIRROR"}, {"use_axis": [False, False, True]}, None),
    ("make it thicker", MOD, {"type": "SOLIDIFY"}, {}, None),
    ("solidify two millimeters", MOD, {"type": "SOLIDIFY"}, {"thickness": 0.002}, None),
    ("decimate to fifty percent", MOD, {"type": "DECIMATE"}, {"ratio": 0.5}, None),
    ("bevel the edges", MOD, {"type": "BEVEL"}, {}, None),
    ("bevel with three segments", MOD, {"type": "BEVEL"}, {"segments": 3}, None),
    ("make five copies", MOD, {"type": "ARRAY"}, {"count": 5}, None),
    ("make four copies along z", MOD, {"type": "ARRAY"},
     {"count": 4, "relative_offset_displace": [0.0, 0.0, 1.0]}, None),
    ("make ten copies", MOD, {"type": "ARRAY"}, {"count": 10}, array_of_five),  # reused
    ("wireframe", MOD, {"type": "WIREFRAME"}, {}, None),
    ("remesh", MOD, {"type": "REMESH"}, {}, None),
    ("add a boolean", MOD, {"type": "BOOLEAN"}, {}, None),
    ("add a weld modifier", MOD, {"type": "WELD"}, {}, None),
    ("add a screw modifier", MOD, {"type": "SCREW"}, {}, None),
    ("triangulate faces", MOD, {"type": "TRIANGULATE"}, {}, None),
    ("apply scale", "object.transform_apply", {"scale": True}, {}, scale_by_two),
    ("apply all transforms", "object.transform_apply",
     {"location": True, "rotation": True, "scale": True}, {}, move_rotate_scale),
    ("origin to geometry", "object.origin_set", {"type": "ORIGIN_GEOMETRY"}, {}, None),
    ("geometry to origin", "object.origin_set", {"type": "GEOMETRY_ORIGIN"}, {}, move),
    ("separate by loose parts", "mesh.separate", {"type": "LOOSE"}, {}, None),
    ("recalculate normals", "mesh.normals_make_consistent", {}, {}, flip),
    ("flip normals", "mesh.flip_normals", {}, {}, None),
    ("merge by distance", "mesh.remove_doubles", {}, {}, None),
    ("smooth vertices", "mesh.vertices_smooth", {"factor": 0.25, "repeat": 1}, {}, None),
    ("smooth the vertices", "mesh.vertices_smooth", {"factor": 0.25}, {}, None),
    ("make it smooth", "object.shade_smooth", {}, {}, None),
    ("smooth the object", "object.shade_smooth", {}, {}, None),
    ("subdivide it twice", MOD, {"type": "SUBSURF"}, {"levels": 2, "render_levels": 2}, None),
    ("add a mirror", MOD, {"type": "MIRROR"}, {"use_axis": [True, False, False]}, None),
    ("convert to mesh", "object.convert", {"target": "MESH"}, {}, mirror),
]


def view3d():
    win = bpy.context.window_manager.windows[0]
    area = next(a for a in win.screen.areas if a.type == "VIEW_3D")
    return {"window": win, "area": area,
            "region": next(r for r in area.regions if r.type == "WINDOW")}


def state():
    """What a voice operation may change, for every object, to compare before and after."""
    layer = bpy.context.view_layer
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    return {
        "objects": sorted(o.name for o in bpy.data.objects if o.users),
        "modifiers": {o.name: [(m.type, m.name, _values(m)) for m in o.modifiers]
                      for o in meshes},
        "hidden": sorted(o.name for o in layer.objects if o.hide_get()),
        "vertices": {o.name: len(o.data.vertices) for o in meshes},
        "smooth": {o.name: [p.use_smooth for p in o.data.polygons] for o in meshes},
        "matrix": {o.name: [round(v, 4) for row in o.matrix_world for v in row]
                   for o in bpy.data.objects},
        "positions": {o.name: round(sum(v.co.x + 3 * v.co.y + 7 * v.co.z
                                        for v in o.data.vertices), 3) for o in meshes},
        "normals": {o.name: round(sum(p.normal.x + 2 * p.normal.y + 3 * p.normal.z
                                      for p in o.data.polygons), 3) for o in meshes},
    }


def _values(modifier):
    out = {}
    for key in ("levels", "count", "thickness", "ratio", "segments", "width"):
        if hasattr(modifier, key):
            out[key] = round(getattr(modifier, key), 5)
    return out


def select_only(obj):
    layer = bpy.context.view_layer
    for o in layer.objects:
        o.select_set(o == obj)
    layer.objects.active = obj


def fresh(setup=None):
    """A scene of Camera, Light and a new Suzanne; the desktop has the Camera selected."""
    for obj in list(bpy.data.objects):
        if obj.name not in ("Camera", "Light"):
            bpy.data.objects.remove(obj)
    for mesh in list(bpy.data.meshes):
        if not mesh.users:
            bpy.data.meshes.remove(mesh)
    with bpy.context.temp_override(**view3d()):
        bpy.ops.mesh.primitive_monkey_add()
    suzanne = bpy.context.view_layer.objects.active
    if setup is not None:
        setup(suzanne)
    select_only(bpy.data.objects["Camera"])
    bpy.ops.ed.undo_push(message="Voice check set-up")
    return suzanne


def drained(*peers):
    """Flush the scene sync, then read every peer's queue empty (a ping and its pong)."""
    bc.mod("sync").flush()
    for peer in peers:
        ping = protocol.message("ping")
        before, reply = yield from bc.ask(peer, ping)
        assert reply["type"] == "pong", reply
        assert all(m["type"] == "scene.update" for m in before), before


def target_of(obj):
    sync = bc.mod("sync")
    oid = sync.object_id(obj)
    return {"id": oid, "generation": sync.generation(oid)}


def resolve(peer, text, target):
    msg = protocol.message("voice.resolve", {"text": text, "confidence": 0.9, "target": target})
    before, reply = yield from bc.ask(peer, msg)
    assert reply["type"] == "voice.candidates", reply
    assert all(m["type"] == "scene.update" for m in before), before
    return reply["payload"]


def voice_run(commander, answer, target, choice=1):
    msg = commander.command("voice.run", args={"resolution": answer["resolution"],
                                               "choice": choice})
    msg["payload"]["source"] = "voice"
    if answer["candidates"][choice - 1]["needs_target"]:
        msg["payload"]["target"] = {"id": target["id"],
                                    "generation": bc.mod("sync").generation(target["id"])}
    return msg


def watched(other, what, update=True):
    """The other client's scene.update (if one was sent) and activity."""
    count = 2 if update else 1
    got = yield from bc.off_thread(lambda: [other.recv() for _ in range(count)], what)
    assert [m["type"] for m in got] == ["scene.update", "activity"][-count:], got
    return got


def close(a, b):
    if isinstance(b, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-7)
    return a == b


def one_operation(talia, other, commander, test):
    text, operator, props, values, setup = test
    obj = fresh(setup)
    target = target_of(obj)
    yield from drained(talia, other)
    answer = yield from resolve(talia, text, target)
    assert answer["decision"] in ("run", "ask"), (text, answer)
    candidate = answer["candidates"][0]
    assert candidate["operator"] == operator, (text, candidate)
    assert props.items() <= candidate["properties"].items(), (text, candidate)
    kept, before = bc.selection(), state()
    started = time.perf_counter()
    receipt, updates = yield from commander.send(voice_run(commander, answer, target))
    took = time.perf_counter() - started
    assert receipt["outcome"] == "applied", (text, receipt)
    assert receipt["summary"].startswith("Voice:"), receipt
    # One scene.update with the change, then the result. A modifier that changes no geometry
    # (a Boolean without a cutter, a Weld with nothing to weld), or applying the modifiers,
    # changes nothing clients see.
    invisible = operator in (MOD, "object.convert")
    assert len(updates) == 1 or (len(updates) == 0 and invisible), (text, updates)
    assert all(u["document"]["revision"] == receipt["revision"] for u in updates)
    got = yield from watched(other, f"the update and activity of {text!r}", bool(updates))
    assert got[-1]["payload"] == receipt
    assert bc.selection() == kept, (text, bc.selection(), kept)  # the host desktop's own
    after = state()
    assert after != before, f"{text!r} changed nothing"
    suzanne = bc.by_id(target["id"])
    if operator.startswith("mesh.primitive") or operator.endswith("_add") and operator != MOD:
        assert len(receipt["created"]) == 1 and bc.by_id(receipt["created"][0]) is not None
        placed_above(bc.by_id(receipt["created"][0]), suzanne, text)
    if operator == MOD:
        found = [m for m in suzanne.modifiers if m.type == props["type"]]
        assert len(found) == 1, (text, [m.type for m in suzanne.modifiers])  # reused, not stacked
        for key, value in values.items():
            got_value = getattr(found[0], key)
            got_value = list(got_value) if not isinstance(value, (int, float)) else got_value
            assert close(got_value, value), (text, key, got_value, value)
    made = [bc.by_id(i) for i in receipt.get("created", [])] or [suzanne]
    triangles = bc.mod("voice_ops")._triangles(bpy, bc.mod("scene"), made)
    # One Undo restores the scene as it was before the voice operation.
    undo, undone = yield from commander.send(commander.command("history.undo"))
    assert undo["outcome"] == "applied" and undo["summary"] == "Undid: " + receipt["summary"], \
        undo
    yield from watched(other, f"the undo of {text!r}", bool(undone))
    assert state() == before, f"one Undo didn't restore the scene after {text!r}"
    assert bc.selection() == kept
    bc.log(f"ok {text!r}: {receipt['summary']} ({took * 1000:.0f} ms)")
    return took, triangles


def placed_above(new, target, text, size=None):
    """A voice add is the target's size, within ADD_SIZE_RANGE, centred over it on +Z, and
    overlaps nothing."""
    vo = bc.mod("voice_ops")
    bpy.context.view_layer.update()
    box, near = vo._world_box(new), vo._world_box(target)
    middle = [(near[0][i] + near[1][i]) / 2 for i in range(2)]
    assert all(math.isclose(new.location[i], middle[i], abs_tol=1e-6) for i in range(2)), \
        (text, tuple(new.location), middle)  # centred over it
    if box is None:  # a camera, light or empty: only its place
        assert new.location.z > near[1][2], (text, tuple(new.location))
        return
    longest = max(vo._sides(box))
    size = vo.ADD_SIZE_RANGE[1] if size is None else size
    assert math.isclose(longest, size, rel_tol=0.02), (text, longest)
    assert box[0][2] > near[1][2], (text, box, near)  # above it, not inside
    others = [vo._world_box(o) for o in bpy.context.view_layer.objects if o != new]
    assert not any(overlap(box, b) for b in others if b), (text, box)
    assert tuple(new.scale) == (1.0, 1.0, 1.0), (text, tuple(new.scale))


def overlap(a, b):
    return all(a[0][i] < b[1][i] and b[0][i] < a[1][i] for i in range(3))


# HostScene.cs shows Blender at displayScale 5 with its origin viewingDistance 1 m in front of the
# eyes and belowEyeHeight 0.35 m below them, so the eyes are here in Blender, looking along +Y.
EYE = (0.0, -1.0 / 5, 0.35 / 5)


def degrees_off_view(point):
    d = [p - e for p, e in zip(point, EYE, strict=True)]
    return math.degrees(math.atan2(math.hypot(d[0], d[2]), d[1]))


def p0_reference():
    """Talia's P0 reference (samples/mechanical/create_reference.py), the demo's: a 20 mm cube
    and a 10 x 30 mm cylinder on the ground, 40 mm apart. The desktop has the Camera selected."""
    for obj in list(bpy.data.objects):
        if obj.name not in ("Camera", "Light"):
            bpy.data.objects.remove(obj)
    with bpy.context.temp_override(**view3d()):
        bpy.ops.mesh.primitive_cube_add(size=0.02, location=(-0.02, 0, 0.01))
        cube = bpy.context.view_layer.objects.active
        bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.005, depth=0.03,
                                            location=(0.02, 0, 0.015))
        cylinder = bpy.context.view_layer.objects.active
    cube.name, cylinder.name = "Cube_20mm", "Cylinder_D10_H30mm"
    select_only(bpy.data.objects["Camera"])
    bpy.ops.ed.undo_push(message="Voice check: P0 reference")
    return cube, cylinder


def adds_in_view(talia, other, commander):
    """In the demo scene an add lands on top of what is selected, in the user's view; a second
    one stacks on the first. Blender's own 2 m cube is 10 m around the user at 5x: no use."""
    cube, cylinder = p0_reference()
    made = []
    for text, anchor, size in (("add a monkey", cube, 0.02), ("add a cone", cylinder, 0.03),
                               ("add a monkey", cube, 0.02)):
        target = target_of(anchor)
        yield from drained(talia, other)
        answer = yield from resolve(talia, text, target)
        assert answer["decision"] == "run" and not answer["candidates"][0]["needs_target"], answer
        receipt, _ = yield from commander.send(voice_run(commander, answer, target))
        assert receipt["outcome"] == "applied", receipt
        yield from watched(other, f"{text!r} on {anchor.name}")
        new = bc.by_id(receipt["created"][0])
        placed_above(new, anchor, text, size)
        angle = degrees_off_view(tuple(new.location))
        assert angle < 20, (text, tuple(new.location), angle)
        made.append(new)
        bc.log(f"ok {text!r} over {anchor.name}: {new.name} at "
               f"{tuple(round(v, 4) for v in new.location)}, {angle:.1f} degrees off the view")
    assert made[2].location.z > made[0].location.z  # stacked on the first, not inside it


def the_demo_question(talia, other, commander):
    """"Add a modifier" asks Array, Mirror or Bevel, and each choice adds that modifier; no
    question offers Convert to mesh unasked."""
    vo = bc.mod("voice_ops")
    for choice, kind in ((1, "ARRAY"), (2, "MIRROR"), (3, "BEVEL")):
        suzanne = fresh()
        target = target_of(suzanne)
        yield from drained(talia, other)
        answer = yield from resolve(talia, "add a modifier", target)
        assert answer["decision"] == "ask", answer
        assert [c["say"] for c in answer["candidates"]] == ["Array", "Mirror on X", "Bevel"]
        receipt, _ = yield from commander.send(voice_run(commander, answer, target, choice))
        assert receipt["outcome"] == "applied", receipt
        yield from watched(other, f"choice {choice} of 'add a modifier'")
        assert [m.type for m in bc.by_id(target["id"]).modifiers] == [kind]
        bc.log(f"ok 'add a modifier', choice {choice}: {receipt['summary']}")
    for text in ("add a mirror modifier", "add array modifier", "modifier"):
        msg = protocol.message("voice.resolve", {"text": text, "confidence": 0.49,
                                                 "target": target_of(suzanne)})
        _, reply = yield from bc.ask(talia, msg)
        ops = [c["operator"] for c in reply["payload"]["candidates"]]
        assert "object.convert" not in ops and set(ops) == {vo.MOD}, (text, reply)
    for text in ("hello", "well", "right", "alright", "come"):
        msg = protocol.message("voice.resolve", {"text": text, "confidence": 1.0,
                                                 "target": target_of(suzanne)})
        _, reply = yield from bc.ask(talia, msg)
        p = reply["payload"]
        assert (p["decision"], p["reason"], p["candidates"]) == ("reject", None, []), (text, p)
    bc.log("ok no Convert to mesh unasked; fillers rejected with nothing to say")


def add_without_selection(talia, other, commander):
    """No target: ADD_SIZE at the 3D cursor, moved past the Suzanne that is there."""
    vo = bc.mod("voice_ops")
    suzanne = fresh()
    yield from drained(talia, other)
    msg = protocol.message("voice.resolve", {"text": "add a cube", "confidence": 0.9})
    _, reply = yield from bc.ask(talia, msg)
    answer = reply["payload"]
    assert answer["decision"] == "run", answer
    receipt, _ = yield from commander.send(voice_run(commander, answer, None))
    assert receipt["outcome"] == "applied", receipt
    yield from watched(other, "the add without a selection")
    cube = bc.by_id(receipt["created"][0])
    bpy.context.view_layer.update()
    box, near = vo._world_box(cube), vo._world_box(suzanne)
    assert math.isclose(max(vo._sides(box)), vo.ADD_SIZE, rel_tol=0.02), box
    assert box[0][0] > near[1][0], (box, near)
    bc.log(f"ok 'add a cube' without a selection: {cube.name} at {tuple(cube.location)}")


def refused_shrink(talia, other, commander):
    """Smooth the vertices of a plane: its corners would keep 75%, so it is undone."""
    for obj in list(bpy.data.objects):
        if obj.name not in ("Camera", "Light"):
            bpy.data.objects.remove(obj)
    with bpy.context.temp_override(**view3d()):
        bpy.ops.mesh.primitive_plane_add()
    plane = bpy.context.view_layer.objects.active
    select_only(bpy.data.objects["Camera"])
    bpy.ops.ed.undo_push(message="Voice check: plane")
    target = target_of(plane)
    yield from drained(talia, other)
    answer = yield from resolve(talia, "smooth the vertices", target)
    assert answer["decision"] == "run", answer
    kept, before = bc.selection(), state()
    receipt, updates = yield from commander.send(voice_run(commander, answer, target))
    assert receipt["outcome"] == "rejected" and "shrink" in receipt["error"]["message"], receipt
    assert updates == [] and state() == before and bc.selection() == kept
    bc.log(f"ok refused: {receipt['error']['message']}")


def heavy_grid(flat):
    """A bumpy grid of about 48,000 triangles, no two of them in one plane."""
    mesh = bpy.data.meshes.new("Bumps")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=156, y_segments=156, size=1.0)
    rng = random.Random(7)
    for v in bm.verts:
        v.co.z = rng.uniform(-0.01, 0.01)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()
    if not flat:
        mesh.shade_smooth()
    obj = bpy.data.objects.new("Bumps", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def refused_heavy(talia, other, commander, text, obj, what):
    target = target_of(obj)
    yield from drained(talia, other)
    answer = yield from resolve(talia, text, target)
    assert answer["decision"] == "run", answer
    kept, before = bc.selection(), state()
    receipt, updates = yield from commander.send(voice_run(commander, answer, target))
    assert receipt["outcome"] == "rejected" and receipt["error"]["code"] == "failed", receipt
    assert "too heavy" in receipt["error"]["message"] and what in receipt["error"]["message"], \
        receipt
    assert updates == [], updates  # nothing changed, so nothing was sent
    assert state() == before and bc.selection() == kept
    bc.log(f"ok refused {text!r}: {receipt['error']['message']}")


def checks():
    bc.install()
    addon_utils.enable(bc.MODULE, default_set=True)
    yield from bc.wait(bc.listening, "the host to listen")
    bc.mod("server").HEARTBEAT_TIMEOUT = 600.0  # these clients don't ping
    talia, welcome, _ = yield from bc.joined("Talia")
    other, _, _ = yield from bc.joined("Jihyeon")
    yield from bc.off_thread(talia.recv, "Talia's session.update")  # Jihyeon joined
    commander = bc.Commander(talia, welcome)

    times = []
    for test in TESTS:
        took, triangles = yield from one_operation(talia, other, commander, test)
        times.append(took)
        assert triangles <= bc.mod("voice_ops").TRIANGLE_BUDGET
    times.sort()
    bc.log(f"{len(TESTS)} voice operations ran through commands.py; voice.run round trip "
           f"median {times[len(times) // 2] * 1000:.0f} ms, max {times[-1] * 1000:.0f} ms")

    yield from add_without_selection(talia, other, commander)
    yield from adds_in_view(talia, other, commander)
    yield from the_demo_question(talia, other, commander)
    yield from refused_shrink(talia, other, commander)

    # Too heavy: Suzanne at level 2 (15,744 triangles) times five is 78,720.
    suzanne = fresh()
    target = target_of(suzanne)
    yield from drained(talia, other)
    answer = yield from resolve(talia, "subdivide level two", target)
    receipt, _ = yield from commander.send(voice_run(commander, answer, target))
    assert receipt["outcome"] == "applied", receipt
    yield from watched(other, "the subdivision")
    yield from refused_heavy(talia, other, commander, "make five copies", suzanne, "triangles")
    undo, _ = yield from commander.send(commander.command("history.undo"))
    assert undo["summary"] == "Undid: " + receipt["summary"], undo  # the refusal left no step
    yield from watched(other, "the undo of the subdivision")
    redo, _ = yield from commander.send(commander.command("history.redo"))
    assert redo["summary"] == "Redid: " + receipt["summary"], redo
    yield from watched(other, "the redo of the subdivision")
    redo, _ = yield from commander.send(commander.command("history.redo"))
    assert redo["outcome"] == "rejected", redo  # no Redo brings the refused array back
    bc.log("ok a refused modifier leaves no Undo or Redo step")

    # Too heavy and reused: the Array of 2 goes back to 2 exactly (level 2 x 5 is 78,720).
    suzanne = fresh(array_of_two)
    target = target_of(suzanne)
    yield from drained(talia, other)
    answer = yield from resolve(talia, "subdivide level two", target)
    receipt, _ = yield from commander.send(voice_run(commander, answer, target))
    assert receipt["outcome"] == "applied", receipt  # 31,488 triangles
    yield from watched(other, "the subdivision after the array")
    yield from refused_heavy(talia, other, commander, "make five copies", suzanne, "triangles")
    assert bc.by_id(target["id"]).modifiers["Array"].count == 2

    # Too heavy by bytes: flat shading splits every vertex (~48,000 triangles, ~9 MB).
    fresh()
    grid = heavy_grid(flat=False)
    bpy.ops.ed.undo_push(message="Voice check: smooth bumps")
    yield from refused_heavy(talia, other, commander, "shade flat", grid, "MB of mesh")

    # Heavy already: a voice operation that makes it lighter still runs.
    fresh()
    grid = heavy_grid(flat=True)
    bpy.ops.ed.undo_push(message="Voice check: flat bumps")
    target = target_of(grid)
    yield from drained(talia, other)
    answer = yield from resolve(talia, "shade smooth", target)
    receipt, _ = yield from commander.send(voice_run(commander, answer, target))
    assert receipt["outcome"] == "applied", receipt
    yield from watched(other, "smoothing the heavy grid")
    bc.log("ok a heavy object can still get lighter")
    talia.close()
    other.close()
    addon_utils.disable(bc.MODULE, default_set=True)


if __name__ == "__main__":
    if bpy.app.background:
        bc.log("run this in GUI Blender (through ~/.local/bin/headless-run)")
        bc.finish(2)
    bc.main(run=checks)

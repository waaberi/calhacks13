"""Disposable background Blender fixture; never attaches to an interactive Host.

Exercises the production planner, native Editor/Undo wrapper, material readback,
metre/mm scenes, rollback after several successful steps, and save/reopen.
"""

import math
import sys
import tempfile
import uuid
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "blender_addon"))
from spatial_modeling import commands, edits, host, scene, sync, voice_ops


class NativeSync:
    def __init__(self):
        self.revision = 0
        self.publications = 0

    def object_id(self, obj):
        if sync.ID_PROPERTY not in obj:
            obj[sync.ID_PROPERTY] = uuid.uuid4().hex
        return obj[sync.ID_PROPERTY]

    def find_object(self, oid):
        return next(
            (o for o in bpy.context.view_layer.objects if o.get(sync.ID_PROPERTY) == oid), None
        )

    def generation(self, oid):
        return 0 if self.find_object(oid) is not None else None

    def flush(self):
        self.revision += 1
        self.publications += 1
        return self.revision

    def describe(self):
        return {"id": "1" * 32, "open_epoch": "2" * 32}


def near(a, b, message):
    assert len(a) == len(b) and all(abs(x - y) < 2e-5 * max(1, abs(y)) for x, y in zip(a, b)), (
        message,
        tuple(a),
        b,
    )


def execute(text, target=None):
    objects = [
        {"id": native.object_id(o), "name": o.name, "generation": 0}
        for o in bpy.context.view_layer.objects
    ]
    result = voice.composer.resolve(text, target, objects, document=("1" * 32, "2" * 32))
    assert result["decision"] == "run", result
    candidate = result["candidates"][0]
    resolution = uuid.uuid4().hex
    voice._keep(resolution, [candidate], candidate["primary"])
    before = native.publications
    applied = editor.apply(
        "voice.run", candidate["primary"], {"resolution": resolution, "choice": 1}
    )
    assert native.publications == before + 1, "only one final publish per sequence"
    return applied


def reset(unit):
    global native, voice, editor
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = unit
    bpy.context.preferences.edit.use_global_undo = True
    native = NativeSync()
    voice = voice_ops.Voice(native)
    editor = edits.Editor(native, host.undoable, voice=voice)
    bpy.ops.ed.undo_push(message="Fixture baseline")


def run(unit):
    reset(unit)
    result = execute(
        "add a cube then move it twenty centimeters along x then rotate it forty five degrees around z then scale it down fifty percent"
    )
    assert len(result.created) == 1
    assert result.selection == {"id": result.created[0]}
    oid = result.created[0]
    obj = native.find_object(oid)
    near(obj.location, (0.2 / unit, 0, 0), "meters converted to scene units")
    near(obj.scale, (0.5, 0.5, 0.5), "shrink")
    assert abs(obj.rotation_euler.z - math.pi / 4) < 1e-5
    editor.apply("history.undo", None, {})
    assert native.find_object(oid) is None, (
        "ONE Undo removes whole create/move/rotate/scale sequence"
    )
    editor.apply("history.redo", None, {})
    obj = native.find_object(oid)
    assert obj is not None
    near(obj.location, (0.2 / unit, 0, 0), "Redo whole chain")
    print("VOICE_SEQUENCE_NATIVE_CHAIN_UNDO PASS", unit)

    result = execute(
        "duplicate it ten centimeters along y then colour it blue then set its width twenty millimeters then scale it by negative one along x",
        oid,
    )
    duplicate_id = result.created[0]
    duplicate = native.find_object(duplicate_id)
    obj = native.find_object(oid)
    near(duplicate.location, (0.2 / unit, 0.1 / unit, 0), "duplicate offset")
    assert duplicate.name == "Cube.001", "private backups must not consume visible object names"
    assert duplicate.data != obj.data
    assert duplicate.scale.x < 0
    near([duplicate.dimensions.x * unit], [0.02], "exact width")
    near(scene.color(duplicate), (0.025, 0.12, 0.8, 1), "native and scene-sync colour")
    assert scene.color(obj) is None
    assert result.selection == {"id": duplicate_id}

    # Mirroring must compose with a later relative rotation, without treating
    # a reflected world-matrix quaternion as the native rotation channels.
    before = duplicate.matrix_world.copy()
    mirrored_scale = tuple(duplicate.scale)
    execute("rotate it thirty degrees around y then move it ten millimeters along z", duplicate_id)
    expected = Quaternion((0, 1, 0), math.pi / 6).to_matrix().to_4x4() @ before.to_3x3().to_4x4()
    expected.translation = before.translation + Vector((0, 0, .01 / unit))
    duplicate = native.find_object(duplicate_id)
    near([v for row in duplicate.matrix_world for v in row],
         [v for row in expected for v in row], "relative rotation after signed scale")
    near(duplicate.scale, mirrored_scale, "rotation retains mirrored scale channels")
    editor.apply("history.undo", None, {})
    duplicate = native.find_object(duplicate_id)
    near([v for row in duplicate.matrix_world for v in row],
         [v for row in before for v in row], "one Undo restores mirrored rotation/move chain")
    editor.apply("history.redo", None, {})
    duplicate = native.find_object(duplicate_id)
    near([v for row in duplicate.matrix_world for v in row],
         [v for row in expected for v in row], "Redo restores mirrored rotation/move chain")
    print("VOICE_SEQUENCE_MIRROR_ROTATE_UNDO PASS", unit)
    execute("reset its rotation then reset its scale then reset its colour", duplicate_id)
    duplicate = native.find_object(duplicate_id)
    near(duplicate.rotation_euler, (0, 0, 0), "reset rotation")
    near(duplicate.scale, (1, 1, 1), "reset signed local scale")
    assert scene.color(duplicate) is None
    print("VOICE_SEQUENCE_NATIVE_FIVE_ADDITIONS PASS", unit)

    # Shared-data colour must leave the other object and its material intact.
    sibling = duplicate.copy()
    sibling.pop(sync.ID_PROPERTY, None)
    bpy.context.scene.collection.objects.link(sibling)
    native.object_id(sibling)
    execute("colour it red then make it lighter", duplicate_id)
    near(scene.color(duplicate), (0.84, 0.22, 0.22, 1), "lighter material")
    assert scene.color(sibling) is None
    print("VOICE_SEQUENCE_SHARED_MATERIAL_ISOLATION PASS", unit)

    # Force a runtime refusal AFTER move, colour, geometry/modifier and creation steps.
    plane_mesh = bpy.data.meshes.new("Flat mesh")
    plane_mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    plane = bpy.data.objects.new("Plane", plane_mesh)
    bpy.context.scene.collection.objects.link(plane)
    bpy.context.view_layer.update()
    plane_id = native.object_id(plane)
    bpy.ops.ed.undo_push(message="Fixture plane")
    location = tuple(plane.location)
    vertices = [tuple(v.co) for v in plane.data.vertices]
    before = {o.name for o in bpy.context.view_layer.objects}
    pubs = native.publications
    try:
        execute(
            "move it ten millimeters along x then colour it green then add a mirror modifier then add a cube then select Plane then set its height twenty millimeters",
            plane_id,
        )
    except commands.Refused:
        pass
    else:
        raise AssertionError("zero-height dimension must fail")
    plane = native.find_object(plane_id)
    near(plane.location, location, "failure restores original location")
    assert [tuple(v.co) for v in plane.data.vertices] == vertices
    assert len(plane.modifiers) == 0 and scene.color(plane) is None
    assert {o.name for o in bpy.context.view_layer.objects} == before
    assert native.publications == pubs, "failed sequence must publish no intermediate edit"
    print("VOICE_SEQUENCE_RUNTIME_ROLLBACK PASS", unit)
    try:
        execute("convert to mesh then set its height twenty millimeters", plane_id)
    except commands.Refused:
        pass
    else:
        raise AssertionError("zero-height refusal after conversion must roll back")
    plane = native.find_object(plane_id)
    assert [tuple(v.co) for v in plane.data.vertices] == vertices
    print("VOICE_SEQUENCE_CONVERT_ROLLBACK PASS", unit)

    # Reused modifier values and object-pointer references must survive rollback too.
    modifier = plane.modifiers.new("Existing Mirror", "MIRROR")
    modifier.use_axis = (False, True, False)
    modifier.mirror_object = native.find_object(oid)
    try:
        execute("mirror on x then set its height twenty millimeters", plane_id)
    except commands.Refused:
        pass
    else:
        raise AssertionError("expected zero-height refusal after modifying existing Mirror")
    plane = native.find_object(plane_id)
    assert tuple(plane.modifiers[0].use_axis) == (False, True, False)
    assert plane.modifiers[0].mirror_object == native.find_object(oid)
    plane.modifiers.clear()
    # Fault injection AFTER native deletion: private backup recreates the deleted target.
    original_delete = editor._delete

    def fail_after_delete(obj, args):
        original_delete(obj, args)
        raise RuntimeError("injected post-delete failure")

    editor._delete = fail_after_delete
    try:
        execute("move it ten millimeters along x then delete it", plane_id)
    except RuntimeError as exc:
        assert "injected" in str(exc)
    else:
        raise AssertionError("injected failure must propagate for unknown-outcome reconciliation")
    finally:
        editor._delete = original_delete
    plane = native.find_object(plane_id)
    assert plane is not None
    near(plane.location, location, "rollback after native deletion restores target")
    print("VOICE_SEQUENCE_POST_DELETE_ROLLBACK PASS", unit)

    # Delete is deferred until validation/execution of all prior reversible steps succeeds.
    execute("colour it purple then delete it", plane_id)
    assert native.find_object(plane_id) is None
    editor.apply("history.undo", None, {})
    assert (
        native.find_object(plane_id) is not None
        and scene.color(native.find_object(plane_id)) is None
    )
    print("VOICE_SEQUENCE_DELETE_ONE_UNDO PASS", unit)

    execute("colour it orange then set its depth thirty millimeters", duplicate_id)
    destination = Path(tempfile.gettempdir()) / (
        "voice-sequence-fixture-" + uuid.uuid4().hex + ".blend"
    )
    bpy.ops.wm.save_as_mainfile(filepath=str(destination))
    bpy.ops.wm.open_mainfile(filepath=str(destination))
    duplicate = native.find_object(duplicate_id)
    assert duplicate is not None
    near(scene.color(duplicate), (0.95, 0.25, 0.015, 1), "material persists after reopen")
    near([duplicate.dimensions.y * unit], [0.03], "exact dimension persists")
    print("VOICE_SEQUENCE_PERSISTENCE PASS", unit)


try:
    for unit in (1.0, 0.001):
        run(unit)
    phrases = [
        "shade smooth",
        "shade flat",
        "shade auto smooth",
        "subdivide it once",
        "mirror on x",
        "solidify two millimeters",
        "decimate to fifty percent",
        "bevel the edges two millimeters",
        "add an array five copies",
        "make it a wire frame",
        "re mesh",
        "add a boolean",
        "weld",
        "screw",
        "triangulate",
        "apply all transforms",
        "origin to geometry",
        "separate by loose parts",
        "recalculate normals",
        "flip normals",
        "merge by distance",
        "smooth vertices",
        "convert to mesh",
    ]
    for unit in (1.0, 0.001):
        for phrase in phrases:
            reset(unit)
            if phrase == "separate by loose parts":
                import bmesh

                bpy.ops.mesh.primitive_cube_add(size=0.05 / unit)
                original = bpy.context.object
                bm = bmesh.new()
                bm.from_mesh(original.data)
                duplicated = bmesh.ops.duplicate(
                    bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces)
                )["geom"]
                bmesh.ops.translate(
                    bm,
                    vec=(0.1 / unit, 0, 0),
                    verts=[v for v in duplicated if isinstance(v, bmesh.types.BMVert)],
                )
                bm.to_mesh(original.data)
                bm.free()
                target_id = native.object_id(original)
                result = execute(phrase + " then move it one millimeter along x", target_id)
                obj = native.find_object(target_id)
            else:
                try:
                    result = execute(
                        "add a cube then " + phrase + " then move it one millimeter along x"
                    )
                except commands.Refused as exc:
                    if phrase == "re mesh" and unit == 0.001:
                        assert "geometry/size limits" in str(exc)
                        assert len(bpy.context.view_layer.objects) == 0 and native.publications == 0
                        print("VOICE_SEQUENCE_BUDGET_REFUSAL PASS", unit, phrase)
                        continue
                    raise
                obj = native.find_object(result.created[0])
            near(obj.location, (0.001 / unit, 0, 0), "registry step chains into existing Move")
            if phrase == "solidify two millimeters":
                near(
                    [obj.modifiers[0].thickness * unit],
                    [0.002],
                    "modifier distance uses scene unit",
                )
            print("VOICE_SEQUENCE_REGISTRY_CHAIN PASS", unit, phrase)
    print("VOICE_SEQUENCE_NATIVE_RESULT PASS")
except Exception:  # noqa: BLE001 - fixture must report failure and exit nonzero
    import traceback

    traceback.print_exc()
    sys.stdout.flush()
    raise SystemExit(1)

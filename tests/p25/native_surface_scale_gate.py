"""Disposable factory Blender: contact-pivot held scale and native history."""

import argparse
import json
import sys
import traceback
import uuid
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
from spatial_modeling import (
    document,
    edits,
    host,
    leases,
    live_edit,
    modeling_tools,
    protocol,
    session,
    spatial_model_edit,
    sync,
)


def run(output):
    assert "--factory-startup" in sys.argv, "Use a new factory process only"
    bpy.utils.keyconfig_init()
    from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active
    VIEW3D_PT_tools_active.register_ensure()
    bpy.context.preferences.edit.use_global_undo = True
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=.1, depth=.3, location=(0, 0, .15))
    cylinder = bpy.context.active_object
    cylinder.name = "Disposable contact cylinder"
    bpy.ops.mesh.primitive_cube_add(size=.1, location=(.8, 0, .7))
    free = bpy.context.active_object
    free.name = "Unselected floating control"
    free.select_set(False)
    cylinder.select_set(True)
    bpy.context.view_layer.objects.active = cylinder
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex)
    sync.register()
    sync.start(doc, sess)
    sync.flush()
    editor = edits.Editor(sync, host.undoable, document=doc)
    lses = leases.Leases(sess, editor)
    manager = live_edit.LiveEdits(sess, editor, lses, host.undoable, kernel=modeling_tools)
    oid, untouched = sync.object_id(cylinder), sync.object_id(free)
    window = bpy.context.window
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.tool_set_by_id(name="builtin.scale")
    report = {"passed": False, "headset_acceptance": False, "checks": [], "blender": bpy.app.version_string}

    class Connection:
        can_edit = True

        def send(self, *_messages):
            pass

    conn = Connection()
    actor = {"actor_id": uuid.uuid4().hex, "name": "Private contact scale gate", "role": "vr"}
    sess.participants[conn] = actor
    sess.store.join(actor)

    def ask(action, **fields):
        native = sess.document()
        identity = {"session_id": sess.session_id, "host_epoch": sess.host_epoch,
                    "document_id": native["id"], "open_epoch": native["open_epoch"], "actor_id": actor["actor_id"]}
        reply = manager.handler(action)(protocol.message("live.edit." + action, identity | fields), conn)
        assert reply["type"] == "live.edit.state", reply
        return reply["payload"]

    def state(identity):
        bpy.context.view_layer.update()
        obj = sync.find_object(identity)
        return tuple(value for row in obj.matrix_world for value in row)

    def geometry():
        bpy.context.view_layer.update()
        obj = sync.find_object(oid)
        points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
        return min(p.z for p in points), max(p.z for p in points), max(abs(p.x) for p in points)

    def near(actual, expected):
        assert max(abs(a - b) for a, b in zip(actual, expected)) < 2e-6, (actual, expected)

    def begin():
        native = spatial_model_edit.read_state(bpy.context, sync)
        assert native["available"], native
        operation = {"tool": "object.scale", "native_tool": "builtin.scale", "mode": "OBJECT",
                     "target_id": oid, "targets": [oid], "topology_token": native["topology_token"],
                     "settings": native["settings"], "selection": {"component": "object", "indices": []}}
        lease = lses.grant(actor["actor_id"], "exclusive")
        token = ask("begin", base_revision=sync.flush(), lease=lease["lease_id"],
                    targets=[{"id": oid, "generation": sync.generation(oid)}], operation=operation)["edit_session_id"]
        return lease, token

    try:
        bpy.ops.ed.undo_push(message="Native state before contact scaling")
        before, other = state(oid), state(untouched)
        baseline_marker = bpy.context.scene.get(edits.STEP_PROPERTY)
        lease, token = begin()
        for seq, factor in enumerate((1.2, 2, .65), 1):
            ask("update", edit_session_id=token, sequence=seq,
                parameters={"scale": [1, 1, factor], "pivot_m": [0, 0, 0]})
            near(geometry(), (0, .3 * factor, .1))
            near(state(untouched), other)
            near(tuple(sync.find_object(oid).matrix_world @ Vector((0, 0, -.15))), (0, 0, 0))
            assert bpy.context.scene.get(edits.STEP_PROPERTY) == baseline_marker
        ask("commit", edit_session_id=token, sequence=3)
        lses.end(lease["lease_id"], actor["actor_id"])
        committed = state(oid)
        assert committed != before
        editor.apply("history.undo", None, {})
        near(state(oid), before)
        editor.apply("history.redo", None, {})
        near(state(oid), committed)
        near(geometry(), (0, .195, .1))
        report["checks"].append("successive cumulative native axis updates keep desk contact and commit one Undo/Redo")
        prior = state(oid)
        prior_marker = bpy.context.scene.get(edits.STEP_PROPERTY)
        lease, token = begin()
        ask("update", edit_session_id=token, sequence=1,
            parameters={"scale": [2, 2, 2], "pivot_m": [0, 0, 0]})
        near(geometry(), (0, .39, .2))
        ask("cancel", edit_session_id=token, reason="Disposable contact scale cancellation")
        lses.end(lease["lease_id"], actor["actor_id"])
        near(state(oid), prior)
        assert bpy.context.scene.get(edits.STEP_PROPERTY) == prior_marker
        report["checks"].append("uniform scale live preview and Cancel preserve exact starting native geometry/history")
        lease, token = begin()
        ask("update", edit_session_id=token, sequence=1,
            parameters={"scale": [-1, 1, 1.5], "pivot_m": [0, 0, 0]})
        near(geometry(), (0, .2925, .1))
        assert sync.find_object(oid).scale.x < 0
        ask("commit", edit_session_id=token, sequence=1)
        lses.end(lease["lease_id"], actor["actor_id"])
        mirrored = state(oid)
        editor.apply("history.undo", None, {})
        near(state(oid), prior)
        editor.apply("history.redo", None, {})
        near(state(oid), mirrored)
        near(state(untouched), other)
        report["checks"].append("signed tangent-axis mirror plus height scaling retain native contact/Undo/Redo and leave unselected floating object untouched")
        report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc()
        raise
    finally:
        manager.stop()
        sync.unregister()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    print(json.dumps(run(args.output)))

"""Native lock-preserving live transforms in a new factory background process."""

import argparse
import json
import sys
import traceback
import uuid
from pathlib import Path

import bpy
from mathutils import Quaternion

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
from spatial_modeling import (
    document,
    edits,
    host,
    leases,
    live_edit,
    modeling_extras,
    modeling_tools,
    session,
    spatial_model_edit,
    sync,
)


def channels(obj):
    return [list(values) for values in edits._channels(obj)]


def animation(obj):
    return [(c.data_path, c.array_index, [(list(k.co), k.interpolation) for k in c.keyframe_points])
            for c in modeling_extras._action_curves(obj.animation_data.action)]


def protocol_checks(report):
    """Real lease/live/baseline/history protocol; no test kernel or mock Undo."""
    bpy.context.preferences.edit.use_global_undo = True
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex)
    sync.register()
    sync.start(doc, sess)
    editor = edits.Editor(sync, host.undoable, document=doc)
    lses = leases.Leases(sess, editor)

    class Connection:
        can_edit = True

        def send(self, *_messages):
            pass

    conn = Connection()
    actor = {"actor_id": uuid.uuid4().hex, "name": "Private lock gate", "role": "vr"}
    sess.participants[conn] = actor
    sess.store.join(actor)
    manager = live_edit.LiveEdits(sess, editor, lses, host.undoable)

    def request(action, **fields):
        native = sess.document()
        identity = {"session_id": sess.session_id, "host_epoch": sess.host_epoch,
                    "document_id": native["id"], "open_epoch": native["open_epoch"], "actor_id": actor["actor_id"]}
        return manager.handler(action)({"v": 1, "type": "live.edit." + action,
                                        "id": uuid.uuid4().hex, "payload": identity | fields}, conn)

    def ask(action, **fields):
        reply = request(action, **fields)
        assert reply["type"] == "live.edit.state", reply
        return reply["payload"]

    def begin(obj, suffix):
        native = spatial_model_edit.read_state(bpy.context, sync)
        assert native["available"], native
        oid = sync.object_id(obj)
        lease = lses.grant(actor["actor_id"], "exclusive")
        operation = {"tool": "object." + suffix, "native_tool": native["native_tool"], "mode": "OBJECT",
                     "target_id": oid, "targets": [oid], "selection": {"component": "object", "indices": []},
                     "topology_token": native["topology_token"], "settings": native["settings"]}
        started = ask("begin", base_revision=sync.flush(), lease=lease["lease_id"],
                      targets=[{"id": oid, "generation": sync.generation(oid)}], operation=operation)
        return started["edit_session_id"], lease, oid

    def same(a, b):
        return all(abs(x - y) < 1e-5 for first, second in zip(a, b) for x, y in zip(first, second))

    try:
        area = next(a for a in bpy.context.window.screen.areas if a.type == "VIEW_3D")
        region = next(r for r in area.regions if r.type == "WINDOW")
        for native_tool, suffix, lock, delta in (
                ("builtin.move", "translate", "lock_location", {"translation_m": [.02, .03, .04]}),
                ("builtin.scale", "scale", "lock_scale", {"scale": [1.3, 1.4, 1.5]}),
                ("builtin.rotate", "rotate", "lock_rotation", {"rotation": list(Quaternion((0, 0, 1), .3))})):
            for item in list(bpy.context.scene.objects):
                bpy.data.objects.remove(item, do_unlink=True)
            bpy.ops.mesh.primitive_cube_add(size=.1)
            obj = bpy.context.active_object
            obj.location = (.1, .2, .3)
            obj.rotation_mode = "XYZ"
            obj.scale = (1.1, 1.2, 1.3)
            obj.keyframe_insert(data_path="scale", frame=1)
            setattr(obj, lock, (True, False, False))
            bpy.context.scene.unit_settings.scale_length = 1
            with bpy.context.temp_override(window=bpy.context.window, area=area, region=region):
                bpy.ops.wm.tool_set_by_id(name=native_tool)
            sync.flush()
            before = channels(obj)
            keys = animation(obj)
            bpy.ops.ed.undo_push(message="Preexisting native locked-channel work")
            marker = bpy.context.scene.get(edits.STEP_PROPERTY)
            edit_id, lease, oid = begin(obj, suffix)
            ask("update", edit_session_id=edit_id, sequence=1, parameters=delta)
            held = channels(obj)
            assert not same(before, held) and bpy.context.scene.get(edits.STEP_PROPERTY) == marker
            ask("commit", edit_session_id=edit_id, sequence=1)
            lses.end(lease["lease_id"], actor["actor_id"])
            assert same(channels(sync.find_object(oid)), held)
            editor.apply("history.undo", None, {})
            assert same(channels(sync.find_object(oid)), before)
            editor.apply("history.redo", None, {})
            obj = sync.find_object(oid)
            assert same(channels(obj), held) and animation(obj) == keys
            saved = channels(obj)
            edit_id, lease, oid = begin(obj, suffix)
            ask("update", edit_session_id=edit_id, sequence=1, parameters=delta)
            ask("cancel", edit_session_id=edit_id, reason="Private lock cancellation proof")
            lses.end(lease["lease_id"], actor["actor_id"])
            assert same(channels(obj), saved) and animation(obj) == keys
            edit_id, lease, oid = begin(obj, suffix)
            setattr(obj, lock, (True, True, False))
            refused = request("update", edit_session_id=edit_id, sequence=1, parameters=delta)
            assert refused["type"] == "error" and refused["payload"]["code"] == "stale_revision", refused
            assert same(channels(obj), saved)
            ask("cancel", edit_session_id=edit_id, reason="Private changed-lock cleanup")
            lses.end(lease["lease_id"], actor["actor_id"])
            assert tuple(getattr(obj, lock)) == (True, True, False) and animation(obj) == keys
            report["checks"].append({"protocol_tool": native_tool, "real_live_update": True,
                                     "one_native_undo_redo": True, "cancel_restores_channels": True,
                                     "changed_locks_refused_without_mutation": True, "keyframes_preserved": True})
    finally:
        manager.stop()
        sync.unregister()


def run(output):
    assert "--factory-startup" in sys.argv and "--background" in sys.argv
    bpy.context.preferences.filepaths.temporary_directory = str(output.parent)
    bpy.utils.keyconfig_init()
    from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active
    VIEW3D_PT_tools_active.register_ensure()
    report = {"passed": False, "physical_acceptance": False, "background": True,
              "blender": bpy.app.version_string, "checks": []}

    class Sync:
        @staticmethod
        def find_object(identity):
            return next((o for o in bpy.context.scene.objects if o.get("spatial_modeling_id") == identity), None)

        @staticmethod
        def generation(_identity):
            return 1

    editor = edits.Editor(Sync, host.undoable)
    area = next(a for a in bpy.context.window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    for unit in (1.0, .001):
        for native_tool, suffix, lock, delta in (
                ("builtin.move", "translate", "lock_location", {"translation_m": [.02, .03, .04]}),
                ("builtin.scale", "scale", "lock_scale", {"scale": [1.3, 1.4, 1.5]}),
                ("builtin.rotate", "rotate", "lock_rotation", {"rotation": list(Quaternion((0, 0, 1), .3))})):
            for item in list(bpy.context.scene.objects):
                bpy.data.objects.remove(item, do_unlink=True)
            bpy.ops.mesh.primitive_cube_add(size=.1 / unit)
            obj = bpy.context.active_object
            obj["spatial_modeling_id"] = identity = uuid.uuid4().hex
            obj.rotation_mode = "XYZ"
            obj.location = (.1 / unit, .2 / unit, .3 / unit)
            obj.scale = (1.1, 1.2, 1.3)
            obj.keyframe_insert(data_path="scale", frame=1)
            action = obj.animation_data.action
            setattr(obj, lock, (True, False, False))
            bpy.context.scene.unit_settings.scale_length = unit
            bpy.context.view_layer.update()
            with bpy.context.temp_override(window=bpy.context.window, area=area, region=region):
                bpy.ops.wm.tool_set_by_id(name=native_tool)
            native = spatial_model_edit.read_state(bpy.context, Sync)
            assert native["available"], native
            # Capture settings even on the historical blanket-lock refusal so
            # the native execution proof distinguishes admission from behavior.
            settings = spatial_model_edit._options(bpy.context, obj, native_tool)
            operation = {"tool": "object." + suffix, "native_tool": native_tool,
                         "mode": "OBJECT", "target_id": identity, "targets": [identity],
                         "selection": {"component": "object", "indices": []}, "settings": settings}
            before = edits._channels(obj)
            locks_before = (tuple(obj.lock_location), tuple(obj.lock_rotation), tuple(obj.lock_scale))
            modeling_tools.apply_live(editor, operation, delta)
            values = obj.location if suffix == "translate" else obj.scale if suffix == "scale" else obj.rotation_euler
            baseline = before[0 if suffix == "translate" else 4 if suffix == "scale" else 1]
            assert abs(values[0] - baseline[0]) < 1e-6, (native_tool, list(values), list(baseline))
            assert any(abs(values[i] - baseline[i]) > 1e-5 for i in (1, 2)), (native_tool, list(values))
            assert (tuple(obj.lock_location), tuple(obj.lock_rotation), tuple(obj.lock_scale)) == locks_before
            assert obj.animation_data.action == action
            edits._restore(obj, before)
            bpy.context.view_layer.update()
            after = edits._channels(obj)
            assert all(abs(a - b) < 1e-6 for old, current in zip(before, after) for a, b in zip(old, current))
            report["checks"].append({"tool": native_tool, "unit": unit,
                                     "available": native["available"], "historical_reason": native["reason"],
                                     "locked_x_preserved": True, "unlocked_channels_changed": True,
                                     "locks_action_and_baseline_preserved": True})
    protocol_checks(report)
    report["passed"] = True
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("NATIVE_LIVE_LOCKED_CHANNELS_CHECK PASS", len(report["checks"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    try:
        run(args.output)
    except Exception:
        args.output.write_text(json.dumps({"passed": False, "error": traceback.format_exc()}, indent=2), encoding="utf-8")
        raise

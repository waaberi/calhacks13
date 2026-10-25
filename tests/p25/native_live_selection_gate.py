"""Factory GUI only: native transform history survives deselect/reselect recovery."""

import argparse
import json
import math
import sys
import traceback
import uuid
from pathlib import Path

import bpy

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
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex)
    sync.register()
    sync.start(doc, sess)
    sync.flush()
    editor = edits.Editor(sync, host.undoable, document=doc)
    lses = leases.Leases(sess, editor)
    manager = live_edit.LiveEdits(sess, editor, lses, host.undoable, kernel=modeling_tools)
    report = {"passed": False, "headset_acceptance": False, "checks": [], "blender": bpy.app.version_string}

    class Connection:
        can_edit = True

        def send(self, *_messages):
            pass

    conn = Connection()
    actor = {"actor_id": uuid.uuid4().hex, "name": "Private live selection recovery", "role": "vr"}
    sess.participants[conn] = actor
    sess.store.join(actor)
    oid = sync.object_id(bpy.context.active_object)
    window = bpy.context.window
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")

    def ask(action, **fields):
        native = sess.document()
        identity = {"session_id": sess.session_id, "host_epoch": sess.host_epoch,
                    "document_id": native["id"], "open_epoch": native["open_epoch"], "actor_id": actor["actor_id"]}
        reply = manager.handler(action)(protocol.message("live.edit." + action, identity | fields), conn)
        assert reply["type"] == "live.edit.state", reply
        return reply["payload"]

    def matrix():
        bpy.context.view_layer.update()
        return tuple(value for row in sync.find_object(oid).matrix_world for value in row)

    def near(actual, expected):
        assert max(abs(a - b) for a, b in zip(actual, expected)) < 1e-6, (actual, expected)

    def transact(tool, parameters, selected=None):
        native = spatial_model_edit.read_state(bpy.context, sync)
        selection_only = selected is not None
        if not selection_only:
            assert native["available"], native
        operation = {"tool": tool, "native_tool": native["native_tool"], "mode": "OBJECT",
                     "target_id": oid, "targets": [oid], "topology_token": native["topology_token"],
                     "settings": native["settings"], "selection": {"component": "object", "indices": []}}
        if selection_only:
            operation["selection_only"] = True
            operation["selection"].update(objects=[oid] if selected else [], active_id=oid if selected else "")
        lease = lses.grant(actor["actor_id"], "exclusive")
        token = ask("begin", base_revision=sync.flush(), lease=lease["lease_id"],
                    targets=[{"id": oid, "generation": sync.generation(oid)}], operation=operation)["edit_session_id"]
        ask("update", edit_session_id=token, sequence=1, parameters=parameters)
        ask("commit", edit_session_id=token, sequence=1)
        lses.end(lease["lease_id"], actor["actor_id"])

    try:
        bpy.ops.ed.undo_push(message="Native state before live selection regression")
        cases = [("builtin.move", "object.translate", {"translation_m": [.013, .007, 0]}),
                 ("builtin.rotate", "object.rotate", {"rotation": [0, 0, math.sin(.13), math.cos(.13)]}),
                 ("builtin.scale", "object.scale", {"scale": [1.1, .9, 1.05]})]
        for native_tool, tool, parameters in cases:
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.wm.tool_set_by_id(name=native_tool)
            before = matrix()
            transact(tool, parameters)
            transformed = matrix()
            assert transformed != before, tool
            marker = bpy.context.scene.get(edits.STEP_PROPERTY)
            for _attempt in range(2):
                transact("object.selection", {}, selected=False)
                assert bpy.context.active_object is None and not bpy.context.selected_objects
                unavailable = spatial_model_edit.read_state(bpy.context, sync)
                assert not unavailable["available"] and unavailable["settings"] == {}
                assert unavailable["selection"]["objects"] == []
                assert unavailable["selection"]["active_id"] == ""
                assert unavailable["selection"]["component"] == "object"
                assert unavailable["selection"]["indices"] == []
                assert unavailable["selection"]["selection_token"] == unavailable["selection_token"]
                near(matrix(), transformed)
                transact("object.selection", {}, selected=True)
                assert bpy.context.active_object == sync.find_object(oid)
                assert bpy.context.selected_objects == [sync.find_object(oid)]
                assert spatial_model_edit.read_state(bpy.context, sync)["available"]
                near(matrix(), transformed)
                assert bpy.context.scene.get(edits.STEP_PROPERTY) == marker
            editor.apply("history.undo", None, {})
            near(matrix(), before)
            editor.apply("history.redo", None, {})
            near(matrix(), transformed)
            report["checks"].append({"tool": tool, "deselect_reselect_cycles": 2,
                                     "no_active_object_recovery": True, "geometry_preserved": True,
                                     "native_undo_redo_preserved": True})
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

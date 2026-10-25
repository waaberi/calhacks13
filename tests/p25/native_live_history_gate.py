"""Fresh factory Blender ONLY: native live updates and final-reconstruction Undo."""

import argparse
import json
import sys
import traceback
import uuid
from pathlib import Path
from types import SimpleNamespace

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))

from spatial_modeling import commands, document, edits, host, leases, live_edit, session, sync


def run(output):
    bpy.ops.wm.read_factory_settings(use_empty=False)
    bpy.context.preferences.edit.use_global_undo = True
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex)
    sync.register()
    sync.start(doc, sess)
    sync.flush()
    editor = edits.Editor(sync, host.undoable, document=doc)
    lses = leases.Leases(sess, editor)
    oid = sync.object_id(bpy.context.active_object)
    report = {"passed": False, "headset_acceptance": False, "blender": bpy.app.version_string, "checks": []}
    class Connection:
        can_edit = True
        def send(self, *_messages):
            pass
    conn = Connection()
    actor = {"actor_id": uuid.uuid4().hex, "name": "Isolated live history", "role": "vr"}
    sess.participants[conn] = actor
    sess.store.join(actor)
    def context():
        return {"mode": bpy.context.mode, "native_tool": "builtin.move"}
    def apply(_editor, operation, parameters):
        obj = sync.find_object(operation["target_id"])
        if operation.get("selection_only"):
            if bpy.context.mode == "OBJECT":
                obj.select_set(True)
                bpy.context.view_layer.objects.active = obj
            else:
                bm = bmesh.from_edit_mesh(obj.data)
                bm.verts.ensure_lookup_table()
                for face in bm.faces:
                    face.select_set(False)
                for edge in bm.edges:
                    edge.select_set(False)
                for vertex in bm.verts:
                    vertex.select_set(False)
                bm.verts[0].select_set(True)
                bmesh.update_edit_mesh(obj.data)
                obj.update_from_editmode()
            return commands.Applied("Native selection only", selection={"id": oid})
        if operation.get("tool") == "test.subdivide":
            bm = bmesh.from_edit_mesh(obj.data)
            bm.edges.ensure_lookup_table()
            bmesh.ops.subdivide_edges(bm, edges=[bm.edges[0]], cuts=parameters["cuts"])
            bmesh.update_edit_mesh(obj.data, destructive=True)
            obj.update_from_editmode()
            return commands.Applied("Live subdivided edge")
        if bpy.context.mode == "OBJECT":
            return _editor._move(obj, {"by": parameters["translation"]})
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.verts[0].co += Vector(parameters["translation"])
        bmesh.update_edit_mesh(obj.data)
        obj.update_from_editmode()
        bpy.context.view_layer.update()
        return commands.Applied("Live moved vertex")
    kernel = SimpleNamespace(validate_live=lambda *_: None, apply_live=apply)
    manager = live_edit.LiveEdits(sess, editor, lses, host.undoable, kernel=kernel, context=context)
    def identity():
        native = sess.document()
        return {"session_id": sess.session_id, "host_epoch": sess.host_epoch,
                "document_id": native["id"], "open_epoch": native["open_epoch"], "actor_id": actor["actor_id"]}
    def request(action, **payload):
        msg = {"v": 1, "type": "live.edit." + action, "id": uuid.uuid4().hex, "payload": identity() | payload}
        result = manager.handler(action)(msg, conn)
        assert result["type"] == "live.edit.state", result
        return result["payload"]
    def point():
        obj = sync.find_object(oid)
        if bpy.context.mode == "OBJECT":
            return obj.location.copy()
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        return bm.verts[0].co.copy()
    def close(actual, expected):
        assert (actual - expected).length < 1e-6, (tuple(actual), tuple(expected))
    try:
        for mode in ("OBJECT", "EDIT_MESH"):
            if mode == "EDIT_MESH":
                bpy.ops.object.mode_set(mode="EDIT")
                bm = bmesh.from_edit_mesh(sync.find_object(oid).data)
                bm.verts.ensure_lookup_table()
                bm.verts[1].co.z += .037  # preexisting native work, separate history
                bmesh.update_edit_mesh(sync.find_object(oid).data)
                sync.find_object(oid).update_from_editmode()
            sync.flush()
            bpy.ops.ed.undo_push(message="Native work before live gesture")
            start = point()
            lease = lses.grant(actor["actor_id"], "exclusive")
            begin = request("begin", base_revision=sync.flush(), lease=lease["lease_id"],
                            targets=[{"id": oid, "generation": sync.generation(oid)}],
                            operation={"target_id": oid, "mode": mode, "native_tool": "builtin.move"})
            token = begin["edit_session_id"]
            request("update", edit_session_id=token, sequence=1, parameters={"translation": [.02, 0, 0]})
            close(point(), start + Vector((.02, 0, 0)))
            request("update", edit_session_id=token, sequence=2, parameters={"translation": [.05, 0, 0]})
            close(point(), start + Vector((.05, 0, 0)))
            report["checks"].append(mode + " actual native changes during held gesture; cumulative baseline parameters")
            result = request("commit", edit_session_id=token, sequence=2)
            assert result["phase"] == "committed"
            lses.end(lease["lease_id"], actor["actor_id"])
            close(point(), start + Vector((.05, 0, 0)))
            editor.apply("history.undo", None, {})
            close(point(), start)
            editor.apply("history.redo", None, {})
            close(point(), start + Vector((.05, 0, 0)))
            report["checks"].append(mode + " one Undo returns pregesture baseline; Redo returns final shape")
            start = point()
            lease = lses.grant(actor["actor_id"], "exclusive")
            begin = request("begin", base_revision=sync.flush(), lease=lease["lease_id"],
                            targets=[{"id": oid, "generation": sync.generation(oid)}],
                            operation={"target_id": oid, "mode": mode, "native_tool": "builtin.move"})
            token = begin["edit_session_id"]
            request("update", edit_session_id=token, sequence=1, parameters={"translation": [.1, 0, 0]})
            close(point(), start + Vector((.1, 0, 0)))
            request("cancel", edit_session_id=token, reason="Isolated cancel")
            close(point(), start)
            lses.end(lease["lease_id"], actor["actor_id"])
            undo = editor.apply("history.undo", None, {})
            assert "live" in undo.summary.lower() or "moved" in undo.summary.lower(), undo.summary
            report["checks"].append(mode + " exact Cancel adds no native Undo step")
            selection_start = point()
            marker = bpy.context.scene.get(edits.STEP_PROPERTY)
            lease = lses.grant(actor["actor_id"], "exclusive")
            begin = request("begin", base_revision=sync.flush(), lease=lease["lease_id"],
                            targets=[{"id": oid, "generation": sync.generation(oid)}],
                            operation={"target_id": oid, "mode": mode, "selection_only": True,
                                       "tool": "object.selection" if mode == "OBJECT" else "mesh.selection"})
            request("update", edit_session_id=begin["edit_session_id"], sequence=1, parameters={})
            request("commit", edit_session_id=begin["edit_session_id"], sequence=1)
            lses.end(lease["lease_id"], actor["actor_id"])
            close(point(), selection_start)
            assert bpy.context.scene.get(edits.STEP_PROPERTY) == marker
            editor.apply("history.redo", None, {})
            report["checks"].append(mode + " native selection synchronization preserves geometry, step marker and Redo history")
        mesh = bmesh.from_edit_mesh(sync.find_object(oid).data)
        original_vertices = len(mesh.verts)
        bpy.ops.ed.undo_push(message="Native mesh before live topology")
        lease = lses.grant(actor["actor_id"], "exclusive")
        begin = request("begin", base_revision=sync.flush(), lease=lease["lease_id"],
                        targets=[{"id": oid, "generation": sync.generation(oid)}],
                        operation={"target_id": oid, "mode": "EDIT_MESH", "tool": "test.subdivide"})
        token = begin["edit_session_id"]
        request("update", edit_session_id=token, sequence=1, parameters={"cuts": 1})
        assert len(bmesh.from_edit_mesh(sync.find_object(oid).data).verts) == original_vertices + 1
        request("update", edit_session_id=token, sequence=2, parameters={"cuts": 3})
        assert len(bmesh.from_edit_mesh(sync.find_object(oid).data).verts) == original_vertices + 3
        request("commit", edit_session_id=token, sequence=2)
        lses.end(lease["lease_id"], actor["actor_id"])
        editor.apply("history.undo", None, {})
        assert len(bmesh.from_edit_mesh(sync.find_object(oid).data).verts) == original_vertices
        editor.apply("history.redo", None, {})
        assert len(bmesh.from_edit_mesh(sync.find_object(oid).data).verts) == original_vertices + 3
        report["checks"].append("Real native topology updates do not accumulate; one Undo/Redo spans complete gesture")
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
    parsed = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    print(json.dumps(run(parsed.output)))

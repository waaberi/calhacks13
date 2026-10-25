"""Private factory GUI only: real mirrored leases + native preview/direct/voice handoff."""
import argparse
import functools
import json
import sys
import time
import traceback
import uuid
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
from spatial_modeling import (
    commands,
    document,
    edits,
    host,
    leases,
    live_edit,
    modeling_tools,
    preview_spatial,
    protocol,
    session,
    session_store,
    spatial_model_edit,
    sync,
    voice_ops,
)


def run(output, url, database):
    assert "--factory-startup" in sys.argv and not bpy.app.background
    bpy.utils.keyconfig_init()
    from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active
    VIEW3D_PT_tools_active.register_ensure()
    bpy.context.preferences.edit.use_global_undo = True
    store = session_store.MirroredStore(functools.partial(
        session_store.SpacetimeStore, output.parent / "private-native-host-token", url=url, database=database))
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex, store=store)
    sync.register(); sync.start(doc, sess); sync.flush()
    editor = edits.Editor(sync, host.undoable, doc, voice=voice_ops.Voice(sync))
    manager = leases.Leases(sess, editor)
    ui = preview_spatial.NativePreviewSessions(sess, manager, lambda: bpy.context)
    live = live_edit.LiveEdits(sess, editor, manager, host.undoable, kernel=modeling_tools)
    cmd = commands.Commands(sess, editor, leases=manager)
    class Connection:
        can_edit = True
        def __init__(self): self.messages = []
        def send(self, *messages): self.messages.extend(messages)
    local, remote = Connection(), Connection()
    for conn, name, role in [(local, "Talia", "vr"), (remote, "Lee", "blender-client")]:
        actor = {"actor_id": uuid.uuid4().hex, "name": name, "role": role}
        sess.participants[conn] = actor; store.join(actor)
    def wait(test):
        deadline = time.monotonic() + 15
        while not test():
            store.poll()
            if time.monotonic() > deadline: raise TimeoutError(store.status)
            time.sleep(.005)
    def identity(conn):
        d = sess.document()
        return {"session_id": sess.session_id, "host_epoch": sess.host_epoch,
                "document_id": d["id"], "open_epoch": d["open_epoch"],
                "actor_id": sess.participants[conn]["actor_id"]}
    def acquire(conn):
        msg = protocol.message("lease.acquire", identity(conn) | {"mode": "exclusive", "targets": []})
        answer = manager.acquire(msg, conn)
        if answer is None:
            wait(lambda: any(m.get("re") == msg["id"] for m in conn.messages))
            answer = next(m for m in conn.messages if m.get("re") == msg["id"])
        return answer
    def release(lease): manager.end(lease["lease_id"], lease["owner"]["actor_id"])
    def gesture(action, **fields):
        reply = live.handler(action)(protocol.message("live.edit." + action, identity(local) | fields), local)
        assert reply["type"] == "live.edit.state", reply
        return reply["payload"]
    def position(): return tuple(sync.find_object(oid).location)
    report = {"passed": False, "physical_acceptance": False, "checks": []}
    try:
        wait(lambda: store.deciding)
        obj = bpy.context.active_object; oid = sync.object_id(obj)
        obj.location.x = .031; sync.flush(); bpy.ops.ed.undo_push(message="Prior native work")
        ui_reply = ui.begin(protocol.message("preview.ui.begin", identity(local)), local)
        assert ui_reply["type"] == "preview.ui.granted", ui_reply
        assert ui.state(local)["input_allowed"] and not ui.state(remote)["input_allowed"]
        assert acquire(remote)["payload"]["code"] == "lease_conflict"
        assert ui.display_leases()[0]["owner"]["actor_id"] == sess.participants[local]["actor_id"]
        ended = ui.end(protocol.message("preview.ui.end", identity(local) | {"ui_session_id": ui.token}), local)
        assert ended["type"] == "preview.ui.ended" and not store.leases()
        report["checks"].append("same-user preview explicit end ACK; real foreign writer refused; display owner is local VR")
        window = bpy.context.window; area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
        with bpy.context.temp_override(window=window, area=area, region=next(r for r in area.regions if r.type == "WINDOW")):
            bpy.ops.wm.tool_set_by_id(name="builtin.move")
        before = position()
        def begin():
            granted = acquire(local); assert granted["type"] == "lease.granted", granted
            lease = granted["payload"]["lease"]
            state = spatial_model_edit.read_state(bpy.context, sync)
            token = gesture("begin", base_revision=sync.flush(), lease=lease["lease_id"],
                targets=[{"id": oid, "generation": sync.generation(oid)}],
                operation={"tool": "object.translate", "native_tool": state["native_tool"], "mode": "OBJECT",
                    "target_id": oid, "targets": [oid], "topology_token": state["topology_token"],
                    "settings": state["settings"], "selection": {"component": "object", "indices": []}})["edit_session_id"]
            return lease, token
        lease, token = begin()
        assert acquire(remote)["payload"]["code"] == "lease_conflict"
        for sequence, delta in [(1, .01), (2, .02)]:
            gesture("update", edit_session_id=token, sequence=sequence, parameters={"translation_m": [delta, 0, 0]})
            assert abs(position()[0] - before[0] - delta) < 1e-6
        gesture("commit", edit_session_id=token, sequence=2); release(lease)
        after = position(); editor.apply("history.undo", None, {}); assert abs(position()[0] - before[0]) < 1e-6
        editor.apply("history.redo", None, {}); assert abs(position()[0] - after[0]) < 1e-6
        report["checks"].append("SpacetimeDB-granted live native updates; foreign conflicts; one UndoRedo preserves prior work")
        lease, token = begin()
        gesture("update", edit_session_id=token, sequence=1, parameters={"translation_m": [.05, 0, 0]})
        gesture("cancel", edit_session_id=token); release(lease)
        assert abs(position()[0] - after[0]) < 1e-6
        report["checks"].append("native live Cancel restores exact accepted baseline")
        resolved = editor.voice.on_resolve(protocol.message("voice.resolve", {
            "text": "move it ten millimeters along y then scale it by negative one along x",
            "confidence": 1.0, "composition": True,
            "target": {"id": oid, "generation": sync.generation(oid)}}), local)
        assert resolved["type"] == "voice.candidates" and resolved["payload"]["decision"] == "run", resolved
        resolution = resolved["payload"]["resolution"]
        granted = acquire(local); assert granted["type"] == "lease.granted", granted
        lease = granted["payload"]["lease"]
        payload = identity(local) | {"base_revision": sync.flush(), "source": "voice", "op": "voice.run", "lease": lease["lease_id"],
            "args": {"resolution": resolution, "choice": 1}, "target": {"id": oid, "generation": sync.generation(oid)}}
        message = protocol.message("command", payload)
        receipt = cmd.command(message, local)
        if receipt is None:
            receipt = next(m for m in local.messages if m.get("re") == message["id"])
        assert receipt["type"] == "result" and receipt["payload"]["outcome"] == "applied", receipt
        release(lease); voice_after = position()
        assert abs(voice_after[1] - after[1] - .01) < 1e-6 and sync.find_object(oid).scale.x < 0
        editor.apply("history.undo", None, {}); assert abs(position()[1] - after[1]) < 1e-6
        editor.apply("history.redo", None, {}); assert abs(position()[1] - voice_after[1]) < 1e-6
        report["checks"].append("direct-to-atomic-voice handoff uses native Commands/identity/generation/lease and one UndoRedo")
        report["passed"] = True
    except BaseException:
        report["error"] = traceback.format_exc(); raise
    finally:
        live.stop(); sync.unregister(); store.close(); store._thread.join(5)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", required=True); parser.add_argument("--database", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    print(json.dumps(run(args.output, args.url, args.database)))

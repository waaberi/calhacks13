"""Owned disposable Blender Host for full-data protocol verification."""
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

import bpy

assert os.environ.get("SPATIAL_NATIVE_SYNC_TEST") == "1"
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "blender_addon"), str(Path(__file__).parent)]
from native_fixture import build_fixture, edit_fixture
from native_graph import capture_graph
from spatial_modeling import commands, document, edits, host, lan, leases, server, session, sync
from spatial_modeling.native_sync.document import NativeDocument
from spatial_modeling.native_sync.host import NativeHost

folder = Path(sys.argv[sys.argv.index("--") + 1])
config = json.loads((folder / "config.json").read_text())
build_fixture()
bpy.ops.ed.undo_push(message="Original Host fixture")
doc = document.Document()
sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex,
    client_can_edit=True, capabilities=lambda: {"native_sync": True})
editor = edits.Editor(sync, host.undoable, doc)
lses = leases.Leases(sess, editor)
cmds = commands.Commands(sess, editor, leases=lses)
listener = server.Listener("127.0.0.1", 0, ssl=lan.server_tls_context(config["token"]),
                           roles=("blender-client",))
srv = server.Server(port=0, handlers=dict(server.HANDLERS), extra_listeners=[listener])
lses.attach(cmds.attach(sess.attach(srv)))
scheduled = []


def schedule(callback, delay):
    scheduled.append((time.monotonic() + delay, callback))


native = NativeHost(sess, doc, sync, NativeDocument(schedule=schedule))
native.attach(srv)
srv.start()
sync.register()
sync.start(doc, sess)
started = time.monotonic()
last_report = 0.0


def publish(name, data):
    temp = folder / (name + ".tmp")
    temp.write_text(json.dumps(data), encoding="utf-8")
    try:
        temp.replace(folder / name)
    except PermissionError:
        # A reader may briefly hold the old file on Windows. The next fixture
        # tick publishes again; this never changes a production refusal.
        return


def stop():
    native.stop()
    sync.stop()
    sync.unregister()
    srv.stop()
    bpy.ops.wm.quit_blender()


def tick():
    global last_report
    try:
        if not native.busy:
            srv.drain(limit=1)
            native.poll()
            if not native.busy:
                sync.poll()
                if time.monotonic() - last_report > .15:
                    publish("host-status.json", {"graph": capture_graph(),
                        "head": native.head() if native.state else None,
                        "native_ids": {obj.name: {"uuid": obj.get("spatial_native_uuid"),
                            "id": obj.get("spatial_modeling_id")} for obj in bpy.data.objects},
                        "leases": sess.store.leases(), "error": native.error})
                    last_report = time.monotonic()
                action_path = folder / "action.json"
                if action_path.exists():
                    try:
                        action = json.loads(action_path.read_text())
                        action_path.unlink()
                    except (PermissionError, json.JSONDecodeError):
                        return .02
                    if action["action"] == "edit":
                        edit_fixture("host")
                        bpy.ops.ed.undo_push(message="Host native tools")
                        native._observe()
                    elif action["action"] == "finish":
                        publish("host-result.json", {"passed": True, "graph": capture_graph(),
                            "leases": sess.store.leases()})
                        stop()
                        return None
                if not (folder / "ready.json").exists():
                    publish("ready.json", {"port": listener.port, "graph": capture_graph()})
        if time.monotonic() - started > config.get("timeout", 180):
            raise TimeoutError("Full native Client did not finish")
        return .02
    except Exception:  # noqa: BLE001 - preserve exact owned fixture failure before quitting
        (folder / "host-error.txt").write_text(traceback.format_exc())
        stop()
        return None


while True:
    for entry in list(scheduled):
        if time.monotonic() >= entry[0]:
            scheduled.remove(entry)
            with bpy.context.temp_override(window=bpy.context.window):
                entry[1]()
    with bpy.context.temp_override(window=bpy.context.window):
        if tick() is None:
            break
    time.sleep(.02)

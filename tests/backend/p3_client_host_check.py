"""Isolated real native Host for the production P2 Client/operator proof."""
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
    lan,
    leases,
    server,
    session,
    session_store,
    sync,
)

folder = Path(sys.argv[sys.argv.index("--") + 1])
config = json.loads((folder / "config.json").read_text())
scale = config["scale"]
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.context.scene.unit_settings.system = "METRIC"
bpy.context.scene.unit_settings.scale_length = scale
bpy.ops.mesh.primitive_cube_add(size=.02 / scale, location=(.01 / scale, 0, 0))
bpy.context.object.name = "Controlled host 20mm cube"
bpy.ops.ed.undo_push(message="Controlled native baseline")
doc = document.Document()
store = None
if config.get("store"):
    url, database = config["store"]
    store = session_store.MirroredStore(functools.partial(
        session_store.SpacetimeStore, folder / "private-store-token", url=url, database=database))
sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex, client_can_edit=False, store=store)
editor = edits.Editor(sync, host.undoable, doc)
lses = leases.Leases(sess, editor)
cmds = commands.Commands(sess, editor, leases=lses)
listener = server.Listener("127.0.0.1", 0, ssl=lan.server_tls_context(config["token"]),
                           roles=("blender-client",))
srv = server.Server(port=0, handlers=dict(server.HANDLERS), extra_listeners=[listener])
lses.attach(cmds.attach(sess.attach(srv)))
original_acquire = srv.handlers["lease.acquire"]
original_command = srv.handlers["command"]
deferred = []
delay = 0
display_lease = None
seen = []


def acquire(msg, conn):
    if delay:
        # Deliberately late permission, to exercise the actual Cancel operator.
        deferred.append((time.monotonic() + delay, msg, conn))
        return None
    return original_acquire(msg, conn)


def command(msg, conn):
    seen.append(msg)
    return original_command(msg, conn)


srv.handlers["lease.acquire"] = acquire
srv.handlers["command"] = command
srv.start()
sync.register()
sync.start(doc, sess)
cube_id = sync.object_id(bpy.context.object)
started = time.monotonic()


def native():
    obj = sync.find_object(cube_id)
    return {"x_native": obj.location.x, "x_meters": obj.location.x * scale,
            "scale": scale, "command_count": len(seen), "leases": sess.store.leases(),
            "receipts": [pair[1] for pair in cmds.receipts.values()],
            "commands": seen}


def tick():
    global delay, display_lease
    try:
        srv.drain()
        sess.store.poll()
        for entry in list(deferred):
            when, msg, conn = entry
            if time.monotonic() >= when:
                deferred.remove(entry)
                # A disconnected actor must not be re-granted a lease.
                if conn in sess.participants:
                    reply = original_acquire(msg, conn)
                    if reply is not None:
                        conn.send(reply)
        bpy.context.view_layer.update()
        sync.poll()
        if (not (folder / "ready.json").exists() and time.monotonic() - started > 1
                and (store is None or store.deciding)):
            (folder / "ready.json").write_text(json.dumps({"port": listener.port,
                "cube_id": cube_id, "native": native()}), encoding="utf-8")
        action_file = folder / "action.json"
        if action_file.exists():
            try:
                action = json.loads(action_file.read_text())
                action_file.unlink()
            except (PermissionError, json.JSONDecodeError):
                # Windows can briefly lock a just-published fixture message.
                # Keep servicing the real server; the overall deadline remains bounded.
                if time.monotonic() - started > 150:
                    raise
                return .01
            name = action["action"]
            if name == "flag_on":
                sess.client_can_edit = True
                for conn in list(srv.connections):
                    conn.close()
            elif name == "delay_on":
                delay = .6
            elif name == "delay_off":
                delay = 0
            elif name == "ownership_on":
                sess.rename_host("Native Client Owner")
                display_lease = lses.grant(sess.host["actor_id"], "shared", [cube_id])
            elif name == "ownership_off":
                lses.end(display_lease["lease_id"], sess.host["actor_id"])
                display_lease = None
            report = {"action": name, "native": native()}
            (folder / "action-result.json").write_text(json.dumps(report), encoding="utf-8")
            if name == "finish":
                assert len(seen) == 1, native()
                assert abs(native()["x_meters"] - .02) < 1e-7, native()
                assert not sess.store.leases(), native()
                (folder / "host-result.json").write_text(json.dumps(report), encoding="utf-8")
                sync.stop()
                srv.stop()
                if store is not None:
                    store.close()
                    store._thread.join(5)
                bpy.ops.wm.quit_blender()
                return None
        if time.monotonic() - started > 150:
            raise TimeoutError("Production Client test did not finish")
        return .01
    except Exception:  # noqa: BLE001 - preserve timer failures before isolated Blender exits
        (folder / "host-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        srv.stop()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=.05)

"""Isolated GUI Blender host for the P2 two-process test; all ports are ephemeral loopback."""
import json
import sys
import time
import traceback
import uuid
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
from spatial_modeling import commands, document, edits, host, lan, leases, protocol, server, session
from spatial_modeling import sync as scene_sync

folder = Path(sys.argv[sys.argv.index("--") + 1])
config = json.loads((folder / "config.json").read_text())
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.context.scene.unit_settings.system = "METRIC"
bpy.context.scene.unit_settings.scale_length = .001
bpy.ops.mesh.primitive_cube_add(size=20)
cube = bpy.context.object
cube.name = "P2 known 20mm cube"
bpy.ops.ed.undo_push(message="P2 native baseline")
cube.location.x = 10
bpy.ops.ed.undo_push(message="P2 native marker")
seen = []
decode = protocol.decode


def record(line):
    msg = decode(line)
    seen.append(msg["type"])
    return msg


protocol.decode = record
doc = document.Document()
sess = session.Session(scene_sync.describe, scene_sync.snapshot, uuid.uuid4().hex)
editor = edits.Editor(scene_sync, host.undoable, doc)
lses = leases.Leases(sess, editor)
cmds = commands.Commands(sess, editor, leases=lses)
listener = server.Listener("127.0.0.1", 0, ssl=lan.server_tls_context(config["token"]),
                           roles=("blender-client",))
srv = server.Server(port=0, handlers=dict(server.HANDLERS), extra_listeners=[listener])
lses.attach(cmds.attach(sess.attach(srv)))
srv.start()
scene_sync.register()
scene_sync.start(doc, sess)
cube_id = scene_sync.object_id(cube)
baseline = scene_sync.snapshot(scene_sync.describe())
started = time.monotonic()


def tick():
    global baseline
    try:
        srv.drain()
        bpy.context.view_layer.update()
        scene_sync.poll()
        if not (folder / "ready.json").exists() and time.monotonic() - started > 1:
            # GUI Blender settles its startup dirty flag on the event loop.
            # Establish the baseline before the client starts, after that settles.
            baseline = scene_sync.snapshot(scene_sync.describe())
            (folder / "ready.json").write_text(json.dumps({"port": listener.port,
                "cube_id": cube_id, "baseline": baseline}), encoding="utf-8")
        action_file = folder / "action.json"
        if action_file.exists():
            action = json.loads(action_file.read_text())
            action_file.unlink()
            name = action["action"]
            if name == "undo_invariance":
                now = scene_sync.snapshot(scene_sync.describe())
                (folder / "native-before.json").write_text(json.dumps(baseline), encoding="utf-8")
                (folder / "native-after.json").write_text(json.dumps(now), encoding="utf-8")
                assert now == baseline, "Read-only client changed the native scene"
                bpy.ops.ed.undo()
                obj = scene_sync.find_object(cube_id)
                assert abs(obj.location.x) < .0001, "Read-only session added a host Undo step"
                bpy.ops.ed.redo()
                obj = scene_sync.find_object(cube_id)
                assert abs(obj.location.x - 10) < .0001, "Redo lost native marker"
                scene_sync.flush()
            elif name == "move":
                scene_sync.find_object(cube_id).location.x = 20
                scene_sync.flush()
            elif name == "add":
                bpy.ops.mesh.primitive_uv_sphere_add(radius=5, location=(30, 0, 0))
                bpy.context.object.name = "P2 temporary sphere"
                scene_sync.flush()
            elif name == "delete":
                obj = bpy.data.objects.get("P2 temporary sphere")
                bpy.data.objects.remove(obj, do_unlink=True)
                scene_sync.flush()
            elif name == "drop":
                for conn in list(srv.connections):
                    conn.close()
            elif name == "new_epoch":
                doc.open_epoch = uuid.uuid4().hex
                for conn in list(srv.connections):
                    conn.close()
            elif name == "finish":
                assert set(seen) <= {"hello", "ping"}, f"Client sent a write: {set(seen)}"
                (folder / "host-result.json").write_text(json.dumps({
                    "passed": True, "inbound_types": sorted(set(seen)),
                    "native_undo_redo": "passed", "loopback_only": True}), encoding="utf-8")
                scene_sync.stop()
                srv.stop()
                (folder / "action-result.json").write_text(json.dumps({"action": name, "passed": True}), encoding="utf-8")
                bpy.ops.wm.quit_blender()
                return None
            (folder / "action-result.json").write_text(json.dumps({"action": name, "passed": True}), encoding="utf-8")
        if time.monotonic() - started > 160:
            raise TimeoutError("P2 test coordinator did not finish")
        return .02
    except Exception:  # noqa: BLE001 - timer failures must be saved before Blender exits
        (folder / "host-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        srv.stop()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=.05)

"""Private background authority prototype. Never installed in production."""

import argparse
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

import bpy

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/p25"))
from native_spatial_gate import setup


def main(args):
    assert bpy.app.background
    bpy.ops.wm.read_factory_settings(use_empty=True)
    identity = setup(args)
    from spatial_modeling import (
        commands,
        document,
        edits,
        host,
        lan,
        leases,
        server,
        session,
        sketch,
        sync,
    )
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = args.unit_scale
    bpy.ops.mesh.primitive_cube_add(size=.02 / args.unit_scale)
    cube = bpy.context.object
    cube.name = "Private authority cube"
    child = bpy.data.objects.new("Private authority child", None)
    bpy.context.collection.objects.link(child)
    child.parent = cube
    path = args.output / "authority.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex,
                           client_can_edit=True, capabilities=lambda: {"sketch": True})
    editor = edits.Editor(sync, host.undoable, doc)
    manager = leases.Leases(sess, editor)
    commander = commands.Commands(sess, editor, leases=manager)
    listener = server.Listener("127.0.0.1", 0,
        ssl=lan.server_tls_context(os.environ["P3_PROTOTYPE_TOKEN"]), roles=("blender-client",))
    srv = server.Server(port=0, handlers=dict(server.HANDLERS), extra_listeners=[listener])
    manager.attach(commander.attach(sess.attach(srv)))
    sync.register()
    sync.start(doc, sess)
    sync.flush()
    bpy.context.preferences.edit.use_global_undo = True
    bpy.ops.ed.undo_push(message="Private authoritative baseline")
    seen = []
    original = srv.handlers["command"]
    def command(msg, conn):
        seen.append({"id": msg["id"], "op": msg["payload"].get("op")})
        return original(msg, conn)
    srv.handlers["command"] = command
    srv.start()
    ready = {"port": listener.port, "document": doc.describe(),
             "cube_id": sync.object_id(cube), "child_id": sync.object_id(child),
             "identity": identity, "process_id": os.getpid()}
    (args.output / "ready.json").write_text(json.dumps(ready), encoding="utf-8")
    started = time.monotonic()
    try:
        while not (args.output / "stop.signal").exists():
            srv.drain()
            bpy.context.view_layer.update()
            sync.poll()
            if time.monotonic() - started > 150:
                raise TimeoutError("Prototype timed out")
            time.sleep(.01)
        final = {"snapshot": sync.snapshot(doc.describe()), "commands": seen,
                 "receipts": [value[1] for value in commander.receipts.values()],
                 "raw_cube_x_m": sync.find_object(ready["cube_id"]).location.x * args.unit_scale,
                 "child_exists": sync.find_object(ready["child_id"]) is not None,
                 "sketches": sketch.snapshot(), "leases": sess.store.leases()}
        (args.output / "authority-result.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
    finally:
        sync.stop()
        srv.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--unit-scale", type=float, default=1)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    try:
        main(args)
    except Exception:
        (args.output / "authority-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise

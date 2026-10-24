"""Disposable CAD host; actual pinned solver, live TLS snapshots and native reopen."""
import json
import math
import sys
import time
import traceback
import uuid
from pathlib import Path
from types import SimpleNamespace

import bpy

folder = Path(sys.argv[sys.argv.index("--") + 1])
config = json.loads((folder / "config.json").read_text())
root, output = Path(config["host_root"]), Path(config["output"])
sys.path.insert(0, str(root / "tests/native-sketch"))
from check_sketch import setup

bpy.ops.wm.read_factory_settings(use_empty=True)
identity = setup(SimpleNamespace(extension=Path(config["extension"]), output=output / "dependency"))
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
from spatial_modeling.commands import Refused

path = output / "native.blend"
metadata = output / "native-meta.json"
if config["phase"] == "reopen":
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
else:
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = .001
doc = document.Document()
sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex,
                       capabilities=lambda: {"sketch": sketch.dependency_status()["available"]})
sync.register()
sync.start(doc, sess)
sync.flush()


def call(op, sid=None, **args):
    done = sketch.apply(op, sid, args)
    bpy.context.view_layer.update()
    sync.flush()
    return done.created or []


def constrain(sid, kind, entities, value=None):
    args = {"kind": kind, "entities": entities}
    if value is not None:
        args["value"] = value
    return call("sketch.constrain", sid, **args)[0]


if config["phase"] == "create":
    rect = call("sketch.create", plane="XY")[0]
    ids = call("sketch.add_rectangle", rect, corner=[0, 0], opposite=[.1, .06])
    constrain(rect, "fixed", [ids[0]])
    width = constrain(rect, "distance", [ids[4]], .1)
    constrain(rect, "distance", [ids[5]], .06)
    circle = call("sketch.create", plane="XZ")[0]
    center, rim = call("sketch.add_circle", circle, center=[.03, .03], radius=.01)
    constrain(circle, "fixed", [center])
    diameter = constrain(circle, "diameter", [rim], .02)
    angle = call("sketch.create", plane="YZ")[0]
    a, b, line1 = call("sketch.add_line", angle, start=[0, 0], end=[.1, 0])
    c, d, line2 = call("sketch.add_line", angle, start=[0, 0], end=[.07, .07])
    constrain(angle, "fixed", [a])
    constrain(angle, "horizontal", [line1])
    constrain(angle, "distance", [line1], .1)
    constrain(angle, "coincident", [c, a])
    constrain(angle, "distance", [line2], .1)
    angle_dim = constrain(angle, "angle", [line1, line2], math.pi / 4)
    info = {"rect": rect, "circle": circle, "angle": angle, "width": width,
            "diameter": diameter, "angle_dim": angle_dim, "opposite_line": ids[6]}
else:
    info = json.loads(metadata.read_text())["info"]
    expected = json.loads(metadata.read_text())["records"]
    actual = sketch.snapshot()
    (output / "reopen-native-observed.json").write_text(json.dumps(actual, indent=2))
    assert {r["id"]: r for r in actual} == {r["id"]: r for r in expected}, "Fresh host reopen lost editable records"

editor = edits.Editor(sync, host.undoable, doc)
lses = leases.Leases(sess, editor)
cmds = commands.Commands(sess, editor, leases=lses)
listener = server.Listener("127.0.0.1", 0, ssl=lan.server_tls_context(config["token"]),
                           roles=("blender-client",))
srv = server.Server(port=0, handlers=dict(server.HANDLERS), extra_listeners=[listener])
lses.attach(cmds.attach(sess.attach(srv)))
srv.start()
started = time.monotonic()
fault = False
display_lease = None
seen = []
decode = __import__("spatial_modeling.protocol", fromlist=["decode"]).decode
from spatial_modeling import protocol


def record(line):
    msg = decode(line)
    seen.append(msg["type"])
    return msg


protocol.decode = record


def report():
    return {"snapshot": sync.snapshot(sync.describe()), "records": sketch.snapshot(),
            "info": info, "identity": identity, "inbound_types": sorted(set(seen))}


(folder / "ready.json").write_text(json.dumps({"port": listener.port, **report()}))
try:
    while time.monotonic() - started < 160:
        srv.drain()
        if not fault:
            sync.poll()
        action_file = folder / "action.json"
        if action_file.exists():
            action = json.loads(action_file.read_text())["action"]
            action_file.unlink()
            extra = {}
            if action == "dimensions":
                call("sketch.set_dimension", info["rect"], constraint=info["width"], value=.12)
                call("sketch.set_dimension", info["circle"], constraint=info["diameter"], value=.03)
                call("sketch.set_dimension", info["angle"], constraint=info["angle_dim"], value=math.pi / 3)
            elif action == "conflict":
                before, revision = sketch.snapshot(), doc.revision
                try:
                    call("sketch.constrain", info["rect"], kind="distance",
                         entities=[info["opposite_line"]], value=.11)
                    raise AssertionError("Conflicting dimension accepted")
                except Refused as exc:
                    assert exc.code == "solver_conflict"
                assert sketch.snapshot() == before and doc.revision == revision
                extra["conflict_preserved"] = True
            elif action == "save":
                bpy.ops.wm.save_as_mainfile(filepath=str(path))
                metadata.write_text(json.dumps({"records": sketch.snapshot(), "info": info}))
            elif action == "reedit":
                call("sketch.set_dimension", info["rect"], constraint=info["width"], value=.13)
            elif action == "ownership_on":
                sess.rename_host("CAD Host Owner")
                display_lease = lses.grant(sess.host["actor_id"], "shared", [info["rect"]])
            elif action == "ownership_off":
                lses.end(display_lease["lease_id"], sess.host["actor_id"])
            elif action == "fault":
                sketch.find(info["rect"]).scale = (2, 1, 1)
                bpy.context.view_layer.update()
                try:
                    sync.flush()
                    raise AssertionError("Unsupported sketch frame serialized")
                except Refused:
                    fault = True
                extra["fault"] = True
            elif action == "restore":
                sketch.find(info["rect"]).scale = (1, 1, 1)
                bpy.context.view_layer.update()
                sync.flush()
                fault = False
            elif action == "delete":
                bpy.data.objects.remove(sketch.find(info["circle"]), do_unlink=True)
                sync.flush()
            result = {"action": action, **extra}
            if not fault:
                result.update(report())
            with (output / f"{config['phase']}-actions.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(result) + "\n")
            (folder / "action-result.json").write_text(json.dumps(result))
            if action == "finish":
                assert set(seen) <= {"hello", "ping"}, seen
                (folder / "host-result.json").write_text(json.dumps(report(), indent=2))
                break
        time.sleep(.01)
    else:
        raise TimeoutError("CAD Client test coordinator did not finish")
except Exception:
    (folder / "host-error.txt").write_text(traceback.format_exc())
    raise
finally:
    srv.stop()
    sync.stop()

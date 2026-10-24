"""P3A evidence through real Blender, isolated ephemeral TCP/TLS listeners.

Run via test_p3a_native.py with P3A_BLENDER pointing at Blender. This script
never enables the add-on's normal listeners or touches an existing process.
Its GUI event loop is required for Blender's real Undo/Redo stack.
"""

import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "blender_addon"))
sys.path.insert(0, str(HERE))

from hello_client import hello
from ping_client import Client
from spatial_modeling import (
    commands,
    document,
    edits,
    host,
    lan,
    leases,
    protocol,
    server,
    session,
    sync,
)

REPORT = {"checks": [], "messages": [], "physical_headset": "not tested",
          "second_pc": "not tested", "mode": "GUI Blender"}
SRV = None
SESS = None
CMDS = None
PEERS = []


def source_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "blender_addon" / "spatial_modeling").rglob("*.py"))}


def log(name, **data):
    REPORT["checks"].append({"name": name, "outcome": "pass", **data})
    print("P3A_CHECK " + json.dumps(REPORT["checks"][-1]), flush=True)


def native_objects():
    bpy.context.view_layer.update()
    return {o.get(sync.ID_PROPERTY) or o.name: {
        "name": o.name, "type": o.type, "location": list(o.location),
        "rotation": list(o.rotation_euler), "scale": list(o.scale),
        "dimensions": list(o.dimensions), "mesh_vertices": len(o.data.vertices)
        if o.type == "MESH" else None,
        "materials": [m.name for m in o.data.materials] if o.type == "MESH" else [],
        "uv_layers": [uv.name for uv in o.data.uv_layers] if o.type == "MESH" else [],
    } for o in bpy.data.objects}


def off_thread(fn):
    box = []

    def run():
        try:
            box.append((True, fn()))
        except BaseException as exc:  # noqa: BLE001 - propagate failures to the main thread
            box.append((False, exc))

    threading.Thread(target=run, daemon=True).start()
    deadline = time.monotonic() + 35
    while not box:
        assert time.monotonic() < deadline, "isolated socket operation timed out"
        yield
    ok, value = box[0]
    if not ok:
        raise value
    return value


class Peer(Client):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.welcome = None

    def recv(self):
        msg = super().recv()
        if msg is not None:
            REPORT["messages"].append(msg)
        return msg

    def ask(self, msg):
        self.send(msg)
        before = []
        while (reply := self.recv()) is not None:
            if reply.get("re") == msg["id"]:
                return before, reply
            before.append(reply)
        raise AssertionError("isolated host closed before its receipt")

    def barrier(self):
        return self.ask(protocol.message("ping"))[0]


def join(name, role="vr", token=None):
    port = SRV.port if token is None else SRV.listeners[1].port
    peer = yield from off_thread(lambda: Peer(port=port, token=token, timeout=15))
    PEERS.append(peer)
    _, welcome = yield from off_thread(lambda: peer.ask(hello(name, role)))
    assert welcome["type"] == "welcome", welcome
    peer.welcome = welcome["payload"]
    rest = yield from off_thread(lambda: [peer.recv(), peer.recv()])
    assert [m["type"] for m in rest] == ["scene.snapshot", "session.update"], rest
    return peer


def request(peer, op, target=None, args=None, generation=None, **fields):
    w = peer.welcome
    payload = {"session_id": w["session_id"], "host_epoch": w["host_epoch"],
               "document_id": w["document"]["id"],
               "open_epoch": w["document"]["open_epoch"], "actor_id": w["actor_id"],
               "base_revision": sync.flush(), "source": "ui", "op": op,
               "args": {} if args is None else args}
    if target is not None:
        payload["target"] = {"id": target, "generation": sync.generation(target)
                             if generation is None else generation}
    payload.update(fields)
    return protocol.message("command", payload)


def acquire(peer):
    w = peer.welcome
    p = {k: w[k] for k in ("session_id", "host_epoch", "actor_id")}
    p.update(document_id=w["document"]["id"], open_epoch=w["document"]["open_epoch"],
             mode="exclusive", targets=[])
    msg = protocol.message("lease.acquire", p)
    _, reply = yield from off_thread(lambda: peer.ask(msg))
    assert reply["type"] == "lease.granted", reply
    return reply["payload"]["lease"]["lease_id"]


def release(peer, lease_id):
    peer.send(protocol.message("lease.release", {"lease_id": lease_id}))
    yield from off_thread(peer.barrier)


def apply(peer, op, target=None, args=None, watcher=None):
    lease_id = yield from acquire(peer)
    msg = request(peer, op, target, args, lease=lease_id)
    before, reply = yield from off_thread(lambda: peer.ask(msg))
    assert reply["type"] == "result", reply
    receipt = reply["payload"]
    assert receipt["outcome"] == "applied", receipt
    updates = [m["payload"] for m in before if m["type"] == "scene.update"]
    assert len(updates) == 1, (op, before)
    assert updates[0]["document"]["revision"] == receipt["revision"], (updates, receipt)
    yield from release(peer, lease_id)
    if watcher is not None:
        seen = yield from off_thread(watcher.barrier)
        matching = [m for m in seen if m["type"] in ("scene.update", "activity")]
        assert [m["type"] for m in matching] == ["scene.update", "activity"], seen
        assert matching[0]["payload"] == updates[0], matching
        assert matching[1]["payload"] == receipt, matching
    return receipt, msg


def obj(oid):
    return next((o for o in bpy.data.objects if o.get(sync.ID_PROPERTY) == oid), None)


def selection():
    layer = bpy.context.view_layer
    return sorted(o.name for o in layer.objects if o.select_get()), (
        layer.objects.active.name if layer.objects.active else None), bpy.context.mode


def close_all():
    for peer in PEERS:
        peer.close()
    PEERS.clear()
    if SRV is not None:
        SRV.stop()
    sync.unregister()


def remote_process(token, target, enabled, output):
    """A fresh real Blender sends the controlled command, on this PC only."""
    env = {**os.environ, "P3A_REMOTE_PORT": str(SRV.listeners[1].port),
           "P3A_REMOTE_TOKEN": token, "P3A_REMOTE_TARGET": target,
           "P3A_REMOTE_ENABLED": "1" if enabled else "0",
           "BLENDER_USER_RESOURCES": str(output / f"remote-resources-{enabled}")}
    cmd = [bpy.app.binary_path, "--background", "--factory-startup", "--python",
           str(Path(__file__).resolve()), "--", "--remote-command"]
    proc = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    stdout = yield from off_thread(lambda: proc.communicate(timeout=120)[0])
    (output / f"remote-flag-{enabled}.log").write_text(stdout, encoding="utf-8")
    line = next((s for s in stdout.splitlines() if s.startswith("P3A_REMOTE_RESULT ")), None)
    assert proc.returncode == 0 and line, stdout
    result = json.loads(line.removeprefix("P3A_REMOTE_RESULT "))
    REPORT["messages"].extend(result.pop("messages"))
    return result


def remote_command():
    """Executed only inside the throwaway background Blender client process."""
    enabled = os.environ["P3A_REMOTE_ENABLED"] == "1"
    with Peer(port=int(os.environ["P3A_REMOTE_PORT"]),
              token=os.environ["P3A_REMOTE_TOKEN"], timeout=20) as peer:
        _, welcome = peer.ask(hello("P3A real remote Blender", "blender-client"))
        assert welcome["type"] == "welcome", welcome
        w = welcome["payload"]
        snapshot, update = peer.recv(), peer.recv()
        assert snapshot["type"] == "scene.snapshot" and update["type"] == "session.update"
        assert w["can_edit"] is enabled, w
        target = os.environ["P3A_REMOTE_TARGET"]
        native_target = next(o for o in snapshot["payload"]["objects"] if o["id"] == target)
        fields = {"session_id": w["session_id"], "host_epoch": w["host_epoch"],
                  "document_id": w["document"]["id"],
                  "open_epoch": w["document"]["open_epoch"], "actor_id": w["actor_id"]}
        lease_id = None
        if enabled:
            _, granted = peer.ask(protocol.message("lease.acquire", {
                **fields, "mode": "exclusive", "targets": []}))
            assert granted["type"] == "lease.granted", granted
            lease_id = granted["payload"]["lease"]["lease_id"]
        payload = {**fields, "base_revision": snapshot["payload"]["document"]["revision"],
                   "source": "ui", "op": "object.move", "args": {"by": [0.01, 0, 0]},
                   "target": {"id": target, "generation": native_target["generation"]}}
        if lease_id:
            payload["lease"] = lease_id
        before, result = peer.ask(protocol.message("command", payload))
        assert result["type"] == "result", result
        receipt = result["payload"]
        if enabled:
            assert receipt["outcome"] == "applied", receipt
            assert [m["type"] for m in before] == ["scene.update"], before
            peer.send(protocol.message("lease.release", {"lease_id": lease_id}))
            peer.barrier()
        else:
            assert receipt["error"]["code"] == "permission_denied", receipt
        print("P3A_REMOTE_RESULT " + json.dumps({"blender": bpy.app.version_string,
              "pid": os.getpid(), "can_edit": w["can_edit"], "receipt": receipt,
              "messages": REPORT["messages"]}), flush=True)


def checks():
    global SRV, SESS, CMDS
    assert os.environ.get("BLENDER_USER_RESOURCES"), "throwaway Blender resources required"
    assert not bpy.app.background, "real GUI Undo/Redo event loop required"
    REPORT.update(blender=bpy.app.version_string, python=sys.version,
                  binary=bpy.app.binary_path, source_hashes=source_hashes())
    scale = float(os.environ.get("P3A_UNIT_SCALE", "0.001"))
    REPORT["unit_scale"] = scale
    units = bpy.context.scene.unit_settings
    units.system, units.length_unit, units.scale_length = "METRIC", "MILLIMETERS", scale
    original = bpy.data.objects["Cube"]
    original.name = "Unrelated_reference"
    original["preserve_me"] = "unrelated native data"
    original.data.materials.append(bpy.data.materials.new("Unrelated_material"))
    original.data.uv_layers.new(name="Unrelated_UV")
    sync.object_id(original)
    unrelated_id = original[sync.ID_PROPERTY]
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.data.objects["Camera"].select_set(True)
    bpy.context.view_layer.objects.active = bpy.data.objects["Camera"]
    kept = selection()
    output = Path(os.environ["P3A_OUTPUT_DIR"])
    output.mkdir(parents=True, exist_ok=True)
    blend = output / "p3a-native.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.ed.undo_push(message="P3A baseline")
    doc = document.Document()
    SESS = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex)
    sync.register()
    sync.start(doc, SESS)
    editor = edits.Editor(sync, host.undoable, doc)
    lses = leases.Leases(SESS, editor)
    CMDS = commands.Commands(SESS, editor, leases=lses)
    token = lan.new_token()
    tls_listener = server.Listener("127.0.0.1", 0, ssl=lan.server_tls_context(token),
                                   roles=("blender-client",))
    SRV = lses.attach(CMDS.attach(SESS.attach(server.Server(port=0,
                                       extra_listeners=[tls_listener]))))
    server.HEARTBEAT_TIMEOUT = 120
    SRV.start()
    REPORT["ports"] = [SRV.port, SRV.listeners[1].port]
    assert all(p not in (8765, 8767) for p in REPORT["ports"]), REPORT["ports"]
    vr = yield from join("P3A isolated VR")
    watcher = yield from join("P3A observer")
    yield from off_thread(vr.barrier)
    unrelated_before = native_objects()[unrelated_id]
    created = {}
    for i, primitive in enumerate(("cube", "sphere", "cylinder")):
        dimensions = [0.02, 0.02, 0.03]
        location = [i * 0.04, 0.03, 0.005]
        receipt, _ = yield from apply(vr, "object.add", args={"primitive": primitive,
            "location": location, "dimensions": dimensions}, watcher=watcher)
        assert len(receipt["created"]) == 1, receipt
        oid = receipt["created"][0]
        created[primitive] = oid
        o = obj(oid)
        assert o is not None and o.type == "MESH", receipt
        assert max(abs(o.dimensions[j] * scale - dimensions[j]) for j in range(3)) < 1e-7
        assert max(abs(o.location[j] * scale - location[j]) for j in range(3)) < 1e-7
        assert selection() == kept, (selection(), kept)
        log("native primitive " + primitive, id=oid, receipt=receipt,
            native_dimensions=list(o.dimensions), selected_context=kept)
    target = created["cube"]
    x_before = obj(target).location.x * scale
    moved, move_msg = yield from apply(vr, "object.move", target,
                                       {"by": [0.01, 0, 0]}, watcher)
    delta = obj(target).location.x * scale - x_before
    assert abs(delta - 0.01) < 1e-8, delta
    rotated, _ = yield from apply(vr, "object.rotate", target,
        {"by": {"axis": "Z", "angle": math.pi / 2}}, watcher)
    radians = obj(target).rotation_euler.z
    assert abs(radians - math.pi / 2) < 1e-7, radians
    scaled, scale_msg = yield from apply(vr, "object.scale", target,
                                          {"by": [1, 1.25, 1.5]}, watcher)
    assert tuple(obj(target).scale) == (1, 1.25, 1.5)
    log("numeric move rotation scale", move_meters=delta, rotation_radians=radians,
        rotation_degrees=math.degrees(radians), scale=list(obj(target).scale),
        receipts=[moved, rotated, scaled])
    deleted = created["cylinder"]
    deletion, _ = yield from apply(vr, "object.delete", deleted, watcher=watcher)
    assert obj(deleted) is None, deleted
    undo, _ = yield from apply(vr, "history.undo", watcher=watcher)
    assert obj(deleted) is not None and tuple(obj(target).scale) == (1, 1.25, 1.5)
    redo, _ = yield from apply(vr, "history.redo", watcher=watcher)
    assert obj(deleted) is None and tuple(obj(target).scale) == (1, 1.25, 1.5)
    assert selection() == kept, (selection(), kept)
    log("delete one-step Undo Redo", receipts=[deletion, undo, redo], selected_context=kept)
    before_native = native_objects()
    before, same = yield from off_thread(lambda: vr.ask(scale_msg))
    assert same["payload"] == scaled and not before, (before, same)
    changed = json.loads(json.dumps(scale_msg))
    changed["payload"]["args"]["by"] = [2, 2, 2]
    _, conflict = yield from off_thread(lambda: vr.ask(changed))
    assert conflict["payload"]["error"]["code"] == "duplicate_request", conflict
    stale = request(vr, "object.move", target, {"by": [0.01, 0, 0]},
                    generation=move_msg["payload"]["target"]["generation"])
    _, reply = yield from off_thread(lambda: vr.ask(stale))
    assert reply["payload"]["error"]["code"] == "stale_revision", reply
    missing = request(vr, "object.delete", "f" * 32, generation=0)
    _, missing_reply = yield from off_thread(lambda: vr.ask(missing))
    assert missing_reply["payload"]["error"]["code"] == "not_found", missing_reply
    invalid = request(vr, "object.move", target, {"by": ["10mm", 0, 0]})
    _, invalid_reply = yield from off_thread(lambda: vr.ask(invalid))
    assert invalid_reply["type"] == "error"
    assert invalid_reply["payload"]["code"] == "invalid_message", invalid_reply
    query = protocol.message("receipt.query", {"host_epoch": vr.welcome["host_epoch"],
        "request_ids": [scale_msg["id"], "0" * 32]})
    _, recovered = yield from off_thread(lambda: vr.ask(query))
    assert recovered["payload"] == {"receipts": [scaled], "missing": ["0" * 32],
                                    "unknown": []}, recovered
    assert native_objects() == before_native, "refused/duplicate requests changed Blender"
    log("duplicate stale missing invalid receipt recovery", duplicate=conflict,
        stale=reply, missing=missing_reply, invalid=invalid_reply, receipts=recovered)
    off_result = yield from remote_process(token, created["sphere"], False, output)
    assert off_result["receipt"]["error"]["code"] == "permission_denied", off_result
    assert native_objects() == before_native
    yield from off_thread(vr.barrier)
    yield from off_thread(watcher.barrier)
    SESS.client_can_edit = True
    remote_result = yield from remote_process(token, created["sphere"], True, output)
    remote_receipt = remote_result["receipt"]
    assert remote_receipt["actor"]["name"] == "P3A real remote Blender", remote_receipt
    assert abs(obj(created["sphere"]).location.x * scale - 0.05) < 1e-7
    seen = yield from off_thread(watcher.barrier)
    changes = [m for m in seen if m["type"] in ("scene.update", "activity")]
    assert [m["type"] for m in changes] == ["scene.update", "activity"], seen
    assert changes[1]["payload"] == remote_receipt, changes
    yield from off_thread(vr.barrier)
    log("controlled remote TLS command flag", default_off=off_result,
        enabled=remote_result, transport="two real Blender processes, TLS localhost, same PC")
    assert native_objects()[unrelated_id] == unrelated_before, "unrelated object changed"
    yield from off_thread(watcher.barrier)
    saved, _ = yield from apply(vr, "document.save", watcher=watcher)
    saved_objects = native_objects()
    REPORT["saved_objects"] = saved_objects
    REPORT["saved_blend"] = str(blend)
    REPORT["saved_sha256"] = hashlib.sha256(blend.read_bytes()).hexdigest()
    reopen = [bpy.app.binary_path, "--background", "--factory-startup", str(blend),
              "--python", str(Path(__file__).resolve()), "--", "--reopen"]
    proc = subprocess.Popen(reopen, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    stdout = yield from off_thread(lambda: proc.communicate(timeout=120)[0])
    (output / "fresh-reopen.log").write_text(stdout, encoding="utf-8")
    line = next((s for s in stdout.splitlines() if s.startswith("P3A_REOPENED ")), None)
    assert proc.returncode == 0 and line, stdout
    reopened = json.loads(line.removeprefix("P3A_REOPENED "))
    assert reopened["objects"] == saved_objects, (reopened, saved_objects)
    assert abs(reopened["unit_scale"] - scale) < 1e-8
    assert deleted not in reopened["objects"], "deleted object returned after reopen"
    assert abs(reopened["objects"][target]["location"][0] * scale - 0.01) < 1e-7
    assert abs(reopened["objects"][target]["rotation"][2] - math.pi / 2) < 1e-7
    assert reopened["objects"][unrelated_id] == unrelated_before
    log("native Save and fresh Blender reopen", receipt=saved,
        blend_sha256=REPORT["saved_sha256"], objects=len(saved_objects),
        preserved_ids=list(created.values()), actual_move_meters=delta,
        actual_rotation_degrees=math.degrees(radians))


def finish(code, error=None):
    REPORT.update(outcome="pass" if code == 0 else "fail", error=error,
                  final_source_hashes=source_hashes())
    REPORT["source_unchanged_during_run"] = (
        REPORT.get("source_hashes") == REPORT["final_source_hashes"])
    close_all()
    dest = Path(os.environ["P3A_OUTPUT_DIR"]) / "result.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(REPORT, indent=2), encoding="utf-8")
    print(f"P3A_RESULT {REPORT['outcome']} {dest}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def main():
    if "--remote-command" in sys.argv:
        remote_command()
        return
    if "--reopen" in sys.argv:
        print("P3A_REOPENED " + json.dumps({"objects": native_objects(),
              "unit_scale": bpy.context.scene.unit_settings.scale_length}), flush=True)
        return
    steps = checks()

    def tick():
        try:
            if SRV is not None:
                SRV.drain()
            next(steps)
            return 0.01
        except StopIteration:
            finish(0)
        except Exception:  # noqa: BLE001 - preserve any failure in the evidence report
            error = traceback.format_exc()
            print(error, flush=True)
            finish(1, error)

    bpy.app.timers.register(tick, first_interval=1)


if __name__ == "__main__":
    main()

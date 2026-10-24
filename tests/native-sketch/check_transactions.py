"""Isolated Blender: real socket commands, native Undo/Redo and whole-sketch leases.

Use the same --extension/--output arguments as check_sketch.py. No fixed ports.
The timer owns every bpy call. Socket clients run in worker threads.
"""

import argparse
import json
import math
import socket
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from check_sketch import setup


class Peer:
    def __init__(self, port, messages):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=15)
        self.file = self.sock.makefile("rb")
        self.messages = messages
        self.welcome = None

    def send(self, message):
        self.sock.sendall((json.dumps(message) + "\n").encode())

    def until(self, kind, re_=None):
        while True:
            msg = json.loads(self.file.readline())
            self.messages.append(msg)
            if msg["type"] == kind and (re_ is None or msg.get("re") == re_):
                return msg

    def join(self, name):
        self.send({"v": 1, "type": "hello", "id": uuid.uuid4().hex,
                   "payload": {"role": "vr", "name": name,
                               "app": {"name": "Native CAD gate", "version": "0.1.0"}}})
        self.welcome = self.until("welcome")["payload"]
        self.until("scene.snapshot")
        self.until("session.update")
        return self


def off(fn):
    result = []
    def run():
        try:
            result.append((True, fn()))
        except Exception as exc:  # noqa: BLE001 - return failure to Blender's main thread
            result.append((False, exc))
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not result:
        assert time.monotonic() < deadline, "socket operation timed out"
        yield
    okay, value = result[0]
    if not okay:
        raise value
    return value


def check(args, state):
    from spatial_modeling import (
        commands,
        document,
        edits,
        host,
        leases,
        protocol,
        session,
        sketch,
        sync,
    )
    messages, receipts = [], []
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex,
                           capabilities=lambda: {"sketch": sketch.dependency_status()["available"]})
    sync.register()
    sync.start(doc, sess)
    sync.flush()
    editor = edits.Editor(sync, host.undoable, document=doc)
    lease_manager = leases.Leases(sess, editor)
    dispatcher = commands.Commands(sess, editor, leases=lease_manager)
    from spatial_modeling import server
    srv = lease_manager.attach(dispatcher.attach(sess.attach(server.Server(port=0))))
    state["server"] = srv
    srv.start()
    one = yield from off(lambda: Peer(srv.port, messages).join("CAD editor"))
    two = yield from off(lambda: Peer(srv.port, messages).join("CAD peer"))
    assert one.welcome["capabilities"] == {"sketch": True}

    def request(peer, kind, payload):
        w = peer.welcome
        identity = {"session_id": w["session_id"], "host_epoch": w["host_epoch"],
                    "document_id": doc.id, "open_epoch": doc.open_epoch,
                    "actor_id": w["actor_id"]}
        return protocol.message(kind, {**identity, **payload})

    def command(peer, op, sid=None, args_=None, extra=None):
        payload = {"base_revision": sync.flush(), "source": "ui", "op": op,
                   "args": args_ or {}}
        if sid:
            payload["target"] = {"id": sid, "generation": sync.generation(sid)}
        payload.update(extra or {})
        message = request(peer, "command", payload)
        state["last_command"] = message
        def send():
            peer.send(message)
            return peer.until("result", message["id"])
        result = yield from off(send)
        receipts.append(result)
        return result["payload"]

    def record(sid):
        return next(value for value in sketch.snapshot() if value["id"] == sid)

    def width(sid):
        points = [entity["at"][0] for entity in record(sid)["entities"] if entity["kind"] == "point"]
        return max(points) - min(points)

    def applied(receipt):
        assert receipt["outcome"] == "applied", receipt
        return receipt

    bpy.ops.ed.undo_push(message="Native CAD baseline")
    sid = applied((yield from command(one, "sketch.create", args_={"plane": "XY"})))["created"][0]
    ids = applied((yield from command(one, "sketch.add_rectangle", sid,
                                     {"corner": [0, 0], "opposite": [.1, .06]})))["created"]
    point, line1, line2, line3 = ids[0], ids[4], ids[5], ids[6]
    for kind, entities, value in (("fixed", [point], None), ("distance", [line1], .1),
                                  ("distance", [line2], .06)):
        args_ = {"kind": kind, "entities": entities}
        if value is not None:
            args_["value"] = value
        done = applied((yield from command(one, "sketch.constrain", sid, args_)))
        if entities == [line1]:
            dimension = done["created"][0]
    assert record(sid)["solver"] == {"status": "fully_constrained", "dof": 0}
    applied((yield from command(one, "sketch.set_dimension", sid,
                               {"constraint": dimension, "value": .12})))
    assert math.isclose(width(sid), .12, abs_tol=1e-7)
    before = record(sid)
    generation = sync.generation(sid)
    replay_message = state["last_command"]
    def replay():
        one.send(replay_message)
        return one.until("result", replay_message["id"])
    replayed = yield from off(replay)
    assert replayed["payload"] == receipts[-1]["payload"]
    assert record(sid) == before and sync.generation(sid) == generation
    query = protocol.message("receipt.query", {"host_epoch": one.welcome["host_epoch"],
                                               "request_ids": [replay_message["id"]]})
    def receipt_query():
        one.send(query)
        return one.until("receipts", query["id"])
    queried = yield from off(receipt_query)
    assert queried["payload"]["receipts"][0] == replayed["payload"]
    conflict = yield from command(one, "sketch.constrain", sid,
                                  {"kind": "distance", "entities": [line3], "value": .11})
    assert conflict["outcome"] == "rejected" and conflict["error"]["code"] == "solver_conflict", conflict
    assert conflict["solver"] == {"status": "conflicting", "dof": None}
    assert record(sid) == before and sync.generation(sid) == generation
    applied((yield from command(one, "history.undo")))
    assert math.isclose(width(sid), .1, abs_tol=1e-7), width(sid)
    applied((yield from command(one, "history.redo")))
    assert math.isclose(width(sid), .12, abs_tol=1e-7), width(sid)
    assert record(sid) == before

    acquire = request(two, "lease.acquire", {"mode": "shared", "targets": [sid]})
    def get_lease():
        two.send(acquire)
        return two.until("lease.granted", acquire["id"])["payload"]["lease"]
    lease = yield from off(get_lease)
    blocked = yield from command(one, "sketch.set_dimension", sid,
                                 {"constraint": dimension, "value": .14})
    assert blocked["outcome"] == "rejected" and blocked["error"]["code"] == "lease_conflict", blocked
    assert record(sid) == before
    owner = applied((yield from command(two, "sketch.set_dimension", sid,
                                       {"constraint": dimension, "value": .125},
                                       {"lease": lease["lease_id"]})))
    assert owner["solver"]["dof"] == 0
    denied_undo = yield from command(one, "history.undo")
    assert denied_undo["error"]["code"] == "lease_conflict"
    release = protocol.message("lease.release", {"lease_id": lease["lease_id"]})
    yield from off(lambda: two.send(release))
    release_deadline = time.monotonic() + 5
    while any(value["lease_id"] == lease["lease_id"] for value in sess.store.leases()):
        assert time.monotonic() < release_deadline, "lease release was not processed"
        yield
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / "transactions.blend"))
    saved = applied((yield from command(one, "document.save")))
    assert saved["summary"].startswith("Saved")
    clean = doc.describe()
    original_curves = len(bpy.data.hair_curves)
    before_saved_reject = record(sid)
    denied = yield from command(one, "sketch.constrain", sid,
                                {"kind": "distance", "entities": [line3], "value": .11})
    assert denied["error"]["code"] == "solver_conflict", denied
    assert record(sid) == before_saved_reject and len(bpy.data.hair_curves) == original_curves
    assert doc.describe() == clean, (doc.describe(), clean)
    for op, args_ in (("object.move", {"by": [.01, 0, 0]}),
                      ("object.scale", {"by": [2, 2, 2]}), ("object.delete", {})):
        refusal = yield from command(one, op, sid, args_)
        assert refusal["outcome"] == "rejected" and refusal["error"]["code"] == "failed", refusal
        assert record(sid) == before_saved_reject
    assert not dispatcher.frozen
    # Reconnect sees the same stable entity/constraint IDs and current solved geometry.
    third = yield from off(lambda: Peer(srv.port, messages).join("Fresh CAD peer"))
    assert third.welcome["document"]["id"] == doc.id
    snapshots = [m["payload"] for m in messages if m["type"] == "scene.snapshot"]
    assert snapshots[-1]["sketches"][0]["entities"] == record(sid)["entities"]
    assert snapshots[-1]["sketches"][0]["constraints"] == record(sid)["constraints"]
    from spatial_modeling import scene
    from spatial_modeling.commands import Refused

    def disconnected(peer):
        fault = peer.until("error")
        assert "scene unavailable" in fault["payload"]["message"].lower(), fault
        assert peer.file.readline() == b"", "serializer fault kept a live/current socket"
        return fault

    # A real unsupported desktop transform invalidates every welcomed client's
    # currentness, even though the server could otherwise still answer pings.
    native_obj = sketch.find(sid)
    native_obj.scale = (2, 1, 1)
    bpy.context.view_layer.update()
    fault_revision = doc.revision
    try:
        sync.flush()
        raise AssertionError("nonrigid native sketch serialized as current")
    except Refused:
        pass
    assert doc.revision == fault_revision
    for peer in (one, two, third):
        yield from off(lambda peer=peer: disconnected(peer))
    try:
        sync.snapshot(doc.describe())
        raise AssertionError("faulted snapshot cache labeled current")
    except RuntimeError:
        pass
    bad = yield from off(lambda: Peer(srv.port, messages))
    def join_faulted():
        bad.send(protocol.message("hello", {"role": "vr", "name": "Faulted rejoin",
                                            "app": {"name": "Native CAD gate", "version": "0.1.0"}}))
        response = bad.until("error")
        assert not any(m["type"] == "welcome" and m.get("re") == response.get("re") for m in messages)
        return response
    yield from off(join_faulted)
    bad.sock.close()
    native_obj.scale = (1, 1, 1)
    bpy.context.view_layer.update()
    sync.flush()
    recovered = yield from off(lambda: Peer(srv.port, messages).join("Recovered CAD peer"))
    after_fault = record(sid)
    assert after_fault == before_saved_reject
    applied((yield from command(recovered, "sketch.set_dimension", sid,
                               {"constraint": dimension, "value": .13})))
    assert math.isclose(width(sid), .13, abs_tol=1e-7)

    # Inject an evaluated-mesh read failure on a real native cube. Keeping its
    # old mesh under a fresh transform/revision would be a false current scene.
    cube = applied((yield from command(recovered, "object.add", args_={
        "primitive": "cube", "location": [0, 0, 0], "dimensions": [.01, .01, .01]})))["created"][0]
    original_mesh = scene.evaluated_mesh
    def failed_mesh(obj, *values):
        if obj.get("spatial_modeling_id") == cube:
            raise RuntimeError("injected evaluated native mesh failure")
        return original_mesh(obj, *values)
    scene.evaluated_mesh = failed_mesh
    sync._state.full = True
    fault_revision = doc.revision
    try:
        try:
            sync.flush()
            raise AssertionError("old mesh silently reused after serialization failure")
        except RuntimeError as exc:
            assert "injected" in str(exc), exc
        assert doc.revision == fault_revision
        yield from off(lambda: disconnected(recovered))
    finally:
        scene.evaluated_mesh = original_mesh
    sync.flush()
    final_peer = yield from off(lambda: Peer(srv.port, messages).join("Mesh recovered peer"))
    final_snapshot = [m["payload"] for m in messages if m["type"] == "scene.snapshot"][-1]
    assert any(obj["id"] == cube and obj["mesh"] is not None for obj in final_snapshot["objects"])
    assert final_snapshot["sketches"][0]["entities"] == record(sid)["entities"]
    state["report"]["serializer_failure_disconnect_recovery"] = True
    state["report"]["mesh_failure_disconnect_recovery"] = True
    state["report"].update({"passed": True, "native_undo_redo": True,
                            "rejected_conflict_no_undo_step": True, "whole_sketch_lease": True,
                            "fresh_peer_snapshot": True, "command_count": len(receipts),
                            "final_sketch": record(sid), "receipts": receipts})
    (args.output / "transaction-messages.json").write_text(json.dumps(messages, indent=2))
    for peer in (one, two, third, recovered, final_peer):
        peer.sock.close()
    srv.stop()
    sync.stop()


def finish(args, state, code):
    if "server" in state:
        state["server"].stop()
    (args.output / "transaction-result.json").write_text(json.dumps(state["report"], indent=2))
    print("NATIVE_CAD_TRANSACTIONS", "PASS" if code == 0 else "FAIL", flush=True)
    if bpy.app.background:
        sys.exit(code)
    bpy.ops.wm.quit_blender()


def main(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    state = {"report": {"identity": setup(args)}}
    steps = check(args, state)
    def tick():
        try:
            if "server" in state:
                state["server"].drain()
            next(steps)
            return .01
        except StopIteration:
            finish(args, state, 0)
        except Exception:  # noqa: BLE001 - preserve failures and close only this disposable process
            state["report"]["error"] = traceback.format_exc()
            traceback.print_exc()
            finish(args, state, 1)
        return None
    if bpy.app.background:
        while tick() is not None:
            time.sleep(.01)
    else:
        bpy.app.timers.register(tick, first_interval=1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    main(args)

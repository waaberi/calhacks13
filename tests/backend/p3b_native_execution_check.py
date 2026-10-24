"""Real GUI Blender: keep a lease through a native commit after its socket dies.

The only application override selects an isolated loopback port. A diagnostic
pause inside the real Editor.apply lets its owner disconnect or reach the
unchanged six-second transport timeout. No FakeEditor, manual Session.left,
reentrant drain, geometry substitute or command replay is used.
"""

import functools
import hashlib
import json
import math
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import traceback
from collections import ChainMap
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "blender_addon"), str(Path(__file__).resolve().parent)]
from ping_client import Client
from spatial_modeling import commands, edits, gate, host, protocol, server, session, sync

PORT = int(os.environ.get("P3B_EXECUTION_PORT", "33765"))
MODE = os.environ.get("P3B_EXECUTION_MODE", "disconnect")
OUTPUT = Path(os.environ["P3B_EXECUTION_OUTPUT"]).resolve()
EVENTS = []
PEERS = []
SOURCE = {}
RESULT = {"status": "running", "mode": MODE, "physical_headset": "not tested",
          "second_pc": "not tested"}
REGISTERED = False


def hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "blender_addon/spatial_modeling").rglob("*.py"))}


def event(kind, **fields):
    EVENTS.append({"at": time.monotonic(), "event": kind, **fields})


def wait(predicate, description, timeout=15):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for " + description)
        yield


class Peer:
    """One real socket with its I/O confined to one worker thread."""

    def __init__(self, name, heartbeat):
        self.name, self.heartbeat = name, heartbeat
        self.messages, self.sent, self.errors = [], [], []
        self.outbound = queue.SimpleQueue()
        self.stop = threading.Event()
        self.close_requested = threading.Event()
        self.eof = threading.Event()
        self.welcome = self.snapshot = None
        self.closed_at = None
        self.thread = threading.Thread(target=self.run, name=name, daemon=True)
        PEERS.append(self)
        self.thread.start()

    def send(self, message):
        self.outbound.put(message)

    def reply(self, request):
        return next((m for m in self.messages if m.get("re") == request["id"]), None)

    def was_sent(self, request):
        return any(item["id"] == request["id"] for item in self.sent)

    def run(self):
        client = None
        try:
            client = Client(port=PORT, timeout=0.05)
            greeting = protocol.message("hello", {"role": "vr", "name": self.name,
                                                   "app": dict(session.APP)})
            self.outbound.put(greeting)
            next_ping = time.monotonic() + 1
            while not self.stop.is_set():
                if self.close_requested.is_set():
                    client.sock.shutdown(socket.SHUT_RDWR)
                    break
                if self.heartbeat and time.monotonic() >= next_ping:
                    self.outbound.put(protocol.message("ping"))
                    next_ping = time.monotonic() + 1
                while not self.outbound.empty():
                    msg = self.outbound.get()
                    client.send(msg)
                    self.sent.append({"id": msg["id"], "type": msg["type"],
                                      "at": time.monotonic()})
                try:
                    msg = client.recv()
                except TimeoutError:
                    continue
                if msg is None:
                    break
                self.messages.append(msg)
                if msg["type"] == "welcome":
                    self.welcome = msg["payload"]
                elif msg["type"] == "scene.snapshot":
                    self.snapshot = msg["payload"]
        except Exception as exc:  # noqa: BLE001 - retain any client failure in evidence
            if not self.stop.is_set() and not self.close_requested.is_set():
                self.errors.append(repr(exc))
        finally:
            if client is not None:
                client.close()
            self.closed_at = time.monotonic()
            self.eof.set()

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=1)


def fields(peer):
    w = peer.welcome
    return {"session_id": w["session_id"], "host_epoch": w["host_epoch"],
            "actor_id": w["actor_id"], "document_id": w["document"]["id"],
            "open_epoch": w["document"]["open_epoch"]}


def acquire(peer, target):
    return protocol.message("lease.acquire", {**fields(peer), "mode": "shared",
                                               "targets": [target]})


def run():
    global REGISTERED
    assert MODE in ("disconnect", "timeout")
    assert not bpy.app.background, "Actual GUI Blender is required for native Undo"
    assert "--factory-startup" in sys.argv
    assert 1024 <= PORT <= 65535 and PORT not in (8765, 8766, 8767)
    resources = Path(os.environ["BLENDER_USER_RESOURCES"]).resolve()
    assert resources.is_relative_to(OUTPUT) and resources != OUTPUT
    assert not any("onedrive" in part.lower() for part in OUTPUT.parts)
    assert float(server.HEARTBEAT_TIMEOUT) == 6.0, "Do not shorten the actual timeout"
    assert not (OUTPUT / "result.json").exists(), "Preserve earlier evidence"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", PORT))
    SOURCE.update(hashes())
    RESULT.update(source_commit=subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        source_hashes=SOURCE, harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        pid=os.getpid(), port=PORT, blender=bpy.app.version_string,
        heartbeat_timeout_seconds=server.HEARTBEAT_TIMEOUT)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.mesh.primitive_cube_add(size=0.02)
    cube = bpy.context.object
    cube.name = "NativeExecutionCube"
    units = bpy.context.scene.unit_settings
    units.system, units.length_unit, units.scale_length = "METRIC", "MILLIMETERS", 1.0
    bpy.ops.ed.undo_push(message="Native execution baseline")
    original_factory = server.Server
    server.Server = functools.partial(original_factory, host="127.0.0.1", port=PORT)
    gate.register()
    REGISTERED = True
    try:
        host.register()  # actual production lifecycle and drain timer
    finally:
        server.Server = original_factory
    assert host._server is not None and host._server.port == PORT
    assert len(host._server.listeners) == 1 and host.lan_status == "Off"
    assert isinstance(host._commands, commands.Commands)
    assert isinstance(host._commands.editor, edits.Editor)
    target = sync.object_id(cube)
    owner = Peer("Native executing owner", heartbeat=False)
    observer = Peer("Native execution contender", heartbeat=True)
    yield from wait(lambda: owner.snapshot is not None and observer.snapshot is not None,
                    "both real welcomes and snapshots")
    request = acquire(owner, target)
    owner.send(request)
    yield from wait(lambda: owner.reply(request), "owner shared lease")
    granted = owner.reply(request)
    assert granted["type"] == "lease.granted", granted
    lease = granted["payload"]["lease"]
    lease_id, owner_id = lease["lease_id"], owner.welcome["actor_id"]
    sess, srv, editor = host._session, host._server, host._commands.editor
    conn = next(c for c, a in sess.participants.items() if a["actor_id"] == owner_id)
    competing = acquire(observer, target)
    original_apply, original_left = editor.apply, srv.on_disconnect
    apply_count = []

    def held():
        return any(x["lease_id"] == lease_id for x in sess.store.leases())

    def on_disconnect(connection):
        event("disconnect_callback", owner=connection is conn, committing=sess.committing,
              owner_lease_held=held())
        result = original_left(connection)
        event("disconnect_callback_done", owner=connection is conn,
              committing=sess.committing, owner_lease_held=held())
        return result

    def apply(op, target_id, args):
        assert (op, target_id, args) == ("object.move", target, {"by": [0.01, 0, 0]})
        apply_count.append(op)
        assert len(apply_count) == 1 and sess.committing and held()
        entered = time.monotonic()
        event("native_apply_enter", committing=sess.committing, owner_lease_held=held())
        observer.send(competing)
        if MODE == "disconnect":
            owner.close_requested.set()
        # No main-thread drain or manual left() while the real native call is
        # executing. The transport thread must close the socket independently.
        deadline = entered + 10
        while not (owner.eof.is_set() and conn not in srv._writers):
            assert time.monotonic() < deadline, "Owner transport did not close during commit"
            time.sleep(0.01)
        assert sess.committing and held() and conn in sess.participants
        assert observer.was_sent(competing), "Contending request never reached the wire"
        elapsed = time.monotonic() - entered
        if MODE == "timeout":
            assert 5.5 < elapsed < 9.5, elapsed
            assert not owner.close_requested.is_set()
        event("transport_closed_during_commit", elapsed_seconds=elapsed,
              committing=sess.committing, owner_lease_held=held(),
              participant_cleanup_pending=conn in sess.participants,
              competing_request_sent=True)
        done = original_apply(op, target_id, args)  # actual Blender data/readback/Undo
        assert sess.committing and held()
        bpy.context.view_layer.update()
        event("native_apply_finished", committing=sess.committing,
              owner_lease_held=held(), native_x_meters=float(cube.location.x))
        return done

    def acquire_trace(msg, connection):
        if msg["id"] == competing["id"]:
            event("competing_acquire_handled", committing=sess.committing,
                  owner_lease_held=held())
            assert not sess.committing, "A competing acquisition interleaved the native commit"
        return host._leases.acquire(msg, connection)

    editor.apply, srv.on_disconnect = apply, on_disconnect
    srv.handlers = ChainMap({"lease.acquire": acquire_trace}, srv.handlers)
    record = next(o for o in owner.snapshot["objects"] if o["id"] == target)
    move = protocol.message("command", {**fields(owner), "base_revision": record["generation"],
        "source": "ui", "op": "object.move", "target": {"id": target,
        "generation": record["generation"]}, "args": {"by": [0.01, 0, 0]}, "lease": lease_id})
    owner.send(move)
    yield from wait(lambda: apply_count and not held() and conn not in sess.participants,
                    "native completion and normal disconnect lease release", timeout=20)
    yield from wait(lambda: observer.reply(competing), "contending lease result")
    reply = observer.reply(competing)
    if reply["type"] == "error":
        assert reply["payload"]["code"] == "lease_conflict", reply
        retry = acquire(observer, target)
        observer.send(retry)
        yield from wait(lambda: observer.reply(retry), "fresh reservation after commit")
        reply = observer.reply(retry)
    assert reply["type"] == "lease.granted", reply
    observer_lease = reply["payload"]["lease"]["lease_id"]
    recovered = Peer("Fresh native receipt reader", heartbeat=True)
    yield from wait(lambda: recovered.snapshot is not None, "fresh recovery snapshot")
    query = protocol.message("receipt.query", {"host_epoch": owner.welcome["host_epoch"],
                                               "request_ids": [move["id"]]})
    recovered.send(query)
    yield from wait(lambda: recovered.reply(query), "lost applied receipt query")
    receipts = recovered.reply(query)["payload"]
    assert receipts["missing"] == [] and receipts["unknown"] == []
    assert len(receipts["receipts"]) == 1 and receipts["receipts"][0]["outcome"] == "applied"
    assert not any(m.get("re") == move["id"] for m in owner.messages), "Owner got an ack"
    current = next(o for o in recovered.snapshot["objects"] if o["id"] == target)
    assert math.isclose(current["transform"]["location"][0], 0.01, abs_tol=1e-7)
    assert math.isclose(cube.location.x, 0.01, abs_tol=1e-7) and len(apply_count) == 1
    assert sum(s["type"] == "command" for p in PEERS for s in p.sent) == 1
    observer.send(protocol.message("lease.release", {"lease_id": observer_lease}))
    yield from wait(lambda: not sess.store.leases(), "last lease release")
    assert not any(p.errors for p in PEERS), [p.errors for p in PEERS]
    assert not observer.eof.is_set(), "Pinging observer was incorrectly dropped"
    RESULT.update(status="PASS", one_real_native_apply=True, original_owner_ack_lost=True,
        native_x_meters=float(cube.location.x), recovered_object=current,
        recovered_receipt=receipts["receipts"][0], no_command_replay=True,
        owner_lease_held_through_native_application=True, normal_disconnect_cleanup_after_commit=True,
        contender_did_not_interleave=True, default_timeout_unchanged=True,
        all_leases_released=True, strict_locking="not established by this transaction test")


def finish(error=None):
    for peer in PEERS:
        peer.finish()
    if REGISTERED:
        host.unregister()
        gate.unregister()
    final = hashes()
    RESULT.update(events=EVENTS, source_hashes_after=final,
                  source_unchanged_during_run=SOURCE == final,
                  harness_sha256_after=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  peers=[{"name": p.name, "messages": p.messages, "sent": p.sent,
                          "errors": p.errors, "closed_at": p.closed_at} for p in PEERS])
    if not error and (SOURCE != final or RESULT.get("harness_sha256") != RESULT["harness_sha256_after"]):
        error = "Application or diagnostic source changed during the run"
    if error:
        RESULT.update(status="FAIL", error=error)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result_path = OUTPUT / "result.json"
    if result_path.exists():
        result_path = OUTPUT / f"refused-overwrite-{os.getpid()}-{time.time_ns()}.json"
    result_path.write_text(json.dumps(RESULT, indent=2), "utf-8")
    print("P3B_NATIVE_EXECUTION " + json.dumps({k: RESULT.get(k) for k in
          ("status", "mode", "native_x_meters", "source_unchanged_during_run", "error")}), flush=True)
    if error:
        os._exit(1)
    bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    steps = run()

    def tick():
        try:
            next(steps)
            return 0.01
        except StopIteration:
            finish()
        except Exception:  # noqa: BLE001 - retain every diagnostic failure
            finish(traceback.format_exc())
        return None

    bpy.app.timers.register(tick, first_interval=1)

"""The fakes in contracts/fakes against each other over real sockets.

Traffic goes through a recording proxy, and every message either fake sends is
validated against contracts/schemas. The fakes are test data only; these tests
check that they keep to the contract, not that Blender does.
"""

import ast
import asyncio
import contextlib
import copy
import json
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import protocol
import pytest
from jsonschema import Draft202012Validator
from ping_client import Client
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
FAKES = CONTRACTS / "fakes"
sys.path.insert(0, str(FAKES))
import fake_client
import fake_host

# A crash on a server or client thread must fail the test, not just warn.
pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")

SCHEMAS = {
    path.name.removesuffix(".schema.json"): json.loads(path.read_text("utf-8"))
    for path in (CONTRACTS / "schemas").glob("*.schema.json")
}
REGISTRY = Registry().with_resources(
    (schema["$id"], Resource.from_contents(schema)) for schema in SCHEMAS.values()
)
VALIDATORS = {name: Draft202012Validator(s, registry=REGISTRY) for name, s in SCHEMAS.items()}
SHAFT, BASE_PLATE, SKETCH = fake_host.SHAFT_ID, fake_host.BASE_PLATE_ID, fake_host.SKETCH_ID


def example(name):
    return json.loads((CONTRACTS / "examples" / name).read_text("utf-8"))


def schema_errors(msg):
    validator = VALIDATORS.get(msg.get("type"))
    if validator is None:
        return [f"no schema for {msg.get('type')!r}"]
    return [f"{list(e.absolute_path)}: {e.message[:200]}" for e in validator.iter_errors(msg)]


def assert_valid(msg):
    assert schema_errors(msg) == [], msg


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


class Proxy:
    """Forwards TCP to the host and records every line: (connection, "up" or "down", bytes)."""

    def __init__(self, upstream):
        self.upstream = upstream
        self.lines = []
        self._lock = threading.Lock()
        self._sockets = []
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        for number in range(1000):
            try:
                downstream, _ = self.listener.accept()
            except OSError:
                return
            upstream = socket.create_connection(("127.0.0.1", self.upstream))
            self._sockets += [downstream, upstream]
            for src, dst, way in ((downstream, upstream, "up"), (upstream, downstream, "down")):
                threading.Thread(target=self._pump, args=(number, src, dst, way), daemon=True).start()

    def _pump(self, number, src, dst, way):
        buffer = b""
        while True:
            try:
                data = src.recv(65536)
            except OSError:
                data = b""
            if not data:
                break
            *lines, buffer = (buffer + data).split(b"\n")
            with self._lock:  # recorded before the receiver can see it
                self.lines += [(number, way, line) for line in lines if line.strip()]
            try:
                dst.sendall(data)
            except OSError:
                break
        with contextlib.suppress(OSError):
            dst.shutdown(socket.SHUT_WR)

    def messages(self, number=None, way=None, pongs=False):
        with self._lock:
            lines = list(self.lines)
        found = [json.loads(line) for n, w, line in lines if number in (None, n) and way in (None, w)]
        return [m for m in found if pongs or m["type"] not in ("ping", "pong")]

    def assert_all_valid(self):
        with self._lock:
            lines = list(self.lines)
        assert lines
        problems = [(n, way, json.loads(line)["type"], schema_errors(json.loads(line)))
                    for n, way, line in lines]
        assert [p for p in problems if p[3]] == []
        return {(way, kind) for _, way, kind, _ in problems}

    def close(self):
        self.listener.close()
        for s in self._sockets:
            with contextlib.suppress(OSError):
                s.close()


@contextlib.contextmanager
def running_host(*flags):
    """A FakeHost on a free port, on its own event loop thread. host.logs has its log lines."""
    logs = []
    host = fake_host.FakeHost(fake_host.parse_args(["--port", "0", *flags]), log=logs.append)
    host.logs = logs
    ready = threading.Event()
    thread = threading.Thread(
        target=lambda: asyncio.run(host.run(ready=lambda _: ready.set())), daemon=True
    )
    thread.start()
    assert ready.wait(5), "the fake host did not start"
    try:
        yield host
    finally:
        host.request_stop()
        thread.join(5)
        assert not thread.is_alive()


@contextlib.contextmanager
def proxied(*flags):
    with running_host(*flags) as host:
        proxy = Proxy(host.port)
        try:
            yield host, proxy
        finally:
            proxy.close()


@contextlib.contextmanager
def joined(port, name="Talia", connect=True, **options):
    out = []
    client = fake_client.FakeClient(port=port, name=name, out=out.append, **options)
    client.output = out
    client.start()
    try:
        if connect:
            assert client.wait_connected(), out
        yield client
    finally:
        client.close()


def raw(port):
    return Client(port=port)


def hello(name="Talia", role="vr", **extra):
    app = {"name": "test", "version": "0.1.0"}
    return protocol.message("hello", {"role": role, "name": name, "app": app, **extra})


def welcomed(port):
    """A raw connection after the handshake, and its welcome payload."""
    c = raw(port)
    c.send(hello())
    welcome, snapshot, session = c.recv(), c.recv(), c.recv()
    assert [welcome["type"], snapshot["type"], session["type"]] == [
        "welcome", "scene.snapshot", "session.update",
    ]
    return c, welcome["payload"]


def command(welcome, op, target=None, args=None, **extra):
    payload = {
        "session_id": welcome["session_id"],
        "host_epoch": welcome["host_epoch"],
        "document_id": welcome["document"]["id"],
        "open_epoch": welcome["document"]["open_epoch"],
        "actor_id": welcome["actor_id"],
        "base_revision": welcome["document"]["revision"],
        "source": "ui",
        "op": op,
        "args": args or {},
        **extra,
    }
    if target is not None:
        payload["target"] = target
    return protocol.message("command", payload)


def assert_error(msg, code, re=None):
    assert_valid(msg)
    assert msg["type"] == "error", msg
    assert msg["payload"]["code"] == code, msg
    assert msg.get("re") == re


def result(reply, outcome="applied", code=None):
    assert reply is not None and reply["type"] == "result", reply
    assert reply["payload"]["outcome"] == outcome, reply
    if code is not None:
        assert reply["payload"]["error"]["code"] == code, reply
    return reply["payload"]


# The scene


def _bbox(mesh):
    p = mesh["positions"]
    return [(min(p[i::3]), max(p[i::3])) for i in range(3)]


def test_snapshot_tells_the_examples_story():
    ours = fake_host.Scene().snapshot()
    assert_valid(protocol.message("scene.snapshot", ours))
    theirs = example("scene.snapshot.json")["payload"]
    for mine, given in zip(ours["objects"], theirs["objects"], strict=True):
        for field in ("id", "name", "type", "parent", "visible", "color"):
            assert mine[field] == given[field]
        for field in ("location", "rotation", "scale"):
            assert mine["transform"][field] == pytest.approx(given["transform"][field], abs=1e-6)
        if given["mesh"] is None:
            assert mine["mesh"] is None
        else:  # our meshes are finer but have the example's dimensions
            assert _bbox(mine["mesh"]) == pytest.approx(_bbox(given["mesh"]), abs=1e-6)
    sketch = dict(theirs["sketches"][0], generation=0)
    assert ours["sketches"] == [sketch]
    assert ours["document"]["id"] == theirs["document"]["id"] == fake_host.DOCUMENT_ID
    assert ours["document"]["units"] == theirs["document"]["units"]
    assert example("welcome.json")["payload"]["session_id"] == fake_host.SESSION_ID
    host = example("session.update.json")["payload"]["participants"][0]
    assert host["actor_id"] == fake_host.HOST_ACTOR["actor_id"]


MESH_CASES = [
    ("cube", [0.1, 0.06, 0.01]),
    ("cube", [0.001, 2, 0.5]),
    ("cylinder", [0.02, 0.02, 0.04]),
    ("cylinder", [0.03, 0.01, 0.002]),
    ("sphere", [0.02, 0.02, 0.02]),
    ("sphere", [0.05, 0.02, 0.01]),
]


@pytest.mark.parametrize(("primitive", "size"), MESH_CASES)
def test_meshes_are_closed_wound_outward_and_the_right_size(primitive, size):
    mesh = fake_host.MESHES[primitive](size)
    p, n, indices = mesh["positions"], mesh["normals"], mesh["indices"]
    count = len(p) // 3
    assert len(p) == len(n) == 3 * count and len(indices) % 3 == 0
    assert all(isinstance(i, int) and 0 <= i < count for i in indices)
    for v in range(count):
        assert sum(c * c for c in n[3 * v:3 * v + 3]) == pytest.approx(1, abs=1e-5)
    assert _bbox(mesh) == pytest.approx([(-s / 2, s / 2) for s in size], abs=1e-6)

    def at(v):
        return p[3 * v:3 * v + 3]

    edges = {}
    for t in range(0, len(indices), 3):
        a, b, c = indices[t:t + 3]
        u = [at(b)[i] - at(a)[i] for i in range(3)]
        w = [at(c)[i] - at(a)[i] for i in range(3)]
        face = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]
        assert any(abs(f) > 0 for f in face), "triangle without area"
        for v in (a, b, c):  # counter-clockwise seen from where the normals point
            assert sum(face[i] * n[3 * v + i] for i in range(3)) > 0
        for start, end in ((a, b), (b, c), (c, a)):
            key = (tuple(at(start)), tuple(at(end)))
            edges[key] = edges.get(key, 0) + 1
    # Closed and consistently wound: each edge once each way.
    assert all(count == 1 and edges.get((end, start)) == 1 for (start, end), count in edges.items())


# The validators the fake host uses agree with contracts/schemas.

COMMAND_EXAMPLES = [
    p.name for p in sorted((CONTRACTS / "examples").glob("command*.json"))
    if json.loads(p.read_text("utf-8"))["payload"]["op"] in fake_host.SUPPORTED_OPS
]
COMMAND_CHANGES = [
    {},
    {"payload.args": {"to": [0.03, 0, 0.03]}},
    {"payload.args": {"by": [1e6, 0, 0]}},
    {"payload.args": {"by": [0.01, 0]}},
    {"payload.args": {"by": ["10 mm", 0, 0]}},
    {"payload.args": {"by": [True, 0, 0]}},
    {"payload.args": {"by": [0.01, 0, 0], "to": [0, 0, 0]}},
    {"payload.args": {}},
    {"payload.op": "object.explode"},
    {"payload.session_id": None},
    {"payload.session_id": "2F05D1EB3F1E4CE98DD998ABF20CDD33"},
    {"payload.base_revision": None},
    {"payload.base_revision": 41.0},
    {"payload.base_revision": -1},
    {"payload.colour": "red"},
    {"payload.source": "keyboard"},
    {"payload.target": None},
    {"payload.target.generation": -1},
    {"payload.target.extra": 1},
    {"payload.lease": "not-a-lease"},
    {"payload.op": "object.add", "payload.target": None, "payload.args": {
        "primitive": "cube", "location": [0, 0, 0], "dimensions": [0.01, 0.01, 0.01]}},
    {"payload.op": "object.add", "payload.args": {
        "primitive": "cube", "location": [0, 0, 0], "dimensions": [0.01, 0.01, 0.01]}},
    {"payload.op": "object.add", "payload.target": None, "payload.args": {
        "primitive": "torus", "location": [0, 0, 0], "dimensions": [0.01, 0.01, 0.01]}},
    {"payload.op": "object.add", "payload.target": None, "payload.args": {
        "primitive": ["cube"], "location": [0, 0, 0], "dimensions": [0.01, 0.01, 0.01]}},
    {"payload.op": "object.add", "payload.target": None, "payload.args": {
        "primitive": "cube", "location": [0, 0, 0], "dimensions": [0, 0.01, 0.01]}},
    {"payload.op": "object.rotate", "payload.args": {"by": {"axis": "Z", "angle": 90}}},
    {"payload.op": "object.rotate", "payload.args": {"by": {"axis": "W", "angle": 1}}},
    {"payload.op": "object.rotate", "payload.args": {"by": {"axis": "Z"}}},
    {"payload.op": "object.rotate", "payload.args": {"to": [0.707107, 0, 0, 0.707107]}},
    {"payload.op": "object.rotate", "payload.args": {"to": [2, 0, 0, 0]}},
    {"payload.op": "object.scale", "payload.args": {"to": [0, 1, 1]}},
    {"payload.op": "object.scale", "payload.args": {"by": [2, 2, 2]}},
    {"payload.op": "object.delete", "payload.args": {"by": [1, 1, 1]}},
    {"payload.op": "history.undo", "payload.target": None},
    {"payload.op": "history.undo", "payload.target": None, "payload.args": {"steps": 3}},
    {"payload.op": "document.save"},
]


def _changed(msg, changes):
    msg = copy.deepcopy(msg)
    for path, value in changes.items():
        *parents, last = path.split(".")
        node = msg
        for key in parents:
            node = node.setdefault(key, {})
        if value is None:
            node.pop(last, None)
        else:
            node[last] = value
    return msg


@pytest.mark.parametrize("name", COMMAND_EXAMPLES)
@pytest.mark.parametrize("changes", COMMAND_CHANGES)
def test_command_checks_agree_with_the_schema(name, changes):
    msg = _changed(example(name), changes)
    try:
        fake_host.check_command(msg["payload"])
        accepted = True
    except fake_host.Invalid:
        accepted = False
    assert accepted == VALIDATORS["command"].is_valid(msg)


HELLO_CHANGES = [
    {},
    {"payload.role": "host"},
    {"payload.name": None},
    {"payload.name": ""},
    {"payload.app.version": "latest"},
    {"payload.app.extra": 1},
    {"payload.document": {"id": SHAFT}},
    {"payload.document": {"id": SHAFT, "open_epoch": "x"}},
    {"payload.colour": "red"},
]


@pytest.mark.parametrize("name", ["hello.json", "hello.blender-client.json"])
@pytest.mark.parametrize("changes", HELLO_CHANGES)
def test_hello_checks_agree_with_the_schema(name, changes):
    msg = _changed(example(name), changes)
    try:
        fake_host.check_hello(msg["payload"])
        accepted = True
    except fake_host.Invalid:
        accepted = False
    assert accepted == VALIDATORS["hello"].is_valid(msg)


def test_the_fakes_know_every_contract_op_except_select():
    ops = set(SCHEMAS["command"]["$defs"]["op"]["enum"]) - {"object.select"}
    assert set(fake_host.CONTRACT_OPS) == ops
    select = example("command.json")
    select["payload"].update(op="object.select", args={"ids": []})
    del select["payload"]["target"]
    with pytest.raises(fake_host.Invalid):
        fake_host.check_command(select["payload"])


def test_framing_matches_protocol_py():
    assert fake_host.VERSION == fake_client.VERSION == protocol.VERSION
    assert fake_host.MAX_LINE_BYTES == fake_client.MAX_LINE_BYTES == protocol.MAX_LINE_BYTES
    msg = example("result.json")
    msg["payload"]["summary"] = "Rotated Shaft 90° about Z"
    assert fake_host.encode(msg) == fake_client.encode(msg) == protocol.encode(msg)
    assert fake_host.decode(protocol.encode(msg)) == protocol.decode(fake_host.encode(msg)) == msg


@pytest.mark.parametrize("name", ["fake_host.py", "fake_client.py"])
def test_the_fakes_parse_as_python_3_9(name):
    ast.parse((FAKES / name).read_text("utf-8"), feature_version=(3, 9))


# Over the wire


def test_handshake_commands_and_the_order_of_replies():
    with proxied() as (_host, proxy), joined(proxy.port, "Talia") as a, \
            joined(proxy.port, "Lee Jae-yeon", role="blender-client") as b:
        down_a = proxy.messages(0, "down")
        assert [m["type"] for m in down_a[:3]] == ["welcome", "scene.snapshot", "session.update"]
        welcome = down_a[0]["payload"]
        assert welcome["session_id"] == fake_host.SESSION_ID
        assert welcome["document"]["name"] == "fake_bracket.blend"
        assert welcome["can_edit"] is True
        wait_until(lambda: len(a.participants) == 3)
        assert [p["role"] for p in a.participants] == ["host", "vr", "blender-client"]

        moved = result(a.run("move Shaft 10mm 0 0"))
        assert moved["revision"] == 1 and moved["summary"] == "Moved Shaft 10 mm along X"
        assert a.objects[SHAFT]["transform"]["location"] == [0.03, 0, 0.03]
        assert a.objects[SHAFT]["mesh"] is not None  # kept from the snapshot
        # scene.update to every client, result to the sender, activity to the others.
        kinds = [(m["type"], m.get("re")) for m in proxy.messages(0, "down")]
        last = kinds.index(("result", moved["request_id"]))
        assert kinds[last - 1][0] == "scene.update"
        wait_until(lambda: any(m["type"] == "activity" for m in proxy.messages(1, "down")))
        down_b = proxy.messages(1, "down")
        seen = [m["type"] for m in down_b]
        assert seen[seen.index("activity") - 1] == "scene.update"
        assert down_b[seen.index("activity")]["payload"]["request_id"] == moved["request_id"]

        turned = result(b.run("rotate Shaft Z 90deg"))
        assert turned["summary"] == "Rotated Shaft 90° about Z" and turned["revision"] == 2
        wait_until(lambda: a.objects[SHAFT]["generation"] == 2)
        assert a.objects[SHAFT]["transform"]["rotation"] == pytest.approx(
            [0.707107, 0, 0, 0.707107], abs=1e-6)

        # Moving the parent moves the child with it.
        result(a.run("move Base 0 10mm 0"))
        assert a.objects[SHAFT]["transform"]["location"] == [0.03, 0.01, 0.03]
        assert a.objects[SHAFT]["generation"] == 3

        stale = a.command({"op": "object.move", "target": {"id": SHAFT, "generation": 0},
                           "args": {"by": [0, 0, 0.01]}})
        e = result(a.send(stale), "rejected", "stale_revision")["error"]
        assert e["details"] == {"generation": 3}
        gone = a.command({"op": "object.delete", "target": {"id": uuid.uuid4().hex,
                                                            "generation": 0}})
        result(a.send(gone), "rejected", "not_found")
        sketch = a.command({"op": "sketch.add_line", "target": "Sketch",
                            "args": {"start": [0, 0], "end": [0.1, 0]}})
        result(a.send(sketch), "rejected", "failed")
        leased = a.command({"op": "object.delete", "target": "Shaft",
                            "lease": uuid.uuid4().hex})
        result(a.send(leased), "rejected", "not_found")
        other = a.command({"op": "object.delete", "target": "Shaft"})
        other["payload"]["actor_id"] = b.welcome["actor_id"]
        result(a.send(other), "rejected", "permission_denied")
        old = a.command({"op": "object.delete", "target": "Shaft"})
        old["payload"]["host_epoch"] = uuid.uuid4().hex
        result(a.send(old), "rejected", "wrong_session")
        reopened = a.command({"op": "object.delete", "target": "Shaft"})
        reopened["payload"]["open_epoch"] = uuid.uuid4().hex
        e = result(a.send(reopened), "rejected", "wrong_document")["error"]
        assert e["details"]["document"]["open_epoch"] == welcome["document"]["open_epoch"]

        added = result(a.run("add sphere 0 0 50mm 20mm 20mm 20mm"))
        sphere = added["created"][0]
        assert a.objects[sphere]["name"] == "Sphere" and a.objects[sphere]["color"] is None
        result(a.run("delete Sphere"))
        assert sphere not in a.objects
        result(a.run("undo"))
        assert a.objects[sphere]["mesh"]["indices"]  # an undone delete sends the mesh again
        result(a.run("redo"))
        assert sphere not in a.objects
        undo = a.command({"op": "history.undo"})
        undo["payload"]["base_revision"] -= 1
        e = result(a.send(undo), "rejected", "stale_revision")["error"]
        assert e["details"] == {"revision": a.document["revision"]}

        revision = a.document["revision"]
        saved = result(a.run("save"))
        assert saved["revision"] == revision and a.document["dirty"] is False

        # A repeated request gets the stored result and isn't applied again.
        first = result(a.run("scale Shaft 1 1 1.5"))
        again = result(a.run("again"))
        assert again == first and a.document["revision"] == first["revision"]
        changed = copy.deepcopy(a.last_command)
        changed["payload"]["args"] = {"by": [2, 2, 2]}
        result(a.send(changed), "rejected", "duplicate_request")

        missing = uuid.uuid4().hex
        receipts = a.send(protocol.message("receipt.query",
                                           {"request_ids": [moved["request_id"], missing]}))
        assert receipts["payload"]["receipts"] == [moved]
        assert receipts["payload"]["missing"] == [missing]
        assert a.send(protocol.message("ping"))["type"] == "pong"

    kinds = proxy.assert_all_valid()
    assert {k for way, k in kinds if way == "down"} >= {
        "welcome", "scene.snapshot", "session.update", "scene.update", "result", "activity",
        "receipts", "pong",
    }
    assert {k for way, k in kinds if way == "up"} == {"hello", "ping", "command", "receipt.query"}


def test_before_welcome_only_hello_and_ping_are_answered():
    with running_host() as host, raw(host.port) as c:
        ping = protocol.message("ping")
        c.send(ping)
        pong = c.recv()
        assert_valid(pong)
        assert pong["re"] == ping["id"]
        welcome = example("welcome.json")["payload"]
        for msg in (command(welcome, "document.save"), protocol.message("frobnicate"),
                    protocol.message("receipt.query", {"request_ids": [uuid.uuid4().hex]})):
            c.send(msg)
            assert_error(c.recv(), "permission_denied", msg["id"])
        bad = hello(role="host")
        c.send(bad)
        assert_error(c.recv(), "invalid_message", bad["id"])
        good = hello()
        c.send(good)
        reply = c.recv()
        assert_valid(reply)
        assert reply["type"] == "welcome" and reply["re"] == good["id"]
        assert [c.recv()["type"], c.recv()["type"]] == ["scene.snapshot", "session.update"]
        again = hello()
        c.send(again)
        assert_error(c.recv(), "invalid_message", again["id"])
        for kind in ("lease.acquire", "welcome"):
            msg = protocol.message(kind)
            c.send(msg)
            assert_error(c.recv(), "unknown_type", msg["id"])


def test_malformed_lines_get_invalid_message_and_the_connection_stays_open():
    with running_host() as host:
        c, welcome = welcomed(host.port)
        with c:
            ping = protocol.message("ping")
            cases = [
                (b"not json\n", None),
                (b"[1, 2]\n", None),
                (b'{"v":1,"type":"ping","id":"abc","payload":{}}\n', None),
                (json.dumps(dict(ping, extra=1)).encode() + b"\n", ping["id"]),
                (json.dumps(dict(ping, re=None)).encode() + b"\n", ping["id"]),
                (json.dumps(dict(ping, payload=[])).encode() + b"\n", ping["id"]),
                (json.dumps(dict(ping, payload={"x": 1})).encode() + b"\n", ping["id"]),
            ]
            nan = command(welcome, "object.move", {"id": SHAFT, "generation": 0}, {"by": [0, 0, 0]})
            line = json.dumps(nan).replace("[0, 0, 0]", "[NaN, 0, 0]").encode() + b"\n"
            cases.append((line, nan["id"]))
            zero = command(welcome, "object.scale", {"id": SHAFT, "generation": 0}, {"to": [0, 1, 1]})
            cases.append((protocol.encode(zero), zero["id"]))
            for line, re_ in cases:
                c.send(line)
                assert_error(c.recv(), "invalid_message", re_)
            moved = command(welcome, "object.move", {"id": SHAFT, "generation": 0}, {"by": [0.01, 0, 0]})
            c.send(moved)
            assert [c.recv()["type"], c.recv()["type"]] == ["scene.update", "result"]


@pytest.mark.parametrize(
    ("msg", "code"),
    [
        (dict(protocol.message("ping"), v=2), "unsupported_version"),
        (hello(role="blender-client", app={"name": "spatial_modeling", "version": "9.9.9"}),
         "unsupported_version"),
        # The examples' Client role expects an older opening of bracket.blend.
        (example("hello.blender-client.json"), "wrong_document"),
    ],
)
def test_refusals_close_the_connection(msg, code):
    with running_host() as host, raw(host.port) as c:
        c.send(msg)
        reply = c.recv()
        assert_error(reply, code, msg["id"])
        if code == "wrong_document":
            document = reply["payload"]["details"]["document"]
            assert document["id"] == fake_host.DOCUMENT_ID
            assert document["open_epoch"] == host.scene.open_epoch
        assert c.recv() is None


def test_oversized_line_closes_the_connection(monkeypatch):
    monkeypatch.setattr(fake_host, "MAX_LINE_BYTES", 1024)
    with running_host() as host, raw(host.port) as c:
        c.send(b'{"pad":"' + b"x" * 1100 + b'"}\n')
        assert_error(c.recv(), "message_too_large")
        assert c.recv() is None


def test_a_matching_document_in_hello_is_welcomed():
    with running_host() as host, raw(host.port) as c:
        document = {"id": fake_host.DOCUMENT_ID, "open_epoch": host.scene.open_epoch}
        c.send(hello(role="blender-client", document=document))
        assert c.recv()["type"] == "welcome"


# Flags


def test_animate_sends_live_updates():
    with proxied("--animate") as (_host, proxy), joined(proxy.port) as a:
        wait_until(lambda: a.objects[SHAFT]["generation"] >= 3)
        updates = [m for m in proxy.messages(0, "down") if m["type"] == "scene.update"]
        revisions = [m["payload"]["document"]["revision"] for m in updates]
        assert revisions == sorted(set(revisions))
        rotations = [m["payload"]["objects"][0]["transform"]["rotation"] for m in updates]
        assert len({tuple(r) for r in rotations}) == len(rotations)
        assert all(m["payload"]["objects"][0]["id"] == SHAFT for m in updates)
        # A command on the animated object needs its latest generation.
        result(a.run("move Base 0 0 1mm"))
    proxy.assert_all_valid()


def test_drop_after_closes_and_a_reconnect_gets_a_fresh_snapshot(monkeypatch):
    monkeypatch.setattr(fake_client, "RECONNECT_EVERY", 0.1)
    with proxied("--drop-after", "1") as (host, proxy), \
            joined(proxy.port, reconnect=True) as a:
        result(a.run("move Shaft 10mm 0 0"))
        first = a.welcome
        wait_until(lambda: any("disconnected" in line for line in a.output))
        wait_until(lambda: a.connected and a.welcome is not first)
        snapshots = [m for m in proxy.messages(1, "down") if m["type"] == "scene.snapshot"]
        assert snapshots[0]["payload"]["document"]["revision"] == 1
        assert a.objects[SHAFT]["transform"]["location"] == [0.03, 0, 0.03]
        assert any("same document" in line for line in a.output)
        assert any("--drop-after" in line for line in host.logs)
    proxy.assert_all_valid()


def test_stall_after_stops_answering_until_stall_for_ends(monkeypatch):
    monkeypatch.setattr(fake_client, "PING_EVERY", 0.2)
    monkeypatch.setattr(fake_client, "NOT_RESPONDING_AFTER", 0.6)
    with proxied("--stall-after", "0.5", "--stall-for", "1.5") as (_host, proxy), \
            joined(proxy.port) as a:
        wait_until(lambda: a.not_responding, timeout=3)
        with pytest.raises(fake_client.UsageError, match="not responding"):
            a.run("move Shaft 10mm 0 0")
        wait_until(lambda: not a.not_responding, timeout=3)
        assert a.sock is not None  # stalled, never closed
        assert any("responding again" in line for line in a.output)
        pings = {m["id"] for m in proxy.messages(0, "up", pongs=True) if m["type"] == "ping"}
        pongs = {m["re"] for m in proxy.messages(0, "down", pongs=True) if m["type"] == "pong"}
        assert len(pings) >= 5 and len(pings - pongs) <= 1  # the held pongs came after the stall
        result(a.run("move Shaft 10mm 0 0"))
    proxy.assert_all_valid()


def test_stall_without_stall_for_never_answers():
    with running_host("--stall-after", "0.2") as host:
        c, _ = welcomed(host.port)
        with c:
            time.sleep(0.4)
            c.send(protocol.message("ping"))
            c.sock.settimeout(1)
            with pytest.raises(TimeoutError):
                c.recv()


def test_wrong_document_refuses_every_hello():
    with proxied("--wrong-document") as (_host, proxy), \
            joined(proxy.port, connect=False) as a:
        assert not a.wait_connected()
        refusal = a.refused["payload"]
        assert refusal["code"] == "wrong_document"
        assert refusal["details"]["document"]["id"] == fake_host.DOCUMENT_ID
        wait_until(lambda: a.finished)
    proxy.assert_all_valid()


def test_idle_timeout_closes_silent_connections():
    with running_host("--idle-timeout", "0.3") as host, raw(host.port) as c:
        c.send(hello())
        assert [c.recv()["type"] for _ in range(3)] == ["welcome", "scene.snapshot", "session.update"]
        assert c.recv() is None
        assert any("nothing heard" in line for line in host.logs)


# The scripts, as people run them


def test_scripts_end_to_end():
    script = [sys.executable, str(FAKES / "fake_host.py"), "--port", "0"]
    host = subprocess.Popen(script, stdout=subprocess.PIPE, text=True)
    try:
        port = None
        for line in host.stdout:
            found = re.search(r"Listening on 127\.0\.0\.1:(\d+)", line)
            if found:
                port = int(found.group(1))
                break
        assert port
        threading.Thread(target=host.stdout.read, daemon=True).start()  # keep the pipe drained
        proxy = Proxy(port)
        try:
            client = [sys.executable, str(FAKES / "fake_client.py"), "--port", str(proxy.port),
                      "--check", "--exit"]
            done = subprocess.run(client + ["move Shaft 10mm 0 0", "undo"], check=False, capture_output=True,
                                  text=True, timeout=30)
            assert done.returncode == 0, done.stdout + done.stderr
            assert "result: applied at revision 1: Moved Shaft 10 mm along X" in done.stdout
            assert "--check: 0 schema violation(s)" in done.stdout
            refused = subprocess.run(client + ["rotate Shaft Z 90"], check=False, capture_output=True,
                                     text=True, timeout=30)
            assert refused.returncode == 1
            assert "must be a number from -6.28319 to 6.28319" in refused.stdout
            # The client sends what you typed; the host refuses it.
            ups = [m for m in proxy.messages(way="up") if m["type"] == "command"]
            assert ups[-1]["payload"]["args"]["by"]["angle"] == 90
            bad = [m for m in proxy.messages() if schema_errors(m)]
            assert bad == [ups[-1]]  # only the deliberately out-of-bounds command
        finally:
            proxy.close()
    finally:
        host.terminate()
        host.wait(5)


def test_client_cannot_reach_a_missing_host():
    with socket.create_server(("127.0.0.1", 0)) as s:
        port = s.getsockname()[1]
    done = subprocess.run([sys.executable, str(FAKES / "fake_client.py"), "--port", str(port)],
                          check=False, capture_output=True, text=True, timeout=30)
    assert done.returncode == 2
    assert "could not connect" in done.stdout

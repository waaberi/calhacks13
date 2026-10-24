"""Commands and receipts of contracts/README.md over real sockets, without Blender.

A host runs as host.py wires it (session.py, commands.py, server.py), with a
FakeEditor standing in for edits.py: a few objects with generations, a revision
counter that flush() raises and broadcasts like sync.py, and a small Undo stack.
So these tests cover the check order, deduplication, outcomes, receipts and
message order; test_edits.py covers what the real editor does in Blender. Every
message the host sends is checked against its schema in contracts/schemas, and
command_problem() is cross-checked against command.schema.json.
"""

import contextlib
import copy
import itertools
import json
import threading
import time
import uuid

import commands
import lan
import protocol
import pytest
import server
import session
from commands import Applied, Refused
from hello_client import hello
from jsonschema import Draft202012Validator
from ping_client import Client
from test_contracts import CONTRACTS, REGISTRY, SCHEMAS

pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")

TOKEN = lan.new_token()
SESSION_ID = "2f05d1eb3f1e4ce98dd998abf20cdd33"
DOCUMENT = {
    "id": "15e12b8b8c12437098bb8a090659c8cb",
    "open_epoch": "5ac7931d230d4870a872dc9e363ca56d",
    "name": "bracket.blend",
    "revision": 0,
    "dirty": False,
    "units": {"system": "METRIC", "length_unit": "MILLIMETERS", "rotation_unit": "DEGREES",
              "scale_length": 0.001},
}
SHAFT = "fd7bd4ddae444528a4fedbc562fe018b"
PLATE = "f21f7d20394f4c02afce7ab1e6f4a1a8"
SKETCH = "420d772974c747ebb91283b7ff8d22a3"
LEASE = "8a54d6b0b6d94e1b9c8f6c1f3c2d1e0f"


def valid(msg):
    return Draft202012Validator(SCHEMAS[msg["type"]], registry=REGISTRY).is_valid(msg)


def assert_valid(msg):
    assert msg is not None, "the host closed the connection"
    Draft202012Validator(SCHEMAS[msg["type"]], registry=REGISTRY).validate(msg)
    return msg


class FakeEditor:
    """Stands in for edits.Editor: the editor interface commands.py uses, in plain Python."""

    def __init__(self):
        self.session = None  # set by hosting(); flush() broadcasts through it
        self.revision = 0
        self.dirty = False
        self.objects = {}
        self.changed, self.removed, self.dirty_changed = set(), set(), False
        self.applied = []  # (op, target, args) of every apply() call
        self.undo, self.redo = [], []
        self.flush_error = None  # raise this from flush()
        self.halfway = None  # an op that raises halfway through
        self.refusal = None  # (code, message) that apply() refuses with
        for oid, name in ((PLATE, "Base plate"), (SHAFT, "Shaft")):
            self.objects[oid] = {"id": oid, "name": name, "generation": 0, "location": [0, 0, 0]}

    def describe(self):
        return {**DOCUMENT, "revision": self.revision, "dirty": self.dirty}

    def record(self, oid):
        o = self.objects[oid]
        return {"id": oid, "name": o["name"], "type": "MESH", "parent": None,
                "generation": o["generation"], "visible": True, "color": None, "mesh": None,
                "transform": {"location": o["location"], "rotation": [1, 0, 0, 0],
                              "scale": [1, 1, 1]}}

    def snapshot(self, document):
        return {"document": document, "objects": [self.record(o) for o in self.objects],
                "sketches": []}

    # The editor interface

    def flush(self):
        if self.flush_error is not None:
            raise self.flush_error
        if not (self.changed or self.removed or self.dirty_changed):
            return self.revision
        if self.changed or self.removed:
            self.revision += 1
        for oid in self.changed:
            self.objects[oid]["generation"] = self.revision
        changed = [self.record(oid) for oid in sorted(self.changed) if oid in self.objects]
        self.session.broadcast(protocol.message("scene.update", {
            "document": self.describe(), "objects": changed, "sketches": [],
            "removed": sorted(self.removed),
        }))
        self.changed, self.removed, self.dirty_changed = set(), set(), False
        return self.revision

    def generation(self, oid):
        obj = self.objects.get(oid)
        return None if obj is None else obj["generation"]

    def apply(self, op, target, args):
        self.applied.append((op, target, copy.deepcopy(args)))
        if self.refusal is not None:
            raise Refused(*self.refusal)
        if op == self.halfway:
            self.changed.add(target or SHAFT)
            raise RuntimeError("Blender stopped halfway")
        if op == "object.add":
            oid = uuid.uuid4().hex
            self.objects[oid] = {"id": oid, "name": "Cube", "generation": 0,
                                 "location": args["location"]}
            return self._commit(f"Added {args['primitive']}", {oid: None}, [oid])
        if op == "object.delete":
            return self._commit(f"Deleted {self.objects[target]['name']}",
                                {target: self.objects.pop(target)})
        if op in ("object.move", "object.rotate", "object.scale"):
            before = copy.deepcopy(self.objects[target])
            if op == "object.move":
                o = self.objects[target]
                o["location"] = [a + b for a, b in zip(o["location"], args["by"], strict=True)]
            return self._commit(f"{op} {before['name']}", {target: before})
        if op in ("history.undo", "history.redo"):
            source, sink = (self.undo, self.redo) if op == "history.undo" else (self.redo, self.undo)
            if not source:
                raise Refused("failed", "Nothing to do.")
            summary, before = source.pop()
            sink.append((summary, self._swap(before)))
            return Applied(("Undid: " if op == "history.undo" else "Redid: ") + summary)
        if op == "document.save":
            self.dirty, self.dirty_changed = False, True
            return Applied("Saved bracket.blend")
        raise AssertionError(f"commands.py let {op} through")

    def _commit(self, summary, before, created=()):
        self.dirty = True
        self.undo.append((summary, before))
        self.redo.clear()
        self.changed.update(oid for oid in before if oid in self.objects)
        self.removed.update(oid for oid in before if oid not in self.objects)
        return Applied(summary, list(created))

    def _swap(self, before):
        """Put the records in `before` back (None: remove); return what was there."""
        self.dirty = True
        after = {}
        for oid, record in before.items():
            after[oid] = self.objects.pop(oid, None)
            if record is not None:
                self.objects[oid] = record
                self.changed.add(oid)
            else:
                self.removed.add(oid)
        return after


class Peer(Client):
    """A participant that checks every message and tracks the revision it has seen."""

    def __init__(self, port, **kwargs):
        super().__init__(port=port, **kwargs)
        self.welcome = None
        self.revision = 0
        self.inbox = []  # messages received but not yet looked at

    def recv(self):
        msg = super().recv()
        if msg is not None:
            assert_valid(msg)
            payload = msg["payload"]
            if msg["type"] in ("scene.update", "scene.snapshot"):
                self.revision = payload["document"]["revision"]
        return msg

    def join(self, name="Talia", role="vr", **hello_args):
        msg = hello(name=name, role=role, **hello_args)
        self.send(msg)
        welcome = self.recv()
        assert welcome["type"] == "welcome", welcome
        assert [self.recv()["type"], self.recv()["type"]] == ["scene.snapshot", "session.update"]
        self.welcome = welcome["payload"]
        self.revision = self.welcome["document"]["revision"]
        return self.welcome

    def command(self, op, target=None, args=None, id=None, **fields):
        """A command with this participant's request fields; target is an ID or {id, generation}."""
        w = self.welcome
        payload = {
            "session_id": w["session_id"], "host_epoch": w["host_epoch"],
            "document_id": w["document"]["id"], "open_epoch": w["document"]["open_epoch"],
            "actor_id": w["actor_id"], "base_revision": self.revision, "source": "ui",
            "op": op, "args": {} if args is None else args,
        }
        if target is not None:
            payload["target"] = target if isinstance(target, dict) else {"id": target,
                                                                           "generation": 0}
        payload.update(fields)
        msg = protocol.message("command", payload)
        if id is not None:
            msg["id"] = id
        return msg

    def ask(self, msg):
        """Send msg; return (messages before the reply, the reply)."""
        self.send(msg)
        before = []
        while (reply := self.recv()) is not None and reply.get("re") != msg["id"]:
            before.append(reply)
        assert reply is not None, "the host closed the connection"
        return before, reply

    def run(self, *args, **kwargs):
        """Send a command; return its receipt."""
        return self.ask(self.command(*args, **kwargs))[1]["payload"]

    def expect(self, *types):
        """The next messages, which must have these types, in this order."""
        msgs = [self.recv() for _ in types]
        assert [m and m["type"] for m in msgs] == list(types), msgs
        return msgs

    def assert_quiet(self):
        """Nothing else is waiting: the next message is the pong."""
        ping = protocol.message("ping")
        self.send(ping)
        assert self.recv()["re"] == ping["id"]


class Host:
    def __init__(self, srv, sess, cmds, editor):
        self.srv, self.sess, self.cmds, self.editor = srv, sess, cmds, editor

    def vr(self, name="Talia"):
        peer = Peer(self.srv.port)
        peer.join(name)
        return peer

    def lee(self, name="Lee"):
        peer = Peer(self.srv.listeners[1].port, token=TOKEN)
        peer.join(name, role="blender-client")
        return peer


@contextlib.contextmanager
def hosting(editor=None, lan_port=False, **session_args):
    """A session with commands, drained by a thread like Blender's timer."""
    editor = editor or FakeEditor()
    extra = []
    if lan_port:
        extra.append(server.Listener("127.0.0.1", 0, ssl=lan.server_tls_context(TOKEN),
                                     roles=("blender-client",)))
    sess = session.Session(editor.describe, editor.snapshot, SESSION_ID, **session_args)
    editor.session = sess
    cmds = commands.Commands(sess, editor)
    srv = cmds.attach(sess.attach(server.Server(port=0, extra_listeners=extra)))
    srv.start()
    stop = threading.Event()

    def pump():
        while not stop.is_set():
            srv.drain()
            time.sleep(0.002)

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    try:
        yield Host(srv, sess, cmds, editor)
    finally:
        stop.set()
        thread.join()
        srv.stop()


@contextlib.contextmanager
def two_peers(**hosting_args):
    """Talia (who sends) and Jihyeon (who watches), both joined; their queues empty."""
    with hosting(**hosting_args) as host, host.vr("Talia") as talia, host.vr("Jihyeon") as other:
        talia.expect("session.update")  # Jihyeon joined
        yield host, talia, other


def assert_rejected(receipt, code):
    assert receipt["outcome"] == "rejected", receipt
    assert receipt["error"]["code"] == code, receipt
    return receipt["error"]


ADD = {"primitive": "cube", "location": [0.01, 0, 0.005], "dimensions": [0.1, 0.06, 0.01]}
EDITS = [
    ("object.add", None, ADD),
    ("object.move", SHAFT, {"by": [0.01, 0, 0]}),
    ("object.rotate", SHAFT, {"by": {"axis": "Z", "angle": 1.5707963267948966}}),
    ("object.scale", SHAFT, {"to": [1, 1, 2]}),
    ("object.delete", SHAFT, {}),
]


# Applying


@pytest.mark.parametrize("op, target, args", EDITS, ids=[e[0] for e in EDITS])
def test_an_edit_goes_scene_update_then_result_then_activity(op, target, args):
    with two_peers() as (host, talia, other):
        msg = talia.command(op, target, args)
        before, result = talia.ask(msg)
        receipt = result["payload"]
        assert [m["type"] for m in before] == ["scene.update"]  # the change is already there
        assert receipt["outcome"] == "applied" and receipt["revision"] == 1, receipt
        assert receipt["request_id"] == msg["id"] and receipt["op"] == op
        assert receipt["actor"] == {"actor_id": talia.welcome["actor_id"], "name": "Talia",
                                    "role": "vr"}
        assert receipt["source"] == "ui" and receipt["summary"]
        assert abs(receipt["at"] - time.time() * 1000) < 10_000
        assert receipt.get("target") == target
        assert ("created" in receipt) == (op == "object.add")
        update, activity = other.expect("scene.update", "activity")
        assert update["payload"] == before[0]["payload"]
        assert update["payload"]["document"]["revision"] == 1
        assert activity["payload"] == receipt
        assert host.editor.applied == [(op, target, args)]
        talia.assert_quiet()
        other.assert_quiet()


def test_the_new_object_is_in_created_and_can_be_targeted():
    with two_peers() as (host, talia, _):
        receipt = talia.run("object.add", args=ADD)
        (new,) = receipt["created"]
        assert host.editor.generation(new) == receipt["revision"]
        moved = talia.run("object.move", {"id": new, "generation": receipt["revision"]},
                          {"by": [0, 0, 0.01]})
        assert moved["outcome"] == "applied" and moved["revision"] == 2


def test_undo_redo_and_save_report_what_they_did():
    with two_peers() as (host, talia, other):
        talia.run("object.move", SHAFT, {"by": [0.01, 0, 0]})
        other.expect("scene.update", "activity")
        undo = talia.run("history.undo")
        assert undo["outcome"] == "applied" and undo["summary"] == "Undid: object.move Shaft"
        assert undo["revision"] == 2 and "target" not in undo
        assert other.expect("scene.update", "activity")[1]["payload"] == undo
        assert host.editor.objects[SHAFT]["location"] == [0, 0, 0]
        redo = talia.run("history.redo")
        assert redo["summary"] == "Redid: object.move Shaft" and redo["revision"] == 3
        other.expect("scene.update", "activity")
        assert host.editor.dirty
        before, result = talia.ask(talia.command("document.save"))
        save = result["payload"]
        assert save["outcome"] == "applied" and save["summary"] == "Saved bracket.blend"
        assert save["revision"] == 3, "Save doesn't change the revision"
        (update,) = before  # only the dirty flag changed
        assert update["payload"]["document"]["dirty"] is False
        assert update["payload"]["objects"] == update["payload"]["removed"] == []
        assert other.expect("scene.update", "activity")[1]["payload"] == save


def test_voice_commands_keep_their_source():
    with two_peers() as (_, talia, other):
        receipt = talia.run("object.move", SHAFT, {"by": [0, 0.005, 0]}, source="voice")
        assert receipt["source"] == "voice"
        assert other.expect("scene.update", "activity")[1]["payload"]["source"] == "voice"


# Deduplication


def test_a_repeated_request_gets_the_stored_result_and_is_not_applied_again():
    with two_peers() as (host, talia, other):
        msg = talia.command("object.move", SHAFT, {"by": [0.01, 0, 0]})
        _, first = talia.ask(msg)
        other.expect("scene.update", "activity")
        again = copy.deepcopy(msg)
        before, second = talia.ask(again)
        assert before == [] and second["payload"] == first["payload"] and second["re"] == msg["id"]
        assert len(host.editor.applied) == 1
        assert host.editor.objects[SHAFT]["location"] == [0.01, 0, 0]
        other.assert_quiet()  # no second update or activity


def test_a_repeat_from_another_connection_also_gets_the_stored_result():
    with two_peers() as (host, talia, other):
        msg = talia.command("object.move", SHAFT, {"by": [0.01, 0, 0]})
        _, first = talia.ask(msg)
        other.expect("scene.update", "activity")
        _, second = other.ask(copy.deepcopy(msg))
        assert second["payload"] == first["payload"] and len(host.editor.applied) == 1


def test_a_repeated_rejection_is_stored_too():
    with two_peers() as (_host, talia, _):
        msg = talia.command("object.move", {"id": SHAFT, "generation": 7}, {"by": [0.01, 0, 0]})
        _, first = talia.ask(msg)
        assert_rejected(first["payload"], "stale_revision")
        _, second = talia.ask(copy.deepcopy(msg))
        assert second["payload"] == first["payload"]


@pytest.mark.parametrize("change", [
    {"args": {"by": [0.02, 0, 0]}},
    {"base_revision": 5},
    {"source": "voice"},
    {"op": "object.scale", "args": {"by": [2, 2, 2]}},
])
def test_the_same_id_with_a_changed_payload_is_a_duplicate_request(change):
    with two_peers() as (host, talia, other):
        msg = talia.command("object.move", SHAFT, {"by": [0.01, 0, 0]})
        _, first = talia.ask(msg)
        other.expect("scene.update", "activity")
        changed = copy.deepcopy(msg)
        changed["payload"].update(change)
        before, result = talia.ask(changed)
        assert before == []
        assert_rejected(result["payload"], "duplicate_request")
        assert result["payload"]["request_id"] == msg["id"]
        assert len(host.editor.applied) == 1
        other.assert_quiet()
        query = protocol.message("receipt.query", {"request_ids": [msg["id"]]})
        _, receipts = talia.ask(query)
        assert receipts["payload"]["receipts"] == [first["payload"]], "the original stays stored"


# Admission, session and document


def test_the_client_role_is_read_only_by_default():
    with hosting(lan_port=True) as host, host.vr() as talia, host.lee() as lee:
        assert lee.welcome["can_edit"] is False
        talia.expect("session.update")
        receipt = lee.run("object.move", SHAFT, {"by": [0.01, 0, 0]})
        assert_rejected(receipt, "permission_denied")
        assert receipt["actor"]["role"] == "blender-client"
        assert host.editor.applied == []
        talia.assert_quiet()  # no activity for a rejection


def test_with_the_flag_on_the_client_role_can_edit_and_vr_sees_it():
    with hosting(lan_port=True, client_can_edit=True) as host, host.vr() as talia, \
            host.lee() as lee:
        assert lee.welcome["can_edit"] is True and talia.welcome["can_edit"] is True
        talia.expect("session.update")
        receipt = lee.run("object.move", SHAFT, {"by": [0.01, 0, 0]})
        assert receipt["outcome"] == "applied", receipt
        activity = talia.expect("scene.update", "activity")[1]["payload"]
        assert activity["actor"]["name"] == "Lee" and activity == receipt
        receipts = lee.ask(protocol.message("receipt.query",
                                            {"request_ids": [receipt["request_id"]]}))[1]
        assert receipts["payload"]["receipts"] == [receipt]


def test_the_flag_doesnt_change_the_vr_app():
    with hosting(client_can_edit=False) as host, host.vr() as talia:
        assert talia.welcome["can_edit"] is True


def test_actor_id_must_be_this_connections():
    with two_peers() as (host, talia, other):
        receipt = talia.run("object.move", SHAFT, {"by": [0.01, 0, 0]},
                            actor_id=other.welcome["actor_id"])
        assert_rejected(receipt, "permission_denied")
        assert receipt["actor"]["actor_id"] == talia.welcome["actor_id"]  # who really sent it
        assert host.editor.applied == []


@pytest.mark.parametrize("field, code", [
    ("session_id", "wrong_session"),
    ("host_epoch", "wrong_session"),
    ("document_id", "wrong_document"),
    ("open_epoch", "wrong_document"),
])
def test_requests_from_another_session_or_document_are_refused(field, code):
    with two_peers() as (host, talia, _):
        error = assert_rejected(talia.run("object.add", args=ADD, **{field: "e" * 32}), code)
        if code == "wrong_document":
            assert error["details"] == {
                "document": {k: DOCUMENT[k] for k in ("id", "open_epoch", "name")}}
        assert host.editor.applied == []


# Target, revision, leases


def test_a_missing_target_is_not_found():
    with two_peers() as (host, talia, _):
        assert_rejected(talia.run("object.move", "0" * 32, {"by": [0.01, 0, 0]}), "not_found")
        talia.run("object.delete", SHAFT)
        receipt = talia.run("object.move", {"id": SHAFT, "generation": 1}, {"by": [0.01, 0, 0]})
        assert_rejected(receipt, "not_found")
        assert len(host.editor.applied) == 1


@pytest.mark.parametrize("generation", [0, 2], ids=["older", "newer"])
def test_a_target_seen_at_another_generation_is_stale(generation):
    with two_peers() as (host, talia, _):
        talia.run("object.move", SHAFT, {"by": [0.01, 0, 0]})  # Shaft is now at generation 1
        receipt = talia.run("object.move", {"id": SHAFT, "generation": generation},
                            {"by": [0.01, 0, 0]})
        error = assert_rejected(receipt, "stale_revision")
        assert error["details"] == {"generation": 1}
        assert receipt["revision"] == 1
        current = talia.run("object.move", {"id": SHAFT, "generation": 1}, {"by": [0.01, 0, 0]})
        assert current["outcome"] == "applied"
        assert len(host.editor.applied) == 2


@pytest.mark.parametrize("op", ["history.undo", "history.redo"])
def test_undo_and_redo_need_the_current_revision(op):
    with two_peers() as (_host, talia, _other):
        talia.run("object.move", SHAFT, {"by": [0.01, 0, 0]})
        if op == "history.redo":
            talia.run("history.undo")
        current = talia.revision
        for base in (current - 1, current + 1):
            error = assert_rejected(talia.run(op, base_revision=base), "stale_revision")
            assert error["details"] == {"revision": current}
        assert talia.run(op)["outcome"] == "applied"


def test_other_commands_dont_need_the_current_revision():
    with two_peers() as (_, talia, _other):
        talia.run("object.move", PLATE, {"by": [0.01, 0, 0]})
        receipt = talia.run("object.move", SHAFT, {"by": [0.01, 0, 0]}, base_revision=0)
        assert receipt["outcome"] == "applied"


def test_nothing_to_undo_is_failed():
    with two_peers() as (_, talia, other):
        assert_rejected(talia.run("history.undo"), "failed")
        assert_rejected(talia.run("history.redo"), "failed")
        other.assert_quiet()


def test_a_lease_is_not_found_before_p3b():
    with two_peers() as (host, talia, _):
        assert_rejected(talia.run("object.move", SHAFT, {"by": [0.01, 0, 0]}, lease=LEASE),
                        "not_found")
        assert host.editor.applied == []


@pytest.mark.parametrize("op, target, args", [
    ("sketch.create", None, {"plane": "XY"}),
    ("sketch.add_circle", SKETCH, {"center": [0, 0], "radius": 0.01}),
])
def test_sketch_ops_are_failed_until_p3c(op, target, args):
    with two_peers() as (host, talia, _):
        assert_rejected(talia.run(op, target, args), "failed")
        assert host.editor.applied == []


def test_a_refusal_from_blender_is_rejected_with_its_code():
    with two_peers() as (host, talia, other):
        host.editor.refusal = ("failed", "Host Blender is in Edit Mode.")
        error = assert_rejected(talia.run("object.add", args=ADD), "failed")
        assert error["message"] == "Host Blender is in Edit Mode."
        other.assert_quiet()


@pytest.mark.parametrize("changes, code", [
    ({"actor_id": "e" * 32, "session_id": "e" * 32}, "permission_denied"),
    ({"session_id": "e" * 32, "document_id": "e" * 32}, "wrong_session"),
    ({"document_id": "e" * 32, "target": {"id": "0" * 32, "generation": 0}}, "wrong_document"),
    ({"op": "sketch.add_circle", "target": {"id": "0" * 32, "generation": 0}}, "failed"),
    ({"target": {"id": SHAFT, "generation": 9}, "lease": LEASE}, "stale_revision"),
])
def test_checks_run_in_the_contracts_order(changes, code):
    with two_peers() as (_, talia, _other):
        args = {"center": [0, 0], "radius": 0.01} if changes.get("op") else {"by": [0.01, 0, 0]}
        msg = talia.command("object.move", SHAFT, args)
        msg["payload"].update(changes)
        assert_rejected(talia.ask(msg)[1]["payload"], code)


def test_deduplication_comes_before_admission():
    with hosting(lan_port=True) as host, host.lee() as lee:
        msg = lee.command("object.move", SHAFT, {"by": [0.01, 0, 0]})
        assert_rejected(lee.ask(msg)[1]["payload"], "permission_denied")
        msg["payload"]["source"] = "voice"
        assert_rejected(lee.ask(msg)[1]["payload"], "duplicate_request")


# Unknown outcomes


def test_a_failure_halfway_is_unknown_and_everyone_gets_a_fresh_snapshot():
    with two_peers() as (host, talia, other):
        host.editor.halfway = "object.move"
        msg = talia.command("object.move", SHAFT, {"by": [0.01, 0, 0]})
        before, result = talia.ask(msg)
        receipt = result["payload"]
        assert before == [] and receipt["outcome"] == "unknown", receipt
        assert receipt["error"]["code"] == "internal_error"
        # Then the host re-reads the scene: what changed, then the full snapshot, no activity.
        for peer in (talia, other):
            _update, snapshot = peer.expect("scene.update", "scene.snapshot")
            assert snapshot["payload"]["document"]["revision"] == 1
            assert {o["id"] for o in snapshot["payload"]["objects"]} == {SHAFT, PLATE}
        assert not host.cmds.frozen
        host.editor.halfway = None
        follow = talia.run("object.move", {"id": SHAFT, "generation": 1}, {"by": [0.01, 0, 0]})
        assert follow["outcome"] == "applied"
        assert talia.ask(msg)[1]["payload"] == receipt, "never re-run an unknown command"


def break_flush_after_apply(editor, halfway=False):
    """From the next apply() on, flush() raises until the test clears editor.flush_error."""
    real_apply = editor.apply

    def apply(*args):
        editor.flush_error = RuntimeError("the scene can't be read")
        editor.apply = real_apply
        if halfway:
            editor.changed.add(SHAFT)
            raise RuntimeError("Blender stopped halfway")
        return real_apply(*args)

    editor.apply = apply


def test_writes_stay_stopped_until_the_scene_can_be_read_again():
    with two_peers() as (host, talia, other):
        break_flush_after_apply(host.editor, halfway=True)
        receipt = talia.run("object.move", SHAFT, {"by": [0.01, 0, 0]})
        assert receipt["outcome"] == "unknown" and host.cmds.frozen
        other.assert_quiet()  # the host couldn't re-read the scene: no snapshot yet
        # flush() still fails before the checks: rejected, nothing changed, still frozen
        assert_rejected(talia.run("object.add", args=ADD), "internal_error")
        assert host.cmds.frozen and host.editor.applied == []
        host.editor.flush_error = None
        receipt = talia.run("object.add", args=ADD)  # reconciles first, then applies
        assert receipt["outcome"] == "applied", receipt
        # Shaft's pending change, the fresh snapshot, then the new command
        other.expect("scene.update", "scene.snapshot", "scene.update", "activity")
        assert not host.cmds.frozen


def test_frozen_writes_are_permission_denied_when_reconciling_fails():
    def broken(document):
        raise RuntimeError("no snapshot")

    with two_peers() as (host, talia, _):
        host.cmds.frozen = True
        original, host.sess.snapshot = host.sess.snapshot, broken
        assert_rejected(talia.run("object.add", args=ADD), "permission_denied")
        assert host.editor.applied == [] and host.cmds.frozen
        host.sess.snapshot = original
        assert talia.run("object.add", args=ADD)["outcome"] == "applied"


def test_a_failure_while_publishing_is_unknown():
    with two_peers() as (host, talia, other):
        break_flush_after_apply(host.editor)
        receipt = talia.run("object.move", SHAFT, {"by": [0.01, 0, 0]})
        assert receipt["outcome"] == "unknown" and host.cmds.frozen
        assert receipt["error"]["code"] == "internal_error"
        other.assert_quiet()  # no activity for an unknown outcome


# Schema


def assert_invalid(peer, msg):
    before, reply = peer.ask(msg)
    assert before == [] and reply["type"] == "error", reply
    assert reply["payload"]["code"] == "invalid_message", reply
    return reply


@pytest.mark.parametrize("change", [
    {"op": "object.select"},
    {"args": {"by": [0.01, 0, 0], "to": [0, 0, 0]}},
    {"args": {"by": [1001, 0, 0]}},
    {"args": {"by": [0.01, 0]}},
    {"args": {"by": [True, 0, 0]}},
    {"args": {"by": ["1", 0, 0]}},
    {"target": {"id": SHAFT}},
    {"target": {"id": SHAFT, "generation": -1}},
    {"target": {"id": SHAFT, "generation": 1.5}},
    {"base_revision": "3"},
    {"source": "keyboard"},
    {"actor_id": "Talia"},
    {"colour": "red"},
])
def test_a_command_that_doesnt_match_the_schema_is_invalid(change):
    with two_peers() as (host, talia, _):
        msg = talia.command("object.move", SHAFT, {"by": [0.01, 0, 0]})
        msg["payload"].update(change)
        assert not valid(msg), "the test's message should break the schema"
        reply = assert_invalid(talia, msg)
        assert reply["re"] == msg["id"]
        assert host.editor.applied == []
        assert talia.run("object.move", SHAFT, {"by": [0.01, 0, 0]})["outcome"] == "applied"


def test_rotate_by_an_angle_in_degrees_is_invalid():
    with two_peers() as (_, talia, _other):
        assert_invalid(talia, talia.command("object.rotate", SHAFT,
                                            {"by": {"axis": "Z", "angle": 90}}))


def test_an_invalid_command_is_not_stored():
    with two_peers() as (_, talia, _other):
        msg = talia.command("object.move", SHAFT, {"by": [1001, 0, 0]})
        assert_invalid(talia, msg)
        msg["payload"]["args"] = {"by": [0.01, 0, 0]}
        assert talia.ask(msg)[1]["payload"]["outcome"] == "applied"


# Receipts


def test_receipt_query_finds_receipts_and_lists_missing_ids():
    with two_peers() as (_, talia, other):
        applied = talia.run("object.move", SHAFT, {"by": [0.01, 0, 0]})
        rejected = talia.run("object.move", "0" * 32, {"by": [0.01, 0, 0]})
        missing = uuid.uuid4().hex
        ids = [rejected["request_id"], missing, applied["request_id"]]
        query = protocol.message("receipt.query", {"request_ids": ids})
        _, reply = other.ask(query)  # any participant may ask
        assert reply["type"] == "receipts" and reply["re"] == query["id"]
        assert reply["payload"] == {"receipts": [rejected, applied], "missing": [missing]}


@pytest.mark.parametrize("payload", [
    {"request_ids": []},
    {"request_ids": ["0" * 32] * 2},
    {"request_ids": [uuid.uuid4().hex for _ in range(101)]},
    {"request_ids": ["nope"]},
    {"request_ids": ["0" * 32], "since": 3},
    {},
])
def test_a_bad_receipt_query_is_invalid(payload):
    with two_peers() as (_, talia, _other):
        msg = protocol.message("receipt.query", payload)
        assert not valid(msg)
        assert_invalid(talia, msg)


def test_the_receipt_store_keeps_the_newest(monkeypatch):
    monkeypatch.setattr(commands, "MAX_RECEIPTS", 3)
    with two_peers() as (_, talia, _other):
        receipts = [talia.run("object.move", "0" * 32, {"by": [0.01, 0, 0]}) for _ in range(4)]
        ids = [r["request_id"] for r in receipts]
        _, reply = talia.ask(protocol.message("receipt.query", {"request_ids": ids}))
        assert reply["payload"] == {"receipts": receipts[1:], "missing": ids[:1]}


# The host's participant


def test_the_host_participant_has_the_hosts_name():
    with hosting(name="  Talia at the desk  ") as host, host.vr("VR") as vr:
        assert host.sess.host["name"] == "Talia at the desk"
        host.sess.rename_host("Talia")
        update = vr.expect("session.update")[0]
        assert update["payload"]["participants"][0] == {**host.sess.host, "name": "Talia"}
        host.sess.rename_host("Talia")  # unchanged: no update
        host.sess.rename_host("   ")
        update = vr.expect("session.update")[0]
        assert update["payload"]["participants"][0]["name"] == session.HOST_NAME
        vr.assert_quiet()


def test_a_long_host_name_is_cut_to_the_schemas_limit():
    assert len(session.host_name("x" * 300)) == 256
    assert session.host_name(None) == session.HOST_NAME


# command_problem() against command.schema.json


def examples(kind):
    return [json.loads(p.read_text("utf-8")) for p in sorted(CONTRACTS.glob(f"examples/{kind}*"))
            if json.loads(p.read_text("utf-8"))["type"] == kind]


REPLACEMENTS = [None, True, 0, -1, 1, 1.0, 1.5, 3.2, 6.3, -6.3, 90, 1000, 1000.5, -1000.5, 0.0005,
                1e-7, 0.001, 2 ** 53, "x", "XY", "a" * 32, [], {}, [0, 0], [0, 0, 0],
                [0, 0, 0, 1], [1, 0, 0, 0, 0]]


def mutations(value):
    """Every payload one edit away from value: each node replaced, keys added and removed."""
    yield from REPLACEMENTS
    if isinstance(value, dict):
        yield {**value, "extra": 1}
        for key in value:
            yield {k: v for k, v in value.items() if k != key}
            for changed in mutations(value[key]):
                yield {**value, key: changed}
    elif isinstance(value, list):
        if value:
            yield value[:-1]
            yield value + value[-1:]
        for i, item in enumerate(value):
            for changed in mutations(item):
                yield value[:i] + [changed] + value[i + 1:]


def test_command_problem_agrees_with_the_schema():
    cases = 0
    disagreements = []
    for example in examples("command"):
        other_ops = ["object.add", "object.delete", "history.undo", "sketch.create",
                     "sketch.constrain"]
        payloads = itertools.chain(
            mutations(example["payload"]),
            ({**example["payload"], "op": op} for op in other_ops),
        )
        for payload in payloads:
            msg = {**example, "payload": payload}
            if not isinstance(payload, dict):
                continue  # protocol.decode refuses a payload that isn't an object
            cases += 1
            expected, problem = valid(msg), commands.command_problem(msg)
            if expected != (problem is None):
                disagreements.append((payload, problem))
    assert not disagreements, disagreements[:5]
    assert cases > 5000


def test_receipt_query_problem_agrees_with_the_schema():
    (example,) = examples("receipt.query")
    for payload in mutations(example["payload"]):
        if isinstance(payload, dict):
            msg = {**example, "payload": payload}
            assert valid(msg) == (commands.receipt_query_problem(msg) is None), payload


def test_every_example_command_is_valid_for_command_problem():
    for example in examples("command"):
        assert commands.command_problem(example) is None, example["payload"]["op"]

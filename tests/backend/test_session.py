"""The Connecting flow of contracts/README.md over real sockets, without Blender.

Every test runs a host with both listeners, as host.py does: the VR app's plain
localhost port and a LAN port for the Client role (TLS with the session token,
or the fallback with the token in hello), both on 127.0.0.1. A fake document
stands in for document.py and the scene of contracts/examples for sync.py (which
needs Blender; test_scene.py covers it). Every message the host sends is checked
against its schema in contracts/schemas.
"""

import contextlib
import json
import logging
import threading
import time

import lan
import protocol
import pytest
import server
import session
from hello_client import hello, join
from jsonschema import Draft202012Validator
from ping_client import Client
from test_contracts import REGISTRY, SCHEMAS, load

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
EXAMPLE_SCENE = load("scene.snapshot.json")["payload"]
RECEIVED = []  # by every Peer in the current test


def snapshot(document):
    """The example scene for `document`, standing in for sync.snapshot."""
    return {**EXAMPLE_SCENE, "document": document}


def assert_valid(msg):
    assert msg is not None, "the host closed the connection"
    Draft202012Validator(SCHEMAS[msg["type"]], registry=REGISTRY).validate(msg)
    return msg


class Peer(Client):
    """A client that checks every message it gets against the contract."""

    def recv(self):
        msg = super().recv()
        if msg is not None:
            RECEIVED.append(assert_valid(msg))
        return msg

    def join(self, **hello_args):
        msgs = join(self, **hello_args)
        assert [m and m["type"] for m in msgs] == ["welcome", "scene.snapshot", "session.update"]
        return msgs


class Host:
    """A running session with its server; vr() and lee() connect clients to the right port."""

    def __init__(self, srv, sess, changes, tls):
        self.srv, self.sess, self.changes, self.tls = srv, sess, changes, tls

    @property
    def lan_port(self):
        return self.srv.listeners[1].port

    def vr(self):
        return Peer(port=self.srv.port)

    def lee(self):
        return Peer(port=self.lan_port, token=TOKEN, tls=self.tls)

    def lee_hello(self, **hello_args):
        """Hello arguments for the Client role; the fallback needs the token in it."""
        return {"role": "blender-client", "name": "Lee", **hello_args,
                **({} if self.tls else {"token": TOKEN})}


@contextlib.contextmanager
def hosting(tls=True, document=DOCUMENT):
    """A session on both listeners, drained by a thread like Blender's timer."""
    RECEIVED.clear()
    changes = []
    lan_listener = server.Listener(
        "127.0.0.1", 0,
        ssl=lan.server_tls_context(TOKEN) if tls else None,
        token=None if tls else TOKEN,
        roles=("blender-client",),
    )
    sess = session.Session(lambda: dict(document), snapshot, SESSION_ID,
                           on_change=lambda: changes.append(list(sess.participants.values())))
    srv = sess.attach(server.Server(port=0, extra_listeners=[lan_listener]))
    srv.start()
    stop = threading.Event()

    def pump():
        while not stop.is_set():
            srv.drain()
            time.sleep(0.005)

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    try:
        yield Host(srv, sess, changes, tls)
    finally:
        stop.set()
        thread.join()
        srv.stop()


def names(update):
    return [(p["name"], p["role"]) for p in update["payload"]["participants"]]


def assert_refused(client, msg, code):
    reply = client.recv()
    assert reply["type"] == "error" and reply["payload"]["code"] == code, reply
    assert reply["re"] == msg["id"]
    assert client.recv() is None, "the host must close after refusing"
    return reply


def assert_pong_next(client):
    """Nothing else is waiting for this client: the next message is the pong."""
    ping = protocol.message("ping")
    client.send(ping)
    assert client.recv()["re"] == ping["id"]


def test_handshake():
    with hosting() as host, host.vr() as talia:
        msg = hello(name="Talia")
        talia.send(msg)
        welcome, snapshot, update = talia.recv(), talia.recv(), talia.recv()

    assert welcome["type"] == "welcome" and welcome["re"] == msg["id"]
    w = welcome["payload"]
    assert w["session_id"] == SESSION_ID and w["host_epoch"] == host.sess.host_epoch
    assert session.is_uuid(w["actor_id"]) and w["can_edit"] is True
    assert w["app"] == {"name": "spatial_modeling", "version": "0.1.0"}
    assert w["document"] == DOCUMENT

    assert snapshot["type"] == "scene.snapshot"
    assert snapshot["payload"] == {**EXAMPLE_SCENE, "document": DOCUMENT}

    assert update["type"] == "session.update"
    assert update["payload"]["participants"] == [
        host.sess.host,
        {"actor_id": w["actor_id"], "name": "Talia", "role": "vr"},
    ]
    assert update["payload"]["leases"] == []


def test_each_connection_gets_its_own_actor_and_the_same_session():
    with hosting() as host, host.vr() as a, host.vr() as b:
        wa, wb = a.join(name="A")[0]["payload"], b.join(name="B")[0]["payload"]
    assert wa["actor_id"] != wb["actor_id"]
    assert (wa["session_id"], wa["host_epoch"]) == (wb["session_id"], wb["host_epoch"])


def test_a_new_session_has_a_new_host_epoch_and_keeps_the_session_id():
    epochs = set()
    for _ in range(2):
        with hosting() as host, host.vr() as client:
            welcome = client.join()[0]["payload"]
            assert welcome["session_id"] == SESSION_ID
            epochs.add(welcome["host_epoch"])
    assert len(epochs) == 2


@pytest.mark.parametrize("type_", ["command", "lease.acquire", "receipt.query", "frobnicate"])
def test_only_hello_and_ping_are_answered_before_welcome(type_):
    with hosting() as host, host.vr() as client:
        assert_pong_next(client)
        msg = protocol.message(type_)
        client.send(msg)
        reply = client.recv()
        assert reply["payload"]["code"] == "permission_denied" and reply["re"] == msg["id"]
        client.join()  # the connection stayed open


def test_wrong_version_envelope_is_refused_and_closed():
    with hosting() as host, host.vr() as client:
        msg = hello()
        msg["v"] = 2
        client.send(msg)
        assert_refused(client, msg, "unsupported_version")


@pytest.mark.parametrize("tls", [True, False], ids=["tls", "no-tls"])
def test_client_role_joins_on_the_lan_port_read_only_and_everyone_sees_it(tls):
    with hosting(tls) as host, host.vr() as talia, host.lee() as lee:
        talia.join(name="Talia")
        welcome, _, update = lee.join(**host.lee_hello())
        assert welcome["payload"]["can_edit"] is False  # until P3A-W-3
        both = [("Host Blender", "host"), ("Talia", "vr"), ("Lee", "blender-client")]
        assert names(update) == both
        assert names(talia.recv()) == both  # across listeners
        lee.close()
        assert names(talia.recv()) == both[:2]


@pytest.mark.parametrize("tls", [True, False], ids=["tls", "no-tls"])
def test_client_role_gets_the_same_snapshot_and_every_update_read_only(tls):
    update = load("scene.update.json")
    with hosting(tls) as host, host.vr() as talia, host.lee() as lee:
        vr_snapshot = talia.join(name="Talia")[1]
        welcome, lee_snapshot, _ = lee.join(**host.lee_hello())
        talia.recv()  # session.update for Lee
        assert welcome["payload"]["can_edit"] is False
        assert lee_snapshot["payload"] == vr_snapshot["payload"]
        assert lee_snapshot["payload"]["objects"] == EXAMPLE_SCENE["objects"]
        host.sess.broadcast(update)  # what sync.flush() does after a change
        assert talia.recv() == update and lee.recv() == update

        command = load("command.json")  # until P3A-W-3 the Client role can't edit
        lee.send(command)
        reply = lee.recv()
        assert reply["type"] == "error" and reply["re"] == command["id"], reply
        assert reply["payload"]["code"] in ("permission_denied", "unknown_type"), reply


def test_the_token_never_reaches_the_session_or_any_message(caplog):
    caplog.set_level(logging.DEBUG)
    seen = []
    with hosting(tls=False) as host, host.vr() as talia, host.lee() as lee:
        original = host.sess.hello
        host.srv.handlers.maps[0]["hello"] = lambda msg, conn: seen.append(
            msg["payload"]) or original(msg, conn)
        talia.join(name="Talia")
        lee.join(**host.lee_hello())
        talia.recv()
    assert seen and all("token" not in payload for payload in seen)
    received = json.dumps(RECEIVED).replace("-", "").lower()
    assert lan.normalize_token(TOKEN) not in received
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("tls", [True, False], ids=["tls", "no-tls"])
def test_client_role_with_another_version_is_refused(tls):
    with hosting(tls) as host, host.lee() as lee:
        msg = hello(**host.lee_hello(version="0.0.9"))
        lee.send(msg)
        assert_refused(lee, msg, "unsupported_version")


def test_vr_app_version_is_not_compared():
    with hosting() as host, host.vr() as client:
        client.join(version="7.3.1")


def test_each_port_admits_only_its_role():
    with hosting() as host:
        for client, args in ((host.vr(), {"role": "blender-client"}), (host.lee(), {})):
            with client:
                msg = hello(name="Wrong port", **args)
                client.send(msg)
                assert_refused(client, msg, "permission_denied")
    assert host.changes == []


@pytest.mark.parametrize(
    "expected",
    [
        {"id": "f" * 32, "open_epoch": DOCUMENT["open_epoch"]},  # another document
        {"id": DOCUMENT["id"], "open_epoch": "e" * 32},  # the same one, reopened
    ],
)
def test_hello_expecting_another_document_is_refused(expected):
    with hosting() as host, host.lee() as lee:
        msg = hello(**host.lee_hello(document=expected))
        lee.send(msg)
        reply = assert_refused(lee, msg, "wrong_document")
    assert reply["payload"]["details"] == {
        "document": {k: DOCUMENT[k] for k in ("id", "open_epoch", "name")}
    }
    assert host.changes == []


def test_hello_expecting_this_document_is_welcomed():
    expected = {k: DOCUMENT[k] for k in ("id", "open_epoch")}
    with hosting() as host, host.lee() as lee:
        lee.join(**host.lee_hello(document=expected))


@pytest.mark.parametrize(
    "change",
    [
        {"role": "host"},
        {"name": ""},
        {"app": {"name": "x", "version": "latest"}},
        {"document": {"id": "nope", "open_epoch": DOCUMENT["open_epoch"]}},
        {"colour": "red"},
    ],
)
def test_malformed_hello_is_invalid_and_keeps_the_connection(change):
    with hosting() as host, host.vr() as client:
        msg = hello()
        msg["payload"].update(change)
        client.send(msg)
        reply = client.recv()
        assert reply["payload"]["code"] == "invalid_message" and reply["re"] == msg["id"]
        client.join()


def test_second_hello_on_a_welcomed_connection_is_invalid():
    with hosting() as host, host.vr() as client:
        client.join()
        msg = hello(name="Someone else")
        client.send(msg)
        reply = client.recv()
        assert reply["payload"]["code"] == "invalid_message" and reply["re"] == msg["id"]
        assert_pong_next(client)
    assert len(host.changes) == 1


def test_everyone_gets_session_update_when_someone_joins_or_leaves():
    with hosting() as host, host.vr() as a:
        assert names(a.join(name="A")[2]) == [("Host Blender", "host"), ("A", "vr")]
        with host.vr() as b:
            update_b = b.join(name="B")[2]
            update_a = a.recv()
            assert names(update_a) == names(update_b) == [
                ("Host Blender", "host"), ("A", "vr"), ("B", "vr")]
        assert names(a.recv()) == [("Host Blender", "host"), ("A", "vr")]  # B left
        assert [len(c) for c in host.changes] == [1, 2, 1]


def test_refused_and_unwelcomed_connections_get_no_session_update():
    with hosting() as host, host.vr() as waiting, host.vr() as a:
        a.join(name="A")
        with host.vr() as b:
            b.join(name="B")
        assert names(a.recv())[-1] == ("B", "vr")
        assert names(a.recv())[-1] == ("A", "vr")
        assert_pong_next(waiting)


def test_heartbeat_timeout_closes_a_participant_and_others_see_it_leave(monkeypatch):
    monkeypatch.setattr(server, "HEARTBEAT_TIMEOUT", 0.5)
    with hosting() as host, host.vr() as a, host.lee() as silent:
        a.join(name="A")
        silent.join(**host.lee_hello(name="Silent"))
        assert names(a.recv())[-1] == ("Silent", "blender-client")
        deadline = time.monotonic() + 3
        update = None
        while update is None:  # A keeps pinging; Silent sends nothing
            assert time.monotonic() < deadline, "the silent participant was never dropped"
            time.sleep(0.1)
            ping = protocol.message("ping")
            a.send(ping)
            while (msg := a.recv())["type"] != "pong":
                update = msg
        assert names(update) == [("Host Blender", "host"), ("A", "vr")]
        assert silent.recv() is None


def test_broadcast_reaches_participants_on_both_ports_except_the_excluded_one():
    with hosting() as host, host.vr() as a, host.lee() as lee, host.vr() as waiting:
        a.join(name="A")
        lee.join(**host.lee_hello())
        a.recv()  # Lee joined
        assert_pong_next(waiting)
        conn_a = next(c for c, actor in host.sess.participants.items() if actor["name"] == "A")
        update = host.sess.session_update()
        host.sess.broadcast(update, exclude=conn_a)
        assert lee.recv() == update
        for client in (a, waiting):
            assert_pong_next(client)

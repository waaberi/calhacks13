"""The host server over real sockets, without Blender. drain() stands in for the bpy timer."""

import contextlib
import json
import socket
import threading
import time

import protocol
import pytest
import server
from ping_client import Client

# A crash on the server thread must fail the test, not just warn.
pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")


def join(msg, conn):
    """Stands in for session.py's hello handler: lets the connection join."""
    conn.joined = True
    return protocol.message("test.joined", re=msg["id"])


def joined(client):
    client.send(protocol.message("hello"))
    assert client.recv()["type"] == "test.joined"
    return client


@contextlib.contextmanager
def running(handlers=None, pump=True, extra_listeners=(), **hooks):
    """A server on a free port; with pump, a thread drains it like Blender's timer."""
    srv = server.Server(port=0, handlers=handlers, extra_listeners=extra_listeners, **hooks)
    srv.start()
    stop = threading.Event()

    def drain_loop():
        while not stop.is_set():
            srv.drain()
            time.sleep(0.005)

    thread = threading.Thread(target=drain_loop, daemon=True)
    if pump:
        thread.start()
    try:
        yield srv
    finally:
        stop.set()
        if pump:
            thread.join()
        srv.stop()


def wait_for_inbox(srv, n, timeout=5.0):
    deadline = time.monotonic() + timeout
    while srv.inbox.qsize() < n:
        assert time.monotonic() < deadline, "messages never reached the queue"
        time.sleep(0.005)


def assert_ping_works(client):
    ping = protocol.message("ping")
    client.send(ping)
    assert client.recv()["re"] == ping["id"]


def assert_error(reply, code, re=None):
    assert reply["type"] == "error"
    assert reply["payload"]["code"] == code
    assert isinstance(reply["payload"]["message"], str)
    assert reply.get("re") == re


def test_listens_on_localhost_8765_by_default():
    srv = server.Server()
    assert (srv.host, srv.port) == ("127.0.0.1", 8765)


def test_ping_pong():
    with running() as srv, Client(port=srv.port) as client:
        ping = protocol.message("ping")
        client.send(ping)
        pong = client.recv()
    assert pong["type"] == "pong"
    assert pong["re"] == ping["id"]
    assert pong["v"] == protocol.VERSION and pong["payload"] == {}


def test_handlers_run_only_inside_drain():
    seen = []
    handlers = {"ping": lambda msg, conn: seen.append(threading.get_ident()) or server.ping(msg, conn)}
    with running(handlers, pump=False) as srv, Client(port=srv.port) as client:
        client.send(protocol.message("ping"))
        wait_for_inbox(srv, 2)  # the connection opening, then the ping
        assert seen == []  # queued by the network thread, not handled there
        assert srv.drain() == 2
        assert seen == [threading.get_ident()]
        assert client.recv()["type"] == "pong"


def test_malformed_json_is_rejected_and_connection_stays_open():
    with running() as srv, Client(port=srv.port) as client:
        client.send(b"not json\n")
        assert_error(client.recv(), "invalid_message")
        client.send(b"[" * 100_000 + b"\n")  # too deep for the JSON parser
        assert_error(client.recv(), "invalid_message")
        assert_ping_works(client)


def test_bad_envelope_is_rejected_with_re():
    with running() as srv, Client(port=srv.port) as client:
        client.send(b'{"v": 1, "type": "ping", "id": "abc", "payload": []}\n')
        assert_error(client.recv(), "invalid_message", re="abc")
        assert_ping_works(client)


def test_wrong_version_closes_the_connection():
    with running() as srv, Client(port=srv.port) as client:
        client.send(b'{"v": 2, "type": "ping", "id": "abc", "payload": {}}\n')
        assert_error(client.recv(), "unsupported_version", re="abc")
        assert client.recv() is None


def test_oversized_line_closes_the_connection(monkeypatch):
    monkeypatch.setattr(protocol, "MAX_LINE_BYTES", 1024)
    with running() as srv, Client(port=srv.port) as client:
        ping = protocol.message("ping", {"pad": ""})
        ping["payload"]["pad"] = "x" * (1024 - len(protocol.encode(ping)))
        assert len(protocol.encode(ping)) == 1024  # exactly at the limit is fine
        client.send(ping)
        assert client.recv()["re"] == ping["id"]

        ping["payload"]["pad"] += "x"
        line = json.dumps(ping, separators=(",", ":")).encode() + b"\n"
        assert len(line) == 1025
        client.send(line)
        assert_error(client.recv(), "message_too_large")
        assert client.recv() is None


def test_unknown_type_gets_an_error():
    with running({"hello": join}) as srv, Client(port=srv.port) as client:
        msg = protocol.message("frobnicate")
        client.send(msg)
        assert_error(client.recv(), "permission_denied", re=msg["id"])  # not joined yet
        joined(client).send(msg)
        assert_error(client.recv(), "unknown_type", re=msg["id"])
        assert_ping_works(client)


def test_failing_handler_gets_an_error():
    def boom(msg, conn):
        raise RuntimeError("boom")

    handlers = {"boom": boom, "ping": server.ping, "hello": join}
    with running(handlers) as srv, joined(Client(port=srv.port)) as client:
        msg = protocol.message("boom")
        client.send(msg)
        assert_error(client.recv(), "internal_error", re=msg["id"])
        assert_ping_works(client)


def test_full_queue_answers_busy(monkeypatch):
    monkeypatch.setattr(server, "MAX_PENDING", 2)
    with running(pump=False) as srv, Client(port=srv.port) as client:
        pings = [protocol.message("ping") for _ in range(3)]
        for ping in pings:
            client.send(ping)
        assert_error(client.recv(), "busy", re=pings[2]["id"])
        assert srv.drain() == 3  # the connection opening and two pings
        assert [client.recv()["re"] for _ in range(2)] == [p["id"] for p in pings[:2]]
        client.send(pings[2])  # there is room again
        wait_for_inbox(srv, 1)
        srv.drain()
        assert client.recv()["re"] == pings[2]["id"]


def test_two_clients_get_their_own_replies_and_a_bad_one_is_isolated():
    with running() as srv, Client(port=srv.port) as a, Client(port=srv.port) as b:
        pa, pb = protocol.message("ping"), protocol.message("ping")
        a.send(pa)
        b.send(pb)
        assert b.recv()["re"] == pb["id"]
        assert a.recv()["re"] == pa["id"]

        a.send(b'{"v": 99}\n')
        assert_error(a.recv(), "unsupported_version")
        assert a.recv() is None
        assert_ping_works(b)


def test_stop_closes_everything_and_restart_reuses_the_port():
    srv = server.Server(port=0)
    srv.start()
    port = srv.port
    for _ in range(3):
        client = Client(port=port)
        client.send(protocol.message("ping"))
        wait_for_inbox(srv, 2)
        srv.drain()
        assert client.recv()["type"] == "pong"

        srv.stop()  # with the client still connected
        assert not srv.running
        assert client.recv() is None
        client.close()
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(("127.0.0.1", port), timeout=1)

        srv.start()  # same port, no "address already in use"
        assert srv.port == port and srv.running
    srv.stop()
    srv.stop()  # stopping twice is harmless


def test_port_in_use_raises_and_leaves_the_first_server_alone():
    with running() as first:
        with pytest.raises(OSError):
            server.Server(port=first.port).start()
        with Client(port=first.port) as client:
            assert_ping_works(client)


def test_drain_after_stop_is_harmless():
    srv = server.Server(port=0)
    srv.start()
    srv.stop()
    srv.inbox.put((server.Connection(srv, srv.listeners[0], 1, None), protocol.message("ping")))
    assert srv.drain() == 1  # the reply is dropped, nothing raises


def test_nan_is_rejected_and_connection_stays_open():
    with running() as srv, Client(port=srv.port) as client:
        msg_id = protocol.message("ping")["id"]
        client.send(b'{"v": 1, "type": "ping", "id": "%s", "payload": {"x": NaN}}\n' % msg_id.encode())
        assert_error(client.recv(), "invalid_message", re=msg_id)
        assert_ping_works(client)


def test_connection_events_reach_drain_in_order_on_its_thread():
    events = []

    def record(kind):
        return lambda conn, *msg: events.append((kind, conn, threading.get_ident()))

    handlers = {"ping": lambda msg, conn: record("ping")(conn) or server.ping(msg, conn)}
    hooks = {"on_connect": record("open"), "on_disconnect": record("close")}
    with running(handlers, pump=False, **hooks) as srv:
        with Client(port=srv.port) as client:
            client.send(protocol.message("ping"))
            wait_for_inbox(srv, 2)
            assert events == []  # nothing runs on the network thread
            srv.drain()
            assert client.recv()["type"] == "pong"
            (conn,) = srv.connections
            assert not conn.joined and conn.peer[0] == "127.0.0.1"
        wait_for_inbox(srv, 1)
        srv.drain()
        assert srv.connections == set()
    assert [(kind, c) for kind, c, _ in events] == [("open", conn), ("ping", conn), ("close", conn)]
    assert {thread for *_, thread in events} == {threading.get_ident()}


def test_disconnect_is_never_dropped_when_the_queue_is_full(monkeypatch):
    monkeypatch.setattr(server, "MAX_PENDING", 1)
    closed = []
    with running(pump=False, on_disconnect=closed.append) as srv:
        with Client(port=srv.port) as client:
            first, second = protocol.message("ping"), protocol.message("ping")
            client.send(first)
            client.send(second)
            assert_error(client.recv(), "busy", re=second["id"])
        wait_for_inbox(srv, 3)
        assert srv.drain() == 3
        assert len(closed) == 1


def test_only_hello_and_ping_before_joining():
    handlers = {"hello": join, "ping": server.ping, "command": lambda msg, conn: protocol.message(
        "result", re=msg["id"])}
    with running(handlers) as srv, Client(port=srv.port) as client:
        for type_ in ("command", "lease.acquire", "frobnicate"):
            msg = protocol.message(type_)
            client.send(msg)
            assert_error(client.recv(), "permission_denied", re=msg["id"])
        assert_ping_works(client)  # still open
        msg = protocol.message("command")
        joined(client).send(msg)
        reply = client.recv()
        assert reply["type"] == "result" and reply["re"] == msg["id"]


def test_close_sends_pending_replies_first_and_ignores_later_messages():
    handled = []

    def refuse(msg, conn):
        handled.append(msg["id"])
        conn.send(server.error("permission_denied", "no", msg["id"]))
        conn.close()

    with running({"hello": refuse}) as srv, Client(port=srv.port) as client:
        first, second = protocol.message("hello"), protocol.message("hello")
        client.send(protocol.encode(first) + protocol.encode(second))  # pipelined
        assert_error(client.recv(), "permission_denied", re=first["id"])
        assert client.recv() is None
    assert handled == [first["id"]]


def test_broadcast_reaches_joined_connections_except_the_excluded_one():
    with (
        running({"hello": join, "ping": server.ping}) as srv,
        joined(Client(port=srv.port)) as a,
        joined(Client(port=srv.port)) as b,
        Client(port=srv.port) as stranger,
    ):
        assert_ping_works(stranger)  # its connection event has been drained
        sender = next(c for c in srv.connections if c.joined and c.peer[1] == a.sock.getsockname()[1])
        news = protocol.message("test.news")
        srv.broadcast(news, exclude=sender)
        assert b.recv() == news
        srv.broadcast(news)
        assert a.recv() == news and b.recv() == news
        for client in (a, b, stranger):
            assert_ping_works(client)  # the next thing each one gets is its pong


def test_heartbeat_closes_a_silent_connection(monkeypatch):
    monkeypatch.setattr(server, "HEARTBEAT_TIMEOUT", 0.3)
    closed = []
    with (
        running(on_disconnect=closed.append) as srv,
        Client(port=srv.port) as silent,
        Client(port=srv.port) as chatty,
    ):
        for _ in range(6):  # 0.6 s, twice the timeout
            time.sleep(0.1)
            assert_ping_works(chatty)
        assert silent.recv() is None
        assert len(closed) == 1 and len(srv.connections) == 1  # the pings kept chatty open

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


@contextlib.contextmanager
def running(handlers=None, pump=True):
    """A server on a free port; with pump, a thread drains it like Blender's timer."""
    srv = server.Server(port=0, handlers=handlers)
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
    handlers = {"ping": lambda msg: seen.append(threading.get_ident()) or server.ping(msg)}
    with running(handlers, pump=False) as srv, Client(port=srv.port) as client:
        client.send(protocol.message("ping"))
        wait_for_inbox(srv, 1)
        assert seen == []  # queued by the network thread, not handled there
        assert srv.drain() == 1
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
    with running() as srv, Client(port=srv.port) as client:
        msg = protocol.message("frobnicate")
        client.send(msg)
        assert_error(client.recv(), "unknown_type", re=msg["id"])
        assert_ping_works(client)


def test_failing_handler_gets_an_error():
    def boom(msg):
        raise RuntimeError("boom")

    with running({"boom": boom, "ping": server.ping}) as srv, Client(port=srv.port) as client:
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
        assert srv.drain() == 2
        assert [client.recv()["re"] for _ in range(2)] == [p["id"] for p in pings[:2]]


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
        wait_for_inbox(srv, 1)
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
    srv.inbox.put((1, protocol.message("ping")))
    assert srv.drain() == 1  # the reply is dropped, nothing raises

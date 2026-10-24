"""The LAN port over real sockets: TLS with the session token as a pre-shared key, and the
fallback without TLS that checks the token in hello. The localhost port must stay plain."""

import contextlib
import shutil
import socket
import ssl
import subprocess
import threading
import time

import lan
import protocol
import pytest
import server
from ping_client import Client, hello
from test_server import assert_error, assert_ping_works, running

pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")

TOKEN = lan.new_token()


@contextlib.contextmanager
def lan_server(tls=True, token=TOKEN, handlers=None, pump=True):
    """A host with its localhost port and a LAN port, both on free ports of 127.0.0.1."""
    listener = server.Listener(
        "127.0.0.1",
        0,
        ssl=lan.server_tls_context(token) if tls else None,
        token=None if tls else token,
    )
    with running(handlers, pump, extra_listeners=[listener]) as srv:
        yield srv, listener.port


def recording_hello(seen):
    """A stand-in hello handler that records what it got."""

    def handle(msg):
        seen.append(msg["payload"])
        return protocol.message("test.welcome", re=msg["id"])

    return {"hello": handle, "ping": server.ping}


def closed(client):
    try:
        return client.recv() is None
    except (ConnectionError, ssl.SSLError):
        return True


# The token and the key derived from it


def test_new_tokens_are_random_and_easy_to_read_aloud():
    tokens = {lan.new_token() for _ in range(50)}
    assert len(tokens) == 50
    for token in tokens:
        groups = token.split("-")
        assert [len(g) for g in groups] == [4] * 6
        assert set("".join(groups)) <= set(lan.TOKEN_ALPHABET)
        assert lan.normalize_token(token) == "".join(groups)


def test_case_spaces_and_dashes_do_not_matter():
    spoken = " ".join(TOKEN.upper().split("-"))
    assert lan.normalize_token(spoken) == lan.normalize_token(TOKEN)
    assert lan.tokens_match(TOKEN, spoken)
    assert lan.psk(spoken) == lan.psk(TOKEN)


def test_short_or_missing_tokens_are_rejected_without_echoing_them():
    for bad in ("", None, "   ", "short-token-1"):
        with pytest.raises(lan.TokenError) as info:
            lan.normalize_token(bad)
        assert "short" not in str(info.value)
    with pytest.raises(lan.TokenError):
        lan.server_tls_context("abc")
    with pytest.raises(lan.TokenError):
        lan.client_tls_context("")


def test_tokens_match_rejects_wrong_missing_and_non_string_tokens():
    assert not lan.tokens_match(TOKEN, lan.new_token())
    assert not lan.tokens_match(TOKEN, None)
    assert not lan.tokens_match(TOKEN, 12345678901234567890)
    assert not lan.tokens_match(TOKEN, TOKEN[:10])


def test_psk_is_32_bytes_and_depends_on_the_token():
    assert len(lan.psk(TOKEN)) == 32
    assert lan.psk(TOKEN) != lan.psk(lan.new_token())


def test_client_context_refuses_certificates_by_construction():
    ctx = lan.client_tls_context(TOKEN)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and not ctx.check_hostname
    assert ctx.cert_store_stats()["x509"] == 0  # nothing a certificate could chain to
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
    assert {c["name"] for c in ctx.get_ciphers() if c["protocol"] == "TLSv1.2"} == {
        "ECDHE-PSK-CHACHA20-POLY1305"
    }


# TLS with the token


def test_right_token_connects_over_tls_and_pings():
    with lan_server() as (_, port), Client(port=port, token=TOKEN) as client:
        assert client.sock.version() == "TLSv1.3"
        assert client.sock.getpeercert(binary_form=True) is None  # authenticated by the PSK
        assert_ping_works(client)


def test_tls_1_2_with_the_token_works_too():
    ctx = lan.client_tls_context(TOKEN)
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    with (
        lan_server() as (_, port),
        ctx.wrap_socket(socket.create_connection(("127.0.0.1", port))) as sock,
    ):
        assert sock.version() == "TLSv1.2"
        assert sock.cipher()[0] == "ECDHE-PSK-CHACHA20-POLY1305"


def test_wrong_token_fails_the_handshake():
    with lan_server() as (_, port), pytest.raises(lan.HandshakeError):
        Client(port=port, token=lan.new_token())


def test_missing_token_fails_the_handshake():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # TLS, but no PSK
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with (
        lan_server() as (_, port),
        socket.create_connection(("127.0.0.1", port)) as raw,
        pytest.raises((ssl.SSLError, ConnectionError)),
    ):
        ctx.wrap_socket(raw)


def test_plain_tcp_to_the_tls_port_fails():
    with lan_server() as (srv, port), Client(port=port) as client:
        client.send(protocol.message("ping"))
        assert closed(client)
        assert srv.inbox.empty()


def test_tls_to_a_plain_port_fails():
    with lan_server() as (srv, _), pytest.raises(lan.HandshakeError):
        lan.connect("127.0.0.1", TOKEN, port=srv.port, timeout=2)


def test_a_failed_handshake_does_not_affect_other_connections():
    with (
        lan_server() as (srv, port),
        Client(port=port, token=TOKEN) as remote,
        Client(port=srv.port) as local,
    ):
        for _ in range(3):
            with pytest.raises(lan.HandshakeError):
                Client(port=port, token=lan.new_token())
            with Client(port=port) as plain:
                plain.send(b"garbage\n")
                assert closed(plain)
        assert_ping_works(remote)
        assert_ping_works(local)


def test_a_silent_client_is_dropped_after_the_handshake_timeout(monkeypatch):
    monkeypatch.setattr(lan, "HANDSHAKE_TIMEOUT", 0.3)
    with lan_server() as (_, port), socket.create_connection(("127.0.0.1", port)) as raw:
        raw.settimeout(5)
        started = time.monotonic()
        assert raw.recv(100) == b""
        assert time.monotonic() - started < 3


def test_hello_over_tls_needs_no_token_and_handlers_never_see_one():
    seen = []
    with (
        lan_server(handlers=recording_hello(seen)) as (_, port),
        Client(port=port, token=TOKEN) as client,
    ):
        for greeting in (hello("Lee"), hello("Lee", TOKEN)):
            client.send(greeting)
            assert client.recv()["re"] == greeting["id"]
    assert seen and all("token" not in payload for payload in seen)


@pytest.mark.skipif(not shutil.which("openssl"), reason="needs the openssl command")
def test_an_impostor_with_a_certificate_instead_of_the_token_is_refused(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
         "-nodes", "-keyout", key, "-out", cert, "-days", "1", "-subj", "/CN=impostor"],
        check=True, capture_output=True,
    )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    listening = socket.create_server(("127.0.0.1", 0))

    def impostor():
        conn, _ = listening.accept()
        with contextlib.suppress(OSError), ctx.wrap_socket(conn, server_side=True) as tls:
            tls.recv(100)

    thread = threading.Thread(target=impostor, daemon=True)
    thread.start()
    with listening, pytest.raises(lan.HandshakeError, match="certificate"):
        lan.connect("127.0.0.1", TOKEN, port=listening.getsockname()[1])
    thread.join(5)


# Without TLS: the token in hello


def test_without_tls_the_right_token_in_hello_admits_and_is_stripped():
    seen = []
    with (
        lan_server(tls=False, handlers=recording_hello(seen)) as (_, port),
        Client(port=port, token=TOKEN, tls=False) as client,
    ):
        greeting = hello("Lee", " ".join(TOKEN.upper().split("-")))  # as read aloud
        client.send(greeting)
        assert client.recv()["type"] == "test.welcome"
        assert_ping_works(client)
    assert seen == [{k: v for k, v in greeting["payload"].items() if k != "token"}]


@pytest.mark.parametrize(
    ("first", "text"),
    [
        (hello("Lee", lan.new_token()), "wrong session token"),
        (hello("Lee", ""), "wrong session token"),
        (hello("Lee"), "hello has no session token"),
        (protocol.message("ping"), "send hello with the session token first"),
    ],
    ids=["wrong", "empty", "missing", "not-hello"],
)
def test_without_tls_a_bad_first_message_is_refused_and_closed(first, text, caplog):
    seen = []
    with (
        lan_server(tls=False, handlers=recording_hello(seen)) as (srv, port),
        Client(port=port, token=TOKEN, tls=False) as client,
        Client(port=srv.port) as local,
    ):
        client.send(first)
        reply = client.recv()
        assert_error(reply, "permission_denied", re=first["id"])
        assert reply["payload"]["message"] == text
        assert closed(client)
        assert_ping_works(local)
    assert seen == []
    assert TOKEN not in caplog.text
    sent = first["payload"].get("token")
    assert not sent or sent not in caplog.text


def test_without_tls_bad_json_first_is_refused_and_closed():
    with lan_server(tls=False) as (_, port), Client(port=port, token=TOKEN, tls=False) as client:
        client.send(b"not json\n")
        assert_error(client.recv(), "invalid_message")
        assert closed(client)


def test_without_tls_a_silent_client_is_dropped(monkeypatch):
    monkeypatch.setattr(lan, "HANDSHAKE_TIMEOUT", 0.3)
    with lan_server(tls=False) as (_, port), Client(port=port, token=TOKEN, tls=False) as client:
        assert closed(client)


def test_without_tls_nothing_reaches_a_client_before_its_hello():
    with (
        lan_server(tls=False, handlers=recording_hello([])) as (srv, port),
        Client(port=port, token=TOKEN, tls=False) as client,
    ):
        time.sleep(0.2)
        assert srv._writers == {}  # not addressable by send() or any broadcast
        greeting = hello("Lee", TOKEN)
        client.send(greeting)
        assert client.recv()["re"] == greeting["id"]
        assert len(srv._writers) == 1


# The localhost port


def test_localhost_port_stays_plain_and_on_loopback_only():
    with lan_server() as (srv, _):
        local = srv.listeners[0]
        assert (local.host, local.ssl, local.token) == ("127.0.0.1", None, None)
        with Client(port=srv.port) as client:  # plain TCP, no token
            assert_ping_works(client)
        address = lan.local_address()
        if address and not address.startswith("127."):
            with pytest.raises(OSError):
                socket.create_connection((address, srv.port), timeout=1)


def test_default_server_has_only_the_localhost_port():
    srv = server.Server()
    assert [(listener.host, listener.port) for listener in srv.listeners] == [("127.0.0.1", 8765)]


def test_a_lan_port_that_cannot_bind_fails_the_start_and_frees_the_localhost_port():
    with lan_server() as (_, busy_port):
        srv = server.Server(port=0, extra_listeners=[server.Listener("127.0.0.1", busy_port)])
        with pytest.raises(OSError):
            srv.start()
        assert not srv.running
        local_port = srv.port
    if local_port:
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(("127.0.0.1", local_port), timeout=1)


def test_stop_closes_lan_connections_and_restart_reuses_both_ports():
    listener = server.Listener("127.0.0.1", 0, ssl=lan.server_tls_context(TOKEN))
    srv = server.Server(port=0, extra_listeners=[listener])
    srv.start()
    ports = (srv.port, listener.port)
    client = Client(port=listener.port, token=TOKEN)
    srv.stop()
    assert closed(client)
    client.close()
    srv.start()
    try:
        assert (srv.port, listener.port) == ports
        with Client(port=listener.port, token=TOKEN) as client:
            client.send(protocol.message("ping"))
            deadline = time.monotonic() + 5
            while srv.drain() == 0:
                assert time.monotonic() < deadline
                time.sleep(0.005)
            assert client.recv()["type"] == "pong"
    finally:
        srv.stop()

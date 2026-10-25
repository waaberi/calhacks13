"""Real socket/TLS tests for the controlled remote operator's pure worker."""

import dataclasses
import time

import pytest
import remote_control
from test_commands import DOCUMENT, SHAFT, TOKEN, hosting


def config(host, **changes):
    return remote_control.RemoteConfig("127.0.0.1", host.srv.listeners[1].port, TOKEN,
                                       timeout=2, **changes)


def test_default_off_never_opens_a_connection(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("network access while the feature is disabled")

    monkeypatch.setattr(remote_control.lan, "connect", forbidden)
    cfg = remote_control.RemoteConfig("host", 8767, "must-never-be-logged")
    result = remote_control.move_selected(cfg, DOCUMENT, SHAFT, 0)
    assert result.code == "feature_disabled" and result.outcome == "rejected"
    assert "must-never-be-logged" not in repr(cfg) + repr(result)


@pytest.mark.parametrize("kwargs,code", [
    ({"target_id": "not-an-id"}, "invalid_target"),
    ({"generation": True}, "invalid_target"),
    ({"expected_document": {}}, "invalid_target"),
])
def test_invalid_target_never_connects(monkeypatch, kwargs, code):
    monkeypatch.setattr(remote_control.lan, "connect", lambda *_a, **_kw: pytest.fail("connected"))
    cfg = remote_control.RemoteConfig("host", 8767, TOKEN)
    args = {"expected_document": DOCUMENT, "target_id": SHAFT, "generation": 0, **kwargs}
    result = remote_control.move_selected(cfg, **args, enabled=True)
    assert result.code == code and not result.blocked


def test_controlled_route_requires_tls_before_connection():
    cfg = remote_control.RemoteConfig("host", 8767, TOKEN, tls=False)
    result = remote_control.move_selected(cfg, DOCUMENT, SHAFT, 0, enabled=True)
    assert result.code == "tls_required"


def test_host_default_flag_refuses_without_mutation():
    with hosting(lan_port=True) as host:
        result = remote_control.move_selected(config(host), DOCUMENT, SHAFT, 0, enabled=True)
        assert result.code == "permission_denied" and result.outcome == "rejected"
        assert host.editor.applied == []


def test_exactly_one_command_has_a_shared_lease_before_apply_and_a_native_receipt():
    with hosting(lan_port=True, client_can_edit=True) as host:
        held = []
        host.editor.during_apply = lambda: held.extend(host.sess.store.leases())
        messages = []
        result = remote_control.move_selected(config(host), DOCUMENT, SHAFT, 0, enabled=True,
                                               on_event=messages.append)
        assert result.outcome == "applied" and not result.blocked
        assert host.editor.applied == [("object.move", SHAFT, {"by": [0.01, 0, 0]})]
        assert host.editor.objects[SHAFT]["location"] == [0.01, 0, 0]
        assert len(held) == 1 and held[0]["mode"] == "shared" and SHAFT in held[0]["targets"]
        assert result.receipt["request_id"] == result.request_id
        assert result.receipt["actor"]["role"] == "blender-client"
        assert [m["type"] for m in messages][-2:] == ["scene.update", "result"]
        deadline = time.monotonic() + 2
        while host.sess.store.leases() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert host.sess.store.leases() == []


@pytest.mark.parametrize("kind,code", [("generation", "stale_revision"),
                                      ("document", "wrong_document"),
                                      ("missing", "not_found")])
def test_fresh_snapshot_rejects_stale_or_wrong_target_before_command(kind, code):
    with hosting(lan_port=True, client_can_edit=True) as host:
        expected, target, generation = DOCUMENT.copy(), SHAFT, 0
        if kind == "generation":
            generation = 99
        elif kind == "document":
            expected["open_epoch"] = "1" * 32
        else:
            target = "f" * 32
        result = remote_control.move_selected(config(host), expected, target, generation,
                                               enabled=True)
        assert result.code == code and result.outcome == "rejected"
        assert host.editor.applied == []


def test_lost_receipt_is_unknown_and_never_replays_a_nonidempotent_move():
    with hosting(lan_port=True, client_can_edit=True) as host:
        original = host.cmds.command

        def lose_result(msg, conn):
            real_send = conn.send

            def send(*messages):
                real_send(*(m for m in messages if m["type"] != "result"))

            conn.send = send
            try:
                return original(msg, conn)
            finally:
                conn.send = real_send

        host.srv.handlers.maps[1]["command"] = lose_result
        cfg = dataclasses.replace(config(host), timeout=0.25)
        result = remote_control.move_selected(cfg, DOCUMENT, SHAFT, 0, enabled=True)
        assert result.outcome == "unknown" and result.blocked and result.request_id
        assert len(host.editor.applied) == 1
        assert host.editor.objects[SHAFT]["location"] == [0.01, 0, 0]


def test_native_unknown_receipt_is_not_reported_as_success():
    with hosting(lan_port=True, client_can_edit=True) as host:
        host.editor.halfway = "object.move"
        result = remote_control.move_selected(config(host), DOCUMENT, SHAFT, 0, enabled=True)
        assert result.outcome == "unknown" and result.blocked
        assert result.receipt["outcome"] == "unknown"
        assert len(host.editor.applied) == 1


def test_transport_failure_never_exposes_secret(monkeypatch):
    secret = "secret-that-must-not-appear"

    def fail(*_a, **_kw):
        raise OSError("failed with " + secret)

    monkeypatch.setattr(remote_control.lan, "connect", fail)
    cfg = remote_control.RemoteConfig("host", 8767, secret)
    result = remote_control.move_selected(cfg, DOCUMENT, SHAFT, 0, enabled=True)
    assert result.outcome == "rejected" and result.code == "connection_failed"
    assert secret not in repr(result)


def test_wire_reads_fragmented_multiple_frames_and_keeps_heartbeat(monkeypatch):
    first = remote_control.protocol.message("session.update", {})
    reply = remote_control.protocol.message("result", {}, re="f" * 32)
    encoded = remote_control.protocol.encode(first) + remote_control.protocol.encode(reply)

    class Fragmented:
        def __init__(self):
            self.parts = [b"", encoded[:13], encoded[13:]]
            self.sent = []

        def sendall(self, raw):
            self.sent.append(remote_control.protocol.decode(raw))

        def settimeout(self, _timeout):
            pass

        def recv(self, _count):
            part = self.parts.pop(0)
            if not part:
                raise TimeoutError
            return part

    monkeypatch.setattr(remote_control, "PING_INTERVAL", 0)
    sock = Fragmented()
    seen = []
    wire = remote_control._Wire(sock, seen.append)
    assert wire.wait(lambda m: m.get("re") == "f" * 32, 1) == reply
    assert seen == [first, reply]
    assert sock.sent and all(m["type"] == "ping" for m in sock.sent)


@pytest.mark.parametrize("action", ["cancel", "timeout"])
def test_late_or_cancelled_permission_never_sends_a_native_command(action):
    with hosting(lan_port=True, client_can_edit=True) as host:
        cancellation = remote_control.MoveCancellation()

        def received(msg):
            if msg["type"] == "lease.granted":
                if action == "cancel":
                    assert cancellation.cancel()
                else:
                    time.sleep(.15)

        cfg = dataclasses.replace(config(host), timeout=.1)
        result = remote_control.move_selected(cfg, DOCUMENT, SHAFT, 0, enabled=True,
            cancelled=cancellation, on_event=received)
        assert result.outcome == "rejected"
        assert not cancellation.sent and host.editor.applied == []
        deadline = time.monotonic() + 2
        while host.sess.store.leases() and time.monotonic() < deadline:
            time.sleep(.01)
        assert not host.sess.store.leases()


def test_cancel_and_send_boundary_is_irreversible():
    cancelled = remote_control.MoveCancellation()
    assert cancelled.cancel()
    with pytest.raises(remote_control._Refused, match="Cancelled"):
        cancelled.begin_send()
    sent = remote_control.MoveCancellation()
    sent.begin_send()
    assert sent.sent and not sent.cancel()
    assert not sent.is_set()

"""Recovery over real sockets, without Blender: "Reconnecting" in contracts/README.md (P5-W-1..3).

The host runs as in test_commands.py (session.py, commands.py, server.py, with the
FakeEditor), on the Unity port and the TLS LAN port. Each scenario runs on both
ports where it matters. Every message the host sends is checked against
contracts/schemas by Peer. test_recovery_blender.py repeats the publishing
checks with real Blender, and blender_check.py the whole story in GUI Blender.

A lost acknowledgement is a client that sends a command and hangs up before
reading anything more; it waits only until the host has closed its side, so the
command is queued before the reconnect.
"""

import copy
import socket
import time
import uuid

import pytest
from test_commands import ADD, PLATE, SHAFT, assert_rejected, hosting, valid
from test_fakes import fake_client

pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")

MOVE = {"by": [0.01, 0, 0]}
PORTS = ["vr", "lan"]


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.005)


def join(host, port, name):
    return host.vr(name) if port == "vr" else host.lee(name)


def hang_up(peer, *msgs):
    """Send msgs, then drop the connection without reading their answers."""
    for msg in msgs:
        peer.send(msg)
    peer.sock.shutdown(socket.SHUT_WR)
    peer.sock.settimeout(5)
    try:
        while peer.sock.recv(65536):  # unread: the client never sees the result
            pass
    except OSError:
        pass
    peer.close()


def assert_joined_fresh(peer, host):
    """A reconnect: Peer.join checked welcome, scene.snapshot, session.update; nothing follows."""
    welcome = peer.welcome
    assert welcome["host_epoch"] == host.sess.host_epoch
    assert welcome["document"]["revision"] == host.editor.revision
    peer.assert_quiet()  # no old result, activity or update after session.update
    return welcome


# 1. Reconnect


@pytest.mark.parametrize("port", PORTS)
def test_a_reconnect_gets_welcome_snapshot_and_session_update_and_nothing_replayed(port):
    with hosting(lan_port=True, client_can_edit=True) as host, host.vr("Jihyeon") as other:
        first = join(host, port, "Lee")
        other.expect("session.update")
        receipt = first.run("object.move", SHAFT, MOVE)
        assert receipt["outcome"] == "applied"
        other.expect("scene.update", "activity")
        old_actor = first.welcome["actor_id"]
        first.close()
        left = other.expect("session.update")[0]["payload"]["participants"]
        assert old_actor not in {p["actor_id"] for p in left}

        again = join(host, port, "Lee")
        welcome = assert_joined_fresh(again, host)
        assert welcome["actor_id"] != old_actor and welcome["can_edit"] is True
        assert again.revision == 1  # the snapshot has the move
        joined = other.expect("session.update")[0]["payload"]["participants"]
        assert welcome["actor_id"] in {p["actor_id"] for p in joined}
        other.assert_quiet()
        again.close()


# 2. Lost acknowledgement


@pytest.mark.parametrize("port", PORTS)
def test_a_lost_result_is_found_with_receipt_query_after_reconnecting(port):
    with hosting(lan_port=True, client_can_edit=True) as host, host.vr("Jihyeon") as other:
        lee = join(host, port, "Lee")
        other.expect("session.update")
        msg = lee.command("object.move", SHAFT, MOVE)
        hang_up(lee, msg)
        # Jihyeon saw it applied, exactly once
        _, activity, _ = other.expect("scene.update", "activity", "session.update")
        assert activity["payload"]["request_id"] == msg["id"]

        again = join(host, port, "Lee")
        assert_joined_fresh(again, host)
        assert again.revision == activity["payload"]["revision"]  # the snapshot has it
        reply = again.query(msg["id"])  # sent under the old actor_id: found all the same
        (receipt,) = reply["receipts"]
        assert reply["missing"] == reply["unknown"] == []
        assert receipt == activity["payload"] and receipt["outcome"] == "applied"
        assert receipt["actor"]["actor_id"] == lee.welcome["actor_id"] != again.welcome["actor_id"]
        assert len(host.editor.applied) == 1
        # Any participant on either port may ask, too
        assert other.query(msg["id"])["receipts"] == [receipt]
        again.close()


@pytest.mark.parametrize("port", PORTS)
def test_resending_after_a_reconnect_returns_the_stored_receipt_and_applies_once(port):
    with hosting(lan_port=True, client_can_edit=True) as host, host.vr("Jihyeon") as other:
        lee = join(host, port, "Lee")
        other.expect("session.update")
        msg = lee.command("object.move", SHAFT, MOVE)
        hang_up(lee, msg)
        other.expect("scene.update", "activity", "session.update")
        again = join(host, port, "Lee")
        other.expect("session.update")
        stored = again.query(msg["id"])["receipts"][0]

        before, same = again.ask(msg)  # the same ID and payload, old actor_id included
        assert before == [] and same["type"] == "result" and same["payload"] == stored
        rebuilt = copy.deepcopy(msg)
        rebuilt["payload"]["actor_id"] = again.welcome["actor_id"]
        assert_rejected(again.ask(rebuilt)[1]["payload"], "duplicate_request")
        assert len(host.editor.applied) == 1 and host.editor.revision == 1
        assert host.editor.objects[SHAFT]["location"] == [0.01, 0, 0]
        other.assert_quiet()  # no second update or activity
        again.close()


def test_a_request_the_host_never_got_is_missing_and_is_never_applied_later():
    with hosting(lan_port=True, client_can_edit=True) as host, host.lee() as lee, \
            host.vr("Jihyeon") as other:
        lost = lee.command("object.move", SHAFT, MOVE)  # never arrived (yet)
        assert lee.query(lost["id"]) == {"receipts": [], "missing": [lost["id"]], "unknown": []}
        # It turns up late, say from the old half-open connection: refused, not applied
        receipt = lee.ask(lost)[1]["payload"]
        assert_rejected(receipt, "duplicate_request")
        assert host.editor.applied == [] and host.editor.revision == 0
        assert lee.query(lost["id"])["receipts"] == [receipt]  # now a rejection, still not applied
        other.assert_quiet()


def test_a_query_answers_each_request_once_in_one_list():
    with hosting() as host, host.vr() as talia:
        applied = talia.run("object.move", SHAFT, MOVE)
        never = uuid.uuid4().hex
        reply = talia.query(never, applied["request_id"])
        assert reply == {"receipts": [applied], "missing": [never], "unknown": []}


# 3. Host restart


def test_after_a_host_restart_old_requests_are_unknown_never_missing():
    """Receipts last one host_epoch. The editor (Blender) keeps its state across the restart."""
    with hosting(lan_port=True, client_can_edit=True) as first:
        editor = first.editor
        lee = first.lee()
        applied = lee.run("object.move", SHAFT, MOVE)
        lost = lee.command("object.move", PLATE, MOVE)
        never = lee.command("object.add", args=ADD)
        hang_up(lee, lost)
        old_epoch = lee.welcome["host_epoch"]
        wait_until(lambda: len(editor.applied) == 2)  # the lost one applied before the restart

    with hosting(editor, lan_port=True, client_can_edit=True) as second:
        again = second.lee()
        assert again.welcome["host_epoch"] != old_epoch
        assert again.welcome["session_id"] == lee.welcome["session_id"]
        assert again.revision == 2  # the snapshot shows both moves
        ids = [applied["request_id"], lost["id"], never["id"]]
        reply = again.query(*ids, host_epoch=old_epoch)
        assert reply == {"receipts": [], "missing": [], "unknown": ids}
        # Resending the lost one doesn't apply it again: it carries the old actor and epoch
        for msg in (lost, never):
            assert again.ask(msg)[1]["payload"]["outcome"] == "rejected"
        assert len(editor.applied) == 2
        again.close()


# 4. Unknown outcome


def test_an_unknown_outcome_freezes_writes_on_both_ports_until_everyone_has_the_snapshot():
    def broken(document):
        raise RuntimeError("the scene can't be read yet")

    with hosting(lan_port=True, client_can_edit=True) as host, host.vr("Talia") as talia, \
            host.lee() as lee:
        talia.expect("session.update")
        host.editor.halfway = "object.move"
        real_snapshot, host.sess.snapshot = host.sess.snapshot, broken
        sent = talia.command("object.move", SHAFT, MOVE)
        unknown = talia.ask(sent)[1]["payload"]
        assert unknown["outcome"] == "unknown" and host.cmds.frozen
        host.editor.halfway = None
        # The changes the host could read went out; the snapshot couldn't yet
        for peer in (talia, lee):
            peer.expect("scene.update")
            peer.assert_quiet()

        # Frozen: every write is refused, on both ports, and nothing is applied
        for peer in (talia, lee, talia):
            receipt = peer.run("object.move", PLATE, MOVE)
            assert_rejected(receipt, "permission_denied")
        assert [a[0] for a in host.editor.applied] == ["object.move"]
        # Asking works while frozen; the unknown receipt says so
        assert lee.query(unknown["request_id"])["receipts"] == [unknown]
        assert host.cmds.frozen

        # The scene can be read again: the host's timer sends everyone the snapshot by itself
        host.sess.snapshot = real_snapshot
        for peer in (talia, lee):
            (snapshot,) = peer.expect("scene.snapshot")
            assert snapshot["payload"]["document"]["revision"] == host.editor.revision
        assert not host.cmds.frozen

        receipt = lee.run("object.move", PLATE, MOVE, base_revision=lee.revision)
        assert receipt["outcome"] == "applied", receipt
        talia.expect("scene.update", "activity")
        # The unknown command is never re-run, whoever repeats it
        assert talia.ask(sent)[1]["payload"] == unknown
        assert [a[0] for a in host.editor.applied] == ["object.move", "object.move"]


# 5. Published only after Blender confirmed it, the same way on both ports


def test_a_refused_command_reaches_nobody_and_an_applied_one_reaches_both_ports_alike():
    with hosting(lan_port=True, client_can_edit=True) as host, host.vr("Talia") as talia, \
            host.lee() as lee:
        talia.expect("session.update")
        host.editor.refusal = ("failed", "Blender can't move Shaft exactly as asked.")
        assert_rejected(lee.run("object.move", SHAFT, MOVE), "failed")
        talia.assert_quiet()
        lee.assert_quiet()
        host.editor.refusal = None

        for sender, watcher in ((lee, talia), (talia, lee)):
            target = {"id": SHAFT, "generation": sender.revision}  # only Shaft changes
            before, result = sender.ask(sender.command("object.move", target, MOVE))
            assert [m["type"] for m in before] == ["scene.update"], before
            assert result["payload"]["outcome"] == "applied"
            update, activity = watcher.expect("scene.update", "activity")
            assert update["payload"] == before[0]["payload"]
            assert activity["payload"] == result["payload"]


# 6. The fake client's shortcut, against the host's own code


def test_the_fake_clients_lose_shortcut_recovers_from_the_real_host(monkeypatch):
    monkeypatch.setattr(fake_client, "RECONNECT_EVERY", 0.1)
    out = []
    with hosting() as host, host.vr("Jihyeon") as other:
        client = fake_client.FakeClient(port=host.srv.port, name="Lee", out=out.append,
                                        check=lambda msg: [] if valid(msg) else ["invalid"])
        client.start()
        try:
            assert client.wait_connected(), out
            other.expect("session.update")
            receipts = client.run("lose move Shaft 10mm 0 0")
            assert fake_client.succeeded(receipts), (receipts, out)
            assert receipts["payload"]["receipts"][0]["request_id"] == client.last_command["id"]
            _, activity, _, _ = other.expect("scene.update", "activity", "session.update",
                                             "session.update")
            assert activity["payload"] == receipts["payload"]["receipts"][0]
            assert client.run("again")["payload"] == activity["payload"]
            assert len(host.editor.applied) == 1
            assert client.violations == 0
        finally:
            client.close()

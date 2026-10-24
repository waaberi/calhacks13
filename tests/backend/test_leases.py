"""Leases of contracts/README.md over real sockets, without Blender.

The host is wired as host.py wires it (session.py, commands.py, leases.py,
server.py), with test_commands.FakeEditor standing in for edits.py; its `links`
stand in for linked data, which test_edits.py checks in Blender. Every message
the host sends is checked against its schema in contracts/schemas.
"""

import copy
import json
import time

import leases
import protocol
import pytest
import session_store
from jsonschema import Draft202012Validator
from test_commands import (
    ADD,
    PLATE,
    SHAFT,
    SKETCH,
    FakeEditor,
    assert_rejected,
    hosting,
    two_peers,
)
from test_contracts import CONTRACTS, REGISTRY, SCHEMAS

pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")

BOLT = "b0170000000000000000000000000001"  # shares its mesh with BOLT_COPY
BOLT_COPY = "b0170000000000000000000000000002"
WASHER = "3a5e0000000000000000000000000003"  # Shaft's child
MOVE = {"by": [0.01, 0, 0]}


def acquire(peer, mode="shared", targets=(), id=None, **fields):
    w = peer.welcome
    payload = {
        "session_id": w["session_id"], "host_epoch": w["host_epoch"],
        "document_id": w["document"]["id"], "open_epoch": w["document"]["open_epoch"],
        "actor_id": w["actor_id"], "mode": mode, "targets": list(targets),
    }
    payload.update(fields)
    msg = protocol.message("lease.acquire", payload)
    if id is not None:
        msg["id"] = id
    return msg


def granted(peer, mode="shared", targets=()):
    """Acquire; the session.update comes first, then lease.granted. Returns the lease."""
    before, reply = peer.ask(acquire(peer, mode, targets))
    assert reply["type"] == "lease.granted", reply
    assert [m["type"] for m in before] == ["session.update"], before
    lease = reply["payload"]["lease"]
    assert lease in before[0]["payload"]["leases"]
    return lease


def refused(peer, msg, code):
    before, reply = peer.ask(msg)
    assert before == [], before
    assert reply["type"] == "error" and reply["payload"]["code"] == code, reply
    return reply["payload"]


def release(peer, lease_id):
    return protocol.message("lease.release", {"lease_id": lease_id})


def released(peer, lease_id):
    """Release; there is no reply, only the session.update everyone gets."""
    peer.send(release(peer, lease_id))
    (update,) = peer.expect("session.update")
    assert lease_id not in [x["lease_id"] for x in update["payload"]["leases"]]


def leases_now(host):
    return host.sess.store.leases()


def linked_editor():
    """Bolt and Bolt.001 share a mesh; Washer is Shaft's child."""
    editor = FakeEditor()
    for oid, name in ((BOLT, "Bolt"), (BOLT_COPY, "Bolt.001"), (WASHER, "Washer")):
        editor.objects[oid] = {"id": oid, "name": name, "generation": 0, "location": [0, 0, 0]}
    editor.links = {BOLT: [BOLT_COPY], BOLT_COPY: [BOLT], SHAFT: [WASHER]}
    return editor


# Granting


def test_a_shared_lease_reaches_everyone_then_the_sender_gets_lease_granted():
    with two_peers() as (host, talia, other):
        msg = acquire(talia, "shared", [SHAFT])
        before, reply = talia.ask(msg)
        assert reply["type"] == "lease.granted" and reply["re"] == msg["id"]
        lease = reply["payload"]["lease"]
        assert lease["mode"] == "shared" and lease["targets"] == [SHAFT]
        assert lease["owner"] == {"actor_id": talia.welcome["actor_id"], "name": "Talia",
                                  "role": "vr"}
        assert abs(lease["acquired_at"] - time.time() * 1000) < 10_000
        (update,) = before
        assert update["type"] == "session.update"
        assert update["payload"]["leases"] == [lease]
        (seen,) = other.expect("session.update")
        assert seen["payload"] == update["payload"]
        assert [p["role"] for p in seen["payload"]["participants"]] == ["host", "vr", "vr"]
        assert leases_now(host) == [lease]
        talia.assert_quiet()
        other.assert_quiet()


def test_overlapping_shared_leases_conflict_and_separate_ones_dont():
    with two_peers() as (_, talia, other):
        lease = granted(talia, "shared", [SHAFT])
        other.expect("session.update")
        error = refused(other, acquire(other, "shared", [PLATE, SHAFT]), "lease_conflict")
        assert error["details"]["lease"] == lease
        assert error["message"] == "Talia is editing this."
        mine = granted(other, "shared", [PLATE])
        assert mine["targets"] == [PLATE]
        talia.expect("session.update")


def test_exclusive_needs_nobody_else_to_hold_a_lease_and_then_blocks_everything():
    with two_peers() as (_, talia, other):
        shared = granted(talia, "shared", [SHAFT])
        other.expect("session.update")
        error = refused(other, acquire(other, "exclusive"), "lease_conflict")
        assert error["details"]["lease"] == shared
        released(talia, shared["lease_id"])
        other.expect("session.update")

        exclusive = granted(talia, "exclusive")
        assert exclusive["targets"] == []
        other.expect("session.update")
        for msg in (acquire(other, "shared", [PLATE]), acquire(other, "exclusive")):
            error = refused(other, msg, "lease_conflict")
            assert error["details"]["lease"] == exclusive
            assert error["message"] == "Talia is editing the whole document."
        for op, target, args in (("object.move", PLATE, MOVE), ("object.add", None, ADD),
                                 ("document.save", None, {}), ("history.undo", None, {})):
            error = assert_rejected(other.run(op, target, args), "lease_conflict")
            assert error["details"]["lease"] == exclusive


def test_a_participants_own_leases_never_conflict():
    with two_peers() as (host, talia, _):
        first = granted(talia, "shared", [SHAFT])
        second = granted(talia, "shared", [SHAFT, PLATE])
        whole = granted(talia, "exclusive")
        again = granted(talia, "shared", [PLATE])
        assert [x["lease_id"] for x in leases_now(host)] == [
            first["lease_id"], second["lease_id"], whole["lease_id"], again["lease_id"]]
        assert talia.run("object.move", SHAFT, MOVE)["outcome"] == "applied"
        assert talia.run("history.undo")["outcome"] == "applied"


def test_a_lease_covers_objects_sharing_the_mesh_and_children():
    with two_peers(editor=linked_editor()) as (_, talia, other):
        bolt = granted(talia, "shared", [BOLT])
        assert bolt["targets"] == [BOLT, BOLT_COPY]  # what was asked first, then linked data
        shaft = granted(talia, "shared", [SHAFT])
        assert shaft["targets"] == [SHAFT, WASHER]
        other.expect("session.update", "session.update")
        error = refused(other, acquire(other, "shared", [BOLT_COPY]), "lease_conflict")
        assert error["details"]["lease"] == bolt
        error = assert_rejected(other.run("object.move", BOLT_COPY, MOVE), "lease_conflict")
        assert error["details"]["lease"] == bolt
        error = assert_rejected(other.run("object.move", WASHER, MOVE), "lease_conflict")
        assert error["details"]["lease"] == shaft
        assert other.run("object.move", PLATE, MOVE)["outcome"] == "applied"


def test_a_command_checks_links_made_after_the_lease_was_granted():
    with two_peers(editor=linked_editor()) as (host, talia, other):
        washer = granted(talia, "shared", [WASHER])
        other.expect("session.update")
        host.editor.links[PLATE] = [WASHER]  # Washer is parented to Base plate meanwhile
        error = assert_rejected(other.run("object.move", PLATE, MOVE), "lease_conflict")
        assert error["details"]["lease"] == washer


def test_a_sketch_is_leased_whole_by_its_id():
    editor = linked_editor()
    editor.objects[SKETCH] = {"id": SKETCH, "name": "Sketch", "generation": 0,
                              "location": [0, 0, 0]}  # the editor knows it, as P3C's will
    with two_peers(editor=editor) as (_, talia, other):
        sketch = granted(talia, "shared", [SKETCH])
        assert sketch["targets"] == [SKETCH]
        other.expect("session.update")
        error = refused(other, acquire(other, "shared", [SKETCH]), "lease_conflict")
        assert error["details"]["lease"] == sketch


# Commands


def test_a_command_without_a_lease_is_refused_on_someone_elses_target():
    with two_peers() as (host, talia, other):
        lease = granted(talia, "shared", [SHAFT])
        other.expect("session.update")
        receipt = other.run("object.move", SHAFT, MOVE)
        error = assert_rejected(receipt, "lease_conflict")
        assert error["details"]["lease"] == lease and error["message"] == "Talia is editing this."
        assert host.editor.applied == []
        talia.assert_quiet()  # no update, no activity


def test_a_command_without_a_lease_holds_nothing_afterwards():
    with two_peers() as (host, talia, other):
        assert talia.run("object.move", SHAFT, MOVE)["outcome"] == "applied"
        other.expect("scene.update", "activity")  # and no session.update
        assert leases_now(host) == []
        receipt = other.run("object.move", {"id": SHAFT, "generation": 1}, MOVE)
        assert receipt["outcome"] == "applied", receipt


def test_someone_elses_shared_lease_doesnt_block_add_or_save():
    with two_peers() as (_, talia, other):
        granted(talia, "shared", [SHAFT])
        other.expect("session.update")
        assert other.run("object.add", args=ADD)["outcome"] == "applied"
        assert other.run("document.save")["outcome"] == "applied"


def test_a_command_with_its_own_lease_is_applied():
    with two_peers() as (_, talia, other):
        lease = granted(talia, "shared", [SHAFT])
        other.expect("session.update")
        receipt = talia.run("object.move", SHAFT, MOVE, lease=lease["lease_id"])
        assert receipt["outcome"] == "applied", receipt
        whole = granted(talia, "exclusive")
        receipt = talia.run("object.move", PLATE, MOVE, lease=whole["lease_id"])
        assert receipt["outcome"] == "applied", receipt
        receipt = talia.run("object.add", args=ADD, lease=lease["lease_id"])
        assert receipt["outcome"] == "applied", receipt


def test_a_commands_lease_must_be_live_its_own_and_cover_the_target():
    with two_peers() as (host, talia, other):
        lease = granted(talia, "shared", [SHAFT])
        other.expect("session.update")
        error = assert_rejected(other.run("object.move", PLATE, MOVE, lease=lease["lease_id"]),
                                "permission_denied")
        assert error["message"] == "That lease is someone else's."
        error = assert_rejected(talia.run("object.move", PLATE, MOVE, lease=lease["lease_id"]),
                                "permission_denied")
        assert "doesn't cover" in error["message"]
        released(talia, lease["lease_id"])
        other.expect("session.update")
        error = assert_rejected(talia.run("object.move", SHAFT, MOVE, lease=lease["lease_id"]),
                                "not_found")
        assert "ended" in error["message"]
        assert host.editor.applied == []


@pytest.mark.parametrize("op", ["history.undo", "history.redo"])
def test_undo_and_redo_are_refused_while_someone_else_holds_any_lease(op):
    with two_peers() as (host, talia, other):
        talia.run("object.move", SHAFT, MOVE)
        other.expect("scene.update", "activity")
        if op == "history.redo":
            talia.run("history.undo")
            other.expect("scene.update", "activity")
        lease = granted(talia, "shared", [PLATE])  # not even what the step changed
        other.expect("session.update")
        error = assert_rejected(other.run(op), "lease_conflict")
        assert error["details"]["lease"] == lease
        assert error["message"] == "Talia is editing, so Undo and Redo wait until they finish."
        assert len(host.editor.applied) == (1 if op == "history.undo" else 2)
        released(talia, lease["lease_id"])
        other.expect("session.update")
        assert other.run(op)["outcome"] == "applied"


def test_the_lease_holder_can_still_undo():
    with two_peers() as (_, talia, other):
        talia.run("object.move", SHAFT, MOVE)
        other.expect("scene.update", "activity")
        granted(talia, "shared", [SHAFT])
        assert talia.run("history.undo")["outcome"] == "applied"


def test_lease_checks_come_after_the_target_and_revision_checks():
    with two_peers() as (_, talia, other):
        granted(talia, "shared", [SHAFT])
        other.expect("session.update")
        receipt = other.run("object.move", {"id": SHAFT, "generation": 9}, MOVE)
        assert_rejected(receipt, "stale_revision")
        assert_rejected(other.run("history.undo", base_revision=7), "stale_revision")


# Releasing and expiry


def test_release_has_no_reply_and_everyone_gets_session_update():
    with two_peers() as (host, talia, other):
        lease = granted(talia, "shared", [SHAFT])
        other.expect("session.update")
        talia.send(release(talia, lease["lease_id"]))
        for peer in (talia, other):
            (update,) = peer.expect("session.update")
            assert update["payload"]["leases"] == []
        talia.assert_quiet()
        assert leases_now(host) == []
        assert other.run("object.move", SHAFT, MOVE)["outcome"] == "applied"


def test_releasing_an_unknown_or_someone_elses_lease_is_refused():
    with two_peers() as (_, talia, other):
        lease = granted(talia, "shared", [SHAFT])
        other.expect("session.update")
        error = refused(other, release(other, lease["lease_id"]), "permission_denied")
        assert error["message"] == "That lease is someone else's."
        refused(talia, release(talia, "0" * 32), "not_found")
        talia.send(release(talia, lease["lease_id"]))
        talia.expect("session.update")
        refused(talia, release(talia, lease["lease_id"]), "not_found")  # once only


def test_a_closed_connection_frees_its_leases_in_one_session_update():
    with two_peers() as (host, talia, other):
        granted(talia, "shared", [SHAFT])
        granted(talia, "exclusive")
        other.expect("session.update", "session.update")
        talia.close()
        (update,) = other.expect("session.update")
        assert update["payload"]["leases"] == []
        assert [p["name"] for p in update["payload"]["participants"]] == ["Host Blender",
                                                                         "Jihyeon"]
        assert leases_now(host) == []
        assert other.run("history.undo")["outcome"] == "rejected"  # nothing to undo, not a lease
        assert other.run("object.move", SHAFT, MOVE)["outcome"] == "applied"


def test_a_silent_owner_loses_its_leases_after_6_seconds():
    """The real heartbeat timeout. On an IO-stalled machine, check /proc/pressure/io and rerun."""
    with two_peers() as (host, talia, other):
        granted(talia, "shared", [SHAFT])
        other.expect("session.update")
        started = time.monotonic()
        other.sock.settimeout(0.5)
        update = None
        while time.monotonic() - started < 10:
            other.send(protocol.message("ping"))  # the watcher keeps talking; Talia doesn't
            try:
                while (msg := other.recv())["type"] == "pong":
                    pass
            except TimeoutError:
                continue
            update = msg
            break
        elapsed = time.monotonic() - started
        assert update is not None and update["type"] == "session.update", update
        assert update["payload"]["leases"] == []
        assert 5.5 < elapsed < 8, elapsed
        assert leases_now(host) == []


def test_a_lease_doesnt_end_during_a_commit():
    with two_peers() as (host, talia, other):
        lease = granted(talia, "shared", [PLATE])
        other.expect("session.update")
        seen = []

        def owner_leaves_mid_commit():
            conn = next(c for c, a in host.sess.participants.items() if a["name"] == "Talia")
            host.sess.left(conn)  # what server.py's drain does when a connection closes
            seen.append([x["lease_id"] for x in leases_now(host)])

        host.editor.during_apply = owner_leaves_mid_commit
        before, result = other.ask(other.command("object.move", SHAFT, MOVE))
        assert result["payload"]["outcome"] == "applied"
        assert seen == [[lease["lease_id"]]], "the lease ended while the commit ran"
        assert leases_now(host) == []
        assert [m["type"] for m in before] == ["scene.update", "session.update"]
        assert before[1]["payload"]["leases"] == []


# Requests


def test_a_repeated_acquire_gets_the_same_lease_and_grants_nothing_new():
    with two_peers() as (host, talia, other):
        msg = acquire(talia, "shared", [SHAFT])
        _, first = talia.ask(msg)
        other.expect("session.update")
        before, second = talia.ask(copy.deepcopy(msg))
        assert before == [] and second["type"] == "lease.granted" and second["re"] == msg["id"]
        assert second["payload"] == first["payload"]
        assert len(leases_now(host)) == 1
        other.assert_quiet()
        changed = copy.deepcopy(msg)
        changed["payload"]["targets"] = [PLATE]
        refused(talia, changed, "duplicate_request")
        assert len(leases_now(host)) == 1


def test_a_repeated_refusal_is_answered_the_same_way():
    with two_peers() as (_, talia, other):
        granted(talia, "shared", [SHAFT])
        other.expect("session.update")
        msg = acquire(other, "shared", [SHAFT])
        first = refused(other, msg, "lease_conflict")
        assert refused(other, copy.deepcopy(msg), "lease_conflict") == first


def test_the_client_role_cant_acquire_while_read_only():
    with hosting(lan_port=True) as host, host.lee() as lee:
        refused(lee, acquire(lee, "shared", [SHAFT]), "permission_denied")
        assert leases_now(host) == []


def test_the_client_role_can_acquire_with_the_test_flag():
    with hosting(lan_port=True, client_can_edit=True) as host, host.lee() as lee:
        lease = granted(lee, "shared", [SHAFT])
        assert lease["owner"]["role"] == "blender-client"


@pytest.mark.parametrize("changes, code", [
    ({"actor_id": "e" * 32}, "permission_denied"),
    ({"session_id": "e" * 32}, "wrong_session"),
    ({"host_epoch": "e" * 32}, "wrong_session"),
    ({"document_id": "e" * 32}, "wrong_document"),
    ({"open_epoch": "e" * 32}, "wrong_document"),
    ({"targets": [SHAFT, "0" * 32]}, "not_found"),
    ({"mode": "exclusive"}, "invalid_message"),  # with targets
    ({"targets": []}, "invalid_message"),  # shared without targets
    ({"targets": [SHAFT, SHAFT]}, "invalid_message"),
    ({"targets": ["SHAFT"]}, "invalid_message"),
    ({"mode": "both"}, "invalid_message"),
    ({"colour": "pink"}, "invalid_message"),
])
def test_a_bad_acquire_is_refused(changes, code):
    with two_peers() as (host, talia, _):
        msg = acquire(talia, "shared", [SHAFT])
        msg["payload"].update(changes)
        error = refused(talia, msg, code)
        if code == "wrong_document":
            assert set(error["details"]["document"]) == {"id", "open_epoch", "name"}
        assert leases_now(host) == []


# The host's own participant and the hook for its desktop edits (#77)


def test_session_update_carries_the_hosts_own_leases():
    with two_peers() as (host, talia, other):
        lease = host.leases.grant(host.sess.host["actor_id"], "shared", [SHAFT])
        assert lease["owner"] == host.sess.host
        for peer in (talia, other):
            (update,) = peer.expect("session.update")
            assert update["payload"]["leases"] == [lease]
        error = assert_rejected(talia.run("object.move", SHAFT, MOVE), "lease_conflict")
        assert error["details"]["lease"]["owner"]["role"] == "host"


def test_lease_owners_follow_a_host_rename():
    with hosting(name="Waaberi") as host, host.vr() as talia:
        host.leases.grant(host.sess.host["actor_id"], "exclusive")
        talia.expect("session.update")
        host.sess.rename_host("Talia's desk")
        (update,) = talia.expect("session.update")
        assert update["payload"]["leases"][0]["owner"]["name"] == "Talia's desk"


def test_may_write_answers_the_host_desktop():
    with two_peers(editor=linked_editor()) as (host, talia, _):
        assert host.leases.may_write([SHAFT]) is None
        assert host.leases.may_write(whole=True) is None
        lease = granted(talia, "shared", [SHAFT])
        assert host.leases.may_write([SHAFT]) == lease
        assert host.leases.may_write([WASHER]) == lease  # linked: Shaft's child
        assert host.leases.may_write([PLATE]) is None
        assert host.leases.may_write() is None  # only an exclusive lease blocks this
        assert host.leases.may_write(whole=True) == lease  # Undo, Redo
        mine = host.leases.grant(host.sess.host["actor_id"], "shared", [PLATE])
        assert host.leases.may_write([PLATE]) is None, "the host's own lease doesn't block it"
        with pytest.raises(session_store.SessionError) as e:
            host.leases.grant(host.sess.host["actor_id"], "shared", [SHAFT])
        assert e.value.code == "lease_conflict" and e.value.details["lease"] == lease
        host.leases.end(mine["lease_id"], host.sess.host["actor_id"])


def test_desktop_reason_names_the_owner_and_what_they_edit():
    owner = {"actor_id": "a" * 32, "name": "Lee", "role": "vr"}
    shared = {"lease_id": "b" * 32, "mode": "shared", "owner": owner, "targets": ["c" * 32]}
    exclusive = {**shared, "mode": "exclusive", "targets": []}
    reason = leases.Leases.desktop_reason
    assert reason(shared, "Cube") == "Lee is editing Cube"
    assert reason(shared) == "Lee is editing"
    assert reason(shared, "Cube", whole=True) == ("Lee is editing Cube, so Undo and Redo wait "
                                                  "until they finish")
    assert reason(exclusive, "Cube") == "Lee is editing — wait for Apply"
    assert reason(exclusive, whole=True) == "Lee is editing — wait for Apply"


# The hand-written schema check


ACQUIRE_CHANGES = [
    {}, {"mode": "exclusive", "targets": []}, {"mode": "exclusive"}, {"targets": []},
    {"targets": ["f" * 32] * 2}, {"targets": [f"{i:032x}" for i in range(64)]},
    {"targets": [f"{i:032x}" for i in range(65)]}, {"targets": "x"}, {"targets": [1]},
    {"mode": None}, {"actor_id": None}, {"actor_id": "A" * 32}, {"extra": 1},
]


@pytest.mark.parametrize("changes", ACQUIRE_CHANGES)
def test_acquire_problem_agrees_with_the_schema(changes):
    msg = protocol.message("lease.acquire", {
        **{k: "a" * 32 for k in ("session_id", "host_epoch", "document_id", "open_epoch",
                                 "actor_id")},
        "mode": "shared", "targets": [SHAFT]})
    for key, value in changes.items():
        if value is None:
            del msg["payload"][key]
        else:
            msg["payload"][key] = value
    schema = Draft202012Validator(SCHEMAS["lease.acquire"], registry=REGISTRY)
    assert (leases.acquire_problem(msg) is None) == schema.is_valid(msg), changes


@pytest.mark.parametrize("payload", [{"lease_id": "a" * 32}, {}, {"lease_id": "x"},
                                     {"lease_id": "a" * 32, "extra": 1}])
def test_release_problem_agrees_with_the_schema(payload):
    msg = protocol.message("lease.release", payload)
    schema = Draft202012Validator(SCHEMAS["lease.release"], registry=REGISTRY)
    assert (leases.release_problem(msg) is None) == schema.is_valid(msg)


def test_the_examples_pass_the_hand_written_checks():
    for name, check in (("lease.acquire", leases.acquire_problem),
                        ("lease.release", leases.release_problem)):
        for path in sorted((CONTRACTS / "examples").glob(f"{name}*.json")):
            assert check(json.loads(path.read_text("utf-8"))) is None, path.name

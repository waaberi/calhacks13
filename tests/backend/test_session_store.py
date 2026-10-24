"""session_store.py: the same behavior from MemoryStore and SpacetimeStore.

Every `store` test runs against MemoryStore, and again against SpacetimeStore when a
SpacetimeDB server is running on SPACETIME_URL (default http://127.0.0.1:3000) and the
`spacetime` CLI can publish spacetime/ to it (run `npm install` in spacetime/ first). The
SpacetimeDB runs publish a fresh database named spatial-modeling-test and are skipped in CI.

  spacetime start --listen-addr 127.0.0.1:3000 &
  pytest tests/backend/test_session_store.py
  BLENDER=/path/to/blender pytest tests/backend/test_session_store.py   # also Blender's Python
"""

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from session_store import MemoryStore, SessionError, SpacetimeStore, StoreUnavailable

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "spacetime"
CHECK = Path(__file__).with_name("spacetime_blender_check.py")
SPACETIME_URL = os.environ.get("SPACETIME_URL", "http://127.0.0.1:3000")
TEST_DB = "spatial-modeling-test"

SCHEMAS = [
    json.loads(p.read_text("utf-8")) for p in (ROOT / "contracts" / "schemas").glob("*.json")
]
REGISTRY = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in SCHEMAS)


def valid(schema_id, payload):
    """Whether `payload` is a valid payload of the message type `schema_id`."""
    msg = {"v": 1, "type": schema_id, "id": uuid.uuid4().hex, "re": uuid.uuid4().hex}
    msg["payload"] = payload
    schema = {"$ref": f"{schema_id}.schema.json"}
    return Draft202012Validator(schema, registry=REGISTRY).is_valid(msg)


def actor(name, role="vr"):
    return {"actor_id": uuid.uuid4().hex, "name": name, "role": role}


def receipt(request_id=None, outcome="applied", who=None, **extra):
    return {
        "request_id": request_id or uuid.uuid4().hex,
        "op": "object.move",
        "target": uuid.uuid4().hex,
        "actor": who or actor("Talia"),
        "source": "voice",
        "outcome": outcome,
        "revision": 7,
        "summary": "Moved Shaft 10 mm along X",
        "at": 1792875603000,
        **extra,
    }


class FakeClock:
    def __init__(self):
        self.now = 1_792_875_600_000

    def __call__(self):
        return self.now

    def advance(self, ms):
        self.now += ms


class Env:
    def __init__(self, store, ttl, advance):
        self.store, self.ttl, self.advance = store, ttl, advance


def server_up():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(SPACETIME_URL + "/v1/ping", timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def spacetime_token(tmp_path_factory):
    """Publish a fresh test database once per run; return the host token's path."""
    if not server_up():
        pytest.skip(f"no SpacetimeDB server at {SPACETIME_URL}")
    cli = shutil.which("spacetime")
    if cli is None:
        pytest.skip("the spacetime CLI isn't on PATH")
    if not (MODULE / "node_modules").is_dir():
        pytest.skip("run `npm install` in spacetime/ first")
    cmd = [cli, "publish", "--no-config", "--server", SPACETIME_URL, "--module-path", str(MODULE)]
    cmd += ["--delete-data=always", "--yes", TEST_DB]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return tmp_path_factory.mktemp("spacetime") / "host-token"


def spacetime_store(token, **kwargs):
    return SpacetimeStore(token, url=SPACETIME_URL, database=TEST_DB, **kwargs)


def clear(store):
    for p in store.participants():
        store.leave(p["actor_id"])


@pytest.fixture(params=["memory", "spacetime"])
def env(request):
    if request.param == "memory":
        clock = FakeClock()
        yield Env(MemoryStore(clock=clock), 6000, clock.advance)
        return
    store = spacetime_store(request.getfixturevalue("spacetime_token"), lease_ttl_ms=1500)
    clear(store)
    yield Env(store, 1500, lambda ms: time.sleep(ms / 1000))
    clear(store)


@pytest.fixture
def store(env):
    return env.store


@pytest.fixture
def talia(store):
    a = actor("Talia", "vr")
    store.join(a)
    return a


@pytest.fixture
def lee(store):
    a = actor("Lee Jae-yeon", "blender-client")
    store.join(a)
    return a


def code_of(call, *args):
    with pytest.raises(SessionError) as e:
        call(*args)
    return e.value.code


# Participants


def by_id(actors):
    return sorted(actors, key=lambda a: a["actor_id"])


def test_join_lists_participants(store):
    host, talia = actor("Host Blender", "host"), actor("Talia")
    store.join(host)
    store.join(talia)
    assert by_id(store.participants()) == by_id([host, talia])
    store.join({**host, "name": "Talia's Blender"})  # joining again updates
    assert by_id(store.participants()) == by_id([{**host, "name": "Talia's Blender"}, talia])
    assert valid("session.update", store.session())


@pytest.mark.parametrize(
    "change", [{"actor_id": "not-hex"}, {"role": "admin"}, {"name": ""}, {"name": "x" * 257}]
)
def test_join_rejects_bad_actors(store, change):
    assert code_of(store.join, {**actor("Talia"), **change}) == "invalid_message"
    assert store.participants() == []


def test_leave_removes_the_participant_and_its_leases(store, talia, lee):
    store.acquire(talia["actor_id"], "shared", [uuid.uuid4().hex])
    store.leave(talia["actor_id"])
    store.leave(talia["actor_id"])  # leaving twice is fine
    assert store.session() == {"participants": [lee], "leases": []}


# Leases


def test_acquire_returns_the_contract_lease(store, talia):
    target = uuid.uuid4().hex
    lease = store.acquire(talia["actor_id"], "shared", [target])
    assert lease["owner"] == talia
    assert lease["mode"] == "shared"
    assert lease["targets"] == [target]
    assert isinstance(lease["acquired_at"], int)
    assert valid("lease.granted", {"lease": lease})
    assert store.leases() == [lease]
    assert valid("session.update", store.session())


def test_second_acquire_of_the_same_target_is_rejected(store, talia, lee):
    target = uuid.uuid4().hex
    first = store.acquire(talia["actor_id"], "shared", [target, uuid.uuid4().hex])
    with pytest.raises(SessionError) as e:
        store.acquire(lee["actor_id"], "shared", [uuid.uuid4().hex, target])
    assert e.value.code == "lease_conflict"
    assert e.value.details == {"lease": first}
    assert "Talia" in e.value.message
    assert valid("error", e.value.error())
    assert store.leases() == [first]


def test_own_leases_never_conflict(store, talia):
    target = uuid.uuid4().hex
    store.acquire(talia["actor_id"], "shared", [target])
    store.acquire(talia["actor_id"], "shared", [target])
    store.acquire(talia["actor_id"], "exclusive", [])
    assert len(store.leases()) == 3


def test_disjoint_shared_leases_coexist(store, talia, lee):
    store.acquire(talia["actor_id"], "shared", [uuid.uuid4().hex])
    store.acquire(lee["actor_id"], "shared", [uuid.uuid4().hex])
    assert by_id(x["owner"] for x in store.leases()) == by_id([talia, lee])


def test_exclusive_and_shared_block_each_other(store, talia, lee):
    shared = store.acquire(talia["actor_id"], "shared", [uuid.uuid4().hex])
    assert code_of(store.acquire, lee["actor_id"], "exclusive", []) == "lease_conflict"
    store.release(shared["lease_id"], talia["actor_id"])
    store.acquire(lee["actor_id"], "exclusive", [])
    assert (
        code_of(store.acquire, talia["actor_id"], "shared", [uuid.uuid4().hex]) == "lease_conflict"
    )


@pytest.mark.parametrize(
    ("mode", "targets"),
    [
        ("exclusive", ["fd7bd4ddae444528a4fedbc562fe018b"]),
        ("shared", []),
        ("shared", ["fd7bd4ddae444528a4fedbc562fe018b"] * 2),
        ("shared", ["not-an-id"]),
        ("owned", []),
    ],
)
def test_acquire_rejects_bad_requests(store, talia, mode, targets):
    assert code_of(store.acquire, talia["actor_id"], mode, targets) == "invalid_message"
    assert store.leases() == []


def test_acquire_needs_a_participant(store):
    assert code_of(store.acquire, uuid.uuid4().hex, "exclusive", []) == "not_found"


def test_acquire_rejects_a_reused_lease_id(store, talia):
    lease = store.acquire(talia["actor_id"], "exclusive", [])
    code = code_of(store.acquire, talia["actor_id"], "exclusive", [], lease["lease_id"])
    assert code == "duplicate_request"


def test_release_checks_the_owner(store, talia, lee):
    lease = store.acquire(talia["actor_id"], "shared", [uuid.uuid4().hex])
    assert code_of(store.release, lease["lease_id"], lee["actor_id"]) == "permission_denied"
    store.release(lease["lease_id"], talia["actor_id"])
    assert store.leases() == []
    assert code_of(store.release, lease["lease_id"], talia["actor_id"]) == "not_found"


def test_unrenewed_leases_expire(env, talia, lee):
    store, target = env.store, uuid.uuid4().hex
    old = store.acquire(talia["actor_id"], "shared", [target])
    env.advance(env.ttl + 300)
    assert store.leases() == []  # not live any more, even before expire() runs
    assert code_of(store.release, old["lease_id"], talia["actor_id"]) == "not_found"
    new = store.acquire(lee["actor_id"], "shared", [target])
    store.expire()
    assert store.leases() == [new]


def test_renew_keeps_leases_alive(env, talia):
    store = env.store
    lease = store.acquire(talia["actor_id"], "exclusive", [])
    for _ in range(3):
        env.advance(env.ttl * 2 // 3)
        store.renew(talia["actor_id"])
    store.expire()
    assert store.leases() == [lease]
    assert code_of(store.renew, uuid.uuid4().hex) == "not_found"


def test_conflict_checks_commands_without_a_lease(store, talia, lee):
    target, other = uuid.uuid4().hex, uuid.uuid4().hex
    lease = store.acquire(talia["actor_id"], "shared", [target])
    assert store.conflict(lee["actor_id"], "shared", [target]) == lease
    assert store.conflict(lee["actor_id"], "shared", [other]) is None
    assert store.conflict(lee["actor_id"], "exclusive", []) == lease  # Undo/Redo
    assert store.conflict(talia["actor_id"], "exclusive", []) is None


# Receipts


def test_receipts_are_found_by_request_id(store):
    a, b = receipt(), receipt(outcome="rejected", error={"code": "stale_revision", "message": "x"})
    store.record_receipt(a, "digest-a")
    store.record_receipt(b, "digest-b")
    unknown = uuid.uuid4().hex
    found, missing = store.receipts([b["request_id"], unknown, a["request_id"]])
    assert found == [b, a]
    assert missing == [unknown]
    assert valid("receipts", {"receipts": found, "missing": missing, "unknown": []})


def test_a_pending_receipt_is_completed_and_then_final(store):
    pending = receipt(outcome="pending")
    pending.pop("summary")
    store.record_receipt(pending, "d")
    done = {**pending, "outcome": "applied", "revision": 8, "summary": "Moved Shaft"}
    store.record_receipt(done, "d")
    store.record_receipt(done, "d")  # recording the same receipt again changes nothing
    assert store.receipts([done["request_id"]]) == ([done], [])
    changed = {**done, "revision": 9}
    assert code_of(store.record_receipt, changed, "d") == "duplicate_request"
    assert store.receipts([done["request_id"]]) == ([done], [])


def test_replay_compares_the_request_digest(store):
    r = receipt()
    store.record_receipt(r, "same payload")
    assert store.replay(r["request_id"], "same payload") == r
    assert code_of(store.replay, r["request_id"], "other payload") == "duplicate_request"
    assert store.replay(uuid.uuid4().hex, "anything") is None


def test_record_receipt_rejects_bad_receipts(store):
    assert code_of(store.record_receipt, receipt(request_id="nope")) == "invalid_message"
    assert code_of(store.record_receipt, receipt(outcome="done")) == "invalid_message"


# SpacetimeDB only


def test_spacetime_state_survives_a_new_host_process(spacetime_token):
    """What a Blender restart does to the store: a new SpacetimeStore with the same token."""
    first = spacetime_store(spacetime_token, lease_ttl_ms=60_000)
    clear(first)
    talia, lee = actor("Talia"), actor("Lee Jae-yeon", "blender-client")
    first.join(talia)
    first.join(lee)
    target = uuid.uuid4().hex
    lease = first.acquire(talia["actor_id"], "shared", [target])
    r = receipt(who=talia)
    first.record_receipt(r, "d")
    del first

    second = spacetime_store(spacetime_token, lease_ttl_ms=60_000)
    try:
        assert second.leases() == [lease]
        assert second.receipts([r["request_id"]]) == ([r], [])
        assert code_of(second.acquire, lee["actor_id"], "shared", [target]) == "lease_conflict"
    finally:
        clear(second)


def test_spacetime_accepts_writes_only_from_the_host(spacetime_token, tmp_path):
    spacetime_store(spacetime_token)  # the host has claimed the database
    with pytest.raises(SessionError) as e:
        spacetime_store(tmp_path / "someone-else")
    assert e.value.code == "permission_denied"


def test_spacetime_store_reports_an_unreachable_server(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # closed again before the store connects
    with pytest.raises(StoreUnavailable) as e:
        SpacetimeStore(tmp_path / "token", url=f"http://127.0.0.1:{port}", timeout=1)
    assert e.value.status is None
    assert not (tmp_path / "token").exists()


@pytest.mark.skipif(not os.environ.get("BLENDER"), reason="set BLENDER=/path/to/blender")
def test_spacetime_from_blenders_own_python(spacetime_token, tmp_path):
    """Pass criteria 3 and 4 in real Blender: acquire, reject, quit, start again, still there."""
    spacetime_store(spacetime_token)
    env = {**os.environ, "BLENDER_USER_RESOURCES": str(tmp_path / "blender")}
    for phase in ("first", "second"):
        cmd = [os.environ["BLENDER"], "--background", "--factory-startup", "--python", str(CHECK)]
        cmd += [
            "--",
            phase,
            str(spacetime_token),
            SPACETIME_URL,
            TEST_DB,
            str(tmp_path / "state.json"),
        ]
        result = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=180, check=False
        )
        assert result.returncode == 0, result.stdout + result.stderr

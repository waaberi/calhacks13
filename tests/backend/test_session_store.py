"""session_store.py: the same behavior from MemoryStore, MirroredStore and SpacetimeStore.

Every `store` test runs against MemoryStore and MirroredStore (with no server), and again
against SpacetimeStore when a
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
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from session_store import (
    MemoryStore,
    MirroredStore,
    SessionError,
    SpacetimeStore,
    StoreUnavailable,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "spacetime"
CHECK = Path(__file__).with_name("spacetime_blender_check.py")
HOST_CHECK = Path(__file__).with_name("spacetime_host_check.py")
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


def no_server():
    raise StoreUnavailable("no server in this test")


@pytest.fixture(params=["memory", "mirrored", "spacetime"])
def env(request):
    if request.param == "memory":
        clock = FakeClock()
        yield Env(MemoryStore(clock=clock), 6000, clock.advance)
        return
    if request.param == "mirrored":
        clock = FakeClock()
        store = MirroredStore(no_server, memory=MemoryStore(clock=clock), retry_s=60)
        yield Env(store, 6000, clock.advance)
        store.close()
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


# MirroredStore: SpacetimeDB decides lease requests on a thread, memory holds the result


class FakeRemote:
    """Records the reducer calls MirroredStore makes; starts with an earlier host's rows."""

    url = "http://fake"

    def __init__(self, participants=(), leases=(), reject=()):
        self.calls = []
        self.rows = {"participant": list(participants), "lease": list(leases)}
        self.reject = dict.fromkeys(reject, "disagrees") if not isinstance(reject, dict) else reject
        self.down = False

    def call(self, reducer, args=None):
        if self.down:
            raise StoreUnavailable("down")
        self.calls.append((reducer, args))
        if reducer in self.reject:
            code, _, text = self.reject[reducer].rpartition(":")
            raise SessionError(code or "lease_conflict", text)

    def select(self, sql):
        if self.down:
            raise StoreUnavailable("down")
        return self.rows["participant" if "participant" in sql else "lease"]


def mirrored(remote, **kwargs):
    store = MirroredStore(lambda: remote, retry_s=0.05, **kwargs)
    assert store.wait_idle(5)
    return store


def reducers(remote, *names):
    return [(r, a) for r, a in remote.calls if r in names]


def test_mirror_never_waits_for_spacetimedb():
    def slow():
        time.sleep(3)
        raise StoreUnavailable("slow")

    store = MirroredStore(slow)
    try:
        a, b = actor("Talia"), actor("Lee", "blender-client")
        start = time.monotonic()
        store.join(a)
        store.join(b)
        target = uuid.uuid4().hex
        store.acquire(a["actor_id"], "shared", [target])
        assert code_of(store.acquire, b["actor_id"], "shared", [target]) == "lease_conflict"
        assert [x["owner"]["name"] for x in store.leases()] == ["Talia"]
        assert time.monotonic() - start < 0.2
    finally:
        store.close()


def test_mirror_clears_an_earlier_host_then_copies_in_order():
    old = uuid.uuid4().hex
    remote = FakeRemote(participants=[{"actor_id": old}], leases=[{"owner_id": old}])
    store = mirrored(remote)
    try:
        assert remote.calls[0] == ("leave", {"actor_id": old})
        a, b = actor("Talia"), actor("Lee", "blender-client")
        store.join(a)
        store.join(b)
        target = uuid.uuid4().hex
        lease = store.acquire(a["actor_id"], "shared", [target])
        assert store.wait_idle(5)
        assert reducers(remote, "join") == [("join", a), ("join", b)]
        assert reducers(remote, "acquire") == [("acquire", {
            "lease_id": lease["lease_id"], "owner_id": a["actor_id"], "mode": "shared",
            "targets": [target], "ttl_ms": 6000})]
        remote.calls.clear()
        store.release(lease["lease_id"], a["actor_id"])
        store.acquire(b["actor_id"], "shared", [target])
        store.leave(a["actor_id"])
        assert store.wait_idle(5)
        names = [r for r, _ in remote.calls if r != "renew"]
        # Talia's lease ends there (released, or with her leave) before Lee's is acquired.
        assert names.count("acquire") == 1 and "leave" in names, names
        assert min(names.index(r) for r in ("release", "leave") if r in names) < names.index(
            "acquire"), names
    finally:
        store.close()


def test_mirror_copies_a_join_that_arrived_during_a_push_before_deciding():
    # On Maincloud each call takes ~300 ms, so a client can join and ask while a push runs.
    class SlowJoin(FakeRemote):
        def __init__(self):
            super().__init__()
            self.joined, self.blocking, self.unblock = set(), threading.Event(), threading.Event()
            self.out_of_step = []

        def call(self, reducer, args=None):
            if reducer == "join" and not self.blocking.is_set():
                self.blocking.set()
                self.unblock.wait(5)
            if reducer == "join":
                self.joined.add(args["actor_id"])
            if reducer == "acquire" and args["owner_id"] not in self.joined:
                self.out_of_step.append(args["owner_id"])
                raise SessionError("not_found", f"no participant {args['owner_id']}")
            super().call(reducer, args)

    remote = SlowJoin()
    store = mirrored(remote)
    try:
        a, b = actor("Talia"), actor("Lee", "blender-client")
        store.join(a)
        assert remote.blocking.wait(5)  # the thread is copying Talia's join
        store.join(b)
        decided = []
        store.acquire_async(b["actor_id"], "shared", [uuid.uuid4().hex],
                            lambda lease, error: decided.append((lease, error)))
        remote.unblock.set()
        assert store.wait_idle(5)
        store.poll()
        assert len(decided) == 1 and decided[0][1] is None, decided
        assert remote.out_of_step == []  # SpacetimeDB decided it; memory didn't have to
    finally:
        store.close()


def test_mirror_releases_before_an_overlapping_acquire():
    remote = FakeRemote()
    store = mirrored(remote)
    try:
        a, b = actor("Talia"), actor("Lee", "blender-client")
        store.join(a)
        store.join(b)
        assert store.wait_idle(5)
        first = store.acquire(a["actor_id"], "exclusive", [])
        store.release(first["lease_id"], a["actor_id"])
        store.acquire(b["actor_id"], "exclusive", [])
        assert store.wait_idle(5)
        writes = [r for r, _ in remote.calls if r in ("release", "acquire")]
        assert writes in (["acquire"], ["acquire", "release", "acquire"])
    finally:
        store.close()


def test_mirror_recopies_everything_after_spacetimedb_comes_back():
    remote = FakeRemote()
    store = mirrored(remote)
    try:
        a = actor("Talia")
        store.join(a)
        assert store.wait_idle(5)
        remote.down = True
        lease = store.acquire(a["actor_id"], "exclusive", [])  # memory still decides
        time.sleep(0.2)
        assert store.status.startswith("Not using SpacetimeDB")
        remote.calls.clear()
        remote.rows["participant"] = [{"actor_id": a["actor_id"]}]
        remote.down = False
        assert store.wait_idle(5)
        assert remote.calls[0] == ("leave", {"actor_id": a["actor_id"]})
        assert ("join", a) in remote.calls
        assert ("acquire", {"lease_id": lease["lease_id"], "owner_id": a["actor_id"],
                            "mode": "exclusive", "targets": [], "ttl_ms": 6000}) in remote.calls
        assert store.status.startswith("SpacetimeDB decides")
    finally:
        store.close()


def test_mirror_logs_a_rejection_and_carries_on():
    remote = FakeRemote(reject={"acquire"})
    store = mirrored(remote)
    try:
        a = actor("Talia")
        store.join(a)
        store.acquire(a["actor_id"], "exclusive", [])
        assert store.wait_idle(5)
        assert store.status.startswith("SpacetimeDB decides")
        assert [x["owner"]["name"] for x in store.leases()] == ["Talia"]
    finally:
        store.close()


def test_mirror_renews_and_leaves_on_close():
    remote = FakeRemote()
    store = MirroredStore(lambda: remote, renew_s=0.05)
    a = actor("Talia")
    store.join(a)
    time.sleep(0.3)
    assert len(reducers(remote, "renew")) >= 2
    store.close()
    store._thread.join(2)
    assert remote.calls[-1] == ("leave", {"actor_id": a["actor_id"]})


def test_mirror_copies_to_a_real_server(spacetime_token):
    host = spacetime_store(spacetime_token)
    clear(host)
    store = MirroredStore(lambda: spacetime_store(spacetime_token))
    try:
        a, b = actor("Talia"), actor("Lee", "blender-client")
        store.join(a)
        store.join(b)
        target = uuid.uuid4().hex
        lease = store.acquire(a["actor_id"], "shared", [target])
        assert code_of(store.acquire, b["actor_id"], "shared", [target]) == "lease_conflict"
        assert store.wait_idle(5)
        rows = host.select("SELECT * FROM lease")
        assert [(r["lease_id"], r["owner_id"]) for r in rows] == [
            (lease["lease_id"], a["actor_id"])]
        # The module agrees: Lee can't take the same object there either.
        assert code_of(host.acquire, b["actor_id"], "shared", [target]) == "lease_conflict"
        store.release(lease["lease_id"], a["actor_id"])
        assert store.wait_idle(5)
        assert host.select("SELECT * FROM lease") == []
    finally:
        store.close()
        store._thread.join(5)
    assert host.select("SELECT * FROM participant") == []


def test_host_addon_copies_leases_to_spacetimedb(spacetime_token, tmp_path):
    """The add-on in Blender, with its own database so its host identity can claim it."""
    blender = os.environ.get("BLENDER")
    if not blender:
        pytest.skip("set BLENDER to run the add-on in Blender")
    database = "spatial-modeling-host-test"
    cmd = [shutil.which("spacetime"), "publish", "--no-config", "--server", SPACETIME_URL,
           "--module-path", str(MODULE), "--delete-data=always", "--yes", database]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    env = dict(os.environ, BLENDER_USER_RESOURCES=str(tmp_path))
    cmd = [blender, "-b", "--factory-startup", "--python", str(HOST_CHECK), "--",
           SPACETIME_URL, database]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env,
                            check=False)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]


class Decisions:
    """A done callback for acquire_async that records what it was called with."""

    def __init__(self):
        self.got = []

    def __call__(self, lease, error):
        self.got.append((lease, error))


def test_without_a_server_memory_decides_at_once():
    store = MirroredStore(no_server, retry_s=60)
    try:
        a = actor("Talia")
        store.join(a)
        done = Decisions()
        store.acquire_async(a["actor_id"], "exclusive", [], done)
        assert len(done.got) == 1 and done.got[0][1] is None
    finally:
        store.close()


def test_spacetimedb_decides_a_lease_request():
    remote = FakeRemote()
    store = mirrored(remote)
    try:
        a = actor("Talia")
        store.join(a)
        assert store.wait_idle(5) and store.deciding
        target = uuid.uuid4().hex
        done = Decisions()
        store.acquire_async(a["actor_id"], "shared", [target], done, names={target: "Cube"})
        assert done.got == [] and store.leases() == []  # nothing until SpacetimeDB answers
        assert store.wait_idle(5)
        store.poll()
        [(lease, error)] = done.got
        assert error is None and lease["targets"] == [target]
        assert store.leases() == [lease]
        assert ("set_labels", {"ids": [target], "names": ["Cube"]}) in remote.calls
        assert reducers(remote, "acquire") == [("acquire", {
            "lease_id": lease["lease_id"], "owner_id": a["actor_id"], "mode": "shared",
            "targets": [target], "ttl_ms": 6000})]  # asked once, not copied again
    finally:
        store.close()


def test_a_refusal_from_spacetimedb_is_the_answer_and_is_noted():
    blocking = uuid.uuid4().hex
    remote = FakeRemote(reject={"acquire": blocking})
    store = mirrored(remote)
    try:
        a = actor("Lee", "blender-client")
        store.join(a)
        assert store.wait_idle(5)
        target = uuid.uuid4().hex
        done = Decisions()
        store.acquire_async(a["actor_id"], "shared", [target], done)
        assert store.wait_idle(5)
        store.poll()
        [(lease, error)] = done.got
        assert lease is None and error.code == "lease_conflict"
        assert store.leases() == []  # memory had no lease: SpacetimeDB decided
        assert ("note_refusal", {"actor_id": a["actor_id"], "blocking_lease_id": blocking,
                                 "targets": [target]}) in remote.calls
    finally:
        store.close()


def test_memory_decides_when_spacetimedb_fails_midway():
    remote = FakeRemote()
    store = mirrored(remote)
    try:
        a = actor("Talia")
        store.join(a)
        assert store.wait_idle(5)
        remote.down = True
        done = Decisions()
        store.acquire_async(a["actor_id"], "exclusive", [], done)
        deadline = time.monotonic() + 5
        while not done.got and time.monotonic() < deadline:
            time.sleep(0.01)
            store.poll()
        [(lease, error)] = done.got
        assert error is None and store.leases() == [lease]
        assert not store.deciding
    finally:
        store.close()


def test_spacetimedb_decides_against_a_real_server(spacetime_token):
    """A lease only SpacetimeDB holds (memory doesn't know it) refuses the request."""
    host = spacetime_store(spacetime_token)
    clear(host)
    store = MirroredStore(lambda: spacetime_store(spacetime_token))
    try:
        a, b = actor("Talia"), actor("Lee", "blender-client")
        store.join(a)
        store.join(b)
        assert store.wait_idle(5) and store.deciding
        target = uuid.uuid4().hex
        hidden = host.acquire(a["actor_id"], "shared", [target])  # straight into SpacetimeDB
        assert store.leases() == []
        done = Decisions()
        store.acquire_async(b["actor_id"], "shared", [target], done, names={target: "Cube"})
        assert store.wait_idle(5)
        store.poll()
        [(lease, error)] = done.got
        assert lease is None and error.code == "lease_conflict", done.got
        [row] = host.select("SELECT * FROM refusal")[-1:]
        assert (row["actor_id"], row["blocking_lease_id"]) == (b["actor_id"], hidden["lease_id"])
        assert {r["object_id"]: r["name"] for r in host.select("SELECT * FROM label")}[
            target] == "Cube"
        host.release(hidden["lease_id"], a["actor_id"])
        done = Decisions()
        store.acquire_async(b["actor_id"], "shared", [target], done)
        assert store.wait_idle(5)
        store.poll()
        [(lease, error)] = done.got
        assert error is None and store.leases() == [lease]
        assert [r["lease_id"] for r in host.select("SELECT * FROM lease")] == [lease["lease_id"]]
    finally:
        store.close()
        store._thread.join(5)


def test_memory_decides_when_spacetimedb_is_out_of_step():
    remote = FakeRemote(reject={"acquire": "not_found:no participant"})
    store = mirrored(remote)
    try:
        a = actor("Talia")
        store.join(a)
        assert store.wait_idle(5)
        done = Decisions()
        store.acquire_async(a["actor_id"], "exclusive", [], done)
        deadline = time.monotonic() + 5
        while not done.got and time.monotonic() < deadline:
            time.sleep(0.01)
            store.poll()
        [(lease, error)] = done.got  # granted by memory, not refused with not_found
        assert error is None and store.leases() == [lease]
        assert "out of step" in store.status
    finally:
        store.close()

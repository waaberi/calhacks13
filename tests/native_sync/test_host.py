"""Production NativeHost admission and async receipts, with isolated native I/O."""
import hashlib
import importlib
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

ADDON = Path(__file__).resolve().parents[2] / "blender_addon/spatial_modeling"
PACKAGE = "native_service_test_addon"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ADDON)]
    sys.modules[PACKAGE] = package
HOST_MODULE = importlib.import_module(PACKAGE + ".native_sync.host")
WIRE = importlib.import_module(PACKAGE + ".native_sync.wire")
SID, EPOCH, DOC, OPEN, ACTOR, LEASE, SCENE = (str(i) * 32 for i in range(1, 8))
RID = "a" * 32
MANIFEST = {SCENE: {"group": "scenes", "name": "Native Scene"}}
CANDIDATE = b"BLENDER-original-file-from-client"


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Connection:
    can_edit = True
    closing = False

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


class Native:
    def __init__(self):
        self.data = b"BLENDER-host-original-baseline"
        self.idle = True
        self.applies = []

    def is_idle(self):
        return self.idle

    def capture(self, path):
        path.write_bytes(self.data)
        return types.SimpleNamespace(data=self.data, sha256=digest(self.data),
                                     manifest=MANIFEST, active_scene_uuid=SCENE)

    def apply(self, path, manifest, on_done, on_error, active_scene_uuid=None):
        self.applies.append((path.read_bytes(), manifest, active_scene_uuid))
        self.done, self.failed = on_done, on_error


class Session:
    session_id, host_epoch = SID, EPOCH

    def __init__(self, conn):
        self.participants = {conn: {"actor_id": ACTOR, "role": "blender-client"}}
        self.leases = [{"lease_id": LEASE, "owner": {"actor_id": ACTOR}, "mode": "exclusive"}]
        self.store = types.SimpleNamespace(leases=lambda: self.leases)
        self.committing = 0

    def document(self):
        return {"id": DOC, "open_epoch": OPEN}

    @contextmanager
    def commit(self):
        self.committing += 1
        try:
            yield
        finally:
            self.committing -= 1


@pytest.fixture
def fixture():
    conn, native = Connection(), Native()
    session = Session(conn)
    calls = {"store": 0, "edited": 0, "flush": 0}

    def counted(name):
        calls[name] += 1

    document = types.SimpleNamespace(store=lambda: counted("store"), edited=lambda: counted("edited"))
    sync = types.SimpleNamespace(flush=lambda: counted("flush"))
    host = HOST_MODULE.NativeHost(session, document, sync, native_document=native)
    host._hooks = lambda: None
    srv = types.SimpleNamespace(handlers={}, on_disconnect=None)
    host.attach(srv)
    host._capture()
    try:
        yield types.SimpleNamespace(host=host, native=native, session=session, conn=conn,
                                     srv=srv, calls=calls)
    finally:
        host.folder.cleanup()


def identity(f):
    return {**f.host.head(), "actor_id": ACTOR, "lease_id": LEASE}


def call(f, kind, payload, conn=None):
    return f.srv.handlers[kind]({"id": "f" * 32, "payload": payload}, conn or f.conn)


def begin(f, **changes):
    payload = {**identity(f), "request_id": RID, "base_revision": f.host.state.revision,
               "base_hash": f.host.state.checkpoint_hash, "content_hash": digest(CANDIDATE),
               "total_bytes": len(CANDIDATE), "chunk_count": 1,
               "manifest": MANIFEST, "active_scene_uuid": SCENE}
    payload.update(changes)
    return payload, call(f, "native.begin", payload)


def upload(f):
    payload, result = begin(f)
    assert result["payload"]["outcome"] == "pending"
    chunk = {**identity(f), "request_id": RID, "index": 0,
             "data": WIRE.encode_chunk(CANDIDATE)}
    assert call(f, "native.chunk", chunk) is None
    return payload, {**identity(f), "request_id": RID}


@pytest.mark.parametrize(("key", "wrong", "code"), [
    ("session_id", "e" * 32, "wrong_session"),
    ("host_epoch", "e" * 32, "wrong_session"),
    ("document_id", "e" * 32, "wrong_document"),
    ("open_epoch", "e" * 32, "wrong_document"),
    ("actor_id", "e" * 32, "wrong_actor"),
    ("lease_id", "e" * 32, "lease_conflict"),
])
def test_wire_claims_cannot_substitute_live_connection_identity(fixture, key, wrong, code):
    f = fixture
    _, reply = begin(f, **{key: wrong})
    assert reply["payload"]["code"] == code
    assert f.host.state.pending is None and not f.native.applies


def test_joined_connection_permission_is_checked_before_native_bytes(fixture):
    f = fixture
    f.conn.can_edit = False
    _, reply = begin(f)
    assert reply["payload"]["code"] == "permission_denied"
    stranger = Connection()
    reply = call(f, "native.get", {}, stranger)
    assert reply["payload"]["code"] == "permission_denied"
    assert not f.native.applies


def test_queued_begin_from_a_connection_already_closing_cannot_mutate(fixture):
    f = fixture
    f.conn.closing = True
    _, reply = begin(f)
    assert reply["payload"]["outcome"] == "rejected"
    assert reply["payload"]["code"] in {"disconnected", "permission_denied"}
    assert f.host.state.pending is None and not f.native.applies


def test_immediate_hidden_native_host_change_invalidates_commit_cas(fixture):
    f = fixture
    _, payload = upload(f)
    f.native.data = b"BLENDER-host-material-or-rig-changed-without-viewport-update"
    reply = call(f, "native.commit", payload)
    assert reply["payload"]["code"] == "stale_revision"
    assert f.host.state.revision == 1 and not f.native.applies


def test_lost_lease_during_upload_never_applies(fixture):
    f = fixture
    begin(f)
    f.session.leases.clear()
    chunk = {**identity(f), "request_id": RID, "index": 0, "data": WIRE.encode_chunk(CANDIDATE)}
    reply = call(f, "native.chunk", chunk)
    assert reply["payload"]["code"] == "lease_conflict"
    reply = call(f, "native.commit", {**identity(f), "request_id": RID})
    assert reply["payload"]["code"] == "lease_conflict"
    assert not f.native.applies


def test_native_ack_uses_verified_host_hash_and_duplicate_begin_is_receipt_only(fixture):
    f = fixture
    original, payload = upload(f)
    assert call(f, "native.commit", payload) is None
    assert f.host.busy and f.session.committing == 1
    assert f.native.applies == [(CANDIDATE, MANIFEST, SCENE)]
    assert not any(m["payload"].get("outcome") == "applied" for m in f.conn.sent)
    f.native.data = b"BLENDER-local-re-export-has-its-own-native-process-data"
    f.native.done({"verified": True})
    receipt = f.conn.sent[-1]["payload"]
    assert receipt["outcome"] == "applied" and receipt["revision"] == 1
    assert receipt["checkpoint_hash"] == digest(f.native.data) != digest(CANDIDATE)
    assert not f.host.busy and f.session.committing == 0
    assert call(f, "native.begin", original)["payload"] == receipt
    assert len(f.native.applies) == 1


def test_async_busy_blocks_snapshot_and_second_commit_until_completion(fixture):
    f = fixture
    _, payload = upload(f)
    call(f, "native.commit", payload)
    assert call(f, "native.get", {})["payload"]["code"] == "native_busy"
    assert call(f, "native.commit", payload)["payload"]["code"] == "native_busy"
    assert begin(f)[1]["payload"]["code"] == "busy"
    assert f.session.committing == 1 and len(f.native.applies) == 1
    f.native.failed(RuntimeError("native replacement failed"))
    assert not f.host.busy and f.session.committing == 0
    assert f.conn.sent[-1]["payload"]["outcome"] == "unknown"


def test_permission_revocation_before_native_ack_cannot_report_applied(fixture):
    f = fixture
    _, payload = upload(f)
    call(f, "native.commit", payload)
    f.native.data = b"BLENDER-changed-but-permission-ended"
    f.conn.can_edit = False
    f.native.done()
    assert f.conn.sent[-1]["payload"]["outcome"] == "unknown"
    assert f.session.committing == 0 and not f.host.busy


def test_native_snapshot_stream_uses_matching_head_and_original_bytes(fixture):
    f = fixture
    assert call(f, "native.get", {}) is None
    for _ in range(5):
        f.host.poll()
    receiver = WIRE.ChunkReceiver()
    completed = None
    for message in f.conn.sent:
        if message["type"] == "native.snapshot":
            completed = receiver.feed(message["payload"]) or completed
    assert completed["data"] == f.native.data
    assert completed["head"]["checkpoint_hash"] == digest(f.native.data)


@pytest.mark.parametrize("completion", ["done", "failed"])
def test_disconnect_during_native_apply_finishes_guard_and_keeps_unknown(fixture, completion):
    f = fixture
    _, payload = upload(f)
    call(f, "native.commit", payload)
    f.srv.on_disconnect(f.conn)
    # Production Session.left removes the participant after the NativeHost hook;
    # complete that removal in the isolated session model.
    f.session.participants.pop(f.conn)
    f.conn.closing = True
    getattr(f.native, completion)(RuntimeError("connection ended"))
    assert not f.host.busy and f.session.committing == 0
    assert f.host.state._receipts[RID].outcome == "unknown"
    assert len(f.native.applies) == 1


def test_duplicate_transfer_id_cannot_replace_native_manifest(fixture):
    f = fixture
    payload, reply = begin(f)
    assert reply["payload"]["outcome"] == "pending"
    changed = {SCENE: {"group": "scenes", "name": "Different Scene Name"}}
    reply = call(f, "native.begin", {**payload, "manifest": changed})
    assert reply["payload"]["code"] == "duplicate_request"
    assert f.host.manifests[RID] == (MANIFEST, SCENE)


def test_checkpoint_file_write_failure_cannot_leave_an_unreceipted_prepared_transfer(fixture):
    f = fixture
    _, payload = upload(f)

    def fail_write(_data):
        raise OSError("isolated checkpoint write failed")

    f.host.upload = types.SimpleNamespace(write_bytes=fail_write)
    reply = call(f, "native.commit", payload)
    receipts = [reply] if reply is not None else f.conn.sent
    assert receipts[-1]["payload"]["outcome"] in {"unknown", "rejected"}
    assert f.host.state.pending is None and not f.host.busy
    assert f.session.committing == 0 and not f.native.applies

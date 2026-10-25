"""Native controller state/transport checks with a deterministic file adapter."""
import hashlib
import importlib
import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2] / "blender_addon/spatial_modeling"
PACKAGE = "_native_controller_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
client_module = importlib.import_module(PACKAGE + ".native_sync.client")
wire = importlib.import_module(PACKAGE + ".native_sync.wire")
NativeClient = client_module.NativeClient

SCENE = uuid.uuid4().hex
MANIFEST = {SCENE: {"group": "scenes", "name": "Original scene"}}
IDENTITY = {key: uuid.uuid4().hex for key in ("session_id", "host_epoch", "document_id", "open_epoch")}
ACTOR, LEASE = uuid.uuid4().hex, uuid.uuid4().hex


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(data):
    return SimpleNamespace(data=data, sha256=digest(data), manifest=MANIFEST,
                           active_scene_uuid=SCENE)


def head(data=b"host original", revision=0):
    return {**IDENTITY, "revision": revision, "checkpoint_hash": digest(data)}


def welcome(capable=True):
    return {"session_id": IDENTITY["session_id"], "host_epoch": IDENTITY["host_epoch"],
        "document": {"id": IDENTITY["document_id"], "open_epoch": IDENTITY["open_epoch"]},
        "actor_id": ACTOR, "can_edit": True, "capabilities": {"native_sync": capable}}


class Document:
    def __init__(self):
        self.data = b"empty"
        self.safe = True
        self.captures = 0
        self.applies = 0

    def is_idle(self):
        return self.safe

    def is_empty_session(self):
        return self.data in {b"empty", b"empty with local material"}

    def capture(self, path):
        self.captures += 1
        Path(path).write_bytes(self.data)
        return snapshot(self.data)

    def apply(self, path, manifest, on_done, _on_error, active_scene_uuid=None):
        assert manifest == MANIFEST and active_scene_uuid == SCENE
        # Local reserialization bytes intentionally DIFFER from the sender's.
        self.data = b"local save:" + Path(path).read_bytes()
        self.applies += 1
        on_done({"datablocks": 1})


def setup(tmp_path):
    now = [0.0]
    doc, sent = Document(), []
    client = NativeClient(doc, lambda msg: sent.append(msg) or True, tmp_path,
                          clock=lambda: now[0])
    client.welcome(welcome())
    feed(client)
    return client, doc, sent, now


def feed(client, data=b"host original", revision=0):
    for payload in wire.iter_messages(snapshot(data), head(data, revision)):
        client.receive("native.snapshot", payload)
    client.tick()


def edit_turn(client):
    assert client.take_edit_turn()
    client.receive("lease.granted", (client._lease_request, {"lease": {
        "lease_id": LEASE, "mode": "exclusive", "owner": {"actor_id": ACTOR}}}))
    assert not client.is_editing  # grant alone does not authorize a stale local model
    feed(client)
    assert client.is_editing


def edited(client, doc, now, value=b"native Edit Mode and material change"):
    doc.data = value
    now[0] += 1
    client.mark_dirty()
    now[0] += .3
    client.tick()
    return client.watcher.pending


def test_missing_native_capability_refuses_silent_limited_fallback(tmp_path):
    sent = []
    client = NativeClient(Document(), lambda msg: sent.append(msg) or True, tmp_path)
    client.welcome(welcome(capable=False))
    assert not client.enabled and not client.connected and not sent
    assert "no limited mirror" in client.status


def test_download_establishes_own_serialization_baseline_and_suppresses_echo(tmp_path):
    client, doc, sent, now = setup(tmp_path)
    assert client.has_native_document and doc.applies == 1
    assert client.watcher.baseline_hash == digest(doc.data)
    assert client.watcher.baseline_hash != client.head["checkpoint_hash"]
    client.mark_dirty(1)
    now[0] = 2
    client.tick()
    assert not client.watcher.has_local_changes
    assert [msg["type"] for msg in sent] == ["native.get"]


def test_explicit_grant_requires_actual_owner_then_fresh_native_document(tmp_path):
    client, doc, sent, _ = setup(tmp_path)
    edit_turn(client)
    acquire = next(msg for msg in sent if msg["type"] == "lease.acquire")
    assert acquire["payload"] == {**IDENTITY, "actor_id": ACTOR,
                                  "mode": "exclusive", "targets": []}
    assert [msg["type"] for msg in sent].count("native.get") == 2
    assert doc.applies == 2 and client.is_editing


def test_native_edit_waits_for_idle_then_paces_upload_after_begin_ack(tmp_path):
    client, doc, sent, now = setup(tmp_path)
    edit_turn(client)
    doc.safe = False
    doc.data = b"a" * (wire.CHUNK_BYTES * 2 + 19)
    client.mark_dirty(1)
    now[0] = 2
    previous = doc.captures
    client.tick()
    assert doc.captures == previous and not client.watcher.pending
    doc.safe = True
    client.tick()
    pending = client.watcher.pending
    assert sent[-1]["type"] == "native.begin"
    for _ in range(3):
        client.tick()
    assert not any(msg["type"] == "native.chunk" for msg in sent)
    client.receive("native.receipt", {"request_id": pending.request_id, "outcome": "pending"})
    for index in range(3):
        client.tick()
        assert sum(msg["type"] == "native.chunk" for msg in sent) == index + 1
    client.tick()
    assert sent[-1]["type"] == "native.commit"
    assert all(msg["payload"]["lease_id"] == LEASE for msg in sent
               if msg["type"] in {"native.begin", "native.chunk", "native.commit"})


def test_applied_receipt_uses_host_cas_head_but_own_saved_baseline(tmp_path):
    client, doc, _, now = setup(tmp_path)
    edit_turn(client)
    pending = edited(client, doc, now)
    remote_hash = digest(b"host reserialized accepted native data")
    client.receive("native.receipt", {"request_id": pending.request_id, "outcome": "applied",
                                      "revision": 1, "checkpoint_hash": remote_hash})
    assert client.head["checkpoint_hash"] == remote_hash
    assert client.watcher.baseline_hash == pending.checkpoint_hash != remote_hash
    client.mark_dirty()
    now[0] += .3
    client.tick()
    assert client.watcher.pending is None and not client.watcher.dirty


def test_rejection_and_incoming_snapshot_never_replace_local_native_draft(tmp_path):
    client, doc, sent, now = setup(tmp_path)
    edit_turn(client)
    pending = edited(client, doc, now)
    client.receive("native.receipt", {"request_id": pending.request_id, "outcome": "rejected",
                                      "code": "stale_revision"})
    before, applies = doc.data, doc.applies
    feed(client, b"a newer host graph", revision=1)
    assert doc.data == before and doc.applies == applies
    assert client.watcher.retained_draft is pending
    assert (tmp_path / ("draft-" + pending.request_id + ".blend")).read_bytes() == before
    count = len(sent)
    for _ in range(10):
        client.tick()
    assert len(sent) == count  # no replay and no silent reacquisition


def test_disconnect_preserves_document_and_draft_and_never_replays_on_welcome(tmp_path):
    client, doc, sent, now = setup(tmp_path)
    edit_turn(client)
    pending = edited(client, doc, now)
    before, applies = doc.data, doc.applies
    client.disconnect()
    assert client.watcher.rejection == "unknown_after_disconnect"
    assert client.has_native_document and doc.data == before
    client.welcome(welcome())
    feed(client)
    assert doc.data == before and doc.applies == applies
    assert client.watcher.pending is pending
    assert [msg["type"] for msg in sent].count("native.begin") == 1


def test_viewer_edits_are_retained_instead_of_overwritten_or_implicitly_shared(tmp_path):
    client, doc, sent, now = setup(tmp_path)
    pending = edited(client, doc, now, b"unsanctioned local draft")
    assert pending is not None and client.watcher.rejection == "edit_turn_required"
    assert not any(msg["type"] == "native.begin" for msg in sent)
    assert not client.take_edit_turn()
    copy = tmp_path / "saved-local-copy.blend"
    client.save_copy(copy)
    assert copy.read_bytes() == doc.data
    assert client.reload_host(discard=True)
    feed(client, b"latest host", revision=1)
    assert doc.data == b"local save:latest host"
    assert not client.watcher.has_local_changes


def test_finish_waits_for_final_checkpoint_ack_before_releasing(tmp_path):
    client, doc, sent, now = setup(tmp_path)
    edit_turn(client)
    pending = edited(client, doc, now)
    assert client.finish_edit_turn()
    now[0] += .3
    client.tick()
    assert not any(msg["type"] == "lease.release" for msg in sent)
    client.receive("native.receipt", {"request_id": pending.request_id, "outcome": "applied",
                                      "revision": 1, "checkpoint_hash": digest(b"host1")})
    client.tick()  # final native capture equals our acknowledged saved bytes
    assert sent[-1]["type"] == "lease.release" and not client.is_editing


def test_lease_loss_stops_sharing_but_keeps_native_document(tmp_path):
    client, doc, _, _ = setup(tmp_path)
    edit_turn(client)
    before = doc.data
    client.receive("session.update", {"leases": []})
    assert not client.is_editing and doc.data == before


def test_incoming_write_failure_leaves_client_recoverable_without_auto_retry(tmp_path, monkeypatch):
    client, doc, _, _ = setup(tmp_path)
    original_write = Path.write_bytes

    def fail_incoming(path, content):
        if path.name.startswith("incoming-"):
            raise OSError("disk full")
        return original_write(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail_incoming)
    feed(client, b"new native graph", revision=1)
    assert not client.applying and client._download_failed
    before = doc.applies
    client.tick()
    assert doc.applies == before
    monkeypatch.setattr(Path, "write_bytes", original_write)
    assert client.reload_host()
    feed(client, b"new native graph", revision=1)
    assert not client.applying and doc.applies == before + 1


def test_post_apply_capture_failure_preserves_document_but_never_grants_edit_turn(tmp_path, monkeypatch):
    client, doc, _, _ = setup(tmp_path)
    assert client.take_edit_turn()
    client.receive("lease.granted", (client._lease_request, {"lease": {
        "lease_id": LEASE, "mode": "exclusive", "owner": {"actor_id": ACTOR}}}))

    original_capture = doc.capture
    audits = []

    def failed_capture(path):
        if not audits:
            audits.append(True)
            return original_capture(path)
        raise OSError("cannot save local baseline")

    monkeypatch.setattr(doc, "capture", failed_capture)
    feed(client)
    assert not client.applying and client.has_native_document
    assert not client.is_editing and "baseline" in client.error


def test_wrong_document_snapshot_is_rejected_before_native_apply(tmp_path):
    client, doc, _, _ = setup(tmp_path)
    bad_head = head()
    bad_head["open_epoch"] = uuid.uuid4().hex
    before = doc.applies
    with pytest.raises(ValueError, match="another session"):
        for payload in wire.iter_messages(snapshot(b"other file"), bad_head):
            client.receive("native.snapshot", payload)
    assert doc.applies == before


def test_announced_head_cannot_rebase_local_draft_onto_unapplied_host_edits(tmp_path):
    client, doc, sent, now = setup(tmp_path)
    edit_turn(client)
    original_base = dict(client.applied_head)
    doc.data = b"local edit based on original host data"
    now[0] = 1
    client.mark_dirty()
    announced = head(b"concurrent host edit", revision=1)
    client.receive("native.head", announced)
    assert client.head == announced and client.applied_head == original_base
    now[0] = 2
    client.tick()
    begin = next(msg for msg in reversed(sent) if msg["type"] == "native.begin")
    assert begin["payload"]["base_revision"] == original_base["revision"] == 0
    assert begin["payload"]["base_hash"] == original_base["checkpoint_hash"]
    assert begin["payload"]["base_hash"] != announced["checkpoint_hash"]
    # The authoritative Host will reject this stale baseline; preserve the draft.
    client.receive("native.receipt", {"request_id": client.watcher.pending.request_id,
                                      "outcome": "rejected", "code": "stale_revision"})
    assert client.watcher.rejection == "stale_revision" and doc.data.startswith(b"local edit")


def test_late_applied_receipt_does_not_regress_newer_announced_head(tmp_path):
    client, doc, _, now = setup(tmp_path)
    edit_turn(client)
    pending = edited(client, doc, now)
    latest = head(b"later authoritative head", revision=2)
    client.receive("native.head", latest)
    accepted_hash = digest(b"our accepted head at revision1")
    client.receive("native.receipt", {"request_id": pending.request_id, "outcome": "applied",
                                      "revision": 1, "checkpoint_hash": accepted_hash})
    assert client.head == latest
    assert client.applied_head["revision"] == 1 and client.applied_head["checkpoint_hash"] == accepted_hash


def test_save_and_explicit_reload_preserve_edits_newer_than_rejected_snapshot(tmp_path):
    client, doc, _, now = setup(tmp_path)
    edit_turn(client)
    pending = edited(client, doc, now, b"uploaded native draft")
    doc.data = b"newer local native changes after upload"
    client.mark_dirty()
    client.receive("native.receipt", {"request_id": pending.request_id, "outcome": "rejected",
                                      "code": "stale_revision"})
    saved = tmp_path / "latest-user-copy.blend"
    client.save_copy(saved)
    assert saved.read_bytes() == b"newer local native changes after upload"
    assert client.reload_host(discard=True)
    feed(client, b"new authoritative original", revision=2)
    backups = list(tmp_path.glob("before-reload-*.blend"))
    assert len(backups) == 1 and backups[0].read_bytes() == saved.read_bytes()
    assert (tmp_path / ("draft-" + pending.request_id + ".blend")).read_bytes() == b"uploaded native draft"


def test_reload_backup_failure_never_replaces_current_local_data(tmp_path, monkeypatch):
    client, doc, _, now = setup(tmp_path)
    edited(client, doc, now, b"local unsent document")
    assert client.reload_host(discard=True)
    before = doc.data

    def failed_capture(_path):
        raise OSError("backup disk is full")

    monkeypatch.setattr(doc, "capture", failed_capture)
    feed(client, b"host replacement", revision=1)
    assert doc.data == before and not client.applying
    assert "backed up" in client.error


def test_old_async_apply_completion_cannot_replace_reconnected_session_head(tmp_path, monkeypatch):
    client, doc, _, _ = setup(tmp_path)
    callbacks = []
    original_apply = doc.apply

    def deferred_apply(path, _manifest, on_done, _on_error, active_scene_uuid=None):
        doc.data = b"old connection native result:" + Path(path).read_bytes()
        callbacks.append(on_done)

    monkeypatch.setattr(doc, "apply", deferred_apply)
    feed(client, b"old connection checkpoint", revision=1)
    assert client.applying
    client.disconnect()
    next_welcome = welcome()
    next_welcome["host_epoch"] = uuid.uuid4().hex
    client.welcome(next_welcome)
    new_head = head(b"new connection graph")
    new_head["host_epoch"] = next_welcome["host_epoch"]
    for payload in wire.iter_messages(snapshot(b"new connection graph"), new_head):
        client.receive("native.snapshot", payload)
    callbacks.pop()({})
    assert not client.applying and client.applied_head is None and not client.is_editing
    monkeypatch.setattr(doc, "apply", original_apply)
    client.tick()
    assert client.applied_head == new_head
    assert doc.data == b"local save:new connection graph"


def test_apply_finishing_after_disconnect_keeps_disconnected_status(tmp_path, monkeypatch):
    client, doc, _, _ = setup(tmp_path)
    callbacks = []

    def deferred_apply(_path, _manifest, on_done, _on_error, active_scene_uuid=None):
        callbacks.append(on_done)

    monkeypatch.setattr(doc, "apply", deferred_apply)
    feed(client, b"received before disconnect", revision=1)
    client.disconnect()
    callbacks.pop()({})
    assert not client.connected and not client.is_editing and not client.applying
    assert client.status.startswith("Disconnected")


def test_native_edit_without_dirty_signal_is_backed_up_and_never_overwritten(tmp_path):
    client, doc, _, now = setup(tmp_path)
    before = doc.applies
    doc.data = b"native changes with no depsgraph signal yet"
    feed(client, b"incoming authoritative update", revision=1)
    assert doc.data == b"native changes with no depsgraph signal yet" and doc.applies == before
    assert client.watcher.dirty and client._incoming_conflict
    backup = next(tmp_path.glob("before-incoming-*.blend"))
    assert backup.read_bytes() == doc.data
    now[0] += .3
    client.tick()
    assert client.watcher.rejection == "local_changes_before_receive"
    assert client.watcher.retained_draft.payload.data == doc.data


def test_objects_added_after_empty_connect_admission_block_first_native_apply(tmp_path):
    now, sent = [0.0], []
    doc = Document()
    client = NativeClient(doc, lambda msg: sent.append(msg) or True, tmp_path,
                          clock=lambda: now[0])
    client.welcome(welcome())
    doc.data = b"newly created object after connection"
    feed(client)
    assert doc.applies == 0 and not client.has_native_document
    assert client.initial_local_work and client.watcher.dirty
    now[0] = 1
    client.tick()
    assert client.watcher.rejection == "local_changes_before_receive"
    assert client.watcher.retained_draft.payload.data == doc.data


def test_unreferenced_data_added_without_objects_blocks_initial_native_apply(tmp_path):
    doc = Document()
    client = NativeClient(doc, lambda _msg: True, tmp_path, clock=lambda: 0)
    client.welcome(welcome())
    doc.data = b"empty with local material"  # still passes object/file empty admission
    assert doc.is_empty_session()
    feed(client)
    assert doc.applies == 0 and client.initial_local_work
    assert next(tmp_path.glob("before-incoming-*.blend")).read_bytes() == doc.data


def test_failed_preapply_audit_retains_actual_document_without_starting_apply(tmp_path, monkeypatch):
    client, doc, _, _ = setup(tmp_path)
    before, applies = doc.data, doc.applies

    def failed_capture(_path):
        raise OSError("local hash audit could not save")

    monkeypatch.setattr(doc, "capture", failed_capture)
    feed(client, b"incoming update", revision=1)
    assert doc.data == before and doc.applies == applies and not client.applying
    assert "not applied" in client.error


def test_author_can_publish_and_finish_settled_edit_mode_but_foreign_apply_waits(tmp_path):
    client, doc, sent, now = setup(tmp_path)
    edit_turn(client)
    doc.safe = False  # is_idle=False represents a local object remaining in Edit Mode
    doc.can_capture = lambda: True  # settled BMesh data can be captured without a modal
    pending = edited(client, doc, now, b"completed native Edit Mode operation")
    assert pending is not None and sent[-1]["type"] == "native.begin"
    assert client.finish_edit_turn()
    client.receive("native.receipt", {"request_id": pending.request_id, "outcome": "applied",
                                      "revision": 1, "checkpoint_hash": digest(b"host accepted")})
    now[0] += .3
    client.tick()
    assert sent[-1]["type"] == "lease.release" and not client.is_editing
    before = doc.applies
    feed(client, b"next author's foreign checkpoint", revision=2)
    assert doc.applies == before and client._download is not None
    doc.safe = True
    client.tick()
    assert doc.applies == before + 1

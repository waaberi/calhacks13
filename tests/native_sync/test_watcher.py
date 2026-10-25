"""Native scheduling tests exercise actual draft/outcome lifecycle, without bpy."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "blender_addon/spatial_modeling/native_sync/watcher.py"
SPEC = importlib.util.spec_from_file_location("native_watcher", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
# dataclass resolves annotations through its module entry during isolated import.
import sys

sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
NativeChangeTracker = MODULE.NativeChangeTracker


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def checkpoint(tracker, value="local edit", now=1):
    tracker.mark_dirty(now)
    return tracker.poll(now + .3, True, lambda: (digest(value), {"value": value}))


def test_quiet_and_safe_gates_never_export_mid_edit_or_modal():
    tracker = NativeChangeTracker()
    calls = []

    def export():
        calls.append(True)
        return digest("settled"), object()

    tracker.mark_dirty(1)
    assert tracker.poll(1.1, True, export) is None
    tracker.mark_dirty(1.2)
    assert tracker.poll(1.4, True, export) is None
    assert tracker.poll(2, False, export) is None  # Edit Mode / modal / remote apply
    assert not calls
    pending = tracker.poll(2.1, True, export)
    assert pending and len(calls) == 1
    assert tracker.poll(5, True, export) is None
    assert len(calls) == 1 and tracker.in_flight


def test_acknowledged_baseline_suppresses_noop_and_undo_echo():
    tracker = NativeChangeTracker()
    first = checkpoint(tracker)
    assert tracker.acknowledge(first.request_id) is first
    assert tracker.baseline_hash == first.checkpoint_hash
    tracker.mark_dirty(3)
    assert tracker.poll(4, True, lambda: (first.checkpoint_hash, "unused")) is None
    assert not tracker.dirty and not tracker.has_local_changes


def test_remote_apply_uses_own_local_hash_not_sending_peer_hash():
    tracker = NativeChangeTracker()
    sender_hash, locally_saved_hash = digest("remote serialized bytes"), digest("local saved bytes")
    assert sender_hash != locally_saved_hash
    tracker.mark_dirty(1)  # depsgraph signal caused by applying the remote checkpoint
    tracker.applied_local_baseline(locally_saved_hash)
    assert tracker.dirty  # the signal is not silently discarded
    assert tracker.poll(2, True, lambda: (locally_saved_hash, "remote echo")) is None
    assert not tracker.has_local_changes


def test_changes_while_waiting_for_ack_are_exported_after_ack():
    tracker = NativeChangeTracker()
    first = checkpoint(tracker, "first", 1)
    tracker.mark_dirty(2)
    assert tracker.poll(3, True, lambda: pytest.fail("request still pending")) is None
    tracker.acknowledge(first.request_id)
    second = tracker.poll(4, True, lambda: (digest("second"), "new native data"))
    assert second and second.request_id != first.request_id
    assert second.checkpoint_hash == digest("second")


def test_reentrant_dirty_during_export_survives_ack():
    tracker = NativeChangeTracker()
    tracker.mark_dirty(1)

    def export():
        tracker.mark_dirty(2)
        return digest("before callback"), "first"

    first = tracker.poll(2, True, export)
    tracker.acknowledge(first.request_id)
    assert tracker.dirty
    assert tracker.poll(2.1, True, lambda: pytest.fail("new signal is not quiet")) is None
    assert tracker.poll(3, True, lambda: (digest("after callback"), "second"))


def test_rejection_keeps_payload_and_new_local_edits_without_replay():
    tracker = NativeChangeTracker()
    first = checkpoint(tracker)
    assert tracker.reject(first.request_id, "conflict") is first
    tracker.mark_dirty(2)
    tracker.applied_local_baseline(digest("remote local copy"))
    for now in (3, 5, 50):
        assert tracker.poll(now, True, lambda: pytest.fail("rejected draft cannot auto-replay")) is None
    assert tracker.pending is first and tracker.retained_draft is first
    assert tracker.dirty and tracker.rejection == "conflict"


def test_explicit_retry_exports_latest_native_document_and_fresh_request():
    tracker = NativeChangeTracker()
    first = checkpoint(tracker, "old")
    tracker.reject(first.request_id, "stale_revision")
    tracker.retry(3)
    assert tracker.retained_draft is first
    second = tracker.poll(4, True, lambda: (digest("latest"), "latest document"))
    assert second.request_id != first.request_id and second.payload == "latest document"
    assert tracker.retained_draft is None


def test_discard_needs_resolved_outcome_and_verified_local_baseline():
    tracker = NativeChangeTracker()
    first = checkpoint(tracker)
    with pytest.raises(ValueError, match="in-flight"):
        tracker.discard(digest("restored"))
    tracker.reject(first.request_id, "conflict")
    with pytest.raises(ValueError, match="SHA256"):
        tracker.discard("not verified")
    assert tracker.retained_draft is first
    tracker.discard(digest("restored"))
    assert tracker.baseline_hash == digest("restored") and not tracker.has_local_changes


def test_late_ack_never_overwrites_newer_local_remote_apply_baseline():
    tracker = NativeChangeTracker()
    first = checkpoint(tracker)
    remote_local_hash = digest("newer remote applied locally")
    tracker.applied_local_baseline(remote_local_hash)
    assert tracker.pending is first
    tracker.acknowledge(first.request_id)
    assert tracker.baseline_hash == remote_local_hash and tracker.dirty
    assert tracker.poll(3, True, lambda: (remote_local_hash, "echo")) is None


def test_wrong_outcomes_and_export_failures_cannot_drop_native_draft():
    tracker = NativeChangeTracker()
    first = checkpoint(tracker)
    with pytest.raises(ValueError, match="does not match"):
        tracker.acknowledge("wrong request")
    with pytest.raises(ValueError, match="does not match"):
        tracker.reject("wrong request", "conflict")
    assert tracker.pending is first
    tracker.reject(first.request_id)
    tracker.retry(2)

    def fail():
        raise OSError("local checkpoint could not be written")

    with pytest.raises(OSError):
        tracker.poll(3, True, fail)
    assert tracker.dirty and tracker.retained_draft is first
    assert tracker.poll(4, True, lambda: (digest("recovered"), "current data"))


def test_invalid_export_hash_keeps_dirty_signal():
    tracker = NativeChangeTracker()
    tracker.mark_dirty(1)
    with pytest.raises(ValueError, match="SHA256"):
        tracker.poll(2, True, lambda: ("invalid", "payload"))
    assert tracker.dirty and tracker.pending is None

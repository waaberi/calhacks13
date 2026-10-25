"""Native checkpoint authority and lifecycle, independently of Blender or transport."""
import hashlib
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "blender_addon/spatial_modeling/native_sync/state.py"
SPEC = importlib.util.spec_from_file_location("native_checkpoint_state", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
Fence, NativeSyncState, Refused = MODULE.Fence, MODULE.NativeSyncState, MODULE.Refused
SID, EPOCH, DOC, OPEN, ACTOR, LEASE = (str(i) * 32 for i in range(1, 7))
RID, OTHER = "a" * 32, "b" * 32
BASE, AFTER = "c" * 64, "d" * 64
PAYLOAD = b"BLENDER-native-checkpoint"


def fixture(**limits):
    state = NativeSyncState(session_id=SID, host_epoch=EPOCH, document_id=DOC,
                            open_epoch=OPEN, revision=7, checkpoint_hash=BASE, **limits)
    fence = Fence(SID, EPOCH, DOC, OPEN, ACTOR, True, True, LEASE, ACTOR, "exclusive", True)
    return state, fence


def begin(state, fence, rid=RID, **changes):
    args = {"base_revision": 7, "base_hash": BASE,
            "content_hash": hashlib.sha256(PAYLOAD).hexdigest(),
            "total_bytes": len(PAYLOAD), "chunk_count": 1}
    args.update(changes)
    return state.begin(rid, fence, **args)


def prepare(state, fence):
    begin(state, fence)
    state.chunk(RID, fence, 0, PAYLOAD)
    return state.prepare(RID, fence)


def refused(code, call):
    with pytest.raises(Refused) as result:
        call()
    assert result.value.code == code


def test_apply_once_and_keep_verified_host_hash_separate_from_received_file_hash():
    state, fence = fixture()
    checkpoint = prepare(state, fence)
    assert checkpoint.data == PAYLOAD and checkpoint.base_revision == 7
    refused("already_prepared", lambda: state.prepare(RID, fence))
    # Native re-export contains process-specific data; compare host to its own
    # baseline and record its fresh hash rather than requiring the peer's hash.
    assert AFTER != checkpoint.content_hash
    receipt = state.applied(RID, fence, revision=8, checkpoint_hash=AFTER)
    assert receipt.outcome == "applied" and receipt.revision == 8
    assert state.pending is None and state.checkpoint_hash == AFTER
    assert begin(state, fence) == receipt  # replay returns receipt, never reopens.
    assert state.query(RID, replace(fence, can_edit=False, lease_current=False)) == receipt


@pytest.mark.parametrize(("field", "value", "code"), [
    ("session_id", "f" * 32, "wrong_session"),
    ("host_epoch", "f" * 32, "wrong_session"),
    ("document_id", "f" * 32, "wrong_document"),
    ("open_epoch", "f" * 32, "wrong_document"),
    ("connected", False, "disconnected"),
    ("can_edit", False, "permission_denied"),
    ("lease_owner", "f" * 32, "lease_conflict"),
    ("lease_mode", "shared", "lease_conflict"),
    ("lease_current", False, "lease_conflict"),
])
def test_live_identity_permission_and_exclusive_lease_rechecked_on_every_chunk(field, value, code):
    state, fence = fixture()
    begin(state, fence)
    refused(code, lambda: state.chunk(RID, replace(fence, **{field: value}), 0, PAYLOAD))
    assert state.pending.received_bytes == 0


def test_actor_or_lease_replacement_cannot_take_over_a_pending_transfer():
    state, fence = fixture()
    begin(state, fence)
    stranger = replace(fence, actor_id=OTHER, lease_owner=OTHER)
    refused("wrong_actor", lambda: state.chunk(RID, stranger, 0, PAYLOAD))
    refused("stale_lease", lambda: state.chunk(
        RID, replace(fence, lease_id=OTHER), 0, PAYLOAD))
    refused("wrong_actor", lambda: state.query(RID, stranger))


def test_stale_baseline_and_native_host_edit_during_transfer_refuse_before_apply():
    state, fence = fixture()
    refused("stale_revision", lambda: begin(state, fence, base_revision=6))
    refused("stale_revision", lambda: begin(state, fence, base_hash=AFTER))
    begin(state, fence)
    state.chunk(RID, fence, 0, PAYLOAD)
    state.sync_head(8, AFTER)
    refused("stale_revision", lambda: state.prepare(RID, fence))
    assert not state.pending.applying
    assert state.cancel(RID, fence).outcome == "rejected"


def test_duplicate_ids_cannot_change_payload_or_mutate_twice():
    state, fence = fixture()
    assert begin(state, fence).outcome == "pending"
    assert begin(state, fence).outcome == "pending"
    refused("duplicate_request", lambda: begin(state, fence, content_hash=AFTER))
    state.chunk(RID, fence, 0, PAYLOAD)
    assert state.chunk(RID, fence, 0, PAYLOAD) == len(PAYLOAD)
    refused("duplicate_chunk", lambda: state.chunk(RID, fence, 0, b"different"))
    state.prepare(RID, fence)
    state.applied(RID, fence, revision=8, checkpoint_hash=AFTER)
    refused("no_pending_transfer", lambda: state.prepare(RID, fence))
    refused("duplicate_request", lambda: begin(state, fence, content_hash=AFTER))


def test_one_pending_transfer_and_byte_chunk_limits():
    state, fence = fixture(max_bytes=32, max_chunk_bytes=16, max_chunks=3)
    refused("transfer_limit", lambda: begin(state, fence, total_bytes=33, chunk_count=3))
    refused("transfer_limit", lambda: begin(state, fence, chunk_count=4))
    begin(state, fence, chunk_count=2)
    refused("busy", lambda: begin(state, fence, rid=OTHER, chunk_count=2))
    refused("invalid_chunk", lambda: state.chunk(RID, fence, 2, b"a"))
    refused("invalid_chunk", lambda: state.chunk(RID, fence, 0, b""))
    refused("invalid_chunk", lambda: state.chunk(RID, fence, 0, b"a" * 17))
    state.chunk(RID, fence, 1, PAYLOAD[12:])
    refused("incomplete_transfer", lambda: state.prepare(RID, fence))
    state.chunk(RID, fence, 0, PAYLOAD[:12])
    assert state.prepare(RID, fence).data == PAYLOAD


def test_hash_mismatch_never_crosses_apply_boundary():
    state, fence = fixture()
    begin(state, fence, content_hash=AFTER)
    state.chunk(RID, fence, 0, PAYLOAD)
    refused("hash_mismatch", lambda: state.prepare(RID, fence))
    assert not state.pending.applying
    assert state.cancel(RID, fence).code == "cancelled_before_apply"


def test_cancel_before_apply_is_terminal_and_cancel_after_prepare_is_refused():
    state, fence = fixture()
    begin(state, fence)
    receipt = state.cancel(RID, fence)
    assert receipt.code == "cancelled_before_apply"
    assert begin(state, fence) == receipt and state.pending is None
    begin(state, fence, rid=OTHER)
    state.chunk(OTHER, fence, 0, PAYLOAD)
    state.prepare(OTHER, fence)
    refused("too_late", lambda: state.cancel(OTHER, fence))
    refused("rollback_unverified", lambda: state.rejected(OTHER, fence))
    assert state.rejected(OTHER, fence, rollback_verified=True).outcome == "rejected"


def test_disconnect_while_receiving_rejects_without_reopening_on_reconnect():
    state, fence = fixture()
    begin(state, fence)
    receipt = state.disconnected(ACTOR)
    assert receipt.code == "connection_lost_before_apply"
    assert begin(state, fence) == receipt and state.pending is None


def test_disconnect_during_apply_is_unknown_blocks_new_work_until_checked():
    state, fence = fixture()
    prepare(state, fence)
    receipt = state.disconnected(ACTOR)
    assert receipt.outcome == "unknown"
    assert begin(state, fence) == receipt and state.pending is None
    refused("unknown_outcome", lambda: begin(state, fence, rid=OTHER))
    refused("stale_revision", lambda: state.acknowledge_unknown(
        RID, fence, revision=6, checkpoint_hash=BASE))
    assert state.acknowledge_unknown(RID, fence, revision=7, checkpoint_hash=BASE) == receipt
    assert begin(state, fence, rid=OTHER).outcome == "pending"
    assert state.query(RID, fence).outcome == "unknown"  # never invent applied/rejected.


def test_unknown_missing_or_old_incarnation_requests_never_automatically_replay():
    state, fence = fixture()
    assert state.query(RID, fence).outcome == "unknown"
    refused("wrong_session", lambda: state.query(RID, replace(fence, host_epoch=OTHER)))
    prepare(state, fence)
    state.unknown(RID)
    assert state.query(RID, fence).code == "apply_unverified"


def test_receipts_are_bounded_without_evicting_dedup_history():
    state, fence = fixture(max_receipts=1)
    begin(state, fence)
    receipt = state.cancel(RID, fence)
    refused("receipt_capacity", lambda: begin(state, fence, rid=OTHER))
    assert begin(state, fence) == receipt


def test_applied_requires_prepare_new_revision_and_no_intervening_host_head():
    state, fence = fixture()
    begin(state, fence)
    refused("not_prepared", lambda: state.applied(RID, fence, revision=8, checkpoint_hash=AFTER))
    state.chunk(RID, fence, 0, PAYLOAD)
    state.prepare(RID, fence)
    refused("revision_not_advanced", lambda: state.applied(
        RID, fence, revision=7, checkpoint_hash=AFTER))
    state.sync_head(9, "e" * 64)
    refused("stale_revision", lambda: state.applied(RID, fence, revision=8, checkpoint_hash=AFTER))
    assert state.unknown(RID).outcome == "unknown"


def test_host_sync_cannot_silently_replace_an_unversioned_native_graph():
    state, _ = fixture()
    refused("unversioned_change", lambda: state.sync_head(7, AFTER))
    refused("revision_regressed", lambda: state.sync_head(6, BASE))
    refused("invalid_revision", lambda: state.sync_head(True, BASE))

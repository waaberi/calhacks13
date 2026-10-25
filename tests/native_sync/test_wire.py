"""Native checkpoint wire limits, complete assembly and malformed-data refusal."""
import copy
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "blender_addon/spatial_modeling/native_sync/wire.py"
SPEC = importlib.util.spec_from_file_location("native_checkpoint_wire", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
ChunkReceiver, WireError = MODULE.ChunkReceiver, MODULE.WireError
SID, EPOCH, DOC, OPEN, SCENE, RID = (str(i) * 32 for i in range(1, 7))
HEAD = {"session_id": SID, "host_epoch": EPOCH, "document_id": DOC, "open_epoch": OPEN,
        "revision": 7, "checkpoint_hash": "a" * 64}
MANIFEST = {SCENE: {"group": "scenes", "name": "Scene"},
            "b" * 32: {"group": "objects", "name": "Original Cube"}}


def messages(data=b"BLENDER-original-native-file", **changes):
    snapshot = {"data": data, "manifest": copy.deepcopy(MANIFEST), "active_scene_uuid": SCENE}
    snapshot.update(changes)
    return list(MODULE.iter_messages(snapshot, HEAD, RID))


def refused(code, call):
    with pytest.raises(WireError) as error:
        call()
    assert error.value.code == code


def test_round_trip_native_data_and_manifest_with_two_chunks():
    data = b"BLENDER" + bytes(range(256)) * 1025
    payloads = messages(data)
    assert [m["phase"] for m in payloads] == ["begin", "chunk", "chunk", "end"]
    receiver = ChunkReceiver()
    for payload in payloads[:-1]:
        assert receiver.feed(payload) is None
    result = receiver.feed(payloads[-1])
    assert result["data"] == data
    assert result["manifest"] == MANIFEST and result["head"] == HEAD
    assert result["active_scene_uuid"] == SCENE and result["request_id"] == RID
    assert not receiver.pending
    refused("no_pending_transfer", lambda: receiver.feed(payloads[-1]))


def test_snapshot_object_and_optional_hash_work_without_blender():
    snapshot = SimpleNamespace(data=b"native", manifest=MANIFEST, active_scene_uuid=SCENE)
    payloads = list(MODULE.iter_messages(snapshot, HEAD, kind="native.commit"))
    assert payloads[0]["kind"] == "native.commit" and len(payloads[0]["request_id"]) == 32
    snapshot.sha256 = "c" * 64
    refused("hash_mismatch", lambda: list(MODULE.iter_messages(snapshot, HEAD)))


def test_active_scene_alias_and_public_manifest_validator():
    snapshot = SimpleNamespace(data=b"native", manifest=MANIFEST, active_scene=SCENE)
    payloads = list(MODULE.iter_messages(snapshot, HEAD))
    assert payloads[0]["active_scene_uuid"] == SCENE
    copied = MODULE.validate_manifest(MANIFEST, SCENE)
    assert copied == MANIFEST and copied is not MANIFEST


@pytest.mark.parametrize("value", ["!!!!", "YQ==\n", "YQ=", "Yf==", "é==="])
def test_noncanonical_or_malformed_base64_refused(value):
    refused("invalid_base64", lambda: MODULE.decode_chunk(value))


def test_chunk_size_checked_before_decode_and_empty_data_refused():
    refused("chunk_limit", lambda: MODULE.decode_chunk("A" * 100, max_bytes=3))
    refused("chunk_limit", lambda: MODULE.encode_chunk(b""))
    refused("chunk_limit", lambda: MODULE.encode_chunk(b"long", max_bytes=3))
    refused("chunk_limit", lambda: MODULE.decode_chunk(""))
    assert MODULE.decode_chunk(MODULE.encode_chunk(b"\x00\xff")) == b"\x00\xff"


def test_total_file_limit_and_chunk_count_cannot_allocate_unbounded_memory():
    begin, _, _ = messages()
    receiver = ChunkReceiver(max_bytes=10)
    refused("transfer_limit", lambda: receiver.feed(begin))
    receiver = ChunkReceiver()
    for key, value in (("total_bytes", MODULE.MAX_BYTES + 1), ("chunk_count", 999999),
                       ("total_bytes", True), ("chunk_count", True)):
        payload = {**begin, key: value}
        refused("transfer_limit", lambda payload=payload: receiver.feed(payload))
        assert not receiver.pending


def test_second_begin_wrong_id_and_out_of_order_chunks_abort_assembly():
    begin, chunk, _ = messages()
    receiver = ChunkReceiver()
    receiver.feed(begin)
    refused("busy", lambda: receiver.feed(begin))
    assert not receiver.pending
    receiver.feed(begin)
    refused("wrong_transfer", lambda: receiver.feed({**chunk, "request_id": "e" * 32}))
    receiver.feed(begin)
    refused("chunk_order", lambda: receiver.feed({**chunk, "index": 1}))
    receiver.feed(begin)
    receiver.feed(chunk)
    refused("chunk_order", lambda: receiver.feed(chunk))


def test_early_end_wrong_size_and_corrupt_hash_never_yield_native_bytes():
    begin, chunk, end = messages()
    receiver = ChunkReceiver()
    receiver.feed(begin)
    refused("incomplete_transfer", lambda: receiver.feed(end))
    receiver.feed(begin)
    refused("chunk_size", lambda: receiver.feed({**chunk, "data": MODULE.encode_chunk(b"short")}))
    receiver.feed({**begin, "content_hash": "e" * 64})
    receiver.feed(chunk)
    refused("hash_mismatch", lambda: receiver.feed(end))
    assert not receiver.pending


@pytest.mark.parametrize(("record", "code"), [
    ({"group": "all_ids", "name": "Unsafe aggregate"}, "invalid_manifest_group"),
    ({"group": "window_managers", "name": "UI"}, "invalid_manifest_group"),
    ({"group": "objects", "name": "x", "path": "C:/remote.blend"}, "invalid_manifest"),
    ({"group": "objects", "name": "\x00"}, "invalid_manifest_name"),
    ({"group": "objects", "name": "x" * 513}, "invalid_manifest_name"),
])
def test_manifest_is_only_native_id_group_and_name(record, code):
    manifest = copy.deepcopy(MANIFEST)
    manifest["b" * 32] = record
    refused(code, lambda: messages(manifest=manifest))


def test_active_scene_must_reference_a_scene_and_manifest_identity_is_unambiguous():
    refused("invalid_active_scene", lambda: messages(active_scene_uuid="b" * 32))
    manifest = {**MANIFEST, "c" * 32: MANIFEST["b" * 32]}
    refused("duplicate_manifest_identity", lambda: messages(manifest=manifest))


def test_head_has_only_fenced_id_revision_and_hash_fields():
    snapshot = {"data": b"x", "manifest": MANIFEST, "active_scene_uuid": SCENE}
    for head, code in (({**HEAD, "revision": True}, "invalid_revision"),
                       ({**HEAD, "path": "C:/remote.blend"}, "invalid_head"),
                       ({**HEAD, "session_id": "wrong"}, "invalid_id")):
        refused(code, lambda head=head: list(MODULE.iter_messages(snapshot, head)))


def test_unknown_fields_phase_and_kind_are_refused_and_disconnect_resets():
    begin, chunk, _ = messages()
    receiver = ChunkReceiver()
    refused("invalid_payload", lambda: receiver.feed({**begin, "path": "remote.blend"}))
    refused("invalid_phase", lambda: receiver.feed({"phase": []}))
    refused("invalid_kind", lambda: receiver.feed({**begin, "kind": []}))
    receiver.feed(begin)
    receiver.reset()
    refused("no_pending_transfer", lambda: receiver.feed(chunk))

"""Bounded native-file payload codec. No envelopes, paths, Blender or execution.

The existing authenticated transport supplies message envelopes and peer identity.
The manifest labels native IDs; it never supplies a filesystem destination.
"""
import base64
import binascii
import hashlib
import json
import math
import re
import uuid
from collections.abc import Mapping

MAX_BYTES = 256 * 1024 * 1024
CHUNK_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 512 * 1024
MAX_MANIFEST_ENTRIES = 4096
MANIFEST_GROUPS = frozenset({
    "actions", "annotations", "armatures", "brushes", "cache_files", "cameras",
    "collections", "curves", "fonts", "grease_pencils", "hair_curves", "images",
    "lattices", "lightprobes", "lights", "linestyles", "masks", "materials", "meshes",
    "metaballs", "movieclips", "node_groups", "objects", "paint_curves", "palettes",
    "particles", "pointclouds", "scenes", "shape_keys", "sounds", "speakers", "texts",
    "textures", "volumes", "worlds",
})
_HEAD_KEYS = {"revision", "checkpoint_hash", "document_id", "open_epoch", "session_id", "host_epoch"}
_ID = re.compile(r"[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class WireError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise WireError("invalid_id")
    return value


def _hash(value):
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise WireError("invalid_hash")
    return value


def _head(value):
    if not isinstance(value, Mapping) or set(value) != _HEAD_KEYS:
        raise WireError("invalid_head")
    out = dict(value)
    if type(out["revision"]) is not int or out["revision"] < 0:
        raise WireError("invalid_revision")
    _hash(out["checkpoint_hash"])
    for key in _HEAD_KEYS - {"revision", "checkpoint_hash"}:
        _id(out[key])
    return out


def _manifest(value, active_scene_uuid):
    if not isinstance(value, Mapping) or not 0 < len(value) <= MAX_MANIFEST_ENTRIES:
        raise WireError("invalid_manifest")
    out = {}
    identities = set()
    for key, record in value.items():
        _id(key)
        if not isinstance(record, Mapping) or set(record) != {"group", "name"}:
            raise WireError("invalid_manifest")
        group, name = record["group"], record["name"]
        if not isinstance(group, str) or group not in MANIFEST_GROUPS:
            raise WireError("invalid_manifest_group")
        if not isinstance(name, str) or not 0 < len(name) <= 512 or "\x00" in name:
            raise WireError("invalid_manifest_name")
        identity = (group, name)
        if identity in identities:
            raise WireError("duplicate_manifest_identity")
        identities.add(identity)
        out[key] = {"group": group, "name": name}
    try:
        size = len(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except UnicodeEncodeError as error:
        raise WireError("invalid_manifest_name") from error
    if size > MAX_MANIFEST_BYTES:
        raise WireError("manifest_limit")
    _id(active_scene_uuid)
    if out.get(active_scene_uuid, {}).get("group") != "scenes":
        raise WireError("invalid_active_scene")
    return out


def validate_manifest(value, active_scene_uuid):
    """Validate/copy UUID→native group/name labels and its explicit active scene."""
    return _manifest(value, active_scene_uuid)


def encode_chunk(data, *, max_bytes=CHUNK_BYTES):
    if type(data) is not bytes or not 0 < len(data) <= max_bytes:
        raise WireError("chunk_limit")
    return base64.b64encode(data).decode("ascii")


def decode_chunk(data, *, max_bytes=CHUNK_BYTES):
    if not isinstance(data, str) or not 0 < len(data) <= 4 * math.ceil(max_bytes / 3):
        raise WireError("chunk_limit")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise WireError("invalid_base64") from error
    if not 0 < len(raw) <= max_bytes:
        raise WireError("chunk_limit")
    if base64.b64encode(raw).decode("ascii") != data:
        raise WireError("invalid_base64")
    return raw


def _field(snapshot, name):
    if name == "active_scene_uuid":
        if isinstance(snapshot, Mapping):
            return snapshot.get(name, snapshot.get("active_scene"))
        return getattr(snapshot, name, getattr(snapshot, "active_scene", None))
    return snapshot[name] if isinstance(snapshot, Mapping) else getattr(snapshot, name)


def iter_messages(snapshot, head, request_id=None, kind="native.snapshot"):
    """Yield begin/chunk/end PAYLOADS, to wrap in the existing message envelope.

    Input is Snapshot(data, sha256, manifest, active_scene_uuid), or a mapping
    with those fields (sha256 optional). Whole-file SHA256 is verified locally.
    """
    if not isinstance(kind, str) or kind not in {"native.snapshot", "native.commit"}:
        raise WireError("invalid_kind")
    request_id = _id(request_id or uuid.uuid4().hex)
    data = _field(snapshot, "data")
    if type(data) is not bytes or not 0 < len(data) <= MAX_BYTES:
        raise WireError("transfer_limit")
    content_hash = hashlib.sha256(data).hexdigest()
    claimed = snapshot.get("sha256") if isinstance(snapshot, Mapping) else getattr(snapshot, "sha256", None)
    if claimed is not None and claimed != content_hash:
        raise WireError("hash_mismatch")
    active = _field(snapshot, "active_scene_uuid")
    manifest, head = _manifest(_field(snapshot, "manifest"), active), _head(head)
    count = math.ceil(len(data) / CHUNK_BYTES)
    common = {"request_id": request_id, "kind": kind}
    yield {**common, "phase": "begin", "total_bytes": len(data), "chunk_count": count,
           "content_hash": content_hash, "manifest": manifest,
           "active_scene_uuid": active, "head": head}
    for index, at in enumerate(range(0, len(data), CHUNK_BYTES)):
        yield {**common, "phase": "chunk", "index": index,
               "data": encode_chunk(data[at:at + CHUNK_BYTES])}
    yield {**common, "phase": "end"}


class ChunkReceiver:
    """Strictly ordered, single-transfer assembler with no native side effects.

    Corrupt/out-of-order data aborts assembly; a caller must explicitly begin a
    new transfer. reset is intended for transport disconnect/session replacement.
    Peer identity/document admission is performed by the transport/controller.
    """

    def __init__(self, *, max_bytes=MAX_BYTES, chunk_bytes=CHUNK_BYTES):
        if (type(max_bytes) is not int or not 0 < max_bytes <= MAX_BYTES
                or type(chunk_bytes) is not int or not 0 < chunk_bytes <= CHUNK_BYTES):
            raise WireError("invalid_limit")
        self.max_bytes, self.chunk_bytes = max_bytes, chunk_bytes
        self.reset()

    def reset(self):
        self._begin = None
        self._chunks = []
        self._received = 0

    @property
    def pending(self):
        return self._begin is not None

    def feed(self, payload):
        try:
            return self._feed(payload)
        except WireError:
            self.reset()
            raise

    def _feed(self, payload):
        if not isinstance(payload, Mapping):
            raise WireError("invalid_payload")
        phase = payload.get("phase")
        if not isinstance(phase, str) or phase not in {"begin", "chunk", "end"}:
            raise WireError("invalid_phase")
        request_id = _id(payload.get("request_id"))
        kind = payload.get("kind", "native.snapshot")
        if not isinstance(kind, str) or kind not in {"native.snapshot", "native.commit"}:
            raise WireError("invalid_kind")
        if phase == "begin":
            if self.pending:
                raise WireError("busy")
            if set(payload) - {"phase", "kind", "request_id", "total_bytes", "chunk_count",
                               "content_hash", "manifest", "active_scene_uuid", "head"}:
                raise WireError("invalid_payload")
            total, count = payload.get("total_bytes"), payload.get("chunk_count")
            if (type(total) is not int or not 0 < total <= self.max_bytes
                    or type(count) is not int or count != math.ceil(total / self.chunk_bytes)):
                raise WireError("transfer_limit")
            active = payload.get("active_scene_uuid")
            self._begin = {"request_id": request_id, "kind": kind,
                           "total_bytes": total, "chunk_count": count,
                           "content_hash": _hash(payload.get("content_hash")),
                           "manifest": _manifest(payload.get("manifest"), active),
                           "active_scene_uuid": active, "head": _head(payload.get("head"))}
            return None
        if not self.pending:
            raise WireError("no_pending_transfer")
        if (request_id, kind) != (self._begin["request_id"], self._begin["kind"]):
            raise WireError("wrong_transfer")
        if phase == "chunk":
            if set(payload) - {"phase", "kind", "request_id", "index", "data"}:
                raise WireError("invalid_payload")
            index = payload.get("index")
            if type(index) is not int or index != len(self._chunks):
                raise WireError("chunk_order")
            if index >= self._begin["chunk_count"]:
                raise WireError("chunk_order")
            data = decode_chunk(payload.get("data"), max_bytes=self.chunk_bytes)
            expected = min(self.chunk_bytes, self._begin["total_bytes"] - self._received)
            if len(data) != expected:
                raise WireError("chunk_size")
            self._chunks.append(data)
            self._received += len(data)
            return None
        if set(payload) - {"phase", "kind", "request_id"}:
            raise WireError("invalid_payload")
        if (self._received != self._begin["total_bytes"]
                or len(self._chunks) != self._begin["chunk_count"]):
            raise WireError("incomplete_transfer")
        data = b"".join(self._chunks)
        if hashlib.sha256(data).hexdigest() != self._begin["content_hash"]:
            raise WireError("hash_mismatch")
        result = {**self._begin, "data": data}
        self.reset()
        return result

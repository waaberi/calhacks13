"""Bounded admission for native checkpoint transfers; no Blender, files or sockets.

Fences are built from LIVE host/session/lease state, never accepted from wire
claims. Call sync_head with a fresh host checkpoint before admitting a transfer.
prepare is the mutation boundary: after it, failure/disconnection is UNKNOWN
until the host reconciles. This class never executes, retries or resends data.
"""

import hashlib
import re
from dataclasses import dataclass, field

_ID = re.compile(r"[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class Refused(ValueError):
    """A stable local error code, suitable for an existing typed error response."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Fence:
    session_id: str
    host_epoch: str
    document_id: str
    open_epoch: str
    actor_id: str
    can_edit: bool = False
    connected: bool = True
    lease_id: str = ""
    lease_owner: str = ""
    lease_mode: str = ""
    lease_current: bool = False


@dataclass(frozen=True)
class Receipt:
    request_id: str
    actor_id: str
    outcome: str
    revision: int | None = None
    checkpoint_hash: str = ""
    code: str = ""


@dataclass(frozen=True)
class Checkpoint:
    request_id: str
    actor_id: str
    base_revision: int
    base_hash: str
    content_hash: str
    data: bytes


@dataclass
class _Transfer:
    request_id: str
    actor_id: str
    lease_id: str
    base_revision: int
    base_hash: str
    content_hash: str
    total_bytes: int
    chunk_count: int
    chunks: dict = field(default_factory=dict)
    received_bytes: int = 0
    applying: bool = False

    @property
    def signature(self):
        return (self.actor_id, self.lease_id, self.base_revision, self.base_hash,
                self.content_hash, self.total_bytes, self.chunk_count)


class NativeSyncState:
    """One receiving/applying checkpoint, a CAS head and bounded receipt ledger.

    Completed IDs are retained, rather than evicted and accidentally executable
    again. Admission refuses when max_receipts is reached. A new host incarnation
    uses a new instance and old-incarnation requests fail its identity fence.
    An unrecognized receipt query reports UNKNOWN, never claims "not applied".
    """

    def __init__(self, *, session_id, host_epoch, document_id, open_epoch,
                 revision, checkpoint_hash, max_bytes=256 * 1024 * 1024,
                 max_chunk_bytes=256 * 1024, max_chunks=4096, max_receipts=4096):
        for value in (session_id, host_epoch, document_id, open_epoch):
            self._id(value)
        self._head(revision, checkpoint_hash)
        for value in (max_bytes, max_chunk_bytes, max_chunks, max_receipts):
            if type(value) is not int or value <= 0:
                raise Refused("invalid_limit")
        self.session_id, self.host_epoch = session_id, host_epoch
        self.document_id, self.open_epoch = document_id, open_epoch
        self.revision, self.checkpoint_hash = revision, checkpoint_hash
        self.max_bytes, self.max_chunk_bytes = max_bytes, max_chunk_bytes
        self.max_chunks, self.max_receipts = max_chunks, max_receipts
        self.pending = None
        self._receipts = {}
        self._signatures = {}
        self._uncertain = set()

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise Refused("invalid_id")

    @staticmethod
    def _head(revision, checkpoint_hash):
        if type(revision) is not int or revision < 0:
            raise Refused("invalid_revision")
        if not isinstance(checkpoint_hash, str) or not _HASH.fullmatch(checkpoint_hash):
            raise Refused("invalid_hash")

    def _fence(self, fence, *, write=False, lease_id=None):
        if (fence.session_id, fence.host_epoch) != (self.session_id, self.host_epoch):
            raise Refused("wrong_session")
        if (fence.document_id, fence.open_epoch) != (self.document_id, self.open_epoch):
            raise Refused("wrong_document")
        self._id(fence.actor_id)
        if not fence.connected:
            raise Refused("disconnected")
        if write:
            if not fence.can_edit:
                raise Refused("permission_denied")
            if (not fence.lease_current or fence.lease_mode != "exclusive"
                    or fence.lease_owner != fence.actor_id):
                raise Refused("lease_conflict")
            self._id(fence.lease_id)
            if lease_id is not None and lease_id != fence.lease_id:
                raise Refused("stale_lease")

    def sync_head(self, revision, checkpoint_hash):
        """Set the freshly observed HOST head; never use a peer's re-export hash.

        A changed native graph must advance the canonical revision. File hashes
        from different Blender processes need not agree after native application.
        """
        self._head(revision, checkpoint_hash)
        if revision < self.revision:
            raise Refused("revision_regressed")
        if revision == self.revision and checkpoint_hash != self.checkpoint_hash:
            raise Refused("unversioned_change")
        self.revision, self.checkpoint_hash = revision, checkpoint_hash

    def _pending(self, request_id, fence, *, baseline=True):
        self._id(request_id)
        pending = self.pending
        if pending is None or pending.request_id != request_id:
            raise Refused("no_pending_transfer")
        self._fence(fence, write=True, lease_id=pending.lease_id)
        if pending.actor_id != fence.actor_id:
            raise Refused("wrong_actor")
        if baseline and (self.revision, self.checkpoint_hash) != (
                pending.base_revision, pending.base_hash):
            raise Refused("stale_revision")
        return pending

    def begin(self, request_id, fence, *, base_revision, base_hash, content_hash,
              total_bytes, chunk_count):
        self._id(request_id)
        self._fence(fence, write=True)
        self._head(base_revision, base_hash)
        self._head(base_revision, content_hash)
        if (type(total_bytes) is not int or not 0 < total_bytes <= self.max_bytes
                or type(chunk_count) is not int
                or not 0 < chunk_count <= min(self.max_chunks, total_bytes)
                or total_bytes > chunk_count * self.max_chunk_bytes):
            raise Refused("transfer_limit")
        signature = (fence.actor_id, fence.lease_id, base_revision, base_hash,
                     content_hash, total_bytes, chunk_count)
        if request_id in self._receipts:
            if self._signatures[request_id] != signature:
                raise Refused("duplicate_request")
            return self.query(request_id, fence)
        if request_id in self._uncertain or self._uncertain:
            raise Refused("unknown_outcome")
        if self.pending is not None:
            if self.pending.request_id == request_id:
                if self.pending.signature != signature:
                    raise Refused("duplicate_request")
                return Receipt(request_id, fence.actor_id, "pending")
            raise Refused("busy")
        if len(self._receipts) >= self.max_receipts:
            raise Refused("receipt_capacity")
        if (base_revision, base_hash) != (self.revision, self.checkpoint_hash):
            raise Refused("stale_revision")
        self.pending = _Transfer(request_id, fence.actor_id, fence.lease_id,
                                 base_revision, base_hash, content_hash,
                                 total_bytes, chunk_count)
        return Receipt(request_id, fence.actor_id, "pending")

    def chunk(self, request_id, fence, index, data):
        pending = self._pending(request_id, fence)
        if pending.applying:
            raise Refused("already_prepared")
        if (type(index) is not int or not 0 <= index < pending.chunk_count
                or type(data) is not bytes or not 0 < len(data) <= self.max_chunk_bytes):
            raise Refused("invalid_chunk")
        if index in pending.chunks:
            if pending.chunks[index] != data:
                raise Refused("duplicate_chunk")
            return pending.received_bytes
        if pending.received_bytes + len(data) > pending.total_bytes:
            raise Refused("transfer_limit")
        pending.chunks[index] = data
        pending.received_bytes += len(data)
        return pending.received_bytes

    def prepare(self, request_id, fence):
        """Validate bytes and cross into APPLYING once; caller now owns mutation.

        A duplicate prepare is refused, so a retried message cannot apply twice.
        The caller must finish with applied/rejected/unknown; reconnect is no retry.
        """
        pending = self._pending(request_id, fence)
        if pending.applying:
            raise Refused("already_prepared")
        if (len(pending.chunks) != pending.chunk_count
                or pending.received_bytes != pending.total_bytes):
            raise Refused("incomplete_transfer")
        data = b"".join(pending.chunks[index] for index in range(pending.chunk_count))
        if hashlib.sha256(data).hexdigest() != pending.content_hash:
            raise Refused("hash_mismatch")
        pending.applying = True
        pending.chunks.clear()
        return Checkpoint(request_id, pending.actor_id, pending.base_revision,
                          pending.base_hash, pending.content_hash, data)

    def _finish(self, pending, outcome, *, revision=None, checkpoint_hash="", code=""):
        receipt = Receipt(pending.request_id, pending.actor_id, outcome,
                          revision, checkpoint_hash, code)
        self._receipts[pending.request_id] = receipt
        self._signatures[pending.request_id] = pending.signature
        if outcome == "unknown":
            self._uncertain.add(pending.request_id)
        self.pending = None
        return receipt

    def applied(self, request_id, fence, *, revision, checkpoint_hash):
        """Record verified local apply; its fresh export hash may differ from input."""
        pending = self._pending(request_id, fence, baseline=False)
        if not pending.applying:
            raise Refused("not_prepared")
        self._head(revision, checkpoint_hash)
        if revision <= pending.base_revision:
            raise Refused("revision_not_advanced")
        if (self.revision, self.checkpoint_hash) not in (
                (pending.base_revision, pending.base_hash), (revision, checkpoint_hash)):
            raise Refused("stale_revision")
        self.sync_head(revision, checkpoint_hash)
        return self._finish(pending, "applied", revision=revision,
                            checkpoint_hash=checkpoint_hash)

    def rejected(self, request_id, fence, *, code="rejected", rollback_verified=False):
        """An applying transfer may reject only after independently verified rollback."""
        pending = self._pending(request_id, fence, baseline=False)
        if pending.applying and not rollback_verified:
            raise Refused("rollback_unverified")
        return self._finish(pending, "rejected", code=code)

    def unknown(self, request_id, *, code="apply_unverified"):
        """Host-internal failure path, including actor departure during native apply."""
        if self.pending is None or self.pending.request_id != request_id:
            raise Refused("no_pending_transfer")
        return self._finish(self.pending, "unknown", code=code)

    def abort(self, request_id, code="aborted", rollback_verified=False):
        """Host-internal cleanup after timeout, lost permission or an expired lease.

        Receiving has not changed native state and may safely reject. After
        prepare, abort stays UNKNOWN unless the host independently proves rollback.
        It does not need the departed actor's permission or stale lease to clean up.
        """
        if self.pending is None or self.pending.request_id != request_id:
            raise Refused("no_pending_transfer")
        if self.pending.applying and not rollback_verified:
            return self.unknown(request_id, code=code)
        return self._finish(self.pending, "rejected", code=code)

    def disconnected(self, actor_id):
        """Never resend a draft or an uncertain applying transfer on reconnect."""
        pending = self.pending
        if pending is None or pending.actor_id != actor_id:
            return None
        if pending.applying:
            return self.unknown(pending.request_id, code="connection_lost_during_apply")
        return self._finish(pending, "rejected", code="connection_lost_before_apply")

    def cancel(self, request_id, fence):
        pending = self._pending(request_id, fence, baseline=False)
        if pending.applying:
            raise Refused("too_late")
        return self._finish(pending, "rejected", code="cancelled_before_apply")

    def query(self, request_id, fence):
        self._id(request_id)
        self._fence(fence)
        receipt = self._receipts.get(request_id)
        if receipt is not None:
            if receipt.actor_id != fence.actor_id:
                raise Refused("wrong_actor")
            return receipt
        if self.pending is not None and self.pending.request_id == request_id:
            if self.pending.actor_id != fence.actor_id:
                raise Refused("wrong_actor")
            return Receipt(request_id, fence.actor_id, "pending")
        return Receipt(request_id, fence.actor_id, "unknown", code="receipt_unavailable")

    def acknowledge_unknown(self, request_id, fence, *, revision, checkpoint_hash):
        """Explicit checked-scene acknowledgement; never converts unknown to applied."""
        receipt = self.query(request_id, fence)
        if receipt.outcome != "unknown" or request_id not in self._uncertain:
            raise Refused("not_unknown")
        if (revision, checkpoint_hash) != (self.revision, self.checkpoint_hash):
            raise Refused("stale_revision")
        self._uncertain.remove(request_id)
        return receipt

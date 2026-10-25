"""Settled native checkpoint scheduling, independent of Blender and transport.

The caller owns authority, file lifetimes and native rollback. A checkpoint is an
optimistic local draft until acknowledged. A rejected/unknown draft is retained
and never retried automatically. Hashes describe this peer's own saved bytes;
they are not compared with a different peer's reserialized .blend bytes.
"""

import math
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

_SHA256 = re.compile(r"[0-9a-fA-F]{64}")


def _digest(value):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("Expected a local checkpoint SHA256")
    return value.lower()


def _time(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected a finite monotonic time")
    return float(value)


@dataclass(frozen=True)
class PendingCheckpoint:
    request_id: str
    checkpoint_hash: str
    payload: Any


class NativeChangeTracker:
    """Coalesce dirty signals until native editing is safe and quiet.

    ``poll(now, safe, export_fn)`` calls ``export_fn()`` only at a safe boundary.
    It returns one PendingCheckpoint, then waits for its explicit outcome.
    ``safe`` must be false during Edit Mode, a transform modal, remote apply,
    unstable native context, or any authority gate the integration requires.
    """

    def __init__(self, quiet_seconds=0.25, *, clock=time.monotonic):
        self.quiet_seconds = _time(quiet_seconds)
        if self.quiet_seconds < 0:
            raise ValueError("Quiet interval cannot be negative")
        self._clock = clock
        self._baseline_hash = None
        self._baseline_epoch = 0
        self._dirty = False
        self._last_dirty = None
        self._generation = 0
        self._pending = None
        self._pending_generation = None
        self._pending_baseline_epoch = None
        self._rejection = None
        self._retained_draft = None

    @property
    def baseline_hash(self):
        return self._baseline_hash

    @property
    def dirty(self):
        return self._dirty

    @property
    def pending(self):
        return self._pending

    @property
    def in_flight(self):
        return self._pending is not None and self._rejection is None

    @property
    def rejection(self):
        return self._rejection

    @property
    def retained_draft(self):
        """Rejected snapshot retained until explicit discard or replacement."""
        return self._retained_draft

    @property
    def has_local_changes(self):
        return self._dirty or self._pending is not None or self._retained_draft is not None

    def mark_dirty(self, now=None):
        self._last_dirty = _time(self._clock() if now is None else now)
        self._generation += 1
        self._dirty = True

    def poll(self, now, safe, export_fn):
        """Export once after settling; retain newer dirty signals during export.

        export_fn returns ``(local_sha256, payload)``. A failure leaves the dirty
        state intact and is raised to the caller. No network operation occurs.
        """
        now = _time(now)
        if self._pending is not None or not self._dirty or not safe:
            return None
        if now - self._last_dirty < self.quiet_seconds:
            return None
        generation, baseline_epoch = self._generation, self._baseline_epoch
        digest, payload = export_fn()
        digest = _digest(digest)
        if digest == self._baseline_hash:
            if generation == self._generation:
                self._dirty = False
            return None  # remote apply / Undo / no-op returned to our own baseline
        self._pending = PendingCheckpoint(uuid.uuid4().hex, digest, payload)
        self._pending_generation = generation
        self._pending_baseline_epoch = baseline_epoch
        self._rejection = None
        self._retained_draft = None
        self._dirty = generation != self._generation
        return self._pending

    def applied_local_baseline(self, checkpoint_hash):
        """Record bytes saved locally after apply without discarding local work.

        Do not pass the sending peer's file hash here: reserialization can differ
        across peers. Dirty/queued/rejected drafts remain intact. A later settled
        export equal to this baseline suppresses an application-induced echo.
        """
        self._baseline_hash = _digest(checkpoint_hash)
        self._baseline_epoch += 1

    def _request(self, request_id):
        if self._pending is None or self._pending.request_id != request_id:
            raise ValueError("Outcome does not match the pending native checkpoint")
        return self._pending

    def acknowledge(self, request_id):
        """Acknowledge this exact request; never erase changes made after export."""
        draft = self._request(request_id)
        if self._pending_baseline_epoch == self._baseline_epoch:
            self._baseline_hash = draft.checkpoint_hash
            self._baseline_epoch += 1
        else:
            # A newer remote apply already established another local baseline.
            # Keep it, then inspect the actual current document after settling.
            self._dirty = True
        self._pending = None
        self._pending_generation = None
        self._pending_baseline_epoch = None
        self._rejection = None
        self._retained_draft = None
        return draft

    def reject(self, request_id, reason="rejected"):
        """Retain a rejected/conflicting/unknown draft; block automatic replay."""
        draft = self._request(request_id)
        if not isinstance(reason, str) or not reason:
            raise ValueError("Rejection needs a reason")
        self._rejection = reason
        self._retained_draft = draft
        return draft

    def retry(self, now=None):
        """Explicitly retry after resolution, exporting fresh current native data.

        The prior rejected payload remains available until a replacement export
        exists. Never use this for an unresolved unknown network outcome.
        """
        if self._pending is None or self._rejection is None:
            raise ValueError("Only a rejected native draft can be retried")
        self._pending = None
        self._pending_generation = None
        self._pending_baseline_epoch = None
        self._rejection = None
        self.mark_dirty(now)

    def discard(self, local_baseline_hash):
        """After caller restores/chooses native data, explicitly discard its draft.

        This method does not mutate Blender. The supplied hash must describe the
        caller's verified current local checkpoint. An in-flight outcome must be
        resolved first; disconnect alone does not make its outcome known.
        """
        if self.in_flight:
            raise ValueError("Resolve the in-flight native request before discarding")
        digest = _digest(local_baseline_hash)
        self._baseline_hash = digest
        self._baseline_epoch += 1
        self._pending = None
        self._pending_generation = None
        self._pending_baseline_epoch = None
        self._retained_draft = None
        self._rejection = None
        self._dirty = False
        self._last_dirty = None
        self._generation += 1

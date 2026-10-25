"""Original native document Client, using acknowledged exclusive editing turns.

This controller owns no socket or bpy call directly. The native document adapter
performs file operations on Blender's main thread. A refused or disconnected
upload remains a local draft; an incoming snapshot never overwrites that draft.
Automatic receives also audit this peer's current saved bytes before applying.
UI-only byte changes can conservatively pause receiving; explicit backed-up
reload resolves that case. This is a preservation fence, not a semantic hash.
"""

import json
import re
import time
from pathlib import Path

from .. import protocol
from . import wire
from .watcher import NativeChangeTracker

_ID = re.compile(r"[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_IDENTITY = ("session_id", "host_epoch", "document_id", "open_epoch")


class NativeClient:
    def __init__(self, document, send_message, directory, *, clock=time.monotonic,
                 quiet_seconds=.25):
        self.document, self.send_message = document, send_message
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.capture_path = self.directory / "checkpoint.blend"
        self.clock = clock
        self._epoch = 0
        self.watcher = NativeChangeTracker(quiet_seconds, clock=clock)
        self.receiver = wire.ChunkReceiver()
        self.enabled = self.connected = self.can_edit = False
        self.has_native_document = self.applying = False
        self._capturing = False
        self.initial_local_work = False
        self._initial_baseline_hash = None
        self._incoming_conflict = False
        self.identity, self.actor_id = {}, ""
        self.head = self.applied_head = None
        self.lease_id = ""
        self._lease_request = None
        self._ready_edit = self._want_edit = self._finish_requested = False
        self._release_sent = self._discard_next = False
        self._download = self._outgoing = None
        self._download_failed = False
        self._upload_stage = ""
        self._get_pending = False
        self._messages = {}
        self._last_upload = self._last_query = 0.0
        self.status = "Native sharing disconnected; local document is preserved"
        self.error = ""

    @property
    def is_editing(self):
        return bool(self.connected and self.enabled and self._ready_edit and self.lease_id
                    and not self._release_sent and not self.applying)

    def _send(self, kind, payload):
        msg = protocol.message(kind, payload)
        if not self.send_message(msg):
            self.disconnect()
            return None
        self._messages[msg["id"]] = kind
        if len(self._messages) > 8192:
            self._messages.pop(next(iter(self._messages)))
        return msg["id"]

    def _fields(self):
        return {**self.identity, "actor_id": self.actor_id, "lease_id": self.lease_id}

    def welcome(self, payload):
        self._epoch += 1
        self.receiver.reset()
        self._download = self._outgoing = None
        self._download_failed = False
        self._upload_stage = ""
        self._get_pending = False
        self._lease_request = None
        self.lease_id = ""
        self._ready_edit = self._want_edit = self._release_sent = False
        self._finish_requested = False
        self._discard_next = False
        self.enabled = payload.get("capabilities", {}).get("native_sync") is True
        if not self.enabled:
            self.connected = False
            self.status = "Host needs native sharing enabled; no limited mirror was substituted"
            return
        doc = payload["document"]
        identity = {"session_id": payload["session_id"], "host_epoch": payload["host_epoch"],
                    "document_id": doc["id"], "open_epoch": doc["open_epoch"]}
        if not all(isinstance(value, str) and _ID.fullmatch(value) for value in identity.values()):
            raise ValueError("Invalid native session identity")
        actor = payload["actor_id"]
        if not isinstance(actor, str) or not _ID.fullmatch(actor):
            raise ValueError("Invalid native actor")
        self.identity, self.actor_id = identity, actor
        self.connected, self.can_edit = True, payload.get("can_edit") is True
        self.head = self.applied_head = None
        self.status = "Receiving original Blender document"
        self.error = ""
        if not self.has_native_document:
            # The connection was admitted into an empty session. Remember its
            # complete LOCAL bytes after the temporary mirror was removed, so
            # even an unreferenced material added before the first packet is
            # protected. Objects/filepath are independently checked at apply.
            if not self.document.is_empty_session():
                self.initial_local_work = self._incoming_conflict = True
                self.watcher.mark_dirty(self.clock())
                self.error = "Local work appeared before initial sharing; it will not be replaced"
            else:
                try:
                    self._initial_baseline_hash = self._capture().sha256
                except (OSError, RuntimeError, ValueError):
                    self._initial_baseline_hash = None
                    self.error = "Initial local checkpoint could not be verified; incoming data will wait"
        self._request_snapshot()

    def _request_snapshot(self):
        if not self.connected or not self.enabled or self._get_pending or self.applying:
            return False
        if self._send("native.get", self.identity) is None:
            return False
        self._get_pending = True
        return True

    def _head(self, value):
        if not isinstance(value, dict) or any(value.get(k) != self.identity.get(k) for k in _IDENTITY):
            raise ValueError("Native head belongs to another session or document")
        if (type(value.get("revision")) is not int or value["revision"] < 0
                or not isinstance(value.get("checkpoint_hash"), str)
                or not _HASH.fullmatch(value["checkpoint_hash"])):
            raise ValueError("Invalid native head")
        return {key: value[key] for key in (*_IDENTITY, "revision", "checkpoint_hash")}

    def mark_dirty(self, now=None):
        if ((self.has_native_document or self.initial_local_work)
                and not self.applying and not self._capturing):
            self.watcher.mark_dirty(self.clock() if now is None else now)

    def take_edit_turn(self):
        if not self.connected or not self.can_edit or not self.enabled or self.head is None:
            self.error = "Wait for the host's original document and edit permission"
            return False
        if self.watcher.has_local_changes:
            self.error = "Local draft retained; save a copy or explicitly reload the host first"
            return False
        if self.lease_id or self._lease_request or self.applying:
            return False
        self._want_edit = True
        self._lease_request = self._send("lease.acquire", {
            **self.identity, "actor_id": self.actor_id, "mode": "exclusive", "targets": []})
        self.status = "Requesting an exclusive native edit turn"
        return self._lease_request is not None

    def finish_edit_turn(self):
        if not self.is_editing or self.watcher.rejection:
            return False
        self._finish_requested = True
        self.watcher.mark_dirty(self.clock())
        self.status = "Finishing native edits; waiting for a settled checkpoint"
        return True

    def _release(self):
        if self.lease_id and not self._release_sent:
            if self._send("lease.release", {"lease_id": self.lease_id}) is None:
                return
            self._release_sent = True
            self._ready_edit = self._want_edit = False
            self._finish_requested = False
            self.status = "Releasing native edit turn"

    def _retain(self):
        draft = self.watcher.pending or self.watcher.retained_draft
        if draft is None:
            return
        path = self.directory / ("draft-" + draft.request_id + ".blend")
        path.write_bytes(draft.payload.data)
        path.with_suffix(".json").write_text(json.dumps({"request_id": draft.request_id,
            "local_hash": draft.checkpoint_hash, "head": self.head,
            "reason": self.watcher.rejection}, indent=2), encoding="utf-8")

    def disconnect(self):
        self._epoch += 1
        self.connected = False
        self._ready_edit = self._want_edit = False
        self._release_sent = self._finish_requested = False
        self._lease_request = None
        self.lease_id = ""
        self.receiver.reset()
        self._download = self._outgoing = None
        self._get_pending = False
        self._upload_stage = ""
        self._discard_next = False
        if self.watcher.pending is not None:
            self.watcher.reject(self.watcher.pending.request_id, "unknown_after_disconnect")
            self._retain()
        self.status = "Disconnected; native document and local drafts are preserved"

    def reload_host(self, *, discard=False):
        if not self.connected or self.applying or self.watcher.in_flight:
            self.error = "Resolve the pending native outcome before reloading"
            return False
        if self.watcher.has_local_changes and not discard:
            self.error = "Local native work must be saved or explicitly discarded first"
            return False
        self._retain()
        self._discard_next = discard
        self._get_pending = False
        self._download = None
        self._download_failed = False
        self.receiver.reset()
        return self._request_snapshot()

    def save_copy(self, path):
        # A retained upload may predate edits made while its ACK was pending.
        # Save the actual current native document; the immutable older draft is
        # separately retained in draft-<request_id>.blend after refusal/drop.
        snapshot = self._capture()
        Path(path).write_bytes(snapshot.data)

    def receive(self, kind, payload):
        if not self.enabled:
            return
        if kind == "lease.granted":
            reply_to, body = payload if isinstance(payload, tuple) else (None, payload)
            lease = body.get("lease", {})
            if self._lease_request is None or (reply_to and reply_to != self._lease_request):
                return
            if (lease.get("mode") != "exclusive"
                    or lease.get("owner", {}).get("actor_id") != self.actor_id
                    or not isinstance(lease.get("lease_id"), str)
                    or not _ID.fullmatch(lease["lease_id"])):
                raise ValueError("Invalid native edit turn grant")
            self._lease_request = None
            self.lease_id = lease["lease_id"]
            self.status = "Edit turn granted; refreshing original data before editing"
            self._get_pending = False
            self._request_snapshot()
        elif kind == "session.update":
            if self.lease_id and not any(lease.get("lease_id") == self.lease_id
                    and lease.get("owner", {}).get("actor_id") == self.actor_id
                    and lease.get("mode") == "exclusive" for lease in payload.get("leases", [])):
                self.lease_id = ""
                self._ready_edit = self._want_edit = self._release_sent = False
                self.status = "Native edit turn ended; current local document is preserved"
        elif kind == "native.head":
            head = self._head(payload)
            if self.head is not None and head["revision"] < self.head["revision"]:
                return
            if (self.head is not None and head["revision"] == self.head["revision"]
                    and head["checkpoint_hash"] != self.head["checkpoint_hash"]):
                raise ValueError("Native revision changed without advancing")
            self.head = head
            if not self.is_editing and not self.watcher.has_local_changes:
                self._request_snapshot()
        elif kind == "native.snapshot":
            complete = self.receiver.feed(payload)
            if complete is not None:
                complete["head"] = self._head(complete["head"])
                self._get_pending = False
                self._download = complete
        elif kind == "native.receipt":
            self._receipt(payload)
        elif kind == "reply_error":
            request_id, code = payload
            if request_id == self._lease_request:
                self._lease_request = None
                self._want_edit = False
                self.error = "Native edit turn refused (" + code + ")"
                self.status = "Another writer may hold the document"

    def _receipt(self, payload):
        pending = self.watcher.pending
        if pending is None or payload.get("request_id") != pending.request_id:
            if payload.get("outcome") == "rejected":
                self._get_pending = False
                self.error = "Native host request refused (" + str(payload.get("code", "rejected")) + ")"
            return
        outcome = payload.get("outcome")
        if outcome == "pending":
            if self._upload_stage == "begin_wait":
                self._upload_stage = "chunks"
            return
        if outcome == "applied":
            revision, digest = payload.get("revision"), payload.get("checkpoint_hash")
            if (type(revision) is not int or revision < 0 or not isinstance(digest, str)
                    or not _HASH.fullmatch(digest)):
                raise ValueError("Invalid native applied receipt")
            self.watcher.acknowledge(pending.request_id)
            acknowledged_head = {**self.identity, "revision": revision, "checkpoint_hash": digest}
            if self.head is None or revision >= self.head["revision"]:
                self.head = acknowledged_head
            self.applied_head = dict(acknowledged_head)
            self._outgoing, self._upload_stage = None, ""
            self.status, self.error = "Native checkpoint acknowledged by host", ""
        elif outcome in {"rejected", "unknown"}:
            self.watcher.reject(pending.request_id, str(payload.get("code") or outcome))
            self._retain()
            self._outgoing, self._upload_stage = None, ""
            self.error = "Native draft retained (" + (self.watcher.rejection or outcome) + ")"
            self.status = "Save a copy before resolving the conflict; no edit is replayed"

    def _export(self):
        snapshot = self._capture()
        return snapshot.sha256, snapshot

    def _capture(self):
        # Capture flushes this main thread's BMesh and updates its view layer.
        # Those own synchronous callbacks are not new user edits. Suppress only
        # this bounded adapter operation; keep the pure tracker's generation
        # fence intact for genuine changes outside our own capture.
        if self._capturing:
            raise RuntimeError("A native checkpoint capture is already running")
        self._capturing = True
        try:
            return self.document.capture(self.capture_path)
        finally:
            self._capturing = False

    def _can_capture(self):
        # Authors may finish a native Edit Mode operation without leaving Edit
        # Mode. The adapter flushes settled BMesh data into the checkpoint. A
        # received foreign graph still requires the stricter is_idle() gate.
        can_capture = getattr(self.document, "can_capture", self.document.is_idle)
        return can_capture()

    def _start_upload(self, pending):
        # An announced Host head is not yet this peer's native baseline. Local
        # edits remain based on the last applied/acknowledged checkpoint, so a
        # concurrent Host edit must produce a CAS rejection, never get adopted as
        # the base of an older local draft.
        base = self.applied_head
        if base is None:
            self.watcher.reject(pending.request_id, "missing_native_baseline")
            self._retain()
            self.error = "Native baseline is unavailable; local draft was retained"
            return
        messages = iter(wire.iter_messages(pending.payload, base,
                        request_id=pending.request_id, kind="native.commit"))
        begin = next(messages)
        payload = {**self._fields(), "request_id": pending.request_id,
            "base_revision": base["revision"], "base_hash": base["checkpoint_hash"],
            **{key: begin[key] for key in ("content_hash", "total_bytes", "chunk_count",
                                           "manifest", "active_scene_uuid")}}
        self._outgoing, self._upload_stage = messages, "begin_wait"
        self._last_upload = self.clock()
        self._send("native.begin", payload)
        self.status = "Sending original Blender checkpoint"

    def _apply_download(self):
        complete = self._download
        if complete is None or self._download_failed or not self.document.is_idle() or self.applying:
            return
        if self.watcher.has_local_changes and not self._discard_next:
            self.error = "Incoming host checkpoint waits; local native draft is preserved"
            return
        if self.head is not None and complete["head"]["revision"] < self.head["revision"]:
            self._download = None
            self._request_snapshot()
            return
        if not self._discard_next:
            if not self.has_native_document and not self.document.is_empty_session():
                self.initial_local_work = self._incoming_conflict = True
                self.watcher.mark_dirty(self.clock())
                self.error = "Local objects or a file appeared before initial sharing; incoming data waits"
                return
            baseline = (self.watcher.baseline_hash if self.has_native_document
                        else self._initial_baseline_hash)
            if baseline is None:
                self.error = "Local checkpoint baseline is unverified; incoming native data waits"
                return
            try:
                current = self._capture()
                if current.sha256 != baseline:
                    (self.directory / ("before-incoming-" + complete["request_id"] + ".blend")).write_bytes(current.data)
                    self.initial_local_work = not self.has_native_document
                    self._incoming_conflict = True
                    self.watcher.mark_dirty(self.clock())
                    self.error = "Unannounced local changes were backed up; incoming native data waits"
                    return
            except (OSError, RuntimeError, ValueError):
                self.error = "Current local checkpoint could not be verified; incoming data was not applied"
                return
        if self._discard_next:
            # Explicit reload is destructive to the current local graph. Keep
            # its latest settled state as well as any earlier in-flight draft.
            # A failed backup must leave the current graph untouched.
            try:
                backup = self._capture()
                (self.directory / ("before-reload-" + complete["request_id"] + ".blend")).write_bytes(backup.data)
            except (OSError, RuntimeError, ValueError):
                self.error = "Current local work could not be backed up; reload was not applied"
                return
        self._download = None
        self.applying = True
        epoch = self._epoch
        discard_requested = self._discard_next
        path = self.directory / ("incoming-" + complete["request_id"] + ".blend")
        self.status = "Applying original Blender document atomically"

        def done(_report=None):
            try:
                self.has_native_document = True
                local = self._capture()
                if epoch != self._epoch or not self.connected:
                    # The native transaction must finish safely, but an older
                    # connection cannot authorize editing or replace a newer
                    # session's canonical metadata. Its current local bytes are
                    # still a valid echo baseline, without discarding drafts.
                    self.watcher.applied_local_baseline(local.sha256)
                    self.status = ("Previous received data settled; waiting for the current host"
                                   if self.connected else
                                   "Disconnected; native document and local drafts are preserved")
                    return
                if discard_requested:
                    self.watcher.discard(local.sha256)
                else:
                    self.watcher.applied_local_baseline(local.sha256)
                self.head = self.applied_head = dict(complete["head"])
                self._ready_edit = bool(self.lease_id and self._want_edit)
                self._discard_next = False
                self.initial_local_work = self._incoming_conflict = False
                self._initial_baseline_hash = None
                self.status = "Your native Blender edit turn" if self._ready_edit else "Original Blender document is current; take an edit turn to share changes"
                self.error = ""
            except (OSError, RuntimeError, ValueError):
                if epoch == self._epoch:
                    self._download_failed = True
                self._ready_edit = False
                self.error = "Native data arrived, but its local baseline could not be saved"
                self.status = "Current document is retained; resolve the local file error before reloading"
            finally:
                self.applying = False

        def failed(_error):
            self.applying = False
            if epoch == self._epoch:
                self._download = complete
                self._download_failed = True
            self._ready_edit = False
            self.error = "Native apply failed; current document and checkpoint files are retained"
            self.status = "Inspect saved copies before reconnecting"

        try:
            path.write_bytes(complete["data"])
            self.document.apply(path, complete["manifest"], done, failed,
                                active_scene_uuid=complete["active_scene_uuid"])
        except (OSError, RuntimeError, ValueError):
            failed(None)

    def tick(self):
        if not self.enabled or not self.connected or self.applying:
            return
        self._apply_download()
        if self.applying:
            return
        now = self.clock()
        if self.has_native_document or self.initial_local_work:
            pending = self.watcher.poll(now, self._can_capture(), self._export)
            if pending is not None:
                if self._incoming_conflict:
                    self.watcher.reject(pending.request_id, "local_changes_before_receive")
                    self._retain()
                    self.error = "Incoming native data waits; unannounced local draft was retained"
                elif self.is_editing and self.can_edit:
                    self._start_upload(pending)
                else:
                    self.watcher.reject(pending.request_id, "edit_turn_required")
                    self._retain()
                    self.error = "Local draft retained; take an edit turn before native editing"
        if self._outgoing is not None and self._upload_stage == "chunks":
            part = next(self._outgoing)
            fields = {**self._fields(), "request_id": part["request_id"]}
            if part["phase"] == "chunk":
                self._send("native.chunk", {**fields, "index": part["index"], "data": part["data"]})
            else:
                self._send("native.commit", fields)
                self._outgoing, self._upload_stage = None, "commit_wait"
            self._last_upload = now
        if (self.watcher.in_flight and self._upload_stage in {"begin_wait", "commit_wait"}
                and now - max(self._last_upload, self._last_query) > 15):
            self._send("native.query", {**self._fields(), "request_id": self.watcher.pending.request_id})
            self._last_query = now
        if self._finish_requested and not self.watcher.has_local_changes and self._can_capture():
            self._release()

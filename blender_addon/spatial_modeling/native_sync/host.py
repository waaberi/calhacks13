"""Host endpoint for original-data checkpoints, on Blender's main thread.

The existing session owns actors and exclusive edit turns. This endpoint adds
bounded file transfers and a separate whole-document revision: the viewport
snapshot revision cannot detect every material, rig or custom-property edit.
"""

import hashlib
import json
import time
from collections import ChainMap
from dataclasses import asdict
from itertools import chain
from pathlib import Path
from tempfile import TemporaryDirectory

from .. import protocol
from .state import Fence, NativeSyncState, Refused


class NativeHost:
    def __init__(self, session, document, scene_sync, native_document=None):
        if native_document is None:
            from .document import NativeDocument
            native_document = NativeDocument()
        self.session, self.document, self.scene_sync = session, document, scene_sync
        self.native = native_document
        self.folder = TemporaryDirectory(prefix="spatial-native-host-")
        self.path = Path(self.folder.name) / "checkpoint.blend"
        self.upload = Path(self.folder.name) / "received.blend"
        self.snapshot = self.state = None
        self.subscribers = set()
        self.outgoing = {}
        self.manifests = {}
        self._metadata = {}  # same bounded lifetime as the state's receipt IDs
        self.busy = False
        self.dirty = True
        self.last_dirty = self.next_audit = 0.0
        self.last_upload = 0.0
        self.error = ""
        self._srv = None
        self._hooked = False

    def attach(self, srv):
        self._srv = srv
        handlers = {"native.get": self.get, "native.begin": self.begin,
                    "native.chunk": self.chunk, "native.commit": self.commit,
                    "native.query": self.query, "native.cancel": self.cancel}
        srv.handlers = ChainMap({k: self._guard(v) for k, v in handlers.items()}, srv.handlers)
        previous = srv.on_disconnect

        def disconnected(conn):
            actor = self.session.participants.get(conn)
            if self.state is not None and actor is not None:
                pending = self.state.pending
                self.state.disconnected(actor["actor_id"])
                if pending is not None and pending.actor_id == actor["actor_id"]:
                    self.manifests.pop(pending.request_id, None)
            self.subscribers.discard(conn)
            self.outgoing.pop(conn, None)
            if previous is not None:
                previous(conn)
        srv.on_disconnect = disconnected
        srv.native_sync = self
        return srv

    def _guard(self, fn):
        def handle(msg, conn):
            try:
                if conn not in self.session.participants or conn.closing:
                    raise Refused("permission_denied")
                return fn(msg, conn)
            except (Refused, ValueError, TypeError, KeyError) as exc:
                code = exc.code if isinstance(exc, Refused) else "invalid_message"
                return protocol.message("native.receipt", {
                    "request_id": msg["payload"].get("request_id", msg["id"]),
                    "outcome": "rejected", "code": code}, re=msg["id"])
            except (OSError, RuntimeError):
                return protocol.message("native.receipt", {
                    "request_id": msg["payload"].get("request_id", msg["id"]),
                    "outcome": "rejected", "code": "native_document_unavailable"}, re=msg["id"])
        return handle

    def _observe(self, *_args):
        if not self.busy:
            self.dirty = True
            self.last_dirty = time.monotonic()

    def _hooks(self):
        if self._hooked:
            return
        import bpy
        for handlers in (bpy.app.handlers.depsgraph_update_post,
                         bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
            handlers.append(self._observe)
        self._hooked = True

    def head(self):
        doc = self.session.document()
        return {"session_id": self.session.session_id, "host_epoch": self.session.host_epoch,
                "document_id": doc["id"], "open_epoch": doc["open_epoch"],
                "revision": self.state.revision, "checkpoint_hash": self.state.checkpoint_hash}

    def _capture(self):
        live = getattr(self._srv, "live_edit", None)
        preview = getattr(self._srv, "preview_ui", None)
        if ((live is not None and live.current is not None)
                or (preview is not None and (preview.owner is not None
                    or preview.lease is not None or preview.ending))):
            raise Refused("native_busy")
        can_capture = getattr(self.native, "can_capture", self.native.is_idle)
        if self.busy or not can_capture():
            raise Refused("native_busy")
        # Give the regular scene its stable object IDs before the native copy.
        self.scene_sync.flush()
        self.document.store()
        snapshot = self.native.capture(self.path)
        self.dirty = False
        if self.state is None:
            doc = self.session.document()
            self.state = NativeSyncState(session_id=self.session.session_id,
                host_epoch=self.session.host_epoch, document_id=doc["id"],
                open_epoch=doc["open_epoch"], revision=0, checkpoint_hash=snapshot.sha256)
        elif snapshot.sha256 != self.snapshot.sha256:
            self.state.sync_head(self.state.revision + 1, snapshot.sha256)
        changed = self.snapshot is None or snapshot.sha256 != self.snapshot.sha256
        self.snapshot = snapshot
        if changed:
            self._announce()
        return snapshot

    def _announce(self):
        for conn in tuple(self.subscribers):
            if not conn.closing:
                conn.send(protocol.message("native.head", self.head()))

    def _check_identity(self, payload):
        head = self.head()
        for key in ("session_id", "host_epoch", "document_id", "open_epoch"):
            if payload.get(key) != head[key]:
                raise Refused("wrong_session" if key in ("session_id", "host_epoch")
                              else "wrong_document")

    def _fence(self, conn, payload):
        self._check_identity(payload)
        actor = self.session.participants.get(conn, {})
        aid = actor.get("actor_id", "")
        if payload.get("actor_id") != aid:
            raise Refused("wrong_actor")
        lease = next((x for x in self.session.store.leases()
                      if x["lease_id"] == payload.get("lease_id")), {})
        doc = self.session.document()
        return Fence(self.session.session_id, self.session.host_epoch, doc["id"],
            doc["open_epoch"], aid, conn.can_edit,
            conn in self.session.participants and not conn.closing,
            lease.get("lease_id", ""), lease.get("owner", {}).get("actor_id", ""),
            lease.get("mode", ""), bool(lease))

    def get(self, msg, conn):
        from .wire import iter_messages
        if self.busy:
            raise Refused("native_busy")
        snapshot = self._capture()
        # Pace chunks on subsequent drain ticks. Do not overflow the existing
        # Maincloud bridge's bounded 4 MiB window or the client's event queue.
        if conn not in self.outgoing:
            outgoing = iter(iter_messages(snapshot, self.head()))
            # Validate the whole-file and manifest bounds here, inside the
            # guarded request, before a lazy generator can break the timer.
            first = next(outgoing)
            self.outgoing[conn] = chain((first,), outgoing)
        self.subscribers.add(conn)
        self._hooks()

    def begin(self, msg, conn):
        from .wire import validate_manifest
        if self.busy:
            raise Refused("busy")
        p = msg["payload"]
        self._capture()  # catches Host edits omitted by the viewport serializer
        fence = self._fence(conn, p)
        manifest = validate_manifest(p["manifest"], p.get("active_scene_uuid"))
        metadata = (manifest, p.get("active_scene_uuid"))
        signature = hashlib.sha256(json.dumps(metadata, sort_keys=True,
            ensure_ascii=False, separators=(",", ":")).encode("utf-8")).digest()
        if p["request_id"] in self._metadata and self._metadata[p["request_id"]] != signature:
            raise Refused("duplicate_request")
        receipt = self.state.begin(p["request_id"], fence,
            base_revision=p["base_revision"], base_hash=p["base_hash"],
            content_hash=p["content_hash"], total_bytes=p["total_bytes"],
            chunk_count=p["chunk_count"])
        if receipt.outcome == "pending":
            self._metadata[p["request_id"]] = signature
            self.manifests[p["request_id"]] = metadata
            self.last_upload = time.monotonic()
        return protocol.message("native.receipt", asdict(receipt), re=msg["id"])

    def chunk(self, msg, conn):
        from .wire import decode_chunk
        p = msg["payload"]
        self.state.chunk(p["request_id"], self._fence(conn, p), p["index"],
                         decode_chunk(p["data"]))
        self.last_upload = time.monotonic()

    def query(self, msg, conn):
        p = msg["payload"]
        receipt = self.state.query(p["request_id"], self._fence(conn, p))
        return protocol.message("native.receipt", asdict(receipt), re=msg["id"])

    def cancel(self, msg, conn):
        p = msg["payload"]
        receipt = self.state.cancel(p["request_id"], self._fence(conn, p))
        self.manifests.pop(p["request_id"], None)
        return protocol.message("native.receipt", asdict(receipt), re=msg["id"])

    def commit(self, msg, conn):
        p, rid = msg["payload"], msg["payload"]["request_id"]
        self._capture()  # final compare-and-swap before touching native data
        fence = self._fence(conn, p)
        # Check native context BEFORE prepare, which is the uncertain boundary.
        if self.busy or not self.native.is_idle():
            raise Refused("native_busy")
        checkpoint = self.state.prepare(rid, fence)
        manifest, active_scene = self.manifests[rid]
        identity_map = (self.scene_sync.native_identity_map()
                        if hasattr(self.scene_sync, "native_identity_map") else {})
        try:
            self.upload.write_bytes(checkpoint.data)
        except OSError:
            # Native application has not started: the unchanged document is the
            # verified rollback state, even though the bytes were prepared.
            receipt = self.state.abort(rid, code="checkpoint_write_failed", rollback_verified=True)
            self.manifests.pop(rid, None)
            return protocol.message("native.receipt", asdict(receipt), re=msg["id"])
        guard = self.session.commit()
        guard.__enter__()
        self.busy = True

        def uncertain(code):
            if self.state.pending is not None and self.state.pending.request_id == rid:
                self.state.unknown(rid, code=code)
            return self.state.query(rid, fence)

        def finish(_report=None):
            try:
                # Capture after ALL phases; no intermediate graph reaches VR.
                self.document.edited()
                self.document.store()
                if hasattr(self.scene_sync, "restore_native_identities"):
                    self.scene_sync.restore_native_identities(identity_map)
                self.scene_sync.flush()
                snapshot = self.native.capture(self.path)
                revision = self.state.revision + 1
                if self.state.pending is not None and self.state.pending.request_id == rid:
                    receipt = self.state.applied(rid, self._fence(conn, p),
                        revision=revision, checkpoint_hash=snapshot.sha256)
                else:
                    # A disconnect may already have closed this receipt as
                    # UNKNOWN. The fresh native head is still authoritative.
                    self.state.sync_head(revision, snapshot.sha256)
                    receipt = self.state.query(rid, fence)
                self.snapshot = snapshot
                self.dirty = False
                conn.send(protocol.message("native.receipt", asdict(receipt)))
                self._announce()
            except Exception:  # noqa: BLE001 - every native callback must release its guard
                self.error = "Native apply outcome requires reconciliation"
                conn.send(protocol.message("native.receipt", asdict(uncertain("apply_unverified"))))
            finally:
                self.busy = False
                self.manifests.pop(rid, None)
                guard.__exit__(None, None, None)

        def failed(_error):
            try:
                self.error = "Native apply failed; preserve both files and reconnect for inspection"
                conn.send(protocol.message("native.receipt", asdict(uncertain("apply_failed"))))
            finally:
                self.busy = False
                self.manifests.pop(rid, None)
                guard.__exit__(None, None, None)

        try:
            self.native.apply(self.upload, manifest, finish, failed, active_scene_uuid=active_scene)
        except Exception as exc:  # noqa: BLE001 - admission already crossed the mutation boundary
            failed(exc)

    def poll(self):
        if self.busy:
            return
        for conn, outgoing in tuple(self.outgoing.items()):
            if conn.closing or conn not in self.session.participants:
                self.outgoing.pop(conn, None)
                continue
            try:
                conn.send(protocol.message("native.snapshot", next(outgoing)))
            except StopIteration:
                self.outgoing.pop(conn, None)
            except (OSError, ValueError, RuntimeError):
                self.outgoing.pop(conn, None)
                self.error = "Native checkpoint could not be sent; ordinary Host remains available"
                conn.send(protocol.message("native.receipt", {"outcome": "rejected",
                    "code": "native_transfer_failed"}))
        if not self.subscribers or self.state is None:
            return
        now = time.monotonic()
        if self.state.pending is not None and now - self.last_upload > 60:
            rid = self.state.pending.request_id
            self.state.abort(rid, code="transfer_timeout")
            self.manifests.pop(rid, None)
        if now >= self.next_audit and (not self.dirty or now - self.last_dirty >= .25):
            self.next_audit = now + 2.0
            try:
                self._capture()
                self.error = ""
            except (OSError, Refused, RuntimeError, ValueError):
                self.error = "Native sync waits for a settled, portable Blender document"

    def stop(self):
        if self._hooked:
            import bpy
            for handlers in (bpy.app.handlers.depsgraph_update_post,
                             bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
                if self._observe in handlers:
                    handlers.remove(self._observe)
        self.subscribers.clear()
        self.outgoing.clear()
        if not self.busy:
            self.folder.cleanup()

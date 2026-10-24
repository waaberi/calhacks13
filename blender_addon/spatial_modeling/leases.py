"""Leases: who may change what, checked immediately before every native write.

Implements "Leases and presence" in contracts/README.md for the Host role (P3B).
The leases themselves live in the session's store (session_store.py, in memory
by default), which grants them atomically; this module decides what a lease must
cover and answers the messages.

- lease.acquire, checked like a command: schema (invalid_message), request ID
  (the same ID and payload get the stored answer again and grant nothing new; a
  changed payload gets duplicate_request), admission (can_edit and actor_id:
  permission_denied), session and document (wrong_session, wrong_document), the
  targets exist (not_found), then the store grants it or refuses with
  lease_conflict and the blocking lease in details.lease. Everyone gets
  session.update with the new lease, then the sender gets lease.granted.
- lease.release: no reply on success, then everyone gets session.update.
  not_found if no such lease is live, permission_denied if it is someone else's.
- check(), step 6 of every command (commands.py), right before it is applied.
- may_write(), for the host desktop's own edits (#77).

What a lease covers. Exclusive: the whole document. Shared: the listed objects
and sketches plus their linked data, which the editor's linked(ids) works out
(edits.py in Blender): other objects that share an object's data (mesh, curve),
its children, and objects whose modifiers or constraints use it, followed
transitively. A sketch is leased whole, by its ID. Leases are stored with what
they covered when granted. A command's own target is expanded again when it is
checked, so links made since (a new child, say) still count.

Conflicts. Another participant's exclusive lease blocks every command and
lease. Another participant's shared lease blocks commands on the objects it
covers, shared leases that overlap it, exclusive leases, and Undo/Redo. A
participant's own leases never block it. object.add, document.save and
sketch.create have no target, so only someone else's exclusive lease blocks them.

This module must not import bpy, so the tests can run it outside Blender.
"""

import hashlib
import json
import logging
from collections import ChainMap, OrderedDict

try:
    from . import commands, protocol, server, session_store
except ImportError:  # imported directly by the tests, outside Blender
    import commands
    import protocol
    import server
    import session_store

MAX_REQUESTS = 10000  # lease.acquire answers kept for deduplication, newest first
MAX_TARGETS = 64  # lease.acquire.schema.json
HISTORY_OPS = commands.HISTORY_OPS

log = logging.getLogger(__name__)


# The schemas, by hand (Blender has no jsonschema).


def _check_acquire(msg):
    p = _envelope(msg, (*commands.REQUEST_FIELDS, "mode", "targets"))
    for name in commands.REQUEST_FIELDS:
        commands._uuid(p[name], name)
    mode, targets = p["mode"], p["targets"]
    if mode not in ("exclusive", "shared"):
        raise commands.Invalid("mode must be exclusive or shared")
    if not isinstance(targets, list) or len(targets) > MAX_TARGETS:
        raise commands.Invalid(f"targets must list at most {MAX_TARGETS} IDs")
    for i, target in enumerate(targets):
        commands._uuid(target, f"targets[{i}]")
    if len(set(targets)) != len(targets):
        raise commands.Invalid("targets must not repeat")
    if mode == "exclusive" and targets:
        raise commands.Invalid("an exclusive lease covers the whole document: targets must be []")
    if mode == "shared" and not targets:
        raise commands.Invalid("a shared lease needs at least one target")


def _check_release(msg):
    commands._uuid(_envelope(msg, ("lease_id",))["lease_id"], "lease_id")


def _envelope(msg, fields):
    commands._uuid(msg["id"], "id")
    if "re" in msg:
        commands._uuid(msg["re"], "re")
    return commands._keys(msg["payload"], "payload", fields)


def acquire_problem(msg):
    """Why msg doesn't match lease.acquire.schema.json, or None."""
    return commands._problem(_check_acquire, msg)


def release_problem(msg):
    """Why msg doesn't match lease.release.schema.json, or None."""
    return commands._problem(_check_release, msg)


def _digest(payload):
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Leases:
    """Grants, ends and checks leases for a session, on Blender's main thread.

    session: the session.Session; its store keeps the leases. editor: the
    commands.py editor; generation(id) says whether a target exists, and the
    optional linked(ids) -> IDs gives the linked data a lease on ids must cover.
    """

    def __init__(self, session, editor, max_requests=None):
        self.session = session
        self.editor = editor
        self.max_requests = MAX_REQUESTS if max_requests is None else max_requests
        self.requests = OrderedDict()  # lease.acquire ID -> (payload digest, reply type, payload)

    @property
    def store(self):
        return self.session.store

    def attach(self, srv):
        """Handle lease.acquire and lease.release on srv. Returns srv."""
        srv.handlers = ChainMap(
            {"lease.acquire": self.acquire, "lease.release": self.release}, srv.handlers
        )
        return srv

    # Handlers

    def acquire(self, msg, conn):
        problem = acquire_problem(msg)
        if problem:
            re_ = msg["id"] if commands.is_uuid(msg["id"]) else None
            return server.error("invalid_message", f"bad lease.acquire: {problem}", re_)
        rid, p = msg["id"], msg["payload"]
        digest = _digest(p)
        stored = self.requests.get(rid)
        if stored is not None:
            if stored[0] == digest:
                return protocol.message(stored[1], stored[2], re=rid)  # nothing granted again
            return server.error("duplicate_request", "This request ID was already used for a "
                                "different lease.acquire. Use a new ID.", rid)
        reply = self._acquire(rid, p, conn)
        self.requests[rid] = (digest, reply["type"], reply["payload"])
        while len(self.requests) > self.max_requests:
            self.requests.popitem(last=False)
        return reply

    def release(self, msg, conn):
        problem = release_problem(msg)
        if problem:
            re_ = msg["id"] if commands.is_uuid(msg["id"]) else None
            return server.error("invalid_message", f"bad lease.release: {problem}", re_)
        actor = self.session.participants.get(conn)
        try:
            self.end(msg["payload"]["lease_id"], actor["actor_id"])
        except session_store.SessionError as e:
            return server.error(e.code, e.message, msg["id"], e.details)
        return None

    def _acquire(self, rid, p, conn):
        def refused(code, text, details=None):
            return server.error(code, text, rid, details)

        actor = self.session.participants.get(conn)
        if not getattr(conn, "can_edit", False):
            return refused("permission_denied", "This connection is read-only.")
        if actor is None or p["actor_id"] != actor["actor_id"]:
            return refused("permission_denied",
                           "actor_id isn't this connection's; copy it from welcome.")
        if (p["session_id"], p["host_epoch"]) != (self.session.session_id,
                                                  self.session.host_epoch):
            return refused("wrong_session", "The host restarted since you joined. Reconnect.")
        doc = self.session.document()
        if (p["document_id"], p["open_epoch"]) != (doc["id"], doc["open_epoch"]):
            name = doc["name"] or "an unsaved file"
            current = {k: doc[k] for k in ("id", "open_epoch", "name")}
            return refused("wrong_document", f"The host has {name} open now. Rejoin to get it.",
                           {"document": current})
        missing = [t for t in p["targets"] if self.editor.generation(t) is None]
        if missing:
            return refused("not_found", f"{len(missing)} of the targets don't exist (any more): "
                           f"{', '.join(missing)}.")
        try:
            lease = self.grant(actor["actor_id"], p["mode"], p["targets"])
        except session_store.SessionError as e:
            return refused(e.code, e.message, e.details)
        return protocol.message("lease.granted", {"lease": lease}, re=rid)

    # Granting and ending, also for the host's own participant (#77)

    def grant(self, actor_id, mode, targets=()):
        """Grant actor_id a lease and tell everyone. Returns the lease as the contract shows it.

        A shared lease covers targets and their linked data. Raises
        session_store.SessionError lease_conflict (details.lease: the blocking lease).
        """
        covered = self.covered(targets) if mode == "shared" else []
        try:
            lease = self.store.acquire(actor_id, mode, covered)
        except session_store.SessionError as e:
            if e.code == "lease_conflict":
                raise self._conflict(e.details and e.details.get("lease"), mode == "exclusive",
                                     "lease") from None
            raise
        self.session.leases_changed()
        what = ", ".join(lease["targets"]) or "the whole document"
        log.info("%s holds a %s lease on %s", lease["owner"]["name"], mode, what)
        return lease

    def end(self, lease_id, actor_id):
        """End actor_id's lease and tell everyone. Raises SessionError not_found or
        permission_denied (someone else's)."""
        try:
            self.store.release(lease_id, actor_id)
        except session_store.SessionError as e:
            text = {"not_found": "No lease with that ID is held (any more).",
                    "permission_denied": "That lease is someone else's."}.get(e.code, e.message)
            raise session_store.SessionError(e.code, text) from None
        self.session.leases_changed()

    # Checks

    def covered(self, ids):
        """ids followed by their linked data (see the module docstring), without repeats."""
        out = list(dict.fromkeys(ids))
        linked = getattr(self.editor, "linked", None)
        if linked is not None and out:
            out.extend(i for i in linked(out) if i not in out)
        return out

    def blocking(self, actor_id, op=None, targets=(), whole=False):
        """The first lease of another participant that forbids this change, or None.

        op: a command op; Undo and Redo (or whole=True) need nobody else to hold a lease.
        targets: the object or sketch IDs that would change, before linked data is added.
        """
        if whole or op in HISTORY_OPS:
            return self.store.conflict(actor_id, "exclusive", [])
        return self.store.conflict(actor_id, "shared", self.covered(targets))

    def check(self, actor_id, op, target_id=None, lease_id=None):
        """Step 6 of a command: None, or (code, message, details) to reject it with.

        A command naming a lease must name a live lease of its own that covers its
        target (an exclusive lease covers everything). With or without one, nobody
        else's lease may cover what would change: without a lease, the command
        leases just its target for itself, and holds nothing afterwards.
        """
        if lease_id is not None:
            lease = next((x for x in self.store.leases() if x["lease_id"] == lease_id), None)
            if lease is None:
                text = "That lease has ended (released, or its owner left). Acquire a new one."
                return "not_found", text, None
            if lease["owner"]["actor_id"] != actor_id:
                return "permission_denied", "That lease is someone else's.", None
            if lease["mode"] == "shared" and target_id is not None and (
                    target_id not in lease["targets"]):
                text = ("Your lease doesn't cover this target. Acquire one that does, or leave "
                        "lease out.")
                return "permission_denied", text, None
        targets = [target_id] if target_id is not None else []
        lease = self.blocking(actor_id, op, targets)
        if lease is None:
            return None
        e = self._conflict(lease, op in HISTORY_OPS, "command")
        return e.code, e.message, e.details

    def may_write(self, object_ids=(), whole=False, actor_id=None):
        """May this participant change these objects now? The lease that forbids it, or None.

        For the host desktop's own edits (#77): actor_id defaults to the host's own
        participant. whole=True asks for a change that affects everything (Undo,
        Redo); with no object_ids and whole=False, only an exclusive lease forbids.
        """
        actor_id = self.session.host["actor_id"] if actor_id is None else actor_id
        return self.blocking(actor_id, targets=object_ids, whole=whole)

    @staticmethod
    def _conflict(lease, whole, what):
        if lease is None:  # the store couldn't say which lease
            return session_store.SessionError("lease_conflict", "Someone else is editing this.")
        name = lease["owner"]["name"]
        if lease["mode"] == "exclusive":
            text = f"{name} is editing the whole document."
        elif whole and what == "command":
            text = f"{name} is editing, so Undo and Redo wait until they finish."
        elif whole:
            text = f"{name} is editing, so nobody can reserve the whole document."
        else:
            text = f"{name} is editing this."
        return session_store.SessionError("lease_conflict", text, {"lease": lease})

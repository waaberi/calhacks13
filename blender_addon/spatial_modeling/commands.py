"""Commands: the one validated path for every native edit, and its receipts.

Implements "Commands" and "Outcomes" in contracts/README.md for the Host role.
A `command` is checked in the contract's order, deduplicated by request ID,
applied by the editor on Blender's main thread and answered with exactly one
`result`. Applied commands then go to every other participant as `activity`.
`receipt.query` answers from the same bounded receipt store.

1. Schema: command_problem() mirrors command.schema.json (Blender has no
   jsonschema), otherwise `error` invalid_message.
2. Request ID: the same ID with the same payload gets the stored result again
   and is never re-applied; with a changed payload, duplicate_request.
3. Admission: can_edit, and actor_id is this connection's: permission_denied.
   So is every write while the host reconciles after an unknown outcome.
4. session_id and host_epoch (wrong_session), document_id and open_epoch
   (wrong_document).
5. The target exists (not_found) and its generation is current; Undo and Redo
   need base_revision to be the current revision (stale_revision).
6. Leases: leases.Leases.check(), right before the write: a named `lease` must
   be this actor's and cover the target (not_found, permission_denied), and no
   other participant's lease may cover what would change (lease_conflict).
7. editor.apply() changes Blender, reads the result back, flushes (scene.update
   to everyone) and pushes one Undo step, inside session.commit() so no lease
   ends halfway; then this module sends `result` to the sender and `activity`
   to the others, in that order.

The editor (edits.py in Blender, a fake in the tests) provides flush() -> the
current revision after broadcasting pending scene updates (sync.flush),
generation(id) -> int or None if there is no such object, and
apply(op, target_id, args) -> Applied, whose revision is what its own flush
returned. apply() raises Refused when Blender changed nothing; any other
exception, a failed flush included, means the outcome is unknown. Then the
host stops writes, re-reads the scene, sends everyone a fresh scene.snapshot
and accepts writes again. If it can't re-read the scene yet, poll() (host.py's
timer) retries, so clients waiting for that snapshot aren't stuck.

Receipts (see "Reconnecting" in contracts/README.md) are keyed by request ID
only, so a client that reconnected, and so has a new actor_id, still finds the
requests it sent under the old one. They last as long as the host_epoch:
receipt.query names the host_epoch its requests were sent under, and the host
answers an earlier one's IDs it has no record of as `unknown`, never as
`missing`. `missing` is only for requests the host never received in this
host_epoch, and the query fences them: if one arrives late (a half-open
connection), it is refused, never applied.

This module must not import bpy, so the tests can run it outside Blender.
Received data is only ever compared and copied, never executed.
"""

import hashlib
import json
import logging
import re
import time
from collections import ChainMap, OrderedDict
from dataclasses import dataclass, field

try:
    from . import protocol, server
except ImportError:  # imported directly by the tests, outside Blender
    import protocol
    import server

MAX_RECEIPTS = 10000  # the newest receipts kept for deduplication and receipt.query
MAX_QUERY = 100
RECONCILE_RETRY = 0.5  # seconds between attempts to re-read the scene while writes are stopped
MAX_REVISION = 9007199254740991
REQUEST_FIELDS = ("session_id", "host_epoch", "document_id", "open_epoch", "actor_id")
OBJECT_OPS = ("object.add", "object.move", "object.rotate", "object.scale", "object.delete")
HISTORY_OPS = ("history.undo", "history.redo")
SKETCH_OPS = ("sketch.create", "sketch.add_line", "sketch.add_rectangle", "sketch.add_circle",
              "sketch.constrain", "sketch.set_dimension")
OPS = (*OBJECT_OPS, *HISTORY_OPS, "document.save", *SKETCH_OPS)
UNTARGETED_OPS = frozenset({"object.add", *HISTORY_OPS, "document.save", "sketch.create"})
NO_ARGS_OPS = frozenset({"object.delete", *HISTORY_OPS, "document.save"})

# Bounds from envelope.schema.json and command.schema.json: meters, radians, factors.
COORDINATE = (-1000, 1000)
LENGTH = (0.000001, 1000)
FACTOR = (0.001, 1000)
ANGLE = (-6.283186, 6.283186)
QUATERNION = (-1.000001, 1.000001)
SKETCH_ANGLE_MAX = 3.141593
DIMENSION_MAX = 1000
CONSTRAINT_KINDS = ("coincident", "horizontal", "vertical", "distance", "angle", "diameter",
                    "fixed")
VALUED_CONSTRAINTS = ("distance", "angle", "diameter")

_UUID = re.compile(r"[0-9a-f]{32}")
_LOCAL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

log = logging.getLogger(__name__)

_FENCED = object()  # stored digest of a request ID that receipt.query reported missing or unknown


class Refused(Exception):
    """Raised by an editor when Blender changed nothing: the result is `rejected`."""

    def __init__(self, code, message, details=None, solver=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.solver = solver


@dataclass
class Applied:
    """What an editor reports after Blender committed a change and it was published.

    revision: what the editor's flush() returned after the change.
    """

    summary: str
    created: list = field(default_factory=list)
    revision: int = 0
    solver: dict | None = None


# Step 1: the schema, by hand.


class Invalid(ValueError):
    """A message that doesn't match its schema."""


def is_uuid(value):
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def _keys(obj, where, required, optional=()):
    if not isinstance(obj, dict):
        raise Invalid(f"{where} must be an object")
    missing = [k for k in required if k not in obj]
    if missing:
        raise Invalid(f"{where} needs {', '.join(missing)}")
    extra = sorted(set(obj) - set(required) - set(optional))
    if extra:
        raise Invalid(f"{where} has an unknown field {extra[0]!r}")
    return obj


def _uuid(value, where):
    if not is_uuid(value):
        raise Invalid(f"{where} must be 32 lowercase hex digits")


def _revision(value, where):
    whole = isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if isinstance(value, bool) or not whole or not 0 <= value <= MAX_REVISION:
        raise Invalid(f"{where} must be a whole number from 0 to {MAX_REVISION}")


def _number(value, where, bounds=(None, None), above=None, unit=""):
    low, high = bounds
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if ok and (low is not None and value < low or high is not None and value > high
               or above is not None and value <= above):
        ok = False
    if not ok:
        if above is not None:
            limits = f" above {above:g} and up to {high:g}"
        elif low is not None:
            limits = f" from {low:g} to {high:g}"
        else:
            limits = ""
        raise Invalid(f"{where} must be a number{limits}{unit}")


def _numbers(value, where, count, bounds, unit=""):
    if not isinstance(value, list) or len(value) != count:
        raise Invalid(f"{where} must be a list of {count} numbers")
    for i, v in enumerate(value):
        _number(v, f"{where}[{i}]", bounds, unit=unit)


def _local_id(value, where):
    if not isinstance(value, str) or _LOCAL_ID.fullmatch(value) is None:
        raise Invalid(f"{where} must be 1 to 64 letters, digits, _ or -")


def _by_or_to(args):
    if not isinstance(args, dict) or set(args) not in ({"by"}, {"to"}):
        raise Invalid("args must have exactly one of by or to")
    return "by" if "by" in args else "to"


def _add_args(args):
    _keys(args, "args", ("primitive", "location", "dimensions"))
    if args["primitive"] not in ("cube", "sphere", "cylinder"):
        raise Invalid("args.primitive must be cube, sphere or cylinder")
    _numbers(args["location"], "args.location", 3, COORDINATE, " (meters)")
    _numbers(args["dimensions"], "args.dimensions", 3, LENGTH, " (meters)")


def _move_args(args):
    key = _by_or_to(args)
    _numbers(args[key], f"args.{key}", 3, COORDINATE, " (meters)")


def _rotate_args(args):
    if _by_or_to(args) == "to":
        _numbers(args["to"], "args.to", 4, QUATERNION)
        return
    by = _keys(args["by"], "args.by", ("axis", "angle"))
    if by["axis"] not in ("X", "Y", "Z"):
        raise Invalid("args.by.axis must be X, Y or Z")
    _number(by["angle"], "args.by.angle", ANGLE, unit=" (radians)")


def _scale_args(args):
    key = _by_or_to(args)
    _numbers(args[key], f"args.{key}", 3, FACTOR)


def _no_args(args):
    if args:
        raise Invalid("args must be {} for this op")


def _sketch_create_args(args):
    _keys(args, "args", ("plane",))
    if args["plane"] not in ("XY", "XZ", "YZ"):
        raise Invalid("args.plane must be XY, XZ or YZ")


def _points_args(*names):
    def check(args):
        _keys(args, "args", names)
        for name in names:
            _numbers(args[name], f"args.{name}", 2, COORDINATE, " (meters)")

    return check


def _sketch_circle_args(args):
    _keys(args, "args", ("center", "radius"))
    _numbers(args["center"], "args.center", 2, COORDINATE, " (meters)")
    _number(args["radius"], "args.radius", LENGTH, unit=" (meters)")


def _sketch_constrain_args(args):
    _keys(args, "args", ("kind", "entities"), ("value",))
    kind, entities = args["kind"], args["entities"]
    if kind not in CONSTRAINT_KINDS:
        raise Invalid(f"args.kind must be one of {', '.join(CONSTRAINT_KINDS)}")
    if not isinstance(entities, list) or not 1 <= len(entities) <= 2:
        raise Invalid("args.entities must list 1 or 2 entity IDs")
    for i, entity in enumerate(entities):
        _local_id(entity, f"args.entities[{i}]")
    if len(set(entities)) != len(entities):
        raise Invalid("args.entities must not repeat")
    if kind in ("coincident", "angle") and len(entities) < 2:
        raise Invalid(f"a {kind} constraint needs 2 entities")
    if kind in ("diameter", "fixed") and len(entities) > 1:
        raise Invalid(f"a {kind} constraint takes 1 entity")
    if kind not in VALUED_CONSTRAINTS:
        if "value" in args:
            raise Invalid(f"a {kind} constraint has no value")
        return
    if "value" not in args:
        raise Invalid(f"a {kind} constraint needs a value")
    if kind == "angle":
        _number(args["value"], "args.value", (None, SKETCH_ANGLE_MAX), above=0, unit=" (radians)")
    else:
        _number(args["value"], "args.value", LENGTH, unit=" (meters)")


def _sketch_set_dimension_args(args):
    _keys(args, "args", ("constraint", "value"))
    _local_id(args["constraint"], "args.constraint")
    _number(args["value"], "args.value", (None, DIMENSION_MAX), above=0)


ARGS_CHECKS = {
    "object.add": _add_args,
    "object.move": _move_args,
    "object.rotate": _rotate_args,
    "object.scale": _scale_args,
    "sketch.create": _sketch_create_args,
    "sketch.add_line": _points_args("start", "end"),
    "sketch.add_rectangle": _points_args("corner", "opposite"),
    "sketch.add_circle": _sketch_circle_args,
    "sketch.constrain": _sketch_constrain_args,
    "sketch.set_dimension": _sketch_set_dimension_args,
    **dict.fromkeys(NO_ARGS_OPS, _no_args),
}


def _envelope(msg):
    _uuid(msg["id"], "id")
    if "re" in msg:
        _uuid(msg["re"], "re")


def _check_command(msg):
    _envelope(msg)
    p = _keys(msg["payload"], "payload",
              (*REQUEST_FIELDS, "base_revision", "source", "op", "args"), ("lease", "target"))
    for name in REQUEST_FIELDS:
        _uuid(p[name], name)
    _revision(p["base_revision"], "base_revision")
    if p["source"] not in ("ui", "voice"):
        raise Invalid("source must be ui or voice")
    if "lease" in p:
        _uuid(p["lease"], "lease")
    op = p["op"]
    if not isinstance(op, str) or op not in OPS:
        raise Invalid(f"unknown op {op!r}")
    if op in UNTARGETED_OPS:
        if "target" in p:
            raise Invalid(f"{op} takes no target")
    elif "target" not in p:
        raise Invalid(f"{op} needs a target {{id, generation}}")
    else:
        target = _keys(p["target"], "target", ("id", "generation"))
        _uuid(target["id"], "target.id")
        _revision(target["generation"], "target.generation")
    if not isinstance(p["args"], dict):
        raise Invalid("args must be an object")
    ARGS_CHECKS[op](p["args"])


def _check_receipt_query(msg):
    _envelope(msg)
    p = _keys(msg["payload"], "payload", ("host_epoch", "request_ids"))
    _uuid(p["host_epoch"], "host_epoch")
    ids = p["request_ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_QUERY:
        raise Invalid(f"request_ids must list 1 to {MAX_QUERY} request IDs")
    for i, value in enumerate(ids):
        _uuid(value, f"request_ids[{i}]")
    if len(set(ids)) != len(ids):
        raise Invalid("request_ids must not repeat")


def _problem(check, msg):
    try:
        check(msg)
    except Invalid as e:
        return str(e)
    return None


def command_problem(msg):
    """Why msg doesn't match command.schema.json, or None."""
    return _problem(_check_command, msg)


def receipt_query_problem(msg):
    """Why msg doesn't match receipt.query.schema.json, or None."""
    return _problem(_check_receipt_query, msg)


def _digest(payload):
    """Identifies a payload for deduplication: the same JSON gives the same digest."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_ms():
    return int(time.time() * 1000)


class Commands:
    """Handles `command` and `receipt.query` for a session, on Blender's main thread.

    session: the session.Session (participants, identity, broadcast, document and
    snapshot). editor: see the module docstring. leases: the leases.Leases that
    step 6 asks; without one nobody holds a lease, so a named lease is not_found.
    """

    def __init__(self, session, editor, max_receipts=None, leases=None):
        self.session = session
        self.editor = editor
        self.leases = leases
        self.max_receipts = MAX_RECEIPTS if max_receipts is None else max_receipts
        self.receipts = OrderedDict()  # request_id -> (payload digest, receipt), oldest first
        # Once any receipt/fence is dropped, an unseen ID may be a replay. Keep
        # retained receipts readable, but refuse every unseen command until a
        # new host epoch rather than risk a second native mutation.
        self.evicted = False
        self.frozen = False  # after an unknown outcome, until the host has re-read the scene
        self._retry_at = 0.0  # when poll() next tries to reconcile
        self._reconcile_failures = 0

    def attach(self, srv):
        """Handle commands and receipt queries on srv. Returns srv."""
        srv.handlers = ChainMap(
            {"command": self.command, "receipt.query": self.receipt_query}, srv.handlers
        )
        return srv

    # Handlers

    def command(self, msg, conn):
        problem = command_problem(msg)
        if problem:
            re_ = msg["id"] if is_uuid(msg["id"]) else None
            return server.error("invalid_message", f"bad command: {problem}", re_)
        rid, payload = msg["id"], msg["payload"]
        digest = _digest(payload)
        stored = self.receipts.get(rid)
        if stored is None and self.evicted:
            text = ("The host's bounded receipt history is full. This request ID may have "
                    "been used before, so it will not change Blender. Save in host Blender, "
                    "then restart "
                    "the hosting session and reconnect before making a new edit.")
            receipt = self._receipt(conn, rid, payload, "rejected", self._revision_now(),
                                    error=_error("duplicate_request", text))
            return protocol.message("result", receipt, re=rid)
        if stored is not None and stored[0] is _FENCED:
            text = ("receipt.query already reported this request ID as not received, so the host "
                    "won't apply it now. Look at the scene, then use a new ID.")
            receipt = self._receipt(conn, rid, payload, "rejected", self._revision_now(),
                                    error=_error("duplicate_request", text))
            self._store(rid, digest, receipt)  # a later query says rejected, not missing
            return protocol.message("result", receipt, re=rid)
        if stored is not None:
            if stored[0] == digest:
                return protocol.message("result", stored[1], re=rid)  # never applied twice
            text = "This request ID was already used for a different command. Use a new ID."
            receipt = self._receipt(conn, rid, payload, "rejected", self._revision_now(),
                                    error=_error("duplicate_request", text))
            return protocol.message("result", receipt, re=rid)  # the original stays stored

        try:
            receipt = self._run(rid, payload, conn)
        except Exception as e:  # a bug; Blender may have changed, so never report "rejected"
            log.exception("%s failed", payload["op"])
            receipt = self._unknown(conn, rid, payload, e)
        self._store(rid, digest, receipt)
        conn.send(protocol.message("result", receipt, re=rid))
        outcome = receipt["outcome"]
        if outcome == "applied":
            self.session.broadcast(protocol.message("activity", receipt), exclude=conn)
            who = receipt["actor"]["name"]
            print(f"Spatial Modeling: {who}: {receipt['summary']} (revision {receipt['revision']})")
        elif outcome == "unknown":
            self._reconcile()
        return None

    def receipt_query(self, msg, conn):
        problem = receipt_query_problem(msg)
        if problem:
            re_ = msg["id"] if is_uuid(msg["id"]) else None
            return server.error("invalid_message", f"bad receipt.query: {problem}", re_)
        p = msg["payload"]
        found, unseen = [], []
        for rid in p["request_ids"]:
            stored = self.receipts.get(rid)
            if stored is not None and stored[1] is not None:
                found.append(stored[1])
            else:
                unseen.append(rid)
        current = p["host_epoch"] == self.session.host_epoch
        if current:
            for rid in unseen:  # never apply them from now on
                if rid not in self.receipts:
                    self._store(rid, _FENCED, None)
        # Only requests sent in this host_epoch, with nothing dropped from the store, are
        # certainly not applied. Before a restart, or once receipts were dropped, they may be.
        sure = current and not self.evicted
        payload = {"receipts": found, "missing": unseen if sure else [],
                   "unknown": [] if sure else unseen}
        return protocol.message("receipts", payload, re=msg["id"])

    def stop_writes(self, why):
        """Refuse writes until the scene is re-read and everyone has a fresh snapshot.

        For a change the host can't vouch for, as after an unknown outcome: gate.py
        calls it when host Blender changed leased data by a route the gate doesn't
        cover. The next poll() reconciles.
        """
        log.warning("edits stopped until the scene is re-read: %s", why)
        self.frozen = True
        self._retry_at = 0.0

    def poll(self):
        """While writes are stopped, retry reconciling now and then. host.py's timer calls it."""
        if self.frozen and time.monotonic() >= self._retry_at:
            self._reconcile()

    # The checks, in the contract's order (step 1 and 2 are in command()).

    def _run(self, rid, p, conn):
        def rejected(code, text, details=None, solver=None):
            return self._receipt(conn, rid, p, "rejected", revision,
                                 error=_error(code, text, details), solver=solver)

        try:
            revision = self.editor.flush()  # pending changes go out first; generations are current
        except Exception:
            log.exception("could not read the scene before %s", p["op"])
            revision = self._revision_now()
            return rejected("internal_error", "The host couldn't read the scene; nothing changed.")

        # 3. Admission
        actor = self.session.participants.get(conn)
        if not getattr(conn, "can_edit", False):
            return rejected("permission_denied", "This connection is read-only.")
        if actor is None or p["actor_id"] != actor["actor_id"]:
            return rejected("permission_denied",
                            "actor_id isn't this connection's; copy it from welcome.")
        if self.frozen and not self._reconcile():
            return rejected("permission_denied", "The host stopped edits while it re-reads the "
                            "scene after an edit it couldn't confirm. Try again shortly.")
        # 4. Session and document
        if (p["session_id"], p["host_epoch"]) != (self.session.session_id,
                                                  self.session.host_epoch):
            return rejected("wrong_session", "The host restarted since you joined. Reconnect.")
        doc = self.session.document()
        if (p["document_id"], p["open_epoch"]) != (doc["id"], doc["open_epoch"]):
            name = doc["name"] or "an unsaved file"
            current = {k: doc[k] for k in ("id", "open_epoch", "name")}
            return rejected("wrong_document", f"The host has {name} open now. Rejoin to get it.",
                            {"document": current})
        op = p["op"]
        if op in SKETCH_OPS and not getattr(self.editor, "supports_sketches", False):
            return rejected("failed", "Sketches aren't available on this host yet.")
        # 5. Target and revision
        target = p.get("target")
        if target is not None:
            generation = self.editor.generation(target["id"])
            if generation is None:
                return rejected("not_found", "That object doesn't exist (any more).")
            if generation != target["generation"]:
                return rejected("stale_revision", "The object changed since you last saw it. "
                                "Look again, then retry.", {"generation": generation})
        if op in HISTORY_OPS and p["base_revision"] != revision:
            return rejected("stale_revision", "The document changed since you last saw it. "
                            "Look again, then retry.", {"revision": revision})
        # 6. Leases, immediately before the write
        if self.leases is not None:
            refusal = self.leases.check(actor["actor_id"], op, target and target["id"],
                                        p.get("lease"))
            if refusal is not None:
                return rejected(*refusal)
        elif "lease" in p:
            return rejected("not_found", "That lease doesn't exist.")
        # 7. Apply, read back, publish (scene.update) and commit as one Undo step
        try:
            with self.session.commit():
                done = self.editor.apply(op, target and target["id"], p["args"])
        except Refused as e:
            return rejected(e.code, e.message, e.details, e.solver)
        except Exception as e:  # including a flush that failed after the change
            log.exception("%s failed halfway", op)
            return self._unknown(conn, rid, p, e)
        return self._receipt(conn, rid, p, "applied", done.revision, summary=done.summary,
                             created=done.created, solver=done.solver)

    def _unknown(self, conn, rid, p, exc):
        """Blender may or may not have changed: stop writes until _reconcile() succeeds."""
        self.frozen = True
        text = f"The host can't tell whether this changed Blender ({type(exc).__name__}: {exc})."
        return self._receipt(conn, rid, p, "unknown", self._revision_now(),
                             error=_error("internal_error", text))

    def _reconcile(self):
        """Re-read the scene, send everyone a fresh snapshot and accept writes again."""
        try:
            self.editor.flush()
            self.session.broadcast(
                protocol.message("scene.snapshot", self.session.snapshot(self.session.document()))
            )
        except Exception:
            if self._reconcile_failures == 0:
                log.exception("could not re-read the scene; edits stay stopped")
            self._reconcile_failures += 1
            self._retry_at = time.monotonic() + RECONCILE_RETRY
            return False
        if self._reconcile_failures:
            log.warning("re-read the scene after %d failed attempts; edits resume",
                        self._reconcile_failures)
        self.frozen = False
        self._reconcile_failures = 0
        return True

    # Receipts

    def _revision_now(self):
        try:
            return self.session.document()["revision"]
        except Exception:
            log.exception("could not read the document's revision")
            return 0

    def _receipt(self, conn, rid, p, outcome, revision, summary=None, created=None, error=None,
                 solver=None):
        receipt = {"request_id": rid, "op": p["op"]}
        if "target" in p:
            receipt["target"] = p["target"]["id"]
        actor = self.session.participants[conn]  # server.py hands over joined connections only
        receipt.update(actor=dict(actor), source=p["source"], outcome=outcome, revision=revision)
        if created:
            receipt["created"] = list(created)
        if solver is not None:
            receipt["solver"] = dict(solver)
        if summary:
            receipt["summary"] = summary[:1024]
        if error is not None:
            receipt["error"] = error
        receipt["at"] = _now_ms()
        return receipt

    def _store(self, rid, digest, receipt):
        self.receipts[rid] = (digest, receipt)
        self.receipts.move_to_end(rid)
        while len(self.receipts) > self.max_receipts:
            self.receipts.popitem(last=False)
            self.evicted = True


def _error(code, text, details=None):
    e = {"code": code, "message": text[:1024]}
    if details is not None:
        e["details"] = details
    return e

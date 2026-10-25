"""Session state the host shares with every client: participants, leases and the receipt log.

One interface, two implementations:

- MemoryStore keeps everything in this process. It needs nothing else and is the fallback.
- SpacetimeStore keeps it in the SpacetimeDB module in spacetime/, so it survives a Blender
  restart and the Unity app can subscribe to it live. Standard library only: reducer calls and
  SQL queries over HTTP to a server on localhost.
- MirroredStore is what the host uses: a MemoryStore decides and answers at once, and a
  background thread copies participants and leases to a SpacetimeStore, so Blender's main
  thread never waits for SpacetimeDB and works the same while no server is running.

The host is the only writer. It checks each request against contracts/README.md (session,
document, schema) before calling in here; the store does the checks that must be atomic, such
as lease conflicts. Reads return contract-shaped dicts, so `session.update`, `lease.granted`
and `receipts` payloads come straight from here and the wire format doesn't depend on the store.

Rejections raise SessionError with a contract error code. SpacetimeStore raises
StoreUnavailable when the server can't be reached; the outcome of that write is unknown.
Its calls block for one localhost round trip each (measured in spacetime/README.md).

No bpy: this module is tested outside Blender.
"""

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

LEASE_TTL_MS = 6000  # the contract's heartbeat: silent for 6 s means gone
UUID = re.compile(r"^[0-9a-f]{32}$")
ROLES = ("vr", "blender-client", "host")
OUTCOMES = ("pending", "applied", "rejected", "unknown")
MAX_TARGETS = 1000
MIRROR_RENEW_S = 2.0  # how often MirroredStore renews SpacetimeDB's copy of the leases
MIRROR_RETRY_S = 5.0  # how long it waits after SpacetimeDB couldn't be reached

log = logging.getLogger(__name__)


class SessionError(Exception):
    """A rejected request. `code` is a contract error code; `details` goes into error.details."""

    def __init__(self, code, message, details=None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details

    def error(self):
        """The contract's `error` object for this rejection."""
        err = {"code": self.code, "message": self.message}
        if self.details is not None:
            err["details"] = self.details
        return err


class StoreUnavailable(Exception):
    """The store couldn't be reached or answered unexpectedly. A write's outcome is unknown.

    `status` is the HTTP status if the server answered, otherwise None.
    """

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def now_ms():
    return time.time_ns() // 1_000_000


def encode_receipt(receipt):
    """The canonical JSON stored for a receipt, so equal receipts compare equal."""
    return json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def overlaps(a_mode, a_targets, b_mode, b_targets):
    """Whether two leases (or a lease and a command's target) collide."""
    if a_mode == "exclusive" or b_mode == "exclusive":
        return True
    return not set(a_targets).isdisjoint(b_targets)


def session_payload(participant_rows, lease_rows, now):
    """Rows of the participant and lease tables as a `session.update` payload. Only live leases.

    Participants in joining order and leases in acquiring order; rows from the same
    millisecond keep the order they came in (MemoryStore's is the order they were added).
    """
    actors = {}
    for p in sorted(participant_rows, key=lambda p: p["joined_at"]):
        actors[p["actor_id"]] = {"actor_id": p["actor_id"], "name": p["name"], "role": p["role"]}
    leases = []
    for row in sorted(lease_rows, key=lambda r: r["acquired_at"]):
        owner = actors.get(row["owner_id"])
        if _live(row, now) and owner is not None:
            leases.append(
                {
                    "lease_id": row["lease_id"],
                    "mode": row["mode"],
                    "owner": owner,
                    "targets": list(row["targets"]),
                    "acquired_at": row["acquired_at"],
                }
            )
    return {"participants": list(actors.values()), "leases": leases}


def _live(row, now):
    return row["expires_at"] is None or row["expires_at"] > now


def _require_uuid(field, value):
    if not isinstance(value, str) or not UUID.match(value):
        raise SessionError("invalid_message", f"{field} must be 32 lowercase hex digits")


class SessionStore:
    """What the host needs to keep about the session. Subclasses implement the abstract methods.

    Participants are contract `actor` dicts. A lease lives until it is released, its owner
    leaves, or nobody renews it for `lease_ttl_ms`; the host renews an owner's leases whenever
    it hears from that owner (its heartbeat), and calls leave() when a connection closes.
    """

    lease_ttl_ms = LEASE_TTL_MS

    # Participants and presence

    def join(self, actor):
        """Add or update a participant: an `actor` dict with actor_id, name and role."""
        raise NotImplementedError

    def leave(self, actor_id):
        """The participant's connection closed: remove it and all of its leases."""
        raise NotImplementedError

    def renew(self, actor_id):
        """The host heard from this participant: extend its live leases by lease_ttl_ms."""
        raise NotImplementedError

    # Leases

    def acquire(self, owner_id, mode, targets, lease_id=None):
        """Grant a lease atomically and return it, or raise SessionError `lease_conflict` with
        the blocking lease in details["lease"]. `exclusive` takes no targets (the document);
        `shared` takes object and sketch IDs."""
        raise NotImplementedError

    def release(self, lease_id, owner_id):
        """End a lease. `not_found` if it isn't live, `permission_denied` if it isn't owner_id's."""
        raise NotImplementedError

    def expire(self):
        """Delete leases nobody renewed in time, so subscribers stop showing them."""
        raise NotImplementedError

    def session(self):
        """{"participants": [...], "leases": [...]}: the payload of `session.update`."""
        raise NotImplementedError

    def participants(self):
        return self.session()["participants"]

    def leases(self):
        return self.session()["leases"]

    def conflict(self, actor_id, mode, targets):
        """The first live lease of another participant that blocks this actor from changing
        `targets` (mode "shared") or the whole document (mode "exclusive", for Undo/Redo), or
        None. For commands sent without a lease of their own."""
        for lease in self.leases():
            if lease["owner"]["actor_id"] != actor_id and overlaps(
                lease["mode"], lease["targets"], mode, targets
            ):
                return lease
        return None

    # Receipt log

    def record_receipt(self, receipt, digest=""):
        """Store a receipt (the payload of `result`), or complete a pending one. `digest` is the
        host's fingerprint of the request payload. A final receipt never changes."""
        raise NotImplementedError

    def replay(self, request_id, digest):
        """The stored receipt of an earlier request with this ID, or None. Raises SessionError
        `duplicate_request` if that request had a different payload (digest)."""
        raise NotImplementedError

    def receipts(self, request_ids):
        """(receipts, missing): stored receipts in request order, and the IDs without one."""
        raise NotImplementedError

    # Shared checks, so both stores reject the same requests

    @staticmethod
    def _check_actor(actor):
        _require_uuid("actor_id", actor.get("actor_id"))
        name = actor.get("name")
        if not isinstance(name, str) or not 1 <= len(name) <= 256:
            raise SessionError("invalid_message", "name must be 1 to 256 characters")
        if actor.get("role") not in ROLES:
            raise SessionError("invalid_message", f"unknown role {actor.get('role')!r}")

    @staticmethod
    def _check_lease(mode, targets):
        if mode == "exclusive":
            if targets:
                raise SessionError("invalid_message", "an exclusive lease has no targets")
        elif mode == "shared":
            if not 1 <= len(targets) <= MAX_TARGETS:
                raise SessionError(
                    "invalid_message", f"a shared lease has 1 to {MAX_TARGETS} targets"
                )
            if len(set(targets)) != len(targets):
                raise SessionError("invalid_message", "targets repeat")
            for target in targets:
                _require_uuid("target", target)
        else:
            raise SessionError("invalid_message", f"unknown mode {mode!r}")

    @staticmethod
    def _check_receipt(receipt):
        _require_uuid("request_id", receipt.get("request_id"))
        if receipt.get("outcome") not in OUTCOMES:
            raise SessionError("invalid_message", f"unknown outcome {receipt.get('outcome')!r}")

    def _conflict_error(self, blocking):
        if blocking is None:
            return SessionError("lease_conflict", "Someone else is editing this")
        name = blocking["owner"]["name"]
        return SessionError("lease_conflict", f"{name} is editing this", {"lease": blocking})


class MemoryStore(SessionStore):
    """Session state in this process: the fallback. Gone when Blender quits.

    lease_ttl_ms=None: leases never lapse on a timer, only by release() and leave(). The host
    uses that, because its server already closes a connection it hasn't heard from for 6 s,
    on its own thread, so a busy Blender (a render) can't time out a client that is pinging.
    """

    def __init__(self, lease_ttl_ms=LEASE_TTL_MS, clock=now_ms, max_receipts=10_000):
        self.lease_ttl_ms = lease_ttl_ms
        self._clock = clock
        self._max_receipts = max_receipts
        self._lock = threading.Lock()
        # Rows shaped like the SpacetimeDB tables, so both stores share session_payload().
        self._participants = {}
        self._leases = {}
        self._receipts = {}  # request_id -> row, oldest first

    def join(self, actor):
        self._check_actor(actor)
        with self._lock:
            now = self._clock()
            row = self._participants.get(actor["actor_id"])
            joined = row["joined_at"] if row else now
            self._participants[actor["actor_id"]] = {
                "actor_id": actor["actor_id"],
                "name": actor["name"],
                "role": actor["role"],
                "joined_at": joined,
                "last_seen": now,
            }

    def leave(self, actor_id):
        with self._lock:
            for lease_id in [k for k, v in self._leases.items() if v["owner_id"] == actor_id]:
                del self._leases[lease_id]
            self._participants.pop(actor_id, None)

    def renew(self, actor_id):
        with self._lock:
            row = self._participants.get(actor_id)
            if row is None:
                raise SessionError("not_found", f"no participant {actor_id}")
            now = self._clock()
            row["last_seen"] = now
            for lease in self._leases.values():
                if lease["owner_id"] == actor_id and _live(lease, now):
                    lease["expires_at"] = self._expiry(now)

    def acquire(self, owner_id, mode, targets, lease_id=None):
        targets = list(targets)
        lease_id = lease_id or uuid.uuid4().hex
        _require_uuid("lease_id", lease_id)
        self._check_lease(mode, targets)
        with self._lock:
            if owner_id not in self._participants:
                raise SessionError("not_found", f"no participant {owner_id}")
            if lease_id in self._leases:
                raise SessionError("duplicate_request", f"lease {lease_id} already exists")
            now = self._clock()
            self._drop_expired(now)
            for other in self._leases.values():
                if other["owner_id"] != owner_id and overlaps(
                    other["mode"], other["targets"], mode, targets
                ):
                    blocking = self._payload(now)["leases"]
                    raise self._conflict_error(
                        next((x for x in blocking if x["lease_id"] == other["lease_id"]), None)
                    )
            self._leases[lease_id] = {
                "lease_id": lease_id,
                "mode": mode,
                "owner_id": owner_id,
                "targets": targets,
                "acquired_at": now,
                "expires_at": self._expiry(now),
            }
            return next(x for x in self._payload(now)["leases"] if x["lease_id"] == lease_id)

    def release(self, lease_id, owner_id):
        with self._lock:
            row = self._leases.get(lease_id)
            if row is None or not _live(row, self._clock()):
                raise SessionError("not_found", f"no lease {lease_id}")
            if row["owner_id"] != owner_id:
                raise SessionError("permission_denied", f"lease {lease_id} belongs to someone else")
            del self._leases[lease_id]

    def expire(self):
        with self._lock:
            self._drop_expired(self._clock())

    def session(self):
        with self._lock:
            return self._payload(self._clock())

    def record_receipt(self, receipt, digest=""):
        self._check_receipt(receipt)
        body = encode_receipt(receipt)
        with self._lock:
            old = self._receipts.get(receipt["request_id"])
            if old is not None and old["outcome"] != "pending":
                if old["body"] != body or old["digest"] != digest:
                    raise SessionError(
                        "duplicate_request", f"receipt {receipt['request_id']} is final"
                    )
                return
            self._receipts.pop(receipt["request_id"], None)
            self._receipts[receipt["request_id"]] = {
                "outcome": receipt["outcome"],
                "digest": digest,
                "body": body,
            }
            while len(self._receipts) > self._max_receipts:
                del self._receipts[next(iter(self._receipts))]

    def replay(self, request_id, digest):
        with self._lock:
            row = self._receipts.get(request_id)
        return _replayed(request_id, row, digest)

    def receipts(self, request_ids):
        with self._lock:
            rows = {i: self._receipts[i] for i in request_ids if i in self._receipts}
        return _found_and_missing(request_ids, rows)

    def _drop_expired(self, now):
        for lease_id in [k for k, v in self._leases.items() if not _live(v, now)]:
            del self._leases[lease_id]

    def _expiry(self, now):
        return None if self.lease_ttl_ms is None else now + self.lease_ttl_ms

    def _payload(self, now):
        return session_payload(self._participants.values(), self._leases.values(), now)


class SpacetimeStore(SessionStore):
    """Session state in the SpacetimeDB module in spacetime/ (see spacetime/README.md).

    `token_path` is where this host's SpacetimeDB token lives; it is created on first use.
    Keep it outside Git. The first identity to call `claim_host` becomes the only writer, so
    the host keeps that token across restarts. Creating the store contacts the server, so it
    raises StoreUnavailable right away if none is running.

    Each call blocks for its round trip (1 to 5 ms on localhost), at most `timeout` seconds.
    Keep the timeout short: the host calls this from Blender's main thread.
    """

    def __init__(
        self,
        token_path,
        url="http://127.0.0.1:3000",
        database="spatial-modeling",
        lease_ttl_ms=LEASE_TTL_MS,
        timeout=1.0,
        clock=now_ms,
    ):
        self.url = url.rstrip("/")
        self.database = database
        self.lease_ttl_ms = lease_ttl_ms
        self._timeout = timeout
        self._clock = clock
        # Never route localhost through a system proxy (urllib reads the Windows proxy settings).
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._token_path = Path(token_path)
        self._token = self._load_token()
        try:
            self.call("claim_host")
        except StoreUnavailable as e:
            if e.status != 401:
                raise
            # The server no longer accepts the saved token (its keys were reset): start over.
            self._token_path.unlink(missing_ok=True)
            self._token = self._load_token()
            self.call("claim_host")

    # Low level, also used by spacetime/measure.py

    def call(self, reducer, args=None):
        """Call a reducer with named arguments. Raises SessionError if it rejects."""
        body = json.dumps(args or {}).encode("utf-8")
        self._post(f"/v1/database/{self.database}/call/{reducer}", body, "application/json")

    def select(self, sql):
        """Run one SQL query and return its rows as dicts."""
        out = json.loads(
            self._post(f"/v1/database/{self.database}/sql", sql.encode(), "text/plain")
        )
        names = [e["name"]["some"] for e in out[0]["schema"]["elements"]]
        return [dict(zip(names, row, strict=True)) for row in out[0]["rows"]]

    # SessionStore

    def join(self, actor):
        self._check_actor(actor)
        self.call("join", {k: actor[k] for k in ("actor_id", "name", "role")})

    def leave(self, actor_id):
        self.call("leave", {"actor_id": actor_id})

    def renew(self, actor_id):
        self.call("renew", {"actor_id": actor_id, "ttl_ms": self.lease_ttl_ms})

    def acquire(self, owner_id, mode, targets, lease_id=None):
        lease_id = lease_id or uuid.uuid4().hex
        args = {
            "lease_id": lease_id,
            "owner_id": owner_id,
            "mode": mode,
            "targets": list(targets),
            "ttl_ms": self.lease_ttl_ms,
        }
        try:
            self.call("acquire", args)
        except SessionError as e:
            if e.code != "lease_conflict":
                raise
            blocking_id = e.message.strip()
            leases = self.leases()
            raise self._conflict_error(
                next((x for x in leases if x["lease_id"] == blocking_id), None)
            ) from None
        for lease in self.leases():
            if lease["lease_id"] == lease_id:
                return lease
        raise StoreUnavailable(f"lease {lease_id} was granted but isn't readable")

    def release(self, lease_id, owner_id):
        self.call("release", {"lease_id": lease_id, "owner_id": owner_id})

    def expire(self):
        self.call("expire")

    def session(self):
        participants = self.select("SELECT * FROM participant")
        leases = self.select("SELECT * FROM lease")
        return session_payload(participants, leases, self._clock())

    def record_receipt(self, receipt, digest=""):
        self._check_receipt(receipt)
        self.call(
            "record_receipt",
            {
                "request_id": receipt["request_id"],
                "at": receipt["at"],
                "actor_id": receipt["actor"]["actor_id"],
                "op": receipt["op"],
                "outcome": receipt["outcome"],
                "digest": digest,
                "body": encode_receipt(receipt),
            },
        )

    def replay(self, request_id, digest):
        _require_uuid("request_id", request_id)
        rows = self.select(f"SELECT * FROM receipt WHERE request_id = '{request_id}'")
        return _replayed(request_id, rows[0] if rows else None, digest)

    def receipts(self, request_ids):
        for request_id in request_ids:
            _require_uuid("request_id", request_id)  # also keeps the SQL below safe
        rows = {}
        if request_ids:
            where = " OR ".join(f"request_id = '{i}'" for i in dict.fromkeys(request_ids))
            rows = {r["request_id"]: r for r in self.select(f"SELECT * FROM receipt WHERE {where}")}
        return _found_and_missing(request_ids, rows)

    # HTTP

    def _load_token(self):
        try:
            return self._token_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass
        out = json.loads(self._post("/v1/identity", b"", "application/json", auth=False))
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(out["token"])
        return out["token"]

    def _post(self, path, body, content_type, auth=True):
        headers = {"Content-Type": content_type}
        if auth:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(self.url + path, data=body, headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace").strip()
            if e.code == 530:  # the reducer rejected the call; nothing changed
                code, sep, detail = text.partition(": ")
                if sep and re.fullmatch(r"[a-z_]+", code):
                    raise SessionError(code, detail) from None
                raise SessionError("internal_error", text[:1024]) from None
            raise StoreUnavailable(f"SpacetimeDB answered {e.code}: {text[:300]}", e.code) from None
        except (urllib.error.URLError, OSError) as e:
            raise StoreUnavailable(f"can't reach SpacetimeDB at {self.url}: {e}") from None


class MirroredStore(SessionStore):
    """A MemoryStore that decides, copied to SpacetimeDB on a background thread.

    Every call goes to `memory` (by default a MemoryStore whose leases end only by release
    and leave, as the host wants) and returns at once; nothing on Blender's main thread waits
    for the network. A thread named spacetime-mirror then makes SpacetimeDB's participant and
    lease tables match memory: leave, release, join, then acquire, in that order, so a lease
    is released there before an overlapping one is acquired. The module's reducers check every
    write again; if one disagrees, that's logged and the copy carries on. While no server
    answers, the host works exactly as with MemoryStore alone and the thread retries every
    MIRROR_RETRY_S. When it (re)connects, it first clears whatever an earlier host left there.

    SpacetimeDB's copy holds each lease for LEASE_TTL_MS and the thread renews it every
    MIRROR_RENEW_S, so if this Blender quits or crashes, subscribers stop seeing its leases
    within 6 s. The receipt log isn't copied: the host doesn't keep receipts in a store yet.

    connect: () -> SpacetimeStore, called on the thread; it may raise StoreUnavailable or
    SessionError (another identity is the host). `status` says what the copy is doing.
    """

    def __init__(self, connect, memory=None, renew_s=MIRROR_RENEW_S, retry_s=MIRROR_RETRY_S):
        self.memory = MemoryStore(lease_ttl_ms=None) if memory is None else memory
        self.lease_ttl_ms = self.memory.lease_ttl_ms
        self.status = "Connecting to SpacetimeDB"
        self._connect = connect
        self._renew_s = renew_s
        self._retry_s = retry_s
        self._remote = None
        self._pushed = None  # ({actor_id: actor}, {lease_id: lease}) SpacetimeDB holds, or None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._idle = threading.Event()  # set while SpacetimeDB matches memory (for tests)
        self._lock = threading.Lock()
        self._generation = 0  # counts changes to memory
        self._thread = threading.Thread(target=self._run, name="spacetime-mirror", daemon=True)
        self._thread.start()

    # SessionStore: memory answers

    def join(self, actor):
        self.memory.join(actor)
        self._changed()

    def leave(self, actor_id):
        self.memory.leave(actor_id)
        self._changed()

    def renew(self, actor_id):
        self.memory.renew(actor_id)

    def acquire(self, owner_id, mode, targets, lease_id=None):
        lease = self.memory.acquire(owner_id, mode, targets, lease_id)
        self._changed()
        return lease

    def release(self, lease_id, owner_id):
        self.memory.release(lease_id, owner_id)
        self._changed()

    def expire(self):
        self.memory.expire()
        self._changed()

    def session(self):
        return self.memory.session()

    def record_receipt(self, receipt, digest=""):
        self.memory.record_receipt(receipt, digest)

    def replay(self, request_id, digest):
        return self.memory.replay(request_id, digest)

    def receipts(self, request_ids):
        return self.memory.receipts(request_ids)

    def close(self):
        """Stop copying. The thread removes this host's participants from SpacetimeDB on its
        way out, if it can; never waits for that."""
        self._stop.set()
        self._wake.set()

    def wait_idle(self, timeout):
        """Wait until SpacetimeDB matches memory. True if it does. For tests and checks."""
        return self._idle.wait(timeout)

    def _changed(self):
        with self._lock:
            self._generation += 1
            self._idle.clear()
            self._wake.set()

    # The copy, on the spacetime-mirror thread

    def _run(self):
        renewed = 0.0
        while not self._stop.is_set():
            self._wake.clear()
            with self._lock:
                generation = self._generation
            try:
                if self._remote is None:
                    self._remote = self._connect()
                    self._pushed = None
                if self._pushed is None:
                    self._clear()
                self._push()
                if time.monotonic() - renewed >= self._renew_s:
                    for actor_id in list(self._pushed[0]):
                        self._write("renew", {"actor_id": actor_id, "ttl_ms": LEASE_TTL_MS})
                    renewed = time.monotonic()
                self._set_status(f"Sharing participants and leases with SpacetimeDB at "
                                 f"{self._remote.url}")
                with self._lock:
                    if generation == self._generation:
                        self._idle.set()
                wait = self._renew_s
            except (StoreUnavailable, SessionError) as e:
                self._pushed = None
                if isinstance(e, SessionError):  # claim_host refused: another host owns it
                    self._remote = None
                self._set_status(f"Not using SpacetimeDB: {e}")
                wait = self._retry_s
            except Exception:
                log.exception("the SpacetimeDB copy failed")
                self._pushed = None
                self._set_status("Not using SpacetimeDB: the copy failed (see the console)")
                wait = self._retry_s
            self._wake.wait(wait)
        self._leave_all()

    def _clear(self):
        """Remove every participant and lease an earlier host left in SpacetimeDB."""
        owners = {r["actor_id"] for r in self._remote.select("SELECT * FROM participant")}
        owners |= {r["owner_id"] for r in self._remote.select("SELECT * FROM lease")}
        for actor_id in owners:
            self._remote.call("leave", {"actor_id": actor_id})
        self._pushed = ({}, {})

    def _push(self):
        """Make SpacetimeDB's participants and leases match memory's."""
        want = self.memory.session()
        actors = {a["actor_id"]: a for a in want["participants"]}
        held = {x["lease_id"]: x for x in want["leases"]}
        have_actors, have_leases = self._pushed
        for actor_id in [a for a in have_actors if a not in actors]:
            self._write("leave", {"actor_id": actor_id})
            del have_actors[actor_id]
            for lease_id in [k for k, v in have_leases.items() if v["owner"]["actor_id"] == actor_id]:
                del have_leases[lease_id]
        for lease_id in [k for k in have_leases if k not in held]:
            owner_id = have_leases[lease_id]["owner"]["actor_id"]
            self._write("release", {"lease_id": lease_id, "owner_id": owner_id})
            del have_leases[lease_id]
        for actor_id, actor in actors.items():
            if have_actors.get(actor_id) != actor:
                self._write("join", {k: actor[k] for k in ("actor_id", "name", "role")})
                have_actors[actor_id] = actor
        for lease_id, lease in held.items():
            if lease_id not in have_leases:
                self._write("acquire", {
                    "lease_id": lease_id,
                    "owner_id": lease["owner"]["actor_id"],
                    "mode": lease["mode"],
                    "targets": list(lease["targets"]),
                    "ttl_ms": LEASE_TTL_MS,
                })
                have_leases[lease_id] = lease

    def _write(self, reducer, args):
        """Call a reducer. A rejection is logged, not raised: memory decided already."""
        try:
            self._remote.call(reducer, args)
        except SessionError as e:
            log.warning("SpacetimeDB rejected %s from the host: %s", reducer, e)

    def _leave_all(self):
        if self._remote is None or not self._pushed:
            return
        try:
            for actor_id in self._pushed[0]:
                self._remote.call("leave", {"actor_id": actor_id})
        except (StoreUnavailable, SessionError):
            pass  # its leases lapse within LEASE_TTL_MS anyway

    def _set_status(self, text):
        if text != self.status:
            log.info("%s", text)
            print("Spatial Modeling:", text)
        self.status = text


def _replayed(request_id, row, digest):
    if row is None:
        return None
    if row["digest"] != digest:
        raise SessionError(
            "duplicate_request", f"request {request_id} was sent with another payload"
        )
    return json.loads(row["body"])


def _found_and_missing(request_ids, rows):
    found, missing = [], []
    for request_id in dict.fromkeys(request_ids):
        if request_id in rows:
            found.append(json.loads(rows[request_id]["body"]))
        else:
            missing.append(request_id)
    return found, missing

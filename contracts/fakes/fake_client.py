#!/usr/bin/env python3
"""Fake client: joins a host, prints what it sends and sends commands you type.

TEST DATA ONLY. It stands in for the Unity app or a Client-role add-on while
debugging; nothing it shows counts as acceptance evidence (PHASE_PLAN.md).

    python3 contracts/fakes/fake_client.py                          # watch everything
    python3 contracts/fakes/fake_client.py "move Shaft 10mm 0 0" --exit
    python3 contracts/fakes/fake_client.py --help                   # every shortcut
    python3 contracts/fakes/fake_client.py --check "lose move Shaft 10mm 0 0" --exit
                                    # lost acknowledgement: reconnect, then receipt.query

It works against contracts/fakes/fake_host.py and the real Host-role add-on. It
does the handshake from contracts/README.md, pings every 2 s, prints a summary
of the snapshot and of every update, activity, session and result message, and
builds commands from short text or JSON.

Plain TCP only. It doesn't do the LAN port's TLS or token yet (port 8767, issue
#19, see blender_addon/spatial_modeling/lan.py), so it reaches the host's
localhost port 8765 or a fake host.

Standard library only and Python 3.9 or newer. --check also validates every
message against contracts/schemas and needs `pip install jsonschema`.
"""

import argparse
import json
import math
import queue
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

VERSION = 1
MAX_LINE_BYTES = 16 * 1024 * 1024
PORT = 8765
APP = {"name": "spatial_modeling-fake-client", "version": "0.1.0"}
PING_EVERY = 2.0
NOT_RESPONDING_AFTER = 6.0
RECONNECT_EVERY = 2.0
WAIT = 10.0  # seconds to wait for the answer to a request
REPLY_TYPES = ("hello", "ping", "command", "receipt.query", "lease.acquire")
REQUEST_FIELDS = ("session_id", "host_epoch", "document_id", "open_epoch", "actor_id")

SHORTCUTS = """\
Commands (type them, or pass them as arguments). OBJ is a name, an ID or the
start of either. Bare numbers are meters and radians, as on the wire; add mm, cm
or m to lengths and deg or rad to angles.

  move OBJ DX DY DZ             object.move by        move Shaft 10mm 0 0
  moveto OBJ X Y Z              object.move to        moveto Shaft 0 0 30mm
  rotate OBJ X|Y|Z ANGLE        object.rotate by      rotate Shaft Z 90deg
  rotateto OBJ W X Y Z          object.rotate to      rotateto Shaft 1 0 0 0
  scale OBJ SX SY SZ            object.scale by       scale Shaft 1 1 1.5
  scaleto OBJ SX SY SZ          object.scale to
  add cube|sphere|cylinder X Y Z DX DY DZ             add cylinder -20mm 0 30mm 20mm 20mm 40mm
  delete OBJ                    object.delete
  undo | redo | save            history.undo, history.redo, document.save
  lease OBJ [OBJ ...]           lease.acquire shared  lease Shaft
  lease all                     lease.acquire exclusive (the whole document)
  release [LEASE]               lease.release (default: your newest lease)
  {"op": ..., "target": OBJ, "args": {...}}           any command: request fields,
                                base_revision, source and the target's generation
                                are filled in
  {"type": ..., "payload": {...}}                     any message, sent as it is
                                (v and id are added if missing)
  again                         resend the last command with the same ID
                                (the host answers with the stored result)
  lose COMMAND                  send COMMAND, then drop the connection before its
                                result; reconnect and ask for it with receipt.query
  query [ID ...]                receipt.query for the last command, or these IDs
  scene | who | help | quit
"""


def new_id():
    return uuid.uuid4().hex


def message(type_, payload=None, re=None):
    msg = {"v": VERSION, "type": type_, "id": new_id(), "payload": payload or {}}
    if re is not None:
        msg["re"] = re
    return msg


def encode(msg):
    text = json.dumps(msg, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return text.encode("utf-8") + b"\n"


class UsageError(ValueError):
    """A typed command that can't be sent; print it and carry on."""


# Numbers and text.

LENGTH_UNITS = (("mm", 0.001), ("cm", 0.01), ("m", 1.0))
ANGLE_UNITS = (("deg", math.pi / 180), ("rad", 1.0))


def _number(word, units, what):
    factor = 1.0
    for suffix, scale in units:
        if word.lower().endswith(suffix):
            word, factor = word[: -len(suffix)], scale
            break
    try:
        value = float(word)
    except ValueError:
        raise UsageError(f"{what} {word!r} is not a number") from None
    if not math.isfinite(value):
        raise UsageError(f"{what} must be finite")
    return round(value * factor, 9)


def length(word):
    return _number(word, LENGTH_UNITS, "length")


def angle(word):
    return _number(word, ANGLE_UNITS, "angle")


def plain(word):
    return _number(word, (), "value")


def mm(meters):
    text = f"{meters * 1000:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def point(values):
    return "(" + ", ".join(mm(v) for v in values) + ") mm"


def rotation(q):
    w, x, y, z = q
    half = math.acos(max(-1.0, min(1.0, abs(w))))
    degrees = round(math.degrees(2 * half), 2)
    if degrees == 0:
        return "no rotation"
    s = math.sin(half) * (1 if w >= 0 else -1)
    axis = [x / s, y / s, z / s]
    for i, name in enumerate("XYZ"):
        if abs(abs(axis[i]) - 1) < 1e-4:
            return f"{degrees:g} deg about {'-' if axis[i] < 0 else ''}{name}"
    return f"{degrees:g} deg about ({', '.join(f'{c:.3f}' for c in axis)})"


def size(record):
    mesh = record.get("mesh")
    if not mesh or not mesh.get("positions"):
        return "no mesh"
    p = mesh["positions"]
    scale = record["transform"]["scale"]
    extent = [(max(p[i::3]) - min(p[i::3])) * abs(scale[i]) for i in range(3)]
    triangles = len(mesh.get("indices", ())) // 3
    return f"{' x '.join(mm(v) for v in extent)} mm, {triangles} triangles"


def describe_object(record, objects):
    t = record["transform"]
    scale = t["scale"]
    text = (f"{record['name']:<12} {record['id'][:8]}  {record['type']:<7} at {point(t['location'])}, "
            f"{rotation(t['rotation'])}")
    if any(abs(s - 1) > 1e-9 for s in scale):
        text += ", scale " + " x ".join(f"{s:g}" for s in scale)
    text += f", {size(record)}, gen {record['generation']}"
    parent = record.get("parent")
    if parent:
        text += f", child of {objects[parent]['name'] if parent in objects else parent[:8]}"
    if not record.get("visible", True):
        text += ", hidden"
    return text


def describe_sketch(sketch):
    kinds = [e["kind"] for e in sketch["entities"]]
    counts = ", ".join(f"{kinds.count(k)} {k}s" for k in ("point", "line", "circle"))
    solver = sketch["solver"]
    return (f"{sketch['name']:<12} {sketch['id'][:8]}  SKETCH  {counts}, "
            f"{len(sketch['constraints'])} constraints, {solver['status']} (dof {solver['dof']}), "
            f"gen {sketch['generation']}")


def describe_document(d):
    units = d["units"]
    return (f"{d['name'] or '(never saved)'}, revision {d['revision']}, "
            f"{'unsaved changes' if d['dirty'] else 'saved'}, units {units['system']} "
            f"{units['length_unit']} (scale_length {units['scale_length']:g})")


def describe_actor(actor):
    return f"{actor['name']} [{actor['role']}]"


def describe_error(e):
    text = f"{e.get('code')}: {e.get('message')}"
    if e.get("details"):
        text += " " + json.dumps(e["details"], separators=(",", ":"))
    return text


def load_checker():
    """A function that lists a message's schema violations, using contracts/schemas."""
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError:
        sys.exit("--check needs jsonschema: pip install jsonschema")
    folder = Path(__file__).resolve().parent.parent / "schemas"
    schemas = {}
    for path in folder.glob("*.schema.json"):
        schemas[path.name[: -len(".schema.json")]] = json.loads(path.read_text("utf-8"))
    if not schemas:
        sys.exit(f"--check: no schemas in {folder}")
    registry = Registry().with_resources(
        (s["$id"], Resource.from_contents(s)) for s in schemas.values()
    )

    def check(msg):
        schema = schemas.get(msg.get("type")) if isinstance(msg, dict) else None
        if schema is None:
            return [f"no schema for type {msg.get('type') if isinstance(msg, dict) else msg!r}"]
        validator = Draft202012Validator(schema, registry=registry)
        return [
            f"{'/'.join(str(p) for p in e.absolute_path) or '(message)'}: {e.message[:200]}"
            for e in validator.iter_errors(msg)
        ]

    return check


class FakeClient:
    """One participant. Threads: a reader per connection, a heartbeat, and the caller's."""

    def __init__(self, host="127.0.0.1", port=PORT, name="Fake client", role="vr", source="ui",
                 document=None, reconnect=False, verbose=False, check=None, out=None):
        self.host, self.port = host, port
        self.name, self.role, self.source = name, role, source
        self.expect_document = document  # {"id", "open_epoch"} for hello, or None
        self.reconnect = reconnect
        self.verbose = verbose
        self.check = check
        self.violations = 0
        self.out = out or self._print
        self._print_lock = threading.Lock()
        self._send_lock = threading.Lock()  # the heartbeat and the caller both send
        self.lock = threading.Condition()
        self.sock = None
        self.hello_id = None
        self.welcome = None
        self.connected = False  # welcome and scene.snapshot arrived
        self.refused = None  # error that answered our hello
        self.finished = False  # no connection and no reconnect coming
        self.stopping = False
        self.document = None
        self.objects = {}
        self.sketches = {}
        self.participants, self.leases = [], []
        self.replies = {}  # id of a request we sent -> the message answering it
        # Request ID -> the host_epoch it was sent under, which receipt.query names.
        self.pending = {}  # commands sent on this connection without an answer yet
        self.unknown = {}  # commands whose outcome we lost; asked about after the next welcome
        self.querying = {}  # asked about with receipt.query; no edits until the answer
        self.sent_under = {}  # every command we sent
        self.rejoin_once = False  # `lose`: reconnect after this drop even without --reconnect
        self.dropping = None  # `lose`: the socket we hung up; what still arrives on it is lost
        self.user_pings = set()
        self.last_command = None
        self.last_heard = time.monotonic()
        self.last_ping = 0.0
        self.not_responding = False
        self._heartbeat = None

    def _print(self, text):
        with self._print_lock:
            print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)

    # Connection

    def start(self):
        """Connect and send hello. Raises OSError if the host can't be reached."""
        self._connect()
        if self._heartbeat is None:
            self._heartbeat = threading.Thread(target=self._beat, name="heartbeat", daemon=True)
            self._heartbeat.start()

    def _connect(self):
        sock = socket.create_connection((self.host, self.port), timeout=5)
        sock.settimeout(None)
        payload = {"role": self.role, "name": self.name, "app": dict(APP)}
        document = self.expect_document
        if self.role == "blender-client" and self.document is not None:
            # Like the Client role: only rejoin the document we had (wrong_document otherwise).
            document = {"id": self.document["id"], "open_epoch": self.document["open_epoch"]}
        if document is not None:
            payload["document"] = document
        hello = message("hello", payload)
        with self.lock:
            self.sock = sock
            self.hello_id = hello["id"]
            self.connected = False
            self.refused = None
            self.finished = False
            self.last_heard = time.monotonic()
            self.not_responding = False
        self.out(f"connected to {self.host}:{self.port}; sending hello as {self.name} ({self.role})")
        self._send(sock, hello)
        threading.Thread(target=self._read, args=(sock,), name="reader", daemon=True).start()

    def wait_connected(self, timeout=WAIT):
        """True once welcome and the snapshot arrived; False if refused, closed or too slow."""
        with self.lock:
            self.lock.wait_for(lambda: self.connected or self.refused or self.finished, timeout)
            return self.connected

    def close(self):
        with self.lock:
            self.stopping = True
            sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _send(self, sock, msg):
        data = encode(msg)
        if self.check is not None:
            self._report(self.check(msg), "sent", msg)
        if self.verbose:
            self.out(f"-> {data.decode('utf-8').strip()[:500]}")
        with self._send_lock:
            sock.sendall(data)

    def _reply(self, sock, msg):
        """Send from the reader thread; a closed socket is the reader's to notice."""
        try:
            self._send(sock, msg)
        except OSError:
            pass

    def _report(self, problems, direction, msg):
        for problem in problems:
            self.violations += 1
            self.out(f"! schema: {direction} {msg.get('type')}: {problem}")

    def _beat(self):
        while not self.stopping:
            time.sleep(0.25)
            with self.lock:
                sock = self.sock
                now = time.monotonic()
                silent = sock is not None and now - self.last_heard > NOT_RESPONDING_AFTER
                if silent and not self.not_responding:
                    self.not_responding = True
                    self.out(f"host not responding: nothing heard for {NOT_RESPONDING_AFTER:g} s "
                             "(edits disabled until it answers)")
                due = sock is not None and now - self.last_ping >= PING_EVERY
                if due:
                    self.last_ping = now
            if due:
                try:
                    self._send(sock, message("ping"))
                except OSError:
                    pass  # the reader notices the closed socket

    def _read(self, sock):
        buffer = b""
        while True:
            try:
                chunk = sock.recv(65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if line.strip():
                    self._receive(sock, line)
            if len(buffer) > MAX_LINE_BYTES:
                self.out(f"! the host sent a line longer than {MAX_LINE_BYTES} bytes; closing")
                break
        self._closed(sock)

    def _closed(self, sock):
        with self.lock:
            if sock is not self.sock and not self.stopping:
                return  # an older connection
            self.sock = None
            lost, self.pending = self.pending, {}
            self.unknown.update(lost)
            self.unknown.update(self.querying)  # the answer was lost too: ask again
            self.querying = {}
            again = ((self.reconnect or self.rejoin_once) and not self.stopping
                     and self.refused is None)
            self.rejoin_once = False
            if sock is self.dropping:
                self.dropping = None
            self.finished = not again
            self.connected = False
            self.lock.notify_all()
        try:
            sock.close()
        except OSError:
            pass
        if self.stopping:
            return
        text = "disconnected: the host closed the connection. Keeping the last scene as stale"
        if lost:
            text += f"; outcome unknown for {len(lost)} command(s)"
        self.out(text + (f"; reconnecting every {RECONNECT_EVERY:g} s" if again else ""))
        if again:
            threading.Thread(target=self._reconnect, name="reconnect", daemon=True).start()

    def _reconnect(self):
        failed = False
        while not self.stopping:
            time.sleep(RECONNECT_EVERY)
            try:
                self._connect()
                return
            except OSError as e:
                if not failed:
                    self.out(f"reconnect failed ({e}); still trying every {RECONNECT_EVERY:g} s")
                failed = True

    # Messages from the host

    def _receive(self, sock, line):
        if sock is self.dropping:
            return  # `lose`: the answer is lost on the way
        try:
            msg = json.loads(line)
        except ValueError:
            self.out(f"! the host sent a line that isn't JSON: {line[:200]!r}")
            return
        if self.verbose:
            self.out(f"<- {line.decode('utf-8', 'replace')[:500]}")
        if self.check is not None:
            self._report(self.check(msg), "received", msg)
        if not isinstance(msg, dict) or not isinstance(msg.get("payload"), dict):
            self.out(f"! the host sent something that isn't a message: {line[:200]!r}")
            return
        with self.lock:
            self.last_heard = time.monotonic()
            if self.not_responding:
                self.not_responding = False
                self.out("host is responding again")
            try:
                self._dispatch(sock, msg)
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                self.out(f"! could not read {msg.get('type')} ({type(e).__name__}: {e}): "
                         f"{line[:300]!r}")
            finally:
                if isinstance(msg.get("re"), str):
                    self.replies[msg["re"]] = msg
                    self.pending.pop(msg["re"], None)
                self.lock.notify_all()

    def _dispatch(self, sock, msg):
        kind, p = msg.get("type"), msg["payload"]
        if kind == "ping":
            self._reply(sock, message("pong", re=msg["id"]))
        elif kind == "pong":
            if msg.get("re") in self.user_pings:
                self.out("pong")
        elif kind == "welcome":
            self._on_welcome(p)
        elif kind == "scene.snapshot":
            self.document = p["document"]
            self.objects = {o["id"]: o for o in p["objects"]}
            self.sketches = {s["id"]: s for s in p["sketches"]}
            self.connected = True
            self.unknown.clear()  # the fresh snapshot is the truth (asked about in welcome)
            lines = [f"scene.snapshot: {describe_document(self.document)}"]
            lines += ["  " + describe_object(o, self.objects) for o in self.objects.values()]
            lines += ["  " + describe_sketch(s) for s in self.sketches.values()]
            self.out("\n".join(lines))
        elif kind == "scene.update":
            self._on_update(p)
        elif kind == "session.update":
            seen = {lease["lease_id"] for lease in self.leases}
            self.participants, self.leases = p["participants"], p["leases"]
            self.out("session.update: " + self._describe_session())
            me = self.welcome["actor_id"] if self.welcome else None
            for lease in self.leases:  # a new lease is the notice that someone started editing
                if lease["lease_id"] not in seen and lease["owner"]["actor_id"] != me:
                    what = ", ".join(self._name(t) for t in lease["targets"]) or "the document"
                    self.out(f"{describe_actor(lease['owner'])} started editing {what}")
        elif kind == "result":
            self._on_receipt("result", p)
        elif kind == "activity":
            self._on_receipt("activity", p)
        elif kind == "receipts":
            lines = ["receipts:"] + [
                f"  {r['request_id'][:8]} {r['op']}: {r['outcome']}, revision {r['revision']}"
                + (f", {describe_error(r['error'])}" if r.get("error") else "")
                for r in p["receipts"]
            ]
            lines += [f"  {m[:8]}: missing (never received, so not applied)" for m in p["missing"]]
            lines += [f"  {m[:8]}: unknown (sent before the host restarted; it may have applied: "
                      "check the scene)" for m in p["unknown"]]
            self.out("\n".join(lines))
            for r in p["receipts"]:
                self.querying.pop(r["request_id"], None)
            for rid in p["missing"] + p["unknown"]:
                self.querying.pop(rid, None)
        elif kind == "error":
            self._on_error(msg)
        elif kind == "lease.granted":
            lease = p["lease"]
            self.out(f"lease.granted: {lease['mode']} lease {lease['lease_id'][:8]} on "
                     f"{', '.join(self._name(t) for t in lease['targets']) or 'the document'}")
        else:
            self.out(f"{kind}: {json.dumps(p)[:300]}")

    def _on_welcome(self, p):
        d = p["document"]
        before = self.document
        self.welcome = p
        self.out(f"welcome: actor {p['actor_id'][:8]}, can_edit={p['can_edit']}, host "
                 f"{p['app']['name']} {p['app']['version']}, session {p['session_id'][:8]}, "
                 f"host_epoch {p['host_epoch'][:8]}")
        if before is not None:
            if (before["id"], before["open_epoch"]) != (d["id"], d["open_epoch"]):
                self.out(f"Wrong document: the host now has {d['name']} open (open_epoch "
                         f"{d['open_epoch'][:8]}, was {before['open_epoch'][:8]}); dropping "
                         "everything held for the old one")
            else:
                self.out("same document; the fresh snapshot replaces the stale scene")
        if self.unknown:  # ask, never resend; one receipt.query per host_epoch they were sent under
            epochs, count = {}, len(self.unknown)
            for rid, epoch in sorted(self.unknown.items()):
                epochs.setdefault(epoch, []).append(rid)
            for epoch, ids in epochs.items():
                for i in range(0, len(ids), 100):
                    self._query(self.sock, epoch, ids[i:i + 100])
            when = "before the host restarted" if set(epochs) != {p["host_epoch"]} else "earlier"
            self.out(f"asked for the receipts of {count} command(s) with unknown outcome, "
                     f"sent {when}")

    def _on_update(self, p):
        self.document = p["document"]
        state = "unsaved changes" if self.document["dirty"] else "saved"
        lines = [f"scene.update: revision {self.document['revision']}, {state}"]
        for o in p["objects"]:
            old = self.objects.get(o["id"])
            if "mesh" not in o and old is not None:
                o = dict(o, mesh=old.get("mesh"))
            self.objects[o["id"]] = o
            lines.append(("  added   " if old is None else "  changed ")
                         + describe_object(o, self.objects))
        for s in p["sketches"]:
            self.sketches[s["id"]] = s
            lines.append("  sketch  " + describe_sketch(s))
        for oid in p["removed"]:
            gone = self.objects.pop(oid, None) or self.sketches.pop(oid, None)
            lines.append(f"  removed {gone['name'] if gone else oid[:8]}")
        self.out("\n".join(lines))

    def _on_receipt(self, kind, r):
        if kind == "result":
            text = f"result: {r['outcome']} at revision {r['revision']}"
        else:
            a = r["actor"]
            text = f"activity: {a['name']} [{a['role']}, {r['source']}] at revision {r['revision']}"
        if r.get("summary"):
            text += f": {r['summary']}"
        if r.get("created"):
            text += f" (created {', '.join(c[:8] for c in r['created'])})"
        if r.get("solver"):
            text += f" (solver {r['solver']['status']})"
        if r.get("error"):
            text += f": {describe_error(r['error'])}"
        self.out(text)

    def _on_error(self, msg):
        p = msg["payload"]
        re_ = msg.get("re")
        if re_ is not None and re_ == self.hello_id:
            self.refused = msg
            self.out(f"error: the host refused hello: {describe_error(p)}")
            if p.get("code") == "unknown_type":
                self.out("(the add-on doesn't handle hello yet; P0 answers only ping)")
            return
        if re_ in self.pending and p.get("code") == "internal_error":
            self.unknown[re_] = self.pending[re_]  # the command may or may not have run
        self.out(f"error{' answering ' + re_[:8] if re_ else ''}: {describe_error(p)}")

    def _describe_session(self):
        me = self.welcome["actor_id"] if self.welcome else None
        people = ", ".join(describe_actor(a) + (" (you)" if a["actor_id"] == me else "")
                           for a in self.participants)
        leases = ", ".join(
            f"{describe_actor(lease['owner'])} {lease['mode']} on "
            f"{', '.join(self._name(t) for t in lease['targets']) or 'the document'}"
            for lease in self.leases
        )
        return f"participants {people}; leases: {leases or 'none'}"

    def _name(self, oid):
        found = self.objects.get(oid) or self.sketches.get(oid)
        return found["name"] if found else oid[:8]

    # Commands

    def resolve(self, ref):
        """An object or sketch by ID, name, or the start of either."""
        records = list(self.objects.values()) + list(self.sketches.values())
        for test in (
            lambda r: r["id"] == ref,
            lambda r: r["name"].lower() == ref.lower(),
            lambda r: r["id"].startswith(ref) or r["name"].lower().startswith(ref.lower()),
        ):
            found = [r for r in records if test(r)]
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                names = ", ".join(f"{r['name']} ({r['id'][:8]})" for r in found)
                raise UsageError(f"{ref!r} could be {names}")
        raise UsageError(f"no object or sketch called {ref!r}; type scene to list them")

    def command(self, fragment):
        """A full command message from {op, target, args, ...}; target may be a name or ID."""
        if not self.welcome or not self.document:
            raise UsageError("not connected yet")
        w = self.welcome
        payload = {
            "session_id": w["session_id"],
            "host_epoch": w["host_epoch"],
            "document_id": w["document"]["id"],
            "open_epoch": w["document"]["open_epoch"],
            "actor_id": w["actor_id"],
            "base_revision": self.document["revision"],
            "source": self.source,
        }
        payload.update({k: v for k, v in fragment.items() if k != "target"})
        payload.setdefault("args", {})
        target = fragment.get("target")
        if isinstance(target, str):
            record = self.resolve(target)
            payload["target"] = {"id": record["id"], "generation": record["generation"]}
        elif isinstance(target, dict) and "generation" not in target and "id" in target:
            record = self.resolve(target["id"])
            payload["target"] = {"id": record["id"], "generation": record["generation"]}
        elif target is not None:
            payload["target"] = target
        return message("command", payload)

    def parse(self, text):
        """Turn one typed line into a message dict (see SHORTCUTS)."""
        text = text.strip()
        if text.startswith("{"):
            try:
                given = json.loads(text)
            except ValueError as e:
                raise UsageError(f"not JSON: {e}") from None
            if not isinstance(given, dict):
                raise UsageError("give a JSON object")
            if "type" in given:
                msg = {"v": VERSION, "type": given["type"], "id": new_id(), "payload": {}}
                msg.update(given)
                return msg
            return self.command(given)
        words = text.split()
        verb, rest = words[0].lower(), words[1:]

        def need(count, usage):
            if len(rest) != count:
                raise UsageError(f"usage: {usage}")

        if verb in ("move", "moveto"):
            need(4, f"{verb} OBJ X Y Z")
            key = "by" if verb == "move" else "to"
            return self.command({"op": "object.move", "target": rest[0],
                                 "args": {key: [length(w) for w in rest[1:]]}})
        if verb == "rotate":
            need(3, "rotate OBJ X|Y|Z ANGLE")
            return self.command({"op": "object.rotate", "target": rest[0],
                                 "args": {"by": {"axis": rest[1].upper(), "angle": angle(rest[2])}}})
        if verb == "rotateto":
            need(5, "rotateto OBJ W X Y Z")
            return self.command({"op": "object.rotate", "target": rest[0],
                                 "args": {"to": [plain(w) for w in rest[1:]]}})
        if verb in ("scale", "scaleto"):
            need(4, f"{verb} OBJ SX SY SZ")
            key = "by" if verb == "scale" else "to"
            return self.command({"op": "object.scale", "target": rest[0],
                                 "args": {key: [plain(w) for w in rest[1:]]}})
        if verb == "add":
            need(7, "add cube|sphere|cylinder X Y Z DX DY DZ")
            values = [length(w) for w in rest[1:]]
            return self.command({"op": "object.add", "args": {
                "primitive": rest[0].lower(), "location": values[:3], "dimensions": values[3:]}})
        if verb == "delete":
            need(1, "delete OBJ")
            return self.command({"op": "object.delete", "target": rest[0]})
        if verb == "lease":
            if not rest:
                raise UsageError("usage: lease OBJ [OBJ ...] | lease all")
            if not self.welcome:
                raise UsageError("not connected yet")
            w = self.welcome
            payload = {k: w[k] for k in ("session_id", "host_epoch", "actor_id")}
            payload.update(document_id=w["document"]["id"], open_epoch=w["document"]["open_epoch"])
            if rest == ["all"]:
                payload.update(mode="exclusive", targets=[])
            else:
                payload.update(mode="shared", targets=[self.resolve(r)["id"] for r in rest])
            return message("lease.acquire", payload)
        if verb == "release":
            me = self.welcome["actor_id"] if self.welcome else None
            mine = [x["lease_id"] for x in self.leases if x["owner"]["actor_id"] == me]
            if len(rest) > 1:
                raise UsageError("usage: release [LEASE]")
            found = [i for i in mine if not rest or i.startswith(rest[0])]
            if rest and not found:
                found = [rest[0]]  # send it anyway; the host answers not_found
            if not found:
                raise UsageError("you hold no lease")
            return message("lease.release", {"lease_id": found[-1]})
        ops = {"undo": "history.undo", "redo": "history.redo", "save": "document.save"}
        if verb in ops:
            need(0, verb)
            return self.command({"op": ops[verb]})
        raise UsageError(f"unknown command {verb!r}; type help")

    def send(self, msg, wait=True, timeout=WAIT):
        """Send a message. For a request, wait for its answer and return it (None if none came)."""
        with self.lock:
            sock = self.sock
            if sock is None:
                raise UsageError("not connected")
            if msg.get("type") == "command":
                if not self.connected:
                    raise UsageError("no snapshot yet; edits wait until then")
                if self.not_responding:
                    raise UsageError("host not responding; edits are disabled")
                if self.unknown or self.querying:
                    count = len(self.unknown) + len(self.querying)
                    raise UsageError(f"{count} command outcome(s) unknown; edits wait for the "
                                     "receipts and a fresh snapshot")
                self.pending[msg["id"]] = msg["payload"]["host_epoch"]
                self.sent_under[msg["id"]] = msg["payload"]["host_epoch"]
                self.last_command = msg
            if msg.get("type") == "ping":
                self.user_pings.add(msg["id"])
            self.replies.pop(msg.get("id"), None)
        self._send(sock, msg)
        if not wait or msg.get("type") not in REPLY_TYPES:
            return None
        with self.lock:
            answered = self.lock.wait_for(lambda: msg["id"] in self.replies or self.sock is None,
                                          timeout)
            if not answered:
                self.out(f"no answer to {msg['type']} {msg['id'][:8]} within {timeout:g} s")
            return self.replies.get(msg["id"])

    def run(self, text, wait=True):
        """Do one typed line. Returns the answer to a request, or None."""
        verb = text.strip().split()[0].lower() if text.strip() else ""
        if verb in ("", "help"):
            self.out(SHORTCUTS)
            return None
        if verb == "scene":
            with self.lock:
                lines = [describe_document(self.document)] if self.document else ["no scene yet"]
                lines += ["  " + describe_object(o, self.objects) for o in self.objects.values()]
                lines += ["  " + describe_sketch(s) for s in self.sketches.values()]
            self.out("\n".join(lines))
            return None
        if verb == "who":
            with self.lock:
                self.out(self._describe_session())
            return None
        if verb == "again":
            if self.last_command is None:
                raise UsageError("no command sent yet")
            with self.lock:
                if self.sock is None:
                    raise UsageError("not connected")
                self.pending[self.last_command["id"]] = self.last_command["payload"]["host_epoch"]
                self.replies.pop(self.last_command["id"], None)
            self.out(f"> {text.strip()} ({self.last_command['payload']['op']}, same ID)")
            return self._resend(self.last_command, wait)
        if verb == "lose":
            return self.lose(text.strip()[len("lose"):].strip(), wait)
        if verb == "query":
            return self.query(text.split()[1:], wait)
        with self.lock:
            msg = self.parse(text)
        self.out(f"> {text.strip()}")
        return self.send(msg, wait)

    def _query(self, sock, host_epoch, ids):
        """Send receipt.query from the reader thread; returns the message."""
        msg = message("receipt.query", {"host_epoch": host_epoch, "request_ids": ids})
        for rid in ids:
            self.querying[rid] = host_epoch
        self.unknown = {k: v for k, v in self.unknown.items() if k not in self.querying}
        self._reply(sock, msg)
        return msg

    def query(self, refs, wait=True):
        """receipt.query for the last command or the given request IDs; returns the answer."""
        with self.lock:
            if not refs:
                if self.last_command is None:
                    raise UsageError("no command sent yet; give request IDs")
                refs = [self.last_command["id"]]
            known = {}
            for ref in refs:
                found = [rid for rid in self.sent_under if rid.startswith(ref)]
                if len(found) == 1:
                    known[found[0]] = self.sent_under[found[0]]
                elif len(ref) == 32:  # someone else's, or before this client started
                    known[ref] = self.welcome["host_epoch"] if self.welcome else None
                else:
                    raise UsageError(f"{ref!r} isn't one request ID we sent; give all 32 digits")
            if None in known.values() or self.sock is None:
                raise UsageError("not connected")
        answer = None
        for epoch in dict.fromkeys(known.values()):
            ids = [rid for rid, e in known.items() if e == epoch]
            msg = message("receipt.query", {"host_epoch": epoch, "request_ids": ids[:100]})
            self.out(f"> receipt.query for {', '.join(i[:8] for i in ids)}")
            answer = self.send(msg, wait)
        return answer

    def lose(self, text, wait=True):
        """Send a command and drop the connection before its result: a lost acknowledgement.

        Reconnects (even without --reconnect), and returns the `receipts` that answer the
        receipt.query sent after the new welcome, or None.
        """
        if not text:
            raise UsageError("usage: lose COMMAND, for example lose move Shaft 10mm 0 0")
        with self.lock:
            msg = self.parse(text)
            if msg.get("type") != "command":
                raise UsageError("lose needs a command")
            if not self.connected or self.unknown or self.querying:
                raise UsageError("edits wait for a snapshot and for unknown outcomes first")
            sock = self.sock
            epoch = msg["payload"]["host_epoch"]
            self.pending[msg["id"]] = self.sent_under[msg["id"]] = epoch
            self.last_command = msg
            self.rejoin_once = True
            self.dropping = sock
        self.out(f"> {text} (then dropping the connection before the result)")
        self._send(sock, msg)
        try:
            sock.shutdown(socket.SHUT_WR)  # the host closes too; then the reader reconnects
        except OSError:
            pass
        if not wait:
            return None
        rid = msg["id"]

        def answers(m):
            p = m["payload"]
            return m.get("type") == "receipts" and (
                rid in p["missing"] or rid in p["unknown"]
                or any(r["request_id"] == rid for r in p["receipts"]))

        with self.lock:
            settled = (lambda: self.finished or self.connected and not {rid} & (
                self.pending.keys() | self.unknown.keys() | self.querying.keys()))
            self.lock.wait_for(settled, WAIT + RECONNECT_EVERY)
            answer = next((m for m in self.replies.values() if answers(m)), None)
        if answer is None:
            self.out(f"no receipts for {rid[:8]} after reconnecting")
        return answer

    def _resend(self, msg, wait):
        self._send(self.sock, msg)
        if not wait:
            return None
        with self.lock:
            self.lock.wait_for(lambda: msg["id"] in self.replies or self.sock is None, WAIT)
            return self.replies.get(msg["id"])


def _document(text):
    try:
        doc_id, open_epoch = text.split(":")
    except ValueError:
        raise argparse.ArgumentTypeError("use DOCUMENT_ID:OPEN_EPOCH") from None
    return {"id": doc_id, "open_epoch": open_epoch}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="fake_client.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Fake client for the host connection (contracts/README.md). TEST DATA ONLY: "
        "never acceptance evidence.\nConnects, does the handshake, pings every 2 s, prints the "
        "snapshot and every update, and sends commands.\n\nPlain TCP only: the LAN port's TLS and "
        "token (8767, issue #19) aren't in this client yet,\nso it reaches the host's localhost "
        "port 8765 or a fake host.",
        epilog=SHORTCUTS,
    )
    parser.add_argument("commands", nargs="*", metavar="COMMAND",
                        help="commands to send once connected, each after the previous answer")
    parser.add_argument("--host", default="127.0.0.1", help="host address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=PORT, help="host port (default 8765)")
    parser.add_argument("--name", default="Fake client", help="your name in hello")
    parser.add_argument("--role", choices=("vr", "blender-client"), default="vr",
                        help="role in hello (default vr). blender-client also rejoins only the "
                        "document it had, like the Client role")
    parser.add_argument("--source", choices=("ui", "voice"), default="ui",
                        help="source of commands (default ui)")
    parser.add_argument("--document", type=_document, metavar="ID:OPEN_EPOCH",
                        help="name this document in hello (the host refuses another one)")
    parser.add_argument("--reconnect", action="store_true",
                        help="after a disconnect, reconnect every 2 s")
    parser.add_argument("--exit", action="store_true",
                        help="exit after the COMMANDs: status 0 if all were applied, 1 if not")
    parser.add_argument("--check", action="store_true",
                        help="validate every message sent and received against contracts/schemas "
                        "(needs pip install jsonschema)")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every raw message")
    return parser.parse_args(argv)


def succeeded(reply):
    """For --exit: a pong, an applied result, or receipts that are all applied."""
    if reply is None:
        return False
    p = reply["payload"]
    if reply.get("type") == "receipts":
        return (bool(p["receipts"]) and not p["missing"] and not p["unknown"]
                and all(r["outcome"] == "applied" for r in p["receipts"]))
    return reply.get("type") in ("result", "pong") and p.get("outcome", "applied") == "applied"


def _stdin_lines(lines):
    for line in sys.stdin:
        lines.put(line)
    lines.put(None)


def main(argv=None):
    options = parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    client = FakeClient(options.host, options.port, options.name, options.role, options.source,
                        options.document, options.reconnect, options.verbose,
                        load_checker() if options.check else None)
    try:
        client.start()
    except OSError as e:
        client.out(f"could not connect to {options.host}:{options.port} ({e}). Is the fake host "
                   "or Blender with the add-on in Host role running?")
        return 2
    try:
        if not client.wait_connected():
            client.out("no snapshot: the host refused or closed the connection")
            return 2
        ok = True
        for text in options.commands:
            try:
                reply = client.run(text)
            except UsageError as e:
                client.out(f"! {e}")
                reply = None
            ok = ok and succeeded(reply)
        if options.exit:
            return 0 if ok else 1
        client.out("Type a command (help lists them). Ctrl-C quits.")
        lines = queue.Queue()
        threading.Thread(target=_stdin_lines, args=(lines,), daemon=True).start()
        while not client.finished:
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                client.out("stdin closed; still listening. Ctrl-C quits.")
                lines = queue.Queue()  # nothing more will come
                continue
            if line.strip().lower() in ("quit", "exit"):
                break
            try:
                client.run(line)
            except UsageError as e:
                client.out(f"! {e}")
        if client.refused:
            return 2
        return 1 if client.finished else 0  # finished: the host closed and we don't reconnect
    except KeyboardInterrupt:
        return 0
    finally:
        client.close()
        if client.check is not None:
            client.out(f"--check: {client.violations} schema violation(s)")


if __name__ == "__main__":
    sys.exit(main())

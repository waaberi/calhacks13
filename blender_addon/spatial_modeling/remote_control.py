"""One opt-in remote +10 mm X command. Pure transport; never imports bpy.

No command is replayed. An interrupted/invalid response after attempting the
command is unknown, even when a write may have completed. Callers must block
further edits until a new mirror connection and explicit user reconciliation.
"""

import re
import time
from dataclasses import dataclass, field

try:
    from . import lan, protocol
except ImportError:  # pure-Python backend tests
    import lan
    import protocol

PING_INTERVAL = 2.0
_UUID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class RemoteConfig:
    address: str
    port: int
    token: str = field(repr=False)
    version: str = "0.1.0"
    name: str = "Controlled Blender editor"
    tls: bool = True
    timeout: float = 15.0


@dataclass(frozen=True)
class MoveOutcome:
    outcome: str
    request_id: str | None = None
    code: str | None = None
    message: str = ""
    receipt: dict | None = None

    @property
    def blocked(self):
        return self.outcome == "unknown"


class _Refused(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class _Wire:
    def __init__(self, sock, on_event=None):
        self.sock = sock
        self.buffer = bytearray()
        self.next_ping = time.monotonic() + PING_INTERVAL
        self.on_event = on_event

    def send(self, msg):
        self.sock.sendall(protocol.encode(msg))

    def wait(self, predicate, timeout):
        deadline = time.monotonic() + timeout
        while True:
            while b"\n" in self.buffer:
                line, _, rest = self.buffer.partition(b"\n")
                self.buffer = bytearray(rest)
                msg = protocol.decode(line)
                if self.on_event is not None:
                    self.on_event(msg)
                if predicate(msg):
                    return msg
            if len(self.buffer) > protocol.MAX_LINE_BYTES:
                raise protocol.ProtocolError("Host frame exceeded the bounded line size")
            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError("No confirmed host reply")
            if now >= self.next_ping:
                self.send(protocol.message("ping"))
                self.next_ping = now + PING_INTERVAL
            self.sock.settimeout(min(0.2, max(0.001, deadline - now)))
            try:
                chunk = self.sock.recv(65536)
            except TimeoutError:
                continue
            if not chunk:
                raise ConnectionError("Host connection closed")
            self.buffer.extend(chunk)


def _identity(doc):
    if not isinstance(doc, dict):
        raise _Refused("invalid_target", "Reconnect to a verified host document first.")
    identity = {k: doc.get(k) for k in ("id", "open_epoch")}
    if not all(isinstance(v, str) and _UUID.fullmatch(v) for v in identity.values()):
        raise _Refused("invalid_target", "The mirrored document identity is invalid.")
    return identity


def _error(msg, fallback):
    code = msg["payload"].get("code", fallback)
    # Never copy arbitrary network/exception text, which may contain credentials.
    safe = {"permission_denied": "The host refused editing; enable its controlled test flag.",
            "wrong_document": "The host document changed. Reconnect the mirror.",
            "stale_revision": "The target changed. Refresh and explicitly retry.",
            "not_found": "The selected host object no longer exists.",
            "lease_conflict": "Another editor owns this object. Try after they finish.",
            "unsupported_version": "Host and client add-on versions must match."}
    if code not in safe:
        code = fallback
    return _Refused(code, safe.get(code, "The host refused the controlled test command."))


def move_selected(config, expected_document, target_id, generation, *, enabled=False,
                  on_event=None):
    """Send exactly one fixed movement, after fresh identity and shared-lease checks.

    Call on a worker thread: config and all target data are copied on Blender's
    main thread first. on_event is for diagnostics/tests and must not access bpy.
    """
    sock = None
    wire = None
    lease_id = None
    attempted = False
    got_receipt = False
    request_id = None
    try:
        if enabled is not True:
            raise _Refused("feature_disabled", "Controlled remote editing is off.")
        if not config.tls:
            raise _Refused("tls_required", "Controlled remote editing requires TLS.")
        expected = _identity(expected_document)
        if (not isinstance(target_id, str) or _UUID.fullmatch(target_id) is None
                or type(generation) is not int or generation < 0):
            raise _Refused("invalid_target", "Select a current host object first.")
        if not (isinstance(config.address, str) and config.address.strip()
                and type(config.port) is int and 1 <= config.port <= 65535
                and 0 < config.timeout <= 120):
            raise _Refused("invalid_connection", "Check the host connection settings.")
        sock = lan.connect(config.address, config.token, port=config.port, tls=True,
                           timeout=min(config.timeout, 5.0))
        wire = _Wire(sock, on_event)
        greeting = protocol.message("hello", {"role": "blender-client", "name": config.name,
            "app": {"name": "spatial_modeling", "version": config.version},
            "document": expected})
        wire.send(greeting)
        answer = wire.wait(lambda m: m.get("re") == greeting["id"], config.timeout)
        if answer["type"] == "error":
            raise _error(answer, "join_refused")
        if answer["type"] != "welcome":
            raise _Refused("invalid_reply", "The host did not confirm this connection.")
        w = answer["payload"]
        if w.get("can_edit") is not True:
            raise _Refused("permission_denied", "The host's controlled remote test flag is off.")
        if _identity(w.get("document")) != expected:
            raise _Refused("wrong_document", "The host document changed. Reconnect the mirror.")
        snapshot = wire.wait(lambda m: m["type"] == "scene.snapshot", config.timeout)["payload"]
        if _identity(snapshot.get("document")) != expected:
            raise _Refused("wrong_document", "The fresh scene belongs to another document.")
        target = next((o for o in snapshot.get("objects", []) if o.get("id") == target_id), None)
        if target is None:
            raise _Refused("not_found", "The selected host object no longer exists.")
        if target.get("generation") != generation:
            raise _Refused("stale_revision", "The target changed. Refresh and explicitly retry.")
        fields = {k: w[k] for k in ("session_id", "host_epoch", "actor_id")}
        fields.update(document_id=expected["id"], open_epoch=expected["open_epoch"])
        acquire = protocol.message("lease.acquire", {**fields, "mode": "shared",
                                                       "targets": [target_id]})
        wire.send(acquire)
        granted = wire.wait(lambda m: m.get("re") == acquire["id"], config.timeout)
        if granted["type"] == "error":
            raise _error(granted, "lease_refused")
        if granted["type"] != "lease.granted":
            raise _Refused("invalid_reply", "The host did not grant editing permission.")
        lease = granted["payload"]["lease"]
        lease_id = lease["lease_id"]
        if (lease.get("owner", {}).get("actor_id") != w["actor_id"]
                or lease.get("mode") != "shared" or target_id not in lease.get("targets", [])):
            raise _Refused("invalid_reply", "The host lease did not cover the selected object.")
        command = protocol.message("command", {**fields,
            "base_revision": snapshot["document"]["revision"], "source": "ui",
            "op": "object.move", "args": {"by": [0.01, 0, 0]}, "lease": lease_id,
            "target": {"id": target_id, "generation": generation}})
        request_id = command["id"]
        attempted = True  # even a partial send can have reached the host; never replay it
        wire.send(command)
        result = wire.wait(lambda m: m.get("re") == request_id, config.timeout)
        receipt = result["payload"]
        if (result["type"] != "result" or receipt.get("request_id") != request_id
                or receipt.get("op") != "object.move" or receipt.get("target") != target_id
                or receipt.get("actor", {}).get("actor_id") != w["actor_id"]
                or receipt.get("outcome") not in ("applied", "rejected", "unknown")):
            raise protocol.ProtocolError("No valid native receipt")
        got_receipt = True
        outcome = receipt["outcome"]
        code = receipt.get("error", {}).get("code")
        message = {"applied": "Host confirmed: moved selected object 10 mm along X.",
                   "rejected": "Host rejected the move. Verify the target before retrying.",
                   "unknown": "Outcome unknown. Reconnect and verify the native scene before retrying."}
        return MoveOutcome(outcome, request_id, code, message[outcome], receipt)
    except _Refused as exc:
        return MoveOutcome("rejected", request_id, exc.code, str(exc))
    except Exception:  # noqa: BLE001 - never lose a pending command or expose connection secrets
        if attempted:
            return MoveOutcome("unknown", request_id, "outcome_unknown",
                               "Outcome unknown. Reconnect and verify the native scene before retrying.")
        return MoveOutcome("rejected", request_id, "connection_failed",
                           "Connection could not be verified. Check settings and reconnect.")
    finally:
        if wire is not None and lease_id is not None and (got_receipt or not attempted):
            try:
                wire.send(protocol.message("lease.release", {"lease_id": lease_id}))
            except OSError:
                pass  # closing also releases; the host defers release during a native commit
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

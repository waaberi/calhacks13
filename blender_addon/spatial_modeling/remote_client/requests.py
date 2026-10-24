"""Client-role edit requests and their state (P5-M1-2/3). No Blender or network calls.

Every edit is a request to the host: nothing changes in the local mirror until the
host's scene.update arrives, so a returned scene is never sent back as a new edit.
Requests follow contracts/README.md › Commands, Outcomes and Reconnecting:

- one request in flight at a time, built from the welcome and the current scene;
- a connection lost before the result makes the request "asking": after the next
  welcome the client sends one receipt.query per host_epoch and never resends;
- an outcome that stays unknown blocks further edits until the user has checked
  the fresh scene and says so.

Host text (summaries, error messages) is not shown: labels are built locally and
errors are shown by code only, like the read-only mirror's diagnostics.
"""

import re
import uuid
from dataclasses import dataclass

_ID = re.compile("[0-9a-f]{32}")
MAX_QUERY = 100  # request IDs per receipt.query (contract)
MAX_KEPT = 50  # finished requests kept for the status list

PENDING = "pending"  # sent, waiting for its result on this connection
ASKING = "asking"  # connection lost before the result; ask after reconnecting
APPLIED = "applied"
REJECTED = "rejected"
MISSING = "missing"  # the host never got it: nothing changed
UNKNOWN = "unknown"  # can't tell; the fresh scene is the truth
CHECKED = "checked"  # unknown, and the user has checked the fresh scene
DROPPED = "dropped"  # belonged to a document that is no longer open

# A command that never reached its handler gets an `error` reply instead of a result.
# internal_error may have happened halfway; the others changed nothing.
_NOT_APPLIED = {"invalid_message", "unknown_type", "busy", "permission_denied",
                "wrong_session", "wrong_document", "unsupported_version", "duplicate_request"}
_ERROR_CODE = re.compile(r"[a-z_]{1,40}")

OUTCOME_TEXT = {
    PENDING: "waiting for the host",
    ASKING: "connection lost — asking the host",
    APPLIED: "applied",
    REJECTED: "rejected",
    MISSING: "not applied (host never got it)",
    UNKNOWN: "UNKNOWN — check the host scene",
    CHECKED: "unknown, checked by you",
    DROPPED: "dropped (host opened another file)",
}


class EditBlocked(Exception):
    """Why a new edit can't be sent right now; safe to show the user."""


@dataclass
class Request:
    request_id: str
    op: str
    label: str
    host_epoch: str
    document: tuple
    state: str = PENDING
    code: str = ""  # error code when rejected/unknown
    revision: int = None


class RequestTracker:
    def __init__(self):
        self.requests = {}  # request_id -> Request, oldest first
        self.welcome = None
        self.queries = {}  # receipt.query message id -> [request_id, ...]

    # Connection lifecycle.

    def welcomed(self, welcome):
        """A new welcome. Returns receipt.query payloads to send for outstanding requests."""
        for key in ("session_id", "host_epoch", "actor_id"):
            if not isinstance(welcome.get(key), str) or not _ID.fullmatch(welcome[key]):
                raise ValueError("Invalid welcome identity")
        document = welcome["document"]
        current = (document["id"], document["open_epoch"])
        self.welcome = welcome
        self.queries.clear()
        for request in self.requests.values():
            if request.state in (PENDING, ASKING, UNKNOWN) and request.document != current:
                # Contract: drop everything held for the old document.
                request.state = DROPPED
            elif request.state == PENDING:
                request.state = ASKING  # sent on the old connection, result never came
        by_epoch = {}
        for request in self.requests.values():
            if request.state == ASKING:
                by_epoch.setdefault(request.host_epoch, []).append(request.request_id)
        payloads = []
        for epoch, ids in by_epoch.items():
            for start in range(0, len(ids), MAX_QUERY):
                payloads.append({"host_epoch": epoch, "request_ids": ids[start:start + MAX_QUERY]})
        return payloads

    def query_sent(self, message_id, payload):
        self.queries[message_id] = list(payload["request_ids"])

    def disconnected(self):
        """The connection closed or stopped answering; results can no longer arrive."""
        self.welcome = None
        self.queries.clear()
        for request in self.requests.values():
            if request.state == PENDING:
                request.state = ASKING

    # Building requests.

    def blocked(self, scene_current, can_edit, healthy):
        """None when a new edit may be sent, otherwise the reason."""
        if self.welcome is None or not healthy:
            return "Not connected to the host"
        if not scene_current:
            return "Waiting for a fresh host scene"
        if not can_edit:
            return "The host doesn't allow Client edits (host: Let the Client role edit)"
        states = {r.state for r in self.requests.values()}
        if PENDING in states:
            return "Waiting for the host to answer the last edit"
        if ASKING in states:
            return "Asking the host what happened to an edit sent before the connection dropped"
        if UNKNOWN in states:
            return "An edit's outcome is unknown: check the host scene, then confirm"
        return None

    def build(self, op, label, document, args=None, target=None):
        """A command message for op; raises EditBlocked. target is a scene object record."""
        welcome = self.welcome
        if welcome is None:
            raise EditBlocked("Not connected to the host")
        if (document["id"], document["open_epoch"]) != (welcome["document"]["id"],
                                                        welcome["document"]["open_epoch"]):
            raise EditBlocked("The scene belongs to another document; wait for a fresh scene")
        request_id = uuid.uuid4().hex
        payload = {
            "session_id": welcome["session_id"],
            "host_epoch": welcome["host_epoch"],
            "document_id": document["id"],
            "open_epoch": document["open_epoch"],
            "actor_id": welcome["actor_id"],
            "base_revision": document["revision"],
            "source": "ui",
            "op": op,
            "args": args or {},
        }
        if target is not None:
            payload["target"] = {"id": target["id"], "generation": target["generation"]}
        self.requests[request_id] = Request(request_id, op, label, welcome["host_epoch"],
                                            (document["id"], document["open_epoch"]))
        self._trim()
        return {"v": 1, "type": "command", "id": request_id, "payload": payload}

    def acknowledge_unknown(self):
        """The user checked the fresh host scene; unknown outcomes stop blocking edits."""
        for request in self.requests.values():
            if request.state == UNKNOWN:
                request.state = CHECKED

    # Answers from the host.

    def on_result(self, payload):
        request = self.requests.get(payload.get("request_id"))
        if request is None:
            return
        outcome = payload.get("outcome")
        if outcome not in (APPLIED, REJECTED, UNKNOWN):
            outcome = UNKNOWN
        self._finish(request, outcome, payload)

    def on_reply_error(self, reply_to, code):
        """An `error` answering one of our messages (command or receipt.query)."""
        code = code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else "invalid_message"
        if reply_to in self.queries:
            # The query itself failed: we still can't tell what happened.
            for request_id in self.queries.pop(reply_to):
                request = self.requests.get(request_id)
                if request is not None and request.state == ASKING:
                    request.state, request.code = UNKNOWN, code
            return
        request = self.requests.get(reply_to)
        if request is None or request.state not in (PENDING, ASKING):
            return
        request.code = code
        request.state = REJECTED if code in _NOT_APPLIED else UNKNOWN

    def on_receipts(self, reply_to, payload):
        asked = set(self.queries.pop(reply_to, []))
        for receipt in payload.get("receipts", []):
            request = self.requests.get(receipt.get("request_id"))
            if request is None or request.state not in (PENDING, ASKING):
                continue
            outcome = receipt.get("outcome")
            if outcome == "pending":
                request.state = PENDING  # still running on the host; its result follows
            else:
                self._finish(request, outcome if outcome in (APPLIED, REJECTED) else UNKNOWN,
                             receipt)
            asked.discard(request.request_id)
        for request_id in payload.get("missing", []):
            request = self.requests.get(request_id)
            if request is not None and request.state == ASKING:
                request.state = MISSING
            asked.discard(request_id)
        for request_id in list(payload.get("unknown", [])) + sorted(asked):
            request = self.requests.get(request_id)
            if request is not None and request.state == ASKING:
                request.state = UNKNOWN

    # Status for the UI.

    def lines(self, count=8):
        """(label, state text, icon) for the newest requests, newest first."""
        out = []
        for request in list(self.requests.values())[-count:][::-1]:
            text = OUTCOME_TEXT[request.state]
            if request.code:
                text += f" ({request.code})"
            icon = {APPLIED: "CHECKMARK", REJECTED: "CANCEL", PENDING: "TIME", ASKING: "TIME",
                    UNKNOWN: "ERROR"}.get(request.state, "INFO")
            out.append((request.label, text, icon))
        return out

    def _finish(self, request, outcome, receipt):
        request.state = outcome
        revision = receipt.get("revision")
        request.revision = revision if type(revision) is int else None
        error = receipt.get("error")
        if isinstance(error, dict) and isinstance(error.get("code"), str) \
                and _ERROR_CODE.fullmatch(error["code"]):
            request.code = error["code"]

    def _trim(self):
        done = [rid for rid, r in self.requests.items()
                if r.state not in (PENDING, ASKING, UNKNOWN)]
        for request_id in done[:max(0, len(self.requests) - MAX_KEPT)]:
            del self.requests[request_id]

"""The hosting session: the hello -> welcome handshake and who is connected.

Implements "Connecting" in contracts/README.md. A Session lives as long as the
host's servers, so host_epoch is new for each. It runs on Blender's main thread
inside Server.drain(). This module must not import bpy: host.py passes in the
document and scene snapshot as functions, so the tests can run it outside Blender.
"""

import logging
import re
import tomllib
import uuid
from collections import ChainMap
from pathlib import Path

try:
    from . import protocol, server
except ImportError:  # imported directly by the tests, outside Blender
    import protocol
    import server


def _manifest_version():
    with open(Path(__file__).with_name("blender_manifest.toml"), "rb") as f:
        return tomllib.load(f)["version"]


APP = {"name": "spatial_modeling", "version": _manifest_version()}
HOST_NAME = "Host Blender"  # the host's own participant, unless the host entered "Your name"
ROLES = ("vr", "blender-client")
_UUID = re.compile(r"[0-9a-f]{32}")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?")

log = logging.getLogger(__name__)


def is_uuid(value):
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def _is_name(value):
    return isinstance(value, str) and 1 <= len(value) <= 256


def host_name(name):
    """The host participant's name: the "Your name" preference, or HOST_NAME if it's blank."""
    name = (name or "").strip()[:256].strip()
    return name or HOST_NAME


def _hello_problem(msg):
    """Why msg doesn't match hello.schema.json, or None. Blender has no jsonschema."""
    payload = msg["payload"]
    if not is_uuid(msg["id"]):
        return "id must be 32 lowercase hex digits"
    extra = set(payload) - {"role", "name", "app", "document", "token"}  # server.py strips token
    if extra:
        return f"unknown field {min(extra)!r}"
    if payload.get("role") not in ROLES:
        return "role must be 'vr' or 'blender-client'"
    if not _is_name(payload.get("name")):
        return "name must be 1 to 256 characters"
    app = payload.get("app")
    if not (
        isinstance(app, dict)
        and set(app) == {"name", "version"}
        and _is_name(app["name"])
        and isinstance(app["version"], str)
        and _VERSION.fullmatch(app["version"])
    ):
        return "app must be {name, version} with a version like 1.2.3"
    if "document" in payload:
        doc = payload["document"]
        if not (isinstance(doc, dict) and set(doc) == {"id", "open_epoch"}
                and all(is_uuid(v) for v in doc.values())):
            return "document must be {id, open_epoch}, each 32 lowercase hex digits"
    return None


class Session:
    """Participants and the handshake, on every listener of the attached server.

    document() returns the open document as welcome carries it (`document` in
    envelope.schema.json); snapshot(document) returns a scene.snapshot payload;
    on_change() runs after someone joins or leaves. All run on the main thread.
    The token never reaches this module: server.py checks it and strips it from
    hello first.

    name: the host desktop user's name for its participant (see host_name()).
    client_can_edit: the add-on preference that lets Client-role connections send
    commands (P3A-W-3, off by default). welcome's can_edit and conn.can_edit
    follow it; the Unity app can always edit.
    """

    def __init__(self, document, snapshot, session_id, on_change=None, name=None,
                 client_can_edit=False):
        self.document = document
        self.snapshot = snapshot
        self.session_id = session_id
        self.host_epoch = uuid.uuid4().hex
        self.host = {"actor_id": uuid.uuid4().hex, "name": host_name(name), "role": "host"}
        self.client_can_edit = client_can_edit
        self.participants = {}  # joined Connection -> actor, in joining order
        self.on_change = on_change
        self._server = None

    def attach(self, srv):
        """Serve this session on srv: hello, and leaving when a connection closes. Returns srv.

        Each listener admits the hello roles in its `roles`.
        """
        srv.handlers = ChainMap({"hello": self.hello}, srv.handlers)
        srv.on_disconnect = self.left
        self._server = srv
        return srv

    def hello(self, msg, conn):
        """Welcome the connection, or refuse it and close (see Connecting, step 3)."""
        problem = _hello_problem(msg)
        if problem:
            return server.error("invalid_message", f"bad hello: {problem}", msg["id"])
        if conn.joined:
            return server.error("invalid_message", "this connection is already welcomed", msg["id"])
        payload = msg["payload"]
        role = payload["role"]
        if role not in conn.listener.roles:
            text = f"This port doesn't admit {role} clients."
            return self._refuse(conn, msg, "permission_denied", text)
        version = payload["app"]["version"]
        if role == "blender-client" and version != APP["version"]:
            text = (f"The host runs Spatial Modeling {APP['version']} and you run {version}. "
                    "Install the same version on both computers.")
            return self._refuse(conn, msg, "unsupported_version", text)
        doc = self.document()
        expected = payload.get("document")
        if expected is not None and expected != {k: doc[k] for k in ("id", "open_epoch")}:
            name = doc["name"] or "an unsaved file"
            if expected["id"] == doc["id"]:
                text = f"The host reopened {name} since you last synced. Rejoin to get a fresh copy."
            else:
                text = f"The host has {name} open, not your document."
            current = {k: doc[k] for k in ("id", "open_epoch", "name")}
            return self._refuse(conn, msg, "wrong_document", text, {"document": current})

        actor = {"actor_id": uuid.uuid4().hex, "name": payload["name"], "role": role}
        can_edit = role == "vr" or self.client_can_edit  # the Client role only behind the flag
        welcome = protocol.message("welcome", {
            "session_id": self.session_id,
            "host_epoch": self.host_epoch,
            "actor_id": actor["actor_id"],
            "can_edit": can_edit,
            "app": APP,
            "document": doc,
        }, re=msg["id"])
        conn.send(welcome, protocol.message("scene.snapshot", self.snapshot(doc)))
        conn.joined = True
        conn.can_edit = can_edit
        self.participants[conn] = actor
        self._changed()
        return None

    def left(self, conn):
        """A connection closed. If it had joined, tell everyone else."""
        if self.participants.pop(conn, None) is not None:
            self._changed()

    def rename_host(self, name):
        """Set the host participant's name; everyone gets session.update if it changed."""
        name = host_name(name)
        if name != self.host["name"]:
            self.host = {**self.host, "name": name}
            self._changed()

    def session_update(self):
        return protocol.message("session.update", {
            "participants": [self.host, *self.participants.values()],
            "leases": [],  # P3B
        })

    def broadcast(self, msg, exclude=None):
        """Send msg to every participant except `exclude`, on every listener."""
        if self._server is not None:
            self._server.broadcast(msg, exclude)

    def _changed(self):
        self.broadcast(self.session_update())
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:  # a display problem must not fail the hello that caused it
                log.exception("on_change failed")

    @staticmethod
    def _refuse(conn, msg, code, text, details=None):
        conn.send(server.error(code, text, msg["id"], details))
        conn.close()

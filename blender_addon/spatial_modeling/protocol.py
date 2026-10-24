"""Wire format shared by the host and every client: one JSON object per line.

See contracts/README.md. This module must not import bpy, so it stays testable
outside Blender.
"""

import json
import uuid

VERSION = 1
MAX_LINE_BYTES = 16 * 1024 * 1024


class ProtocolError(ValueError):
    """A message that must be rejected; reply with an `error` message."""


def message(type_, payload=None, re=None):
    msg = {"v": VERSION, "type": type_, "id": uuid.uuid4().hex, "payload": payload or {}}
    if re is not None:
        msg["re"] = re
    return msg


def encode(msg):
    line = json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    if len(line) > MAX_LINE_BYTES:
        raise ProtocolError(f"message is {len(line)} bytes; the limit is {MAX_LINE_BYTES}")
    return line


def decode(line):
    if len(line) > MAX_LINE_BYTES:
        raise ProtocolError(f"line is {len(line)} bytes; the limit is {MAX_LINE_BYTES}")
    try:
        msg = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ProtocolError(f"not valid JSON: {e}") from e
    if not isinstance(msg, dict):
        raise ProtocolError("message must be a JSON object")
    if msg.get("v") != VERSION:
        raise ProtocolError(f"unsupported contract version {msg.get('v')!r}; expected {VERSION}")
    for field, kind in (("type", str), ("id", str), ("payload", dict)):
        if not isinstance(msg.get(field), kind):
            raise ProtocolError(f"field {field!r} must be a {kind.__name__}")
    if "re" in msg and not isinstance(msg["re"], str):
        raise ProtocolError("field 're' must be a str")
    return msg

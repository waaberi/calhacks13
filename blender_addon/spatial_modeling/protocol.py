"""Wire format shared by the host and every client: one JSON object per line.

See contracts/README.md. This module must not import bpy, so it stays testable
outside Blender.
"""

import json
import math
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
    try:
        text = json.dumps(msg, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except ValueError as e:  # NaN or Infinity: receivers would reject it
        raise ProtocolError(f"message is not valid JSON: {e}") from e
    line = text.encode("utf-8") + b"\n"
    if len(line) > MAX_LINE_BYTES:
        raise ProtocolError(f"message is {len(line)} bytes; the limit is {MAX_LINE_BYTES}")
    return line


def _reject_constant(name):
    raise ProtocolError(f"not valid JSON: {name} is not a number")


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):  # for example 1e999
        raise ProtocolError(f"not valid JSON: {text} is out of range")
    return value


def decode(line):
    if len(line) > MAX_LINE_BYTES:
        raise ProtocolError(f"line is {len(line)} bytes; the limit is {MAX_LINE_BYTES}")
    try:
        msg = json.loads(line, parse_constant=_reject_constant, parse_float=_finite_float)
    except ProtocolError:
        raise
    except (ValueError, RecursionError) as e:  # bad JSON or UTF-8, a 5000-digit integer
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

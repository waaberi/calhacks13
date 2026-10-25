#!/usr/bin/env python3
"""Fake Host-role add-on: serves the host connection with made-up scene data.

TEST DATA ONLY. Nothing here comes from Blender, so nothing seen through this fake
counts as acceptance evidence (PHASE_PLAN.md: "Fake means test data only"). The
document is called fake_bracket.blend and the host participant "Fake host (test
data)", so screenshots show where their data came from.

    python3 contracts/fakes/fake_host.py          # listens on 127.0.0.1:8765
    python3 contracts/fakes/fake_host.py --help   # flags for live updates and failures

It follows contracts/README.md: hello gets welcome, scene.snapshot and
session.update; ping gets pong; a command gets scene.update to every client, then
result to the sender and activity to the others. The scene is the one from
contracts/examples (same IDs): a 100 x 60 x 10 mm base plate, a 20 mm x 40 mm
shaft standing on it, a camera and a dimensioned sketch, with real meshes.

Commands: object.add, object.move, object.rotate, object.scale, object.delete,
history.undo, history.redo and document.save. Sketch ops are rejected with
`failed`. Leases follow "Leases and presence" with the real host's rules and
messages: lease.acquire, lease.granted, lease.release, conflicts, a command's own
lease, Undo/Redo refused while someone else holds one, and leases ending when
their owner disconnects. Linked data here is an object's descendants (Base
plate's lease covers Shaft) and objects sharing its mesh; the real host also
adds objects whose modifiers or constraints use it.

Voice: voice.resolve gets canned voice.candidates (run, ask or reject; see
voice_answer()), voice.run runs one of them once, and voice.grammar_query gets the
real host's phrase list from contracts/examples/voice.grammar.json.

Standard library only and Python 3.9 or newer, so it runs on a Mac without
Blender. The framing repeats blender_addon/spatial_modeling/protocol.py so this
file runs on its own; tests/backend/test_fakes.py checks that they agree.
"""

import argparse
import asyncio
import itertools
import json
import math
import re
import sys
import time
import traceback
import uuid
from pathlib import Path

VERSION = 1
MAX_LINE_BYTES = 16 * 1024 * 1024
HOST = "127.0.0.1"  # like the real host, never reachable from the LAN
PORT = 8765
MAX_WRITE_BUFFER = 4 * MAX_LINE_BYTES  # unread data before we drop a client
MAX_UNDO = 100
ANIMATE_INTERVAL = 0.25  # seconds between scene.updates with --animate
ANIMATE_DEGREES_PER_SECOND = 20.0

APP = {"name": "spatial_modeling-fake-host", "version": "0.1.0"}
DOCUMENT_NAME = "fake_bracket.blend"
UNITS = {
    "system": "METRIC",
    "length_unit": "MILLIMETERS",
    "rotation_unit": "DEGREES",
    "scale_length": 0.001,
}
# IDs from contracts/examples, so the fake tells the same story. host_epoch and
# open_epoch are new on every run, as the contract requires.
SESSION_ID = "2f05d1eb3f1e4ce98dd998abf20cdd33"
DOCUMENT_ID = "15e12b8b8c12437098bb8a090659c8cb"
BASE_PLATE_ID = "f21f7d20394f4c02afce7ab1e6f4a1a8"
SHAFT_ID = "fd7bd4ddae444528a4fedbc562fe018b"
CAMERA_ID = "c498249e5a674e29bc24b0e23246406a"
SKETCH_ID = "420d772974c747ebb91283b7ff8d22a3"
HOST_ACTOR = {
    "actor_id": "4f8ee9f286eb4403813e6398e796d696",
    "name": "Fake host (test data)",
    "role": "host",
}

OBJECT_OPS = ("object.add", "object.move", "object.rotate", "object.scale", "object.delete")
SUPPORTED_OPS = OBJECT_OPS + ("history.undo", "history.redo", "document.save", "voice.run")
SKETCH_OPS = (
    "sketch.create",
    "sketch.add_line",
    "sketch.add_rectangle",
    "sketch.add_circle",
    "sketch.constrain",
    "sketch.set_dimension",
)
# The fake knows this contract but has no native toolbar/base mesh to apply it.
CONTRACT_OPS = SUPPORTED_OPS + SKETCH_OPS + ("object.spatial_edit",)
UNTARGETED_OPS = ("object.add", "history.undo", "history.redo", "document.save", "sketch.create")
NO_ARGS_OPS = ("object.delete", "history.undo", "history.redo", "document.save")
OPTIONAL_TARGET_OPS = ("voice.run",)
VOICE_EXPIRES_IN = 30  # seconds a voice.candidates resolution can be run
REQUEST_FIELDS = ("session_id", "host_epoch", "document_id", "open_epoch", "actor_id")
PRIMITIVES = {"cube": "Cube", "sphere": "Sphere", "cylinder": "Cylinder"}

# Bounds from contracts/schemas/envelope.schema.json and command.schema.json.
COORDINATE = (-1000.0, 1000.0)
LENGTH = (0.000001, 1000.0)
FACTOR = (0.001, 1000.0)
ANGLE = (-6.283186, 6.283186)
QUATERNION = (-1.000001, 1.000001)

UUID = re.compile(r"[0-9a-f]{32}")
TYPE = re.compile(r"[a-z]+(\.[a-z_]+)?")
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?")


# Framing: one UTF-8 JSON object per line, as in protocol.py.


def new_id():
    return uuid.uuid4().hex


def message(type_, payload=None, re=None):
    msg = {"v": VERSION, "type": type_, "id": new_id(), "payload": payload or {}}
    if re is not None:
        msg["re"] = re
    return msg


def error(code, text, re=None, details=None):
    payload = {"code": code, "message": text[:1024]}
    if details:
        payload["details"] = details
    return message("error", payload, re)


def encode(msg):
    text = json.dumps(msg, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return text.encode("utf-8") + b"\n"


class WireError(ValueError):
    """A line that can't be accepted: reply `error` with this code, then maybe close."""

    def __init__(self, code, text, re=None, close=False):
        super().__init__(text)
        self.code = code
        self.re = re
        self.close = close


def _no_constants(name):
    raise ValueError(f"{name} is not JSON")


def is_uuid(value):
    return isinstance(value, str) and UUID.fullmatch(value) is not None


def _readable_id(line):
    """The id of a line that isn't strict JSON (NaN, say), for the error's `re`."""
    try:
        raw = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return raw["id"] if isinstance(raw, dict) and is_uuid(raw.get("id")) else None


def decode(line):
    """Parse one line and check the envelope, more strictly than protocol.decode."""
    try:
        msg = json.loads(line, parse_constant=_no_constants)
    except (ValueError, RecursionError) as e:  # includes JSONDecodeError and UnicodeDecodeError
        raise WireError("invalid_message", f"not valid JSON: {e}", _readable_id(line)) from None
    if not isinstance(msg, dict):
        raise WireError("invalid_message", "a message must be a JSON object")
    re_ = msg["id"] if is_uuid(msg.get("id")) else None
    v = msg.get("v")
    if isinstance(v, bool) or v != VERSION:
        raise WireError(
            "unsupported_version", f"contract version {v!r} isn't supported; use v={VERSION}",
            re_, close=True,
        )
    unknown = sorted(set(msg) - {"v", "type", "id", "re", "payload"})
    if unknown:
        raise WireError("invalid_message", f"unknown envelope field(s): {', '.join(unknown)}", re_)
    if not isinstance(msg.get("type"), str) or TYPE.fullmatch(msg["type"]) is None:
        raise WireError("invalid_message", "type must be a message type such as 'ping'", re_)
    if re_ is None:
        raise WireError(
            "invalid_message",
            "id must be 32 lowercase hex digits (Python uuid4().hex, C# Guid.ToString(\"N\"))",
        )
    if "re" in msg and not is_uuid(msg["re"]):
        raise WireError("invalid_message", "re must be 32 lowercase hex digits; leave it out "
                        "instead of sending null", re_)
    if not isinstance(msg.get("payload"), dict):
        raise WireError("invalid_message", "payload must be an object", re_)
    return msg


# Payload checks. They follow contracts/schemas for every message the fake
# handles; sketch op arguments aren't checked because sketch ops are refused.


class Invalid(ValueError):
    """A payload that doesn't match its schema: reply `error` invalid_message."""


def _fields(obj, where, required, optional=()):
    if not isinstance(obj, dict):
        raise Invalid(f"{where} must be an object")
    missing = [k for k in required if k not in obj]
    if missing:
        raise Invalid(f"{where} is missing {', '.join(missing)}")
    unknown = sorted(set(obj) - set(required) - set(optional))
    if unknown:
        raise Invalid(f"{where} has unknown field(s) {', '.join(unknown)}")
    return obj


def _uuid(value, where):
    if not is_uuid(value):
        raise Invalid(f"{where} must be 32 lowercase hex digits")
    return value


def _integer(value, where):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2**53 - 1:
        raise Invalid(f"{where} must be a whole number, 0 or more")
    return value


def _number(value, where, bounds):
    low, high = bounds
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not ok or not math.isfinite(value) or not low <= value <= high:
        raise Invalid(f"{where} must be a number from {low:g} to {high:g}")
    return float(value)


def _numbers(value, where, count, bounds):
    if not isinstance(value, list) or len(value) != count:
        raise Invalid(f"{where} must be a list of {count} numbers")
    return [_number(v, f"{where}[{i}]", bounds) for i, v in enumerate(value)]


def _text(value, where, longest=256):
    if not isinstance(value, str) or not 1 <= len(value) <= longest:
        raise Invalid(f"{where} must be a string of 1 to {longest} characters")
    return value


def _by_or_to(args):
    if len(args) != 1 or not ("by" in args or "to" in args):
        raise Invalid("args must have exactly one of by or to")
    return "by" if "by" in args else "to"


def _check_add(args):
    _fields(args, "args", ("primitive", "location", "dimensions"))
    if args["primitive"] not in tuple(PRIMITIVES):  # a tuple, so a list value is no TypeError
        raise Invalid("args.primitive must be cube, sphere or cylinder")
    _numbers(args["location"], "args.location", 3, COORDINATE)
    _numbers(args["dimensions"], "args.dimensions", 3, LENGTH)


def _check_move(args):
    key = _by_or_to(args)
    _numbers(args[key], f"args.{key}", 3, COORDINATE)


def _check_rotate(args):
    if _by_or_to(args) == "to":
        _numbers(args["to"], "args.to", 4, QUATERNION)
        return
    by = _fields(args["by"], "args.by", ("axis", "angle"))
    if by["axis"] not in ("X", "Y", "Z"):
        raise Invalid("args.by.axis must be X, Y or Z")
    _number(by["angle"], "args.by.angle (radians)", ANGLE)


def _check_scale(args):
    key = _by_or_to(args)
    _numbers(args[key], f"args.{key}", 3, FACTOR)


def _check_no_args(args):
    if args:
        raise Invalid("args must be {} for this op")


def _check_voice_run(args):
    _fields(args, "args", ("resolution", "choice"))
    _uuid(args["resolution"], "args.resolution")
    choice = args["choice"]
    whole = isinstance(choice, int) or (isinstance(choice, float) and choice.is_integer())
    if isinstance(choice, bool) or not whole or not 1 <= choice <= 3:
        raise Invalid("args.choice must be 1, 2 or 3")


ARGS_CHECKS = {
    "object.add": _check_add,
    "object.move": _check_move,
    "object.rotate": _check_rotate,
    "object.scale": _check_scale,
    "voice.run": _check_voice_run,
}
for _op in NO_ARGS_OPS:
    ARGS_CHECKS[_op] = _check_no_args


def check_command(p):
    _fields(p, "command payload", REQUEST_FIELDS + ("base_revision", "source", "op", "args"),
            ("target", "lease"))
    for field in REQUEST_FIELDS:
        _uuid(p[field], field)
    _integer(p["base_revision"], "base_revision")
    if p["source"] not in ("ui", "voice"):
        raise Invalid("source must be ui or voice")
    if "lease" in p:
        _uuid(p["lease"], "lease")
    op = p["op"]
    if op not in CONTRACT_OPS:
        raise Invalid(f"unknown op {op!r}")
    if op in UNTARGETED_OPS:
        if "target" in p:
            raise Invalid(f"{op} takes no target")
    elif "target" not in p:
        if op not in OPTIONAL_TARGET_OPS:
            raise Invalid(f"{op} needs a target {{id, generation}}")
    else:
        target = _fields(p["target"], "target", ("id", "generation"))
        _uuid(target["id"], "target.id")
        _integer(target["generation"], "target.generation")
    if not isinstance(p["args"], dict):
        raise Invalid("args must be an object")
    check = ARGS_CHECKS.get(op)
    if check is not None:
        check(p["args"])


def check_hello(p):
    # token: the LAN port's session token. Checked like the schema, then ignored, as the host
    # ignores it on its other ports.
    _fields(p, "hello payload", ("role", "name", "app"), ("document", "token"))
    if p["role"] not in ("vr", "blender-client"):
        raise Invalid("role must be vr or blender-client")
    _text(p["name"], "name")
    app = _fields(p["app"], "app", ("name", "version"))
    _text(app["name"], "app.name")
    if not isinstance(app["version"], str) or SEMVER.fullmatch(app["version"]) is None:
        raise Invalid("app.version must look like 1.2.3")
    if "document" in p:
        document = _fields(p["document"], "document", ("id", "open_epoch"))
        _uuid(document["id"], "document.id")
        _uuid(document["open_epoch"], "document.open_epoch")
    if "token" in p:
        _text(p["token"], "token", 256)
        if len(p["token"]) < 16:
            raise Invalid("token must be at least 16 characters")


def check_lease_acquire(p):
    _fields(p, "lease.acquire payload", REQUEST_FIELDS + ("mode", "targets"))
    for field in REQUEST_FIELDS:
        _uuid(p[field], field)
    mode, targets = p["mode"], p["targets"]
    if mode not in ("exclusive", "shared"):
        raise Invalid("mode must be exclusive or shared")
    if not isinstance(targets, list) or len(targets) > 64:
        raise Invalid("targets must list at most 64 IDs")
    for i, value in enumerate(targets):
        _uuid(value, f"targets[{i}]")
    if len(set(targets)) != len(targets):
        raise Invalid("targets must not repeat")
    if mode == "exclusive" and targets:
        raise Invalid("an exclusive lease covers the whole document: targets must be []")
    if mode == "shared" and not targets:
        raise Invalid("a shared lease needs at least one target")


def check_lease_release(p):
    _fields(p, "lease.release payload", ("lease_id",))
    _uuid(p["lease_id"], "lease_id")


def check_receipt_query(p):
    _fields(p, "receipt.query payload", ("host_epoch", "request_ids"))
    _uuid(p["host_epoch"], "host_epoch")
    ids = p["request_ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100:
        raise Invalid("request_ids must be a list of 1 to 100 IDs")
    for i, value in enumerate(ids):
        _uuid(value, f"request_ids[{i}]")
    if len(set(ids)) != len(ids):
        raise Invalid("request_ids must not repeat")


def check_voice_resolve(p):
    _fields(p, "voice.resolve payload", ("text", "confidence"), ("target",))
    _text(p["text"], "text", 500)
    _number(p["confidence"], "confidence", (0.0, 1.0))
    if "target" in p:
        target = _fields(p["target"], "target", ("id", "generation"))
        _uuid(target["id"], "target.id")
        _integer(target["generation"], "target.generation")


# Voice: canned answers, so the Unity app can build the voice.candidates flow without
# Blender. The real host matches about 40 operations (blender_addon/.../voice_ops.py).

def _voice_candidate(say, operator, properties, set_, needs_target):
    return {"say": say, "operator": operator, "properties": properties, "set": set_,
            "needs_target": needs_target}


VOICE_MONKEY = _voice_candidate("Add a monkey", "mesh.primitive_monkey_add", {}, {}, False)
VOICE_ARRAY = _voice_candidate("Array, 5 copies along Z", "object.modifier_add",
                               {"type": "ARRAY"},
                               {"count": 5, "relative_offset_displace": [0.0, 0.0, 1.0]}, True)
VOICE_ASK = [
    _voice_candidate("Subdivision Surface, level 1", "object.modifier_add", {"type": "SUBSURF"},
                     {"levels": 1, "render_levels": 1}, True),
    _voice_candidate("Shade smooth", "object.shade_smooth", {}, {}, True),
    _voice_candidate("Shade auto smooth", "object.shade_auto_smooth", {}, {}, True),
]
GRAMMAR_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "voice.grammar.json"


def voice_answer(text):
    """The fake's canned (decision, reason, candidates) for a transcript: "join" is rejected,
    "monkey" runs Add a monkey, "copies" or "array" runs an Array on the target, and anything
    else asks between three smoothing operations."""
    words = re.findall(r"[a-z]+", text.lower())
    if "join" in words:
        return "reject", "Join isn't available by voice. Use host Blender.", []
    if "monkey" in words:
        found = [VOICE_MONKEY]
    elif "copies" in words or "array" in words:
        found = [VOICE_ARRAY]
    else:
        return "ask", None, [dict(c, choice=i) for i, c in enumerate(VOICE_ASK, 1)]
    return "run", None, [dict(c, choice=i) for i, c in enumerate(found, 1)]


def voice_grammar():
    """The real host's phrase list, as contracts/examples/voice.grammar.json has it."""
    try:
        return json.loads(GRAMMAR_EXAMPLE.read_text("utf-8"))["payload"]
    except (OSError, ValueError, KeyError):  # this file was copied on its own
        return {"version": "fake", "phrases": ["add a monkey", "five copies", "smooth", "one",
                                               "two", "three", "cancel"]}


# Meshes: triangulated, local space, meters, counter-clockwise seen from outside,
# vertices split where normals differ (contracts/README.md, Mesh encoding).


def _r(x):
    return round(x, 6) + 0.0  # 1 µm, and no -0.0


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v]


class _MeshBuilder:
    def __init__(self):
        self.positions, self.normals, self.indices = [], [], []

    def vertex(self, position, normal):
        self.positions.extend(_r(c) for c in position)
        self.normals.extend(_r(c) for c in normal)
        return len(self.positions) // 3 - 1

    def triangle(self, a, b, c):
        self.indices.extend((a, b, c))

    def mesh(self):
        return {"positions": self.positions, "normals": self.normals, "indices": self.indices}


def box_mesh(size):
    """A box centered on the origin; size is [x, y, z] in meters."""
    half = [s / 2 for s in size]
    m = _MeshBuilder()
    # (normal, u, v) with u x v = normal, so the corners below run counter-clockwise.
    faces = (
        ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
        ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
        ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
        ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
        ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
    )
    for n, u, v in faces:
        a, b, c, d = (
            m.vertex([(n[i] + su * u[i] + sv * v[i]) * half[i] for i in range(3)], n)
            for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))
        )
        m.triangle(a, b, c)
        m.triangle(a, c, d)
    return m.mesh()


def cylinder_mesh(size, segments=32):
    """A Z-axis cylinder centered on the origin: diameter size[0] by size[1], depth size[2]."""
    rx, ry, hz = size[0] / 2, size[1] / 2, size[2] / 2
    ring = [
        (math.cos(2 * math.pi * i / segments), math.sin(2 * math.pi * i / segments))
        for i in range(segments)
    ]
    m = _MeshBuilder()
    for z in (hz, -hz):  # caps, as fans around a center vertex
        n = (0, 0, 1 if z > 0 else -1)
        center = m.vertex((0, 0, z), n)
        first = center + 1
        for c, s in ring:
            m.vertex((rx * c, ry * s, z), n)
        for i in range(segments):
            a, b = first + i, first + (i + 1) % segments
            if z > 0:
                m.triangle(center, a, b)
            else:
                m.triangle(center, b, a)
    first = len(m.positions) // 3
    for c, s in ring:  # smooth sides
        n = _unit((c / rx, s / ry, 0))
        m.vertex((rx * c, ry * s, -hz), n)
        m.vertex((rx * c, ry * s, hz), n)
    for i in range(segments):
        j = (i + 1) % segments
        bottom_i, top_i = first + 2 * i, first + 2 * i + 1
        bottom_j, top_j = first + 2 * j, first + 2 * j + 1
        m.triangle(bottom_i, bottom_j, top_j)
        m.triangle(bottom_i, top_j, top_i)
    return m.mesh()


def sphere_mesh(size, segments=32, rings=16):
    """A UV sphere (an ellipsoid if size isn't uniform) centered on the origin."""
    rx, ry, rz = (s / 2 for s in size)
    m = _MeshBuilder()
    grid = []
    for j in range(rings + 1):
        phi = -math.pi / 2 + math.pi * j / rings
        row = []
        for i in range(segments + 1):
            theta = 2 * math.pi * i / segments
            d = (math.cos(phi) * math.cos(theta), math.cos(phi) * math.sin(theta), math.sin(phi))
            normal = _unit((d[0] / rx, d[1] / ry, d[2] / rz))
            row.append(m.vertex((rx * d[0], ry * d[1], rz * d[2]), normal))
        grid.append(row)
    for j in range(rings):
        for i in range(segments):
            a, b = grid[j][i], grid[j][i + 1]
            c, d = grid[j + 1][i + 1], grid[j + 1][i]
            if j > 0:  # the other triangle touching a pole has no area
                m.triangle(a, b, c)
            if j < rings - 1:
                m.triangle(a, c, d)
    return m.mesh()


MESHES = {"cube": box_mesh, "sphere": sphere_mesh, "cylinder": cylinder_mesh}


# Transforms: world location, rotation quaternion [w, x, y, z] and scale.


def quat_multiply(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return [
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ]


def axis_quat(axis, angle):
    q = [math.cos(angle / 2), 0.0, 0.0, 0.0]
    q[1 + "XYZ".index(axis)] = math.sin(angle / 2)
    return q


def _matrix(t):
    """World transform -> (3x3 linear part as rows, translation)."""
    w, x, y, z = _unit(t["rotation"])
    r = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ]
    s = t["scale"]
    return [[r[i][j] * s[j] for j in range(3)] for i in range(3)], list(t["location"])


def _compose(a, b):
    """The affine map a after b."""
    (la, ta), (lb, tb) = a, b
    linear = [[sum(la[i][k] * lb[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return linear, [sum(la[i][k] * tb[k] for k in range(3)) + ta[i] for i in range(3)]


def _det(m):
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _inverse(a):
    m, t = a
    det = _det(m)
    inv = [[0.0] * 3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            rows = [r for r in range(3) if r != j]
            cols = [c for c in range(3) if c != i]
            minor = m[rows[0]][cols[0]] * m[rows[1]][cols[1]] - m[rows[0]][cols[1]] * m[rows[1]][cols[0]]
            inv[i][j] = (-1) ** (i + j) * minor / det
    return inv, [-sum(inv[i][k] * t[k] for k in range(3)) for i in range(3)]


def _quat_from_rotation(m):
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        q = [s / 4, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s]
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = [(m[2][1] - m[1][2]) / s, s / 4, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s]
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = [(m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, s / 4, (m[1][2] + m[2][1]) / s]
    else:
        s = math.sqrt(1 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = [(m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, s / 4]
    return q


def tidy_transform(location, rotation, scale):
    """Round to 1 µm and keep the quaternion normalized with w >= 0."""
    q = _unit(rotation)
    if q[0] < 0:
        q = [-c for c in q]
    return {
        "location": [_r(c) for c in location],
        "rotation": [_r(c) for c in q],
        "scale": [float(f"{c:.9g}") + 0.0 for c in scale],  # relative: tiny scales stay > 0
    }


def _transform(a):
    """Affine map -> world transform. Shear is lost, as on the real host."""
    m, t = a
    scale = [math.sqrt(sum(m[i][j] ** 2 for i in range(3))) for j in range(3)]
    if _det(m) < 0:
        scale[0] = -scale[0]
    rotation = [[m[i][j] / scale[j] for j in range(3)] for i in range(3)]
    return tidy_transform(t, _quat_from_rotation(rotation), scale)


# Text for summaries and logs.


def mm(meters):
    text = f"{meters * 1000:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def mm3(values):
    return " x ".join(mm(v) for v in values)


def _factor(value):
    return f"{round(value, 6):g}"


def moved_summary(name, by):
    axes = [i for i in range(3) if by[i] != 0]
    if len(axes) == 1:
        return f"Moved {name} {mm(by[axes[0]])} mm along {'XYZ'[axes[0]]}"
    return f"Moved {name} by ({', '.join(mm(v) for v in by)}) mm"


# The scene: one document, its objects, the example sketch and the Undo history.


def _object(oid, name, type_, parent, location, rotation, color, mesh):
    return {
        "id": oid,
        "name": name,
        "type": type_,
        "parent": parent,
        "generation": 0,
        "visible": True,
        "transform": tidy_transform(location, rotation, [1, 1, 1]),
        "color": color,
        "mesh": mesh,
    }


def initial_objects():
    """The objects of contracts/examples/scene.snapshot.json, with generated meshes."""
    return [
        _object(BASE_PLATE_ID, "Base plate", "MESH", None, [0, 0, 0.005], [1, 0, 0, 0],
                [0.8, 0.8, 0.8, 1], box_mesh([0.1, 0.06, 0.01])),
        _object(SHAFT_ID, "Shaft", "MESH", BASE_PLATE_ID, [0.02, 0, 0.03], [1, 0, 0, 0],
                [0.25, 0.4, 0.8, 1], cylinder_mesh([0.02, 0.02, 0.04])),
        _object(CAMERA_ID, "Camera", "CAMERA", None, [0.3, -0.3, 0.2],
                [0.775377, 0.502339, 0.208076, 0.321172], None, None),
    ]


def initial_sketch():
    """The sketch of contracts/examples/scene.snapshot.json: a 100 x 60 mm rectangle on XY."""
    points = [("p1", [0, 0]), ("p2", [0.1, 0]), ("p3", [0.1, 0.06]), ("p4", [0, 0.06])]
    lines = [("l1", "p1", "p2"), ("l2", "p2", "p3"), ("l3", "p3", "p4"), ("l4", "p4", "p1")]
    return {
        "id": SKETCH_ID,
        "name": "Sketch",
        "generation": 0,
        "plane": {"location": [0, 0, 0], "rotation": [1, 0, 0, 0]},
        "solver": {"status": "fully_constrained", "dof": 0},
        "entities": [{"id": i, "kind": "point", "at": at} for i, at in points]
        + [{"id": i, "kind": "line", "points": [a, b]} for i, a, b in lines],
        "constraints": [
            {"id": "k1", "kind": "fixed", "entities": ["p1"]},
            {"id": "k2", "kind": "horizontal", "entities": ["l1"]},
            {"id": "k3", "kind": "horizontal", "entities": ["l3"]},
            {"id": "k4", "kind": "vertical", "entities": ["l2"]},
            {"id": "k5", "kind": "vertical", "entities": ["l4"]},
            {"id": "k6", "kind": "distance", "entities": ["l1"], "value": 0.1},
            {"id": "k7", "kind": "distance", "entities": ["l2"], "value": 0.06},
        ],
    }


def without_mesh(record):
    return {k: v for k, v in record.items() if k != "mesh"}


class Scene:
    """Records are never changed in place: every change makes new dicts."""

    def __init__(self):
        self.open_epoch = new_id()
        self.revision = 0
        self.dirty = False
        self.objects = {o["id"]: o for o in initial_objects()}
        self.sketches = [initial_sketch()]
        self.undo, self.redo = [], []

    def document(self):
        return {
            "id": DOCUMENT_ID,
            "open_epoch": self.open_epoch,
            "name": DOCUMENT_NAME,
            "revision": self.revision,
            "dirty": self.dirty,
            "units": dict(UNITS),
        }

    def snapshot(self):
        objects = list(self.objects.values())
        return {"document": self.document(), "objects": objects, "sketches": self.sketches}

    def change(self, changes):
        """Apply {id: record, or None to delete} as one revision; return the scene.update payload."""
        self.revision += 1
        self.dirty = True
        objects, removed = [], []
        for oid, record in changes.items():
            if record is None:
                if self.objects.pop(oid, None) is not None:
                    removed.append(oid)
                continue
            record = dict(record, generation=self.revision)
            known = oid in self.objects
            self.objects[oid] = record
            # Clients already have the mesh of an object they know; ours never change.
            objects.append(without_mesh(record) if known else record)
        return {"document": self.document(), "objects": objects, "sketches": [], "removed": removed}

    def commit(self, changes, summary):
        """change() plus one Undo step."""
        before = {oid: self.objects.get(oid) for oid in changes}
        update = self.change(changes)
        self.undo.append({"summary": summary, "before": before, "after": dict(changes)})
        del self.undo[:-MAX_UNDO]
        del self.redo[:]
        return update

    def step(self, backwards):
        """Undo (or redo) one step. Returns (summary, update) or None if there's nothing to do."""
        source, sink = (self.undo, self.redo) if backwards else (self.redo, self.undo)
        if not source:
            return None
        entry = source.pop()
        sink.append(entry)
        return entry["summary"], self.change(entry["before"] if backwards else entry["after"])

    def save(self):
        self.dirty = False  # Save doesn't change the revision
        return {"document": self.document(), "objects": [], "sketches": [], "removed": []}

    def children(self, oid):
        return [o for o, record in self.objects.items() if record["parent"] == oid]

    def descendants(self, oid):
        found, queue = [], [oid]
        while queue:
            for child in self.children(queue.pop()):
                found.append(child)
                queue.append(child)
        return found

    def transformed(self, oid, transform):
        """Changes for giving oid a new world transform. Its children move with it, as in Blender."""
        record = self.objects[oid]
        transform = tidy_transform(transform["location"], transform["rotation"], transform["scale"])
        changes = {oid: dict(record, transform=transform)}
        delta = _compose(_matrix(transform), _inverse(_matrix(record["transform"])))
        for child in self.descendants(oid):
            old = self.objects[child]
            moved = _transform(_compose(delta, _matrix(old["transform"])))
            changes[child] = dict(old, transform=moved)
        return changes

    def unique_name(self, base):
        names = {record["name"] for record in self.objects.values()}
        if base not in names:
            return base
        for n in itertools.count(1):
            name = f"{base}.{n:03d}"
            if name not in names:
                return name


# The server.


class Connection:
    def __init__(self, host, number, writer):
        self.host = host
        self.number = number
        self.writer = writer
        self.actor = None
        self.welcomed = False
        self.ended = False  # the reader saw the socket close
        self.stalled = False
        self.held = []  # data kept back while stalled
        self.resumed = asyncio.Event()
        self.resumed.set()
        self.inbox = asyncio.Queue()
        self.last_heard = asyncio.get_running_loop().time()

    @property
    def label(self):
        return f"#{self.number}" + (f" {self.actor['name']}" if self.actor else "")

    def send(self, msg):
        self.send_data(encode(msg), msg)

    def send_data(self, data, msg):
        if self.writer.is_closing():
            return
        if self.stalled:
            self.held.append((data, msg))
            return
        self.writer.write(data)
        self.host.trace(self, "->", msg, len(data))
        if self.writer.transport.get_write_buffer_size() > MAX_WRITE_BUFFER:
            self.host.log(f"{self.label}: not reading what we send; dropping it")
            self.writer.transport.abort()

    def close(self):
        if not self.writer.is_closing():
            self.writer.close()  # sends what is buffered first

    def resume(self):
        self.stalled = False
        held, self.held = self.held, []
        for data, msg in held:
            self.send_data(data, msg)
        self.last_heard = asyncio.get_running_loop().time()
        self.resumed.set()


TOO_LARGE = object()  # put in the inbox when a line is over MAX_LINE_BYTES
FENCED = (None, None)  # a request ID receipt.query reported missing: never applied from then on


def _print_log(text):
    print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)


class FakeHost:
    def __init__(self, options, log=_print_log):
        self.options = options
        self.log = log
        self.scene = Scene()
        self.host_epoch = new_id()
        self.port = options.port  # the bound port once started, useful with --port 0
        self.connections = {}  # number -> Connection
        self.receipts = {}  # request id -> (payload as canonical JSON, receipt)
        self.leases = {}  # lease_id -> lease, in the order they were granted
        self.lease_requests = {}  # lease.acquire id -> (payload as canonical JSON, reply)
        self.voice_resolutions = {}  # resolution -> (expires at, candidates, target ID or None)
        self._numbers = itertools.count(1)
        self._server = None
        self._stopped = None
        self._tasks = set()
        self.loop = None

    # Lifecycle

    async def run(self, ready=None):
        """Serve until request_stop() (or Ctrl-C)."""
        await self.start()
        if ready is not None:
            ready(self)
        try:
            await self._stopped.wait()
        finally:
            await self.stop()

    async def start(self):
        self.loop = asyncio.get_running_loop()
        self._stopped = asyncio.Event()
        # limit + 1 is the longest line accepted, newline included (as in server.py).
        self._server = await asyncio.start_server(
            self._serve, HOST, self.options.port, limit=MAX_LINE_BYTES - 1
        )
        self.port = self._server.sockets[0].getsockname()[1]
        if self.options.animate:
            self._spawn(self._animate())
        self._banner()

    def request_stop(self):
        """Safe from any thread."""
        self.loop.call_soon_threadsafe(self._stopped.set)

    async def stop(self):
        if self._server is not None:
            self._server.close()
        for conn in list(self.connections.values()):
            conn.writer.transport.abort()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _spawn(self, coro):
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _banner(self):
        o = self.options
        flags = [
            "--animate" if o.animate else None,
            f"--drop-after {o.drop_after:g}" if o.drop_after is not None else None,
            f"--stall-after {o.stall_after:g}" if o.stall_after is not None else None,
            f"--stall-for {o.stall_for:g}" if o.stall_for is not None else None,
            "--wrong-document" if o.wrong_document else None,
        ]
        flags = [f for f in flags if f]
        self.log("FAKE HOST: test data only, never acceptance evidence.")
        self.log(f"Listening on {HOST}:{self.port}. Document {DOCUMENT_NAME}, revision 0:")
        self.log(f"  Base plate {BASE_PLATE_ID[:8]}  box 100 x 60 x 10 mm at (0, 0, 5) mm")
        self.log(f"  Shaft      {SHAFT_ID[:8]}  cylinder 20 x 20 x 40 mm at (20, 0, 30) mm, "
                 "child of Base plate")
        self.log(f"  Camera     {CAMERA_ID[:8]}  no mesh")
        self.log(f"  Sketch     {SKETCH_ID[:8]}  100 x 60 mm rectangle on XY")
        self.log("Flags: " + (" ".join(flags) if flags else "none (see --help)"))

    # Connections

    async def _serve(self, reader, writer):
        conn = Connection(self, next(self._numbers), writer)
        self.connections[conn.number] = conn
        peer = writer.get_extra_info("peername") or ("?", 0)
        self.log(f"#{conn.number}: connected from {peer[0]}:{peer[1]}")
        timers = [self._spawn(self._watch(conn))]
        if self.options.drop_after is not None:
            timers.append(self._spawn(self._drop_later(conn)))
        if self.options.stall_after is not None:
            timers.append(self._spawn(self._stall_later(conn)))
        handler = self._spawn(self._handle(conn))
        try:
            await self._read(conn, reader)
        finally:
            conn.ended = True
            conn.resumed.set()  # a stalled handler finishes the lines already read
            conn.inbox.put_nowait(None)
            for timer in timers:
                timer.cancel()
            try:
                await handler
            finally:
                conn.close()
                del self.connections[conn.number]
                self.log(f"{conn.label}: disconnected")
                if conn.welcomed:
                    conn.welcomed = False
                    mine = [k for k, v in self.leases.items()
                            if v["owner"]["actor_id"] == conn.actor["actor_id"]]
                    for lease_id in mine:  # a lease ends with its owner's connection
                        del self.leases[lease_id]
                    if mine:
                        self.log(f"{conn.label}: its {len(mine)} lease(s) ended")
                    self.broadcast_session()

    async def _read(self, conn, reader):
        while True:
            try:
                line = await reader.readuntil(b"\n")
            except asyncio.IncompleteReadError:
                return  # closed; a last line without a newline is ignored
            except asyncio.LimitOverrunError:
                conn.inbox.put_nowait(TOO_LARGE)
                return
            except (ConnectionError, OSError):
                return
            conn.last_heard = self.loop.time()
            conn.inbox.put_nowait(line)

    async def _handle(self, conn):
        while True:
            line = await conn.inbox.get()
            if line is None:
                return
            if conn.stalled:
                await conn.resumed.wait()
            self.handle_line(conn, line)

    async def _watch(self, conn):
        """Close a connection we haven't heard from, as the real host does (Heartbeat)."""
        timeout = self.options.idle_timeout
        if not timeout:
            return
        while True:
            await asyncio.sleep(min(0.5, timeout / 4))
            if not conn.stalled and self.loop.time() - conn.last_heard > timeout:
                self.log(f"{conn.label}: nothing heard for {timeout:g} s, closing "
                         "(clients send ping every 2 s)")
                conn.close()
                return

    async def _drop_later(self, conn):
        await asyncio.sleep(self.options.drop_after)
        self.log(f"{conn.label}: --drop-after: closing the connection")
        conn.close()

    async def _stall_later(self, conn):
        await asyncio.sleep(self.options.stall_after)
        if conn.ended:
            return
        conn.stalled = True
        conn.resumed.clear()
        until = f" for {self.options.stall_for:g} s" if self.options.stall_for is not None else ""
        self.log(f"{conn.label}: --stall-after: answering nothing{until} (no pong, no updates)")
        if self.options.stall_for is None:
            return
        await asyncio.sleep(self.options.stall_for)
        conn.resume()
        self.log(f"{conn.label}: answering again")

    async def _animate(self):
        step = math.radians(ANIMATE_DEGREES_PER_SECOND) * ANIMATE_INTERVAL
        self.log("--animate: turning Shaft about Z, one scene.update every "
                 f"{ANIMATE_INTERVAL:g} s")
        while True:
            await asyncio.sleep(ANIMATE_INTERVAL)
            objects = self.scene.objects
            oid = SHAFT_ID if SHAFT_ID in objects else next(
                (o for o, record in objects.items() if record["mesh"]), None
            )
            if oid is None:
                continue
            t = objects[oid]["transform"]
            turned = dict(t, rotation=quat_multiply(axis_quat("Z", step), t["rotation"]))
            update = self.scene.change(self.scene.transformed(oid, turned))
            self.broadcast(message("scene.update", update))

    def trace(self, conn, arrow, msg, size):
        if self.options.verbose and msg is not None:
            text = json.dumps(msg, separators=(",", ":"), ensure_ascii=False)
            if len(text) > 300:
                text = text[:300] + f"... ({size} bytes)"
            self.log(f"{conn.label} {arrow} {text}")

    def broadcast(self, msg, exclude=None):
        data = encode(msg)
        for conn in list(self.connections.values()):
            if conn.welcomed and conn is not exclude:
                conn.send_data(data, msg)

    def broadcast_session(self):
        participants = [dict(HOST_ACTOR)] + [
            dict(c.actor) for c in self.connections.values() if c.welcomed
        ]
        leases = [dict(lease) for lease in self.leases.values()]
        self.broadcast(message("session.update", {"participants": participants,
                                                  "leases": leases}))

    # Messages

    def handle_line(self, conn, line):
        if line is TOO_LARGE:
            text = f"line is longer than {MAX_LINE_BYTES} bytes"
            conn.send(error("message_too_large", text))
            conn.close()
            return
        if not line.strip():
            return
        try:
            msg = decode(line)
        except WireError as e:
            self.log(f"{conn.label}: rejected a line ({e.code}: {e})")
            conn.send(error(e.code, str(e), e.re))
            if e.close:
                conn.close()
            return
        self.trace(conn, "<-", msg, len(line))
        kind, mid = msg["type"], msg["id"]
        try:
            if kind == "ping":
                _fields(msg["payload"], "ping payload", ())
                conn.send(message("pong", re=mid))
            elif kind == "pong":
                pass
            elif kind == "error":
                p = msg["payload"]
                self.log(f"{conn.label}: the client sent error {p.get('code')}: {p.get('message')}")
            elif kind == "hello":
                self.on_hello(conn, msg)
            elif not conn.welcomed:
                text = "Send hello and wait for welcome first."
                conn.send(error("permission_denied", text, mid))
            elif kind == "command":
                self.on_command(conn, msg)
            elif kind == "receipt.query":
                self.on_receipt_query(conn, msg)
            elif kind == "lease.acquire":
                self.on_lease_acquire(conn, msg)
            elif kind == "lease.release":
                self.on_lease_release(conn, msg)
            elif kind == "voice.resolve":
                self.on_voice_resolve(conn, msg)
            elif kind == "voice.grammar_query":
                _fields(msg["payload"], "voice.grammar_query payload", ())
                conn.send(message("voice.grammar", voice_grammar(), re=mid))
            else:
                text = f"The fake host doesn't handle {kind!r} messages."
                conn.send(error("unknown_type", text, mid))
        except Invalid as e:
            self.log(f"{conn.label}: invalid {kind}: {e}")
            conn.send(error("invalid_message", str(e), mid))
        except Exception as e:  # noqa: BLE001 (logged; a bug in the fake must not stop it)
            self.log(f"{conn.label}: fake host bug while handling {kind}:\n{traceback.format_exc()}")
            conn.send(error("internal_error", f"fake host bug: {e}", mid))

    def _document_details(self):
        d = self.scene.document()
        return {"document": {"id": d["id"], "open_epoch": d["open_epoch"], "name": d["name"]}}

    def _refuse(self, conn, msg, code, text, details=None):
        self.log(f"{conn.label}: refused hello: {code}: {text}")
        conn.send(error(code, text, msg["id"], details))
        conn.close()

    def on_hello(self, conn, msg):
        if conn.welcomed:
            raise Invalid("this connection was already welcomed")
        p = msg["payload"]
        check_hello(p)
        if p["role"] == "blender-client" and p["app"]["version"] != APP["version"]:
            text = (f"The host runs version {APP['version']} and this add-on is "
                    f"{p['app']['version']}. Install the same version on both PCs.")
            self._refuse(conn, msg, "unsupported_version", text)
            return
        expected = p.get("document")
        scene = self.scene
        other = expected is not None and (expected["id"], expected["open_epoch"]) != (
            DOCUMENT_ID, scene.open_epoch,
        )
        if self.options.wrong_document or other:
            text = f"Blender has another document open ({DOCUMENT_NAME}). Rejoin to get it."
            self._refuse(conn, msg, "wrong_document", text, self._document_details())
            return
        conn.actor = {"actor_id": new_id(), "name": p["name"], "role": p["role"]}
        conn.send(message("welcome", {
            "session_id": SESSION_ID,
            "host_epoch": self.host_epoch,
            "actor_id": conn.actor["actor_id"],
            "can_edit": True,
            "app": dict(APP),
            "document": scene.document(),
        }, re=msg["id"]))
        conn.send(message("scene.snapshot", scene.snapshot()))
        conn.welcomed = True
        self.log(f"{conn.label}: welcomed ({p['role']}, {p['app']['name']} {p['app']['version']}); "
                 f"sent the snapshot at revision {scene.revision}")
        self.broadcast_session()

    def on_voice_resolve(self, conn, msg):
        p = msg["payload"]
        check_voice_resolve(p)
        decision, reason, candidates = voice_answer(p["text"])
        resolution = new_id()
        if decision != "reject":
            target = p.get("target")
            target_id = target["id"] if target and target["id"] in self.scene.objects else None
            now = time.monotonic()
            self.voice_resolutions = {r: v for r, v in self.voice_resolutions.items()
                                      if v[0] > now}
            self.voice_resolutions[resolution] = (now + VOICE_EXPIRES_IN, candidates, target_id)
        self.log(f"{conn.label}: voice {p['text']!r}: {decision} "
                 f"{[c['say'] for c in candidates] or reason}")
        conn.send(message("voice.candidates", {
            "resolution": resolution, "decision": decision, "reason": reason,
            "expires_in": VOICE_EXPIRES_IN, "candidates": candidates}, re=msg["id"]))

    def run_voice(self, args, target):
        """voice.run: (summary, created, changes) or a (code, text) refusal. Single use."""
        kept = self.voice_resolutions.pop(args["resolution"], None)
        if kept is None or kept[0] <= time.monotonic() or args["choice"] > len(kept[1]):
            return "not_found", "That voice choice has expired. Say it again."
        _, candidates, target_id = kept
        c = candidates[int(args["choice"]) - 1]
        if not c["needs_target"]:  # the fake's one add: a 40 mm box named like Blender's monkey
            name = self.scene.unique_name("Suzanne")
            record = _object(new_id(), name, "MESH", None, [0, 0, 0.02], [1, 0, 0, 0], None,
                             box_mesh([0.04, 0.04, 0.04]))
            return f"Voice: added {name}", [record["id"]], {record["id"]: record}
        if target is None:
            return "failed", f"{c['say']} needs an object. Select one, then say it again."
        if target_id is not None and target["id"] != target_id:
            return "failed", "That choice was for another object. Say it again."
        # The fake has no modifiers: the target only gets a new generation.
        summary = f"Voice: {c['say']} on {target['name']}"
        return summary, None, {target["id"]: dict(target)}

    def on_receipt_query(self, conn, msg):
        p = msg["payload"]
        check_receipt_query(p)
        ids = p["request_ids"]
        found = [self.receipts[i][1] for i in ids if self.receipts.get(i, FENCED)[1] is not None]
        unseen = [i for i in ids if self.receipts.get(i, FENCED)[1] is None]
        if p["host_epoch"] != self.host_epoch:  # from before a restart: they may have applied
            conn.send(message("receipts", {"receipts": found, "missing": [], "unknown": unseen},
                              re=msg["id"]))
            return
        for i in unseen:
            self.receipts[i] = FENCED  # never received; refused if it turns up late
        conn.send(message("receipts", {"receipts": found, "missing": unseen, "unknown": []},
                          re=msg["id"]))

    def on_command(self, conn, msg):
        p, rid = msg["payload"], msg["id"]
        check_command(p)
        key = json.dumps(p, sort_keys=True)
        stored = self.receipts.get(rid)
        if stored is FENCED:
            receipt = self._receipt(conn, p, rid, "rejected", error={
                "code": "duplicate_request",
                "message": "receipt.query already reported this request ID as not received.",
            })
            self.receipts[rid] = (key, receipt)
            self.log(f"{conn.label}: {p['op']} rejected: duplicate_request (fenced by receipt.query)")
            conn.send(message("result", receipt, re=rid))
            return
        if stored is not None:
            if stored[0] == key:
                self.log(f"{conn.label}: repeated request {rid[:8]}; sent its stored result again")
                conn.send(message("result", stored[1], re=rid))
                return
            receipt = self._receipt(conn, p, rid, "rejected", error={
                "code": "duplicate_request",
                "message": "This request ID was already used for a different command.",
            })
            self.log(f"{conn.label}: {p['op']} rejected: duplicate_request")
            conn.send(message("result", receipt, re=rid))
            return
        receipt, update = self.run_command(conn, p, rid)
        self.receipts[rid] = (key, receipt)
        # The contract's order: scene.update to every client, result, activity to the others.
        if update is not None:
            self.broadcast(message("scene.update", update))
        conn.send(message("result", receipt, re=rid))
        if receipt["outcome"] == "applied":
            self.broadcast(message("activity", receipt), exclude=conn)
            self.log(f"{conn.label}: {p['op']} applied, revision {receipt['revision']}: "
                     f"{receipt['summary']}")
        else:
            e = receipt["error"]
            self.log(f"{conn.label}: {p['op']} rejected: {e['code']}: {e['message']}")

    # Leases, with the real host's rules (blender_addon/spatial_modeling/leases.py)

    def on_lease_acquire(self, conn, msg):
        p, rid = msg["payload"], msg["id"]
        check_lease_acquire(p)
        key = json.dumps(p, sort_keys=True)
        stored = self.lease_requests.get(rid)
        if stored is not None:
            if stored[0] == key:
                self.log(f"{conn.label}: repeated lease.acquire {rid[:8]}; sent its answer again")
                conn.send(dict(stored[1], id=new_id()))
            else:
                conn.send(error("duplicate_request", "This request ID was already used for a "
                                "different lease.acquire. Use a new ID.", rid))
            return
        reply = self.grant_lease(conn, p, rid)
        self.lease_requests[rid] = (key, reply)
        if reply["type"] == "error":
            e = reply["payload"]
            self.log(f"{conn.label}: lease.acquire refused: {e['code']}: {e['message']}")
        conn.send(reply)

    def grant_lease(self, conn, p, rid):
        """Check one schema-valid lease.acquire. Returns lease.granted or error."""
        if p["actor_id"] != conn.actor["actor_id"]:
            return error("permission_denied", "actor_id isn't this connection's; copy it from "
                         "welcome.", rid)
        if (p["session_id"], p["host_epoch"]) != (SESSION_ID, self.host_epoch):
            return error("wrong_session", "The host restarted since you connected. Reconnect.",
                         rid)
        if (p["document_id"], p["open_epoch"]) != (DOCUMENT_ID, self.scene.open_epoch):
            return error("wrong_document", f"Blender has another document open "
                         f"({DOCUMENT_NAME}).", rid, self._document_details())
        sketches = {s["id"] for s in self.scene.sketches}
        missing = [t for t in p["targets"] if t not in self.scene.objects and t not in sketches]
        if missing:
            return error("not_found", f"{len(missing)} of the targets don't exist (any more): "
                         f"{', '.join(missing)}.", rid)
        actor_id, mode = conn.actor["actor_id"], p["mode"]
        targets = self.covered(p["targets"]) if mode == "shared" else []
        blocking = self.blocking_lease(actor_id, mode, targets)
        if blocking is not None:
            text = _conflict_text(blocking, mode == "exclusive", "lease")
            return error("lease_conflict", text, rid, {"lease": dict(blocking)})
        lease = {"lease_id": new_id(), "mode": mode, "owner": dict(conn.actor),
                 "targets": targets, "acquired_at": int(time.time() * 1000)}
        self.leases[lease["lease_id"]] = lease
        names = ", ".join(self._target_name(t) for t in targets) or "the whole document"
        self.log(f"{conn.label}: {mode} lease {lease['lease_id'][:8]} on {names}")
        self.broadcast_session()  # everyone sees the new owner, then the sender gets the lease
        return message("lease.granted", {"lease": dict(lease)}, re=rid)

    def on_lease_release(self, conn, msg):
        p = msg["payload"]
        check_lease_release(p)
        lease = self.leases.get(p["lease_id"])
        if lease is None:
            conn.send(error("not_found", "No lease with that ID is held (any more).", msg["id"]))
        elif lease["owner"]["actor_id"] != conn.actor["actor_id"]:
            conn.send(error("permission_denied", "That lease is someone else's.", msg["id"]))
        else:
            del self.leases[p["lease_id"]]
            self.log(f"{conn.label}: released lease {p['lease_id'][:8]}")
            self.broadcast_session()  # no reply on success

    def covered(self, ids):
        """ids followed by their linked data: descendants and objects sharing a mesh."""
        objects = self.scene.objects
        out, queue = list(dict.fromkeys(ids)), list(ids)
        while queue:
            record = objects.get(queue.pop())
            if record is None:
                continue  # a sketch, leased whole by its ID
            near = self.scene.children(record["id"]) + [
                o for o, r in objects.items()
                if record["mesh"] is not None and r["mesh"] is record["mesh"]
            ]
            for oid in near:
                if oid not in out:
                    out.append(oid)
                    queue.append(oid)
        return out

    def blocking_lease(self, actor_id, mode, targets):
        """Another participant's lease that collides with this mode and these targets, or None."""
        for lease in self.leases.values():
            if lease["owner"]["actor_id"] == actor_id:
                continue  # your own leases never conflict
            if "exclusive" in (mode, lease["mode"]) or set(targets) & set(lease["targets"]):
                return lease
        return None

    def lease_check(self, actor_id, op, target_id, lease_id):
        """Step 6 of a command: None, or (code, message, details) to reject it with."""
        if lease_id is not None:
            lease = self.leases.get(lease_id)
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
        history = op in ("history.undo", "history.redo")
        targets = self.covered([target_id]) if target_id is not None else []
        blocking = self.blocking_lease(actor_id, "exclusive" if history else "shared", targets)
        if blocking is None:
            return None
        return "lease_conflict", _conflict_text(blocking, history, "command"), {
            "lease": dict(blocking)}

    def _target_name(self, oid):
        record = self.scene.objects.get(oid)
        return record["name"] if record else oid[:8]

    def _receipt(self, conn, p, rid, outcome, summary=None, created=None, error=None):
        receipt = {"request_id": rid, "op": p["op"]}
        if "target" in p:
            receipt["target"] = p["target"]["id"]
        receipt.update(actor=dict(conn.actor), source=p["source"], outcome=outcome,
                       revision=self.scene.revision)
        if created:
            receipt["created"] = created
        if summary:
            receipt["summary"] = summary[:1024]
        if error:
            receipt["error"] = error
        receipt["at"] = int(time.time() * 1000)
        return receipt

    def run_command(self, conn, p, rid):
        """Check and apply one schema-valid command. Returns (receipt, scene.update payload)."""
        scene, op, args = self.scene, p["op"], p["args"]

        def rejected(code, text, details=None):
            e = {"code": code, "message": text}
            if details:
                e["details"] = details
            return self._receipt(conn, p, rid, "rejected", error=e), None

        if p["actor_id"] != conn.actor["actor_id"]:
            return rejected("permission_denied", "actor_id isn't this connection's; copy it "
                            "from welcome.")
        if (p["session_id"], p["host_epoch"]) != (SESSION_ID, self.host_epoch):
            return rejected("wrong_session", "The host restarted since you connected. Reconnect.")
        if (p["document_id"], p["open_epoch"]) != (DOCUMENT_ID, scene.open_epoch):
            return rejected("wrong_document", f"Blender has another document open "
                            f"({DOCUMENT_NAME}).", self._document_details())
        if op not in SUPPORTED_OPS:
            return rejected("failed", f"The fake host doesn't do {op}. It does "
                            f"{', '.join(SUPPORTED_OPS)}.")
        target = None
        if "target" in p:
            target = scene.objects.get(p["target"]["id"])
            if target is None:
                return rejected("not_found", "That object doesn't exist (any more).")
            if target["generation"] != p["target"]["generation"]:
                return rejected("stale_revision", f"{target['name']} changed since you last saw "
                                "it. Check it and try again.", {"generation": target["generation"]})
        if op in ("history.undo", "history.redo") and p["base_revision"] != scene.revision:
            return rejected("stale_revision", "The document changed since you last saw it. "
                            "Check it and try again.", {"revision": scene.revision})
        refusal = self.lease_check(conn.actor["actor_id"], op, target and target["id"],
                                   p.get("lease"))
        if refusal is not None:
            return rejected(*refusal)

        created = None
        if op == "object.add":
            primitive, size = args["primitive"], args["dimensions"]
            name = scene.unique_name(PRIMITIVES[primitive])
            record = _object(new_id(), name, "MESH", None, args["location"], [1, 0, 0, 0], None,
                             MESHES[primitive](size))
            created = [record["id"]]
            summary = f"Added {name} ({mm3(size)} mm)"
            update = scene.commit({record["id"]: record}, summary)
        elif op in ("object.move", "object.rotate", "object.scale"):
            t, name = dict(target["transform"]), target["name"]
            if op == "object.move" and "by" in args:
                t["location"] = [a + b for a, b in zip(t["location"], args["by"])]
                summary = moved_summary(name, args["by"])
            elif op == "object.move":
                t["location"] = args["to"]
                summary = f"Moved {name} to ({', '.join(mm(v) for v in args['to'])}) mm"
            elif op == "object.rotate" and "by" in args:
                axis, angle = args["by"]["axis"], args["by"]["angle"]
                t["rotation"] = quat_multiply(axis_quat(axis, angle), t["rotation"])
                summary = f"Rotated {name} {round(math.degrees(angle), 3):g}° about {axis}"
            elif op == "object.rotate":
                if math.sqrt(sum(c * c for c in args["to"])) < 1e-6:
                    return rejected("failed", "args.to is not a rotation: its length is 0.")
                t["rotation"] = args["to"]
                summary = f"Set the rotation of {name}"
            elif "by" in args:
                t["scale"] = [a * b for a, b in zip(t["scale"], args["by"])]
                summary = f"Scaled {name} by {' x '.join(_factor(v) for v in args['by'])}"
            else:
                t["scale"] = args["to"]
                summary = f"Set the scale of {name} to {' x '.join(_factor(v) for v in args['to'])}"
            update = scene.commit(scene.transformed(target["id"], t), summary)
        elif op == "object.delete":
            changes = {target["id"]: None}
            for child in scene.children(target["id"]):  # children stay where they are
                changes[child] = dict(scene.objects[child], parent=None)
            summary = f"Deleted {target['name']}"
            update = scene.commit(changes, summary)
        elif op in ("history.undo", "history.redo"):
            undo = op == "history.undo"
            done = scene.step(backwards=undo)
            if done is None:
                return rejected("failed", "Nothing to undo." if undo else "Nothing to redo.")
            summary = ("Undid: " if undo else "Redid: ") + done[0]
            update = done[1]
        elif op == "voice.run":
            done = self.run_voice(args, target)
            if len(done) == 2:
                return rejected(*done)
            summary, created, changes = done
            update = scene.commit(changes, summary)
        else:  # document.save
            update = scene.save()
            summary = f"Saved {DOCUMENT_NAME}"
        return self._receipt(conn, p, rid, "applied", summary, created), update


def _conflict_text(lease, whole, what):
    name = lease["owner"]["name"]
    if lease["mode"] == "exclusive":
        return f"{name} is editing the whole document."
    if whole and what == "command":
        return f"{name} is editing, so Undo and Redo wait until they finish."
    if whole:
        return f"{name} is editing, so nobody can reserve the whole document."
    return f"{name} is editing this."


def _seconds(text):
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more seconds")
    return value


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="fake_host.py",
        description="Fake Host-role add-on for building the Unity app without Blender. "
        "TEST DATA ONLY: never acceptance evidence. Serves the contract in "
        "contracts/README.md on 127.0.0.1.",
        epilog="--drop-after, --stall-after and --idle-timeout count from when each connection "
        "opens, so a client that reconnects goes through them again. Ctrl-C stops the fake.",
    )
    parser.add_argument("--port", type=int, default=PORT,
                        help="TCP port on 127.0.0.1 (default 8765; 0 picks a free one)")
    parser.add_argument("--animate", action="store_true",
                        help="turn Shaft about Z at 20 degrees/s, one scene.update every 0.25 s, "
                        "as if someone were editing in Blender (live updates)")
    parser.add_argument("--drop-after", type=_seconds, metavar="SECONDS",
                        help="close each connection SECONDS after it opens (Disconnected, "
                        "reconnect; the fresh snapshot keeps the changes made so far)")
    parser.add_argument("--stall-after", type=_seconds, metavar="SECONDS",
                        help="SECONDS after each connection opens, stop sending it anything: no "
                        "pong, no updates, the socket stays open (Not responding)")
    parser.add_argument("--stall-for", type=_seconds, metavar="SECONDS",
                        help="with --stall-after: answer again after SECONDS, sending what was "
                        "held back (default: stay silent)")
    parser.add_argument("--wrong-document", action="store_true",
                        help="refuse every hello with error wrong_document and close. The real "
                        "host does that only to a hello that names another document")
    parser.add_argument("--idle-timeout", type=_seconds, default=6.0, metavar="SECONDS",
                        help="close a connection that sent nothing for SECONDS, like the real "
                        "host (default 6; 0 turns it off)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="log every message sent and received")
    options = parser.parse_args(argv)
    if options.stall_for is not None and options.stall_after is None:
        parser.error("--stall-for needs --stall-after")
    return options


def main(argv=None):
    options = parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    try:
        asyncio.run(FakeHost(options).run())
    except KeyboardInterrupt:
        print("Stopped.")
    except OSError as e:
        sys.exit(f"Could not listen on {HOST}:{options.port} ({e}). Is Blender with the add-on "
                 "in Host role, or another fake host, already using the port?")


if __name__ == "__main__":
    main()

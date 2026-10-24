"""Every example in contracts/examples matches its schema, and broken messages don't."""

import copy
import json
import re
from pathlib import Path

import protocol
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SCHEMAS = {
    path.name.removesuffix(".schema.json"): json.loads(path.read_text("utf-8"))
    for path in sorted((CONTRACTS / "schemas").glob("*.schema.json"))
}
REGISTRY = Registry().with_resources(
    (schema["$id"], Resource.from_contents(schema)) for schema in SCHEMAS.values()
)
EXAMPLES = sorted((CONTRACTS / "examples").glob("*.json"))
HTTP_BODIES = {"capture.status"}  # served by the capture helper, no envelope
MESSAGE_TYPES = set(SCHEMAS) - HTTP_BODIES - {"envelope"}
DELETE = object()


def load(name):
    return json.loads((CONTRACTS / "examples" / name).read_text("utf-8"))


def schema_for(instance):
    return instance["type"] if "v" in instance else "capture.status"


def is_valid(schema_name, instance):
    return Draft202012Validator(SCHEMAS[schema_name], registry=REGISTRY).is_valid(instance)


def changed(name, changes):
    """The example `name` with {"dotted.path": value} applied; DELETE removes the key."""
    msg = copy.deepcopy(load(name))
    for path, value in changes.items():
        *parents, last = [int(p) if p.isdigit() else p for p in path.split(".")]
        node = msg
        for key in parents:
            node = node[key]
        if value is DELETE:
            del node[last]
        else:
            node[last] = value
    return msg


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_schema_is_valid(name):
    Draft202012Validator.check_schema(SCHEMAS[name])
    assert SCHEMAS[name]["$id"] == f"{name}.schema.json"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_matches_its_schema(path):
    instance = json.loads(path.read_text("utf-8"))
    name = schema_for(instance)
    stem = path.name.removesuffix(".json")
    assert stem == name or stem.startswith(name + "."), "file name must start with the type"
    Draft202012Validator(SCHEMAS[name], registry=REGISTRY).validate(instance)
    if name not in HTTP_BODIES:
        assert protocol.decode(protocol.encode(instance)) == instance


def test_every_type_and_op_has_an_example():
    examples = [json.loads(p.read_text("utf-8")) for p in EXAMPLES]
    types = {m["type"] for m in examples if "v" in m}
    assert types == MESSAGE_TYPES
    ops = {m["payload"]["op"] for m in examples if m.get("type") == "command"}
    assert ops == set(SCHEMAS["command"]["$defs"]["op"]["enum"])


def test_readme_lists_every_type_and_error_code():
    readme = (CONTRACTS / "README.md").read_text("utf-8")
    table_rows = set(re.findall(r"^\| `([a-z._]+)`", readme, re.MULTILINE))
    assert MESSAGE_TYPES <= table_rows
    codes = SCHEMAS["envelope"]["$defs"]["error_code"]["enum"]
    assert {c for c in codes if f"`{c}`" not in readme} == set()


TRANSPORT_CODES = {
    "invalid_message",
    "unsupported_version",
    "message_too_large",
    "unknown_type",
    "busy",
    "internal_error",
}


def test_error_codes_include_the_servers_transport_codes():
    assert TRANSPORT_CODES <= set(SCHEMAS["envelope"]["$defs"]["error_code"]["enum"])


VALID = [
    ("command.json", {"payload.args": {"to": [0.03, 0, 0.03]}}),
    ("command.object.rotate.json", {"payload.args": {"to": [0.707107, 0, 0, 0.707107]}}),
    ("command.object.scale.json", {"payload.args": {"by": [2, 2, 2]}, "payload.lease": DELETE}),
    ("command.object.select.json", {"payload.args.ids": []}),
    (
        "command.sketch.constrain.json",
        {"payload.args": {"kind": "angle", "entities": ["l1", "l5"], "value": 0.785398}},
    ),
    (
        "command.sketch.constrain.json",
        {"payload.args": {"kind": "coincident", "entities": ["p5", "l1"]}},
    ),
    ("command.sketch.constrain.json", {"payload.args": {"kind": "fixed", "entities": ["p1"]}}),
    (
        "command.sketch.constrain.json",
        {"payload.args": {"kind": "diameter", "entities": ["c1"], "value": 0.02}},
    ),
    ("lease.acquire.json", {"payload.mode": "exclusive", "payload.targets": []}),
    ("result.json", {"payload.outcome": "unknown"}),
    ("error.json", {"re": DELETE, "payload.details": DELETE}),
]


@pytest.mark.parametrize(("name", "changes"), VALID)
def test_accepts(name, changes):
    msg = changed(name, changes)
    assert is_valid(schema_for(msg), msg)


INVALID = [
    ("ping.json", {"v": 2}),
    ("ping.json", {"id": "not-a-uuid"}),
    ("ping.json", {"extra": 1}),
    ("pong.json", {"re": DELETE}),
    ("hello.json", {"payload.role": "host"}),
    ("hello.json", {"payload.name": DELETE}),
    ("hello.json", {"payload.app.version": "latest"}),
    ("welcome.json", {"payload.document.units.scale_length": 0}),
    ("welcome.json", {"payload.actor_id": DELETE}),
    ("error.json", {"payload.code": "malformed"}),
    ("error.json", {"payload.message": DELETE}),
    ("command.json", {"payload.op": "object.explode"}),
    ("command.json", {"payload.session_id": DELETE}),
    ("command.json", {"payload.base_revision": DELETE}),
    ("command.json", {"payload.colour": "red"}),
    ("command.json", {"payload.source": "keyboard"}),
    ("command.json", {"payload.target": DELETE}),
    ("command.json", {"payload.target.generation": -1}),
    ("command.json", {"payload.args.by": [1e6, 0, 0]}),
    ("command.json", {"payload.args.by": [0.01, 0]}),
    ("command.json", {"payload.args.by": ["10 mm", 0, 0]}),
    ("command.json", {"payload.args": {"by": [0.01, 0, 0], "to": [0, 0, 0]}}),
    ("command.object.rotate.json", {"payload.args.by.angle": 90}),
    ("command.object.rotate.json", {"payload.args.by.axis": "W"}),
    ("command.object.add.json", {"payload.args.primitive": "torus"}),
    ("command.object.add.json", {"payload.args.dimensions": [0, 0.02, 0.04]}),
    (
        "command.object.add.json",
        {"payload.target": {"id": "fd7bd4ddae444528a4fedbc562fe018b", "generation": 40}},
    ),
    ("command.object.scale.json", {"payload.args.to": [0, 1, 1]}),
    ("command.object.select.json", {"payload.args.ids": ["fd7bd4ddae444528a4fedbc562fe018b"] * 2}),
    ("command.history.undo.json", {"payload.args": {"steps": 3}}),
    ("command.sketch.constrain.json", {"payload.args.value": DELETE}),
    ("command.sketch.constrain.json", {"payload.args.kind": "tangent"}),
    (
        "command.sketch.constrain.json",
        {"payload.args": {"kind": "horizontal", "entities": ["l1"], "value": 0.1}},
    ),
    ("command.sketch.constrain.json", {"payload.args": {"kind": "coincident", "entities": ["p1"]}}),
    (
        "command.sketch.constrain.json",
        {"payload.args": {"kind": "angle", "entities": ["l1", "l2"], "value": 90}},
    ),
    ("command.sketch.set_dimension.json", {"payload.args.value": -0.12}),
    ("result.json", {"re": DELETE}),
    ("result.json", {"payload.outcome": "pending"}),
    ("result.json", {"payload.outcome": "rejected"}),
    ("result.stale_revision.json", {"payload.outcome": "applied"}),
    ("activity.json", {"payload.outcome": "rejected"}),
    ("receipt.query.json", {"payload.request_ids": []}),
    ("receipts.json", {"payload.missing": DELETE}),
    ("lease.acquire.json", {"payload.targets": []}),
    ("lease.acquire.json", {"payload.mode": "exclusive"}),
    ("lease.acquire.json", {"payload.actor_id": DELETE}),
    ("lease.granted.json", {"payload.lease.owner": "Talia"}),
    ("lease.release.json", {"payload.lease_id": DELETE}),
    ("session.update.json", {"payload.leases.0.mode": "locked"}),
    ("scene.snapshot.json", {"payload.objects.0.mesh": DELETE}),
    ("scene.snapshot.json", {"payload.objects.0.transform.rotation": [1, 0, 0]}),
    ("scene.snapshot.json", {"payload.objects.0.id": "Base plate"}),
    ("scene.snapshot.json", {"payload.sketches.0.constraints.5.value": DELETE}),
    ("scene.snapshot.json", {"payload.sketches.0.solver.status": "solved"}),
    ("scene.update.json", {"payload.removed": DELETE}),
    ("capture.status.json", {"state": "paused"}),
    ("capture.status.json", {"frame": DELETE}),
]


@pytest.mark.parametrize(("name", "changes"), INVALID)
def test_rejects(name, changes):
    msg = changed(name, changes)
    assert not is_valid(schema_for(msg), msg)


def test_requests_copy_their_fields_from_welcome():
    welcome = load("welcome.json")["payload"]
    expected = {
        "session_id": welcome["session_id"],
        "host_epoch": welcome["host_epoch"],
        "document_id": welcome["document"]["id"],
        "open_epoch": welcome["document"]["open_epoch"],
        "actor_id": welcome["actor_id"],
    }
    requests = [json.loads(p.read_text("utf-8")) for p in EXAMPLES]
    requests = [m for m in requests if m.get("type") in ("command", "lease.acquire")]
    assert requests
    for msg in requests:
        assert {k: msg["payload"][k] for k in expected} == expected

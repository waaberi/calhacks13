"""Validate the message contracts in contracts/ (layout described in contracts/README.md).

  contracts/schemas/<message>.schema.json       JSON Schema (draft 2020-12) for one message type
  contracts/samples/<message>/*.json            examples that MUST validate against that schema
  contracts/samples/<message>/invalid/*.json    malformed examples that MUST be rejected

Schemas may $ref each other by file name, e.g. {"$ref": "envelope.schema.json"}.

Run locally from the repo root: python .github/scripts/validate_contracts.py
"""

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts" / "schemas"
SAMPLES = ROOT / "contracts" / "samples"
SUFFIX = ".schema.json"


def rel(path):
    return path.relative_to(ROOT).as_posix()


def load_json(path, errors):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        errors.append((path, f"Invalid JSON: {e}"))
        return None


def main():
    errors = []
    schemas = {}
    for path in sorted(SCHEMAS.glob(f"*{SUFFIX}")):
        schema = load_json(path, errors)
        if schema is None:
            continue
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as e:
            errors.append((path, f"Not a valid JSON Schema: {e.message}"))
            continue
        schemas[path.name[: -len(SUFFIX)]] = (path, schema)

    resources = []
    for path, schema in schemas.values():
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        resources.append((path.name, resource))
        if resource.id():
            resources.append((resource.id(), resource))
    registry = Registry().with_resources(resources)

    checked = 0
    for path in sorted(SAMPLES.rglob("*.json")):
        parts = path.relative_to(SAMPLES).parts
        if len(parts) < 2:
            errors.append((path, "Put samples in contracts/samples/<message>/ so CI knows which schema to use."))
            continue
        message, expect_invalid = parts[0], parts[1] == "invalid"
        if message not in schemas:
            errors.append((path, f"No schema found at contracts/schemas/{message}{SUFFIX}."))
            continue
        sample = load_json(path, errors)
        if sample is None:
            continue
        validator = Draft202012Validator(schemas[message][1], registry=registry)
        problems = sorted(validator.iter_errors(sample), key=lambda e: list(e.path))
        checked += 1
        if expect_invalid and not problems:
            errors.append((path, f"Expected this invalid sample to be rejected by {message}{SUFFIX}, but it passed."))
        elif not expect_invalid:
            for problem in problems:
                where = "/".join(str(p) for p in problem.path) or "(root)"
                errors.append((path, f"{where}: {problem.message}"))

    for path, message in errors:
        print(f"::error file={rel(path)}::{message}")
        print(f"  {rel(path)}: {message}", file=sys.stderr)
    if errors:
        print(f"{len(errors)} contract problem(s) found.", file=sys.stderr)
        return 1
    if not schemas and not checked:
        print("No contracts yet; nothing to validate.")
    else:
        print(f"Contracts OK ({len(schemas)} schema(s), {checked} sample(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

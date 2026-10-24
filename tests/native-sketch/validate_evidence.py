"""Validate real native gate output against the repository's wire schemas.

Run with the normal Python test environment (jsonschema/referencing installed),
passing one or more disposable evidence folders produced by the Blender gates.
"""

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


def validate(folders):
    root = Path(__file__).resolve().parents[2]
    schemas = {path.name.removesuffix(".schema.json"): json.loads(path.read_text())
               for path in (root / "contracts/schemas").glob("*.json")}
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema))
                                        for schema in schemas.values())
    count, results = 0, 0
    for folder in folders:
        files = list(folder.glob("*-result.json"))
        assert files, f"No completed gate result in {folder}"
        for path in files:
            assert json.loads(path.read_text())["passed"], path
            results += 1
        for path in folder.glob("*-messages.json"):
            messages = json.loads(path.read_text())
            assert messages, path
            for msg in messages:
                Draft202012Validator(schemas[msg["type"]], registry=registry).validate(msg)
                count += 1
    assert count, "No native messages validated"
    print(json.dumps({"passed": True, "native_results": results, "schema_messages": count}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folders", nargs="+", type=Path)
    validate(parser.parse_args().folders)

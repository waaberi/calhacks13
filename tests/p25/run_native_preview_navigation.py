"""One private fresh background process for installed keymap/native viewport checks."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
from run_native_preview_workflows import (
    bytecode_fingerprint,
    fingerprint,
    outside_workspace,
    private_environment,
)


def classify_result(result):
    """Pending optional observations never mask a failed required assertion."""
    if not result.get("required_passed", False):
        return "failed"
    return "pending" if result.get("pending") else "passed"


def classify_run(result, *, process_exit, sources_unchanged, bytecode_unchanged):
    """An otherwise passing native result cannot override runner isolation gates."""
    if process_exit or not sources_unchanged or not bytecode_unchanged:
        return "failed"
    return classify_result(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = outside_workspace(args.output, os.environ)
    if output.exists():
        raise ValueError("Evidence directory must be new")
    output.mkdir(parents=True)
    # Isolate source-consistency to our inputs; other agents may edit unrelated
    # managed sources while this single bounded native check runs.
    paths = {"addon": root / "blender_addon/spatial_modeling", "tests": Path(__file__).parent}
    catalog = root / "app/Assets/SpatialModeling/Scripts/PreviewShortcutCatalog.cs"
    before = {name: fingerprint(path) for name, path in paths.items()}
    before["catalog"] = {str(catalog): hashlib.sha256(catalog.read_bytes()).hexdigest()}
    bytecode_before = {name: bytecode_fingerprint(path) for name, path in paths.items()}
    profile = output / "profile"
    env = private_environment(profile, os.environ)
    command = [str(args.blender), "--background", "--factory-startup", "--threads", "2", "--python-exit-code", "1",
               "--python", str(root / "tests/p25/native_preview_navigation.py"), "--", "--output", str(output),
               "--private-profile", str(profile)]
    with (output / "navigation.log").open("w", encoding="utf-8") as log:
        done = subprocess.run(command, env=env, cwd=output, stdout=log, stderr=subprocess.STDOUT,
                              timeout=150, check=False,
                              creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
                              if os.name == "nt" else 0)
    result_path = output / "navigation-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    after = {name: fingerprint(path) for name, path in paths.items()}
    after["catalog"] = {str(catalog): hashlib.sha256(catalog.read_bytes()).hexdigest()}
    bytecode_after = {name: bytecode_fingerprint(path) for name, path in paths.items()}
    outcome = classify_run(result, process_exit=done.returncode, sources_unchanged=before == after,
                           bytecode_unchanged=bytecode_before == bytecode_after)
    manifest = {"method": "one factory-startup Blender background process; no GUI/input/socket/VR",
                "git_source": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "inputs_before": before, "input_sources_unchanged": before == after,
                "source_bytecode_unchanged": bytecode_before == bytecode_after,
                "exit": done.returncode, "passed": outcome == "passed", "outcome": outcome,
                "native_outcome": classify_result(result),
                "required_passed": result.get("required_passed", False), "isolation": result.get("isolation"),
                "checks": len(result.get("checks", [])), "shortcuts": len(result.get("shortcuts", [])),
                "optional_checks": len(result.get("optional_checks", [])),
                "matched_shortcuts": sum(entry["matched"] for entry in result.get("shortcuts", [])),
                "panel_fixture": result.get("panel_fixture"),
                "pending": result.get("pending", [])}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"P25_NATIVE_NAVIGATION exit={done.returncode} required_checks={manifest['checks']} "
          f"matched={manifest['matched_shortcuts']}/{manifest['shortcuts']} outcome={manifest['outcome']}", flush=True)
    if manifest["outcome"] == "failed":
        print(result.get("error") or {"failed_required_checks": [entry for entry in result.get("checks", [])
                                                                if not entry["passed"]],
                                      "input_sources_unchanged": before == after,
                                      "source_bytecode_unchanged": bytecode_before == bytecode_after}, flush=True)
        return done.returncode or 1
    if manifest["outcome"] == "pending":
        print(json.dumps({"pending": manifest["pending"]}, indent=2), flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

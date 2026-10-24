"""Isolated native exact-transform/common-modeling gate runner, reusing private process guards."""

import argparse
import json
import os
import shutil
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--unit-scale", required=True, type=float)
    parser.add_argument("--extension", type=Path, help="Optional pinned CAD source; omitted means CAD-free")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = outside_workspace(args.output, os.environ)
    if output.exists():
        raise ValueError("Evidence directory must be new")
    output.mkdir(parents=True)
    paths = {"addon": root / "blender_addon/spatial_modeling", "tests": Path(__file__).parent}
    if args.extension:
        paths["cad_source"] = args.extension.resolve()
    before = {name: fingerprint(path) for name, path in paths.items()}
    bytecode_before = {name: bytecode_fingerprint(path) for name, path in paths.items()}
    manifest = {"method": "background native typed Commands/Leases/Editor; no GUI/input/socket/Player",
                "git_source": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "unit_scale": args.unit_scale, "cad_optional": bool(args.extension), "inputs_before": before, "runs": []}
    extension = output / "private-cad/CAD_Sketcher"
    if args.extension:
        shutil.copytree(args.extension, extension, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for phase in ("create", "reopen"):
        profile = output / ("profile-" + phase)
        env = private_environment(profile, os.environ)
        command = [str(args.blender), "--background", "--factory-startup", "--threads", "2", "--python-exit-code", "1",
                   "--python", str(root / "tests/p25/native_modeling_workflows.py"), "--", "--output", str(output),
                   "--private-profile", str(profile), "--unit-scale", str(args.unit_scale), "--phase", phase]
        if args.extension:
            command += ["--extension", str(extension)]
        with (output / f"{phase}.log").open("w", encoding="utf-8") as log:
            done = subprocess.run(command, env=env, cwd=output, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=180, check=False,
                                  creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
                                  if os.name == "nt" else 0)
        result_path = output / f"modeling-{phase}-result.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
        after = {name: fingerprint(path) for name, path in paths.items()}
        bytecode_after = {name: bytecode_fingerprint(path) for name, path in paths.items()}
        manifest["input_sources_unchanged"] = before == after
        manifest["source_bytecode_unchanged"] = bytecode_before == bytecode_after
        manifest["runs"].append({"phase": phase, "exit": done.returncode, "passed": result.get("passed", False),
                                 "checks": len(result.get("checks", [])), "receipts": len(result.get("receipts", [])),
                                 "isolation": result.get("isolation")})
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"P25_NATIVE_MODELING_WORKFLOWS {phase}: exit={done.returncode} checks={len(result.get('checks', []))} passed={result.get('passed', False)}", flush=True)
        if done.returncode or not result.get("passed") or before != after or bytecode_before != bytecode_after:
            print(result.get("error", "Source/bytecode invariant failed; inspect manifest/log"), flush=True)
            return done.returncode or 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

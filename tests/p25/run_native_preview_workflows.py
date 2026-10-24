"""Run disposable background native workflow gates; no UI/input/network runtime."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def fingerprint(root):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".log")}


def bytecode_fingerprint(root):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.rglob("*.pyc"))
            if path.is_file()}


def private_environment(profile, inherited):
    env = {name: value for name, value in inherited.items() if not name.upper().startswith("BLENDER_USER_")}
    resources = profile / "blender-resources"
    for name, directory in {
        "BLENDER_USER_RESOURCES": resources,
        "BLENDER_USER_CONFIG": resources / "config",
        "BLENDER_USER_SCRIPTS": resources / "scripts",
        "BLENDER_USER_DATAFILES": resources / "datafiles",
        "TEMP": profile / "temp", "TMP": profile / "temp", "TMPDIR": profile / "temp",
    }.items():
        directory.mkdir(parents=True, exist_ok=True)
        env[name] = str(directory)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def outside_workspace(output, environ):
    if not output.is_absolute():
        raise ValueError("--output must be an absolute path before resolving it")
    output = output.resolve()
    if any((part / ".git").exists() or part.name.lower().startswith("onedrive")
           for part in (output, *output.parents)):
        raise ValueError("Evidence must be outside worktrees and OneDrive")
    for name, value in environ.items():
        if name.lower().startswith("onedrive") and value and output.is_relative_to(Path(value).resolve()):
            raise ValueError("Evidence must be outside every configured OneDrive root")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True, type=Path)
    parser.add_argument("--extension", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--unit-scale", type=float, default=1)
    parser.add_argument("--without-cad", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = outside_workspace(args.output, os.environ)
    if output.exists():
        raise ValueError("Choose a new evidence directory; previous results must remain intact")
    output.mkdir(parents=True)
    before = {"addon": fingerprint(root / "blender_addon/spatial_modeling"),
              "cad_source": fingerprint(args.extension.resolve()),
              "test_scripts": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in (Path(__file__), Path(__file__).with_name("native_preview_workflows.py"),
                                            Path(__file__).with_name("native_spatial_gate.py"))}}
    bytecode_before = {"addon": bytecode_fingerprint(root / "blender_addon/spatial_modeling"),
                       "cad_source": bytecode_fingerprint(args.extension.resolve()),
                       "test_scripts": bytecode_fingerprint(Path(__file__).parent)}
    extension = output / "private-cad" / "CAD_Sketcher"
    shutil.copytree(args.extension, extension, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    manifest = {"method": "factory-startup Blender background native operations; no GUI/input/socket/VR",
                "extension_source": str(args.extension.resolve()), "unit_scale": args.unit_scale,
                "git_source": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "source_hashes": {}, "inputs_before": before, "runs": []}
    for path in sorted((root / "blender_addon/spatial_modeling").rglob("*.py")):
        manifest["source_hashes"][path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for phase in ("create", "reopen"):
        profile = output / ("profile-" + phase)
        env = private_environment(profile, os.environ)
        command = [str(args.blender), "--background", "--factory-startup", "--threads", "2", "--python-exit-code", "1",
                   "--python", str(root / "tests/p25/native_preview_workflows.py"), "--",
                   "--extension", str(extension), "--output", str(output), "--phase", phase,
                   "--unit-scale", str(args.unit_scale), "--private-profile", str(profile)]
        if args.without_cad:
            command.append("--without-cad")
        with (output / (phase + ".log")).open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       timeout=180, check=False,
                                       creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
                                       if os.name == "nt" else 0)
        result_path = output / f"preview-{phase}-result.json"
        native_result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
        manifest["runs"].append({"phase": phase, "exit": completed.returncode,
                                 "passed": native_result.get("passed", False),
                                 "checks": len(native_result.get("checks", [])), "log": str(output / (phase + ".log")),
                                 "private_profile": str(profile), "isolation": native_result.get("isolation")})
        after = {"addon": fingerprint(root / "blender_addon/spatial_modeling"),
                 "cad_source": fingerprint(args.extension.resolve()),
                 "test_scripts": {path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                                  for path in before["test_scripts"]}}
        manifest["input_sources_unchanged"] = before == after
        bytecode_after = {"addon": bytecode_fingerprint(root / "blender_addon/spatial_modeling"),
                          "cad_source": bytecode_fingerprint(args.extension.resolve()),
                          "test_scripts": bytecode_fingerprint(Path(__file__).parent)}
        manifest["source_bytecode_unchanged"] = bytecode_before == bytecode_after
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"P25_NATIVE_PREVIEW {phase}: exit={completed.returncode} checks={len(native_result.get('checks', []))} passed={native_result.get('passed', False)}", flush=True)
        if completed.returncode or not native_result.get("passed") or before != after or bytecode_before != bytecode_after:
            print(native_result.get("error", "See native process log"), flush=True)
            return completed.returncode or 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

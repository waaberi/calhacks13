"""Sequential isolated P3 native suite; reuses completed P2.5 engineering."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/p25"))
from run_native_preview_workflows import (
    bytecode_fingerprint,
    fingerprint,
    outside_workspace,
    private_environment,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cad-ui-only", action="store_true")
    args = parser.parse_args()
    out = outside_workspace(args.output, os.environ)
    if out.exists():
        raise ValueError("Evidence output must be new")
    out.mkdir(parents=True)
    paths = {"addon": ROOT / "blender_addon", "tests": ROOT / "tests", "cad": args.extension}
    before = {k: fingerprint(v) for k, v in paths.items()}
    bytecode = {k: bytecode_fingerprint(v) for k, v in paths.items()}
    result = {"method": "isolated background native Blender only", "cases": [], "passed": False}
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
    cases = [("navigation", "run_native_preview_navigation.py", [])]
    for scale in ("1", ".001"):
        for kind, script in (("preview", "run_native_preview_workflows.py"),
                             ("modeling", "run_native_modeling_workflows.py"),
                             ("objects", "run_native_object_actions.py")):
            cases.append((f"{kind}-{scale}", script, ["--extension", str(args.extension), "--unit-scale", scale]))
    if args.cad_ui_only:
        cases = []
    for name, script, extra in cases:
        with (out / (name + ".log")).open("w", encoding="utf-8") as log:
            done = subprocess.run([sys.executable, str(ROOT / "tests/p25" / script), "--blender", str(args.blender),
                "--output", str(out / name), *extra], cwd=ROOT, env=env, stdout=log,
                stderr=subprocess.STDOUT, timeout=400, check=False)
        result["cases"].append({"name": name, "exit": done.returncode})
        print(name, done.returncode, flush=True)
    for scale in ("1", ".001"):
        folder = out / ("cad-ui-" + scale)
        folder.mkdir()
        extension = folder / "cad/CAD_Sketcher"
        shutil.copytree(args.extension, extension, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
        for phase in ("create", "reopen"):
            profile = folder / (phase + "-profile")
            native_env = private_environment(profile, env)
            with (folder / (phase + ".log")).open("w", encoding="utf-8") as log:
                done = subprocess.run([str(args.blender), "--background", "--factory-startup", "--threads", "2",
                    "--python-exit-code", "1", "--python", str(ROOT / "tests/p3/native_ui.py"), "--",
                    "--output", str(folder), "--extension", str(extension), "--unit-scale", scale,
                    "--phase", phase, "--require-history"], cwd=profile, env=native_env, stdout=log,
                    stderr=subprocess.STDOUT, timeout=180, check=False,
                    creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
                    if os.name == "nt" else 0)
            result["cases"].append({"name": f"cad-ui-{scale}-{phase}", "exit": done.returncode})
            print(f"cad-ui-{scale}-{phase}", done.returncode, flush=True)
            if done.returncode:
                break
    result.update(sources_unchanged=before == {k: fingerprint(v) for k, v in paths.items()},
                  bytecode_unchanged=bytecode == {k: bytecode_fingerprint(v) for k, v in paths.items()},
                  sources_before=before)
    result["passed"] = not any(c["exit"] for c in result["cases"]) and result["sources_unchanged"] and result["bytecode_unchanged"]
    (out / "manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Run two disposable background Blenders, with private profiles and no runtime takeover."""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
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
    parser.add_argument("--blender", required=True, type=Path)
    parser.add_argument("--extension", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = outside_workspace(args.output, os.environ)
    if output.exists():
        raise ValueError("Choose a new output directory; preserve prior failures")
    output.mkdir(parents=True)
    paths = {"addon": ROOT / "blender_addon", "tests": ROOT / "tests", "cad": args.extension}
    before = {k: fingerprint(v) for k, v in paths.items()}
    bytecode = {k: bytecode_fingerprint(v) for k, v in paths.items()}
    extension = output / "cad/CAD_Sketcher"
    shutil.copytree(args.extension, extension, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
    token = secrets.token_hex(32)  # inherited only in private child environments
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == "nt" else 0
    script = Path(__file__).parent
    processes, exits = {}, {}
    manifest = {"method": "two background Blender processes; no OS input/GUI/Player/helper",
                "source": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "runtime_acceptance": False, "production_replaced": False, "passed": False}
    try:
        with (output / "authority.log").open("w", encoding="utf-8") as log:
            env = private_environment(output / "authority-profile", os.environ)
            env["P3_PROTOTYPE_TOKEN"] = token
            cmd = [str(args.blender), "--background", "--factory-startup", "--threads", "2",
                   "--python-exit-code", "1", "--python", str(script / "authority_host.py"),
                   "--", "--output", str(output), "--extension", str(extension)]
            authority = subprocess.Popen(cmd, cwd=output, env=env, stdout=log,
                                         stderr=subprocess.STDOUT, creationflags=flags)
            processes["authority"] = authority.pid
            deadline = time.monotonic() + 45
            while not (output / "ready.json").is_file():
                if authority.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Private authority failed to start; see preserved log")
                time.sleep(.05)
            with (output / "mirror.log").open("w", encoding="utf-8") as mirror_log:
                env = private_environment(output / "mirror-profile", os.environ)
                env["P3_PROTOTYPE_TOKEN"] = token
                client = subprocess.run([str(args.blender), "--background", "--factory-startup", "--threads", "2",
                    "--python-exit-code", "1", "--python", str(script / "authority_mirror.py"),
                    "--", "--output", str(output)], cwd=output, env=env, stdout=mirror_log,
                    stderr=subprocess.STDOUT, timeout=120, check=False, creationflags=flags)
                exits["mirror"] = client.returncode
            (output / "stop.signal").touch()
            exits["authority"] = authority.wait(timeout=15)
            if any(exits.values()):
                raise RuntimeError("Private prototype failed; inspect native logs/results")
            result = json.loads((output / "mirror-result.json").read_text())
            native = json.loads((output / "authority-result.json").read_text())
            assert result["passed"] and abs(native["raw_cube_x_m"] - .01) < 1e-7 and native["child_exists"]
            assert not native["leases"] and len(native["sketches"]) == 1
            manifest["passed"] = True
            manifest["checks"] = len(result["checks"])
            manifest["bypasses"] = result["bypasses"]
    finally:
        if "authority" in locals() and authority.poll() is None:
            (output / "stop.signal").touch()
            try:
                exits["authority"] = authority.wait(timeout=15)
            except subprocess.TimeoutExpired:
                authority.terminate()  # only the exact private child created above
                exits["authority"] = authority.wait(timeout=10)
        manifest.update(processes=processes, exits=exits, sources_before=before,
            sources_unchanged=before == {k: fingerprint(v) for k, v in paths.items()},
            bytecode_unchanged=bytecode == {k: bytecode_fingerprint(v) for k, v in paths.items()})
        manifest["passed"] &= manifest["sources_unchanged"] and manifest["bytecode_unchanged"]
        manifest["result_hashes"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in output.glob("*-result.json")}
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("P3_AUTHORITY_PROTOTYPE", "PASS" if manifest["passed"] else "FAIL", flush=True)
    return 0 if manifest["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

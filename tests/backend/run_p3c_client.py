"""Run isolated real CAD Host and solver-free Client, then fresh native reopen."""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--host-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--faults-only", action="store_true",
                        help="Run independent baseline/fault/ownership/delete gates; no dimension/reopen claim")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scripts = Path(__file__).parent
    host_root = args.host_root.resolve()
    (output / "host-source-hashes.json").write_text(json.dumps({str(p.relative_to(host_root)):
        hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (host_root / "blender_addon/spatial_modeling").rglob("*.py")}, indent=2))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for phase in (("create",) if args.faults_only else ("create", "reopen")):
        with tempfile.TemporaryDirectory(prefix="p3c-peer-") as temporary:
            folder = Path(temporary)
            config = {"token": secrets.token_hex(24), "phase": phase, "output": str(output),
                      "extension": str(args.extension.resolve()), "host_root": str(host_root),
                      "faults_only": args.faults_only}
            (folder / "config.json").write_text(json.dumps(config))
            host_temp, client_temp = folder / "host-temp", folder / "client-temp"
            host_temp.mkdir()
            client_temp.mkdir()
            env = {**os.environ, "BLENDER_USER_RESOURCES": str(folder / "host-resources"),
                   "TEMP": str(host_temp), "TMP": str(host_temp)}
            with (output / f"{phase}-host.log").open("w", encoding="utf-8") as stream:
                host = subprocess.Popen([args.blender, "--background", "--factory-startup",
                    "--python-exit-code", "1", "--python", str(scripts / "p3c_client_host.py"),
                    "--", str(folder)], env=env, stdout=stream, stderr=subprocess.STDOUT,
                    creationflags=flags)
                try:
                    deadline = time.monotonic() + 50
                    while not (folder / "ready.json").exists():
                        if host.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError(f"{phase} host startup failed; see preserved log")
                        time.sleep(.1)
                    (output / f"{phase}-ready.json").write_bytes((folder / "ready.json").read_bytes())
                    env.update(BLENDER_USER_RESOURCES=str(folder / "client-resources"),
                               TEMP=str(client_temp), TMP=str(client_temp))
                    client = subprocess.run([args.blender, "--background", "--factory-startup",
                        "--python-exit-code", "1", "--python", str(scripts / "p3c_client_check.py"),
                        "--", str(folder)], env=env, capture_output=True, text=True, timeout=120,
                        check=False, creationflags=flags)
                    (output / f"{phase}-client.log").write_text(client.stdout + client.stderr, encoding="utf-8")
                    for name in ("host-result.json", "client-result.json", "host-error.txt", "client-error.txt"):
                        if (folder / name).exists():
                            (output / f"{phase}-{name}").write_bytes((folder / name).read_bytes())
                    if client.returncode or not (folder / "client-result.json").exists():
                        raise RuntimeError(f"{phase} Client proof failed; see preserved logs")
                    host.wait(timeout=12)
                    if host.returncode:
                        raise RuntimeError(f"{phase} native host failed at shutdown")
                finally:
                    if host.poll() is None:
                        host.terminate()  # Only this freshly launched isolated test process.
                        host.wait(timeout=10)
    if args.faults_only:
        print(json.dumps({"focused_fault_checks_passed": True, "dimensions": "not run",
                          "fresh_native_reopen": "not run", "fresh_mirror_reopen": "not run"}))
        return
    with tempfile.TemporaryDirectory(prefix="p3c-peer-reopen-") as temporary:
        env = {**os.environ, "BLENDER_USER_RESOURCES": str(Path(temporary) / "resources"),
               "TEMP": temporary, "TMP": temporary}
        result = subprocess.run([args.blender, "--background", "--factory-startup",
            "--python-exit-code", "1", "--python", str(scripts / "p3c_client_reopen.py"),
            "--", str(output)], env=env, capture_output=True, text=True, timeout=40,
            check=False, creationflags=flags)
        (output / "mirror-reopen.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("Fresh mirror metadata reopen failed; see preserved log")
    print(json.dumps({"passed": True, "actual_host_client_pairs": 2,
                      "fresh_native_reopen": True, "fresh_mirror_reopen": True}))


if __name__ == "__main__":
    main()

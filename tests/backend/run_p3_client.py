"""Run two isolated real Blenders; preserve outputs, keep credentials temporary."""
import argparse
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
    parser.add_argument("--output", required=True)
    parser.add_argument("--scale", type=float, choices=(1.0, .001), required=True)
    parser.add_argument("--ownership", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).parent
    with tempfile.TemporaryDirectory(prefix="p3-client-") as tmp:
        folder = Path(tmp)
        (folder / "config.json").write_text(json.dumps({"token": secrets.token_hex(24),
            "scale": args.scale, "ownership": args.ownership}))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with (output / "host.log").open("w", encoding="utf-8") as log:
            (folder / "host-temp").mkdir()
            (folder / "client-temp").mkdir()
            env = {**os.environ, "BLENDER_USER_RESOURCES": str(folder / "host-resources"),
                   "TEMP": str(folder / "host-temp"), "TMP": str(folder / "host-temp")}
            host = subprocess.Popen([args.blender, "--factory-startup", "--python",
                str(scripts / "p3_client_host_check.py"), "--", str(folder)],
                env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
            try:
                deadline = time.monotonic() + 40
                while not (folder / "ready.json").exists():
                    if host.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Isolated host did not start; see host.log")
                    time.sleep(.1)
                env["BLENDER_USER_RESOURCES"] = str(folder / "client-resources")
                env["TEMP"] = env["TMP"] = str(folder / "client-temp")
                client = subprocess.run([args.blender, "--background", "--factory-startup",
                    "--python-exit-code", "1", "--python", str(scripts / "p3_client_operator_check.py"),
                    "--", str(folder)], env=env, capture_output=True, text=True, timeout=120,
                    creationflags=flags, check=False)
                (output / "client.log").write_text(client.stdout + client.stderr, encoding="utf-8")
                for name in ("host-result.json", "client-result.json", "host-error.txt", "client-error.txt"):
                    source = folder / name
                    if source.exists():
                        (output / name).write_bytes(source.read_bytes())
                if client.returncode != 0 or not (folder / "client-result.json").exists():
                    raise RuntimeError("Production Client operator test failed; see preserved logs")
                host.wait(timeout=12)
                print((output / "client-result.json").read_text())
            finally:
                if host.poll() is None:
                    host.terminate()  # Only our freshly launched process.
                    host.wait(timeout=10)


if __name__ == "__main__":
    main()

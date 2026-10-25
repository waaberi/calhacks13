"""Run isolated two-Blender checks without using VR or the running P1 host."""
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
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).parent
    with tempfile.TemporaryDirectory(prefix="p2-isolated-") as tmp:
        folder = Path(tmp)
        # Temporary test-only secret never leaves this directory or appears in logs/arguments.
        (folder / "config.json").write_text(json.dumps({"token": secrets.token_hex(24)}))
        startup = None
        if os.name == "nt":
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
        with (output / "host.log").open("w", encoding="utf-8") as log:
            (folder / "host-temp").mkdir()
            (folder / "mirror-temp").mkdir()
            env = {**os.environ, "BLENDER_USER_RESOURCES": str(folder / "host-resources"),
                   "TEMP": str(folder / "host-temp"), "TMP": str(folder / "host-temp")}
            process = subprocess.Popen([args.blender, "--factory-startup", "--python",
                str(scripts / "p2_host_check.py"), "--", str(folder)],
                env=env, stdout=log, stderr=subprocess.STDOUT, startupinfo=startup)
            try:
                deadline = time.monotonic() + 35
                while not (folder / "ready.json").exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Isolated host did not start; see host.log")
                    time.sleep(.1)
                env["BLENDER_USER_RESOURCES"] = str(folder / "mirror-resources")
                env["TEMP"] = env["TMP"] = str(folder / "mirror-temp")
                mirror = subprocess.run([args.blender, "--background", "--factory-startup",
                    "--python-exit-code", "1", "--python", str(scripts / "p2_mirror_check.py"),
                    "--", str(folder)], check=False, env=env, capture_output=True, text=True, timeout=130)
                (output / "mirror.log").write_text(mirror.stdout + mirror.stderr, encoding="utf-8")
                for filename in ("host-result.json", "mirror-result.json", "host-error.txt", "mirror-error.txt",
                                 "native-before.json", "native-after.json"):
                    source = folder / filename
                    if source.exists():
                        (output / filename).write_bytes(source.read_bytes())
                if mirror.returncode != 0 or not (output / "mirror-result.json").exists():
                    raise RuntimeError("P2 mirror test failed; see evidence logs")
                process.wait(timeout=12)
                print((output / "mirror-result.json").read_text())
            finally:
                if process.poll() is None:
                    process.terminate()  # Only this freshly launched isolated process.
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()

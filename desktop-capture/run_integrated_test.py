"""Launch the assembled integration package after the accepted Player handoff.

Default mode only validates the package. --launch is an explicit runtime action.
Never closes another application or opens a personal Blender document.
"""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from launch import player_processes
from launch_p25 import input_preflight, native_preflight, validate_binding


def free_port(port):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def wait_for(check, process, seconds=60):
    deadline = time.monotonic() + seconds
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Owned process exited {process.returncode}; inspect the session logs")
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError, RuntimeError) as error:
            last_error = error
        time.sleep(.25)
    raise RuntimeError(f"Readiness timed out: {last_error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args()
    package = args.package.resolve()
    config = json.loads((package / "test-config.json").read_text())
    required = ["SpatialModeling.exe", "SpatialModeling_Data/Managed/Assembly-CSharp.dll",
                "support/bootstrap_p25.py", "support/capture_helper.py", "support/launch_p25.py",
                "addon/spatial_modeling/__init__.py", "CAD_Sketcher/blender_manifest.toml",
                "CAD_Sketcher/wheels/slvs-3.2-cp313-cp313-win_amd64.whl", "reference.blend",
                "rollback-p2/SpatialModeling.exe"]
    for relative in required:
        if not (package / relative).is_file():
            raise RuntimeError(f"Incomplete package: {relative}")
    manifest = json.loads((package / "package-manifest.json").read_text())
    for relative, expected in manifest["files"].items():
        path = (package / relative).resolve()
        if not path.is_relative_to(package) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Package hash mismatch: {relative}")
    if not args.launch:
        print("Package complete. Accepted session unchanged. Launch requires its coordinated handoff.")
        return
    running = player_processes("SpatialModeling.exe")
    if running:
        raise RuntimeError(f"Existing Player {running}: coordinate its clean handoff first; nothing started")
    host_port, capture_port = config["host_port"], config["capture_port"]
    free_port(host_port)
    free_port(capture_port)
    session = Path(config["session_parent"]) / datetime.now(UTC).strftime("integrated-%Y%m%dT%H%M%SZ")
    session.mkdir(parents=True, exist_ok=False)
    native_session = session / "native"
    env = {name: value for name, value in os.environ.items() if not name.upper().startswith("BLENDER_USER_")}
    env.update(BLENDER_USER_RESOURCES=str(native_session / "blender-resources"),
               PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(package / "python-deps"))
    native_log = (session / "blender.log").open("w", encoding="utf-8")
    native = subprocess.Popen([config["blender"], "--factory-startup", "--disable-autoexec",
                               "--python", str(package / "support/bootstrap_p25.py"), "--",
                               "--session-dir", str(native_session), "--blend", str(package / "reference.blend"),
                               "--addon-root", str(package / "addon/spatial_modeling"),
                               "--host-port", str(host_port), "--cad-extension", str(package / "CAD_Sketcher")],
                              env=env, stdout=native_log, stderr=subprocess.STDOUT)
    bootstrap = native_session / "bootstrap.json"
    def host_ready():
        if not bootstrap.is_file():
            return None
        record = json.loads(bootstrap.read_text())
        return record if record.get("status") == "host_ready" else None

    identity = wait_for(host_ready, native)
    if identity.get("status") != "host_ready" or identity.get("process_id") != native.pid or not identity.get("cad_available"):
        raise RuntimeError("Private native host/CAD did not report ready")
    from capture_helper import Windows
    windows = wait_for(lambda: [w for w in Windows().windows() if w["pid"] == native.pid], native)
    if len(windows) != 1:
        raise RuntimeError("Expected one private main Blender window; no arbitrary window was selected")
    helper_log = (session / "capture.log").open("w", encoding="utf-8")
    helper = subprocess.Popen([sys.executable, str(package / "support/capture_helper.py"),
                               "--port", str(capture_port), "--window", str(windows[0]["hwnd"]), "--enable-input",
                               *(["--clear-text"] if config.get("clear_text", False) else [])],
                              env=env, stdout=helper_log, stderr=subprocess.STDOUT,
                              creationflags=subprocess.CREATE_NO_WINDOW)

    def binding():
        welcome, state = native_preflight(host_port)
        return validate_binding(welcome, state, input_preflight(capture_port))

    report = wait_for(binding, helper, seconds=45)
    (session / "prepared.json").write_text(json.dumps({"native_pid": native.pid, "helper_pid": helper.pid,
                                                      "binding": report}, indent=2))
    result = subprocess.run([sys.executable, str(package / "support/launch_p25.py"),
                             "--host-port", str(host_port), "--capture-port", str(capture_port),
                             "--player", str(package / "SpatialModeling.exe"),
                             "--session-dir", str(session / "player")], env=env, check=False)
    if result.returncode:
        raise RuntimeError(f"Player launcher refused: {result.returncode}; private native/helper retained for inspection")
    print(f"Integrated VR test session: {session}. Original P2 native/helper and personal files preserved.")


if __name__ == "__main__":
    main()

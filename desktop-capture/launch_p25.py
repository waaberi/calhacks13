"""Preflight an explicitly isolated P2.5 host/helper, then launch its Player.

Does not install add-ons, start Blender/helpers, select/focus windows, send input,
save documents or stop another Player. --diagnose performs read-only preflight.
"""

import argparse
import json
import os
import socket
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

from launch import player_processes


def isolated_port(value):
    port = int(value)
    if not 1 <= port <= 65535 or port in (8765, 8766):
        raise argparse.ArgumentTypeError("Use an explicit port outside P2's default 8765/8766")
    return port


def envelope(kind, payload):
    return {"v": 1, "type": kind, "id": uuid.uuid4().hex, "payload": payload}


def native_preflight(port):
    """Join briefly and query state. Never request editing permission or mutation."""
    hello = envelope("hello", {"role": "vr", "name": "P2.5 read-only preflight",
                               "app": {"name": "p25-preflight", "version": "0.1.0"}})
    query = envelope("preview.state.query", {})
    welcome = None
    deadline = time.monotonic() + 6
    with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
        connection.sendall(json.dumps(hello).encode() + b"\n")
        with connection.makefile("rb") as stream:
            while time.monotonic() < deadline:
                line = stream.readline(4 * 1024 * 1024 + 1)
                if not line or len(line) > 4 * 1024 * 1024:
                    raise RuntimeError("Native preflight closed or exceeded the message size limit")
                msg = json.loads(line)
                if msg.get("type") == "error":
                    raise RuntimeError("Native preflight refused: " + str(msg.get("payload", {}).get("code")))
                if msg.get("type") == "welcome" and msg.get("re") == hello["id"]:
                    welcome = msg["payload"]
                    connection.sendall(json.dumps(query).encode() + b"\n")
                if msg.get("type") == "preview.state" and msg.get("re") == query["id"]:
                    if welcome is None:
                        raise RuntimeError("Host state arrived before a matching welcome")
                    return welcome, msg["payload"]
    raise RuntimeError("Native preflight timed out waiting for P2.5 preview state")


def input_preflight(port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/input/state", timeout=2) as response:
        data = response.read(256 * 1024 + 1)
    if len(data) > 256 * 1024:
        raise RuntimeError("Input helper state exceeded the size limit")
    return json.loads(data)


def validate_binding(welcome, native, capture):
    if not all(isinstance(value, dict) for value in (welcome, native, capture)):
        raise RuntimeError("Native/helper preflight must return JSON objects")
    if welcome.get("can_edit") is not True:
        raise RuntimeError("Native host did not admit an editable local VR connection")
    if welcome.get("capabilities", {}).get("preview_spatial") is not True:
        raise RuntimeError("Host does not advertise the P2.5 preview bridge; use this branch's add-on")
    document = welcome.get("document", {})
    expected = {"session_id": welcome.get("session_id"), "host_epoch": welcome.get("host_epoch"),
                "document_id": document.get("id"), "open_epoch": document.get("open_epoch")}
    if any(not value or native.get(name) != value for name, value in expected.items()):
        raise RuntimeError("Native preview state does not match its welcomed document/session")
    if capture.get("enabled") is not True or capture.get("ready") is not True:
        raise RuntimeError("Start the isolated helper with --enable-input and select a fresh captured window: "
                           + str(capture.get("reason", "unavailable")))
    native_pid = native.get("process_id")
    selection = capture.get("selection")
    if (isinstance(native_pid, bool) or not isinstance(native_pid, int) or native_pid <= 0
            or not isinstance(selection, dict) or selection.get("pid") != native_pid
            or not isinstance(selection.get("hwnd"), int) or isinstance(selection.get("hwnd"), bool)):
        raise RuntimeError("Capture selection must belong to the connected P2.5 native host process")
    # Deliberately omit the helper's input token and private document path.
    return {"native_process_id": native_pid, "capture_hwnd": selection["hwnd"],
            "native_cad_available": welcome.get("capabilities", {}).get("sketch") is True,
            "focused": capture.get("focused") is True, "binding_verified": True,
            "runtime_acceptance": False}


def safe_session_directory(path):
    path = path.resolve()
    for directory in (path, *path.parents):
        if (directory / ".git").exists() or directory.name.lower().startswith("onedrive"):
            raise ValueError("Session output must be outside Git worktrees and OneDrive")
    if path.exists():
        raise ValueError("Use a new session directory to preserve earlier logs")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-port", type=isolated_port, required=True)
    parser.add_argument("--capture-port", type=isolated_port, required=True)
    parser.add_argument("--player", type=Path, help="Separately built P2.5 SpatialModeling.exe")
    parser.add_argument("--session-dir", type=Path, help="New external session directory")
    parser.add_argument("--diagnose", action="store_true", help="Read-only state/binding check; never launches anything")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This launcher requires Windows")
    if args.host_port == args.capture_port:
        parser.error("Host and capture ports must be distinct")
    try:
        welcome, native = native_preflight(args.host_port)
        report = validate_binding(welcome, native, input_preflight(args.capture_port))
        report.update(host_port=args.host_port, capture_port=args.capture_port)
        if args.diagnose:
            print(json.dumps(report, indent=2))
            return
        if args.player is None or not args.player.is_file() or args.player.suffix.lower() != ".exe":
            parser.error("--player must point to the separately built P2.5 Windows EXE")
        if args.session_dir is None:
            parser.error("--session-dir is required for launch")
        session = safe_session_directory(args.session_dir)
        running = set(player_processes("SpatialModeling.exe")) | set(player_processes(args.player.name))
        if running:
            parser.error(f"An existing Player is running (PID {sorted(running)}); coordinate its clean handoff before P2.5")
        env = os.environ.copy()
        env.update(CALHACKS_P25="1", CALHACKS_HOST_PORT=str(args.host_port),
                   CALHACKS_CAPTURE_PORT=str(args.capture_port))
        session.mkdir(parents=True)
        # Recheck immediately before spawn, after filesystem/preflight work.
        if player_processes("SpatialModeling.exe") or player_processes(args.player.name):
            raise RuntimeError("Another Player appeared during preflight; no P2.5 Player launched")
        player = subprocess.Popen([str(args.player.resolve()), "-logFile", str(session / "player.log"),
                                   "-screen-fullscreen", "0", "-screen-width", "1280", "-screen-height", "800"],
                                  cwd=args.player.resolve().parent, env=env)
        report["player_pid"] = player.pid
        (session / "launch.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"P2.5 Player launched; use Focus Blender inside its UI. Logs: {session}")
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()

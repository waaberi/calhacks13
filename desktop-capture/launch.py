"""Start/attach Blender Host, selected-window capture and the USB Windows VR app."""

import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from ctypes import wintypes
from pathlib import Path


def ping_host():
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=2) as connection:
            request_id = uuid.uuid4().hex
            message = {"v": 1, "type": "ping", "id": request_id, "payload": {}}
            connection.sendall(json.dumps(message).encode() + b"\n")
            with connection.makefile("rb") as stream:
                reply = json.loads(stream.readline(16 * 1024))
            return reply.get("type") == "pong" and reply.get("re") == request_id
    except (OSError, ValueError):
        return False


def capture_status(path="/status"):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:8766" + path, timeout=2) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return None


def player_processes(executable_name):
    """Include windowless/hung Players; never launch a competing XR instance."""
    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        result = []
        more = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while more:
            if entry.szExeFile.casefold() == executable_name.casefold():
                result.append(entry.th32ProcessID)
            more = kernel.Process32NextW(handle, ctypes.byref(entry))
        return result
    finally:
        kernel.CloseHandle(handle)


def verify_existing_selection(requested, selected):
    if requested is not None and (not selected or selected.get("hwnd") != requested):
        raise RuntimeError(
            "The running capture helper has not confirmed the requested Blender window. "
            "Select it in the picker (restart an older helper lacking /selection), then retry."
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--player", type=Path, help="Built SpatialModeling.exe (not needed with --diagnose)"
    )
    parser.add_argument("--blender", type=Path, help="Blender executable, if no running Host")
    parser.add_argument("--blend", type=Path, help="Reference .blend to open in a separate window")
    parser.add_argument(
        "--window", type=int, help="Explicit selected Blender HWND (otherwise choose in helper)"
    )
    parser.add_argument(
        "--session-dir", type=Path, help="New local session directory outside the repo"
    )
    parser.add_argument(
        "--diagnose", action="store_true", help="Read-only dependency/connection diagnostic"
    )
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This launcher requires Windows")
    if args.diagnose:
        from capture_helper import Windows

        print(
            json.dumps(
                {
                    "python": sys.version.split()[0],
                    "player_exists": bool(args.player and args.player.is_file()),
                    "native_ping": ping_host(),
                    "capture": capture_status(),
                    "blender_windows": Windows().windows(),
                },
                indent=2,
            )
        )
        return
    if args.player is None or not args.player.is_file():
        parser.error("--player must point to a built Windows EXE")
    players = player_processes(args.player.name)
    if players:
        parser.error(f"A Player is already running (PID {players}). Close it cleanly before relaunching.")
    existing_capture = capture_status()
    if existing_capture is not None:
        verify_existing_selection(args.window, capture_status("/selection"))
    script_dir = Path(__file__).resolve().parent
    repo = script_dir.parent
    session = (
        args.session_dir.resolve()
        if args.session_dir
        else Path(tempfile.mkdtemp(prefix="calhacks-p1-"))
    )
    if session == repo or repo in session.parents:
        parser.error("--session-dir must be outside the repository")
    session.mkdir(parents=True, exist_ok=True)
    logs = []

    def spawn(command, name, env=None):
        log = (session / (name + ".log")).open("w", encoding="utf-8")
        logs.append(log)
        return subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    record = {"host": "attached", "session": str(session), "player": str(args.player.resolve())}
    if not ping_host():
        if (
            not args.blender
            or not args.blender.is_file()
            or not args.blend
            or not args.blend.is_file()
        ):
            parser.error(
                "No responding Blender Host. Supply --blender and --blend, or start the existing Host."
            )
        env = os.environ.copy()
        resources = session / "blender-resources"
        resources.mkdir(exist_ok=True)
        env["BLENDER_USER_RESOURCES"] = str(resources)
        addon = session / "spatial_modeling.zip"
        with zipfile.ZipFile(addon, "w", zipfile.ZIP_DEFLATED) as archive:
            package = repo / "blender_addon" / "spatial_modeling"
            for source in package.rglob("*"):
                if (
                    source.is_file()
                    and "__pycache__" not in source.parts
                    and source.suffix != ".pyc"
                ):
                    archive.write(source, source.relative_to(package))
        host = spawn(
            [
                str(args.blender),
                "--factory-startup",
                "--python",
                str(script_dir / "bootstrap_blender.py"),
                "--",
                "--addon",
                str(addon),
                "--blend",
                str(args.blend),
            ],
            "blender",
            env,
        )
        record.update(host="launched separate Blender", host_pid=host.pid)
        until = time.monotonic() + 60
        while not ping_host():
            if host.poll() is not None or time.monotonic() > until:
                raise RuntimeError(
                    "Blender Host did not start; inspect the session's blender.log. Existing Blender windows were not changed."
                )
            time.sleep(0.5)
    if capture_status() is None:
        command = [sys.executable, str(script_dir / "capture_helper.py")]
        if args.window:
            command += ["--window", str(args.window)]
        helper = spawn(command, "capture")
        record["capture_pid"] = helper.pid
    print(
        "Native Blender ping PASS. Select the intended Blender window in the capture helper.",
        flush=True,
    )
    until = time.monotonic() + 180
    while True:
        status = capture_status()
        if status and status.get("state") == "capturing":
            break
        if time.monotonic() > until:
            raise RuntimeError(
                "No selected live capture after 180 seconds. Helper remains open; choose Blender, then rerun launcher."
            )
        time.sleep(0.25)
    record["capture_status_at_launch"] = status
    selection = capture_status("/selection")
    verify_existing_selection(args.window, selection)
    record["capture_selection_at_launch"] = selection
    player_log = session / "player.log"
    player = spawn(
        [
            str(args.player.resolve()),
            "-logFile",
            str(player_log),
            "-screen-fullscreen",
            "0",
            "-screen-width",
            "1280",
            "-screen-height",
            "800",
        ],
        "player-console",
    )
    record["player_pid"] = player.pid
    (session / "launch.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(
        f"P1 app launched. USB Link: A/X shows or hides Blender; B/Y recenters. Logs: {session}",
        flush=True,
    )
    for log in logs:
        log.close()
    # Do not kill Blender or save/close a user's document when launcher exits.


if __name__ == "__main__":
    main()

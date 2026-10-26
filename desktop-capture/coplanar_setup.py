"""Coplanar desktop setup. No chat history, saved PID, or developer paths required."""

import argparse
import hashlib
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


class SetupError(RuntimeError):
    pass


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def local_data():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "Coplanar"


def discover_blender():
    import shutil

    candidates = list(Path(os.environ.get("ProgramFiles", "C:/Program Files")).glob(
        "Blender Foundation/Blender 5.2*/blender.exe"))
    on_path = shutil.which("blender")
    if on_path:
        candidates.append(Path(on_path))
    return next((str(path) for path in candidates if path.is_file()), "")


def validate_package(package):
    """Verify shipped files before executing them; never use test-config paths."""
    package = Path(package).resolve()
    manifest = read_json(package / "package-manifest.json")
    files = manifest.get("files", {})
    required = ("SpatialModeling.exe", "SpatialModeling_Data/Managed/Assembly-CSharp.dll",
                "support/bootstrap_p25.py", "addon/spatial_modeling/__init__.py", "reference.blend")
    for name in required:
        if name not in files:
            raise SetupError("Coplanar installation is incomplete. Choose a complete Coplanar folder.")
    for name, expected in files.items():
        path = (package / name).resolve()
        if not path.is_relative_to(package) or not path.is_file():
            raise SetupError("Coplanar installation is incomplete: " + name)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected:
            raise SetupError("Coplanar installation needs repair: " + name)
    return package


def available_port():
    while True:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        if port not in (8765, 8766, 8767):
            return port


def wait_ready(check, process=None, seconds=45):
    deadline = time.monotonic() + seconds
    last = "Starting"
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise SetupError("A Coplanar component stopped. Open setup logs for details.")
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError, RuntimeError) as exc:
            last = str(exc)
        time.sleep(.3)
    raise SetupError("Connection is not ready. Retry after checking Blender. " + last)


def selected_main_window(windows, native_pid, hwnd=None):
    candidates = [window for window in windows if window["pid"] == native_pid
                  and (hwnd is None or window["hwnd"] == hwnd)]
    if len(candidates) != 1:
        raise SetupError("The connected Blender window has closed or is ambiguous. Reconnect your session.")
    return candidates[0]


class Controller:
    def __init__(self, data=None, notify=lambda message: None):
        self.data = Path(data) if data else local_data()
        self.notify = notify
        self.state = self.data / "session.json"
        self.children = []

    def stamp(self, pid):
        from capture_helper import Windows
        from input_bridge import WindowsInput

        return WindowsInput(Windows()).process_stamp(pid)

    def binding(self, record):
        from launch_p25 import input_preflight, native_preflight, validate_binding

        welcome, native = native_preflight(record["host_port"])
        capture = input_preflight(record["capture_port"])
        report = validate_binding(welcome, native, capture)
        if (report["native_process_id"] != record["native_pid"]
                or report["capture_hwnd"] != record["hwnd"]
                or capture.get("helper_pid") != record["helper_pid"]):
            raise SetupError("The screen feed belongs to another Blender session. Reconnect Coplanar.")
        return report

    def window(self, record):
        from capture_helper import Windows

        api = Windows()
        window = selected_main_window(api.windows(), record["native_pid"], record.get("hwnd"))
        if record.get("native_started"):
            from input_bridge import WindowsInput
            # inspect() requires a drawable/non-minimized window. Identity must
            # be checked independently so Restore can repair that very state.
            if WindowsInput(api).process_stamp(window["pid"]) != record["native_started"]:
                raise SetupError("This Blender session has ended. Its old window cannot be reused.")
        return api, window

    def restore_blender(self, record):
        import ctypes
        from ctypes import wintypes

        api, window = self.window(record)
        api.u.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        api.u.ShowWindowAsync.restype = wintypes.BOOL
        # Only restore the verified connected HWND. A maximized window stays maximized.
        if api.u.IsIconic(window["hwnd"]):
            api.u.ShowWindowAsync(window["hwnd"], 9)  # SW_RESTORE
        api.u.SetForegroundWindow.argtypes = [wintypes.HWND]
        api.u.SetForegroundWindow.restype = wintypes.BOOL
        api.u.SetForegroundWindow(window["hwnd"])
        return window

    def spawn(self, command, log, env):
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w", encoding="utf-8") as stream:
            process = subprocess.Popen(command, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.children.append(process)
        return process

    def start(self, settings, new=False):
        from launch import player_processes

        # Never close/restart an existing Player to work around a mismatch.
        players = player_processes("SpatialModeling.exe")
        record = read_json(self.state) if self.state.is_file() and not new else None
        if players:
            if not record or record.get("player_pid") not in players or len(players) != 1 or new:
                raise SetupError("Coplanar VR is already open. Close its window before starting a different session.")
            if self.stamp(record["player_pid"]) != record.get("player_started"):
                raise SetupError("Another VR session is running. Close it before reconnecting.")
            self.window(record)
            self.restore_blender(record)
            self.binding(record)
            self.notify("Connected to your current Blender session. Enter Quest Link in your headset.")
            return record
        if record and not new:
            try:
                alive = self.stamp(record["native_pid"]) == record.get("native_started")
            except (OSError, RuntimeError):
                alive = False
            if not alive:
                # The prior process ended. Reopen a COPY of its saved work, never a stale HWND.
                saved = Path(record.get("working_copy", ""))
                settings = {**settings, **({"blend": str(saved)} if saved.is_file() else {})}
                record = None
        if record and not new:
            # Refuse stale records instead of silently replacing unsaved work.
            window = self.window(record)[1]
            record["hwnd"] = window["hwnd"]
            self.restore_blender(record)
            self.ensure_capture(record)
        else:
            record = self.create_session(settings)
        return self.launch_player(record)

    def ensure_capture(self, record):
        from launch_p25 import input_preflight

        try:
            capture = input_preflight(record["capture_port"])
        except (OSError, ValueError):
            capture = None
        if capture is not None:
            # An existing helper must match; never redirect another session's input.
            if capture.get("helper_pid") != record.get("helper_pid"):
                raise SetupError("The screen connection is in use by another session. Start a new workspace.")
        else:
            if record.get("helper_pid"):
                try:
                    alive = self.stamp(record["helper_pid"]) == record.get("helper_started")
                except (OSError, RuntimeError):
                    alive = False
                if alive:
                    wait_ready(lambda: self.binding(record), seconds=15)
                    return
            env = {**os.environ, "PYTHONPATH": str(Path(record["package"]) / "python-deps")}
            helper = self.spawn([sys.executable, str(Path(__file__).with_name("capture_helper.py")),
                                 "--port", str(record["capture_port"]), "--window", str(record["hwnd"]),
                                 "--enable-input", "--headless", "--clear-text"],
                                Path(record["session"]) / ("capture-" + uuid.uuid4().hex + ".log"), env)
            record.update(helper_pid=helper.pid, helper_started=self.stamp(helper.pid))
            write_json(self.state, record)
            wait_ready(lambda: self.binding(record), helper)
        wait_ready(lambda: self.binding(record), seconds=15)

    def create_session(self, settings):
        from capture_helper import Windows
        from input_bridge import WindowsInput

        self.notify("Checking Coplanar installation…")
        package = validate_package(settings["package"])
        blender = Path(settings["blender"])
        if not blender.is_file():
            raise SetupError("Choose Blender 5.2 using Browse, then press Start.")
        source = Path(settings.get("blend") or package / "reference.blend").resolve()
        if not source.is_file() or source.suffix.lower() != ".blend":
            raise SetupError("Choose a Blender .blend file, or leave it blank for the starter scene.")
        session = self.data / "sessions" / uuid.uuid4().hex
        session.mkdir(parents=True)
        host_port, capture_port = available_port(), available_port()
        while capture_port == host_port:
            capture_port = available_port()
        native_dir = session / "native"
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("BLENDER_USER_")}
        env.update(BLENDER_USER_RESOURCES=str(native_dir / "blender-resources"),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(package / "python-deps"))
        command = [str(blender), "--factory-startup", "--disable-autoexec", "--python",
                   str(package / "support/bootstrap_p25.py"), "--", "--session-dir", str(native_dir),
                   "--blend", str(source), "--addon-root", str(package / "addon/spatial_modeling"),
                   "--host-port", str(host_port)]
        if (package / "CAD_Sketcher/blender_manifest.toml").is_file():
            command += ["--cad-extension", str(package / "CAD_Sketcher")]
        self.notify("Opening a safe working copy in Blender…")
        native = self.spawn(command, session / "blender.log", env)
        record = {"package": str(package), "session": str(session), "native_pid": native.pid,
                  "native_started": self.stamp(native.pid),
                  "host_port": host_port, "capture_port": capture_port,
                  "working_copy": str(native_dir / "working.blend"), "source": str(source)}
        # Persist partial progress: a failed later step must not spawn another Blender on retry.
        write_json(self.state, {**record, "stage": "blender_starting"})
        bootstrap = native_dir / "bootstrap.json"
        def host_ready():
            data = read_json(bootstrap) if bootstrap.is_file() else {}
            return data if data.get("status") == "host_ready" and data.get("process_id") == native.pid else None
        wait_ready(host_ready, native, seconds=90)
        api = Windows()
        window = wait_ready(lambda: selected_main_window(api.windows(), native.pid), native)
        record.update(hwnd=window["hwnd"], native_started=WindowsInput(api).process_stamp(window["pid"]))
        write_json(self.state, {**record, "stage": "capture_starting"})
        self.notify("Connecting the Blender screen automatically…")
        self.ensure_capture(record)
        record["stage"] = "connected"
        write_json(self.state, record)
        return record

    def launch_player(self, record):
        from launch import player_processes

        if player_processes("SpatialModeling.exe"):
            raise SetupError("Coplanar VR opened during setup. Close it before retrying.")
        self.binding(record)
        package = Path(record["package"])
        # Revalidate before resuming as well as on first launch.
        validate_package(package)
        self.notify("Starting Coplanar VR. Enter Quest Link in your headset…")
        env = {**os.environ, "CALHACKS_P25": "1", "CALHACKS_HOST_PORT": str(record["host_port"]),
               "CALHACKS_CAPTURE_PORT": str(record["capture_port"])}
        # Voice is optional; an absent key never blocks basic Blender setup.
        key = local_data().parent / "CalhacksVR/secrets/gemini.key"
        if key.is_file():
            env["GEMINI_API_KEY_FILE"] = str(key)
            env.setdefault("GEMINI_MODEL", "gemini-3.5-flash-lite")
        if player_processes("SpatialModeling.exe"):
            raise SetupError("Coplanar VR is already open. No second copy was started.")
        player = self.spawn([str(package / "SpatialModeling.exe"), "-logFile",
                             str(Path(record["session"]) / "player.log")],
                            Path(record["session"]) / "player-console.log", env)
        record.update(player_pid=player.pid, player_started=self.stamp(player.pid), stage="vr_starting")
        write_json(self.state, record)
        self.notify("Blender is connected. Put on your headset and enter Quest Link. VR readiness is shown there.")
        return record


def connection_message(record):
    """A fresh capture status is not a claim that a wearer has entered VR."""
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{record["capture_port"]}/status', timeout=2) as response:
        status = json.loads(response.read(256 * 1024))
    if status.get("state") == "capturing":
        return "Blender screen connected. Put on your headset and enter Quest Link to use VR."
    if status.get("state") == "minimized":
        return "The connected Blender is minimized. Press Show connected Blender to restore its screen."
    if status.get("state") == "no_window":
        return "Your connected Blender has closed. Press Start / Reconnect to reopen its last saved file."
    return "Blender screen unavailable. " + str(status.get("message") or "Press Start / Reconnect to retry.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--check", action="store_true", help="Check settings only; never launch applications")
    args = parser.parse_args()
    data = args.data or local_data()
    settings_path = data / "settings.json"
    try:
        settings = read_json(settings_path) if settings_path.is_file() else {}
    except (OSError, ValueError):
        settings = {}
    if args.package:
        settings.setdefault("package", str(args.package.resolve()))
    if not settings.get("blender") or not Path(settings["blender"]).is_file():
        settings["blender"] = discover_blender()
    settings.setdefault("package", str(Path(__file__).resolve().parent.parent))
    if args.check:
        validate_package(settings["package"])
        print(json.dumps({"package_valid": True, "blender_found": Path(settings["blender"]).is_file(),
                          "session_saved": (data / "session.json").is_file(), "applications_started": False}))
        return
    # One setup owner per user, including the final Player launch check.
    import msvcrt

    data.mkdir(parents=True, exist_ok=True)
    launch_lock = (data / "setup.lock").open("a+b")
    launch_lock.seek(0)
    launch_lock.write(b"1")
    launch_lock.flush()
    launch_lock.seek(0)
    try:
        msvcrt.locking(launch_lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        import tkinter as tk
        from tkinter import messagebox

        notice = tk.Tk()
        notice.withdraw()
        messagebox.showinfo("Coplanar", "Coplanar setup is already open. Return to its window to start or reconnect.")
        notice.destroy()
        return
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Coplanar")
    root.geometry("720x440")
    root.minsize(660, 420)
    root.configure(padx=24, pady=20)
    ttk.Label(root, text="Your Blender workspace, in VR", font=("Segoe UI", 20)).pack(anchor="w")
    ttk.Label(root, text="1. Connect your headset in Meta Quest Link.\n2. Press Start. We connect Blender and the screen for you.",
              padding=(0, 12)).pack(anchor="w")
    form = ttk.Frame(root)
    form.pack(fill="x")
    form.columnconfigure(1, weight=1)
    values = {}
    advanced = []
    for row, (key, label, folder) in enumerate((("blend", "Blender file (optional)", False),
                                               ("blender", "Blender 5.2", False), ("package", "Coplanar folder", True))):
        values[key] = tk.StringVar(value=settings.get(key, ""))
        label_widget = ttk.Label(form, text=label)
        label_widget.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=6)
        entry = ttk.Entry(form, textvariable=values[key])
        entry.grid(row=row, column=1, sticky="ew")
        def browse(key=key, folder=folder):
            chosen = filedialog.askdirectory() if folder else filedialog.askopenfilename(
                filetypes=[("Blender scene", "*.blend")] if key == "blend" else [("Blender executable", "blender.exe")])
            if chosen:
                values[key].set(chosen)
        browse_button = ttk.Button(form, text="Browse…", command=browse)
        browse_button.grid(row=row, column=2, padx=(8, 0))
        if key != "blend":
            advanced.extend((label_widget, entry, browse_button))
    show_settings = tk.BooleanVar(value=not bool(settings.get("blender")))
    def toggle_settings():
        for widget in advanced:
            if show_settings.get():
                widget.grid()
            else:
                widget.grid_remove()
    ttk.Checkbutton(root, text="Installation settings", variable=show_settings,
                    command=toggle_settings).pack(anchor="w", pady=(10, 0))
    toggle_settings()
    status = tk.StringVar(value="Ready to connect. Original files and other Blender windows stay safe.")
    ttk.Label(root, textvariable=status, wraplength=650, padding=(0, 16)).pack(anchor="w")
    events = queue.Queue()
    controller = Controller(data, events.put)
    busy = [False]
    connected = [False]
    controls = ttk.Frame(root)
    controls.pack(fill="x")
    def run(action):
        busy[0] = True
        connected[0] = False
        for button in buttons:
            button.config(state="disabled")
        def worker():
            try:
                action()
                events.put({"connected": True})
            except Exception as exc:  # noqa: BLE001 -- UI boundary must show recoverable failures.
                events.put("Could not connect. " + str(exc))
                write_json(data / "setup-error.json", {"error": str(exc)})
            finally:
                events.put(None)
        threading.Thread(target=worker).start()
    def start(new=False):
        if new and not messagebox.askyesno("New workspace", "Open a new working copy? Your existing Blender work stays open. Save it in Blender before closing it."):
            return
        selected = {key: value.get() for key, value in values.items()}
        write_json(settings_path, selected)
        run(lambda: controller.start(selected, new=new))
    buttons = [ttk.Button(controls, text="Start / Reconnect", command=start),
               ttk.Button(controls, text="Show connected Blender", command=lambda: run(
                   lambda: controller.restore_blender(read_json(controller.state)))),
               ttk.Button(controls, text="New workspace", command=lambda: start(True))]
    for button in buttons:
        button.pack(side="left", padx=(0, 8))
    ttk.Button(root, text="Open setup logs", command=lambda: (data.mkdir(parents=True, exist_ok=True),
               os.startfile(data))).pack(anchor="w", pady=10)
    def poll():
        while not events.empty():
            message = events.get_nowait()
            if message is None:
                busy[0] = False
                for button in buttons:
                    button.config(state="normal")
            elif isinstance(message, dict):
                connected[0] = message.get("connected", False)
            else:
                status.set(message)
        root.after(100, poll)
    poll()
    def monitor():
        if connected[0] and not busy[0]:
            def check():
                try:
                    message = connection_message(read_json(controller.state))
                except (OSError, ValueError, RuntimeError):
                    message = "Blender screen disconnected. Press Start / Reconnect to retry."
                if not busy[0]:
                    events.put(message)
            threading.Thread(target=check, daemon=True).start()
        root.after(3000, monitor)
    monitor()
    root.mainloop()


if __name__ == "__main__":
    main()

"""Selected Blender window -> bounded latest JPEG on loopback. Windows only."""

import argparse
import ctypes as C
import io
import json
import os
import socket
import threading
import time
from collections import deque
from ctypes import wintypes as W
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageStat


class WindowUnavailable(RuntimeError):
    def __init__(self, state, message):
        super().__init__(message)
        self.state = state


class Windows:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Window capture requires Windows.")
        self.u = C.WinDLL("user32", use_last_error=True)
        self.g = C.WinDLL("gdi32", use_last_error=True)
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.callback = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        signatures = [
            (self.u, "EnumWindows", [self.callback, W.LPARAM], W.BOOL),
            (self.u, "IsWindow", [W.HWND], W.BOOL),
            (self.u, "IsWindowVisible", [W.HWND], W.BOOL),
            (self.u, "IsIconic", [W.HWND], W.BOOL),
            (self.u, "GetWindowTextW", [W.HWND, W.LPWSTR, C.c_int], C.c_int),
            (self.u, "GetClassNameW", [W.HWND, W.LPWSTR, C.c_int], C.c_int),
            (self.u, "GetWindowThreadProcessId", [W.HWND, C.POINTER(W.DWORD)], W.DWORD),
            (self.u, "GetWindowRect", [W.HWND, C.POINTER(W.RECT)], W.BOOL),
            (self.u, "GetWindowDC", [W.HWND], W.HDC),
            (self.u, "ReleaseDC", [W.HWND, W.HDC], C.c_int),
            (self.u, "PrintWindow", [W.HWND, W.HDC, W.UINT], W.BOOL),
            (self.g, "CreateCompatibleDC", [W.HDC], W.HDC),
            (self.g, "CreateCompatibleBitmap", [W.HDC, C.c_int, C.c_int], W.HBITMAP),
            (self.g, "SelectObject", [W.HDC, W.HANDLE], W.HANDLE),
            (self.g, "DeleteObject", [W.HANDLE], W.BOOL),
            (self.g, "DeleteDC", [W.HDC], W.BOOL),
            (
                self.g,
                "GetDIBits",
                [W.HDC, W.HBITMAP, W.UINT, W.UINT, C.c_void_p, C.c_void_p, W.UINT],
                C.c_int,
            ),
            (self.k, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            (
                self.k,
                "QueryFullProcessImageNameW",
                [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)],
                W.BOOL,
            ),
            (self.k, "CloseHandle", [W.HANDLE], W.BOOL),
        ]
        for dll, name, args, result in signatures:
            fn = getattr(dll, name)
            fn.argtypes, fn.restype = args, result
        try:
            self.u.SetProcessDpiAwarenessContext(C.c_void_p(-4))
        except (AttributeError, OSError):
            pass

    def identity(self, hwnd):
        pid = W.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, C.byref(pid))
        handle = self.k.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return None
        try:
            name, length = C.create_unicode_buffer(32768), W.DWORD(32768)
            if not self.k.QueryFullProcessImageNameW(handle, 0, name, C.byref(length)):
                return None
            if os.path.basename(name.value).lower() != "blender.exe":
                return None
            title = C.create_unicode_buffer(1024)
            self.u.GetWindowTextW(hwnd, title, len(title))
            cls = C.create_unicode_buffer(128)
            self.u.GetClassNameW(hwnd, cls, len(cls))
            if cls.value != "GHOST_WindowClass":
                return (
                    None  # Never the console or an unrelated process with 'Blender' in its title.
                )
            return {"hwnd": int(hwnd), "pid": pid.value, "title": title.value}
        finally:
            self.k.CloseHandle(handle)

    def windows(self):
        result = []

        @self.callback
        def visit(hwnd, _):
            item = self.identity(hwnd) if self.u.IsWindowVisible(hwnd) else None
            if item:
                result.append(item)
            return True

        self.u.EnumWindows(visit, 0)
        return result

    def capture(self, selected):
        hwnd = selected["hwnd"]
        current = self.identity(hwnd) if self.u.IsWindow(hwnd) else None
        if not current or current["pid"] != selected["pid"]:
            raise WindowUnavailable(
                "no_window",
                "Selected Blender window closed. Reopen Blender and select its window again.",
            )
        if self.u.IsIconic(hwnd):
            raise WindowUnavailable(
                "minimized", "Blender is minimized. Restore its window to resume capture."
            )
        rect = W.RECT()
        if not self.u.GetWindowRect(hwnd, C.byref(rect)):
            raise WindowUnavailable("error", "Cannot read the selected window size.")
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if not (1 <= width <= 8192 and 1 <= height <= 8192):
            raise WindowUnavailable(
                "error", "Selected window size is unsupported (maximum 8192 pixels per side)."
            )
        dc = self.u.GetWindowDC(hwnd)
        memory = self.g.CreateCompatibleDC(dc)
        bitmap = self.g.CreateCompatibleBitmap(dc, width, height)
        old = self.g.SelectObject(memory, bitmap)
        try:
            # PW_RENDERFULLCONTENT. No desktop/screen-grab fallback: other windows stay private.
            if not self.u.PrintWindow(hwnd, memory, 2):
                raise WindowUnavailable("error", "Blender did not provide a capture frame.")
            self.g.SelectObject(memory, old)
            header = (C.c_uint32 * 10)(
                40, width, (-height) & 0xFFFFFFFF, 1 | (32 << 16), 0, width * height * 4, 0, 0, 0, 0
            )
            pixels = C.create_string_buffer(width * height * 4)
            if self.g.GetDIBits(dc, bitmap, 0, height, pixels, C.byref(header), 0) != height:
                raise WindowUnavailable("error", "Could not read the selected window pixels.")
            image = Image.frombytes("RGB", (width, height), pixels.raw, "raw", "BGRX")
            # GPU surfaces that don't support PrintWindow can report success but return black.
            if max(ImageStat.Stat(image.resize((32, 32))).mean) < 1:
                raise WindowUnavailable(
                    "error",
                    "Blender returned a black frame; this GPU/window capture is unsupported.",
                )
            # Preserve native UI pixels on ordinary laptop displays. Text suffers when
            # a high-DPI window is reduced before it even reaches the headset.
            image.thumbnail((3840, 2400), Image.Resampling.LANCZOS)
            return image, current["title"]
        finally:
            self.g.SelectObject(memory, old)
            self.g.DeleteObject(bitmap)
            self.g.DeleteDC(memory)
            self.u.ReleaseDC(hwnd, dc)


class LatestFrame:
    def __init__(self):
        self.lock = threading.Lock()
        self.selected = None
        self.generation = 0
        self.sequence = 0
        self.jpeg = None
        self.captured_ms = 0
        self.last_success = 0
        self.status = {
            "state": "no_window",
            "window": None,
            "frame": None,
            "width": None,
            "height": None,
            "fps": 0.0,
            "message": "Select a Blender window in the capture helper.",
        }

    def select(self, window):
        with self.lock:
            self.selected = window
            self.generation += 1
            self.jpeg = None
            self.captured_ms = 0
            self.last_success = 0
            self.status = {
                "state": "no_window",
                "window": window["title"] if window else None,
                "frame": None,
                "width": None,
                "height": None,
                "fps": 0.0,
                "message": "Waiting for selected Blender window."
                if window
                else "Select a Blender window.",
            }

    def fail(self, generation, state, message):
        with self.lock:
            if generation != self.generation:
                return
            self.jpeg = None
            self.status.update(state=state, fps=0.0, message=message)

    def publish(self, generation, image, title, fps, captured_ms):
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=95, subsampling=0)
        self.publish_jpeg(
            generation, output.getvalue(), image.width, image.height, title, fps, captured_ms
        )

    def publish_jpeg(self, generation, jpeg, width, height, title, fps, captured_ms):
        with self.lock:
            if generation != self.generation or captured_ms <= self.captured_ms:
                return False  # A slow old encoder must never roll the newest image back.
            self.sequence += 1
            self.jpeg = jpeg
            self.captured_ms = captured_ms
            self.last_success = time.monotonic()
            self.status = {
                "state": "capturing",
                "window": title,
                "frame": self.sequence,
                "width": width,
                "height": height,
                "fps": round(fps, 1),
                "message": "",
            }
            return True

    def snapshot(self):
        with self.lock:
            status = dict(self.status)
            jpeg = self.jpeg
            if status["state"] == "capturing" and time.monotonic() - self.last_success > 3:
                status.update(
                    state="error", fps=0.0, message="Capture stalled. Last frame is unavailable."
                )
                jpeg = None
            return status, jpeg, self.captured_ms


def capture_refresh_due(last_callback, now):
    # Window identity and an HTTP heartbeat do not prove new pixels. Static WGC
    # windows may emit no changes; reopen the same selected capture for a fresh
    # snapshot instead of certifying an arbitrarily old image as "unchanged".
    return now - last_callback >= 2.0


def owned_capture_pixels(frame):
    # Never retain a native mapped GPU frame across the callback/encoder boundary.
    # An owned, contiguous CPU snapshot lets WGC release/reuse its mapped surface.
    import cv2

    # WGC supplies BGRA8; JPEG uses the same BGR channels and ignores alpha.
    # Convert into an owned contiguous BGR snapshot while the mapping is valid.
    # OpenCV's copy is faster than NumPy's strided four-channel mapped copy.
    return cv2.cvtColor(frame.frame_buffer, cv2.COLOR_BGRA2BGR)


def measured_frame_rate(times, now):
    span = now - times[0] if times else 0
    return (len(times) - 1) / span if len(times) > 1 and span > 0 else 0


def capture_loop(api, latest, stop, fps):
    previous = None
    while not stop.is_set():
        started = time.monotonic()
        captured_ms = int(time.time() * 1000)
        with latest.lock:
            selected, generation = latest.selected, latest.generation
        if selected:
            try:
                image, title = api.capture(selected)
                finished = time.monotonic()
                measured = 1 / (finished - previous) if previous else 0
                previous = finished
                latest.publish(generation, image, title, measured, captured_ms)
            except WindowUnavailable as exc:
                latest.fail(generation, exc.state, str(exc))
                previous = None
            except (OSError, ValueError, RuntimeError) as exc:
                latest.fail(generation, "error", f"Capture failed: {type(exc).__name__}")
                previous = None
        stop.wait(max(0.01, 1 / fps - (time.monotonic() - started)))


def graphics_capture_loop(api, latest, stop, fps):
    import cv2
    from windows_capture import WindowsCapture

    control = None
    active_generation = None
    raw_lock = threading.Lock()
    raw_ready = threading.Event()
    raw_slot = [None]
    encoded_times = deque()
    encoded_lock = threading.Lock()
    session = [0]
    last_callback = [time.monotonic()]

    def encode_newest():
        while not stop.is_set():
            if not raw_ready.wait(0.1):
                continue
            with raw_lock:
                item, raw_slot[0] = raw_slot[0], None
                raw_ready.clear()
            if item is None:
                continue
            generation, selected, pixels, captured_ms, item_session = item
            item = None
            with latest.lock:
                if generation != latest.generation or item_session != session[0]:
                    continue
            height, width = pixels.shape[:2]
            scale = min(1.0, 3840 / width, 2400 / height)
            if scale < 1:
                pixels = cv2.resize(
                    pixels, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA
                )
                height, width = pixels.shape[:2]
            try:
                ok, encoded = cv2.imencode(
                    ".jpg",
                    pixels,
                    [
                        cv2.IMWRITE_JPEG_QUALITY,
                        95,
                        cv2.IMWRITE_JPEG_SAMPLING_FACTOR,
                        cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444,
                    ],
                )
            except cv2.error as exc:
                latest.fail(generation, "error", f"JPEG encode failed: {exc}")
                continue
            current = api.identity(selected["hwnd"])
            if item_session != session[0] or not ok or not current or current["pid"] != selected["pid"]:
                continue
            if api.u.IsIconic(selected["hwnd"]):
                continue
            with encoded_lock:
                # Restart and publication share this lock. An encoder which
                # passed an earlier check cannot publish after an epoch change.
                if item_session != session[0]:
                    continue
                # Take the high-resolution timestamp inside the publication lock.
                # Windows monotonic ticks can coincide; parallel completions must
                # neither divide by zero nor append times in reverse lock order.
                now = time.perf_counter()
                encoded_times.append(now)
                while encoded_times and now - encoded_times[0] > 1:
                    encoded_times.popleft()
                measured = measured_frame_rate(encoded_times, now)
                if not latest.publish_jpeg(
                    generation, encoded.tobytes(), width, height, current["title"], measured, captured_ms
                ):
                    encoded_times.pop()

    # Exactly two in-flight encodes plus one replaceable waiting snapshot.
    # Publication rejects old capture times; nothing accumulates in a queue.
    for index in range(2):
        threading.Thread(target=encode_newest, daemon=True, name=f"Latest JPEG encoder {index}").start()

    def start(selected, generation):
        with encoded_lock:
            session[0] += 1
            this_session = session[0]
            encoded_times.clear()
        last_callback[0] = time.monotonic()
        capture = WindowsCapture(
            window_hwnd=selected["hwnd"],
            cursor_capture=True,
            secondary_window=False,
            minimum_update_interval=max(1, int(1000 / fps)),
            dirty_region=False,
        )

        @capture.event
        def on_frame_arrived(frame, capture_control):
            if stop.is_set() or this_session != session[0]:
                capture_control.stop()
                return
            current = api.identity(selected["hwnd"])
            if not current or current["pid"] != selected["pid"]:
                latest.fail(
                    generation,
                    "no_window",
                    "Selected Blender window closed. Select it again after reopening.",
                )
                capture_control.stop()
                return
            if api.u.IsIconic(selected["hwnd"]):
                latest.fail(
                    generation,
                    "minimized",
                    "Blender is minimized. Restore its window to resume capture.",
                )
                return
            last_callback[0] = time.monotonic()
            # At most one owned waiting frame plus two being encoded. Release the
            # native mapping before returning; superseded CPU snapshots drop.
            pixels = owned_capture_pixels(frame)
            with raw_lock:
                raw_slot[0] = (generation, selected, pixels, int(time.time() * 1000), this_session)
                raw_ready.set()

        @capture.event
        def on_closed():
            if this_session != session[0]:
                return
            latest.fail(
                generation,
                "no_window",
                "Selected Blender window closed. Reopen and select its window again.",
            )

        return capture, capture.start_free_threaded()

    _capture = None
    try:
        while not stop.wait(0.1):
            with latest.lock:
                selected, generation = latest.selected, latest.generation
            if active_generation != generation:
                if control is not None:
                    control.stop()
                control, _capture = None, None
                active_generation = generation
            if not selected:
                continue
            current = api.identity(selected["hwnd"])
            if not current or current["pid"] != selected["pid"]:
                latest.fail(
                    generation,
                    "no_window",
                    "Selected Blender window closed. Reopen and select its window again.",
                )
                continue
            if api.u.IsIconic(selected["hwnd"]):
                latest.fail(
                    generation,
                    "minimized",
                    "Blender is minimized. Restore its window to resume capture.",
                )
                continue
            if control is not None and capture_refresh_due(last_callback[0], time.monotonic()):
                # A fresh capture yields an actual snapshot even for a static
                # window; it also recovers a live-but-stalled capture session.
                with encoded_lock:
                    session[0] += 1
                    encoded_times.clear()
                with raw_lock:
                    raw_slot[0] = None
                # Keep the last image only within its existing3s freshness lease.
                # A quick static-window refresh must not blank/flicker the panel.
                control.stop()
                control, _capture = None, None
                print("CAPTURE_RECOVERY no_new_callback; reopening selected window", flush=True)
            if control is None or control.is_finished():
                try:
                    _capture, control = start(selected, generation)
                except (OSError, RuntimeError, ValueError) as exc:
                    latest.fail(generation, "error", f"Graphics capture failed: {exc}")
                    stop.wait(1)
                    continue
    finally:
        if control is not None:
            control.stop()


def make_server(latest, port):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            # No CORS, no control endpoints, no capture of anything but the local selection.
            if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
                self.send_error(403)
                return
            status, jpeg, captured = latest.snapshot()
            headers = {}
            if self.path == "/status":
                code, mime, body = 200, "application/json", json.dumps(status).encode()
            elif self.path == "/selection":
                # Launcher identity check; separate from the fixed status schema.
                # Read-only: changing selection still requires the local picker.
                with latest.lock:
                    selected = dict(latest.selected) if latest.selected else None
                code, mime, body = 200, "application/json", json.dumps(selected).encode()
            elif self.path == "/frame":
                if not jpeg:
                    code, mime, body = 503, "application/json", json.dumps(status).encode()
                else:
                    etag = f'"{status["frame"]}"'
                    code = 304 if self.headers.get("If-None-Match") == etag else 200
                    mime, body = "image/jpeg", jpeg if code == 200 else b""
                    headers = {
                        "ETag": etag,
                        "X-Captured-At": str(captured),
                        "X-Capture-Alive": str(int(time.time() * 1000)),
                        "X-Window": (status["window"] or "")
                        .encode("ascii", "replace")
                        .decode()
                        .replace("\r", " ")
                        .replace("\n", " "),
                        "X-Size": f"{status['width']}x{status['height']}",
                    }
            else:
                self.send_error(404)
                return
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 8
        allow_reuse_address = False

        def server_bind(self):
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(3)
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return connection, address

    return Server(("127.0.0.1", port), Handler)


def picker(api, latest):
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Spatial Modeling — Select Blender window")
    root.geometry("720x290")
    ttk.Label(
        root,
        text="Select the Blender window to show in VR. Only this window is captured.",
        wraplength=680,
    ).pack(padx=16, pady=12)
    names = tk.StringVar()
    combo = ttk.Combobox(root, textvariable=names, state="readonly", width=95)
    combo.pack(padx=16, pady=8)
    windows = []

    def refresh():
        windows[:] = api.windows()
        combo["values"] = [f"PID {w['pid']} — {w['title']}" for w in windows]
        if windows:
            combo.current(0)

    def choose():
        index = combo.current()
        if 0 <= index < len(windows):
            latest.select(windows[index])

    controls = ttk.Frame(root)
    controls.pack(pady=8)
    ttk.Button(controls, text="Refresh windows", command=refresh).pack(side="left", padx=8)
    ttk.Button(controls, text="Capture selected window", command=choose).pack(side="left", padx=8)
    label = ttk.Label(root, wraplength=680)
    label.pack(padx=16, pady=10)

    def update():
        status, _, _ = latest.snapshot()
        label.config(
            text=f"{status['state']}: {status['message'] or status['window']}\nFrame {status['frame']} — {status['fps']} fps. A / X in VR: show/hide Blender."
        )
        root.after(500, update)

    refresh()
    update()
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--fps", type=float, default=60)
    parser.add_argument("--backend", choices=("graphics", "print"), default="graphics")
    parser.add_argument(
        "--window", type=int, help="Explicit selected Blender HWND; otherwise opens a picker"
    )
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.fps <= 60:
        parser.error("--fps must be between 1 and 60")
    api = Windows()
    if args.list:
        print(json.dumps(api.windows(), ensure_ascii=False))
        return
    latest = LatestFrame()
    if args.window:
        selected = api.identity(args.window)
        if not selected:
            parser.error("--window must identify an actual Blender application window")
        latest.select(selected)
    server = make_server(latest, args.port)
    stop = threading.Event()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    loop = graphics_capture_loop if args.backend == "graphics" else capture_loop
    if args.backend == "graphics":
        import windows_capture  # noqa: F401 -- Fail before starting the HTTP service if dependency is missing.
    threading.Thread(target=loop, args=(api, latest, stop, args.fps), daemon=True).start()
    print(
        f"Capture helper listening on http://127.0.0.1:{server.server_port}; selected window only",
        flush=True,
    )
    try:
        picker(api, latest)
    finally:
        stop.set()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()

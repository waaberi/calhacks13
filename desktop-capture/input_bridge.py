"""Opt-in, selected-window native input. No global desktop capture or input fallback.

Normalized pointer coordinates address the *entire captured image*, top left (0,0).
The capture producer supplies exact native pixel bounds before JPEG downscaling.
All mutations are serialized without a queue and consume a sequence before dispatch:
an uncertain/failed SendInput must never be retried automatically.
"""

import ctypes as C
import math
import os
import secrets
import threading
import time
from ctypes import wintypes as W


class InputRejected(RuntimeError):
    def __init__(self, reason, status=409):
        super().__init__(reason)
        self.reason, self.status = reason, status


KEYS = {
    "BACKSPACE": 0x08, "TAB": 0x09, "ENTER": 0x0D, "SHIFT": 0x10,
    "CTRL": 0x11, "ALT": 0x12, "ESC": 0x1B, "SPACE": 0x20,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22, "END": 0x23, "HOME": 0x24,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "INSERT": 0x2D, "DELETE": 0x2E, "NUMPAD0": 0x60,
    "MULTIPLY": 0x6A, "ADD": 0x6B, "SUBTRACT": 0x6D,
    "DECIMAL": 0x6E, "DIVIDE": 0x6F,
    "SEMICOLON": 0xBA, "EQUALS": 0xBB, "COMMA": 0xBC,
    "MINUS": 0xBD, "PERIOD": 0xBE, "SLASH": 0xBF, "GRAVE": 0xC0,
    "LEFTBRACKET": 0xDB, "BACKSLASH": 0xDC, "RIGHTBRACKET": 0xDD, "QUOTE": 0xDE,
}
KEYS.update({chr(code): code for code in range(ord("A"), ord("Z") + 1)})
KEYS.update({str(n): ord(str(n)) for n in range(10)})
KEYS.update({f"F{n}": 0x6F + n for n in range(1, 25)})
KEYS.update({f"NUMPAD{n}": 0x60 + n for n in range(10)})
EXTENDED_KEYS = {"PAGEUP", "PAGEDOWN", "END", "HOME", "LEFT", "UP", "RIGHT",
                 "DOWN", "INSERT", "DELETE", "DIVIDE"}
BUTTONS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010),
           "middle": (0x0020, 0x0040)}


class MouseInput(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class KeyboardInput(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class HardwareInput(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class InputUnion(C.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeyboardInput), ("hi", HardwareInput)]


class NativeInput(C.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", W.DWORD), ("data", InputUnion)]


class WindowsInput:
    """Thin Win32 adapter, replaceable in tests; construction sends no input."""

    def __init__(self, windows):
        if os.name != "nt":
            raise RuntimeError("Native input requires Windows")
        self.windows, self.u = windows, windows.u
        self.dwm = C.WinDLL("dwmapi", use_last_error=True)
        signatures = [
            (self.u, "GetForegroundWindow", [], W.HWND),
            (self.u, "SetForegroundWindow", [W.HWND], W.BOOL),
            (self.u, "GetDpiForWindow", [W.HWND], W.UINT),
            (self.u, "WindowFromPoint", [W.POINT], W.HWND),
            (self.u, "GetAncestor", [W.HWND, W.UINT], W.HWND),
            (self.u, "GetSystemMetrics", [C.c_int], C.c_int),
            (self.u, "GetAsyncKeyState", [C.c_int], C.c_short),
            (self.u, "SendInput", [W.UINT, C.POINTER(NativeInput), C.c_int], W.UINT),
            (self.dwm, "DwmGetWindowAttribute",
             [W.HWND, W.DWORD, C.c_void_p, W.DWORD], C.c_long),
            (windows.k, "GetProcessTimes", [W.HANDLE, C.POINTER(W.FILETIME),
             C.POINTER(W.FILETIME), C.POINTER(W.FILETIME), C.POINTER(W.FILETIME)], W.BOOL),
        ]
        for dll, name, args, result in signatures:
            fn = getattr(dll, name)
            fn.argtypes, fn.restype = args, result

    @staticmethod
    def _rect(rect):
        return [rect.left, rect.top, rect.right, rect.bottom]

    def inspect(self, selected):
        hwnd = selected["hwnd"]
        current = self.windows.identity(hwnd) if self.u.IsWindow(hwnd) else None
        if not current or current["pid"] != selected["pid"]:
            raise InputRejected("selected_window_closed")
        if not self.u.IsWindowVisible(hwnd) or self.u.IsIconic(hwnd):
            raise InputRejected("selected_window_hidden_or_minimized")
        full, visible = W.RECT(), W.RECT()
        if not self.u.GetWindowRect(hwnd, C.byref(full)):
            raise InputRejected("window_geometry_unavailable")
        if self.dwm.DwmGetWindowAttribute(hwnd, 9, C.byref(visible), C.sizeof(visible)):
            visible = full
        dpi = self.u.GetDpiForWindow(hwnd)
        if not dpi:
            raise InputRejected("window_dpi_unavailable")
        return {"window_rect": self._rect(full), "visible_rect": self._rect(visible),
                "dpi": dpi, "process_started": self.process_stamp(selected["pid"])}

    def process_stamp(self, pid):
        handle = self.windows.k.OpenProcess(0x1000, False, pid)
        if not handle:
            raise InputRejected("selected_process_unavailable")
        try:
            created, exited, kernel, user = W.FILETIME(), W.FILETIME(), W.FILETIME(), W.FILETIME()
            if not self.windows.k.GetProcessTimes(handle, C.byref(created), C.byref(exited),
                                                  C.byref(kernel), C.byref(user)):
                raise InputRejected("selected_process_identity_unavailable")
            return (created.dwHighDateTime << 32) | created.dwLowDateTime
        finally:
            self.windows.k.CloseHandle(handle)

    def windows_for(self, selected, process_started):
        try:
            if self.process_stamp(selected["pid"]) != process_started:
                return []
        except InputRejected:
            return []
        return [w for w in self.windows.windows()
                if w["pid"] == selected["pid"] and not self.u.IsIconic(w["hwnd"])]

    def foreground(self, hwnd):
        # Same-process auxiliary windows are deliberately NOT accepted implicitly.
        return int(self.u.GetForegroundWindow() or 0) == hwnd

    def focus(self, hwnd):
        self.u.SetForegroundWindow(hwnd)
        return self.foreground(hwnd)

    def target_visible(self, hwnd, x, y):
        hit = self.u.WindowFromPoint(W.POINT(x, y))
        return bool(hit) and int(self.u.GetAncestor(hit, 2) or hit) == hwnd

    def key_is_down(self, key):
        return bool(self.u.GetAsyncKeyState(KEYS[key]) & 0x8000)

    def button_is_down(self, button):
        return bool(self.u.GetAsyncKeyState({"left": 1, "right": 2, "middle": 4}[button]) & 0x8000)

    def send(self, events):
        records = []
        for event in events:
            kind = event[0]
            record = NativeInput()
            if kind == "move":
                _, x, y = event
                left, top = self.u.GetSystemMetrics(76), self.u.GetSystemMetrics(77)
                width, height = self.u.GetSystemMetrics(78), self.u.GetSystemMetrics(79)
                if width <= 1 or height <= 1:
                    raise InputRejected("virtual_desktop_geometry_unavailable")
                record.type = 0
                record.mi = MouseInput(round((x - left) * 65535 / (width - 1)),
                                       round((y - top) * 65535 / (height - 1)),
                                       0, 0x8000 | 0x4000 | 0x0001, 0, 0)
            elif kind == "button":
                record.type = 0
                record.mi = MouseInput(0, 0, 0, BUTTONS[event[1]][event[2] == "up"], 0, 0)
            elif kind == "wheel":
                record.type = 0
                record.mi = MouseInput(0, 0, event[2] & 0xFFFFFFFF,
                                       0x1000 if event[1] == "x" else 0x0800, 0, 0)
            elif kind == "key":
                record.type = 1
                flags = (2 if event[2] == "up" else 0) | (1 if event[1] in EXTENDED_KEYS else 0)
                record.ki = KeyboardInput(KEYS[event[1]], 0, flags, 0, 0)
            elif kind == "unicode":
                record.type = 1
                record.ki = KeyboardInput(0, event[1], 4 | (2 if event[2] == "up" else 0), 0, 0)
            else:
                raise ValueError("Unknown native event")
            records.append(record)
        if records:
            array = (NativeInput * len(records))(*records)
            sent = self.u.SendInput(len(records), array, C.sizeof(NativeInput))
            if sent != len(records):
                # UIPI can reject delivery with no useful last-error information.
                # The caller releases tracked downs and consumes the request sequence.
                raise InputRejected("native_input_delivery_failed", 502)


class InputBridge:
    def __init__(self, latest, native, enabled=False, clock=time.monotonic):
        self.latest, self.native, self.enabled, self.clock = latest, native, enabled, clock
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self.session = secrets.token_urlsafe(18)
        self.fingerprint = None
        self.sequence = 0
        self.held_keys, self.held_buttons = set(), set()
        self.last_event = 0
        self.release_error = False
        self.process_binding = None

    def frame_geometry(self, selected, width, height, source):
        """Only exact recognized native rectangles can authorize pointer mapping."""
        try:
            live = self.native.inspect(selected)
        except InputRejected:
            return None
        candidates = ["window_rect"] if source == "print" else ["visible_rect", "window_rect"]
        for name in candidates:
            left, top, right, bottom = live[name]
            if (right - left, bottom - top) == (width, height):
                return {**live, "left": left, "top": top, "width": width, "height": height,
                        "source": name}
        return None

    def _snapshot(self, include_windows=False):
        with self.latest.lock:
            status = dict(self.latest.status)
            jpeg = self.latest.jpeg
            if time.monotonic() - self.latest.last_success > 3:
                jpeg = None
            selected = dict(self.latest.selected) if self.latest.selected else None
            generation = self.latest.generation
            instance = self.latest.capture_instance
            geometry = self.latest.input_geometry
        reason, live = "", None
        if not self.enabled:
            reason = "input_disabled"
        elif not selected:
            reason = "no_selected_window"
        elif status["state"] != "capturing" or not jpeg:
            reason = "capture_unavailable"
        elif not geometry:
            reason = "capture_geometry_unverified"
        else:
            try:
                live = self.native.inspect(selected)
                binding_changed = (self.process_binding is not None
                                   and self.process_binding[0] == generation
                                   and self.process_binding[1:] != (selected["pid"], live["process_started"]))
                if (live["process_started"] != geometry["process_started"] or binding_changed
                        or selected.get("input_process_started", live["process_started"]) != live["process_started"]):
                    reason = "selected_process_identity_changed"
                elif any(live[k] != geometry[k] for k in ("window_rect", "visible_rect", "dpi")):
                    reason = "window_geometry_changed_wait_for_frame"
                else:
                    self.process_binding = (generation, selected["pid"], live["process_started"])
            except InputRejected as exc:
                reason = exc.reason
        fingerprint = (generation, selected and selected["hwnd"], selected and selected["pid"],
                       status["width"], status["height"], repr(geometry), reason)
        if fingerprint != self.fingerprint:
            self._release()
            self.session = secrets.token_urlsafe(18)
            self.sequence = 0
            self.fingerprint = fingerprint
        focused = bool(selected and not reason and self.native.foreground(selected["hwnd"]))
        return {"enabled": self.enabled, "ready": not reason, "reason": reason,
                "session": self.session, "token": self.token if self.enabled else None,
                "capture_generation": generation, "capture_instance": instance,
                "helper_pid": os.getpid(),
                "frame": status["frame"],
                "selection": selected, "image": {"width": status["width"], "height": status["height"]},
                "geometry": geometry, "focused": focused, "next_seq": self.sequence + 1,
                "windows": self._windows(selected)
                if include_windows and self.enabled and selected else [],
                "release_error": self.release_error}

    def _windows(self, selected):
        # Closing a selected popup must not strand the user, but a recycled PID
        # must never authorize selecting a different Blender process. A previous
        # fresh, identity-verified frame supplies the process creation stamp.
        if not selected or not self.process_binding or self.process_binding[1] != selected["pid"]:
            return []
        return self.native.windows_for(selected, self.process_binding[2])

    def state(self):
        with self.lock:
            return self._snapshot(include_windows=True)

    def _release(self):
        events = [("button", button, "up") for button in sorted(self.held_buttons)]
        events += [("key", key, "up") for key in sorted(self.held_keys)]
        if not events:
            return
        try:
            self.native.send(events)
        except (InputRejected, OSError):
            # Keep tracking for the next watchdog release attempt, but prevent
            # further downs until cleanup succeeds. No mutation is replayed.
            self.release_error = True
            return
        self.held_keys.clear()
        self.held_buttons.clear()
        self.release_error = False

    def watchdog(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            state = self._snapshot()
            if (not state["ready"] or not state["focused"]
                    or self.clock() - self.last_event > 1.5 or self.release_error):
                self._release()
        finally:
            self.lock.release()

    def run_watchdog(self, stop):
        while not stop.wait(0.2):
            self.watchdog()
        with self.lock:
            self._release()

    @staticmethod
    def _number(value, low, high):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InputRejected("invalid_number", 400)
        if not math.isfinite(value) or not low <= value <= high:
            raise InputRejected("number_out_of_range", 400)
        return value

    def _pointer(self, payload, state):
        x = self._number(payload.get("x"), 0, 1)
        y = self._number(payload.get("y"), 0, 1)
        g = state["geometry"]
        px = g["left"] + round(x * (g["width"] - 1))
        py = g["top"] + round(y * (g["height"] - 1))
        if not self.native.target_visible(state["selection"]["hwnd"], px, py):
            raise InputRejected("selected_window_occluded_at_pointer")
        return ("move", px, py)

    def dispatch(self, payload):
        if not self.lock.acquire(blocking=False):
            raise InputRejected("input_busy", 429)
        try:
            state = self._snapshot()
            if not isinstance(payload, dict):
                raise InputRejected("expected_json_object", 400)
            if not self.enabled:
                raise InputRejected("input_disabled", 403)
            if not isinstance(payload.get("token"), str) or not secrets.compare_digest(
                    payload["token"], self.token):
                raise InputRejected("invalid_input_token", 403)
            if payload.get("session") != self.session:
                raise InputRejected("stale_input_session")
            seq = payload.get("seq")
            if isinstance(seq, bool) or not isinstance(seq, int) or seq != self.sequence + 1:
                raise InputRejected("unexpected_input_sequence")
            # Consume even a rejected mutation. Clients inspect state; never retry.
            self.sequence = seq
            kind = payload.get("type")
            if kind == "release":
                self._release()
                if self.release_error:
                    raise InputRejected("release_delivery_failed", 502)
                return {"ok": True, "seq": seq}
            if kind == "select_window":
                requested = payload.get("hwnd")
                if isinstance(requested, bool) or not isinstance(requested, int):
                    raise InputRejected("invalid_window_handle", 400)
                window = next((w for w in self._windows(state["selection"])
                               if w["hwnd"] == requested), None)
                if not window:
                    raise InputRejected("window_outside_selected_process", 403)
                live = self.native.inspect(window)
                if live["process_started"] != self.process_binding[2]:
                    raise InputRejected("selected_process_identity_changed", 403)
                window = {**window, "input_process_started": live["process_started"]}
                self._release()
                if self.release_error:
                    raise InputRejected("release_pending", 502)
                self.latest.select(window)
                return {"ok": True, "seq": seq, "selection_changed": True}
            if not state["ready"]:
                raise InputRejected(state["reason"])
            if self.release_error:
                raise InputRejected("release_pending", 502)
            hwnd = state["selection"]["hwnd"]
            if kind == "focus":
                self._release()
                if not self.native.focus(hwnd):
                    raise InputRejected("foreground_activation_denied")
                self.last_event = self.clock()
                return {"ok": True, "seq": seq}
            if not self.native.foreground(hwnd):
                self._release()
                raise InputRejected("selected_window_not_foreground")
            if kind == "heartbeat":
                self.last_event = self.clock()
                return {"ok": True, "seq": seq}
            events = []
            if kind in ("pointer", "button", "scroll"):
                events.append(self._pointer(payload, state))
            if kind == "button":
                button, action = payload.get("button"), payload.get("action")
                if not isinstance(button, str) or button not in BUTTONS or action not in (
                        "down", "up", "click", "double_click"):
                    raise InputRejected("invalid_button_action", 400)
                if (action == "up") != (button in self.held_buttons):
                    raise InputRejected("button_already_held_or_not_pressed")
                if action != "up" and self.native.button_is_down(button):
                    raise InputRejected("button_held_by_other_input")
                # Track every possible down before SendInput (partial sends can occur).
                if action != "up":
                    self.held_buttons.add(button)
                actions = [action] if action in ("down", "up") else ["down", "up"] * (2 if action == "double_click" else 1)
                events += [("button", button, a) for a in actions]
            elif kind == "scroll":
                for axis in ("x", "y"):
                    detents = self._number(payload.get("d" + axis, 0), -20, 20)
                    if detents:
                        events.append(("wheel", axis, round(detents * 120)))
            elif kind == "key":
                key, action = payload.get("key"), payload.get("action")
                key = key.upper() if isinstance(key, str) else ""
                if key not in KEYS or action not in ("down", "up", "press"):
                    raise InputRejected("invalid_key_action", 400)
                if (action == "up") != (key in self.held_keys):
                    raise InputRejected("key_already_held_or_not_pressed")
                if action != "up" and self.native.key_is_down(key):
                    raise InputRejected("key_held_by_other_input")
                if action != "up":
                    self.held_keys.add(key)
                events = [("key", key, a) for a in (["down", "up"] if action == "press" else [action])]
            elif kind == "text":
                text = payload.get("text")
                if not isinstance(text, str) or not 1 <= len(text) <= 256 or "\x00" in text:
                    raise InputRejected("invalid_text", 400)
                if self.held_keys or self.held_buttons:
                    raise InputRejected("release_held_inputs_before_text")
                try:
                    units = text.encode("utf-16-le")
                except UnicodeEncodeError as exc:
                    raise InputRejected("invalid_unicode", 400) from exc
                events = [("unicode", int.from_bytes(units[i:i + 2], "little"), a)
                          for i in range(0, len(units), 2) for a in ("down", "up")]
            elif kind != "pointer":
                raise InputRejected("unknown_input_type", 400)
            try:
                # SendInput has no target HWND. Recheck immediately before the
                # batch as well as before constructing it; never send to a new
                # foreground application after a slow context lookup.
                if not self.native.foreground(hwnd):
                    raise InputRejected("selected_window_not_foreground")
                live = self.native.inspect(state["selection"])
                if live["process_started"] != state["geometry"]["process_started"]:
                    raise InputRejected("selected_process_identity_changed")
                if any(live[k] != state["geometry"][k]
                       for k in ("window_rect", "visible_rect", "dpi")):
                    raise InputRejected("window_geometry_changed_wait_for_frame")
                self.native.send(events)
            except (InputRejected, OSError):
                if kind == "text":
                    try:
                        self.native.send([event for event in events if event[2] == "up"])
                    except (InputRejected, OSError):
                        pass
                self._release()
                raise
            if kind == "button" and action != "down":
                self.held_buttons.discard(button)
            if kind == "key" and action != "down":
                self.held_keys.discard(key)
            self.last_event = self.clock()
            return {"ok": True, "seq": seq}
        finally:
            self.lock.release()

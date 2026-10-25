"""Real dialog input bridge with fake Win32 and loopback only; no desktop input."""

import ctypes as C
import http.client
import json
import threading
import unittest
from contextlib import closing
from ctypes import wintypes as W
from types import SimpleNamespace
from unittest.mock import patch

from capture_helper import LatestFrame, make_server
from input_bridge import InputBridge, InputRejected, WindowsInput
from window_family import resolve_window


class FakeWindowSystem:
    """Native metadata only; membership decisions use the production resolver."""

    def __init__(self):
        self.records = {}
        self.stamps = {200: 200001, 300: 300001, 301: 301001, 500: 500001}
        self.active = 100
        self.activation_calls = []
        self.activation_allowed = True
        self.activation_hook = None
        self.inventory_override = None
        self.closed_handles = []
        self.add(100, 200, "GHOST_WindowClass", executable=r"C:\fixture\blender.exe")
        self.add(110, 300, "#32770", owner=100, visible=False)
        self.add(120, 300, "#32768", owner=110, menu_owner=110, visible=False)
        self.add(130, 301, "ComboLBox", owner=120, visible=False)
        self.add(140, 300, "#32770", owner=999, visible=False)
        self.add(400, 500, "GHOST_WindowClass", executable=r"C:\other\blender.exe", visible=False)
        self.u = SimpleNamespace(
            IsWindow=lambda hwnd: hwnd in self.records,
            IsWindowVisible=lambda hwnd: bool(self.records.get(hwnd, {}).get("visible")),
            IsIconic=lambda hwnd: bool(self.records.get(hwnd, {}).get("minimized")),
            GetWindowRect=self.get_rect,
            GetDpiForWindow=lambda hwnd: self.records[hwnd]["dpi"],
            GetForegroundWindow=lambda: self.active,
            GetAncestor=self.get_ancestor,
            SetForegroundWindow=self.set_foreground,
        )
        self.k = SimpleNamespace(OpenProcess=lambda _, __, pid: pid if pid in self.stamps else 0,
                                 GetProcessTimes=self.get_process_times, CloseHandle=self.closed_handles.append)

    def add(self, hwnd, pid, cls, *, owner=0, menu_owner=0, executable=r"C:\fixture\broker.exe", visible=True):
        self.records[hwnd] = {"hwnd": hwnd, "pid": pid, "title": f"Native fixture {hwnd}",
                              "window_class": cls, "owner_hwnd": owner, "parent_hwnd": 0,
                              "menu_owner_hwnd": menu_owner, "executable": executable,
                              "visible": visible, "minimized": False,
                              "window_rect": [-1808, -708, -192, -92],
                              "visible_rect": [-1800, -700, -200, -100], "dpi": 192}

    def identity(self, hwnd):
        return resolve_window(hwnd, lambda handle: self.records.get(handle))

    def windows(self, include_owned=False):
        assert include_owned
        if self.inventory_override is not None:
            return [dict(item) for item in self.inventory_override]
        # EnumWindows supplies topmost first. Newly opened nested windows precede parents.
        return [item for hwnd, record in reversed(list(self.records.items()))
                if record["visible"] and (item := self.identity(hwnd))]

    @staticmethod
    def write_rect(target, values):
        rect = C.cast(target, C.POINTER(W.RECT)).contents
        rect.left, rect.top, rect.right, rect.bottom = values

    def get_rect(self, hwnd, target):
        self.write_rect(target, self.records[hwnd]["window_rect"])
        return True

    def get_visible_rect(self, hwnd, _, target, __):
        self.write_rect(target, self.records[hwnd]["visible_rect"])
        return 0

    def get_ancestor(self, hwnd, flag):
        assert flag == 2  # GA_ROOT follows child parents, never top-level owners.
        seen = set()
        for _ in range(16):
            if hwnd not in self.records or hwnd in seen:
                return 0
            seen.add(hwnd)
            parent = self.records[hwnd]["parent_hwnd"]
            if not parent:
                return hwnd
            hwnd = parent
        return 0

    def get_process_times(self, handle, created, *_):
        value = C.cast(created, C.POINTER(W.FILETIME)).contents
        stamp = self.stamps[handle]
        value.dwHighDateTime, value.dwLowDateTime = stamp >> 32, stamp & 0xFFFFFFFF
        return True

    def set_foreground(self, hwnd):
        self.activation_calls.append(hwnd)
        if self.activation_hook:
            self.activation_hook(hwnd)
        if self.activation_allowed:
            self.active = hwnd
        return self.activation_allowed


class RecordingWindowsInput(WindowsInput):
    """Real admission/inspection/following; event delivery is only an in-memory log."""

    def __init__(self, windows, latest):
        self.windows, self.u, self.latest = windows, windows.u, latest
        self.dwm = SimpleNamespace(DwmGetWindowAttribute=windows.get_visible_rect)
        self.sent = []
        self.delivery_selection = []
        self.fail_releases = False
        self.focus_calls = []

    def send(self, events):
        self.sent.append(list(events))
        self.delivery_selection.append(self.latest.selected["hwnd"])
        if self.fail_releases and any(event[-1] == "up" for event in events):
            raise InputRejected("native_input_delivery_failed", 502)

    def focus(self, hwnd):
        self.focus_calls.append(hwnd)
        return super().focus(hwnd)

    def target_visible(self, *_):
        return True

    def key_is_down(self, _):
        return False

    def button_is_down(self, _):
        return False


class DialogInputTests(unittest.TestCase):
    def setUp(self):
        self.latest, self.windows = LatestFrame(), FakeWindowSystem()
        self.native = RecordingWindowsInput(self.windows, self.latest)
        self.now = 10
        self.bridge = InputBridge(self.latest, self.native, enabled=True, clock=lambda: self.now)
        self.latest.select(self.windows.identity(100))
        self.publish()
        self.assertTrue(self.bridge.state()["ready"])

    def publish(self):
        selected = self.latest.selected
        rect = self.windows.records[selected["hwnd"]]["visible_rect"]
        raw = rect[2] - rect[0], rect[3] - rect[1]
        geometry = self.bridge.frame_geometry(selected, *raw, "graphics")
        return self.latest.publish_jpeg(self.latest.generation, b"private-fake-jpeg", raw[0] // 2, raw[1] // 2,
                                        selected["title"], 0, self.latest.captured_ms + 1, geometry)

    def event(self, kind, **values):
        state = self.bridge.state()
        return {"session": state["session"], "token": state["token"], "seq": state["next_seq"],
                "type": kind, **values}

    def dispatch(self, kind, **values):
        return self.bridge.dispatch(self.event(kind, **values))

    def reject(self, payload, reason):
        with self.assertRaises(InputRejected) as context:
            self.bridge.dispatch(payload)
        self.assertEqual(context.exception.reason, reason)

    def open_dialog(self):
        self.windows.records[110]["visible"] = True
        self.windows.active = 110
        self.bridge.watchdog()
        self.assertEqual(self.latest.selected["hwnd"], 110)
        self.assertFalse(self.bridge.state()["ready"])
        self.publish()
        self.assertTrue(self.bridge.state()["ready"])

    def slow_census(self, target):
        entered, resume = threading.Event(), threading.Event()
        errors = []
        windows = self.windows.windows

        def delayed(*args, **kwargs):
            entered.set()
            if not resume.wait(3):
                raise AssertionError("test census was not released")
            return windows(*args, **kwargs)

        def run():
            try:
                target()
            except Exception as exc:  # noqa: BLE001 - propagate worker failures on the test thread.
                errors.append(exc)

        override = patch.object(self.windows, "windows", side_effect=delayed)
        override.start()
        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(entered.wait(2), "read-only census starts")

        def finish():
            resume.set()
            worker.join(3)
            override.stop()
            self.assertFalse(worker.is_alive(), "bounded census worker finishes")
            if errors:
                raise errors[0]

        return finish

    def test_slow_state_census_does_not_reject_or_queue_legitimate_input(self):
        payload = self.event("pointer", x=.5, y=.5)
        result = []
        finish = self.slow_census(lambda: result.append(self.bridge.state()))
        try:
            self.assertEqual(self.bridge.dispatch(payload), {"ok": True, "seq": payload["seq"]})
            self.assertEqual(len(self.native.sent), 1, "input is delivered while enumeration is still blocked")
        finally:
            finish()
        self.assertEqual(result[0]["next_seq"], payload["seq"] + 1, "state reports the current sequence after concurrent input")
        self.assertEqual({w["blender_pid"] for w in result[0]["windows"]}, {200})

    def test_slow_watchdog_census_releases_stale_button_first_and_admits_fresh_input(self):
        self.dispatch("button", button="left", action="down", x=.5, y=.5)
        previous_session = self.bridge.session
        self.now += 2
        finish = self.slow_census(self.bridge.watchdog)
        try:
            self.assertFalse(self.bridge.held_buttons, "owned stale button is released before enumeration can block")
            self.assertEqual(self.native.sent[-1], [("button", "left", "up")])
            self.assertNotEqual(self.bridge.session, previous_session)
            with self.bridge.lock:
                state = self.bridge._snapshot()
            payload = {"session": state["session"], "token": state["token"], "seq": state["next_seq"],
                       "type": "pointer", "x": .5, "y": .5}
            self.assertTrue(self.bridge.dispatch(payload)["ok"])
            self.assertEqual(self.native.sent[-1][0][0], "move", "fresh input is not queued behind the census")
        finally:
            finish()

    def test_slow_state_census_discards_windows_after_root_lifetime_changes(self):
        result = []
        finish = self.slow_census(lambda: result.append(self.bridge.state()))
        try:
            self.windows.stamps[200] += 1
        finally:
            finish()
        self.assertEqual(result[0]["windows"], [], "old census cannot advertise a recycled native root")
        self.assertEqual(result[0]["reason"], "selected_process_identity_changed")

    def test_late_census_cannot_follow_after_explicit_scope_change(self):
        self.windows.records[110]["visible"] = True
        finish = self.slow_census(self.bridge.watchdog)
        try:
            self.latest.select(self.windows.identity(400))
            self.windows.records[400]["visible"] = True
            self.publish()
            self.windows.active = 110
            changed_scope, changed_generation = self.latest.window_scope, self.latest.generation
        finally:
            finish()
        self.assertEqual((self.latest.selected["hwnd"], self.latest.window_scope, self.latest.generation),
                         (400, changed_scope, changed_generation))
        self.assertFalse(self.native.sent, "stale read-only candidate cannot change the new native binding")

    def test_late_census_refuses_foreign_popup_and_recycled_blender_root(self):
        for changed in ("foreign_popup", "root_lifetime"):
            with self.subTest(changed=changed):
                self.setUp()
                self.windows.records[110]["visible"] = True
                if changed == "foreign_popup":
                    foreign = {**self.windows.identity(400), "blender_pid": 200, "blender_hwnd": 100}
                    self.windows.inventory_override = [self.windows.identity(100), foreign]
                    self.windows.active = 400
                finish = self.slow_census(self.bridge.watchdog)
                try:
                    if changed == "root_lifetime":
                        self.windows.stamps[200] += 1
                        self.windows.active = 110
                finally:
                    finish()
                self.assertEqual(self.latest.selected["hwnd"], 100)
                self.assertFalse(self.native.sent, "fresh native identity refuses untrusted or recycled census targets")

    def test_brokered_dialog_has_separate_target_and_blender_birth_stamps(self):
        self.open_dialog()
        state = self.bridge.state()
        self.assertEqual(state["selection"]["pid"], 300)
        self.assertEqual(state["selection"]["blender_pid"], 200)
        self.assertEqual(state["selection"]["input_process_started"], 300001)
        self.assertEqual(state["selection"]["blender_process_started"], 200001)
        self.assertEqual(state["geometry"]["process_started"], 300001)
        self.assertEqual(state["geometry"]["blender_process_started"], 200001)
        self.assertEqual({item["pid"] for item in state["windows"]}, {200, 300})

    def test_watchdog_follows_dialog_nested_popup_and_close_back_to_parent(self):
        scope = self.latest.window_scope
        self.open_dialog()
        for hwnd, active in ((120, 110), (130, 120)):
            self.windows.records[hwnd]["visible"] = True
            self.windows.active = active
            self.bridge.watchdog()
            self.assertEqual(self.latest.selected["hwnd"], hwnd)
            self.assertEqual(self.latest.window_scope, scope)
            self.publish()
        self.windows.records[130]["visible"] = False
        self.windows.active = 120
        self.bridge.watchdog()
        self.assertEqual(self.latest.selected["hwnd"], 120)
        self.publish()
        self.windows.records[120]["visible"] = False
        self.windows.active = 110
        self.bridge.watchdog()
        self.assertEqual(self.latest.selected["hwnd"], 110)
        self.publish()
        self.windows.records[110]["visible"] = False
        self.windows.active = 100
        self.bridge.watchdog()
        self.assertEqual(self.latest.selected["hwnd"], 100)
        self.assertEqual(self.latest.window_scope, scope)
        self.assertEqual(self.native.focus_calls, [])
        self.assertEqual(self.native.sent, [])

    def test_closed_dialog_returns_to_owner_even_if_another_application_is_foreground(self):
        self.open_dialog()
        del self.windows.records[110]
        self.windows.active = 999
        self.bridge.watchdog()
        self.assertEqual(self.latest.selected["hwnd"], 100)
        self.assertFalse(self.bridge.state()["focused"])
        self.assertEqual(self.native.focus_calls, [])

    def test_popup_with_foreground_owner_accepts_real_native_menu_events(self):
        self.open_dialog()
        self.windows.records[120]["visible"] = True
        self.windows.active = 110
        self.bridge.watchdog()
        self.assertEqual(self.latest.selected["hwnd"], 120)
        self.assertNotEqual(self.windows.active, 120)
        self.publish()
        self.assertTrue(self.bridge.state()["focused"])
        self.dispatch("key", key="DOWN", action="press")
        self.dispatch("key", key="ENTER", action="press")
        self.assertEqual(self.native.sent, [[("key", "DOWN", "down"), ("key", "DOWN", "up")],
                                            [("key", "ENTER", "down"), ("key", "ENTER", "up")]])
        self.assertEqual(self.native.delivery_selection, [120, 120])

    def test_unproven_or_foreign_foreground_owner_never_authorizes_popup(self):
        self.open_dialog()
        self.windows.records[120]["visible"] = True
        self.windows.records[400]["visible"] = True
        for foreground in (100, 400, 999):
            with self.subTest(foreground=foreground):
                self.windows.active = foreground
                self.assertFalse(self.native.foreground(120))
        self.windows.records[120]["owner_hwnd"] = 999
        self.windows.records[120]["menu_owner_hwnd"] = 999
        self.windows.active = 999
        self.assertFalse(self.native.foreground(120))
        self.assertEqual(self.native.sent, [])

    def test_child_owned_combo_popup_follows_its_foreground_dialog_without_activation(self):
        self.open_dialog()
        self.windows.add(115, 300, "ComboBox", visible=False)
        self.windows.records[115]["parent_hwnd"] = 110
        self.windows.add(130, 300, "ComboLBox")
        self.windows.records[130]["parent_hwnd"] = 115
        scope = self.latest.window_scope
        self.assertEqual(self.windows.active, 110)
        self.assertTrue(self.native.foreground(130), "the child ComboBox's real GA_ROOT is the foreground dialog")
        self.bridge.watchdog()
        self.assertEqual(self.latest.selected["hwnd"], 130)
        self.assertEqual(self.latest.window_scope, scope)
        self.publish()
        self.assertTrue(self.bridge.state()["ready"])
        self.assertTrue(self.bridge.state()["focused"])
        self.dispatch("key", key="DOWN", action="press")
        self.dispatch("key", key="ENTER", action="press")
        self.assertEqual(self.native.delivery_selection, [130, 130])
        self.assertEqual(self.native.sent, [[("key", "DOWN", "down"), ("key", "DOWN", "up")],
                                          [("key", "ENTER", "down"), ("key", "ENTER", "up")]])
        self.assertEqual(self.windows.active, 110)
        self.assertEqual(self.native.focus_calls, [])
        self.assertEqual(self.windows.activation_calls, [])

    def test_child_owned_combo_popup_refuses_another_main_window_or_foreign_foreground(self):
        self.open_dialog()
        self.windows.add(115, 300, "ComboBox", visible=False)
        self.windows.records[115]["parent_hwnd"] = 110
        self.windows.add(130, 300, "ComboLBox")
        self.windows.records[130]["parent_hwnd"] = 115
        self.windows.add(105, 200, "GHOST_WindowClass", executable=r"C:\fixture\blender.exe")
        self.latest.select(self.windows.identity(130), preserve_scope=True)
        self.publish()
        for foreground in (100, 105, 400, 999):
            with self.subTest(foreground=foreground):
                self.windows.active = foreground
                self.assertFalse(self.native.foreground(130), "sharing a native Blender PID is not the popup's foreground owner")
                self.reject(self.event("key", key="ENTER", action="press"), "selected_window_not_foreground")
        self.assertEqual(self.native.sent, [])
        self.assertEqual(self.native.focus_calls, [])
        self.assertEqual(self.windows.activation_calls, [])

    def test_window_change_releases_owned_inputs_before_selection_and_invalidates_old_session(self):
        self.dispatch("key", key="CTRL", action="down")
        self.dispatch("button", button="left", action="down", x=0, y=0)
        stale = self.event("text", text="must not reach dialog")
        generation, scope = self.latest.generation, self.latest.window_scope
        self.windows.records[110]["visible"] = True
        self.windows.active = 110
        self.bridge.watchdog()
        self.assertEqual(self.native.sent[-1], [("button", "left", "up"), ("key", "CTRL", "up")])
        self.assertEqual(self.native.delivery_selection[-1], 100)
        self.assertEqual(self.latest.selected["hwnd"], 110)
        self.assertEqual(self.latest.window_scope, scope)
        self.assertFalse(self.bridge.held_keys | self.bridge.held_buttons)
        self.assertFalse(self.bridge.state()["ready"])
        self.assertFalse(self.latest.publish_jpeg(generation, b"queued-old-frame", 800, 300, "stale", 0, 999, {}))
        self.publish()
        self.reject(stale, "stale_input_session")
        self.assertEqual(len(self.native.sent), 3)

    def test_failed_owned_release_blocks_automatic_and_explicit_handoff(self):
        self.dispatch("key", key="SHIFT", action="down")
        self.windows.records[110]["visible"] = True
        self.windows.active = 110
        self.native.fail_releases = True
        self.bridge.watchdog()
        self.assertEqual(self.latest.selected["hwnd"], 100)
        self.assertTrue(self.bridge.release_error)
        self.assertEqual(self.bridge.held_keys, {"SHIFT"})
        self.reject(self.event("select_window", hwnd=110), "release_pending")
        self.assertEqual(self.latest.selected["hwnd"], 100)
        self.assertEqual(self.native.focus_calls, [])
        self.native.fail_releases = False
        self.bridge.watchdog()
        self.assertEqual(self.latest.selected["hwnd"], 110)
        self.assertFalse(self.bridge.release_error)
        self.assertFalse(self.bridge.held_keys)

    def test_fresh_dialog_geometry_maps_full_downscaled_image_to_negative_physical_pixels(self):
        self.open_dialog()
        for x, y in ((0, 0), (1, 1), (0.5, 0.5)):
            self.dispatch("pointer", x=x, y=y)
        self.assertEqual(self.native.sent, [[("move", -1800, -700)], [("move", -201, -101)],
                                            [("move", -1000, -400)]])
        state = self.bridge.state()
        self.assertEqual(state["image"], {"width": 800, "height": 300})
        self.assertEqual(state["geometry"]["dpi"], 192)
        self.assertEqual((state["geometry"]["left"], state["geometry"]["top"]), (-1800, -700))

    def test_geometry_or_dpi_change_needs_new_frame_and_old_session_never_sends(self):
        self.open_dialog()
        old = self.event("pointer", x=1, y=1)
        self.windows.records[110].update(dpi=144, window_rect=[-908, -408, -92, -92],
                                          visible_rect=[-900, -400, -100, -100])
        self.reject(old, "stale_input_session")
        self.assertFalse(self.bridge.state()["ready"])
        self.publish()
        self.reject(old, "stale_input_session")
        self.dispatch("pointer", x=1, y=1)
        self.assertEqual(self.native.sent, [[("move", -101, -101)]])

    def test_same_target_geometry_cannot_hide_recycled_dialog_process(self):
        self.open_dialog()
        old = self.event("text", text="forbidden")
        self.windows.stamps[300] += 1
        with self.assertRaises(InputRejected) as context:
            self.native.inspect(self.latest.selected)
        self.assertEqual(context.exception.reason, "selected_process_identity_changed")
        self.publish()
        self.assertFalse(self.bridge.state()["ready"])
        self.assertEqual(self.bridge.state()["reason"], "capture_geometry_unverified")
        self.reject(old, "stale_input_session")
        self.assertEqual(self.native.sent, [])

    def test_local_picker_dialog_also_pins_target_birth_not_only_blender_birth(self):
        self.windows.records[110]["visible"] = True
        self.windows.active = 110
        self.latest.select(self.windows.identity(110))
        self.publish()
        self.assertTrue(self.bridge.state()["ready"])
        old = self.event("text", text="must not reach a recycled picker target")
        self.windows.stamps[300] += 1
        with self.assertRaises(InputRejected) as context:
            self.native.inspect(self.latest.selected)
        self.assertEqual(context.exception.reason, "selected_process_identity_changed")
        self.publish()
        self.assertIsNone(self.latest.input_geometry)
        self.assertFalse(self.bridge.state()["ready"])
        self.assertEqual(self.bridge.state()["reason"], "capture_geometry_unverified")
        self.reject(old, "stale_input_session")
        self.assertEqual(self.native.sent, [])

    def test_recycled_blender_root_invalidates_dialog_and_all_inventory(self):
        self.open_dialog()
        self.windows.stamps[200] += 1
        with self.assertRaises(InputRejected) as context:
            self.native.inspect(self.latest.selected)
        self.assertEqual(context.exception.reason, "selected_process_identity_changed")
        self.publish()
        state = self.bridge.state()
        self.assertFalse(state["ready"])
        self.assertEqual(state["reason"], "capture_geometry_unverified")
        self.assertEqual(state["windows"], [])
        self.reject(self.event("select_window", hwnd=100), "window_outside_selected_process")
        self.assertEqual(self.native.sent, [])

    def test_owner_change_under_same_root_invalidates_selected_dialog(self):
        self.open_dialog()
        self.windows.add(111, 300, "#32770", owner=100)
        self.windows.records[110]["owner_hwnd"] = 111
        state = self.bridge.state()
        self.assertEqual(state["reason"], "selected_window_owner_changed")
        self.assertFalse(state["ready"])
        self.assertEqual(self.native.sent, [])

    def test_unverified_inventory_and_foreign_blender_root_cannot_be_selected(self):
        self.windows.records[400]["visible"] = True
        self.windows.records[140]["visible"] = True
        admitted = {item["hwnd"] for item in self.bridge.state()["windows"]}
        self.assertNotIn(400, admitted)
        self.assertNotIn(140, admitted)
        self.reject(self.event("select_window", hwnd=400), "window_outside_selected_process")
        self.reject(self.event("select_window", hwnd=140), "window_outside_selected_process")
        # Even a corrupt inventory must be revalidated against the live root.
        forged = {**self.windows.identity(400), "blender_pid": 200, "blender_hwnd": 100}
        self.windows.inventory_override = [forged]
        self.reject(self.event("select_window", hwnd=400), "selected_window_owner_changed")
        self.windows.active = 400
        self.bridge.watchdog()
        self.assertEqual(self.latest.selected["hwnd"], 100)
        self.assertEqual(self.native.sent, [])

    def test_explicit_local_picker_rotates_scope_and_permits_new_verified_root(self):
        previous = self.bridge.state()
        self.windows.records[400]["visible"] = True
        self.windows.active = 400
        self.latest.select(self.windows.identity(400))
        self.assertNotEqual(self.latest.window_scope, previous["window_scope"])
        self.assertFalse(self.bridge.state()["ready"])
        self.assertEqual(self.bridge.state()["windows"], [])
        self.publish()
        current = self.bridge.state()
        self.assertTrue(current["ready"])
        self.assertEqual(current["selection"]["blender_pid"], 500)
        self.assertEqual(current["selection"]["blender_process_started"], 500001)
        self.assertNotEqual(current["session"], previous["session"])
        self.assertEqual(current["next_seq"], 1)

    def test_follow_does_not_steal_selection_for_other_foreground_application(self):
        scope, generation = self.latest.window_scope, self.latest.generation
        self.windows.records[400]["visible"] = True
        self.windows.active = 400
        self.bridge.watchdog()
        self.assertEqual((self.latest.window_scope, self.latest.generation), (scope, generation))
        self.assertEqual(self.latest.selected["hwnd"], 100)
        self.assertEqual(self.native.focus_calls, [])

    def test_explicit_inventory_selection_preserves_scope_and_requires_fresh_dialog_pixels(self):
        before = self.bridge.state()
        old = self.event("key", key="A", action="press")
        self.windows.records[110]["visible"] = True
        result = self.dispatch("select_window", hwnd=110)
        self.assertTrue(result["selection_changed"])
        self.assertEqual(self.latest.window_scope, before["window_scope"])
        self.assertEqual(self.latest.selected["hwnd"], 110)
        self.assertIsNone(self.latest.input_geometry)
        self.assertIsNone(self.latest.jpeg)
        self.assertFalse(self.bridge.state()["ready"])
        self.publish()
        current = self.bridge.state()
        self.assertTrue(current["ready"])
        self.assertNotEqual(current["session"], before["session"])
        self.assertEqual(current["next_seq"], 1)
        self.reject(old, "stale_input_session")
        self.assertEqual(self.native.sent, [])

    def test_explicit_selection_releases_then_activates_once_and_waits_for_target_pixels(self):
        self.dispatch("key", key="CTRL", action="down")
        before = self.bridge.state()
        self.windows.records[110]["visible"] = True
        requested = self.event("select_window", hwnd=110)

        def observe_activation(hwnd):
            self.assertEqual(hwnd, 110)
            self.assertFalse(self.bridge.held_keys | self.bridge.held_buttons)
            self.assertEqual(self.latest.selected["hwnd"], 100, "cleanup and activation precede capture selection")
            self.assertEqual(self.native.sent[-1], [("key", "CTRL", "up")])

        self.windows.activation_hook = observe_activation
        response = self.bridge.dispatch(requested)
        self.assertEqual(response, {"ok": True, "seq": requested["seq"], "selection_changed": True})
        self.assertEqual(self.native.focus_calls, [110])
        self.assertEqual(self.windows.activation_calls, [110])
        self.assertEqual(self.windows.active, 110)
        self.assertEqual(self.latest.selected["hwnd"], 110)
        self.assertEqual(self.latest.window_scope, before["window_scope"])
        self.assertEqual(self.native.delivery_selection, [100, 100])
        self.assertIsNone(self.latest.jpeg)
        self.assertIsNone(self.latest.input_geometry)
        self.assertFalse(self.bridge.state()["ready"])
        self.reject(requested, "stale_input_session")
        self.assertEqual(self.windows.activation_calls, [110], "an old request is never replayed as another activation")
        self.publish()
        self.assertTrue(self.bridge.state()["ready"])
        self.assertTrue(self.bridge.state()["focused"])

    def test_denied_explicit_focus_keeps_selection_and_pixels_without_replay(self):
        self.windows.records[110]["visible"] = True
        self.windows.activation_allowed = False
        before = (self.latest.selected.copy(), self.latest.generation, self.latest.jpeg,
                  self.latest.captured_ms, self.latest.sequence)
        requested = self.event("select_window", hwnd=110)
        self.reject(requested, "foreground_activation_denied")
        self.assertEqual((self.latest.selected, self.latest.generation, self.latest.jpeg,
                          self.latest.captured_ms, self.latest.sequence), before)
        self.assertEqual(self.native.focus_calls, [110])
        self.assertEqual(self.windows.activation_calls, [110])
        self.assertEqual(self.windows.active, 100)
        self.assertEqual(self.native.sent, [])
        self.reject(requested, "unexpected_input_sequence")
        self.assertEqual(self.windows.activation_calls, [110])

    def test_failed_release_prevents_explicit_focus_and_capture_handoff(self):
        self.dispatch("key", key="SHIFT", action="down")
        self.windows.records[110]["visible"] = True
        self.native.fail_releases = True
        before = (self.latest.selected.copy(), self.latest.generation, self.latest.jpeg, self.latest.captured_ms)
        self.reject(self.event("select_window", hwnd=110), "release_pending")
        self.assertTrue(self.bridge.release_error)
        self.assertEqual(self.bridge.held_keys, {"SHIFT"})
        self.assertEqual(self.native.focus_calls, [])
        self.assertEqual(self.windows.activation_calls, [])
        self.assertEqual((self.latest.selected, self.latest.generation, self.latest.jpeg,
                          self.latest.captured_ms), before)
        self.assertEqual(self.native.delivery_selection, [100, 100])

    def test_lifetime_or_owner_change_during_explicit_focus_cannot_select_target(self):
        self.windows.records[110]["visible"] = True
        self.windows.add(111, 300, "#32770", owner=100, visible=False)
        baseline = dict(self.windows.records[110])
        for cause, reason in (("target_process", "selected_process_identity_changed"),
                              ("blender_process", "selected_process_identity_changed"),
                              ("owner", "selected_window_owner_changed"),
                              ("closed", "selected_window_closed")):
            with self.subTest(cause=cause):
                self.windows.active = 100
                before = (self.latest.selected.copy(), self.latest.generation, self.latest.jpeg,
                          self.latest.captured_ms, self.latest.sequence)

                def change_during_focus(hwnd, cause=cause):
                    self.assertEqual(hwnd, 110)
                    if cause == "target_process":
                        self.windows.stamps[300] += 1
                    elif cause == "blender_process":
                        self.windows.stamps[200] += 1
                    elif cause == "owner":
                        self.windows.records[110]["owner_hwnd"] = 111
                    else:
                        del self.windows.records[110]

                self.windows.activation_hook = change_during_focus
                self.reject(self.event("select_window", hwnd=110), reason)
                self.assertEqual((self.latest.selected, self.latest.generation, self.latest.jpeg,
                                  self.latest.captured_ms, self.latest.sequence), before)
                self.assertEqual(self.native.sent, [])
                self.windows.records[110] = dict(baseline)
                self.windows.stamps[200], self.windows.stamps[300] = 200001, 300001
                self.windows.activation_hook = None
        self.assertEqual(self.native.focus_calls, [110] * 4)
        self.assertEqual(self.windows.activation_calls, [110] * 4)

    def test_focus_loss_during_final_dialog_inspection_never_sends_to_another_application(self):
        self.open_dialog()
        requested = self.event("key", key="A", action="press")
        inspect = self.native.inspect
        calls = []

        def inspect_then_lose_focus(selected):
            live = inspect(selected)
            calls.append(selected["hwnd"])
            if len(calls) == 2:  # _snapshot first; immediate pre-delivery inspection second.
                self.windows.active = 400
            return live

        with patch.object(self.native, "inspect", side_effect=inspect_then_lose_focus):
            self.reject(requested, "selected_window_not_foreground")
        self.assertEqual(self.windows.active, 400)
        self.assertEqual(self.native.sent, [])
        self.assertFalse(self.bridge.held_keys | self.bridge.held_buttons)

    def test_explicit_same_window_picker_resets_scope_and_prevents_old_session_reuse(self):
        old = self.event("pointer", x=0, y=0)
        scope = self.latest.window_scope
        self.latest.select(self.windows.identity(100))
        self.assertNotEqual(self.latest.window_scope, scope)
        self.publish()
        self.reject(old, "stale_input_session")
        self.assertTrue(self.bridge.state()["ready"])
        self.assertEqual(self.native.sent, [])

    def test_disabled_bridge_never_auto_follows_dialogs_or_sends_cleanup_events(self):
        disabled = InputBridge(self.latest, self.native, enabled=False)
        scope, generation = self.latest.window_scope, self.latest.generation
        self.windows.records[110]["visible"] = True
        self.windows.active = 110
        disabled.watchdog()
        self.assertEqual(disabled.state()["reason"], "input_disabled")
        self.assertEqual((self.latest.window_scope, self.latest.generation), (scope, generation))
        self.assertEqual(self.latest.selected["hwnd"], 100)
        self.assertEqual(self.native.sent, [])


class DialogLoopbackTests(unittest.TestCase):
    setUp_fixture = DialogInputTests.setUp
    publish = DialogInputTests.publish
    event = DialogInputTests.event

    def setUp(self):
        self.setUp_fixture()
        self.server = make_server(self.latest, 0, self.bridge)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)
        self.assertFalse(self.worker.is_alive())

    def request(self, method, path, payload=None):
        body = json.dumps(payload) if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        with closing(http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)) as client:
            client.request(method, path, body=body, headers=headers)
            response = client.getresponse()
            return response.status, json.loads(response.read())

    def test_loopback_dialog_handoff_exposes_root_identity_and_never_replays_old_input(self):
        code, before = self.request("GET", "/input/state")
        self.assertEqual(code, 200)
        old = {"session": before["session"], "token": before["token"], "seq": before["next_seq"],
               "type": "text", "text": "old document text"}
        self.windows.records[110]["visible"] = True
        self.windows.active = 110
        self.bridge.watchdog()
        _, waiting = self.request("GET", "/input/state")
        self.assertFalse(waiting["ready"])
        self.assertEqual(waiting["window_scope"], before["window_scope"])
        self.assertEqual(self.request("POST", "/input", old), (409, {"ok": False, "reason": "stale_input_session"}))
        self.publish()
        _, ready = self.request("GET", "/input/state")
        self.assertTrue(ready["ready"])
        self.assertEqual((ready["selection"]["pid"], ready["selection"]["blender_pid"]), (300, 200))
        self.assertEqual((ready["selection"]["input_process_started"], ready["selection"]["blender_process_started"]),
                         (300001, 200001))
        self.assertEqual(ready["next_seq"], 1)
        event = {"session": ready["session"], "token": ready["token"], "seq": ready["next_seq"],
                 "type": "key", "key": "ESC", "action": "press"}
        self.assertEqual(self.request("POST", "/input", event)[0], 200)
        self.assertEqual(self.request("POST", "/input", event),
                         (409, {"ok": False, "reason": "unexpected_input_sequence"}))
        self.assertEqual(self.native.sent, [[("key", "ESC", "down"), ("key", "ESC", "up")]])

    def test_busy_loopback_mutation_is_refused_without_queue_then_old_session_stays_refused(self):
        queued = self.event("text", text="never queued")
        self.bridge.lock.acquire()
        try:
            self.assertEqual(self.request("POST", "/input", queued), (429, {"ok": False, "reason": "input_busy"}))
        finally:
            self.bridge.lock.release()
        self.windows.records[110]["visible"] = True
        self.windows.active = 110
        self.bridge.watchdog()
        self.publish()
        self.assertEqual(self.request("POST", "/input", queued), (409, {"ok": False, "reason": "stale_input_session"}))
        self.assertEqual(self.native.sent, [])


if __name__ == "__main__":
    unittest.main()

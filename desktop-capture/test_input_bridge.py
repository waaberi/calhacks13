"""P2.5 input regressions. Every native call is a fake; never controls the desktop."""

import ctypes as C
import http.client
import json
import os
import threading
import time
import unittest
from contextlib import closing
from ctypes import wintypes as W
from types import SimpleNamespace
from unittest.mock import patch

from capture_helper import LatestFrame, graphics_capture_loop, make_server
from input_bridge import InputBridge, InputRejected, NativeInput, WindowsInput


class FakeNative:
    def __init__(self):
        self.window = {"hwnd": 100, "pid": 200, "title": "Blender document"}
        self.popup = {"hwnd": 101, "pid": 200, "title": "Blender Preferences"}
        self.geometry = {"window_rect": [92, 42, 1716, 974],
                         "visible_rect": [100, 50, 1708, 966], "dpi": 144,
                         "process_started": 123456}
        self.focused = True
        self.focus_allowed = True
        self.visible = True
        self.available = True
        self.occluded = False
        self.sent = []
        self.focus_calls = []
        self.physical_keys = set()
        self.physical_buttons = set()
        self.fail_next = False

    def inspect(self, selected):
        if not self.available or selected["pid"] != self.window["pid"]:
            raise InputRejected("selected_window_closed")
        if not self.visible:
            raise InputRejected("selected_window_hidden_or_minimized")
        return dict(self.geometry)

    def windows_for(self, selected, process_started):
        if not self.available or process_started != self.geometry["process_started"]:
            return []
        return [dict(w) for w in (self.window, self.popup) if w["pid"] == selected["pid"]]

    def foreground(self, _):
        return self.focused

    def focus(self, hwnd):
        self.focus_calls.append(hwnd)
        self.focused = self.focus_allowed
        return self.focused

    def target_visible(self, *_):
        return not self.occluded

    def key_is_down(self, key):
        return key in self.physical_keys

    def button_is_down(self, button):
        return button in self.physical_buttons

    def send(self, events):
        self.sent.append(list(events))
        if self.fail_next:
            self.fail_next = False
            raise InputRejected("native_input_delivery_failed", 502)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.latest, self.native = LatestFrame(), FakeNative()
        self.now = 10
        self.bridge = InputBridge(self.latest, self.native, enabled=True, clock=lambda: self.now)
        self.latest.select(self.native.window)
        self.publish()

    def publish(self, raw=(1608, 916), image=(804, 458)):
        geometry = self.bridge.frame_geometry(self.latest.selected, *raw, "graphics")
        self.latest.publish_jpeg(self.latest.generation, b"jpeg", *image, "Blender", 10,
                                 self.latest.captured_ms + 1, geometry)

    def event(self, kind, **values):
        state = self.bridge.state()
        return {"session": state["session"], "token": state["token"],
                "seq": state["next_seq"], "type": kind, **values}

    def dispatch(self, kind, **values):
        return self.bridge.dispatch(self.event(kind, **values))

    def reject(self, reason, payload):
        with self.assertRaises(InputRejected) as context:
            self.bridge.dispatch(payload)
        self.assertEqual(context.exception.reason, reason)

    def test_downscaled_full_image_maps_to_exact_visible_physical_rectangle(self):
        self.dispatch("pointer", x=0, y=0)
        self.dispatch("pointer", x=1, y=1)
        self.dispatch("pointer", x=0.5, y=0.5)
        self.assertEqual(self.native.sent, [[("move", 100, 50)], [("move", 1707, 965)],
                                            [("move", 904, 508)]])

    def test_print_capture_uses_full_window_rectangle_not_visible_border(self):
        geometry = self.bridge.frame_geometry(self.native.window, 1624, 932, "print")
        self.latest.publish_jpeg(self.latest.generation, b"jpeg", 812, 466, "Blender", 10,
                                 self.latest.captured_ms + 1, geometry)
        self.dispatch("pointer", x=0, y=0)
        self.assertEqual(self.native.sent[-1], [("move", 92, 42)])

    def test_ambiguous_or_unrecognized_capture_crop_rejects_input(self):
        self.publish(raw=(1600, 900))
        state = self.bridge.state()
        self.assertFalse(state["ready"])
        self.reject("capture_geometry_unverified", self.event("pointer", x=0, y=0))
        self.assertEqual(self.native.sent, [])

    def test_ordinary_capture_default_exposes_no_control(self):
        disabled = InputBridge(self.latest, self.native)
        state = disabled.state()
        self.assertFalse(state["enabled"])
        self.assertIsNone(state["token"])
        self.reject("invalid_input_token", {**self.event("pointer", x=0, y=0), "token": "wrong"})
        with self.assertRaises(InputRejected) as context:
            disabled.dispatch({})
        self.assertEqual(context.exception.reason, "input_disabled")

    def test_stale_selection_geometry_resize_and_dpi_reject_old_session(self):
        for change in ("window_rect", "visible_rect", "dpi"):
            with self.subTest(change=change):
                self.setUp()
                old = self.event("pointer", x=0.5, y=0.5)
                if change == "dpi":
                    self.native.geometry[change] += 48
                else:
                    self.native.geometry[change] = [n + 10 for n in self.native.geometry[change]]
                self.reject("stale_input_session", old)
                self.assertFalse(self.bridge.state()["ready"])
                self.publish()
                self.assertTrue(self.bridge.state()["ready"])
                self.assertFalse(self.native.sent)

    def test_same_shape_new_selection_and_closed_or_minimized_window_reject(self):
        old = self.event("pointer", x=0, y=0)
        self.latest.select(self.native.popup)
        self.publish()
        self.reject("stale_input_session", old)
        self.native.available = False
        self.assertEqual(self.bridge.state()["reason"], "selected_window_closed")
        self.native.available = True
        self.native.visible = False
        self.assertEqual(self.bridge.state()["reason"], "selected_window_hidden_or_minimized")
        self.assertFalse(self.native.sent)

    def test_expired_pixels_disable_input_even_when_window_still_exists(self):
        old = self.event("button", button="left", action="click", x=0, y=0)
        self.latest.last_success = time.monotonic() - 4
        self.reject("stale_input_session", old)
        self.assertEqual(self.bridge.state()["reason"], "capture_unavailable")
        self.assertFalse(self.native.sent)

    def test_focus_is_explicit_verified_and_never_implicitly_retried(self):
        self.native.focused = False
        self.reject("selected_window_not_foreground", self.event("pointer", x=0, y=0))
        self.assertFalse(self.native.focus_calls)
        self.native.focus_allowed = False
        self.reject("foreground_activation_denied", self.event("focus"))
        self.assertEqual(self.native.focus_calls, [100])
        self.native.focus_allowed = True
        self.dispatch("focus")
        self.dispatch("pointer", x=0, y=0)
        self.assertEqual(self.native.focus_calls, [100, 100])

    def test_occlusion_blocks_click_even_with_selected_window_in_foreground(self):
        self.native.occluded = True
        self.reject("selected_window_occluded_at_pointer",
                    self.event("button", button="left", action="click", x=0.5, y=0.5))
        self.assertFalse(self.native.sent)

    def test_native_pointer_drag_double_click_and_both_scroll_axes(self):
        self.dispatch("button", button="left", action="down", x=0.2, y=0.3)
        self.dispatch("pointer", x=0.4, y=0.5)
        self.assertEqual(self.bridge.held_buttons, {"left"})
        self.dispatch("button", button="left", action="up", x=0.4, y=0.5)
        self.dispatch("button", button="right", action="double_click", x=0.4, y=0.5)
        self.assertEqual(self.native.sent[-1][1:], [("button", "right", a)
                                                   for a in ("down", "up", "down", "up")])
        self.dispatch("scroll", x=0.5, y=0.5, dx=-1, dy=2.5)
        self.assertEqual(self.native.sent[-1][1:], [("wheel", "x", -120), ("wheel", "y", 300)])
        self.assertFalse(self.bridge.held_buttons)

    def test_modifiers_shortcuts_and_unicode_numeric_entry_are_native_events(self):
        self.dispatch("key", key="CTRL", action="down")
        self.dispatch("key", key="z", action="press")
        self.dispatch("key", key="CTRL", action="up")
        self.dispatch("text", text="12.5 mm\U0001f600")
        self.assertEqual(self.native.sent[1], [("key", "Z", "down"), ("key", "Z", "up")])
        self.assertIn(("unicode", 0xD83D, "down"), self.native.sent[-1])
        self.assertIn(("unicode", 0xDE00, "up"), self.native.sent[-1])
        self.assertFalse(self.bridge.held_keys)

    def test_physically_held_key_is_not_overwritten(self):
        self.native.physical_keys.add("SHIFT")
        self.reject("key_held_by_other_input", self.event("key", key="SHIFT", action="down"))
        self.assertFalse(self.bridge.held_keys)
        self.assertFalse(self.native.sent)

    def test_physically_held_mouse_button_is_not_overwritten(self):
        self.native.physical_buttons.add("left")
        self.reject("button_held_by_other_input",
                    self.event("button", button="left", action="click", x=0, y=0))
        self.assertFalse(self.bridge.held_buttons)
        self.assertFalse(self.native.sent)

    def test_invalid_payloads_are_rejected_before_send(self):
        cases = [("pointer", {"x": float("nan"), "y": 0}),
                 ("pointer", {"x": -0.1, "y": 0}),
                 ("pointer", {"x": True, "y": 0}),
                 ("button", {"button": {}, "action": "click", "x": 0, "y": 0}),
                 ("key", {"key": "WIN", "action": "press"}),
                 ("text", {"text": "x" * 257}),
                 ("text", {"text": "\ud800"}),
                 ("scroll", {"x": 0, "y": 0, "dy": 21})]
        for kind, values in cases:
            with self.subTest(kind=kind, values=values), self.assertRaises(InputRejected):
                self.dispatch(kind, **values)
        self.assertFalse(self.native.sent)

    def test_duplicate_or_out_of_order_sequence_never_replays_mutation(self):
        click = self.event("button", button="left", action="click", x=0, y=0)
        self.bridge.dispatch(click)
        self.reject("unexpected_input_sequence", click)
        self.reject("unexpected_input_sequence", {**click, "seq": 100})
        self.assertEqual(len(self.native.sent), 1)

    def test_failed_native_send_consumes_sequence_and_releases_possible_down(self):
        event = self.event("key", key="CTRL", action="down")
        self.native.fail_next = True
        self.reject("native_input_delivery_failed", event)
        self.assertEqual(self.native.sent[-1], [("key", "CTRL", "up")])
        self.assertFalse(self.bridge.held_keys)
        self.reject("unexpected_input_sequence", event)
        self.assertEqual(len(self.native.sent), 2)

    def test_held_inputs_expire_or_release_on_focus_loss(self):
        self.dispatch("button", button="left", action="down", x=0, y=0)
        self.dispatch("key", key="SHIFT", action="down")
        self.now += 1
        self.dispatch("heartbeat")
        self.now += 1
        self.bridge.watchdog()
        self.assertEqual(self.bridge.held_keys, {"SHIFT"})
        self.now += 1
        self.bridge.watchdog()
        self.assertFalse(self.bridge.held_buttons)
        self.assertFalse(self.bridge.held_keys)
        self.dispatch("key", key="ALT", action="down")
        self.native.focused = False
        self.bridge.watchdog()
        self.assertEqual(self.native.sent[-1], [("key", "ALT", "up")])

    def test_window_selection_is_explicit_and_confined_to_same_blender_process(self):
        self.reject("window_outside_selected_process", self.event("select_window", hwnd=999))
        result = self.dispatch("select_window", hwnd=101)
        self.assertTrue(result["selection_changed"])
        self.assertEqual(self.latest.selected["hwnd"], 101)
        self.assertFalse(self.bridge.state()["ready"])

    def test_closed_or_minimized_popup_can_explicitly_return_to_previously_confirmed_process(self):
        self.bridge.state()  # Bind the original fresh-frame process identity.
        for reason in ("no_window", "minimized"):
            with self.subTest(reason=reason):
                self.latest.fail(self.latest.generation, reason, "Restore or choose another window")
                self.assertFalse(self.bridge.state()["ready"])
                result = self.dispatch("select_window", hwnd=101)
                self.assertTrue(result["selection_changed"])
                self.assertEqual(self.latest.selected["hwnd"], 101)
        self.assertFalse(self.native.sent)

    def test_closed_popup_never_authorizes_recycled_process_id(self):
        self.bridge.state()
        self.latest.fail(self.latest.generation, "no_window", "Popup closed")
        self.native.geometry["process_started"] += 1
        self.assertEqual(self.bridge.state()["windows"], [])
        self.reject("window_outside_selected_process", self.event("select_window", hwnd=101))
        self.assertFalse(self.native.sent)

    def test_recycled_pid_and_hwnd_cannot_rebind_without_explicit_picker_selection(self):
        self.bridge.state()
        self.native.geometry["process_started"] += 1
        self.publish()
        self.assertEqual(self.bridge.state()["reason"], "selected_process_identity_changed")
        self.assertEqual(self.bridge.state()["windows"], [])

    def test_concurrent_dispatch_is_rejected_without_queue(self):
        payload = self.event("pointer", x=0, y=0)
        self.bridge.lock.acquire()
        try:
            self.reject("input_busy", payload)
        finally:
            self.bridge.lock.release()
        self.assertFalse(self.native.sent)


class InputHttpTests(unittest.TestCase):
    publish = BridgeTests.publish
    event = BridgeTests.event

    def setUp(self):
        BridgeTests.setUp(self)
        self.server = make_server(self.latest, 0, self.bridge)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def request(self, method, path, body=None, headers=None):
        with closing(http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)) as client:
            client.request(method, path, body=body, headers=headers or {})
            response = client.getresponse()
            return response.status, response.read()

    def test_http_state_and_authenticated_event(self):
        code, body = self.request("GET", "/input/state")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["ready"])
        self.assertEqual(json.loads(body)["capture_generation"], self.latest.generation)
        self.assertEqual(json.loads(body)["capture_instance"], self.latest.capture_instance)
        self.assertEqual(json.loads(body)["frame"], self.latest.sequence)
        self.assertEqual(json.loads(body)["helper_pid"], os.getpid())
        self.assertEqual(json.loads(body)["capture_geometry"], self.latest.capture_geometry)
        payload = self.event("key", key="ESC", action="press")
        code, body = self.request("POST", "/input", json.dumps(payload),
                                  {"Content-Type": "application/json"})
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_browser_origins_and_host_spoofing_cannot_read_token_or_mutate(self):
        for headers in ({"Origin": "http://attacker.invalid"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "same-origin"}, {"Host": "attacker.invalid"}):
            self.assertEqual(self.request("GET", "/input/state", headers=headers)[0], 403)
            self.assertEqual(self.request("POST", "/input", "{}", headers)[0], 403)
        self.assertFalse(self.native.sent)

    def test_body_and_token_validation(self):
        headers = {"Content-Type": "application/json"}
        for body in ("{", "x" * 8193):
            self.assertEqual(self.request("POST", "/input", body, headers)[0], 400)
        self.assertEqual(self.request("POST", "/input", "{}")[0], 415)
        bad = {**self.event("pointer", x=0, y=0), "token": "invalid"}
        self.assertEqual(self.request("POST", "/input", json.dumps(bad), headers)[0], 403)
        self.assertFalse(self.native.sent)

    def post_event(self, payload):
        code, body = self.request("POST", "/input", json.dumps(payload),
                                  {"Content-Type": "application/json"})
        return code, json.loads(body)

    def test_non_ascii_or_surrogate_token_is_forbidden_without_breaking_http(self):
        for token in ("\u00e9", "\ud800"):
            with self.subTest(token=repr(token)):
                code, result = self.post_event({**self.event("pointer", x=0, y=0), "token": token})
                self.assertEqual((code, result["reason"]), (403, "invalid_input_token"))
        self.assertFalse(self.native.sent)

    def test_huge_json_integer_coordinates_and_scroll_are_bounded_without_overflow(self):
        for kind, values in (("pointer", {"x": 10 ** 1000, "y": 0}),
                             ("scroll", {"x": 0, "y": 0, "dy": 10 ** 1000})):
            with self.subTest(kind=kind):
                code, result = self.post_event(self.event(kind, **values))
                self.assertEqual((code, result["reason"]), (400, "number_out_of_range"))
        self.assertFalse(self.native.sent)

    def test_focus_does_not_acknowledge_or_activate_window_when_held_release_failed(self):
        self.assertEqual(self.post_event(self.event("key", key="CTRL", action="down"))[0], 200)
        event = self.event("focus")
        self.native.fail_next = True
        code, result = self.post_event(event)
        self.assertEqual((code, result["reason"]), (502, "release_pending"))
        self.assertEqual(self.native.focus_calls, [])
        self.assertTrue(self.bridge.release_error)
        self.assertEqual(self.bridge.held_keys, {"CTRL"})
        self.assertEqual(self.post_event(self.event("release"))[0], 200)
        self.assertFalse(self.bridge.release_error)
        self.assertFalse(self.bridge.held_keys)

    def test_context_rejected_before_dispatch_never_sends_phantom_key_or_button_up(self):
        for kind, values in (("key", {"key": "SHIFT", "action": "down"}),
                             ("button", {"button": "left", "action": "down", "x": 0, "y": 0}),
                             ("text", {"text": "a"})):
            with self.subTest(kind=kind):
                event = self.event(kind, **values)
                original = dict(self.native.geometry)
                resized = {**original, "dpi": original["dpi"] + 48}
                with patch.object(self.native, "inspect", side_effect=[original, resized]):
                    code, result = self.post_event(event)
                self.assertEqual((code, result["reason"]), (409, "window_geometry_changed_wait_for_frame"))
                self.assertFalse(self.bridge.held_keys)
                self.assertFalse(self.bridge.held_buttons)
                self.assertFalse(self.native.sent)

    def test_context_rejection_still_releases_earlier_owned_inputs_without_new_phantom_ups(self):
        self.assertEqual(self.post_event(self.event("key", key="CTRL", action="down"))[0], 200)
        event = self.event("key", key="SHIFT", action="down")
        original = dict(self.native.geometry)
        with patch.object(self.native, "inspect", side_effect=[original, {**original, "dpi": 192}]):
            code, result = self.post_event(event)
        self.assertEqual((code, result["reason"]), (409, "window_geometry_changed_wait_for_frame"))
        self.assertEqual(self.native.sent, [[("key", "CTRL", "down")], [("key", "CTRL", "up")]])
        self.assertFalse(self.bridge.held_keys)

    def test_watchdog_releases_and_invalidates_stale_held_gesture_once(self):
        self.assertEqual(self.post_event(self.event("key", key="SHIFT", action="down"))[0], 200)
        stale = self.event("key", key="A", action="press")
        self.now += 2
        self.bridge.watchdog()
        code, body = self.request("GET", "/input/state")
        state = json.loads(body)
        self.assertEqual(code, 200)
        self.assertNotEqual(state["session"], stale["session"])
        self.assertEqual(state["next_seq"], 1)
        self.assertEqual(self.post_event(stale), (409, {"ok": False, "reason": "stale_input_session"}))
        self.assertEqual(self.native.sent, [[("key", "SHIFT", "down")], [("key", "SHIFT", "up")]])
        self.bridge.watchdog()
        self.assertEqual(self.bridge.state()["session"], state["session"])

    def test_failed_watchdog_release_preserves_session_for_explicit_cleanup_then_stays_stable(self):
        self.assertEqual(self.post_event(self.event("button", button="left", action="down", x=0, y=0))[0], 200)
        before = self.bridge.state()["session"]
        self.native.fail_next = True
        self.now += 2
        self.bridge.watchdog()
        state = self.bridge.state()
        self.assertTrue(state["release_error"])
        self.assertEqual(state["session"], before)
        self.assertEqual(self.post_event(self.event("release"))[0], 200)
        self.bridge.watchdog()
        self.assertEqual(self.bridge.state()["session"], before)
        self.assertFalse(self.bridge.release_error)

    def test_no_held_input_watchdog_and_heartbeats_preserve_session(self):
        before = self.bridge.state()["session"]
        self.now += 2
        self.bridge.watchdog()
        self.assertEqual(self.post_event(self.event("heartbeat"))[0], 200)
        self.now += 2
        self.bridge.watchdog()
        self.assertEqual(self.bridge.state()["session"], before)
        self.assertFalse(self.native.sent)


class WindowsAdapterTests(unittest.TestCase):
    def test_process_creation_stamp_is_read_from_owned_handle_and_handle_is_released(self):
        closed = []

        def process_times(handle, created, *_):
            self.assertEqual(handle, 42)
            value = C.cast(created, C.POINTER(W.FILETIME)).contents
            value.dwHighDateTime, value.dwLowDateTime = 123, 456
            return True

        native = WindowsInput.__new__(WindowsInput)
        native.windows = SimpleNamespace(k=SimpleNamespace(
            OpenProcess=lambda *_: 42, GetProcessTimes=process_times, CloseHandle=closed.append))
        self.assertEqual(native.process_stamp(200), (123 << 32) | 456)
        self.assertEqual(closed, [42])

    def test_sendinput_structures_and_flags_with_mocked_win32_only(self):
        delivered = []

        def send(count, array, size):
            self.assertEqual(size, C.sizeof(NativeInput))
            for record in array:
                delivered.append((record.type, record.mi.dx, record.mi.dy, record.mi.dwFlags,
                                  record.mi.mouseData, record.ki.wVk, record.ki.wScan, record.ki.dwFlags))
            return count

        native = WindowsInput.__new__(WindowsInput)
        native.u = SimpleNamespace(GetSystemMetrics=lambda n: {76: -1920, 77: 0, 78: 3840, 79: 1080}[n],
                                   SendInput=send)
        native.send([("move", -1920, 0), ("move", 1919, 1079), ("button", "left", "down"),
                     ("button", "left", "up"), ("wheel", "y", -120),
                     ("key", "LEFT", "down"), ("key", "LEFT", "up"),
                     ("unicode", 0x00E9, "down"), ("unicode", 0x00E9, "up")])
        self.assertEqual(delivered[0][1:4], (0, 0, 0xC001))
        self.assertEqual(delivered[1][1:4], (65535, 65535, 0xC001))
        self.assertEqual(delivered[2][3], 2)
        self.assertEqual(delivered[3][3], 4)
        self.assertEqual(delivered[4][3:5], (0x800, 0xFFFFFF88))
        self.assertEqual(delivered[5][5:], (0x25, 0, 1))
        self.assertEqual(delivered[6][7], 3)
        self.assertEqual(delivered[7][5:], (0, 0xE9, 4))
        self.assertEqual(delivered[8][7], 6)


class CaptureGeometryTests(unittest.TestCase):
    def test_actual_mocked_graphics_callback_preserves_geometry_across_downscale(self):
        import numpy as np

        captures = []

        class FakeCapture:
            def __init__(self, **_):
                self.callbacks = {}
                captures.append(self)

            def event(self, callback):
                self.callbacks[callback.__name__] = callback
                return callback

            def start_free_threaded(self):
                return SimpleNamespace(stop=lambda: None, is_finished=lambda: False)

        latest, native = LatestFrame(), FakeNative()
        native.geometry = {"window_rect": [0, 0, 4000, 10],
                           "visible_rect": [0, 0, 4000, 10], "dpi": 192,
                           "process_started": 123456}
        latest.select(native.window)
        bridge = InputBridge(latest, native, enabled=True)
        latest.input_bridge = bridge
        api = SimpleNamespace(identity=lambda hwnd: {**native.window, "hwnd": hwnd},
                              u=SimpleNamespace(IsIconic=lambda _: False))
        stop = threading.Event()

        def wait_until(predicate):
            deadline = time.monotonic() + 3
            while not predicate() and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertTrue(predicate())

        with patch("windows_capture.WindowsCapture", FakeCapture):
            worker = threading.Thread(target=graphics_capture_loop,
                                      args=(api, latest, stop, 60), daemon=True)
            worker.start()
            try:
                wait_until(lambda: bool(captures))
                captures[0].callbacks["on_frame_arrived"](
                    SimpleNamespace(frame_buffer=np.full((10, 4000, 4), 100, dtype=np.uint8)),
                    SimpleNamespace(stop=lambda: None))
                wait_until(lambda: latest.snapshot()[1] is not None)
                state = bridge.state()
                self.assertTrue(state["ready"])
                self.assertEqual(state["image"], {"width": 3840, "height": 9})
                self.assertEqual(state["geometry"]["width"], 4000)
                bridge.dispatch({"session": state["session"], "token": state["token"],
                                 "seq": state["next_seq"], "type": "pointer", "x": 1, "y": 1})
                self.assertEqual(native.sent[-1], [("move", 3999, 9)])
            finally:
                stop.set()
                worker.join(3)
                self.assertFalse(worker.is_alive())
                for encoder in threading.enumerate():
                    if encoder.name.startswith("Latest JPEG encoder"):
                        encoder.join(1)


if __name__ == "__main__":
    unittest.main()

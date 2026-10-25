"""Production dialog capture paths with fake Win32/GDI/WGC; no native capture."""

import ctypes as C
import io
import sys
import threading
import unittest
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from capture_helper import (
    LatestFrame,
    Windows,
    WindowUnavailable,
    capture_dialog_snapshot,
    graphics_capture_loop,
    selected_window_identity,
)
from input_bridge import InputBridge
from PIL import Image
from test_dialog_input import FakeWindowSystem, RecordingWindowsInput


class FakePrintWindows(FakeWindowSystem):
    """Use real Windows.capture; its selected-window pixel APIs only log/fill RAM."""

    capture = Windows.capture

    def __init__(self):
        super().__init__()
        for item in self.records.values():
            item["window_rect"] = [-308, -208, -92, -92]
            item["visible_rect"] = [-300, -200, -100, -100]
        self.pixel_calls, self.cleaned = [], []
        self.black, self.print_ok, self.read_ok = False, True, True
        self.after_read = None
        self.u.GetWindowDC = self.get_dc
        self.u.ReleaseDC = lambda hwnd, dc: self.cleaned.append(("release", hwnd, dc))
        self.u.PrintWindow = self.print_window
        self.g = SimpleNamespace(
            CreateCompatibleDC=lambda dc: 2,
            CreateCompatibleBitmap=self.bitmap,
            SelectObject=lambda dc, obj: 4,
            DeleteObject=lambda obj: self.cleaned.append(("bitmap", obj)),
            DeleteDC=lambda dc: self.cleaned.append(("dc", dc)),
            GetDIBits=self.read_bits,
        )

    def get_dc(self, hwnd):
        self.pixel_calls.append(("dc", hwnd))
        return 1

    def bitmap(self, dc, width, height):
        self.pixel_calls.append(("bitmap", width, height))
        self.bitmap_size = width, height
        return 3

    def print_window(self, hwnd, dc, flags):
        self.pixel_calls.append(("print", hwnd, flags))
        return self.print_ok

    def read_bits(self, dc, bitmap, start, height, pixels, header, mode):
        self.pixel_calls.append(("read", height))
        width, actual_height = self.bitmap_size
        data = (b"\0\0\0\0" if self.black else b"\x80\x60\x40\0") * (width * actual_height)
        C.memmove(pixels, data, len(data))
        if self.after_read:
            self.after_read()
        return height if self.read_ok else 0


class ScriptedStop:
    """Advance the loop without sleeps, then stop its owned encoder threads."""

    def __init__(self, maximum, action=None):
        self.stopped = threading.Event()
        self.maximum, self.action, self.steps = maximum, action, 0

    def is_set(self):
        return self.stopped.is_set()

    def wait(self, timeout):
        self.steps += 1
        if self.action:
            self.action(self.steps, timeout)
        if self.steps >= self.maximum:
            self.stopped.set()
        return self.stopped.is_set()


class DialogCaptureTests(unittest.TestCase):
    def setUp(self):
        self.latest, self.windows = LatestFrame(), FakePrintWindows()
        self.native = RecordingWindowsInput(self.windows, self.latest)
        self.bridge = InputBridge(self.latest, self.native, enabled=True)
        self.latest.input_bridge = self.windows.input_bridge = self.bridge
        self.latest.select(self.windows.identity(100))
        geometry = self.bridge.frame_geometry(self.latest.selected, 200, 100, "graphics")
        self.latest.publish_jpeg(self.latest.generation, b"initial-root-frame", 200, 100,
                                 "root", 0, 1, geometry)
        self.assertTrue(self.bridge.state()["ready"])
        self.select(110)

    def select(self, hwnd):
        self.windows.records[hwnd]["visible"] = True
        self.windows.active = hwnd
        selected = self.windows.identity(hwnd)
        selected.update(input_process_started=self.windows.stamps[selected["pid"]],
                        blender_process_started=self.windows.stamps[selected["blender_pid"]])
        self.latest.select(selected, preserve_scope=True)
        return self.latest.selected

    def snapshot(self, timestamp=100):
        with patch("capture_helper.time.time", return_value=timestamp):
            return capture_dialog_snapshot(self.windows, self.latest, self.latest.selected, self.latest.generation)

    def assert_no_pixels(self):
        self.assertEqual(self.windows.pixel_calls, [])
        self.assertEqual(self.native.sent, [])

    def test_owner_and_declared_target_metadata_are_rechecked_before_pixel_calls(self):
        original = dict(self.latest.selected)
        for field, value in (("pid", 301), ("window_class", "ChangedClass"),
                             ("owner_hwnd", 120), ("parent_hwnd", 120),
                             ("menu_owner_hwnd", 120), ("blender_hwnd", 400), ("blender_pid", 500)):
            with self.subTest(field=field):
                selected = {**original, field: value}
                self.assertIsNone(selected_window_identity(self.windows, selected))
                with self.assertRaises(WindowUnavailable):
                    self.windows.capture(selected)
                self.assert_no_pixels()
        del self.windows.records[100]
        with self.assertRaises(WindowUnavailable):
            self.snapshot()
        self.assert_no_pixels()

    def test_dialog_and_blender_birth_stamps_are_rechecked_before_pixels(self):
        for pid in (300, 200):
            with self.subTest(pid=pid):
                self.windows.stamps[pid] += 1
                self.assertIsNone(selected_window_identity(self.windows, self.latest.selected))
                with self.assertRaises(WindowUnavailable):
                    self.snapshot()
                self.assert_no_pixels()
                self.windows.stamps[pid] -= 1

    def test_existing_scope_root_binding_cannot_be_replaced_by_new_raw_metadata(self):
        self.bridge.process_binding = (self.latest.generation, 200, 999999)
        self.assertIsNone(selected_window_identity(self.windows, self.latest.selected))
        with self.assertRaises(WindowUnavailable):
            self.snapshot()
        self.assert_no_pixels()

    def test_print_bounds_and_geometry_describe_the_actual_downscaled_jpeg(self):
        self.windows.records[110].update(window_rect=[-4008, -208, 8, -100],
                                          visible_rect=[-4000, -200, 0, -108], dpi=192)
        self.assertTrue(self.snapshot())
        status, jpeg, captured_ms = self.latest.snapshot()
        image = Image.open(io.BytesIO(jpeg))
        self.assertEqual(image.size, (3840, 103))
        self.assertEqual((status["width"], status["height"]), image.size)
        self.assertEqual(captured_ms, 100000)
        geometry = self.latest.input_geometry
        self.assertEqual((geometry["left"], geometry["top"], geometry["width"], geometry["height"]),
                         (-4008, -208, 4016, 108))
        self.assertEqual(geometry["source"], "window_rect")
        self.assertEqual((geometry["dpi"], geometry["process_started"], geometry["blender_process_started"]),
                         (192, 300001, 200001))
        self.assertEqual(self.windows.pixel_calls[0:3], [("dc", 110), ("bitmap", 4016, 108), ("print", 110, 2)])
        self.assertTrue(self.latest.capture_geometry)
        self.assertEqual(self.native.sent, [])

    def test_late_old_generation_capture_cannot_replace_new_selection_pixels(self):
        selected, generation = dict(self.latest.selected), self.latest.generation

        def switch_selection():
            self.select(100)
            self.latest.publish_jpeg(self.latest.generation, b"new-root-pixels", 200, 100, "root", 0, 20, {})

        self.windows.after_read = switch_selection
        with patch("capture_helper.time.time", return_value=100):
            self.assertFalse(capture_dialog_snapshot(self.windows, self.latest, selected, generation))
        self.assertEqual(self.latest.selected["hwnd"], 100)
        self.assertEqual(self.latest.snapshot()[1:3], (b"new-root-pixels", 20))
        self.assertEqual(self.native.sent, [])

    def test_owner_process_or_geometry_change_during_read_cannot_publish_fresh_pixels(self):
        self.windows.add(111, 300, "#32770", owner=100, visible=False)
        original = deepcopy(self.windows.records[110])
        stamps = dict(self.windows.stamps)
        before = (self.latest.sequence, self.latest.captured_ms, self.latest.jpeg, self.latest.last_success)

        def change(cause):
            if cause == "owner":
                self.windows.records[110]["owner_hwnd"] = 111
            elif cause == "target_process":
                self.windows.stamps[300] += 1
            elif cause == "blender_process":
                self.windows.stamps[200] += 1
            elif cause == "geometry":
                self.windows.records[110]["window_rect"] = [-288, -188, -72, -72]
                self.windows.records[110]["visible_rect"] = [-280, -180, -80, -80]
            else:
                self.windows.records[110]["dpi"] = 144

        for cause in ("owner", "target_process", "blender_process", "geometry", "dpi"):
            with self.subTest(cause=cause):
                self.windows.after_read = lambda cause=cause: change(cause)
                with self.assertRaises(WindowUnavailable):
                    self.snapshot()
                self.assertEqual((self.latest.sequence, self.latest.captured_ms, self.latest.jpeg,
                                  self.latest.last_success), before)
                self.windows.records[110] = deepcopy(original)
                self.windows.stamps.update(stamps)
        self.assertEqual(self.native.sent, [])

    def test_black_failed_and_unreadable_print_frames_never_renew_pixels_or_timestamp(self):
        self.assertTrue(self.snapshot())
        previous = self.latest.snapshot()
        sequence, last_success = self.latest.sequence, self.latest.last_success
        for field, value in (("black", True), ("print_ok", False), ("read_ok", False)):
            with self.subTest(field=field):
                setattr(self.windows, field, value)
                with self.assertRaises(WindowUnavailable):
                    self.snapshot(timestamp=200)
                self.assertEqual(self.latest.snapshot(), previous)
                self.assertEqual((self.latest.sequence, self.latest.last_success), (sequence, last_success))
                setattr(self.windows, field, not value)
        self.assertEqual(len([call for call in self.windows.cleaned if call[0] == "release"]), 4)
        with patch("capture_helper.time.monotonic", return_value=last_success + 4):
            self.assertIsNone(self.latest.snapshot()[1], "failed frames cannot extend the previous freshness lease")

    def test_disabled_and_native_root_never_use_dialog_print_fallback(self):
        self.bridge.enabled = False
        self.assertFalse(self.snapshot())
        self.bridge.enabled = True
        self.select(100)
        self.assertFalse(self.snapshot())
        self.latest.input_bridge = None
        self.select(110)
        self.assertFalse(self.snapshot())
        self.assert_no_pixels()

    @contextmanager
    def fake_graphics(self, *, fail_start=True, on_start=None):
        captures = []

        class FakeCapture:
            def __init__(inner, **options):
                inner.options, inner.callbacks, inner.stops = options, {}, 0
                captures.append(inner)

            def event(inner, callback):
                inner.callbacks[callback.__name__] = callback
                return callback

            def start_free_threaded(inner):
                if fail_start:
                    raise RuntimeError("fake selected-window WGC start failure")
                control = SimpleNamespace(stop=lambda: setattr(inner, "stops", inner.stops + 1),
                                          is_finished=lambda: False)
                if on_start:
                    on_start(inner, control)
                return control

        existing_threads = set(threading.enumerate())
        with patch.dict(sys.modules, {"windows_capture": SimpleNamespace(WindowsCapture=FakeCapture),
                                      "cv2": SimpleNamespace(error=RuntimeError)}):
            try:
                yield captures
            finally:
                for thread in set(threading.enumerate()) - existing_threads:
                    if thread.name.startswith("Latest JPEG encoder"):
                        thread.join(1)
                        self.assertFalse(thread.is_alive(), "test-owned JPEG worker must stop")

    def run_graphics(self, stop):
        # Each successful snapshot receives a genuinely new capture timestamp.
        ticks = iter(range(100, 1000))
        try:
            with patch("capture_helper.time.time", side_effect=lambda: next(ticks)):
                graphics_capture_loop(self.windows, self.latest, stop, 30)
        finally:
            stop.stopped.set()

    def test_actual_graphics_loop_start_failure_latches_print_until_new_generation(self):
        generations = []

        def advance(step, _):
            if step == 3:
                generations.append(self.latest.generation)
                self.select(120)

        stop = ScriptedStop(5, advance)
        with self.fake_graphics() as captures:
            self.run_graphics(stop)
        self.assertEqual([item.options["window_hwnd"] for item in captures], [110, 120])
        self.assertEqual([call[1] for call in self.windows.pixel_calls if call[0] == "print"], [110, 110, 120, 120])
        self.assertEqual(self.latest.generation, generations[0] + 1)
        self.assertEqual(self.latest.selected["hwnd"], 120)
        self.assertEqual(self.latest.status["state"], "capturing")
        self.assertEqual(self.latest.input_geometry["process_started"], 300001)
        self.assertEqual(self.native.sent, [])

    def test_actual_graphics_loop_stall_uses_one_selected_dialog_fallback(self):
        stop = ScriptedStop(4)
        with self.fake_graphics(fail_start=False) as captures, patch("capture_helper.capture_refresh_due", return_value=True):
            self.run_graphics(stop)
        self.assertEqual(len(captures), 1)
        self.assertEqual(captures[0].stops, 1)
        self.assertEqual([call[1] for call in self.windows.pixel_calls if call[0] == "print"], [110, 110])
        self.assertEqual(self.latest.status["state"], "capturing")

    def test_actual_graphics_loop_black_fallback_frame_does_not_extend_freshness(self):
        first = []

        def black_after_first(step, _):
            if step == 2:
                first.append((self.latest.sequence, self.latest.captured_ms, self.latest.last_success))
                self.windows.black = True

        stop = ScriptedStop(3, black_after_first)
        with self.fake_graphics() as captures:
            self.run_graphics(stop)
        self.assertEqual(len(captures), 1)
        self.assertEqual((self.latest.sequence, self.latest.captured_ms, self.latest.last_success), first[0])
        self.assertEqual(self.latest.status["state"], "error")
        self.assertIsNone(self.latest.snapshot()[1])
        self.assertEqual(len([call for call in self.windows.pixel_calls if call[0] == "print"]), 2)

    def test_actual_graphics_loop_never_broadens_failed_root_or_disabled_dialog_capture(self):
        for hwnd, enabled in ((100, True), (110, False)):
            with self.subTest(hwnd=hwnd, enabled=enabled):
                self.select(hwnd)
                self.bridge.enabled = enabled
                stop = ScriptedStop(3)
                with self.fake_graphics() as captures:
                    self.run_graphics(stop)
                self.assertEqual(len(captures), 1)
                self.assertEqual(self.latest.status["state"], "error")
                self.assertIsNone(self.latest.snapshot()[1])
                self.assert_no_pixels()

    def test_actual_wgc_callback_refuses_recycled_dialog_before_reading_frame_pixels(self):
        def recycled(capture, control):
            self.windows.stamps[300] += 1
            capture.callbacks["on_frame_arrived"](SimpleNamespace(), control)

        stop = ScriptedStop(2)
        with self.fake_graphics(fail_start=False, on_start=recycled) as captures, \
                patch("capture_helper.owned_capture_pixels", side_effect=AssertionError("unsafe frame read")):
            self.run_graphics(stop)
        self.assertEqual(self.latest.status["state"], "no_window")
        self.assertIsNone(self.latest.snapshot()[1])
        self.assertGreaterEqual(captures[0].stops, 1)
        self.assert_no_pixels()


if __name__ == "__main__":
    unittest.main()

"""HTTP contract and stale-frame/selection regression tests. No desktop is captured."""

import http.client
import json
import sys
import threading
import time
import types
import unittest
from collections import deque
from contextlib import closing, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from capture_helper import (
    LatestFrame,
    capture_refresh_due,
    graphics_capture_loop,
    make_server,
    measured_frame_rate,
    owned_capture_pixels,
)
from PIL import Image

try:
    import cv2  # noqa: F401 -- graphics_capture_loop imports it.
    import numpy as np
except ImportError:
    np = None


class CaptureContractTests(unittest.TestCase):
    def setUp(self):
        self.latest = LatestFrame()
        self.server = make_server(self.latest, 0)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def get(self, path, headers=None):
        with closing(
            http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        ) as client:
            client.request("GET", path, headers=headers or {})
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()

    def publish(self):
        self.latest.publish(
            self.latest.generation,
            Image.new("RGB", (64, 48), "blue"),
            "Blender",
            10,
            max(int(time.time() * 1000), self.latest.captured_ms + 1),
        )

    def test_no_window_returns_unavailable_not_stale_image(self):
        code, _, body = self.get("/frame")
        self.assertEqual(code, 503)
        self.assertIn(b'"state": "no_window"', body)

    def test_jpeg_headers_and_conditional_get(self):
        self.publish()
        code, headers, body = self.get("/frame")
        self.assertEqual(code, 200)
        self.assertEqual(headers["Content-Type"], "image/jpeg")
        self.assertEqual(headers["X-Size"], "64x48")
        self.assertTrue(body.startswith(b"\xff\xd8"))
        code, _, body = self.get("/frame", {"If-None-Match": headers["ETag"]})
        self.assertEqual((code, body), (304, b""))

    def test_failure_invalidates_previous_image(self):
        self.publish()
        self.latest.fail(0, "minimized", "Restore Blender")
        code, _, body = self.get("/frame")
        self.assertEqual(code, 503)
        self.assertIn(b'"minimized"', body)

    def test_stalled_capture_never_serves_previous_image(self):
        self.publish()
        self.latest.last_success -= 4
        code, _, body = self.get("/frame")
        self.assertEqual(code, 503)
        self.assertIn(b"stalled", body)

    def test_selection_change_discards_inflight_old_frame(self):
        self.latest.select({"title": "New window"})
        self.latest.publish(0, Image.new("RGB", (64, 48), "red"), "Old window", 10, 123)
        self.assertEqual(self.get("/frame")[0], 503)
        self.assertEqual(self.latest.snapshot()[0]["window"], "New window")

    def test_selection_identity_is_separate_from_status_schema(self):
        self.latest.select({"hwnd": 123, "pid": 456, "title": "Blender"})
        code, _, body = self.get("/selection")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {"hwnd": 123, "pid": 456, "title": "Blender"})
        self.assertNotIn("hwnd", json.loads(self.get("/status")[2]))

    def test_latest_only_never_queues(self):
        for _ in range(20):
            self.publish()
        code, headers, _ = self.get("/frame")
        self.assertEqual(code, 200)
        self.assertEqual(headers["ETag"], '"20"')

    def test_slow_encoder_cannot_publish_older_pixels_after_a_newer_frame(self):
        self.assertTrue(self.latest.publish_jpeg(0, b"new", 10, 10, "Blender", 40, 200))
        self.assertFalse(self.latest.publish_jpeg(0, b"old", 10, 10, "Blender", 40, 100))
        status, jpeg, captured = self.latest.snapshot()
        self.assertEqual((status["frame"], jpeg, captured), (1, b"new", 200))
        self.latest.select({"title": "New document window"})
        self.assertTrue(self.latest.publish_jpeg(1, b"next", 10, 10, "New", 40, 150))

    def test_host_header_rejects_nonlocal_origin_and_unknown_path(self):
        self.assertEqual(self.get("/status", {"Host": "attacker.invalid"})[0], 403)
        self.assertEqual(self.get("/not-found")[0], 404)

    def test_second_helper_cannot_bind_the_same_port(self):
        with self.assertRaises(OSError):
            make_server(LatestFrame(), self.server.server_port)

    def test_server_requests_cannot_certify_a_frozen_image_as_healthy(self):
        self.publish()
        self.latest.last_success -= 4
        for _ in range(3):
            self.assertEqual(self.get("/frame")[0], 503)

    def test_static_or_stalled_callback_requires_a_fresh_snapshot(self):
        self.assertFalse(capture_refresh_due(10, 11.9))
        self.assertTrue(capture_refresh_due(10, 12))
        self.assertTrue(capture_refresh_due(10, 7200))

    def test_async_encoder_owns_pixels_independent_of_native_frame(self):
        import numpy as np
        pixels = np.zeros((8, 12, 4), dtype=np.uint8)
        frame = type("Frame", (), {"frame_buffer": pixels})()
        queued = owned_capture_pixels(frame)
        pixels[:] = 255
        self.assertTrue(queued.flags.c_contiguous)
        self.assertFalse(np.shares_memory(queued, pixels))
        self.assertEqual(int(queued.max()), 0)

    def test_rate_measurement_tolerates_coincident_clock_readings(self):
        self.assertEqual(measured_frame_rate(deque(), 5.0), 0)
        self.assertEqual(measured_frame_rate(deque([5.0, 5.0]), 5.0), 0)
        self.assertEqual(measured_frame_rate(deque([5.0, 5.5, 6.0]), 6.0), 2.0)


class FakeControl:
    def __init__(self, fail_stop):
        self.finished = False
        self.fail_stop = fail_stop

    def stop(self):
        self.finished = True
        if self.fail_stop:
            # What windows-capture 2.0.1 raises when the native thread ended with an error.
            raise Exception("Failed to stop the capture thread: frame handler error")  # noqa: TRY002

    def is_finished(self):
        return self.finished


class FakeCapture:
    def __init__(self, harness, **settings):
        self.harness, self.settings, self.callbacks = harness, settings, {}

    def event(self, handler):
        self.callbacks[handler.__name__] = handler
        return handler

    def start_free_threaded(self):
        if self.harness.start_failures:
            self.harness.start_failures -= 1
            raise Exception("Failed to find window: closed while starting")  # noqa: TRY002
        control = FakeControl(self.harness.fail_stop)
        self.harness.captures.append((self, control))
        return control


class FakeApi:
    u = SimpleNamespace(IsIconic=lambda hwnd: False)

    def identity(self, hwnd):
        return {"hwnd": hwnd, "pid": 7, "title": f"Blender {hwnd}"}


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class GraphicsWorkerTests(unittest.TestCase):
    """The real graphics capture/encoder threads, with a fake windows_capture module."""

    def setUp(self):
        self.thread_errors = []
        hook = patch("threading.excepthook", lambda args: self.thread_errors.append(args.exc_value))
        hook.start()
        self.addCleanup(hook.stop)

    @contextmanager
    def workers(self, start_failures=0, fail_stop=False):
        latest = LatestFrame()
        latest.select({"hwnd": 101, "pid": 7, "title": "Blender 101"})
        harness = SimpleNamespace(captures=[], start_failures=start_failures, fail_stop=fail_stop)
        module = types.ModuleType("windows_capture")
        module.WindowsCapture = lambda **settings: FakeCapture(harness, **settings)
        stop = threading.Event()
        with patch.dict(sys.modules, {"windows_capture": module}):
            loop = threading.Thread(
                target=graphics_capture_loop, args=(FakeApi(), latest, stop, 60), daemon=True
            )
            loop.start()
            try:
                yield harness, latest, loop
            finally:
                stop.set()
                loop.join(2)
        self.assertEqual(self.thread_errors, [])

    def wait_until(self, predicate, timeout=3):
        until = time.perf_counter() + timeout  # One test pins time.monotonic().
        while not predicate() and time.perf_counter() < until:
            time.sleep(0.005)
        self.assertTrue(predicate(), "capture threads did not reach the expected state")

    def arrive(self, capture, pixels):
        time.sleep(0.005)  # Distinct X-Captured-At milliseconds.
        capture.callbacks["on_frame_arrived"](
            SimpleNamespace(frame_buffer=pixels), SimpleNamespace(stop=lambda: None)
        )

    def test_empty_native_frame_reports_error_then_next_frame_recovers(self):
        with self.workers() as (harness, latest, _):
            self.wait_until(lambda: harness.captures)
            capture = harness.captures[0][0]
            self.arrive(capture, np.empty((0, 12, 4), np.uint8))
            self.wait_until(lambda: latest.snapshot()[0]["state"] == "error")
            self.assertIsNone(latest.snapshot()[1])
            self.arrive(capture, np.full((8, 12, 4), 64, np.uint8))
            self.wait_until(lambda: latest.snapshot()[1] is not None)
            self.assertEqual(latest.snapshot()[0]["state"], "capturing")

    def test_publications_at_one_clock_reading_keep_the_encoder_running(self):
        # time.monotonic() ticks every 15.6 ms on Windows before Python 3.13.
        clock = patch("capture_helper.time.monotonic", return_value=1000.0)
        with clock, self.workers() as (harness, latest, _):
            self.wait_until(lambda: harness.captures)
            capture = harness.captures[0][0]
            for frame in (1, 2, 3):
                self.arrive(capture, np.full((8, 12, 4), 40 * frame, np.uint8))
                self.wait_until(lambda frame=frame: latest.snapshot()[0]["frame"] == frame)

    def test_capture_start_error_is_reported_and_retried(self):
        with self.workers(start_failures=1) as (harness, latest, loop):
            self.wait_until(lambda: latest.snapshot()[0]["message"].startswith("Graphics capture"))
            self.wait_until(lambda: harness.captures)
            self.arrive(harness.captures[0][0], np.full((8, 12, 4), 64, np.uint8))
            self.wait_until(lambda: latest.snapshot()[1] is not None)
            self.assertTrue(loop.is_alive())

    def test_reselection_survives_a_capture_that_ended_with_an_error(self):
        with self.workers(fail_stop=True) as (harness, latest, loop):
            self.wait_until(lambda: harness.captures)
            latest.select({"hwnd": 202, "pid": 7, "title": "Blender 202"})
            self.wait_until(lambda: len(harness.captures) == 2)
            capture = harness.captures[1][0]
            self.assertEqual(capture.settings["window_hwnd"], 202)
            self.arrive(capture, np.full((8, 12, 4), 64, np.uint8))
            self.wait_until(lambda: latest.snapshot()[0]["window"] == "Blender 202")
            self.assertTrue(loop.is_alive())


if __name__ == "__main__":
    unittest.main()

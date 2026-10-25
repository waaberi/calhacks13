"""HTTP contract and stale-frame/selection regression tests. No desktop is captured."""

import http.client
import io
import json
import os
import sys
import threading
import time
import types
import unittest
from contextlib import closing, contextmanager, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from capture_helper import (
    LatestFrame,
    RecoveryLog,
    capture_refresh_due,
    graphics_capture_loop,
    make_server,
    measured_frame_rate,
    owned_capture_pixels,
    secondary_blender_window,
)
from PIL import Image

try:
    import cv2
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

    def test_static_window_reopen_is_logged_once_a_minute(self):
        log = RecoveryLog(every=60)
        first = log.note(0)
        self.assertEqual(first, "CAPTURE_RECOVERY no_new_callback; reopening selected window")
        self.assertEqual([log.note(t) for t in range(2, 60, 2)], [None] * 29)
        self.assertEqual(log.note(60), first + " (29 more since the last message)")
        self.assertIsNone(log.note(62))

    def test_only_main_blender_windows_are_offered(self):
        for title in ("Blender Preferences", "Blender Render", "Blender File View",
                      "Blender Drivers", "Blender Info"):
            self.assertTrue(secondary_blender_window(title), title)
        for title in ("* (Unsaved) - Blender 5.2.2 LTS",
                      "bracket.blend - C:\\work\\bracket.blend - Blender 5.2.2 LTS",
                      "Blender test.blend - C:\\Blender test.blend - Blender 5.2.2 LTS", ""):
            self.assertFalse(secondary_blender_window(title), title)

    def test_async_encoder_owns_pixels_independent_of_native_frame(self):
        import numpy as np
        pixels = np.zeros((8, 12, 4), dtype=np.uint8)
        frame = type("Frame", (), {"frame_buffer": pixels})()
        queued = owned_capture_pixels(frame)
        pixels[:] = 255
        self.assertTrue(queued.flags.c_contiguous)
        self.assertFalse(np.shares_memory(queued, pixels))
        self.assertEqual(int(queued.max()), 0)

    def test_owned_bgr_snapshot_preserves_padded_source_channels_and_identical_jpeg(self):
        import cv2
        import numpy as np

        backing = np.arange(8 * 16 * 4, dtype=np.uint8).reshape(8, 16, 4)
        mapped = backing[:, :12]
        self.assertFalse(mapped.flags.c_contiguous)
        owned = owned_capture_pixels(SimpleNamespace(frame_buffer=mapped))
        self.assertTrue(owned.flags.c_contiguous)
        self.assertFalse(np.shares_memory(owned, mapped))
        np.testing.assert_array_equal(owned, mapped[:, :, :3])
        settings = [cv2.IMWRITE_JPEG_QUALITY, 95, cv2.IMWRITE_JPEG_SAMPLING_FACTOR,
                    cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444]
        self.assertEqual(cv2.imencode(".jpg", mapped, settings)[1].tobytes(),
                         cv2.imencode(".jpg", owned, settings)[1].tobytes())
        backing[:] = 0
        self.assertGreater(int(owned.max()), 0)

    def test_coincident_clock_ticks_never_crash_capture_rate_reporting(self):
        self.assertEqual(measured_frame_rate([100, 100], 100), 0)
        self.assertEqual(measured_frame_rate([100], 100), 0)
        self.assertAlmostEqual(measured_frame_rate([100, 100.025, 100.05], 100.05), 40)

    @contextmanager
    def actual_graphics_workers(self):
        captures = []
        refresh = threading.Event()
        reached_publication = threading.Event()
        release_publication = threading.Event()
        blocked = [False]
        stop = threading.Event()
        thread_errors = []

        def iconic(_):
            if threading.current_thread().name.startswith("Latest JPEG encoder") and not blocked[0]:
                blocked[0] = True
                reached_publication.set()
                release_publication.wait(4)
            return False

        class FakeCapture:
            def __init__(self, **_):
                self.callbacks = {}
                captures.append(self)

            def event(self, handler):
                self.callbacks[handler.__name__] = handler
                return handler

            def start_free_threaded(self):
                return SimpleNamespace(stop=lambda: None, is_finished=lambda: False)

        def refresh_due(*_):
            if refresh.is_set():
                refresh.clear()
                return True
            return False

        api = SimpleNamespace(identity=lambda hwnd: {"hwnd": hwnd, "pid": 2, "title": "Blender"},
                              u=SimpleNamespace(IsIconic=iconic))
        latest = LatestFrame()
        latest.select({"hwnd": 1, "pid": 2, "title": "Blender"})
        with patch("windows_capture.WindowsCapture", FakeCapture), \
             patch("capture_helper.capture_refresh_due", refresh_due), \
             patch("threading.excepthook", thread_errors.append):
            worker = threading.Thread(target=graphics_capture_loop, args=(api, latest, stop, 60), daemon=True)
            worker.start()
            try:
                self.wait_until(lambda: bool(captures))
                yield SimpleNamespace(captures=captures, refresh=refresh, reached=reached_publication,
                                      release=release_publication, latest=latest)
            finally:
                release_publication.set()
                stop.set()
                worker.join(3)
                self.assertFalse(worker.is_alive())
                for encoder in threading.enumerate():
                    if encoder.name.startswith("Latest JPEG encoder"):
                        encoder.join(1)
                self.assertFalse(thread_errors, [str(error.exc_value) for error in thread_errors])

    def wait_until(self, predicate):
        until = time.monotonic() + 3
        while not predicate() and time.monotonic() < until:
            time.sleep(0.005)
        self.assertTrue(predicate(), "Actual graphics workers did not reach the expected state")

    @unittest.skipUnless(os.name == "nt", "Windows capture binding")
    def test_empty_callback_reports_unavailable_then_valid_pixels_recover(self):
        import numpy as np

        with self.actual_graphics_workers() as run:
            callback = run.captures[0].callbacks["on_frame_arrived"]
            callback(SimpleNamespace(frame_buffer=np.empty((0, 12, 4), dtype=np.uint8)),
                     SimpleNamespace(stop=lambda: None))
            self.assertEqual(run.latest.snapshot()[0]["state"], "error")
            self.assertIsNone(run.latest.snapshot()[1])
            run.release.set()
            callback(SimpleNamespace(frame_buffer=np.full((8, 12, 4), 64, dtype=np.uint8)),
                     SimpleNamespace(stop=lambda: None))
            self.wait_until(lambda: run.latest.snapshot()[1] is not None)
            self.assertEqual(run.latest.snapshot()[0]["state"], "capturing")

    @unittest.skipUnless(os.name == "nt", "Windows capture binding")
    def test_epoch_change_during_final_publication_cannot_resurrect_old_pixels(self):
        import numpy as np

        with self.actual_graphics_workers() as run:
            frame = SimpleNamespace(frame_buffer=np.full((8, 12, 4), 32, dtype=np.uint8))
            run.captures[0].callbacks["on_frame_arrived"](frame, SimpleNamespace(stop=lambda: None))
            self.assertTrue(run.reached.wait(2))  # Past the first session check, before final publication.
            run.refresh.set()
            self.wait_until(lambda: len(run.captures) >= 2)
            run.release.set()
            time.sleep(0.1)
            self.assertIsNone(run.latest.snapshot()[1])

    @unittest.skipUnless(os.name == "nt", "Windows capture binding")
    def test_two_actual_encoders_allow_new_frame_to_overtake_blocked_old_frame(self):
        import cv2
        import numpy as np

        with self.actual_graphics_workers() as run:
            old = SimpleNamespace(frame_buffer=np.full((8, 12, 4), 16, dtype=np.uint8))
            new = SimpleNamespace(frame_buffer=np.full((8, 12, 4), 192, dtype=np.uint8))
            callback = run.captures[0].callbacks["on_frame_arrived"]
            callback(old, SimpleNamespace(stop=lambda: None))
            self.assertTrue(run.reached.wait(2))
            callback(new, SimpleNamespace(stop=lambda: None))
            self.wait_until(lambda: run.latest.snapshot()[1] is not None)
            jpeg = run.latest.snapshot()[1]
            run.release.set()
            time.sleep(0.1)
            self.assertEqual(run.latest.snapshot()[1], jpeg)
            self.assertEqual(run.latest.snapshot()[0]["frame"], 1)
            image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
            self.assertTrue((image == 192).all())


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
        until = time.perf_counter() + timeout
        while not predicate() and time.perf_counter() < until:
            time.sleep(0.005)
        self.assertTrue(predicate(), "capture threads did not reach the expected state")

    def arrive(self, capture, pixels):
        time.sleep(0.005)  # Distinct X-Captured-At milliseconds.
        capture.callbacks["on_frame_arrived"](
            SimpleNamespace(frame_buffer=pixels), SimpleNamespace(stop=lambda: None)
        )

    def test_unexpected_encoder_error_is_reported_and_next_frame_recovers(self):
        real_imencode, calls = cv2.imencode, []

        def imencode(*args):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("unexpected encoder failure")
            return real_imencode(*args)

        with patch("cv2.imencode", imencode), self.workers() as (harness, latest, _):
            self.wait_until(lambda: harness.captures)
            capture = harness.captures[0][0]
            self.arrive(capture, np.full((8, 12, 4), 32, np.uint8))
            self.wait_until(lambda: latest.snapshot()[0]["message"].startswith("Capture encoder failed"))
            self.assertIsNone(latest.snapshot()[1])
            self.arrive(capture, np.full((8, 12, 4), 64, np.uint8))
            self.wait_until(lambda: latest.snapshot()[1] is not None)
            self.assertEqual(latest.snapshot()[0]["state"], "capturing")

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

    def test_capture_that_ended_by_itself_is_joined_logged_and_restarted(self):
        output = io.StringIO()
        with redirect_stdout(output), self.workers(fail_stop=True) as (harness, latest, loop):
            self.wait_until(lambda: harness.captures)
            harness.captures[0][1].finished = True  # The native thread ended with an error.
            self.wait_until(lambda: len(harness.captures) == 2)
            self.assertIn("CAPTURE_STOP_ERROR", output.getvalue())
            self.arrive(harness.captures[1][0], np.full((8, 12, 4), 64, np.uint8))
            self.wait_until(lambda: latest.snapshot()[1] is not None)
            self.assertTrue(loop.is_alive())


if __name__ == "__main__":
    unittest.main()

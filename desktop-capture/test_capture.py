"""HTTP contract and stale-frame/selection regression tests. No desktop is captured."""

import http.client
import threading
import time
import unittest
from contextlib import closing

from capture_helper import LatestFrame, capture_refresh_due, make_server, owned_capture_pixels
from PIL import Image


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
            int(time.time() * 1000),
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

    def test_latest_only_never_queues(self):
        for _ in range(20):
            self.publish()
        code, headers, _ = self.get("/frame")
        self.assertEqual(code, 200)
        self.assertEqual(headers["ETag"], '"20"')

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


if __name__ == "__main__":
    unittest.main()

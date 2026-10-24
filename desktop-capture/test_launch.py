"""Launcher attachment identity and process guard checks; no desktop input."""

import os
import unittest

from launch import player_processes, verify_existing_selection


class LauncherTests(unittest.TestCase):
    def test_requested_window_must_be_confirmed_by_helper(self):
        verify_existing_selection(123, {"hwnd": 123, "pid": 456})
        for selected in (None, {"hwnd": 999}, {}):
            with self.assertRaisesRegex(RuntimeError, "requested Blender window"):
                verify_existing_selection(123, selected)

    def test_picker_attachment_without_explicit_request_remains_allowed(self):
        verify_existing_selection(None, None)

    @unittest.skipUnless(os.name == "nt", "Windows process snapshot")
    def test_process_snapshot_includes_this_windowless_interpreter(self):
        import sys
        from pathlib import Path

        self.assertIn(os.getpid(), player_processes(Path(sys.executable).name))


if __name__ == "__main__":
    unittest.main()

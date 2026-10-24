"""Launcher attachment identity and process guard checks; no desktop input."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launch import main, player_processes, verify_existing_selection


class LauncherTests(unittest.TestCase):
    def test_requested_window_must_be_confirmed_by_helper(self):
        verify_existing_selection(123, {"hwnd": 123, "pid": 456})
        for selected in (None, {"hwnd": 999}, {}):
            with self.assertRaisesRegex(RuntimeError, "requested Blender window"):
                verify_existing_selection(123, selected)

    def test_picker_attachment_without_explicit_request_remains_allowed(self):
        verify_existing_selection(None, None)

    @unittest.skipUnless(os.name == "nt", "Windows launcher")
    def test_changed_selection_during_startup_cannot_launch_player(self):
        selections = iter(({"hwnd": 123}, {"hwnd": 999}))

        def status(path="/status"):
            return next(selections) if path == "/selection" else {"state": "capturing"}

        with tempfile.TemporaryDirectory() as folder:
            player = Path(folder) / "SpatialModeling.exe"
            player.touch()
            with patch("sys.argv", ["launch.py", "--player", str(player), "--window", "123",
                                    "--session-dir", str(Path(folder) / "session")]), \
                 patch("launch.player_processes", return_value=[]), \
                 patch("launch.ping_host", return_value=True), \
                 patch("launch.capture_status", side_effect=status), \
                 patch("launch.subprocess.Popen") as spawn:
                with self.assertRaisesRegex(RuntimeError, "requested Blender window"):
                    main()
                spawn.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows process snapshot")
    def test_process_snapshot_includes_this_windowless_interpreter(self):
        import sys
        self.assertIn(os.getpid(), player_processes(Path(sys.executable).name))


if __name__ == "__main__":
    unittest.main()

"""Startup/recovery regressions: no GUI, personal Blender, or XR runtime required."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import coplanar_setup as setup
from capture_helper import minimized_message


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.controller = setup.Controller(self.data)
        self.record = {"native_pid": 10, "native_started": 100, "hwnd": 20,
                       "player_pid": 30, "player_started": 300, "helper_pid": 40,
                       "helper_started": 400, "capture_port": 15001, "host_port": 15002,
                       "package": str(self.data), "session": str(self.data),
                       "working_copy": str(self.data / "saved.blend")}

    def saved(self):
        setup.write_json(self.controller.state, self.record)

    def test_reconnect_reuses_exact_runtime_and_restores_only_its_blender(self):
        self.saved()
        with (patch("launch.player_processes", return_value=[30]),
              patch.object(self.controller, "stamp", return_value=300),
              patch.object(self.controller, "window"),
              patch.object(self.controller, "restore_blender") as restore,
              patch.object(self.controller, "binding"),
              patch.object(self.controller, "spawn") as spawn):
            self.assertEqual(self.controller.start({}), self.record)
        restore.assert_called_once_with(self.record)
        spawn.assert_not_called()

    def test_foreign_or_recycled_player_never_closes_or_spawns_anything(self):
        self.saved()
        with (patch("launch.player_processes", return_value=[30]),
              patch.object(self.controller, "stamp", return_value=999),
              patch.object(self.controller, "spawn") as spawn,
              self.assertRaisesRegex(setup.SetupError, "Another VR session")):
            self.controller.start({})
        spawn.assert_not_called()
        with (patch("launch.player_processes", return_value=[55]),
              self.assertRaisesRegex(setup.SetupError, "already open")):
            self.controller.start({})

    def test_closed_native_restarts_from_copy_of_saved_work(self):
        self.saved()
        Path(self.record["working_copy"]).write_bytes(b"saved work")
        with (patch("launch.player_processes", return_value=[]),
              patch.object(self.controller, "stamp", side_effect=OSError),
              patch.object(self.controller, "create_session", return_value=self.record) as create,
              patch.object(self.controller, "launch_player", return_value=self.record)):
            self.controller.start({"blend": "other.blend"})
        self.assertEqual(create.call_args.args[0]["blend"], self.record["working_copy"])
        self.assertEqual(Path(self.record["working_copy"]).read_bytes(), b"saved work")

    def test_multiple_blender_windows_do_not_choose_first_or_visible_foreign_window(self):
        windows = [{"pid": 11, "hwnd": 21}, {"pid": 10, "hwnd": 20}]
        self.assertEqual(setup.selected_main_window(windows, 10, 20), windows[1])
        with self.assertRaises(setup.SetupError):
            setup.selected_main_window(windows, 10, 21)
        with self.assertRaises(setup.SetupError):
            setup.selected_main_window(windows + [{"pid": 10, "hwnd": 22}], 10)

    def test_restore_does_not_unmaximize_and_never_targets_other_window(self):
        api = Mock()
        api.u.IsIconic.return_value = False
        window = {"pid": 10, "hwnd": 20}
        with patch.object(self.controller, "window", return_value=(api, window)):
            self.controller.restore_blender(self.record)
            api.u.ShowWindowAsync.assert_not_called()
            api.u.IsIconic.return_value = True
            self.controller.restore_blender(self.record)
            api.u.ShowWindowAsync.assert_called_once_with(20, 9)
        self.assertTrue(all(call.args == (20,) for call in api.u.SetForegroundWindow.call_args_list))

    def test_minimized_identity_check_does_not_require_drawable_geometry(self):
        api = Mock()
        api.windows.return_value = [{"pid": 10, "hwnd": 20}]
        native = Mock()
        native.process_stamp.return_value = 100
        native.inspect.side_effect = AssertionError("Geometry refuses minimized windows")
        with (patch("capture_helper.Windows", return_value=api),
              patch("input_bridge.WindowsInput", return_value=native)):
            self.assertEqual(self.controller.window(self.record)[1]["hwnd"], 20)
        native.inspect.assert_not_called()

    def test_health_uses_fresh_status_and_does_not_claim_worn_headset(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"state":"minimized"}'
        opener = Mock()
        opener.open.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            self.assertIn("Show connected Blender", setup.connection_message(self.record))
            response.read.return_value = b'{"state":"capturing"}'
            self.assertIn("enter Quest Link", setup.connection_message(self.record))

    def test_wrong_capture_connection_refuses_without_starting_another(self):
        with (patch("launch_p25.input_preflight", return_value={"helper_pid": 999}),
              patch.object(self.controller, "spawn") as spawn,
              self.assertRaisesRegex(setup.SetupError, "another session")):
            self.controller.ensure_capture(self.record)
        spawn.assert_not_called()

    def test_live_but_slow_helper_does_not_spawn_duplicate(self):
        with (patch("launch_p25.input_preflight", side_effect=OSError),
              patch.object(self.controller, "stamp", return_value=400),
              patch.object(setup, "wait_ready"), patch.object(self.controller, "spawn") as spawn):
            self.controller.ensure_capture(self.record)
        spawn.assert_not_called()

    def test_dead_helper_recovers_same_connected_hwnd_without_picker(self):
        child = Mock(pid=41)
        with (patch("launch_p25.input_preflight", side_effect=OSError),
              patch.object(self.controller, "stamp", side_effect=[OSError(), 401]),
              patch.object(setup, "wait_ready"),
              patch.object(self.controller, "spawn", return_value=child) as spawn):
            self.controller.ensure_capture(self.record)
        command = spawn.call_args.args[0]
        self.assertEqual(command[command.index("--window") + 1], "20")
        self.assertIn("--headless", command)
        self.assertEqual(setup.read_json(self.controller.state)["helper_pid"], 41)

    def test_minimized_error_identifies_the_connected_window(self):
        message = minimized_message({"pid": 10, "title": "old.blend"})
        self.assertIn("old.blend", message)
        self.assertIn("PID 10", message)
        self.assertIn("Show connected Blender", message)

    def test_incomplete_or_tampered_package_refused(self):
        setup.write_json(self.data / "package-manifest.json", {"files": {}})
        with self.assertRaisesRegex(setup.SetupError, "incomplete"):
            setup.validate_package(self.data)
        files = {name: "wrong digest" for name in (
            "SpatialModeling.exe", "SpatialModeling_Data/Managed/Assembly-CSharp.dll",
            "support/bootstrap_p25.py", "addon/spatial_modeling/__init__.py", "reference.blend")}
        for name in files:
            path = self.data / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        setup.write_json(self.data / "package-manifest.json", {"files": files})
        with self.assertRaisesRegex(setup.SetupError, "repair"):
            setup.validate_package(self.data)


if __name__ == "__main__":
    unittest.main()

"""P2.5 isolation/identity preflight checks. No Player, window or native input."""

import argparse
import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from launch_p25 import isolated_port, main, native_preflight, validate_binding


def binding():
    welcome = {"can_edit": True, "session_id": "session", "host_epoch": "host",
               "document": {"id": "document", "open_epoch": "open"},
               "capabilities": {"preview_spatial": True, "sketch": False}}
    native = {"session_id": "session", "host_epoch": "host", "document_id": "document",
              "open_epoch": "open", "process_id": 123}
    capture = {"enabled": True, "ready": True, "focused": False,
               "selection": {"pid": 123, "hwnd": 456}, "token": "secret-not-for-output"}
    return welcome, native, capture


def family_binding():
    welcome, native, capture = binding()
    capture.update(window_scope="one-explicit-picker-scope", capture_instance="one-helper-instance", release_error=False,
                   selection={"pid": 321, "hwnd": 457, "blender_pid": 123, "blender_hwnd": 456,
                              "blender_process_started": 123001, "input_process_started": 321001},
                   geometry={"process_started": 321001, "blender_pid": 123, "blender_hwnd": 456,
                             "blender_process_started": 123001})
    return welcome, native, capture


class P25LauncherTests(unittest.TestCase):
    def test_isolated_ports_do_not_attach_to_p2_defaults(self):
        for value in ("0", "1023", "65536", "8765", "8766", "8767"):
            with self.assertRaises(argparse.ArgumentTypeError):
                isolated_port(value)
        self.assertEqual(isolated_port("8769"), 8769)

    def test_valid_host_binding_does_not_require_focus_or_cad(self):
        result = validate_binding(*binding())
        self.assertTrue(result["binding_verified"])
        self.assertFalse(result["focused"])
        self.assertFalse(result["native_cad_available"])
        self.assertNotIn("token", result)
        self.assertFalse(result["root_lifetime_verified"])

    def test_verified_brokered_dialog_binds_to_native_blender_root_not_broker_pid(self):
        result = validate_binding(*family_binding())
        self.assertTrue(result["binding_verified"])
        self.assertTrue(result["root_lifetime_verified"])
        self.assertEqual(result["native_process_id"], 123)
        self.assertEqual(result["capture_process_id"], 321)
        self.assertEqual(result["capture_hwnd"], 457)
        self.assertFalse(result["focused"])
        self.assertNotIn("token", result)

    def test_modern_main_window_preserves_same_pid_binding_with_matching_lifetimes(self):
        values = family_binding()
        values[2]["selection"].update(pid=123, hwnd=456, input_process_started=123001)
        values[2]["geometry"]["process_started"] = 123001
        self.assertTrue(validate_binding(*values)["root_lifetime_verified"])

    @unittest.skipUnless(os.name == "nt", "Windows launcher")
    def test_diagnose_accepts_broker_dialog_without_querying_windows_spawning_or_leaking_token(self):
        values = family_binding()
        output = io.StringIO()
        with patch("sys.argv", ["launch_p25.py", "--host-port", "8769", "--capture-port", "8768", "--diagnose"]), \
             patch("launch_p25.native_preflight", return_value=values[:2]), \
             patch("launch_p25.input_preflight", return_value=values[2]), \
             patch("launch_p25.player_processes", side_effect=AssertionError("Diagnose must not query desktop processes")), \
             patch("launch_p25.subprocess.Popen") as spawn, redirect_stdout(output):
            main()
        spawn.assert_not_called()
        report = json.loads(output.getvalue())
        self.assertEqual((report["native_process_id"], report["capture_process_id"]), (123, 321))
        self.assertTrue(report["root_lifetime_verified"])
        self.assertFalse(report["runtime_acceptance"])
        self.assertNotIn("token", report)
        self.assertNotIn("secret-not-for-output", output.getvalue())

    def test_mismatched_or_missing_dialog_root_target_lifetimes_and_scopes_refuse(self):
        changes = [
            lambda c: c["selection"].update(blender_pid=999),
            lambda c: c["geometry"].update(blender_pid=999),
            lambda c: c["geometry"].update(blender_process_started=123002),
            lambda c: c["geometry"].update(process_started=321002),
            lambda c: c["geometry"].update(blender_hwnd=999),
            lambda c: c["selection"].pop("blender_process_started"),
            lambda c: c["selection"].pop("input_process_started"),
            lambda c: c["selection"].pop("blender_hwnd"),
            lambda c: c["selection"].pop("blender_pid"),
            lambda c: c["geometry"].pop("blender_process_started"),
            lambda c: c.update(geometry=None),
            lambda c: c.update(window_scope=""),
            lambda c: c.update(capture_instance=None),
            lambda c: c.update(release_error=True),
        ]
        for change in changes:
            values = family_binding()
            change(values[2])
            with self.subTest(capture=values[2]), self.assertRaises(RuntimeError):
                validate_binding(*values)

    def test_boolean_nonpositive_and_out_of_protocol_identity_values_refuse(self):
        for field in ("pid", "hwnd", "blender_pid", "blender_hwnd", "blender_process_started", "input_process_started"):
            for value in (True, False, 0, -1, "123", 1 << 64):
                values = family_binding()
                values[2]["selection"][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                    validate_binding(*values)
        for field in ("process_started", "blender_process_started", "blender_pid", "blender_hwnd"):
            values = family_binding()
            values[2]["geometry"][field] = True
            with self.subTest(geometry_field=field), self.assertRaises(RuntimeError):
                validate_binding(*values)

    def test_wrong_process_document_stale_disabled_missing_bridge_all_refuse(self):
        mutations = [
            (0, lambda value: value.update(can_edit=False)),
            (0, lambda value: value["capabilities"].update(preview_spatial=False)),
            (1, lambda value: value.update(open_epoch="different-file-open")),
            (1, lambda value: value.update(process_id=789)),
            (2, lambda value: value.update(ready=False)),
            (2, lambda value: value.update(enabled=False)),
            (2, lambda value: value.update(selection=None)),
        ]
        for index, change in mutations:
            values = copy.deepcopy(binding())
            change(values[index])
            with self.subTest(index=index, values=values), self.assertRaises(RuntimeError):
                validate_binding(*values)

    def test_read_only_native_preflight_never_requests_permission_or_mutation(self):
        class Connection:
            def __init__(self):
                self.messages = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def sendall(self, data):
                self.messages.append(json.loads(data))

            def makefile(self, _mode):
                return self

            def readline(self, _limit):
                request = self.messages[-1]
                payload = binding()[0 if request["type"] == "hello" else 1]
                return json.dumps({"type": "welcome" if request["type"] == "hello" else "preview.state",
                                   "re": request["id"], "payload": payload}).encode() + b"\n"

        connection = Connection()
        with patch("launch_p25.socket.create_connection", return_value=connection):
            welcome, native = native_preflight(8769)
        self.assertEqual(native["process_id"], 123)
        self.assertTrue(welcome["can_edit"])
        self.assertEqual([m["type"] for m in connection.messages], ["hello", "preview.state.query"])

    @unittest.skipUnless(os.name == "nt", "Windows launcher")
    def test_existing_player_refuses_launch_without_stopping_or_replacing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            player = Path(folder) / "SpatialModeling.exe"
            player.touch()
            with patch("sys.argv", ["launch_p25.py", "--host-port", "8769", "--capture-port", "8768",
                                    "--player", str(player), "--session-dir", str(Path(folder) / "session")]), \
                 patch("launch_p25.native_preflight", return_value=binding()[:2]), \
                 patch("launch_p25.input_preflight", return_value=binding()[2]), \
                 patch("launch_p25.player_processes", return_value=[999]), \
                 patch("launch_p25.subprocess.Popen") as spawn:
                with self.assertRaises(SystemExit):
                    main()
                spawn.assert_not_called()
                self.assertFalse((Path(folder) / "session").exists())


if __name__ == "__main__":
    unittest.main()

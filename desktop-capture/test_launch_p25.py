"""P2.5 isolation/identity preflight checks. No Player, window or native input."""

import argparse
import copy
import json
import os
import tempfile
import unittest
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

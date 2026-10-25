"""Integration package launch safety: no actual process, window or native input."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import run_integrated_test as launcher


class IntegratedLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name)
        files = ["SpatialModeling.exe", "SpatialModeling_Data/Managed/Assembly-CSharp.dll",
                 "support/bootstrap_p25.py", "support/capture_helper.py", "support/launch_p25.py",
                 "addon/spatial_modeling/__init__.py", "CAD_Sketcher/blender_manifest.toml",
                 "CAD_Sketcher/wheels/slvs-3.2-cp313-cp313-win_amd64.whl", "reference.blend",
                 "rollback-p2/SpatialModeling.exe"]
        for name in files:
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"private fixture only")
        (self.package / "test-config.json").write_text("{}")
        (self.package / "package-manifest.json").write_text(json.dumps({"files": {
            name: hashlib.sha256((self.package / name).read_bytes()).hexdigest() for name in files}}))

    def run_main(self, *extra):
        with patch("sys.argv", ["run_integrated_test.py", "--package", str(self.package), *extra]):
            launcher.main()

    def test_default_validation_does_not_start_or_inspect_applications(self):
        with patch.object(launcher.subprocess, "Popen") as spawn, patch.object(launcher, "player_processes") as processes:
            self.run_main()
        spawn.assert_not_called()
        processes.assert_not_called()

    def test_accepted_player_prevents_every_runtime_mutation(self):
        with patch.object(launcher, "player_processes", return_value=[76636]), \
                patch.object(launcher.subprocess, "Popen") as spawn, patch.object(launcher, "free_port") as ports:
            with self.assertRaisesRegex(RuntimeError, "Existing Player"):
                self.run_main("--launch")
        spawn.assert_not_called()
        ports.assert_not_called()

    def test_tampered_assembly_refuses_before_launch(self):
        (self.package / "SpatialModeling_Data/Managed/Assembly-CSharp.dll").write_bytes(b"changed")
        with patch.object(launcher.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                self.run_main("--launch")
        spawn.assert_not_called()

    def test_incomplete_folder_refuses_before_launch(self):
        (self.package / "reference.blend").unlink()
        with patch.object(launcher.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "Incomplete package"):
                self.run_main("--launch")
        spawn.assert_not_called()

    def test_owned_process_exit_cannot_be_mistaken_for_readiness(self):
        process = Mock()
        process.poll.return_value = 1
        process.returncode = 1
        check = Mock(return_value={"status": "host_ready"})
        with self.assertRaisesRegex(RuntimeError, "Owned process exited"):
            launcher.wait_for(check, process)
        check.assert_not_called()

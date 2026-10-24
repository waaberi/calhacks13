"""Fresh C gates: package identity, isolation and actual handshake; no Blender/XR."""
import json
import socket
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fresh_c import (
    archive_entries,
    build_addon_zip,
    isolated_environment,
    package_identity,
    require_free_port,
    require_selected_host,
    run,
    sha256,
    verify_player,
    verify_protocol,
    verify_readiness,
    write_json,
)


class FreshCTests(unittest.TestCase):
    def test_player_changed_during_picker_cannot_spawn(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "blender_addon/spatial_modeling"
            source.mkdir(parents=True)
            (source / "__init__.py").write_text("# source")
            (source / "blender_manifest.toml").write_text('id="spatial_modeling"\nversion="0.1.0"')
            notices = root / "docs/third-party"
            notices.mkdir(parents=True)
            for name in ("CAD_DEPENDENCIES.md", "CAD_SKETCHER_GPL3.txt", "SLVS_COPYING.txt"):
                (notices / name).write_text("notice fixture")
            archive = root / "c.zip"
            identity = build_addon_zip(source, archive, "a" * 40)
            player, blender, blend = (root / name for name in ("SpatialModeling.exe", "Blender.exe", "source.blend"))
            for path in (player, blender, blend):
                path.write_bytes(b"test fixture")
            assembly = root / "SpatialModeling_Data/Managed/Assembly-CSharp.dll"
            assembly.parent.mkdir(parents=True)
            assembly.write_bytes(b"tested C assembly")
            cad = root / "CAD_Sketcher"
            cad.mkdir()
            args = SimpleNamespace(player=player, blender=blender, blend=blend, addon_zip=archive,
                                   addon_sha256=identity["zip_sha256"], cad_extension=cad,
                                   session_dir=root / "session", host_only=False, window=456,
                                   player_assembly_sha256=sha256(assembly), player_source_revision="b" * 40)
            def spawn_host(*_, **__):
                write_json(args.session_dir / "c-ready.json", {
                    "status": "ready", "pid": 123, "host": "127.0.0.1", "port": 8765,
                    "working_copy": str(args.session_dir / "working.blend"), **identity,
                    "cad": {"available": True, "cad_sketcher": "0.32.1", "slvs": "3.2"}})
                return SimpleNamespace(pid=123, poll=lambda: None)
            def selected(path="/status"):
                return {"pid": 123, "hwnd": 456} if path == "/selection" else {"state": "capturing"}
            def pixels():
                assembly.write_bytes(b"different build after user picker wait")
                return 123456
            with patch("fresh_c.require_free_port"), patch("fresh_c.verify_cad"), \
                    patch("fresh_c.verify_protocol", return_value={}), \
                    patch("fresh_c.require_fresh_pixels", side_effect=pixels), \
                    patch("fresh_c.subprocess.Popen", side_effect=spawn_host) as spawn:
                with self.assertRaisesRegex(ValueError, "Player assembly does not match"):
                    run(args, existing_players=lambda _: [], capture_status=selected)
                self.assertEqual(spawn.call_count, 1)  # Only the mocked native host; no Player.

    def test_old_player_assembly_cannot_silently_be_used_for_c(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            player = root / "SpatialModeling.exe"
            player.write_bytes(b"player stub")
            managed = root / "SpatialModeling_Data" / "Managed"
            managed.mkdir(parents=True)
            assembly = managed / "Assembly-CSharp.dll"
            assembly.write_bytes(b"tested C assembly")
            proof = verify_player(player, sha256(assembly), "a" * 40)
            self.assertEqual(proof["source_revision"], "a" * 40)
            assembly.write_bytes(b"old P1 assembly")
            with self.assertRaisesRegex(ValueError, "does not match"):
                verify_player(player, proof["assembly_sha256"], "a" * 40)

    def test_zip_matches_exact_source_and_detects_changed_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "blender_addon" / "spatial_modeling"
            source.mkdir(parents=True)
            notices = root / "docs" / "third-party"
            notices.mkdir(parents=True)
            for name in ("CAD_DEPENDENCIES.md", "CAD_SKETCHER_GPL3.txt", "SLVS_COPYING.txt"):
                (notices / name).write_text("retained notice for unit fixture")
            (source / "__init__.py").write_text("# exact native source")
            (source / "blender_manifest.toml").write_text('id="spatial_modeling"\nversion="0.1.0"')
            archive = root / "c.zip"
            manifest = build_addon_zip(source, archive, "a" * 40)
            actual = package_identity(archive, manifest["zip_sha256"].upper())
            self.assertEqual(actual["source_revision"], "a" * 40)
            changed = root / "changed.zip"
            with zipfile.ZipFile(archive) as original, zipfile.ZipFile(changed, "w") as modified:
                for item in original.infolist():
                    modified.writestr(item.filename, b"changed" if item.filename == "__init__.py" else original.read(item))
            with self.assertRaisesRegex(ValueError, "file manifest"):
                package_identity(changed, sha256(changed))
            with self.assertRaisesRegex(ValueError, "expected SHA256"):
                package_identity(changed, manifest["zip_sha256"])

    def test_archive_paths_cannot_escape_private_install(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "unsafe.zip"
            for name in ("../shared.py", "/absolute.py", "..\\shared.py"):
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr(name, b"unsafe")
                with zipfile.ZipFile(path) as archive, self.assertRaisesRegex(ValueError, "unsafe path"):
                    archive_entries(archive)

    def test_busy_listener_never_attaches_or_starts_process(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with self.assertRaisesRegex(RuntimeError, "not attached or stopped"):
                require_free_port(listener.getsockname()[1])
        args = SimpleNamespace(player=Path("SpatialModeling.exe"))
        with patch("fresh_c.require_free_port", side_effect=RuntimeError("occupied")), \
                patch("fresh_c.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "occupied"):
                run(args, existing_players=lambda _: [], capture_status=lambda _: None)
            spawn.assert_not_called()

    def test_user_paths_are_child_only_and_all_shared_overrides_removed(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {
                "BLENDER_USER_RESOURCES": "old-shared", "BLENDER_USER_SCRIPTS": "shared-scripts",
                "BLENDER_USER_OTHER": "old-other"}):
            env = isolated_environment(folder)
            self.assertNotIn("BLENDER_USER_OTHER", env)
            self.assertEqual(env["BLENDER_USER_RESOURCES"], str(Path(folder).resolve()))
            self.assertTrue(Path(env["BLENDER_USER_SCRIPTS"]).is_relative_to(Path(folder).resolve()))

    def test_existing_capture_cannot_select_original_host(self):
        require_selected_host({"pid": 123, "hwnd": 456}, 123, 456)
        for value in (None, {"pid": 55356, "hwnd": 456}, {"pid": 123, "hwnd": 789}):
            with self.assertRaisesRegex(RuntimeError, "newly launched C"):
                require_selected_host(value, 123, 456)

    def test_readiness_needs_exact_process_source_copy_and_pins(self):
        identity = {"source_revision": "a" * 40, "zip_sha256": "b" * 64}
        ready = {**identity, "status": "ready", "pid": 123, "host": "127.0.0.1", "port": 8765,
                 "working_copy": str(Path("working.blend").resolve()),
                 "cad": {"available": True, "cad_sketcher": "0.32.1", "slvs": "3.2"}}
        verify_readiness(ready, identity, 123, "working.blend")
        for key, value in (("pid", 55356), ("source_revision", "c" * 40), ("zip_sha256", "c" * 64),
                           ("working_copy", "personal.blend"), ("cad", {"available": False})):
            with self.assertRaisesRegex(RuntimeError, "identity/CAD readiness"):
                verify_readiness({**ready, key: value}, identity, 123, "working.blend")

    def protocol_trial(self, mutation=None):
        doc = {"id": "a" * 32, "open_epoch": "b" * 32, "revision": 0}
        ready = {"document": doc, "host_epoch": "c" * 32}
        observed = []
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            def respond():
                with listener.accept()[0] as connection, connection.makefile("rb") as stream:
                    hello, ping = (json.loads(stream.readline()) for _ in range(2))
                    observed.extend([hello["type"], ping["type"]])
                    welcome = {"v": 1, "type": "welcome", "re": hello["id"],
                               "payload": {"capabilities": {"sketch": True}, "host_epoch": ready["host_epoch"], "document": doc}}
                    snapshot = {"v": 1, "type": "scene.snapshot", "payload": {"document": doc, "objects": [], "sketches": []}}
                    if mutation:
                        mutation(welcome, snapshot)
                    connection.sendall(b"".join(json.dumps(msg).encode() + b"\n" for msg in
                                               (welcome, snapshot, {"v": 1, "type": "pong", "re": ping["id"]})))
            worker = threading.Thread(target=respond)
            worker.start()
            try:
                return verify_protocol(ready, "0.1.0", listener.getsockname()[1])
            finally:
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(observed, ["hello", "ping"])

    def test_actual_handshake_requires_c_capability_current_scene_and_pong(self):
        self.assertTrue(self.protocol_trial()["native_pong"])
        with self.assertRaisesRegex(RuntimeError, "C capabilities"):
            self.protocol_trial(lambda welcome, _: welcome["payload"]["capabilities"].update(sketch=False))
        with self.assertRaisesRegex(RuntimeError, "document changed"):
            self.protocol_trial(lambda _, snapshot: snapshot["payload"].update(document={"id": "d" * 32, "open_epoch": "b" * 32}))
        with self.assertRaisesRegex(RuntimeError, "complete current C scene"):
            self.protocol_trial(lambda _, snapshot: snapshot["payload"].pop("sketches"))


if __name__ == "__main__":
    unittest.main()

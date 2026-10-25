"""Private bootstrap guards/copies only. No bpy import, apps, ports or input."""

import argparse
import hashlib
import json
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from bootstrap_p25 import (
    WHEEL_NAME,
    configure_private_server,
    configure_private_ui,
    isolated_port,
    prepare,
    private_temporary_files,
    require_factory_process,
    safe_session,
    validated_wheel,
)


class BootstrapPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="p25-bootstrap-test-")
        self.root = Path(self.temp.name).resolve()
        self.blend = self.root / "original.blend"
        self.blend.write_bytes(b"BLENDER-v502original bytes; never save over these")
        self.addon = self.root / "source" / "spatial_modeling"
        self.addon.mkdir(parents=True)
        for name in ("__init__.py", "server.py", "host.py", "preview_spatial.py"):
            (self.addon / name).write_text("# private source copy\n", encoding="utf-8")
        self.session = self.root / "new-session"
        self.args = SimpleNamespace(session_dir=self.session, blend=self.blend,
                                    addon_root=self.addon, host_port=8769, cad_extension=None)
        self.environ = {"BLENDER_USER_RESOURCES": str(self.session / "blender-resources")}

    def tearDown(self):
        self.temp.cleanup()

    def test_private_ui_suppresses_first_run_splash_without_saving_preferences(self):
        prefs = SimpleNamespace(view=SimpleNamespace(show_splash=True), use_preferences_save=True)
        config = self.session / "blender-resources/config"
        fake = SimpleNamespace(context=SimpleNamespace(preferences=prefs),
                               utils=SimpleNamespace(user_resource=lambda *a, **kw: str(config)))
        result = configure_private_ui(fake, config.parent)
        self.assertFalse(prefs.view.show_splash)
        self.assertFalse(prefs.use_preferences_save)
        self.assertFalse(result["show_splash"])
        self.assertFalse(config.exists(), "this pure fixture must not create files or save user preferences")

    def test_private_ui_refuses_foreign_profile_before_changing_preferences(self):
        prefs = SimpleNamespace(view=SimpleNamespace(show_splash=True), use_preferences_save=True)
        fake = SimpleNamespace(context=SimpleNamespace(preferences=prefs),
                               utils=SimpleNamespace(user_resource=lambda *a, **kw: str(self.root / "personal")))
        with self.assertRaisesRegex(RuntimeError, "outside the private"):
            configure_private_ui(fake, self.session / "blender-resources")
        self.assertTrue(prefs.view.show_splash)
        self.assertTrue(prefs.use_preferences_save)

    def cad_source(self):
        path = self.root / "CAD_Sketcher"
        path.mkdir()
        (path / "blender_manifest.toml").write_text('version = "0.32.1"\n', encoding="utf-8")
        (path / "__init__.py").write_text("# private CAD source\n", encoding="utf-8")
        (path / "wheels").mkdir()
        with zipfile.ZipFile(path / "wheels" / WHEEL_NAME, "w") as archive:
            archive.writestr("slvs-3.2.dist-info/METADATA", "Name: slvs\nVersion: 3.2\n")
            archive.writestr("slvs.pyd", b"native solver fixture; not imported")
        return path

    def test_generic_preview_private_copy_preserves_original_and_requires_new_session(self):
        original = self.blend.read_bytes()
        before = set(sys.modules)
        record = prepare(self.args, self.environ)
        self.assertEqual(self.blend.read_bytes(), original)
        self.assertEqual(Path(record["working_blend"]).read_bytes(), original)
        self.assertEqual(record["original_blend_sha256"], hashlib.sha256(original).hexdigest())
        self.assertIsNone(record["cad"])
        self.assertEqual(record["host_port"], 8769)
        self.assertTrue(Path(record["addon_package"], "preview_spatial.py").is_file())
        self.assertEqual(json.loads((self.session / "bootstrap.json").read_text())["status"], "prepared")
        self.assertEqual(set(sys.modules) - before, set())
        with self.assertRaisesRegex(ValueError, "NEW"):
            prepare(self.args, self.environ)

    def test_private_pinned_cad_package_and_solver_are_copied_before_extracting(self):
        self.args.cad_extension = self.cad_source()
        record = prepare(self.args, self.environ)
        cad = record["cad"]
        self.assertEqual(cad["version"], "0.32.1")
        self.assertTrue(Path(cad["solver"], "slvs.pyd").is_file())
        self.assertTrue(Path(cad["package"], "wheels", WHEEL_NAME).is_file())
        self.assertEqual(len(cad["wheel_sha256"]), 64)
        Path(cad["package"], "__init__.py").write_text("changed private copy")
        self.assertEqual((self.args.cad_extension / "__init__.py").read_text(), "# private CAD source\n")

    def test_wrong_cad_version_or_wheel_does_not_create_session(self):
        self.args.cad_extension = self.cad_source()
        (self.args.cad_extension / "blender_manifest.toml").write_text('version = "0.31.0"\n')
        with self.assertRaisesRegex(ValueError, "0.32.1"):
            prepare(self.args, self.environ)
        self.assertFalse(self.session.exists())

    def test_git_onedrive_and_ancestor_environment_overrides_are_rejected(self):
        git = self.root / "worktree"
        git.mkdir()
        (git / ".git").write_text("gitdir: elsewhere")
        for path in (git / "session", self.root / "OneDrive - Test" / "session"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_session(path, {"BLENDER_USER_RESOURCES": str(path / "blender-resources")})
        with self.assertRaisesRegex(ValueError, "CONFIG"):
            safe_session(self.session, {**self.environ, "BLENDER_USER_CONFIG": str(self.root / "personal")})
        with self.assertRaises(ValueError):
            safe_session(self.session, {**self.environ, "OneDrive": str(self.root)})

    def test_profile_must_point_to_future_private_resources_not_personal_or_parent(self):
        for env in ({}, {"BLENDER_USER_RESOURCES": str(self.root)},
                    {"BLENDER_USER_RESOURCES": str(self.root / "personal")}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                prepare(self.args, env)
        self.assertFalse(self.session.exists())

    def test_sources_must_be_real_p25_package_and_nonempty_blend(self):
        (self.addon / "preview_spatial.py").unlink()
        with self.assertRaisesRegex(ValueError, "P2.5"):
            prepare(self.args, self.environ)
        self.assertFalse(self.session.exists())

    def test_wheel_path_traversal_absolute_paths_and_links_are_rejected_before_extraction(self):
        cad = self.cad_source()
        wheel = cad / "wheels" / WHEEL_NAME
        for name in ("../escape", "/absolute", "C:/escape", "..\\escape"):
            with self.subTest(name=name):
                with zipfile.ZipFile(wheel, "w") as archive:
                    archive.writestr("slvs-3.2.dist-info/METADATA", "Name: slvs\nVersion: 3.2\n")
                    archive.writestr(name, "bad")
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    validated_wheel(wheel)
        link = zipfile.ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(link, "../../outside")
        with self.assertRaisesRegex(ValueError, "unsafe"):
            validated_wheel(wheel)
        self.assertFalse((self.root / "escape").exists())


class BootstrapRuntimeGuardTests(unittest.TestCase):
    def test_private_temp_overrides_environment_and_cached_tempfile_before_cad_import(self):
        with tempfile.TemporaryDirectory(prefix="p25-temp-guard-") as session:
            env = {"TMP": "personal", "TEMP": "personal", "TMPDIR": "personal"}
            fake_tempfile = SimpleNamespace(tempdir="cached-personal")
            private = private_temporary_files(session, env, fake_tempfile)
            self.assertEqual(private.parent, Path(session).resolve())
            self.assertTrue(private.is_dir())
            self.assertEqual(set(env.values()), {str(private)})
            self.assertEqual(fake_tempfile.tempdir, str(private))

    def test_only_factory_empty_clean_blender52_process_is_allowed(self):
        fake = SimpleNamespace(data=SimpleNamespace(filepath="", is_dirty=False),
                               app=SimpleNamespace(version=(5, 2, 0)))
        argv = ["blender.exe", "--factory-startup", "--python", "bootstrap_p25.py", "--", "--session-dir", "new"]
        require_factory_process(fake, argv)
        fake.data.is_dirty = True
        with self.assertRaisesRegex(RuntimeError, "unsaved"):
            require_factory_process(fake, argv)
        fake.data.is_dirty = False
        fake.data.filepath = "personal.blend"
        with self.assertRaisesRegex(RuntimeError, "open file"):
            require_factory_process(fake, argv)
        fake.data.filepath = ""
        with self.assertRaisesRegex(RuntimeError, "factory-startup"):
            require_factory_process(fake, ["blender.exe", "--python", "bootstrap_p25.py"])

    def test_explicit_port_wraps_frozen_default_without_touching_any_other_server(self):
        calls = []

        class Server:
            def __init__(self, host="127.0.0.1", port=8765, **kwargs):
                calls.append((host, port, kwargs))

        module = SimpleNamespace(PORT=8765, Server=Server)
        configure_private_server(module, 8769)
        module.Server(extra_listeners=[])
        self.assertEqual(calls[-1], ("127.0.0.1", 8769, {"extra_listeners": []}))
        Server()
        self.assertEqual(calls[-1][1], 8765)
        for kwargs in ({"host": "0.0.0.0"}, {"port": 8765}, {"extra_listeners": [object()]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeError):
                module.Server(**kwargs)

    def test_default_p2_and_lan_ports_are_rejected(self):
        for value in (8765, 8766, 8767, 0, 65536):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                isolated_port(value)
        self.assertEqual(isolated_port(8769), 8769)


if __name__ == "__main__":
    unittest.main()

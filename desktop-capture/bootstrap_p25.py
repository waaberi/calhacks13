"""Bootstrap ONLY a new factory-startup Blender with private P2.5 files/profile.

Example (the caller sets BLENDER_USER_RESOURCES to SESSION/blender-resources):
  Blender --factory-startup --python bootstrap_p25.py --
    --session-dir NEW_EXTERNAL_SESSION --blend ORIGINAL.blend
    --addon-root REPO/blender_addon/spatial_modeling --host-port 8769
    [--cad-extension PINNED_CAD_SKETCHER_0_32_1_DIRECTORY]

Importing this module or calling prepare() never imports bpy, starts a process,
opens a port, installs into a personal profile, or changes the supplied sources.
"""

import argparse
import hashlib
import importlib
import json
import os
import shutil
import stat
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

CAD_VERSION = "0.32.1"
WHEEL_NAME = "slvs-3.2-cp313-cp313-win_amd64.whl"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def isolated_port(value):
    port = int(value)
    if not 1024 <= port <= 65535 or port in (8765, 8766, 8767):
        raise argparse.ArgumentTypeError("Use a nonprivileged isolated port outside P2's 8765/8766/8767")
    return port


def safe_session(path, environ):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("--session-dir must be an absolute new external path")
    path = path.resolve()
    for directory in (path, *path.parents):
        if (directory / ".git").exists() or directory.name.lower().startswith("onedrive"):
            raise ValueError("Session must be outside Git worktrees and OneDrive")
    for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        value = environ.get(key)
        if value and path.is_relative_to(Path(value).resolve()):
            raise ValueError("Session must be outside the configured OneDrive folder")
    if path.exists():
        raise ValueError("--session-dir must be NEW; existing files/profile are never reused")
    resources = path / "blender-resources"
    if Path(environ.get("BLENDER_USER_RESOURCES", "")).resolve() != resources:
        raise ValueError("Caller must set BLENDER_USER_RESOURCES to SESSION/blender-resources")
    for key, value in environ.items():
        if key.startswith("BLENDER_USER_") and value and not Path(value).resolve().is_relative_to(resources):
            raise ValueError(f"{key} must stay inside the private Blender resource directory")
    return path, resources


def checked_copy(source, destination):
    before = sha256(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha256(source) != before or sha256(destination) != before:
        raise ValueError(f"Source changed while copying: {source.name}; use a fresh session")
    return before


def private_package(source, destination):
    """Copy a package without source/cache links or hidden repository metadata."""
    records = {}
    for directory, dirs, files in os.walk(source, followlinks=False):
        directory = Path(directory)
        dirs[:] = [name for name in dirs if name not in (".git", "__pycache__", ".pytest_cache", ".ruff_cache")]
        for name in (*dirs, *files):
            candidate = directory / name
            if (candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)()
                    or not candidate.resolve().is_relative_to(source)):
                raise ValueError("Source packages must not contain symbolic links/junctions")
        for name in files:
            file = directory / name
            if file.suffix == ".pyc":
                continue
            relative = file.relative_to(source)
            records[relative.as_posix()] = checked_copy(file, destination / relative)
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def validated_wheel(wheel):
    """Validate every archive path before extraction; never trust extractall alone."""
    with zipfile.ZipFile(wheel) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(item.file_size for item in entries) > 256 * 1024 * 1024:
            raise ValueError("Solver wheel exceeds the bounded extraction size")
        for item in entries:
            path = PurePosixPath(item.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in item.filename
                    or any(":" in part for part in path.parts)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError("Solver wheel contains an unsafe archive path or link")
        metadata = archive.read("slvs-3.2.dist-info/METADATA").decode("utf-8")
        if "Name: slvs" not in metadata.splitlines() or "Version: 3.2" not in metadata.splitlines():
            raise ValueError("Pinned slvs 3.2 wheel metadata required")


def prepare(args, environ=None):
    """Validate first, then create exclusively owned copies. No bpy/network calls."""
    environ = os.environ if environ is None else environ
    session, resources = safe_session(args.session_dir, environ)
    port = isolated_port(args.host_port)
    blend = Path(args.blend).resolve()
    addon = Path(args.addon_root).resolve()
    if not blend.is_file() or blend.suffix.lower() != ".blend" or blend.stat().st_size == 0:
        raise ValueError("--blend must identify a readable nonempty original .blend file")
    if not addon.is_dir() or not all((addon / name).is_file() for name in ("__init__.py", "server.py", "host.py", "preview_spatial.py")):
        raise ValueError("--addon-root must be this P2.5 branch's spatial_modeling package")
    cad = Path(args.cad_extension).resolve() if args.cad_extension else None
    if cad:
        manifest = tomllib.loads((cad / "blender_manifest.toml").read_text(encoding="utf-8"))
        if manifest.get("version") != CAD_VERSION or not (cad / "__init__.py").is_file():
            raise ValueError("Only pinned CAD Sketcher 0.32.1 is supported")
        validated_wheel(cad / "wheels" / WHEEL_NAME)
    # No cleanup/delete on failure: preserve the exclusively created partial
    # session for diagnosis and require a new path for a later attempt.
    session.mkdir(parents=True, exist_ok=False)
    resources.mkdir()
    working = session / "working.blend"
    record = {"status": "prepared", "host_port": port, "resources": str(resources),
              "working_blend": str(working), "original_blend_sha256": checked_copy(blend, working),
              "addon_package": str(session / "packages" / "spatial_modeling"), "cad": None}
    record["addon_tree_sha256"] = private_package(addon, Path(record["addon_package"]))
    if cad:
        copied = session / "packages" / "CAD_Sketcher"
        tree = private_package(cad, copied)
        wheel = copied / "wheels" / WHEEL_NAME
        validated_wheel(wheel)
        solver = session / "solver"
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(solver)  # Every member was validated above.
        record["cad"] = {"version": CAD_VERSION, "package": str(copied), "solver": str(solver),
                         "tree_sha256": tree, "wheel_sha256": sha256(wheel),
                         "manifest_sha256": sha256(copied / "blender_manifest.toml")}
    (session / "bootstrap.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def require_factory_process(bpy, argv):
    options = argv[:argv.index("--")] if "--" in argv else argv
    if "--factory-startup" not in options or "--python" not in options:
        raise RuntimeError("Run only as a new Blender --factory-startup --python bootstrap_p25.py process")
    if bpy.data.filepath or bpy.data.is_dirty:
        raise RuntimeError("Refusing a process containing an open file or unsaved changes")
    if tuple(bpy.app.version[:2]) != (5, 2):
        raise RuntimeError("This P2.5 bootstrap targets the verified Blender 5.2 runtime")
    if any(name == "slvs" or name.split(".")[0] in ("spatial_modeling", "CAD_Sketcher")
           for name in sys.modules):
        raise RuntimeError("Refusing a process where the native project packages are already loaded")


def configure_private_server(server, port):
    """PORT defaults were bound at class definition; supply the explicit port."""
    port = isolated_port(port)
    original = server.Server
    server.PORT = port

    class PrivateServer(original):
        def __init__(self, host="127.0.0.1", port=None, **kwargs):
            if host != "127.0.0.1" or port not in (None, server.PORT) or kwargs.get("extra_listeners"):
                raise RuntimeError("P2.5 private bootstrap permits only its explicit loopback listener")
            super().__init__(host="127.0.0.1", port=server.PORT, **kwargs)

    server.Server = PrivateServer


def private_temporary_files(session, environ=None, tempfile_module=None):
    """CAD's logger uses gettempdir(), independently of Blender resources."""
    if tempfile_module is None:
        import tempfile as tempfile_module
    environ = os.environ if environ is None else environ
    directory = Path(session).resolve() / "temp"
    directory.mkdir(exist_ok=False)
    for key in ("TMP", "TEMP", "TMPDIR"):
        environ[key] = str(directory)
    # tempfile may already have cached the old Windows TEMP during startup.
    tempfile_module.tempdir = str(directory)
    return directory


def configure_private_ui(bpy, resources):
    """No first-run splash or preference autosave in the disposable process."""
    config = Path(bpy.utils.user_resource("CONFIG", create=True)).resolve()
    if not config.is_relative_to(Path(resources).resolve()):
        raise RuntimeError("Blender resolved its configuration outside the private resources")
    bpy.context.preferences.view.show_splash = False
    bpy.context.preferences.use_preferences_save = False
    return {"config": str(config), "show_splash": False, "preference_autosave": False}


def run(args, argv=None):
    import bpy  # Blender-only entry point; pure prepare/tests never import this.

    require_factory_process(bpy, sys.argv if argv is None else argv)
    record = prepare(args)
    record["private_ui"] = configure_private_ui(bpy, record["resources"])
    record["temporary_files"] = str(private_temporary_files(args.session_dir))
    package = Path(record["addon_package"])
    sys.path.insert(0, str(package.parent))
    if record["cad"]:
        sys.path.insert(0, record["cad"]["solver"])
        solver = importlib.import_module("slvs")
        if not Path(solver.__file__).resolve().is_relative_to(Path(record["cad"]["solver"])):
            raise RuntimeError("Solver module did not resolve to the private wheel extraction")
        cad = importlib.import_module("CAD_Sketcher")
        if not Path(cad.__file__).resolve().is_relative_to(Path(record["cad"]["package"])):
            raise RuntimeError("CAD module did not resolve to the private copy")
        bpy.context.preferences.addons.new().module = "CAD_Sketcher"
        cad.register()
    # Register CAD before loading its native saved data. The original is never
    # opened, saved or overwritten; scripts embedded in the copy are disabled.
    loaded = bpy.ops.wm.open_mainfile(filepath=record["working_blend"], load_ui=False, use_scripts=False)
    if "FINISHED" not in loaded or Path(bpy.data.filepath).resolve() != Path(record["working_blend"]):
        raise RuntimeError("Private working copy did not load; no host was started")
    addon = importlib.import_module("spatial_modeling")
    if not Path(addon.__file__).resolve().is_relative_to(package):
        raise RuntimeError("Host module did not resolve to the private copy")
    configure_private_server(addon.host.server, record["host_port"])
    bpy.context.preferences.addons.new().module = "spatial_modeling"
    addon.register()
    prefs = bpy.context.preferences.addons["spatial_modeling"].preferences
    if prefs.lan_enabled or prefs.role != "HOST":
        addon.unregister()
        raise RuntimeError("Private host must stay local-only in HOST role")
    host = addon.host._server
    if host is None or host.host != "127.0.0.1" or host.port != record["host_port"]:
        addon.unregister()
        raise RuntimeError("Private host failed to bind its explicit isolated port")
    record.update(status="host_ready", process_id=os.getpid(), cad_available=addon.host.sketch.dependency_status()["available"])
    if record["cad"] and not record["cad_available"]:
        addon.unregister()
        raise RuntimeError("Pinned private CAD/solver failed dependency verification")
    Path(args.session_dir, "bootstrap.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"P25_PRIVATE_HOST_READY pid={os.getpid()} loopback_port={host.port} cad={record['cad_available']}", flush=True)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--session-dir", type=Path, required=True)
    result.add_argument("--blend", type=Path, required=True)
    result.add_argument("--addon-root", type=Path, required=True)
    result.add_argument("--host-port", type=isolated_port, required=True)
    result.add_argument("--cad-extension", type=Path)
    return result


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    run(parser().parse_args(argv))

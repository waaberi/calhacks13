"""Load an exact C ZIP and pinned CAD in one newly created isolated Blender."""
import argparse
import importlib
import json
import os
import sys
import traceback
import zipfile
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fresh_c import (
    archive_entries,
    package_identity,
    require_free_port,
    sha256,
    verify_cad,
    write_json,
)


def inside(path, parent):
    return Path(path).resolve().is_relative_to(Path(parent).resolve())


def unpack(archive_path, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive_path) as archive:
        for name, data in archive_entries(archive).items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def start(config, expected_port=8765, before_register=None):
    """Listener injection is an owned native-test hook, never a production CLI option."""
    import bpy
    if "--factory-startup" not in sys.argv:
        raise RuntimeError("Fresh C requires a new factory-startup Blender")
    session = Path(config["session"]).resolve()
    resources = Path(os.environ.get("BLENDER_USER_RESOURCES", "")).resolve()
    if resources != session / "blender-resources":
        raise RuntimeError("Fresh C resource directory does not match its new session")
    for key in ("BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        if not os.environ.get(key) or not inside(os.environ[key], resources):
            raise RuntimeError("Blender user path is outside the private C resources")
    if bpy.app.version != (5, 2, 2) or sys.version_info[:2] != (3, 13):
        raise RuntimeError("Fresh C requires the pinned Blender5.2.2/Python3.13")
    working, addon, cad = (Path(config[key]).resolve() for key in ("working_copy", "addon", "cad_extension"))
    if any(not inside(path, session) for path in (working, addon, cad)):
        raise RuntimeError("Fresh C inputs must be the prepared private copies")
    require_free_port(expected_port)
    identity = package_identity(addon, config["addon_sha256"])
    pins = verify_cad(cad)
    if any(name == "CAD_Sketcher" or name.endswith(".CAD_Sketcher")
           or name == "spatial_modeling" or name.startswith("spatial_modeling.") for name in sys.modules):
        raise RuntimeError("A CAD/project add-on was already imported; use a new isolated Blender")
    python_dir = resources / "private-python"
    unpack(cad / "wheels/slvs-3.2-cp313-cp313-win_amd64.whl", python_dir)
    sys.path[:0] = [str(python_dir), str(cad.parent)]
    cad_module = importlib.import_module("CAD_Sketcher")
    if not inside(cad_module.__file__, cad):
        raise RuntimeError("CAD Sketcher loaded from a different installation")
    # This entry is required before register() initializes its logger/preferences.
    bpy.context.preferences.addons.new().module = "CAD_Sketcher"
    cad_module.register()
    slvs = importlib.import_module("slvs")
    native_slvs = importlib.import_module("slvs.solvespace")
    if (version("slvs") != "3.2" or not inside(slvs.__file__, python_dir)
            or not inside(native_slvs.__file__, python_dir)
            or not hasattr(bpy.types.Curves, "sketch_constraints")):
        raise RuntimeError("Pinned private native slvs/CAD registration did not load")
    # Register native constraint property groups before loading editable sketches.
    bpy.ops.wm.open_mainfile(filepath=str(working), load_ui=False)
    addon_dir = resources / "private-addons" / "spatial_modeling"
    unpack(addon, addon_dir)
    for name, digest in identity["files"].items():
        if sha256(addon_dir / name) != digest:
            raise RuntimeError("Extracted project source does not match the selected C ZIP")
    sys.path.insert(0, str(addon_dir.parent))
    package = importlib.import_module("spatial_modeling")
    if not inside(package.__file__, addon_dir):
        raise RuntimeError("Spatial Modeling loaded from a different source")
    # Private process-local activation avoids shared extension dependency reconciliation.
    bpy.context.preferences.addons.new().module = "spatial_modeling"
    if before_register is not None:
        before_register(package)
    package.register()
    prefs = bpy.context.preferences.addons["spatial_modeling"].preferences
    host = importlib.import_module("spatial_modeling.host")
    if prefs.role != "HOST" or prefs.lan_enabled:
        host.stop()
        raise RuntimeError("Fresh C requires Host role and LAN disabled")
    sketch = importlib.import_module("spatial_modeling.sketch")
    dependency = sketch.dependency_status()
    if dependency.get("available") is not True:
        host.stop()
        raise RuntimeError("Matching C add-on did not confirm the pinned CAD dependency")
    if host._server is None or host._server.host != "127.0.0.1" or host._server.port != expected_port:
        host.stop()
        raise RuntimeError("The new private C host did not own its expected loopback listener")
    sync = importlib.import_module("spatial_modeling.sync")
    sync.flush()
    ready = {"status": "ready", "pid": os.getpid(), "host": "127.0.0.1", "port": host._server.port,
             "working_copy": str(Path(bpy.data.filepath).resolve()), "source_revision": identity["source_revision"],
             "zip_sha256": identity["zip_sha256"], "source_files": identity["files"],
             "cad": dependency, "cad_pins": pins, "blender": bpy.app.version_string,
             "python": sys.version, "addon_module": str(Path(package.__file__).resolve()),
             "cad_module": str(Path(cad_module.__file__).resolve()),
             "slvs_module": str(Path(slvs.__file__).resolve()),
             "slvs_native": str(Path(native_slvs.__file__).resolve()),
             "host_epoch": host._session.host_epoch, "document": sync.describe()}
    write_json(session / "c-ready.json", ready)
    def stop_requested():
        if (session / "stop.signal").exists():
            host.stop()
            write_json(session / "c-stopped.json", {"pid": os.getpid(), "reason": "owned session stop.signal"})
            bpy.ops.wm.quit_blender()
            return None
        return .2
    bpy.app.timers.register(stop_requested, first_interval=.2, persistent=True)
    print("FRESH_C_HOST_READY private package/CAD and native listener; no global preferences saved", flush=True)
    return ready


def main():
    import bpy
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if Path(config["session"]).resolve() != args.config.resolve().parent:
        raise RuntimeError("C bootstrap config/session mismatch")

    def initialize():
        try:
            start(config)
        except Exception:  # noqa: BLE001 - preserve startup diagnostics, then close only this new process
            write_json(Path(config["session"]) / "c-error.json", {"error": traceback.format_exc()})
            print(traceback.format_exc(), flush=True)
            package = sys.modules.get("spatial_modeling.host")
            if package is not None:
                package.stop()
            bpy.ops.wm.quit_blender()

    bpy.app.timers.register(initialize, first_interval=.5)


if __name__ == "__main__":
    main()

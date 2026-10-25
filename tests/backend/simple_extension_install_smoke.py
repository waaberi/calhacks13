"""Install the delivered ZIP into an isolated Blender profile; never contact a host."""
import hashlib
import importlib
import json
import sys
import traceback
import uuid
from pathlib import Path

import addon_utils
import bpy

folder = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
manifest = json.loads((folder / "SHA256-MANIFEST.json").read_text(encoding="utf-8"))
archive = folder / manifest["zip"]
MODULE = "bl_ext.user_default.spatial_modeling"
report = {"passed": False, "production_source": manifest["production_source"],
          "zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
          "blender_version": bpy.app.version_string, "module": MODULE,
          "host_connections": 0, "checks": []}
try:
    assert report["zip_sha256"] == manifest["zip_sha256"]
    assert bpy.ops.extensions.package_install_files(filepath=str(archive), repo="user_default",
                                                   enable_on_install=False) == {"FINISHED"}
    addon = importlib.import_module(MODULE)
    original_sync = addon.host.sync
    addon.host.sync = lambda: None
    try:
        enabled = addon_utils.enable(MODULE, default_set=True, persistent=False)
        assert enabled is addon
        prefs = bpy.context.preferences.addons[MODULE].preferences
        prefs.role = "CLIENT"
    finally:
        addon.host.sync = original_sync
    assert prefs.role == "CLIENT" and addon.host._server is None
    report["checks"].append("actual extension ZIP installs and enables in extension namespace without host startup")
    installed = Path(addon.__file__).resolve().parent
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((installed / name).read_bytes()).hexdigest() == expected["sha256"], name
    report["checks"].append(f"all {len(manifest['files'])} installed production files match pinned SHA256 manifest")
    for name in ("client_move", "client_rotate", "client_scale", "client_delete", "client_undo", "client_redo"):
        assert getattr(bpy.ops.spatial_modeling, name).get_rna_type().identifier
    if "native_sync/document.py" in manifest["files"]:
        for name in ("native_take_turn", "native_finish_turn", "native_save_copy", "native_reload"):
            assert getattr(bpy.ops.spatial_modeling, name).get_rna_type().identifier
        native = importlib.import_module(MODULE + ".native_sync.document")
        assert native.NativeDocument().can_capture()
        assert callable(native.document_fingerprint)
        assert importlib.import_module(MODULE + ".session").APP["version"] == "0.2.0"
        report["checks"].append("native 0.2.0 operators, document engine and fingerprint resolve in extension namespace")
    rc = addon.remote_client
    assert callable(rc._live_tick) and callable(rc.live.begin_drag) and callable(rc.live.finish_drag)
    report["checks"].append("registered native Client edit/history operators and modal lifecycle hooks resolve")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    mirror_module = importlib.import_module(MODULE + ".remote_client.mirror")
    mirror = mirror_module.Mirror()
    oid = uuid.uuid4().hex
    state = rc.SceneState()
    state.receive({"document": {"id": uuid.uuid4().hex, "open_epoch": uuid.uuid4().hex,
        "name": "isolated-install-smoke", "revision": 0, "dirty": False,
        "units": {"system": "METRIC", "scale_length": 1}}, "sketches": [],
        "objects": [{"id": oid, "generation": 0, "name": "Packaged object", "type": "MESH",
        "visible": True, "parent": None, "color": [.8, .8, .8, 1],
        "transform": {"location": [0, 0, 0], "rotation": [1, 0, 0, 0], "scale": [1, 1, 1]},
        "mesh": {"positions": [0, 0, 0, 1, 0, 0, 0, 1, 0], "indices": [0, 1, 2]}}]}, True)
    mirror.apply(state)
    mirror.set_editable(True)
    bpy.context.view_layer.update()
    target = mirror.objects[oid]
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    assert bpy.ops.transform.translate(value=(.025, 0, 0)) == {"FINISHED"}
    bpy.context.view_layer.update()
    assert abs(mirror.local_transforms()[oid]["location"][0] - .025) < 1e-6
    assert not target.hide_select
    mirror.set_editable(False)
    assert target.hide_select
    mirror.clear()
    report["checks"].append("packaged mirror accepts actual Blender native transform and disables selection when read-only")
    addon_utils.disable(MODULE, default_set=True)
    report["passed"] = True
except Exception:  # noqa: BLE001 - preserve any isolated install failure before Blender exits
    report["error"] = traceback.format_exc()
finally:
    (folder / "INSTALL-SMOKE.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)
if not report["passed"]:
    raise SystemExit(1)

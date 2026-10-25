"""Actual File Open supersedes pending three-phase native checkpoint callbacks."""
import json
import sys
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
from spatial_modeling.native_sync.document import NativeDocument, NativeDocumentCancelled

out = Path(sys.argv[sys.argv.index("--") + 1])
fixture = Path(sys.argv[sys.argv.index("--") + 2])
out.mkdir(parents=True, exist_ok=True)
report = {"passed": False, "checks": [], "headless": bpy.app.background}
pending, errors, successes = [], [], []
document = NativeDocument(schedule=lambda callback, delay: pending.append(callback))
try:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cube_add(size=.31)
    bpy.context.object.name = "NativeSync_UserOpenedFreshDocument"
    bpy.context.object["user_file_note"] = "must remain untouched by late native callbacks"
    replacement = out / "user-replacement.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(replacement), copy=True, compress=False)
    bpy.ops.wm.open_mainfile(filepath=str(fixture / "baseline.blend"))
    manifest = json.loads((fixture / "candidate-manifest.json").read_text())
    active = json.loads((fixture / "candidate-active.json").read_text())
    document.apply(fixture / "candidate.blend", manifest, successes.append, errors.append,
                   active_scene_uuid=active)
    assert document.busy and pending
    bpy.ops.wm.open_mainfile(filepath=str(replacement))
    assert not document.busy and document._transaction is None
    assert len(errors) == 1 and isinstance(errors[0], NativeDocumentCancelled)
    report["checks"].append("actual File Open cancels pending native transaction with typed error before old-ID deletion")
    while pending:
        callback = pending.pop(0)
        with bpy.context.temp_override(window=bpy.context.window):
            callback()
    assert not successes
    assert bpy.data.filepath == str(replacement)
    assert set(bpy.data.objects.keys()) == {"NativeSync_UserOpenedFreshDocument"}
    fresh = bpy.data.objects["NativeSync_UserOpenedFreshDocument"]
    assert fresh["user_file_note"] == "must remain untouched by late native callbacks"
    assert len(fresh.data.vertices) == 8
    report["checks"].append("late scheduled callbacks are no-ops and preserve new file's exact object/data/metadata")
    bpy.ops.wm.open_mainfile(filepath=str(fixture / "baseline.blend"))
    document.apply(fixture / "candidate.blend", manifest, successes.append, errors.append,
                   active_scene_uuid=active)
    callback = pending.pop(0)
    with bpy.context.temp_override(window=bpy.context.window):
        callback()
    assert document.busy and document._transaction["removed"] and pending
    bpy.ops.wm.open_mainfile(filepath=str(replacement))
    assert not document.busy and len(errors) == 2 and isinstance(errors[-1], NativeDocumentCancelled)
    while pending:
        with bpy.context.temp_override(window=bpy.context.window):
            pending.pop(0)()
    assert not successes and set(bpy.data.objects.keys()) == {"NativeSync_UserOpenedFreshDocument"}
    assert bpy.data.objects["NativeSync_UserOpenedFreshDocument"]["user_file_note"] == "must remain untouched by late native callbacks"
    report["checks"].append("File Open after old-ID deletion also cancels finalization without touching replacement file")
    bpy.ops.wm.open_mainfile(filepath=str(fixture / "baseline.blend"))
    original_scene = bpy.context.window.scene
    original_objects = set(bpy.data.objects.keys())
    document.apply(fixture / "candidate.blend", manifest, successes.append, errors.append,
                   active_scene_uuid=active)
    bpy.context.window.scene = original_scene
    while pending:
        with bpy.context.temp_override(window=bpy.context.window):
            pending.pop(0)()
    assert not document.busy and not successes and len(errors) == 3
    assert isinstance(errors[-1], NativeDocumentCancelled)
    assert bpy.context.window.scene == original_scene and set(bpy.data.objects.keys()) == original_objects
    report["checks"].append("user scene switch before deletion rejects transaction and cleans only staged document IDs")
    report["passed"] = True
except Exception:  # noqa: BLE001 - preserve owned headless document lifecycle failures
    report["error"] = traceback.format_exc()
finally:
    (out / "RESULT.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)

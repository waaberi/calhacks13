"""Actual whole-native checkpoint capture/import/history in disposable Blender."""
import argparse
import json
import sys
import time
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
sys.path.insert(0, str(Path(__file__).parent))
from native_fixture import build_fixture, edit_fixture, edit_topology_fixture
from native_graph import capture_graph, differences
from spatial_modeling.native_sync.document import (
    MANIFEST_GROUPS,
    NativeDocument,
    NativeDocumentError,
)

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
parser.add_argument("--apply", action="store_true")
parser.add_argument("--skip-negative", action="store_true")
parser.add_argument("--edit-mode", action="store_true")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
out = Path(args.output)
report = {"passed": False, "checks": [], "network_sync_tested": False}
pending = []

def schedule(callback, delay):
    if bpy.app.background:
        pending.append((time.monotonic() + delay, callback))
    else:
        bpy.app.timers.register(callback, first_interval=delay)


document = NativeDocument(schedule=schedule)
state = {}


def unused():
    return {"material": bpy.data.materials.get("NativeSync_UnusedMaterial") is not None,
            "mesh": bpy.data.meshes.get("NativeSync_UnusedMesh") is not None,
            "text": bpy.data.texts.get("NativeSync_UnusedText").as_string()
                    if bpy.data.texts.get("NativeSync_UnusedText") else None,
            "fake_user": bool(bpy.data.materials["NativeSync_UnusedMaterial"].use_fake_user)}


def finish(error=None):
    report["passed"] = error is None
    if error is not None:
        report["error"] = str(error)
    (out / ("apply-result.json" if args.apply else "export-result.json")).write_text(json.dumps(report, indent=2))
    bpy.ops.wm.quit_blender()


def redo():
    try:
        bpy.ops.ed.redo()
        assert not differences(state["expected"], capture_graph()), differences(state["expected"], capture_graph())
        assert unused() == state["expected_unused"], unused()
        report["checks"].append("one native Redo restores full topology/UV/modifier/node/driver/shape-key/rig graph")
        finish()
    except Exception:  # noqa: BLE001 - retain actual native history failures
        finish(traceback.format_exc())


def undo():
    try:
        bpy.ops.ed.undo()
        assert not differences(state["before"], capture_graph()), differences(state["before"], capture_graph())
        assert unused() == state["before_unused"]
        report["checks"].append("one native Undo restores prior full graph and unreferenced datablocks")
        schedule(redo, .1)
    except Exception:  # noqa: BLE001 - retain actual native history failures
        finish(traceback.format_exc())


def retry_after_rejection(error):
    try:
        assert isinstance(error, NativeDocumentError), str(error)
        assert not document.busy
        assert not differences(state["before"], capture_graph()), differences(state["before"], capture_graph())
        assert {name: len(getattr(bpy.data, name)) for name in MANIFEST_GROUPS} == state["counts"]
        assert bpy.data.filepath == state["filepath"]
        report["checks"].append("stale/missing native identity rejects with original graph/UI and all ID counts retained")
        document.apply(out / "candidate.blend", json.loads((out / "candidate-manifest.json").read_text()),
            applied, finish, active_scene_uuid=json.loads((out / "candidate-active.json").read_text()))
    except Exception:  # noqa: BLE001 - retain negative native transaction cleanup failures
        finish(traceback.format_exc())


def applied(result):
    try:
        report["apply_report"] = result
        actual = capture_graph()
        assert not differences(state["expected"], actual), differences(state["expected"], actual)
        assert unused() == state["expected_unused"], unused()
        assert bpy.data.filepath == state["filepath"]
        assert not (out / "AUTOEXEC_RAN").exists()
        assert bpy.data.texts["NativeSync_ModuleText"].use_module
        report["checks"].append("received module Text remains native data and never automatically executes")
        report["checks"].append("all original native graph and unreferenced datablocks apply without replacing UI/file path")
        recaptured = document.capture(out / "recaptured.blend")
        assert recaptured.manifest
        report["checks"].append("received native document can be captured again without false weak-library rejection")
        schedule(undo, .1)
    except Exception:  # noqa: BLE001 - retain actual native graph fidelity failures
        finish(traceback.format_exc())


def run():
    try:
        bpy.context.preferences.edit.use_global_undo = True
        if not args.apply:
            build_fixture()
            bpy.data.materials.new("NativeSync_UnusedMaterial")
            bpy.data.meshes.new("NativeSync_UnusedMesh")
            bpy.data.texts.new("NativeSync_UnusedText").write("native unreferenced text data\n")
            baseline = document.capture(out / "baseline.blend")
            (out / "baseline-manifest.json").write_text(json.dumps(baseline.manifest))
            report["checks"].append("capture preserves zero-user unreferenced datablocks and user's filepath")
            module_text = bpy.data.texts.new("NativeSync_ModuleText")
            module_text.use_module = True
            module_text.write("from pathlib import Path\nPath(" + repr(str(out / "AUTOEXEC_RAN")) + ").write_text('unsafe')\n")
            edit_fixture("host")
            edit_fixture("client")
            edit_topology_fixture()
            if args.edit_mode:
                from native_fixture import CUBE, select_only
                select_only(bpy.data.objects[CUBE])
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_all(action="SELECT")
                bpy.ops.transform.translate(value=(.04, 0, 0))
                bpy.context.object.update_from_editmode()
                state["before_edit_capture"] = capture_graph()
                (out / "before-edit-capture.json").write_text(json.dumps(state["before_edit_capture"]))
            snapshot = document.capture(out / "candidate.blend")
            if args.edit_mode:
                (out / "after-edit-capture.json").write_text(json.dumps(capture_graph()))
                report["edit_capture_differences"] = differences(state["before_edit_capture"], capture_graph())
                report["mode_after_capture"] = bpy.context.object.mode
            repeated = document.capture(out / "candidate.blend")
            assert snapshot.sha256 == repeated.sha256, "Unchanged native capture hash is unstable"
            (out / "candidate-manifest.json").write_text(json.dumps(snapshot.manifest))
            (out / "candidate-active.json").write_text(json.dumps(snapshot.active_scene_uuid))
            (out / "expected.json").write_text(json.dumps(capture_graph()))
            (out / "expected-unused.json").write_text(json.dumps(unused()))
            report["checks"].append("full native edited checkpoint captures repeatedly with stable SHA256")
            finish()
        else:
            state["filepath"] = bpy.data.filepath
            state["before"] = capture_graph()
            state["before_unused"] = unused()
            state["expected"] = json.loads((out / "expected.json").read_text())
            state["expected_unused"] = json.loads((out / "expected-unused.json").read_text())
            state["counts"] = {name: len(getattr(bpy.data, name)) for name in MANIFEST_GROUPS}
            if args.skip_negative:
                document.apply(out / "candidate.blend", json.loads((out / "candidate-manifest.json").read_text()),
                    applied, finish, active_scene_uuid=json.loads((out / "candidate-active.json").read_text()))
                return
            bad_manifest = json.loads((out / "candidate-manifest.json").read_text())
            original_identity = next(identity for identity, entry in bad_manifest.items() if entry["group"] != "scenes")
            bad_manifest["0" * 32] = bad_manifest.pop(original_identity)
            document.apply(out / "candidate.blend", bad_manifest,
                lambda _: finish("stale native identity was incorrectly accepted"), retry_after_rejection,
                active_scene_uuid=json.loads((out / "candidate-active.json").read_text()))
    except Exception:  # noqa: BLE001 - retain capture/preflight/import failures
        finish(traceback.format_exc())


schedule(run, 1)
if bpy.app.background:
    deadline = time.monotonic() + 45
    while pending and time.monotonic() < deadline:
        pending.sort(key=lambda item: item[0])
        when, callback = pending[0]
        if time.monotonic() < when:
            time.sleep(.002)
            continue
        pending.pop(0)
        window = bpy.context.window
        print("HEADLESS CALLBACK", callback.__name__, "scene", window.scene.name, flush=True)
        with bpy.context.temp_override(window=window):
            callback()
        print("HEADLESS FINISHED", callback.__name__, flush=True)
    if pending:
        finish("Headless native transaction deadline exceeded")

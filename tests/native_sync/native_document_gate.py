"""Actual whole-native checkpoint capture/import/history in disposable Blender."""
import argparse
import json
import sys
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
sys.path.insert(0, str(Path(__file__).parent))
from native_fixture import build_fixture, edit_fixture, edit_topology_fixture
from native_graph import capture_graph, differences
from spatial_modeling.native_sync.document import NativeDocument

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
parser.add_argument("--apply", action="store_true")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
out = Path(args.output)
report = {"passed": False, "checks": [], "network_sync_tested": False}
document = NativeDocument()
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
        bpy.app.timers.register(redo, first_interval=.1)
    except Exception:  # noqa: BLE001 - retain actual native history failures
        finish(traceback.format_exc())


def applied(result):
    try:
        report["apply_report"] = result
        actual = capture_graph()
        assert not differences(state["expected"], actual), differences(state["expected"], actual)
        assert unused() == state["expected_unused"], unused()
        assert bpy.data.filepath == state["filepath"]
        report["checks"].append("all original native graph and unreferenced datablocks apply without replacing UI/file path")
        bpy.app.timers.register(undo, first_interval=.1)
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
            edit_fixture("host")
            edit_fixture("client")
            edit_topology_fixture()
            snapshot = document.capture(out / "candidate.blend")
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
            document.apply(out / "candidate.blend", json.loads((out / "candidate-manifest.json").read_text()),
                applied, finish, active_scene_uuid=json.loads((out / "candidate-active.json").read_text()))
    except Exception:  # noqa: BLE001 - retain capture/preflight/import failures
        finish(traceback.format_exc())


bpy.app.timers.register(run, first_interval=1)

"""Local native fidelity prerequisite; explicitly not a network-sync acceptance."""
import argparse
import json
import sys
import traceback
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from native_fixture import build_fixture, edit_fixture
from native_graph import assert_original_data, capture_graph, differences

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
parser.add_argument("--reopen", action="store_true")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)
report = {"passed": False, "network_sync_tested": False, "checks": []}
state = {}


def same(expected):
    actual = capture_graph()
    mismatch = differences(expected, actual)
    assert not mismatch, mismatch
    assert_original_data(actual)


def save(name, graph):
    bpy.ops.wm.save_as_mainfile(filepath=str(out / (name + ".blend")), copy=True, compress=False)
    (out / (name + ".json")).write_text(json.dumps(graph, indent=2))


def steps():
    if args.reopen:
        same(json.loads((out / "client-edited.json").read_text()))
        report["checks"].append("full original graph survives fresh .blend reopen")
        return
    bpy.context.preferences.edit.use_global_undo = True
    build_fixture()
    state["baseline"] = capture_graph()
    assert_original_data(state["baseline"])
    save("baseline", state["baseline"])
    bpy.ops.ed.undo_push(message="Native fidelity baseline")
    report["checks"].append("self-contained original native dependency graph created")
    yield
    edit_fixture("host")
    state["host"] = capture_graph()
    assert_original_data(state["host"])
    assert differences(state["baseline"], state["host"])
    save("host-edited", state["host"])
    bpy.ops.ed.undo_push(message="Host full native data transaction")
    report["checks"].append("Host ordinary Edit Mode/modifier/UV/material/driver-property edits recorded")
    yield
    bpy.ops.ed.undo()
    same(state["baseline"])
    report["checks"].append("Host native Undo restores complete original graph")
    yield
    bpy.ops.ed.redo()
    same(state["host"])
    report["checks"].append("Host native Redo restores complete edited graph")
    yield
    edit_fixture("client")
    state["client"] = capture_graph()
    assert_original_data(state["client"])
    assert differences(state["host"], state["client"])
    save("client-edited", state["client"])
    bpy.ops.ed.undo_push(message="Client full native data transaction")
    report["checks"].append("Client ordinary Edit Mode/node-group/shape-key/pose edits recorded")
    yield
    bpy.ops.ed.undo()
    same(state["host"])
    report["checks"].append("Client native Undo preserves prior Host edit")
    yield
    bpy.ops.ed.redo()
    same(state["client"])
    report["checks"].append("Client native Redo restores complete second-side graph")


def finish():
    report["native_blender_version"] = bpy.app.version_string
    (out / ("reopen-result.json" if args.reopen else "fixture-result.json")).write_text(json.dumps(report, indent=2))
    bpy.ops.wm.quit_blender()


def tick():
    try:
        area = next(area for area in bpy.context.window.screen.areas if area.type == "VIEW_3D")
        region = next(region for region in area.regions if region.type == "WINDOW")
        with bpy.context.temp_override(area=area, region=region):
            next(scenario)
        return .15
    except StopIteration:
        report["passed"] = True
        finish()
    except Exception:  # noqa: BLE001 - retain native timer failures before disposable process exits
        report["error"] = traceback.format_exc()
        finish()
    return None


scenario = steps()
bpy.app.timers.register(tick, first_interval=1)

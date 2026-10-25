"""Host-solved records are preserved atomically, with no local constraint solve."""
import copy
import importlib.util
import json
import math
from pathlib import Path

import pytest
from test_remote_state import SceneState

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "remote_sketch_paths", ROOT / "blender_addon/spatial_modeling/remote_client/sketches.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def snapshot():
    return json.loads((ROOT / "contracts/examples/scene.snapshot.json").read_text())["payload"]


def test_full_records_live_dimension_generation_removal_and_snapshot_replacement():
    body = snapshot()
    state = SceneState()
    state.receive(body, True)
    sid = body["sketches"][0]["id"]
    assert state.sketches[sid] == body["sketches"][0]
    update = {"document": copy.deepcopy(body["document"]), "objects": [], "removed": [],
              "sketches": copy.deepcopy(body["sketches"])}
    update["document"]["revision"] += 1
    record = update["sketches"][0]
    record["generation"] = update["document"]["revision"]
    for point in record["entities"]:
        if point["kind"] == "point" and point["at"][0] > .05:
            point["at"][0] = .12
    record["constraints"][-2]["value"] = .12
    state.receive(update, False)
    assert state.sketches[sid]["constraints"][-2]["value"] == .12
    assert state.sketches[sid]["entities"] == record["entities"]
    assert len(MODULE.polylines(state.sketches[sid])) == 4
    state.receive({**update, "sketches": [], "removed": [sid]}, False)
    assert not state.sketches
    state.receive(body, True)
    assert state.sketches[sid] == body["sketches"][0]
    state.receive({**body, "sketches": []}, True)
    assert not state.sketches


@pytest.mark.parametrize("bad", ["point_ref", "constraint_ref", "duplicate", "cross_kind",
    "radius", "plane", "solver", "generation", "regress", "same_generation", "nan"])
def test_invalid_sketch_never_partially_changes_valid_scene(bad):
    body = snapshot()
    state = SceneState()
    state.receive(body, True)
    before = copy.deepcopy((state.document, state.objects, state.sketches))
    update = copy.deepcopy(body)
    update["document"]["revision"] += 1
    update["removed"] = [body["objects"][0]["id"]]
    update["objects"] = []
    record = update["sketches"][0]
    record["generation"] = update["document"]["revision"]
    if bad == "point_ref": record["entities"][-1]["points"][0] = "missing"
    if bad == "constraint_ref": record["constraints"][0]["entities"] = ["missing"]
    if bad == "duplicate": update["sketches"].append(copy.deepcopy(record))
    if bad == "cross_kind": record["id"] = body["objects"][1]["id"]
    if bad == "radius": record["entities"].append({"id": "circle", "kind": "circle", "center": "p1", "radius": 0})
    if bad == "plane": record["plane"]["rotation"] = [0, 0, 0, 0]
    if bad == "solver": record["solver"]["dof"] = -1
    if bad == "generation": record["generation"] += 1
    if bad == "regress": record["generation"] = 1
    if bad == "same_generation":
        record["generation"] = body["sketches"][0]["generation"]
        record["name"] = "changed without generation"
    if bad == "nan": record["entities"][0]["at"][0] = math.nan
    with pytest.raises(ValueError):
        state.receive(update, False)
    assert (state.document, state.objects, state.sketches) == before


def test_analytic_circle_tessellation_uses_only_solved_center_radius():
    record = {"entities": [{"id": "center", "kind": "point", "at": [.03, .04]},
                           {"id": "circle", "kind": "circle", "center": "center", "radius": .015}]}
    points, cyclic = MODULE.polylines(record)[0]
    assert cyclic and len(points) == 128
    assert all(math.isclose(math.hypot(x-.03, y-.04), .015, abs_tol=1e-12) for x, y, z in points)


@pytest.mark.parametrize("value", [{}, [1]])
def test_wrong_sketch_container_or_record_fails_without_touching_current_scene(value):
    state = SceneState()
    body = snapshot()
    state.receive(body, True)
    before = copy.deepcopy(state.sketches)
    with pytest.raises(TypeError):
        state.receive({**body, "sketches": value}, True)
    assert state.sketches == before

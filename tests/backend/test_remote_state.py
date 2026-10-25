"""Semantic mirror acceptance: no bpy dependency, real contract fixture."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "p2_state", ROOT / "blender_addon/spatial_modeling/remote_client/state.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SceneState = MODULE.SceneState


@pytest.fixture
def snapshot():
    return json.loads((ROOT / "contracts/examples/scene.snapshot.json").read_text())["payload"]


def test_semantic_reference_and_units(snapshot):
    state = SceneState()
    state.receive(snapshot, True)
    first = snapshot["objects"][0]
    result = state.check_reference({first["id"]: [0, 0, .005]})
    assert result["wire_units"] == "meters" and result["scale_length"] == .001
    with pytest.raises(ValueError, match="Position mismatch"):
        state.check_reference({first["id"]: [0, 0, 5]})


def test_delta_mesh_retention_delete_and_stale(snapshot):
    state = SceneState()
    state.receive(snapshot, True)
    first = copy.deepcopy(snapshot["objects"][0])
    first.pop("mesh")
    first["transform"]["location"][0] = .01
    delta = {**copy.deepcopy(snapshot), "objects": [first], "removed": []}
    delta["document"]["revision"] += 1
    state.receive(delta, False)
    assert state.objects[first["id"]]["mesh"] == snapshot["objects"][0]["mesh"]
    assert state.objects[first["id"]]["transform"]["location"][0] == .01
    # A dirty/save update may repeat a revision.
    state.receive({**delta, "objects": []}, False)
    state.stale()
    with pytest.raises(ValueError, match="stale"):
        state.check_reference({})
    with pytest.raises(ValueError, match="fresh snapshot"):
        state.receive(delta, False)
    state.receive(snapshot, True)
    assert state.current


@pytest.mark.parametrize("problem", ["gap", "document", "units", "mesh", "duplicate", "parent"])
def test_bad_scenes_cannot_partly_replace_current_scene(snapshot, problem):
    state = SceneState()
    state.receive(snapshot, True)
    before = copy.deepcopy(state.objects)
    bad = copy.deepcopy(snapshot)
    bad["removed"] = []
    if problem == "gap": bad["document"]["revision"] += 2
    if problem == "document": bad["document"]["id"] = "another"
    if problem == "units": bad["document"]["units"]["scale_length"] = 0
    if problem == "mesh": bad["objects"][0]["mesh"]["indices"][0] = 999999
    if problem == "duplicate": bad["objects"].append(copy.deepcopy(bad["objects"][0]))
    if problem == "parent": bad["objects"][0]["parent"] = "missing"
    with pytest.raises(ValueError):
        state.receive(bad, False)
    assert state.objects == before

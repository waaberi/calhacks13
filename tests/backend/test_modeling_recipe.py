"""Pure complete-plan checks; no Blender, UI input, API key or native mutation."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "blender_addon" / "spatial_modeling"))
import modeling_recipe as recipe

A, B = "a" * 32, "b" * 32


def catalog():
    return [{"id": tool, "modes": ["EDIT_MESH"], "components": components,
             "parameters": {"required": required}, "outputs": outputs}
            for tool, components, required, outputs in (
                ("mesh.inset", ["face"], ["thickness_m"], ["inner_faces", "boundary_edges"]),
                ("mesh.extrude", ["vertex", "edge", "face"], ["translation_m"], ["new_faces", "new_edges", "new_vertices"]),
                ("mesh.bevel", ["vertex", "edge"], ["width_m"], ["new_faces"]),
                ("mesh.loop_cut", ["edge"], ["cuts"], ["new_edges"]),
                ("mesh.knife", ["face"], ["path_m"], ["new_edges"]),
                ("mesh.merge", ["vertex"], ["variant"], ["selection"]),
                ("mesh.dissolve", ["vertex", "edge", "face"], [], ["selection"]),
                ("mesh.delete", ["vertex", "edge", "face"], ["domain"], ["selection"]),
                ("mesh.translate", ["vertex", "edge", "face"], ["translation_m"], ["selection"]),
            )]


def context():
    return {"document_id": "d" * 32, "open_epoch": "e" * 32, "revision": 7,
            "mode": "EDIT_MESH", "native_tool": "builtin.inset", "topology_token": "f" * 64,
            "options": {}, "objects": [{"id": A, "name": "Cube", "generation": 3},
                                      {"id": B, "name": "Shaft", "generation": 2}],
            "selection": {"objects": [{"id": A, "generation": 3}], "component": "face", "indices": [1, 2]}}


def step(tool="mesh.inset", params=None, selection="captured", sid="first", target="selected"):
    return {"id": sid, "tool": tool, "target": target, "selection": selection,
            "params": {"thickness_m": .002} if params is None else params}


def prepare(steps=None, expected=None, actual=None, stage=None):
    planner = recipe.Planner(catalog(), lambda tool, params, component: params, lambda: 1)
    draft = {"decision": "propose", "steps": steps or [step()], "missing": [], "reason": "", "unhandled_intent": []}
    pid, plan = planner.prepare(draft, expected or context(), actual or context(), "actor", stage)
    return pid, plan


def test_complete_ordered_recipe_preserves_selected_components_and_geometry_outputs():
    _, plan = prepare([step(), step("mesh.extrude", {"translation_m": [0, 0, .005]},
                                  {"step": "first", "output": "inner_faces"}, "second"),
                       step("mesh.bevel", {"width_m": .0005},
                            {"step": "first", "output": "boundary_edges"}, "third")])
    assert [s["tool"] for s in plan["steps"]] == ["mesh.inset", "mesh.extrude", "mesh.bevel"]
    assert plan["steps"][0]["selection"] == {"component": "face", "indices": [1, 2]}
    assert all(s["target"] == A for s in plan["steps"])
    assert plan["generations"] == {A: 3}
    assert plan["confirm"] is True


@pytest.mark.parametrize("variant", ["FIRST", "LAST"])
def test_first_last_merge_requires_actual_ordered_native_vertex_picks(variant):
    captured = context()
    captured["selection"].update(component="vertex", indices=[2, 1])
    captured["native_selection"] = copy.deepcopy(captured["selection"])
    captured["native_selection"]["order_complete"] = False
    with pytest.raises(recipe.Clarify):
        prepare([step("mesh.merge", {"variant": variant})], expected=captured, actual=captured)
    captured["native_selection"]["order_complete"] = True
    _, plan = prepare([step("mesh.merge", {"variant": variant})], expected=captured, actual=captured)
    assert plan["steps"][0]["selection"]["indices"] == [2, 1]


@pytest.mark.parametrize("tool,component,params", [
    ("mesh.extrude", "face", {"translation_m": [0, 0, .005]}),
    ("mesh.inset", "face", {"thickness_m": .002}),
    ("mesh.bevel", "edge", {"width_m": .0005}),
    ("mesh.loop_cut", "edge", {"cuts": 2, "slide": .2}),
    ("mesh.knife", "face", {"path_m": [[0, 0, 0], [.01, 0, 0]]}),
    ("mesh.merge", "vertex", {"variant": "CENTER"}),
    ("mesh.dissolve", "edge", {}),
    ("mesh.delete", "face", {"domain": "FACES"}),
    ("mesh.translate", "vertex", {"translation_m": [.01, 0, 0], "constraint_axis": [True, False, False],
                                   "proportional_radius_m": .02, "snap_increment_m": .001}),
])
def test_every_required_family_compiles_typed_parameters(tool, component, params):
    _, plan = prepare([step(tool, params, {"component": component, "indices": [1, 2]})])
    assert plan["steps"][0]["params"] == params


@pytest.mark.parametrize("field,value", [("document_id", "1"*32), ("open_epoch", "2"*32),
    ("revision", 8), ("mode", "OBJECT"), ("native_tool", "builtin.bevel"),
    ("topology_token", "0"*64), ("options", {"snap": True})])
def test_stale_ai_context_cannot_be_retargeted(field, value):
    current = context(); current[field] = value
    with pytest.raises(recipe.InvalidRecipe):
        prepare(actual=current)


def test_changed_secondary_target_is_refused_before_any_staging():
    current = context(); current["objects"][1]["generation"] += 1
    with pytest.raises(recipe.InvalidRecipe):
        prepare(actual=current, stage=lambda *_: pytest.fail("must not stage a stale request"))


@pytest.mark.parametrize("tail", [step("bpy.ops.mesh.inset"), step("exec"),
    step("mesh.inset", {"thickness_m": float("nan")}),
    {**step(), "python": "danger()"}, step(selection={"step": "future", "output": "inner_faces"}),
    step(selection={"component": "face", "indices": [True]})])
def test_invalid_tail_never_returns_a_valid_prefix_or_stages(tail):
    tail = copy.deepcopy(tail); tail["id"] = "second"
    with pytest.raises(recipe.InvalidRecipe):
        prepare([step(), tail], stage=lambda *_: pytest.fail("invalid whole plan must not stage"))


def test_missing_value_clarifies_without_inventing_a_default():
    with pytest.raises(recipe.Clarify) as caught:
        prepare([step(params={})])
    assert caught.value.field == "first.thickness_m"


def test_invalid_output_reference_rejected_before_native_work():
    with pytest.raises(recipe.InvalidRecipe):
        prepare([step(), step("mesh.extrude", {"translation_m": [0, 0, .001]},
                             {"step": "first", "output": "invented_faces"}, "second")])


def test_alias_order_uses_the_snapshot_sent_to_the_model():
    expected = context(); expected["objects"].reverse()
    _, plan = prepare([step(target="object_0")], expected=expected)
    assert plan["steps"][0]["target"] == B


def test_stage_only_after_complete_validation_and_never_modifies_input():
    original = context(); calls = []
    _, plan = prepare(stage=lambda steps, ctx: calls.append((steps, ctx)) or {"summary": "preview"})
    assert len(calls) == 1 and plan["preview"] == {"summary": "preview"}
    assert context() == original


def test_unhandled_intent_refuses_whole_plan():
    planner = recipe.Planner(catalog(), lambda *args: {}, lambda: 1)
    with pytest.raises(recipe.InvalidRecipe):
        planner.prepare({"decision": "propose", "steps": [step()], "unhandled_intent": ["teleport"]}, context(), context(), "actor")


def test_native_component_change_without_geometry_revision_invalidates_plan():
    expected = context(); actual = context()
    expected["native_selection"] = {"component": "face", "indices": [1, 2], "selection_token": "old"}
    actual["native_selection"] = {"component": "face", "indices": [3], "selection_token": "new"}
    with pytest.raises(recipe.InvalidRecipe):
        prepare(expected=expected, actual=actual)


def test_local_mesh_selection_must_match_acknowledged_native_components():
    expected = context(); actual = context()
    actual["native_selection"] = {"component": "face", "indices": [3]}
    with pytest.raises(recipe.InvalidRecipe):
        prepare(expected=expected, actual=actual)


def test_unacknowledged_live_selection_refuses_plan():
    expected = context(); expected["gesture_active"] = True
    with pytest.raises(recipe.InvalidRecipe):
        prepare(expected=expected)

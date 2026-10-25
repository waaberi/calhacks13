"""Typed direct-model API validation and native-tool state without Blender."""

import copy
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "backend"))
PACKAGE = "direct_model_backend"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "blender_addon" / "spatial_modeling")]
sys.modules.setdefault(PACKAGE, package)
native = importlib.import_module(PACKAGE + ".spatial_model_edit")


def gesture(tool="builtin.move", mode="OBJECT", component="object", **delta):
    return {"native_tool": tool, "mode": mode, "component": component,
            "indices": [] if component == "object" else [0],
            "topology_token": "a" * 64, "delta": delta or {"translation": [.1, 0, 0]}}


@pytest.mark.parametrize("args", [
    gesture(), gesture("builtin.rotate", rotation=[1, 0, 0, 0]),
    gesture("builtin.scale", scale=[-1, 1, .8]),
    gesture("builtin.move", "EDIT_MESH", "vertex"),
    gesture("builtin.rotate", "EDIT_MESH", "edge", rotation=[1, 0, 0, 0]),
    gesture("builtin.scale", "EDIT_MESH", "face", scale=[-1, 1, 2]),
    gesture("builtin.extrude_region", "EDIT_MESH", "face")])
def test_supported_finite_typed_gestures(args):
    native.validate_args(args)


@pytest.mark.parametrize("name,value", [
    ("native_tool", "bpy.ops.mesh.delete"), ("native_tool", []),
    ("mode", "SCULPT"), ("component", "vertex"),
    ("indices", [0]), ("indices", [True]), ("indices", list(range(257))),
    ("topology_token", ""), ("delta", {"translation": [float("nan"), 0, 0]}),
    ("delta", {"translation": [float("inf"), 0, 0]}),
    ("delta", {"translation": [True, 0, 0]}),
    ("delta", {"translation": [1001, 0, 0]}),
    ("delta", {"translation": [1, 0, 0], "scale": [1, 1, 1]}),
    ("delta", {"python": "arbitrary received operator"})])
def test_malformed_gestures_are_refused_before_native_access(name, value):
    args = gesture()
    args[name] = value
    with pytest.raises(ValueError):
        native.validate_args(args)


def test_zero_scale_invalid_selection_and_wrong_tool_parameter_are_refused():
    invalid = [gesture("builtin.scale", scale=[0, 1, 1]),
               gesture("builtin.scale", scale=[.00001, 1, 1]),
               gesture("builtin.extrude_region"),
               gesture("builtin.extrude_region", "EDIT_MESH", "vertex"),
               gesture("builtin.rotate", rotation=[2, 0, 0, 0]),
               gesture("builtin.rotate", translation=[.1, 0, 0])]
    repeated = gesture("builtin.move", "EDIT_MESH", "vertex")
    repeated["indices"] = [0, 0]
    invalid.append(repeated)
    for args in invalid:
        with pytest.raises(ValueError):
            native.validate_args(args)


def test_schema_and_pure_admission_agree_on_wire_shape():
    import commands
    from test_contracts import is_valid, load
    template = load("command.json")
    for args in [gesture(), gesture("builtin.scale", scale=[-1, 1, .8]),
                 gesture("builtin.extrude_region", "EDIT_MESH", "face")]:
        msg = copy.deepcopy(template)
        msg["payload"].update(op="object.spatial_edit", args=args)
        assert commands.command_problem(msg) is None
        assert is_valid("command", msg)
    for args in [gesture("builtin.scale", scale=[0, 1, 1]),
                 gesture("builtin.extrude_region"),
                 gesture("builtin.rotate", translation=[1, 0, 0])]:
        msg["payload"]["args"] = args
        assert commands.command_problem(msg) is not None
        assert not is_valid("command", msg)


def test_native_unsupported_tools_and_multi_window_ambiguity_are_explicit():
    def window(tool):
        return NS(screen=NS(areas=[NS(type="VIEW_3D")]), workspace=NS(tools=NS(
            from_space_view3d_mode=lambda *a, **k: NS(idname=tool))))
    context = NS(mode="OBJECT", window_manager=NS(windows=[window("builtin.bevel")]))
    state = native.read_state(context)
    assert not state["available"] and "Choose Blender" in state["reason"]
    context.window_manager.windows.append(window("builtin.move"))
    assert "one native Blender workspace" in native.read_state(context)["reason"]


def test_state_serialization_failure_does_not_escape_preview_handler():
    state = native.read_state(NS(mode="EDIT_MESH", window_manager=NS(windows=[])))
    assert not state["available"]
    assert state["vertices"] == state["edges"] == state["faces"] == state["triangles"] == []


@pytest.mark.parametrize("tool", ["builtin.move", "builtin.rotate", "builtin.scale", "builtin.select_box"])
def test_no_active_object_exports_authoritative_empty_selection_without_enabling_editing(monkeypatch, tool):
    monkeypatch.setattr(native, "_tool", lambda _context: (tool, ""))
    monkeypatch.setattr(native, "_component", lambda _context: "object")
    context = NS(mode="OBJECT", active_object=None, selected_objects=[])
    state = native.read_state(context)
    assert not state["available"] and state["live_supported"]
    assert state["reason"] == "Select a floating object with the controller to begin."
    assert state["native_tool"] == tool and state["active_object_id"] == ""
    assert state["generation"] == 0 and state["topology_token"] == "" and state["settings"] == {}
    assert state["selection"] == {"component": "object", "objects": [], "indices": [],
                                  "active_id": "", "selection_token": state["selection_token"]}
    assert len(state["selection_token"]) == 64
    assert native.read_state(context)["selection"] == state["selection"]
    assert context.active_object is None and context.selected_objects == []


def test_selected_objects_without_active_object_do_not_invent_an_active_target(monkeypatch):
    monkeypatch.setattr(native, "_tool", lambda _context: ("builtin.scale", ""))
    monkeypatch.setattr(native, "_component", lambda _context: "object")
    obj = {"spatial_modeling_id": "a" * 32}
    context = NS(mode="OBJECT", active_object=None, selected_objects=[obj])
    state = native.read_state(context, NS(generation=lambda _id: 17))
    assert state["selection"]["objects"] == [{"id": "a" * 32, "generation": 17}]
    assert state["selection"]["active_id"] == "" and state["active_object_id"] == ""
    assert not state["available"] and state["settings"] == {}
    assert context.active_object is None and context.selected_objects == [obj]


@pytest.mark.parametrize("mode,component", [("OBJECT", "object"), ("EDIT_MESH", "vertex"), ("EDIT_MESH", "edge")])
def test_live_individual_extrude_reports_face_mode_before_native_geometry(monkeypatch, mode, component):
    monkeypatch.setattr(native, "_tool", lambda _context: ("builtin.extrude_individual", ""))
    monkeypatch.setattr(native, "_component", lambda _context: component)
    state = native.read_state(NS(mode=mode, active_object=None))
    assert not state["available"]
    assert "Extrude Region / Individual" in state["reason"] and "face selection" in state["reason"]


@pytest.mark.parametrize("setting", ["use_snap", "use_proportional_edit", "use_mesh_automerge",
                                    "use_transform_data_origin", "use_transform_skip_children"])
def test_native_tool_options_are_not_silently_ignored(setting):
    context = NS(mode="OBJECT", tool_settings=NS(**{setting: True}))
    with pytest.raises(ValueError, match="native options"):
        native._native_options(context, NS(), "builtin.move")


def test_mesh_mirror_pivot_and_locked_channels_are_explicit():
    context = NS(mode="EDIT_MESH", tool_settings=NS(transform_pivot_point="CURSOR"))
    with pytest.raises(ValueError, match="Pivot CURSOR"):
        native._native_options(context, NS(data=NS()), "builtin.rotate")
    context.tool_settings.transform_pivot_point = "MEDIAN_POINT"
    with pytest.raises(ValueError, match="Mesh Mirror"):
        native._native_options(context, NS(data=NS(use_mirror_x=True)), "builtin.move")
    context.mode = "OBJECT"
    with pytest.raises(ValueError, match="Locked"):
        native._native_options(context, NS(lock_location=(True, False, False)), "builtin.move")


@pytest.mark.parametrize("tool,channel", [("builtin.move", "lock_location"),
                                         ("builtin.rotate", "lock_rotation"),
                                         ("builtin.scale", "lock_scale")])
def test_live_partial_locks_use_native_channels_while_legacy_and_fully_locked_stay_refused(tool, channel):
    context = NS(mode="OBJECT", tool_settings=NS())
    obj = NS(**{channel: (True, False, False)})
    before = copy.deepcopy(vars(obj))
    native._native_options(context, obj, tool, live=True)
    assert vars(obj) == before
    with pytest.raises(ValueError, match="Locked"):
        native._native_options(context, obj, tool)
    setattr(obj, channel, (True, True, True))
    with pytest.raises(ValueError, match="Locked"):
        native._native_options(context, obj, tool, live=True)


@pytest.mark.parametrize("tool", ["builtin.move", "builtin.rotate"])
def test_scale_locks_do_not_block_unrelated_live_tools(tool):
    native._native_options(NS(mode="OBJECT", tool_settings=NS()),
                           NS(lock_scale=(True, True, True)), tool, live=True)


@pytest.mark.parametrize("fields,code", [
    ({"document_id": "f" * 32}, "wrong_document"),
    ({"host_epoch": "f" * 32}, "wrong_session"),
    ({"actor_id": "f" * 32}, "permission_denied")])
def test_direct_api_retains_normal_document_session_actor_authority(fields, code):
    from test_commands import SHAFT, assert_rejected, two_peers
    with two_peers() as (host, owner, _):
        assert_rejected(owner.run("object.spatial_edit", SHAFT, gesture(), **fields), code)
        assert host.editor.applied == []


def test_direct_api_refuses_stale_generation_and_foreign_native_lease():
    from test_commands import SHAFT, assert_rejected, two_peers
    from test_leases import acquire
    with two_peers() as (host, owner, other):
        assert_rejected(owner.run("object.spatial_edit", {"id": SHAFT, "generation": 1}, gesture()),
                        "stale_revision")
        _, reply = other.ask(acquire(other, mode="exclusive"))
        assert reply["type"] == "lease.granted"
        assert_rejected(owner.run("object.spatial_edit", SHAFT, gesture()), "lease_conflict")
        assert host.editor.applied == []

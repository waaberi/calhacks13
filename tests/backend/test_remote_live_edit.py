"""Client viewport edits (two-way editing): local changes become requests. No bpy."""
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "live_edit", ROOT / "blender_addon/spatial_modeling/remote_client/live_edit.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LiveEdits, changes = MODULE.LiveEdits, MODULE.changes

IDENTITY = {"location": [0, 0, 0], "rotation": [1, 0, 0, 0], "scale": [1, 1, 1]}


def record(**transform):
    return {"name": "Cube", "generation": 1, "transform": {**IDENTITY, **transform}}


def local(**transform):
    return {**IDENTITY, **transform}


def test_unchanged_sends_nothing():
    noise = local(location=[1e-6, 0, 0], rotation=[1, 1e-5, 0, 0], scale=[1.00001, 1, 1])
    assert changes(IDENTITY, noise, "Cube") == []


def test_move_rotate_scale_in_order_with_absolute_args():
    half = math.sqrt(.5)
    ops = changes(IDENTITY, local(location=[.1, 0, .2], rotation=[-half, 0, 0, -half],
                                  scale=[2, 2, 2]), "Cube")
    assert [op for op, _, _ in ops] == ["object.move", "object.rotate", "object.scale"]
    assert ops[0][2] == {"to": [.1, 0, .2]}
    assert ops[1][2]["to"] == pytest.approx([half, 0, 0, half])  # unit, w >= 0
    assert ops[2][2] == {"to": [2, 2, 2]}
    assert ops[0][1] == "Move Cube to (100, 0, 200) mm"


def test_negated_quaternion_is_the_same_rotation():
    assert changes(IDENTITY, local(rotation=[-1, 0, 0, 0]), "Cube") == []


def test_out_of_range_is_refused():
    with pytest.raises(ValueError):
        changes(IDENTITY, local(scale=[0.0001, 1, 1]), "Cube")
    with pytest.raises(ValueError):
        changes(IDENTITY, local(location=[2000, 0, 0]), "Cube")


def test_next_request_holds_and_sends_one_at_a_time():
    live = LiveEdits()
    records = {"a": record(), "b": record()}
    moved = {"a": local(location=[1, 0, 0]), "b": local(location=[0, 1, 0])}
    oid, op, _, args = live.next_request(records, moved, set())
    assert (oid, op, args) == ("a", "object.move", {"to": [1, 0, 0]})
    assert live.held == {"a", "b"}
    live.sent["r1"] = "a"
    oid, *_ = live.next_request(records, moved, set())
    assert oid == "b"  # a is waiting for its answer


def test_applied_waits_for_scene_update_then_releases():
    live = LiveEdits()
    records = {"a": record()}
    moved = {"a": local(location=[1, 0, 0])}
    live.next_request(records, moved, set())
    live.sent["r1"] = "a"
    reqs = {"r1": SimpleNamespace(state="applied", revision=5, code="")}
    live.settle(reqs, 4)
    assert live.busy("a") and live.next_request(records, moved, set()) is None
    live.settle(reqs, 5)  # the scene.update arrived
    records = {"a": record(location=[1, 0, 0])}
    assert live.next_request(records, moved, set()) is None
    assert live.held == set()


def test_rejected_reverts_to_host():
    live = LiveEdits()
    records = {"a": record()}
    live.next_request(records, {"a": local(location=[1, 0, 0])}, set())
    live.sent["r1"] = "a"
    live.settle({"r1": SimpleNamespace(state="rejected", revision=3, code="stale_revision")}, 3)
    assert live.revert == {"a"} and "a" not in live.held
    assert "stale_revision" in live.error


def test_local_delete_becomes_object_delete():
    live = LiveEdits()
    chosen = live.next_request({"a": record()}, {}, {"a"})
    assert chosen == ("a", "object.delete", "Delete Cube", {})
    assert live.held == {"a"}
    # The host already removed it: nothing to send.
    assert live.next_request({}, {}, {"a"}) is None
    assert live.held == set()


def test_bad_local_value_reverts_with_reason():
    live = LiveEdits()
    assert live.next_request({"a": record()}, {"a": local(scale=[5000, 1, 1])}, set()) is None
    assert live.revert == {"a"} and "scale" in live.error


def test_cancelled_drag_keeps_its_original_baseline_across_host_updates():
    live = LiveEdits()
    records = {"a": record(), "b": record()}
    live.begin_drag(records, {"a", "b"})
    records["a"]["transform"]["location"] = [0, .7, 0]
    live.begin_drag(records, {"a", "b"})
    # Esc on A restores its pre-drag transform, while a committed drag on B differs.
    assert live.finish_drag({"a": local(), "b": local(location=[.2, 0, 0])}) == {"a"}
    assert live.drag_baselines == {}


def test_new_document_reset_discards_pending_drag_baselines():
    live = LiveEdits()
    live.begin_drag({"a": record()}, {"a"})
    live.reset()
    assert live.finish_drag({"a": local()}) == set()


def test_successful_delete_releases_hold_when_mirror_already_forgot_object():
    live = LiveEdits()
    live.next_request({"a": record()}, {}, {"a"})
    live.sent["r1"] = "a"
    live.settle({"r1": SimpleNamespace(state="applied", revision=2, code="")}, 2)
    assert live.next_request({}, {}, set()) is None
    assert not live.held and not live.sent and not live.wait_revision

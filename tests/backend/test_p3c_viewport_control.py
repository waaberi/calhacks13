"""Validate the bounded external stimulus grammar without importing Blender."""

import json

import pytest
from p3c_viewport_stimulus import control_request, drawable_bounds


@pytest.mark.parametrize("value", [
    {}, [], {"seq": True, "action": "stop"}, {"seq": 0, "action": "stop"},
    {"seq": 2**31, "action": "stop"}, {"seq": 1, "action": "quit"},
    {"seq": 1, "action": ["stop"]}, {"seq": 1, "action": "stop", "target": "a"},
    {"seq": 1, "action": "frame", "target": "not-a-sketch-uuid"},
    *[{"seq": 1, "action": "orbit", "duration_s": v}
      for v in (None, True, 0, 3, 5, 61, float("nan"), float("inf"))],
])
def test_reject_unbounded_or_ambiguous_controls(value):
    with pytest.raises((TypeError, ValueError)):
        control_request(json.dumps(value), 0)


def test_sequence_replay_does_not_restart_motion():
    raw = '{"seq": 4, "action": "orbit", "duration_s": 48}'
    assert control_request(raw, 3)["duration_s"] == 48
    assert control_request(raw, 4) is None
    assert control_request(raw, 5) is None


def test_explicit_real_sketch_target_and_size_limit():
    value = {"seq": 1, "action": "frame", "target": "420d772974c747ebb91283b7ff8d22a3"}
    assert control_request(json.dumps(value), 0) == value
    with pytest.raises(ValueError, match="4096"):
        control_request(" " * 4097, 0)


def test_fixed_origin_alone_does_not_complete_a_frame():
    assert drawable_bounds({"entities": [{"id": "origin", "kind": "point", "at": [0, 0]}]}) is None


def test_unconnected_origin_does_not_skew_drawable_bounds():
    entities = [{"id": pid, "kind": "point", "at": at}
                for pid, at in (("origin", [0, 0]), ("a", [.1, .2]), ("b", [.2, .3]))]
    entities.append({"id": "line", "kind": "line", "points": ["a", "b"]})
    assert drawable_bounds({"entities": entities}) == ([.1, .2], [.2, .3])


def test_circle_extents_include_real_radius():
    record = {"entities": [{"id": "a", "kind": "point", "at": [.03, .04]},
                           {"id": "circle", "kind": "circle", "center": "a", "radius": .01}]}
    lo, hi = drawable_bounds(record)
    assert lo == pytest.approx([.02, .03])
    assert hi == pytest.approx([.04, .05])

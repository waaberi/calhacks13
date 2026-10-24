"""Validate the bounded external stimulus grammar without importing Blender."""

import json

import pytest
from p3c_viewport_stimulus import control_request


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

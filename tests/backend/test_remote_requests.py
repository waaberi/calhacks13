"""Client edit requests (P5-M1-2/3): building, outcomes and reconnect recovery. No bpy."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "p5_requests", ROOT / "blender_addon/spatial_modeling/remote_client/requests.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
RequestTracker, EditBlocked = MODULE.RequestTracker, MODULE.EditBlocked


def example(name):
    return json.loads((ROOT / f"contracts/examples/{name}.json").read_text())["payload"]


@pytest.fixture
def welcome():
    return example("welcome")


@pytest.fixture
def scene():
    return example("scene.snapshot")


def tracker_for(welcome):
    tracker = RequestTracker()
    assert tracker.welcomed(welcome) == []
    return tracker


def move(tracker, scene, mm=10):
    obj = scene["objects"][0]
    return tracker.build("object.move", f"Move {obj['name']}", scene["document"],
                         {"by": [mm / 1000, 0, 0]}, obj)


def test_command_uses_welcome_scene_and_target(welcome, scene):
    tracker = tracker_for(welcome)
    msg = move(tracker, scene)
    p = msg["payload"]
    assert msg["type"] == "command" and msg["id"] == next(iter(tracker.requests))
    assert (p["session_id"], p["host_epoch"], p["actor_id"]) == (
        welcome["session_id"], welcome["host_epoch"], welcome["actor_id"])
    assert (p["document_id"], p["open_epoch"], p["base_revision"]) == (
        scene["document"]["id"], scene["document"]["open_epoch"], scene["document"]["revision"])
    obj = scene["objects"][0]
    assert p["target"] == {"id": obj["id"], "generation": obj["generation"]}
    assert p["source"] == "ui" and p["args"] == {"by": [0.01, 0, 0]}


def test_commands_validate_against_contract_schema(welcome, scene):
    pytest.importorskip("jsonschema")
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    schemas = [json.loads(p.read_text()) for p in (ROOT / "contracts/schemas").glob("*.schema.json")]
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)
    command = next(s for s in schemas if s["$id"].endswith("command.schema.json"))
    validator = Draft202012Validator(command, registry=registry)
    obj = scene["objects"][0]
    for op, args, target in [
        ("object.move", {"by": [0.01, 0, 0]}, obj),
        ("object.rotate", {"by": {"axis": "Z", "angle": 1.5707963}}, obj),
        ("object.scale", {"by": [1, 1, 1.5]}, obj),
        ("object.delete", {}, obj),
        ("object.add", {"primitive": "cube", "location": [0, 0, 0.05],
                        "dimensions": [0.1, 0.1, 0.1]}, None),
        ("history.undo", {}, None),
        ("history.redo", {}, None),
    ]:
        tracker = tracker_for(welcome)
        validator.validate(tracker.build(op, op, scene["document"], args, target))


def test_one_request_in_flight(welcome, scene):
    tracker = tracker_for(welcome)
    assert tracker.blocked(True, True, True) is None
    msg = move(tracker, scene)
    assert "Waiting for the host" in tracker.blocked(True, True, True)
    tracker.on_result({"request_id": msg["id"], "outcome": "applied", "revision": 43})
    assert tracker.blocked(True, True, True) is None
    request = tracker.requests[msg["id"]]
    assert (request.state, request.revision) == ("applied", 43)


@pytest.mark.parametrize("current,can_edit,healthy,reason", [
    (False, True, True, "fresh host scene"),
    (True, False, True, "doesn't allow Client edits"),
    (True, True, False, "Not connected"),
])
def test_blocked_reasons(welcome, current, can_edit, healthy, reason):
    assert reason in tracker_for(welcome).blocked(current, can_edit, healthy)


def test_rejected_keeps_only_the_error_code(welcome, scene):
    tracker = tracker_for(welcome)
    msg = move(tracker, scene)
    tracker.on_result({"request_id": msg["id"], "outcome": "rejected", "revision": 42,
                       "error": {"code": "stale_revision", "message": "<host text>"}})
    label, text, icon = tracker.lines()[0]
    assert "rejected (stale_revision)" == text and icon == "CANCEL"
    assert "<host text>" not in label + text
    assert tracker.blocked(True, True, True) is None


@pytest.mark.parametrize("code,state", [
    ("invalid_message", "rejected"), ("busy", "rejected"), ("permission_denied", "rejected"),
    ("internal_error", "unknown"), ("<script>", "rejected"),
])
def test_error_reply_to_a_command(welcome, scene, code, state):
    tracker = tracker_for(welcome)
    msg = move(tracker, scene)
    tracker.on_reply_error(msg["id"], code)
    assert tracker.requests[msg["id"]].state == state
    assert "<" not in tracker.lines()[0][1]


def test_unknown_blocks_until_user_checked(welcome, scene):
    tracker = tracker_for(welcome)
    msg = move(tracker, scene)
    tracker.on_result({"request_id": msg["id"], "outcome": "unknown"})
    assert "unknown" in tracker.blocked(True, True, True)
    with pytest.raises(EditBlocked):
        tracker.welcome = None
        move(tracker, scene)
    tracker.welcome = welcome
    tracker.acknowledge_unknown()
    assert tracker.blocked(True, True, True) is None


def test_lost_result_is_asked_never_resent(welcome, scene):
    tracker = tracker_for(welcome)
    first = move(tracker, scene)
    tracker.disconnected()
    assert "Not connected" in tracker.blocked(True, True, True)
    queries = tracker.welcomed({**welcome, "actor_id": "f" * 32})
    assert queries == [{"host_epoch": welcome["host_epoch"], "request_ids": [first["id"]]}]
    assert "Asking the host" in tracker.blocked(True, True, True)
    tracker.query_sent("q" * 32, queries[0])
    tracker.on_receipts("q" * 32, {"receipts": [{"request_id": first["id"], "outcome": "applied",
                                                 "revision": 43}], "missing": [], "unknown": []})
    assert tracker.requests[first["id"]].state == "applied"
    assert tracker.blocked(True, True, True) is None


@pytest.mark.parametrize("answer,state,blocks", [
    ({"receipts": [], "missing": ["ID"], "unknown": []}, "missing", False),
    ({"receipts": [], "missing": [], "unknown": ["ID"]}, "unknown", True),
    ({"receipts": [], "missing": [], "unknown": []}, "unknown", True),  # not answered at all
])
def test_receipt_answers(welcome, scene, answer, state, blocks):
    tracker = tracker_for(welcome)
    msg = move(tracker, scene)
    tracker.disconnected()
    payload = tracker.welcomed(welcome)[0]
    tracker.query_sent("q" * 32, payload)
    answer = {k: [msg["id"] if x == "ID" else x for x in v] for k, v in answer.items()}
    tracker.on_receipts("q" * 32, answer)
    assert tracker.requests[msg["id"]].state == state
    assert (tracker.blocked(True, True, True) is not None) == blocks


def test_still_running_on_host_waits_for_its_result(welcome, scene):
    tracker = tracker_for(welcome)
    msg = move(tracker, scene)
    tracker.disconnected()
    tracker.query_sent("q" * 32, tracker.welcomed(welcome)[0])
    tracker.on_receipts("q" * 32, {"receipts": [{"request_id": msg["id"], "outcome": "pending"}],
                                   "missing": [], "unknown": []})
    assert tracker.requests[msg["id"]].state == "pending"
    tracker.on_result({"request_id": msg["id"], "outcome": "applied", "revision": 43})
    assert tracker.requests[msg["id"]].state == "applied"


def test_failed_query_leaves_outcome_unknown(welcome, scene):
    tracker = tracker_for(welcome)
    msg = move(tracker, scene)
    tracker.disconnected()
    tracker.query_sent("q" * 32, tracker.welcomed(welcome)[0])
    tracker.on_reply_error("q" * 32, "invalid_message")
    assert tracker.requests[msg["id"]].state == "unknown"


def test_queries_split_by_epoch_and_limit(welcome, scene):
    tracker = tracker_for(welcome)
    ids = []
    for i in range(150):
        msg = move(tracker, scene)
        ids.append(msg["id"])
        tracker.requests[msg["id"]].state = "asking"
        if i == 120:
            tracker.welcome = {**welcome, "host_epoch": "e" * 32}
    queries = tracker.welcomed(welcome)
    assert [len(q["request_ids"]) for q in queries] == [100, 21, 29]
    assert {q["host_epoch"] for q in queries} == {welcome["host_epoch"], "e" * 32}


def test_new_document_drops_old_requests(welcome, scene):
    tracker = tracker_for(welcome)
    msg = move(tracker, scene)
    tracker.disconnected()
    other = {**welcome, "document": {**welcome["document"], "open_epoch": "a" * 32}}
    assert tracker.welcomed(other) == []
    assert tracker.requests[msg["id"]].state == "dropped"
    with pytest.raises(EditBlocked, match="another document"):
        move(tracker, scene)


def test_results_for_other_requests_are_ignored(welcome, scene):
    tracker = tracker_for(welcome)
    move(tracker, scene)
    tracker.on_result({"request_id": "0" * 32, "outcome": "applied"})
    tracker.on_reply_error("0" * 32, "busy")
    tracker.on_receipts("0" * 32, {"receipts": [], "missing": ["0" * 32], "unknown": []})
    assert [r.state for r in tracker.requests.values()] == ["pending"]


def test_history_is_trimmed_but_open_requests_are_kept(welcome, scene):
    tracker = tracker_for(welcome)
    for _ in range(80):
        msg = move(tracker, scene)
        tracker.on_result({"request_id": msg["id"], "outcome": "applied"})
    assert len(tracker.requests) <= MODULE.MAX_KEPT + 1
    open_one = move(tracker, scene)
    assert open_one["id"] in tracker.requests

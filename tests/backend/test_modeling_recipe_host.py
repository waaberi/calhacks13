"""Recipe resolve/admission on real protocol sockets, without native edits or AI calls."""
import copy
import sys
import types

import modeling_recipe as recipe
import protocol
import pytest
from commands import Refused
from test_commands import DOCUMENT, PLATE, assert_rejected, assert_valid, two_peers, valid
from test_modeling_recipe import catalog, step
from test_voice_composer import AdmittingVoiceEditor
from test_voice_ops import attach


def captured(sync):
    return {"document_id": DOCUMENT["id"], "open_epoch": DOCUMENT["open_epoch"],
            "revision": sync.revision, "mode": "EDIT_MESH", "native_tool": "builtin.inset",
            "topology_token": "f" * 64, "options": {},
            "objects": [{"id": oid, "name": obj["name"], "generation": obj["generation"]}
                        for oid, obj in sync.objects.items()]}


@pytest.fixture(autouse=True)
def fake_native_context(monkeypatch):
    monkeypatch.setitem(sys.modules, "tool_catalog", types.SimpleNamespace(catalog=catalog, validate=lambda tool, params, component: params))
    monkeypatch.setattr(recipe, "capture_context", captured)


def request(client, editor, steps=None, draft=None, **context_changes):
    context = captured(editor)
    context["selection"] = {"objects": [{"id": PLATE, "generation": editor.generation(PLATE)}], "component": "face", "indices": [1, 2]}
    context.update(context_changes)
    payload = {"text": "inset selected faces then extrude the inset", "confidence": 1,
               "composition": True, "recipe": draft or {"decision": "propose", "steps": steps or [step()]}, "context": context}
    msg = protocol.message("voice.resolve", payload)
    assert valid(msg)
    _, reply = client.ask(msg)
    assert_valid(reply)
    return reply["payload"]


def test_review_recipe_round_trip_is_read_only_and_retains_every_step():
    with two_peers(editor=AdmittingVoiceEditor()) as (host, client, _other):
        attach(host)
        result = request(client, host.editor, [step(), step("mesh.extrude", {"translation_m": [0, 0, .005]},
                         {"step": "first", "output": "inner_faces"}, "second")])
        assert result["decision"] == "run" and result["expires_in"] == 120
        assert result["candidates"][0]["requires_confirmation"] is True
        assert [s["tool"] for s in result["recipe_plan"]["steps"]] == ["mesh.inset", "mesh.extrude"]
        assert host.editor.applied == [] and host.editor.revision == 0


@pytest.mark.parametrize("draft,decision", [
    ({"decision": "propose", "steps": [step(), step("arbitrary.python", {}, sid="tail")]}, "reject"),
    ({"decision": "propose", "steps": [step(params={})]}, "clarify"),
    ({"decision": "propose", "steps": [step()], "unhandled_intent": ["teleport"]}, "reject"),
    ({"decision": "clarify", "steps": [], "missing": ["distance"], "reason": "How far?"}, "clarify"),
])
def test_whole_draft_never_admits_prefix_when_unsupported_or_missing(draft, decision):
    with two_peers(editor=AdmittingVoiceEditor()) as (host, client, _other):
        attach(host)
        result = request(client, host.editor, draft=draft)
        assert result["decision"] == decision and result["candidates"] == []
        receipt = client.run("voice.run", PLATE, {"resolution": result["resolution"], "choice": 1}, source="voice")
        assert_rejected(receipt, "not_found")
        assert host.editor.applied == []


def test_stored_review_is_connection_owned_and_bound_to_native_revision():
    with two_peers(editor=AdmittingVoiceEditor()) as (host, client, other):
        attach(host)
        result = request(client, host.editor)
        args = {"resolution": result["resolution"], "choice": 1}
        assert_rejected(other.run("voice.run", PLATE, args, source="voice"), "permission_denied")
        host.editor.objects[PLATE]["generation"] += 1
        assert_rejected(client.run("voice.run", PLATE, args, source="voice"), "stale_revision")
        assert host.editor.applied == []


def test_review_expires_and_successful_take_is_single_use():
    now = [1]
    with two_peers(editor=AdmittingVoiceEditor(clock=lambda: now[0])) as (host, client, _other):
        attach(host)
        result = request(client, host.editor)
        rid = result["resolution"]
        now[0] = 122
        assert_rejected(client.run("voice.run", PLATE, {"resolution": rid, "choice": 1}, source="voice"), "not_found")
        result = request(client, host.editor)
        rid = result["resolution"]
        candidate, target = host.editor.voice.take(rid, 1)
        assert candidate["intent"] == "__recipe" and target == PLATE
        with pytest.raises(Refused) as caught:
            host.editor.voice.take(rid, 1)
        assert caught.value.code == "not_found"


@pytest.mark.parametrize("component,indices", [([], [1]), ("face", [True]), ("face", [-1]), ("face", [1, 1])])
def test_wire_invalid_components_return_invalid_message(component, indices):
    import voice_ops
    editor = AdmittingVoiceEditor()
    context = captured(editor)
    context["selection"] = {"objects": [], "component": "face", "indices": [1]}
    draft = {"decision": "propose", "steps": [step(selection={"component": component, "indices": indices})]}
    msg = protocol.message("voice.resolve", {"text": "inset", "confidence": 1, "composition": True,
                                            "recipe": copy.deepcopy(draft), "context": context})
    assert voice_ops.resolve_problem(msg)

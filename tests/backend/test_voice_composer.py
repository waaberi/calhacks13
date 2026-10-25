import math

import pytest
import voice_composer as vc
import voice_ops
from test_commands import assert_rejected, two_peers
from test_leases import granted
from test_voice_ops import CUE_CARD, PLATE, SHAFT, VoiceEditor, attach, voice_hosting
from test_voice_ops import ask as legacy_ask


def ask(peer, text, confidence=0.9, target=None):
    import protocol
    from test_commands import assert_valid

    payload = {"text": text, "confidence": confidence, "composition": True}
    if target is not None:
        payload["target"] = target
    msg = protocol.message("voice.resolve", payload)
    _, reply = peer.ask(msg)
    assert_valid(reply)
    assert reply["type"] == "voice.candidates"
    return reply["payload"]


OBJECTS = [
    {"id": PLATE, "name": "Base plate", "generation": 0},
    {"id": SHAFT, "name": "Shaft", "generation": 0},
]


def plan(text, target=PLATE):
    return vc.Planner(voice_ops, lambda: 0).resolve(text, target, OBJECTS)


def steps(text, target=PLATE):
    result = plan(text, target)
    assert result["decision"] == "run", result
    return result["candidates"][0]["steps"]


def test_general_chain_new_targets_and_units():
    s = steps(
        "add a cube then move it twenty centimeters along x then rotate it forty five degrees around z then scale it down fifty percent",
        None,
    )
    assert len(s) == 4
    assert all(step.get("target") == "new:0" for step in s[1:])
    assert s[1]["by"] == [0.2, 0, 0]
    assert s[2]["angle"] == math.pi / 4
    assert s[3]["by"] == [0.5] * 3


@pytest.mark.parametrize("text,op,props,post", CUE_CARD)
def test_existing_curated_operations_compose_without_combination_rules(text, op, props, post):
    s = steps(text + " then move it one millimeter along x")
    assert s[0]["candidate"]["op"] == op
    assert s[1]["kind"] == "move"


@pytest.mark.parametrize(
    "text,wanted",
    [
        ("scale it down twenty percent", [0.8] * 3),
        ("scale it up twenty percent", [1.2] * 3),
        ("scale it by negative one along x", [-1, 1, 1]),
        ("scale it by -1 along y", [1, -1, 1]),
        ("scale it along z by two", [1, 1, 2]),
        ("scale it by half", [0.5] * 3),
        ("scale it by negative fifty percent", [-0.5] * 3),
    ],
)
def test_scaling(text, wanted):
    assert steps(text)[0]["by"] == wanted


@pytest.mark.parametrize(
    "text",
    [
        "scale it by zero",
        "scale it down one hundred percent",
        "scale it by one thousand",
        "scale it down twenty",
        "move it twenty degrees along x",
        "rotate it forty five centimeters around x",
        "add cube then teleport it",
        "add cube and teleport it",
        "add cube and sing",
        "shade smooth and teleport it",
        "move it one centimeter along x nonsense",
        "move it twenty centimeters from x axis",
        "delete it then move it one centimeter along x",
        "add cube then undo",
        "add cube then",
        "add cube and cancel",
    ],
)
def test_invalid_plan_never_returns_executable_prefix(text):
    with pytest.raises(vc.InvalidPlan):
        plan(text)


@pytest.mark.parametrize(
    "text,kind",
    [
        ("colour it red", "colour"),
        ("make it lighter", "colour"),
        ("reset its colour", "reset"),
        ("set its width twenty millimeters", "dimension"),
        ("set its height thirty centimeters", "dimension"),
        ("duplicate it ten centimeters along x", "duplicate"),
        ("reset its rotation", "reset"),
        ("reset its scale", "reset"),
    ],
)
def test_five_additions(text, kind):
    assert steps(text)[0]["kind"] == kind


def test_explicit_names_and_duplicate_it_binding():
    s = steps("select Shaft then duplicate it ten centimeters along y then colour it blue")
    assert s[1]["target"] == SHAFT and s[1]["by"] == [0, 0.1, 0]
    assert s[2]["target"] == "new:1"


def test_compact_create_location():
    s = steps("add cube at x twenty centimeters", None)
    assert s[0]["kind"] == "add_placed" and s[0]["absolute"] and s[0]["distance"] == 0.2


def test_transform_apply_rotation_and_scale_is_one_registry_step():
    single = steps("apply rotation and scale")
    assert len(single) == 1 and single[0]["candidate"]["intent"] == "apply_transforms"
    s = steps("apply rotation and scale then shade smooth")
    assert len(s) == 2 and s[0]["candidate"]["intent"] == "apply_transforms"


@pytest.mark.parametrize("text", ["add cube and teleport it", "add cube and sing", "shade smooth and teleport it"])
def test_unknown_and_tail_is_detected_and_never_offers_a_prefix_over_socket(text):
    assert vc.handles(text) and vc.has_chain_connector(text)
    assert "and" in voice_ops.GRAMMAR
    with voice_hosting() as host, host.vr() as client:
        attach(host)
        for resolver in (ask, legacy_ask):
            result = resolver(client, text)
            assert result["decision"] == "reject" and result["candidates"] == []
            receipt = client.run("voice.run", None, {"resolution": result["resolution"], "choice": 1}, source="voice")
            assert_rejected(receipt, "not_found")
            assert host.editor.revision == 0


def test_legacy_native_semantic_and_phrase_still_resolves():
    assert not vc.has_chain_connector("apply rotation and scale")
    with voice_hosting() as host, host.vr() as client:
        attach(host)
        result = legacy_ask(client, "apply rotation and scale", target={"id": PLATE, "generation": 0})
        assert result["decision"] == "run"
        assert result["candidates"][0]["operator"] == "object.transform_apply"


def test_missing_fields_retain_whole_plan_and_selection_continues():
    p = vc.Planner(voice_ops, lambda: 0)
    r = p.resolve(
        "move it ten centimeters then colour it red", None, OBJECTS, owner="a", document="d"
    )
    assert r["missing"] == "target"
    r = p.resolve("selected", PLATE, OBJECTS, r["resolution"], "a", "d")
    assert r["missing"] == "axis"
    r = p.resolve("x", PLATE, OBJECTS, r["resolution"], "a", "d")
    assert r["decision"] == "run" and len(r["candidates"][0]["steps"]) == 2


def test_colour_clarification():
    p = vc.Planner(voice_ops, lambda: 0)
    r = p.resolve("colour it", PLATE, OBJECTS)
    assert r["missing"] == "colour"
    r = p.resolve("purple", PLATE, OBJECTS, r["resolution"])
    assert r["candidates"][0]["steps"][0]["colour"] == "purple"


def test_pending_owner_document_expiry_and_target_generation():
    now = [0]
    p = vc.Planner(voice_ops, lambda: now[0])
    for owner, doc, objects in [
        ("other", "doc", OBJECTS),
        ("me", "other", OBJECTS),
        ("me", "doc", [dict(o, generation=1) for o in OBJECTS]),
    ]:
        r = p.resolve(
            "move it ten centimeters then shade smooth", PLATE, OBJECTS, owner="me", document="doc"
        )
        with pytest.raises(vc.InvalidPlan):
            p.resolve("x", PLATE, objects, r["resolution"], owner, doc)
    r = p.resolve("colour it", PLATE, OBJECTS)
    now[0] = 31
    with pytest.raises(vc.InvalidPlan):
        p.resolve("red", PLATE, OBJECTS, r["resolution"])


def test_delete_plan_requires_confirmation_and_tracks_each_existing_target():
    r = plan("move Shaft one centimeter along x then delete Base plate")
    c = r["candidates"][0]
    assert c["confirm"] and c["generations"] == {PLATE: 0, SHAFT: 0}


def test_new_wire_capability_and_ready_plan_contract():
    with voice_hosting() as host, host.vr() as client:
        attach(host)
        r = ask(
            client,
            "move it one centimeter along x then shade smooth",
            target={"id": PLATE, "generation": 0},
        )
        assert r["decision"] == "run"
        c = r["candidates"][0]
        assert c["operator"] == "voice.sequence" and c["target_id"] == PLATE


def test_missing_wire_contract_and_unsupported_tail_rejects():
    with voice_hosting() as host, host.vr() as client:
        attach(host)
        r = ask(
            client,
            "move it ten centimeters then shade smooth",
            target={"id": PLATE, "generation": 0},
        )
        assert r["decision"] == "clarify"
        r = ask(client, "add cube then teleport it")
        assert r["decision"] == "reject"


class AdmittingVoiceEditor(VoiceEditor):
    def command_targets(self, op, args, conn):
        return self.voice.command_targets(args, conn) if op == "voice.run" else {}


def test_chain_checks_the_lease_of_every_target_not_only_primary():
    with two_peers(editor=AdmittingVoiceEditor()) as (host, client, other):
        attach(host)
        r = ask(
            client,
            "move Base plate one millimeter along x then colour Shaft red",
            target={"id": PLATE, "generation": 0},
        )
        granted(other, "shared", [SHAFT])
        client.expect("session.update")
        receipt = client.run(
            "voice.run", PLATE, {"resolution": r["resolution"], "choice": 1}, source="voice"
        )
        assert_rejected(receipt, "lease_conflict")
        assert host.editor.applied == []


def test_other_target_generation_is_checked_even_with_current_primary_generation():
    with two_peers(editor=AdmittingVoiceEditor()) as (host, client, _other):
        attach(host)
        r = ask(
            client,
            "move Base plate one millimeter along x then colour Shaft red",
            target={"id": PLATE, "generation": 0},
        )
        host.editor.objects[SHAFT]["generation"] = 1
        receipt = client.run(
            "voice.run", PLATE, {"resolution": r["resolution"], "choice": 1}, source="voice"
        )
        assert_rejected(receipt, "stale_revision")
        assert host.editor.applied == []


def test_ready_plan_cannot_be_executed_by_another_connection():
    with two_peers(editor=AdmittingVoiceEditor()) as (host, client, other):
        attach(host)
        r = ask(client, "colour it red", target={"id": PLATE, "generation": 0})
        receipt = other.run(
            "voice.run", PLATE, {"resolution": r["resolution"], "choice": 1}, source="voice"
        )
        assert_rejected(receipt, "permission_denied")
        assert host.editor.applied == []


def test_parameter_words_do_not_override_an_explicit_it_target():
    objects = OBJECTS + [
        {"id": "c" * 32, "name": "Red", "generation": 0},
        {"id": "d" * 32, "name": "Two", "generation": 0},
        {"id": "e" * 32, "name": "X", "generation": 0},
    ]
    p = vc.Planner(voice_ops, lambda: 0)
    r = p.resolve(
        "colour it red then scale it by two then move it one centimeter along x", PLATE, objects
    )
    assert r["decision"] == "run"
    assert all(step.get("target") == PLATE for step in r["candidates"][0]["steps"])


def test_signed_amounts_and_signed_axes_preserve_direction_semantics():
    assert steps("move it negative ten centimeters along negative x")[0]["by"] == [0.1, 0, 0]
    assert steps("rotate it forty five degrees around negative x")[0]["angle"] == -math.pi / 4
    assert steps("scale it along negative x by two")[0]["by"] == [-2, 1, 1]


def test_old_client_does_not_receive_new_composition_decisions():
    with voice_hosting() as host, host.vr() as client:
        attach(host)
        r = legacy_ask(client, "colour it red", target={"id": PLATE, "generation": 0})
        assert r["decision"] == "reject"


def test_later_named_target_change_during_earlier_clarification_cancels_whole_plan():
    p = vc.Planner(voice_ops, lambda: 0)
    r = p.resolve("move it ten centimeters then colour Shaft red", PLATE, OBJECTS)
    assert r["missing"] == "axis"
    changed = [dict(o, generation=1) if o["id"] == SHAFT else o for o in OBJECTS]
    with pytest.raises(vc.InvalidPlan):
        p.resolve("x", PLATE, changed, r["resolution"])


def test_leading_decimal_scale_is_never_misread_as_five_times():
    assert steps("scale it by -.5 along x")[0]["by"] == [-0.5, 1, 1]
    assert steps("scale it by .5 along x")[0]["by"] == [0.5, 1, 1]


def test_clarification_continues_over_real_socket_with_capability_and_same_owner():
    import protocol
    from test_commands import assert_valid, valid

    with voice_hosting() as host, host.vr() as client:
        attach(host)
        r = ask(
            client,
            "move it ten centimeters then colour it red",
            target={"id": PLATE, "generation": 0},
        )
        assert r["decision"] == "clarify" and r["missing"] == "axis"
        payload = {
            "text": "x",
            "confidence": 1,
            "target": {"id": PLATE, "generation": 0},
            "continuation": r["resolution"],
            "composition": True,
        }
        msg = protocol.message("voice.resolve", payload)
        assert valid(msg)
        _, reply = client.ask(msg)
        assert_valid(reply)
        assert reply["payload"]["decision"] == "run"
        assert (
            len(host.editor.voice.resolutions[reply["payload"]["resolution"]][1][0]["steps"]) == 2
        )
        del payload["composition"]
        invalid = protocol.message("voice.resolve", payload)
        assert not valid(invalid) and voice_ops.resolve_problem(invalid)

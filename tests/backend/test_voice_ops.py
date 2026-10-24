"""Voice in the host (voice_ops.py) without Blender: the resolver, the grammar, and the
voice.resolve -> voice.candidates -> voice.run round trip through commands.py over real sockets.

The executor's Blender half (operators, Undo, the triangle budget) is checked in GUI Blender
by voice_blender_check.py. Every message the host sends is validated against contracts/schemas.
"""

import json

import commands
import protocol
import pytest
import voice_ops
from commands import Applied, Refused
from test_commands import (
    PLATE,
    SHAFT,
    FakeEditor,
    assert_rejected,
    assert_valid,
    hosting,
    two_peers,
    valid,
)
from test_contracts import CONTRACTS

pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")

MESH = {"mode": "OBJECT", "active_type": "MESH"}


def resolve(text, confidence=1.0, context=MESH):
    return voice_ops.resolve(text, confidence, context)


# The resolver

# The demo cue card (research plan, section 3) and what each runs, with its values.
CUE_CARD = [
    ("add a monkey", "mesh.primitive_monkey_add", {}, {}),
    ("shade smooth", "object.shade_smooth", {}, {}),
    ("subdivide level two", "object.modifier_add", {"type": "SUBSURF"},
     {"levels": 2, "render_levels": 2}),
    ("add a mirror modifier", "object.modifier_add", {"type": "MIRROR"},
     {"use_axis": [True, False, False]}),
    ("make it thicker", "object.modifier_add", {"type": "SOLIDIFY"}, {}),
    ("bevel the edges", "object.modifier_add", {"type": "BEVEL"}, {}),
    ("add an array five copies", "object.modifier_add", {"type": "ARRAY"}, {"count": 5}),
    ("add a donut", "mesh.primitive_torus_add", {}, {}),
    ("make five copies along z", "object.modifier_add", {"type": "ARRAY"},
     {"count": 5, "relative_offset_displace": [0.0, 0.0, 1.0]}),
    ("solidify two millimeters", "object.modifier_add", {"type": "SOLIDIFY"},
     {"thickness": 0.002}),
    ("decimate to fifty percent", "object.modifier_add", {"type": "DECIMATE"}, {"ratio": 0.5}),
]


@pytest.mark.parametrize(("text", "op", "props", "post"), CUE_CARD)
def test_cue_card_phrases_run(text, op, props, post):
    r = resolve(text)
    assert r["decision"] == "run", r
    top = r["candidates"][0]
    assert (top["op"], top["props"], top["post"]) == (op, props, post)


@pytest.mark.parametrize("text", [t for t, *_ in CUE_CARD])
def test_cue_card_phrases_are_in_the_grammar(text):
    """Every word is a grammar word, so the recognizer can hear the phrase at all."""
    known = {w for p in voice_ops.GRAMMAR for w in p.split()}
    assert set(voice_ops.words(text)) - {"to"} <= known


def test_a_dropped_add_still_runs():
    assert resolve("a monkey")["decision"] == "run"


@pytest.mark.parametrize("text", ["subdivide level to", "subdivide level too",
                                  "make to copies", "subdivide it twice"])
def test_two_heard_as_to_still_counts(text):
    r = resolve(text)
    assert r["decision"] == "run", r
    post = r["candidates"][0]["post"]
    assert post.get("levels", post.get("count")) == 2


def test_a_low_confidence_may_only_ask():
    r = resolve("add a monkey", confidence=0.46)
    assert r["decision"] == "ask"
    assert r["candidates"][0]["op"] == "mesh.primitive_monkey_add"
    assert resolve("add a monkey", confidence=0.5)["decision"] == "run"


@pytest.mark.parametrize(("text", "key", "value"), [
    ("subdivide level five", "levels", 2),
    ("make fifty copies", "count", 20),
    ("add an array one copy", "count", 2),
    ("bevel with nine segments", "segments", 4),
])
def test_numbers_are_capped(text, key, value):
    r = resolve(text)
    assert r["decision"] in ("run", "ask"), r
    assert r["candidates"][0]["post"][key] == value


def test_a_capped_number_asks_and_says_why():
    r = resolve("subdivision level three")
    assert r["decision"] == "ask"
    assert r["reason"] == "levels capped at 2"
    assert voice_ops.say(r["candidates"][0]) == "Subdivision Surface, level 2"


@pytest.mark.parametrize(("text", "word"), [
    ("join them", "Join"), ("hmm a join them", "Join"), ("duplicate it", "Duplicate"),
    ("make a copy", "Duplicate"), ("hide it", "Hide"), ("show hidden", "Show hidden"),
])
def test_join_duplicate_and_hide_are_refused_with_a_reason(text, word):
    r = resolve(text)
    assert r["decision"] == "reject" and r["candidates"] == []
    assert r["reason"].startswith(word)


@pytest.mark.parametrize("text", ["extrude", "inset faces"])
def test_edit_mode_tools_are_refused(text):
    r = resolve(text)
    assert r["decision"] == "reject"
    assert "needs Edit Mode" in r["reason"]


@pytest.mark.parametrize("text", ["this is our project", "thank you so much", "[unk] [unk]",
                                  "can you hear me", "wait a second"])
def test_chatter_never_runs(text):
    assert resolve(text)["decision"] != "run"


def test_candidates_never_include_what_cant_run():
    unsupported = {i["op"] for i in voice_ops.INTENTS if i["unsupported"] or i["edit_only"]}
    for text in ["make copies", "smooth it", "bevel", "copies", "flip", "light frame",
                 "make a copy along z", "subdivide", "merge"]:
        for c in resolve(text)["candidates"]:
            assert c["op"] not in unsupported, (text, c)


def test_without_a_mesh_target_mesh_operations_only_ask():
    r = resolve("shade smooth", context={"mode": "OBJECT", "active_type": None})
    assert r["decision"] != "run"
    assert resolve("add a monkey", context={"mode": "OBJECT", "active_type": None})[
        "decision"] == "run"


def test_say_reads_the_values():
    said = [voice_ops.say(c) for c in resolve("make five copies along z")["candidates"]]
    assert said[0] == "Array, 5 copies along Z"
    assert voice_ops.say(resolve("mirror on the z axis")["candidates"][0]) == "Mirror on Z"
    assert voice_ops.say(resolve("bevel five millimeters")["candidates"][0]) == \
        "Bevel, 5 millimeters"


def test_resolve_is_fast():
    import time
    texts = [t for t, *_ in CUE_CARD] * 5
    started = time.perf_counter()
    for t in texts:
        resolve(t)
    assert (time.perf_counter() - started) / len(texts) < 0.05  # measured about 4 ms


# The grammar


def test_the_grammar_has_no_join_and_no_to():
    words = {w for p in voice_ops.GRAMMAR for w in p.split()}
    assert "join" not in words and "combine" not in words
    assert "to" not in words
    assert {"two", "level two", "five copies", "cancel", "undo", "add a monkey"} <= set(
        voice_ops.GRAMMAR)


def test_the_grammar_keeps_voicecores_own_words():
    for w in ("move", "rotate", "scale", "delete", "cube", "sphere", "cylinder", "degrees",
              "millimeters", "x", "y", "z", "by", "along"):
        assert w in voice_ops.GRAMMAR


def test_the_grammar_example_is_what_the_host_sends():
    example = json.loads((CONTRACTS / "examples" / "voice.grammar.json").read_text("utf-8"))
    assert example["payload"] == {"version": voice_ops.GRAMMAR_VERSION,
                                  "phrases": voice_ops.GRAMMAR}


@pytest.mark.parametrize("name", ["voice.candidates.json", "voice.candidates.ask.json",
                                  "voice.candidates.reject.json"])
def test_the_candidates_examples_are_what_the_host_answers(name):
    answer = json.loads((CONTRACTS / "examples" / name).read_text("utf-8"))
    question = json.loads((CONTRACTS / "examples" / name.replace("candidates", "resolve"))
                          .read_text("utf-8"))
    p = question["payload"]
    r = resolve(p["text"], p["confidence"])
    assert answer["re"] == question["id"]
    assert answer["payload"]["decision"] == r["decision"]
    assert answer["payload"]["candidates"] == voice_ops.wire_candidates(r["candidates"])


# Over the wire, through commands.py


class FakeObject:
    def __init__(self, name, type_="MESH"):
        self.name, self.type = name, type_


class VoiceEditor(FakeEditor):
    """FakeEditor plus edits.py's voice.run: Voice.choose() decides, then a fake change."""

    def __init__(self, clock=None):
        super().__init__()
        self.mode = "OBJECT"
        self.blender = {PLATE: FakeObject("Base plate"), SHAFT: FakeObject("Shaft")}
        kw = {"clock": clock} if clock else {}
        self.voice = voice_ops.Voice(self, mode=lambda: self.mode, **kw)

    def find_object(self, oid):  # the sync interface Voice uses
        return self.blender.get(oid)

    def _change(self, op, target, args):
        if op != "voice.run":
            return super()._change(op, target, args)
        self.applied.append((op, target, args))
        c, obj = self.voice.choose(self.find_object(target) if target else None, args)
        if obj is None:
            return super()._change("object.add", None, {"primitive": "cube",
                                                         "location": [0, 0, 0]})
        before = dict(self.objects[target])
        return self._commit(f"Voice: {voice_ops.say(c)} on {obj.name}", {target: before})


def voice_hosting(**kw):
    return hosting(editor=VoiceEditor(**kw))


def attach(host):
    host.editor.voice.attach(host.srv)


def ask(peer, text, confidence=0.9, target=None):
    payload = {"text": text, "confidence": confidence}
    if target is not None:
        payload["target"] = target
    msg = protocol.message("voice.resolve", payload)
    _, reply = peer.ask(msg)
    assert_valid(reply)
    assert reply["type"] == "voice.candidates" and reply["re"] == msg["id"], reply
    return reply["payload"]


def voice_run(peer, answer, choice=1, target=None, **kw):
    args = {"resolution": answer["resolution"], "choice": choice}
    return peer.command("voice.run", target, args, source="voice", **kw)


def test_without_voice_the_host_answers_unknown_type():
    with voice_hosting() as host, host.vr() as talia:
        msg = protocol.message("voice.resolve", {"text": "add a monkey", "confidence": 0.9})
        _, reply = talia.ask(msg)
        assert reply["type"] == "error" and reply["payload"]["code"] == "unknown_type"


def test_grammar_on_request():
    with voice_hosting() as host, host.vr() as talia:
        attach(host)
        msg = protocol.message("voice.grammar_query")
        _, reply = talia.ask(msg)
        assert reply["type"] == "voice.grammar" and reply["re"] == msg["id"]
        assert reply["payload"]["phrases"] == voice_ops.GRAMMAR


def test_a_run_goes_through_commands_like_any_command():
    with two_peers(editor=VoiceEditor()) as (host, talia, other):
        attach(host)
        answer = ask(talia, "make five copies along z", target={"id": SHAFT, "generation": 0})
        assert answer["decision"] == "run" and answer["expires_in"] == 30
        assert answer["candidates"][0]["say"] == "Array, 5 copies along Z"
        assert answer["candidates"][0]["needs_target"] is True
        msg = voice_run(talia, answer, target={"id": SHAFT, "generation": 0})
        before, reply = talia.ask(msg)
        assert [m["type"] for m in before] == ["scene.update"]  # the change, then the result
        receipt = reply["payload"]
        assert receipt["outcome"] == "applied" and receipt["source"] == "voice"
        assert receipt["summary"] == "Voice: Array, 5 copies along Z on Shaft"
        assert other.expect("scene.update", "activity")[1]["payload"]["op"] == "voice.run"
        # The same request again gets its stored result; a new request can't run it again.
        assert talia.ask(msg)[1]["payload"] == receipt
        again = talia.ask(voice_run(talia, answer, target={"id": SHAFT, "generation": 1}))[1]
        assert_rejected(again["payload"], "not_found")
        assert [a[0] for a in host.editor.applied].count("voice.run") == 2


def test_an_add_needs_no_target():
    with voice_hosting() as host, host.vr() as talia:
        attach(host)
        answer = ask(talia, "add a monkey")
        assert answer["decision"] == "run"
        assert answer["candidates"][0]["needs_target"] is False
        receipt = talia.run("voice.run", None, {"resolution": answer["resolution"],
                                                "choice": 1})
        assert receipt["outcome"] == "applied" and len(receipt["created"]) == 1


def test_an_ask_runs_the_chosen_candidate():
    with voice_hosting() as host, host.vr() as talia:
        attach(host)
        answer = ask(talia, "smooth it", target={"id": SHAFT, "generation": 0})
        assert answer["decision"] == "ask"
        assert [c["choice"] for c in answer["candidates"]] == [1, 2, 3]
        receipt = talia.run("voice.run", {"id": SHAFT, "generation": 0},
                            {"resolution": answer["resolution"], "choice": 2})
        assert receipt["summary"] == "Voice: Shade smooth on Shaft"


@pytest.mark.parametrize(("choice", "target", "code"), [
    (1, None, "failed"),  # needs an object
    (1, {"id": PLATE, "generation": 0}, "failed"),  # another object than it was offered for
    (3, {"id": SHAFT, "generation": 0}, "not_found"),  # a run offers fewer than 3
])
def test_voice_run_is_refused_when_it_doesnt_fit(choice, target, code):
    with voice_hosting() as host, host.vr() as talia:
        attach(host)
        answer = ask(talia, "make five copies along z", target={"id": SHAFT, "generation": 0})
        receipt = talia.run("voice.run", target, {"resolution": answer["resolution"],
                                                  "choice": choice})
        assert_rejected(receipt, code)
        assert host.editor.revision == 0


def test_a_resolution_expires():
    now = [100.0]
    with voice_hosting(clock=lambda: now[0]) as host, host.vr() as talia:
        attach(host)
        answer = ask(talia, "add a monkey")
        now[0] += voice_ops.EXPIRES_IN + 1
        receipt = talia.run("voice.run", None, {"resolution": answer["resolution"],
                                                "choice": 1})
        assert_rejected(receipt, "not_found")


def test_a_resolution_never_offered_is_not_found():
    with voice_hosting() as host, host.vr() as talia:
        attach(host)
        receipt = talia.run("voice.run", None, {"resolution": "0" * 32, "choice": 1})
        assert_rejected(receipt, "not_found")


def test_voice_run_respects_leases():
    with two_peers(editor=VoiceEditor()) as (host, talia, other):
        attach(host)
        other.ask(protocol.message("lease.acquire", {
            **{k: other.command("history.undo")["payload"][k] for k in commands.REQUEST_FIELDS},
            "mode": "shared", "targets": [SHAFT]}))
        talia.expect("session.update")
        answer = ask(talia, "shade smooth", target={"id": SHAFT, "generation": 0})
        receipt = talia.run("voice.run", {"id": SHAFT, "generation": 0},
                            {"resolution": answer["resolution"], "choice": 1})
        assert_rejected(receipt, "lease_conflict")


def test_a_rejection_has_no_candidates_and_cant_run():
    with voice_hosting() as host, host.vr() as talia:
        attach(host)
        answer = ask(talia, "this is our project")
        assert answer["decision"] == "reject" and answer["candidates"] == []
        assert answer["reason"] == "I don't know that command."
        receipt = talia.run("voice.run", None, {"resolution": answer["resolution"],
                                                "choice": 1})
        assert_rejected(receipt, "not_found")


def test_outside_object_mode_everything_is_rejected():
    with voice_hosting() as host, host.vr() as talia:
        attach(host)
        host.editor.mode = "EDIT_MESH"
        answer = ask(talia, "add a monkey")
        assert answer["decision"] == "reject"
        assert answer["reason"] == "Host Blender is in Edit Mode. Switch it to Object Mode first."


@pytest.mark.parametrize("payload", [
    {"text": "", "confidence": 0.9},
    {"text": "x" * 501, "confidence": 0.9},
    {"text": "add a monkey"},
    {"text": "add a monkey", "confidence": 1.5},
    {"text": "add a monkey", "confidence": True},
    {"text": "add a monkey", "confidence": 0.9, "target": {"id": SHAFT}},
    {"text": "add a monkey", "confidence": 0.9, "op": "object.join"},
])
def test_a_bad_resolve_is_invalid(payload):
    with voice_hosting() as host, host.vr() as talia:
        attach(host)
        msg = protocol.message("voice.resolve", payload)
        _, reply = talia.ask(msg)
        assert reply["type"] == "error" and reply["payload"]["code"] == "invalid_message"
        assert not valid(msg)  # the schema agrees


def test_voice_run_checks_its_args_like_the_schema():
    example = json.loads((CONTRACTS / "examples" / "command.voice.run.json").read_text("utf-8"))
    for args in ({"resolution": "a" * 32, "choice": 1}, {"resolution": "a" * 32, "choice": 3.0},
                 {"resolution": "a" * 32, "choice": 0}, {"resolution": "a" * 32, "choice": 4},
                 {"resolution": "a" * 32, "choice": True}, {"resolution": "A" * 32, "choice": 1},
                 {"resolution": "a" * 32}, {"resolution": "a" * 32, "choice": 1, "x": 1}):
        for with_target in (True, False):
            payload = dict(example["payload"], args=args)
            if not with_target:
                payload.pop("target")
            msg = dict(example, payload=payload)
            assert valid(msg) == (commands.command_problem(msg) is None), payload


def test_the_executor_refuses_the_unsupported_even_if_offered():
    """A candidate can't be refused at resolve time and then run anyway by its choice."""
    voice = voice_ops.Voice(sync=None, mode=lambda: "OBJECT")
    join = {"intent": "join", "op": "object.join", "props": {}, "post": {}, "label": "join",
            "score": 1, "exact": 1, "macro": False, "needs": "MESH", "notes": []}
    assert voice_ops._refusal(join)
    voice._keep("r" * 32, [join], None)
    with pytest.raises(Refused, match="^Join isn't available"):
        voice.choose(FakeObject("Shaft"), {"resolution": "r" * 32, "choice": 1})


def test_applied_and_refused_are_the_commands_ones():
    assert voice_ops.commands.Applied is Applied and voice_ops.commands.Refused is Refused


# The fake host's canned voice answers, for building the Unity side without Blender


def send_and_wait(c, msg, until):
    c.send(msg)
    while not until(reply := c.recv()):
        pass
    return reply


def test_the_fake_host_answers_voice_like_the_contract():
    from test_fakes import command, proxied, schema_errors, welcomed

    with proxied() as (_host, proxy):
        c, welcome = welcomed(proxy.port)
        target = {"id": SHAFT, "generation": 0}

        def send(type_, payload):
            msg = protocol.message(type_, payload)
            return send_and_wait(c, msg, lambda m: m.get("re") == msg["id"])

        def run(target, resolution, choice):
            msg = command(welcome, "voice.run", target, {"resolution": resolution,
                                                         "choice": choice}, source="voice")
            return send_and_wait(c, msg, lambda m: m["type"] == "result")["payload"]

        grammar = send("voice.grammar_query", {})
        assert grammar["payload"]["phrases"] == voice_ops.GRAMMAR
        answer = send("voice.resolve", {"text": "make five copies", "confidence": 0.9,
                                        "target": target})["payload"]
        assert answer["decision"] == "run" and answer["candidates"][0]["needs_target"]
        receipt = run(target, answer["resolution"], 1)
        assert receipt["outcome"] == "applied"
        assert receipt["summary"] == "Voice: Array, 5 copies along Z on Shaft"
        again = run({"id": SHAFT, "generation": receipt["revision"]}, answer["resolution"], 1)
        assert again["error"]["code"] == "not_found"  # single use
        answer = send("voice.resolve", {"text": "smooth it", "confidence": 0.9})["payload"]
        assert answer["decision"] == "ask" and len(answer["candidates"]) == 3
        assert run(None, answer["resolution"], 2)["error"]["code"] == "failed"  # no target
        answer = send("voice.resolve", {"text": "add a monkey", "confidence": 0.9})["payload"]
        assert len(run(None, answer["resolution"], 1)["created"]) == 1
        answer = send("voice.resolve", {"text": "join them", "confidence": 0.9})["payload"]
        assert answer["decision"] == "reject" and answer["candidates"] == []
        bad = send("voice.resolve", {"text": "", "confidence": 0.9})
        assert bad["type"] == "error" and bad["payload"]["code"] == "invalid_message"
        c.close()
        types = {m["type"] for m in proxy.messages()}
        assert {"voice.candidates", "voice.grammar", "scene.update", "result"} <= types
        assert [m for m in proxy.messages(way="down") if schema_errors(m)] == []  # the host's

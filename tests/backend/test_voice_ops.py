"""Voice in the host (voice_ops.py) without Blender: the resolver, the grammar, and the
voice.resolve -> voice.candidates -> voice.run round trip through commands.py over real sockets.

The executor's Blender half (operators, Undo, the triangle budget) is checked in GUI Blender
by voice_blender_check.py. Every message the host sends is validated against contracts/schemas.
"""

import itertools
import json
import math

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


# What the Unity run showed (24 Oct): "subdivide it twice", "make it smooth" and "smooth the
# object" weren't grammar phrases, so Vosk couldn't take them whole and Whisper's text snapped
# to something else; generic smoothing offered Smooth vertices, which shrank a 2 m cube to 0.26 m.

WHOLE_PHRASES = ["subdivide it twice", "subdivide twice", "subdivide it once", "subdivide once",
                 "subdivide it two times", "subdivide two times", "subdivide level two",
                 "make it smooth", "smooth the object", "smooth it", "smooth",
                 "add a mirror modifier", "add a mirror", "add mirror modifier", "mirror on x",
                 "add a monkey", "shade smooth", "make it thicker", "bevel the edges",
                 "smooth the vertices"]


@pytest.mark.parametrize("text", WHOLE_PHRASES)
def test_demo_phrases_are_whole_grammar_phrases(text):
    """The app takes Vosk's answer at once only when it is exactly one grammar phrase."""
    assert text in voice_ops.GRAMMAR


def test_the_grammar_says_twice_as_it_is_said():
    assert voice_ops.spoken_words("subdivide it twice") == ["subdivide", "it", "twice"]
    assert "subdivide it two times" in voice_ops.GRAMMAR  # both are said
    assert voice_ops.words("subdivide it twice")[-2:] == ["two", "times"]  # the resolver's


@pytest.mark.parametrize(("text", "level"), [
    ("subdivide it twice", 2), ("subdivide twice", 2), ("subdivide it two times", 2),
    ("subdivide two times", 2), ("subdivide it once", 1), ("subdivide once", 1),
    ("subdivide it", 1), ("subdivide level two", 2),
])
def test_subdivide_twice_is_level_two(text, level):
    r = resolve(text)
    assert r["decision"] == "run", r
    top = r["candidates"][0]
    assert top["props"] == {"type": "SUBSURF"}
    assert top["post"] == {"levels": level, "render_levels": level}


def test_every_heard_phrase_runs_its_intent():
    for it in voice_ops.INTENTS:
        for text in it["hear"]:
            r = resolve(text)
            assert r["decision"] == "run" and r["candidates"][0]["intent"] == it["id"], (text, r)


@pytest.mark.parametrize("text", ["make it smooth", "smooth the object", "smooth it", "smooth"])
def test_make_it_smooth_runs_shade_smooth(text):
    r = resolve(text)
    assert r["decision"] == "run", r
    assert r["candidates"][0]["op"] == "object.shade_smooth"


@pytest.mark.parametrize("text", ["add a mirror modifier", "add a mirror", "add mirror modifier",
                                  "mirror modifier", "it a mirror modifier"])
def test_mirror_phrasings_run(text):
    """'it a mirror modifier' is what Vosk heard for Piper's 'add a mirror modifier'."""
    r = resolve(text)
    assert r["decision"] == "run", r
    assert r["candidates"][0]["props"] == {"type": "MIRROR"}


@pytest.mark.parametrize("text", ["make it smooth", "smooth it", "smooth the object", "smooth",
                                  "smoothen it", "make it smoother", "smoother the object",
                                  "smooth it out", "make it look smooth", "smooth the edges"])
def test_smooth_vertices_is_never_offered_for_generic_smoothing(text):
    assert all(c["op"] != "mesh.vertices_smooth" for c in resolve(text)["candidates"]), text


@pytest.mark.parametrize("text", ["smooth the vertices", "smooth vertices"])
def test_smooth_vertices_runs_when_named_and_gently(text):
    r = resolve(text)
    assert r["decision"] == "run", r
    top = r["candidates"][0]
    assert top["op"] == "mesh.vertices_smooth"
    assert top["props"]["factor"] <= 0.25 and top["props"]["repeat"] == 1
    assert voice_ops.BY_ID["smooth_vertices"]["keep_size"]


def test_a_mesh_that_shrinks_too_much_is_refused():
    assert voice_ops._shrunk([2.0, 2.0, 2.0], [0.263, 0.263, 0.263]) == "13%"
    assert voice_ops._shrunk([2.0, 2.0, 0.0], [1.5, 1.5, 0.0]) == "75%"  # flat: Z is ignored
    assert voice_ops._shrunk([2.0, 2.0, 2.0], [1.667, 1.667, 1.667]) is None  # a cube, 1 pass
    assert voice_ops._shrunk(None, [1.0, 1.0, 1.0]) is None


# What the second Unity run showed (24 Oct): "add a modifier" and "add a mirror modifier" offered
# Convert to mesh, which applies the whole stack; "hello", "well", "right", "alright" and "come"
# asked at full confidence; a voice add beside the selection was 79 degrees off the user's view.

MENU = ["Array", "Mirror on X", "Bevel"]


@pytest.mark.parametrize("text", ["add a modifier", "add modifier", "a modifier", "modifier",
                                  "the modifier", "add a modifier please", "add another modifier",
                                  "add some modifiers", "give it a modifier", "make a modifier"])
@pytest.mark.parametrize("confidence", [1.0, 0.9, 0.49])
def test_add_a_modifier_asks_array_mirror_or_bevel(text, confidence):
    """The demo's "which one?": always the same three safe choices, in this order."""
    r = resolve(text, confidence)
    assert r["decision"] == "ask" and r["reason"] is None, r
    assert [voice_ops.say(c) for c in r["candidates"]] == MENU
    assert all(c["op"] == "object.modifier_add" for c in r["candidates"])


def test_the_demo_question_is_a_whole_grammar_phrase():
    """So Whisper's "add a modifier," snaps onto it word for word (without it, the app's
    snapper made it "add array modifier" at 0.49). Vosk heard Piper's as "the modifier"."""
    assert "add a modifier" in voice_ops.GRAMMAR
    assert "add a modifier" in voice_ops.MENU_PHRASES


def test_a_modifier_request_offers_only_modifiers():
    r = resolve("add array modifier", 0.49)  # the Unity run's snap of "add a modifier"
    assert r["decision"] == "ask"
    assert [voice_ops.say(c) for c in r["candidates"]] == MENU  # was Array, Mirror, Convert
    for text in ["add a mirror modifier", "bevel modifier", "add a boolean modifier",
                 "decimate modifier", "add a modifire"]:
        assert all(c["op"] == "object.modifier_add" for c in resolve(text, 0.49)["candidates"])


@pytest.mark.parametrize("text", ["add a modifier", "add a mirror modifier", "add array modifier",
                                  "modifier", "mirror modifier", "add a subdivision surface",
                                  "apply scale", "apply all transforms", "make it a mesh",
                                  "add a mirror", "triangulate", "apply rotation and scale"])
@pytest.mark.parametrize("confidence", [1.0, 0.49])
def test_convert_to_mesh_is_never_offered_unasked(text, confidence):
    assert all(c["op"] != "object.convert" for c in resolve(text, confidence)["candidates"]), text


@pytest.mark.parametrize("text", ["convert to mesh", "convert it to a mesh", "apply modifiers",
                                  "apply all modifiers", "apply the modifiers"])
def test_convert_to_mesh_runs_when_asked_for(text):
    r = resolve(text)
    assert r["decision"] == "run", r
    assert r["candidates"][0]["op"] == "object.convert"
    assert "apply all modifiers" in voice_ops.GRAMMAR


@pytest.mark.parametrize("text", ["hello", "well", "right", "alright", "come", "think", "all",
                                  "all right", "hello there", "come on", "oh well", "okay", "um",
                                  "yeah", "hmm", "hello two", "make it", "what time his it",
                                  "[unk] [unk]"])
@pytest.mark.parametrize("confidence", [1.0, 0.49])
def test_fillers_alone_are_rejected_silently(text, confidence):
    """Nothing asked and nothing said: reject with no reason."""
    r = resolve(text, confidence)
    assert (r["decision"], r["reason"], r["candidates"]) == ("reject", None, [])


def test_no_two_grammar_fillers_ask_or_run():
    """Every absorber, alone and with any other: 13,924 pairs (1,087 asked before)."""
    for a, b in itertools.product(voice_ops.ABSORBERS, repeat=2):
        r = resolve(f"{a} {b}")
        assert r["decision"] == "reject", (a, b, r)
    for w in voice_ops.ABSORBERS:
        assert resolve(w)["reason"] in (None, voice_ops.NO_WORDS), w  # "two": a number


def test_no_phrase_is_only_fillers():
    """So the filler rule can't silence an operation."""
    for it in voice_ops.INTENTS:
        for p in it["say"] + it["hear"]:
            _, rest = voice_ops.extract_slots(voice_ops.words(p))
            assert not all(w in voice_ops.FILLERS for w in rest), (it["id"], p)


@pytest.mark.parametrize(("text", "decision"), [
    ("okay add a monkey", "run"), ("right shade smooth", "run"), ("hello add a monkey", "ask"),
    ("well add a monkey", "ask"), ("alright make it thicker", "ask"),
])
def test_fillers_dont_hide_a_command(text, decision):
    r = resolve(text)
    assert r["decision"] == decision, r
    assert r["candidates"][0]["intent"] in ("add_monkey", "shade_smooth", "solidify")


def test_without_a_selection_an_add_goes_beside_what_is_at_the_cursor():
    cube = ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))
    next_to = ((1.0, -0.1, -0.1), (1.2, 0.1, 0.1))
    far = ((5.0, 5.0, 5.0), (6.0, 6.0, 6.0))
    assert voice_ops.add_location((0.0, 0.0, 0.0), 0.1, []) == (0.0, 0.0, 0.0)
    assert voice_ops.add_location((0.0, 0.0, 0.0), 0.1, [far]) == (0.0, 0.0, 0.0)
    x, y, z = voice_ops.add_location((0.0, 0.0, 0.0), 0.1, [cube])
    assert (y, z) == (0.0, 0.0) and x == pytest.approx(1.0 + 0.1 * (voice_ops.ADD_GAP + 0.5))
    x, _, _ = voice_ops.add_location((0.0, 0.0, 0.0), 0.1, [cube, next_to])
    assert x == pytest.approx(1.2 + 0.1 * (voice_ops.ADD_GAP + 0.5))  # past both
    low, high = voice_ops.ADD_SIZE_RANGE
    assert low <= voice_ops.ADD_SIZE <= high <= 0.25  # 1.25 m on the app's 5x table at most


# Talia's P0 reference (samples/mechanical/create_reference.py): a 20 mm cube and a 10 x 30 mm
# cylinder beside it, on the ground at Blender's origin. The fake bracket (contracts/examples):
# a 100 x 60 x 10 mm base plate with a 20 x 40 mm shaft standing on it.
P0_CUBE = ((-0.03, -0.01, 0.0), (-0.01, 0.01, 0.02))
P0_CYLINDER = ((0.015, -0.005, 0.0), (0.025, 0.005, 0.03))
PLATE_BOX = ((-0.05, -0.03, 0.0), (0.05, 0.03, 0.01))
SHAFT_BOX = ((0.01, -0.01, 0.01), (0.03, 0.01, 0.05))
P0, BRACKET = [P0_CUBE, P0_CYLINDER], [PLATE_BOX, SHAFT_BOX]
# HostScene.cs puts Blender's origin 1 m in front of the eyes and 0.35 m below them, at 5x, so
# the eyes are at this Blender point, looking along +Y.
EYE = (0.0, -1.0 / 5, 0.35 / 5)


def degrees_off_view(point):
    d = [p - e for p, e in zip(point, EYE, strict=True)]
    return math.degrees(math.atan2(math.hypot(d[0], d[2]), d[1]))


def overlaps(a, b):
    return all(a[0][i] < b[1][i] and b[0][i] < a[1][i] for i in range(3))


def box_at(center, size):
    return (tuple(c - size / 2 for c in center), tuple(c + size / 2 for c in center))


@pytest.mark.parametrize(("boxes", "anchor"), [(P0, P0_CUBE), (P0, P0_CYLINDER),
                                               (BRACKET, PLATE_BOX), (BRACKET, SHAFT_BOX)])
def test_an_add_goes_above_the_selection_in_view(boxes, anchor):
    """Centred over the selection, ADD_GAP above it (or above what stands on it), its size,
    overlapping nothing, and in the user's view: the selection is what they look at. A second
    add stacks on the first."""
    size = max(voice_ops.ADD_SIZE_RANGE[0], min(max(voice_ops._sides(anchor)),
                                                 voice_ops.ADD_SIZE_RANGE[1]))
    center = voice_ops.add_location(voice_ops.above(anchor, size), size, boxes, axis=2)
    assert center[:2] == pytest.approx(((anchor[0][0] + anchor[1][0]) / 2,
                                        (anchor[0][1] + anchor[1][1]) / 2))
    new = box_at(center, size)
    assert new[0][2] >= anchor[1][2] + size * voice_ops.ADD_GAP - 1e-9  # the gap, at least
    assert not any(overlaps(new, b) for b in boxes)
    assert degrees_off_view(center) < 20  # the Quest 3S shows about 45 degrees each way
    second = voice_ops.add_location(voice_ops.above(anchor, size), size, boxes + [new], axis=2)
    assert second[2] == pytest.approx(new[1][2] + size * (voice_ops.ADD_GAP + 0.5))  # stacked
    assert not any(overlaps(box_at(second, size), b) for b in boxes + [new])
    assert degrees_off_view(second) < 45  # over the plate (10 cm adds) 42: the top of the view


def test_above_the_p0_cube_is_right_over_it():
    size = 0.02
    assert voice_ops.above(P0_CUBE, size) == pytest.approx((-0.02, 0.0, 0.035))  # 5 mm gap


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
                                  "phrases": voice_ops.GRAMMAR, "composition": True}


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
        answer = ask(talia, "smoothen it", target={"id": SHAFT, "generation": 0})
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


def test_the_demo_question_runs_the_chosen_modifier():
    with voice_hosting() as host, host.vr() as talia:
        attach(host)
        answer = ask(talia, "add a modifier", target={"id": SHAFT, "generation": 0})
        assert answer["decision"] == "ask" and answer["reason"] is None
        assert [c["say"] for c in answer["candidates"]] == MENU
        assert all(c["needs_target"] for c in answer["candidates"])
        receipt = talia.run("voice.run", {"id": SHAFT, "generation": 0},
                            {"resolution": answer["resolution"], "choice": 3})
        assert receipt["summary"] == "Voice: Bevel on Shaft"


def test_a_filler_is_rejected_with_nothing_to_say():
    with voice_hosting() as host, host.vr() as talia:
        attach(host)
        answer = ask(talia, "hello", confidence=1.0, target={"id": SHAFT, "generation": 0})
        assert (answer["decision"], answer["reason"], answer["candidates"]) == ("reject", None, [])
        receipt = talia.run("voice.run", {"id": SHAFT, "generation": 0},
                            {"resolution": answer["resolution"], "choice": 1})
        assert_rejected(receipt, "not_found")
        assert host.editor.revision == 0


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
        answer = send("voice.resolve", {"text": "smoothen it", "confidence": 0.9})["payload"]
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

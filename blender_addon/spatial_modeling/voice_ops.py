"""Voice: what the user said, resolved to one of ~40 curated Blender operations, run as a command.

Implements "Voice" in contracts/README.md for the Host role. VoiceCore (in the
Unity app) handles the commands it fully understands itself (move, rotate,
scale, add cube, undo ...). Anything else it sends here as `voice.resolve`
{text, confidence, target}; the host answers `voice.candidates`:

- run: candidate 1 is certain. Unity sends command op `voice.run` choice 1 at once.
- ask: up to three candidates; Unity asks "one, two or three?" and sends the answer.
- reject: nothing fits; `reason` is a sentence Unity can speak.

Nothing named on the wire is ever executed: `voice.run` {resolution, choice}
picks a candidate this host created, once, within EXPIRES_IN seconds. It goes
through commands.py like any command (schema, deduplication, admission,
target generation, leases, one Undo step, scene.update before the result).

The resolver is the intent tier of the measured research prototype (research
results 24 Oct, match_v2.py): a table of intents with trigger phrases and
number, unit, axis and count slots, scored per word (exact, stem, spelling and
sound) and per utterance (the sound of the whole utterance). Thresholds, as
calibrated there: run only when every word of the best phrase was heard, its
score is at least RUN_MIN with a margin of RUN_MARGIN over the next, and the
recognizer's confidence is at least ASR_RUN_MIN; ask from ASK_MIN; a low
confidence may only ask. Join, hide, duplicate and show-hidden stay in the
table only so that they are recognized and refused with a reason: they never
run, are never offered, and aren't in the grammar.

grammar_phrases() is the recognizer's phrase list (`voice.grammar`), generated
from the same table. It leaves out "to": CommandParser treats it as a filler,
and with it in a grammar Vosk scores "two" about 0.5 (#93). "level to" and
"to copies" are still read as 2.

The executor (Voice.run, Blender only; edits.py calls it for `voice.run`)
selects only the target, runs the operator from host.py's timer with
context.temp_override, runs whole-mesh operators in a temporary Edit Mode,
changes an existing modifier of the same type instead of stacking another,
caps the parameters, and puts the host's own selection and active object back.
If the result is too heavy to sync (TRIANGLE_BUDGET evaluated triangles, or
MAX_MESH_BYTES of mesh JSON: flat shading costs about 192 bytes a triangle), it
undoes the change and refuses it, so nothing changed.

Everything above Voice.run runs without bpy, so the tests can use it outside
Blender. Received text is only compared, never executed.
"""

import collections
import hashlib
import json
import logging
import math
import re
import time
import uuid
from collections import ChainMap, OrderedDict

try:
    from . import commands, protocol, server
except ImportError:  # imported directly by the tests, outside Blender
    import commands
    import protocol
    import server

log = logging.getLogger(__name__)

EXPIRES_IN = 30  # seconds a resolution can be run
MAX_RESOLUTIONS = 64  # the newest kept; older ones expire early
MAX_TEXT = 500  # characters of a transcript
TRIANGLE_BUDGET = 50_000  # evaluated triangles a voice result may have (the VR collider limit)
MAX_MESH_BYTES = 8 * 1024 * 1024  # mesh JSON a voice result may have: half a 16 MiB line
BYTES_PER_TRIANGLE_MAX = 222  # sync's upper bound: 3 split vertices of 3 x 12 + 3 x 10 bytes, +24
MAX_SUBSURF_LEVEL = 2  # Suzanne at level 2 is 15,744 triangles, at level 3 62,976
ARRAY_COUNT = (2, 20)
MAX_BEVEL_SEGMENTS = 4
REUSED_MODIFIERS = ("SUBSURF", "ARRAY", "SOLIDIFY", "DECIMATE", "MIRROR", "WIREFRAME", "BEVEL")
MODE_NAMES = {"EDIT_MESH": "Edit Mode", "SCULPT": "Sculpt Mode", "POSE": "Pose Mode"}


# Numbers: NumberWords.TryRead (voice/VoiceCore/Runtime/NumberWords.cs), zero to 999.999,
# "point" and "hundred and", plus near-misses that count only next to a count word.

SMALL = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
         "nineteen"]
TENS = [None, None, "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
# What a recognizer hears for small numbers: "level to", "levels for", "to copies".
SLOT_NEAR = {"to": 2, "too": 2, "for": 4, "won": 1, "free": 3, "tree": 3, "sex": 6, "ate": 8,
             "nein": 9, "tan": 10}


def _at(ws, i):
    return ws[i] if 0 <= i < len(ws) else None


def _small(w):
    return SMALL.index(w) if w in SMALL else -1


def _tens(w):
    return TENS.index(w) * 10 if w in TENS and TENS.index(w) >= 2 else 0


def _below_hundred(ws, j):
    t = _tens(_at(ws, j))
    if t:
        j += 1
        o = _small(_at(ws, j))
        if 1 <= o <= 9:
            t += o
            j += 1
        return True, j, t
    v = _small(_at(ws, j))
    if v < 0:
        return False, j, 0
    return True, j + 1, v


def read_number(ws, i):
    """The number spoken at ws[i:]: (value, next index), or (None, i). NaN if it broke off."""
    j, whole, found = i, 0, False
    h = _small(_at(ws, j))
    if 1 <= h <= 9 and _at(ws, j + 1) == "hundred":
        j += 2
        whole, found = h * 100, True
        k = j + 1 if _at(ws, j) == "and" else j
        ok, k2, rest = _below_hundred(ws, k)
        if ok:
            whole += rest
            j = k2
        elif k > j:
            return float("nan"), k  # "one hundred and a": the rest was misheard
    else:
        ok, j2, below = _below_hundred(ws, j)
        if ok:
            whole, j, found = below, j2, True
    frac = 0.0
    if _at(ws, j) == "point":
        k, scale = j + 1, 0.1
        while k - j <= 3 and 0 <= _small(_at(ws, k)) <= 9:
            frac += _small(_at(ws, k)) * scale
            scale /= 10
            k += 1
        if k == j + 1:
            ok, k2, f = _below_hundred(ws, k)
            if ok:
                frac, k = f / (10.0 if f < 10 else 100.0), k2  # "point twenty five"
        if k > j + 1:
            j, found = k, True
    return (whole + frac, j) if found else (None, i)


# Words and sounds

ALIASES = {"mm": "millimeters", "cm": "centimeters", "m": "meters", "millimetre": "millimeter",
           "millimetres": "millimeters", "centimetre": "centimeter",
           "centimetres": "centimeters", "metre": "meter", "metres": "meters", "%": "percent",
           "doughnut": "donut", "colour": "color", "centre": "center",
           "symmetrical": "symmetric", "twice": "two times", "thrice": "three times",
           "once": "one times", "subsurf": "sub surf", "icosphere": "ico sphere",
           "remesh": "re mesh", "wireframe": "wire frame", "uvsphere": "uv sphere"}
_DIGITS = re.compile(r"\d+(?:\.\d+)?")


def words(text):
    """Lower-case words, digits spelled out, and ALIASES applied; "[unk]" becomes "unk"."""
    text = (text or "").lower().replace("[unk]", " unk ")
    text = _DIGITS.sub(lambda m: " " + " ".join(_digits_to_words(m.group())) + " ", text)
    out = []
    for w in re.findall(r"[a-z]+|%", text):
        out.extend(ALIASES.get(w, w).split())
    return out


def _digits_to_words(d):
    whole, _, frac = d.partition(".")
    n = int(whole)
    if n < 20:
        ws = [SMALL[n]]
    elif n < 100:
        ws = [TENS[n // 10]] + ([SMALL[n % 10]] if n % 10 else [])
    else:
        ws = [SMALL[int(c)] for c in whole]
    if frac:
        ws += ["point"] + [SMALL[int(c)] for c in frac]
    return ws


def stem(w):
    for suffix in ("ings", "ing", "ies", "es", "ed", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            base = w[: -len(suffix)]
            return base + "y" if suffix == "ies" else base
    return w


_SOUND_RULES = (
    ("^kn", "n"), ("^gn", "n"), ("^pn", "n"), ("^wr", "r"), ("^ps", "s"), ("^x", "s"), ("^wh", "w"),
    ("mb$", "m"), ("ph", "f"), ("ck", "k"), ("sch", "sk"), ("tch", "ch"), ("dg(?=[eiy])", "j"),
    ("gh(?![aeiou])", ""), ("c(?=[eiy])", "s"), ("ch", "X"), ("sh", "X"), ("th", "0"),
    ("tio", "X"), ("tia", "X"), ("c", "k"), ("q", "k"), ("x", "ks"), ("z", "s"), ("v", "f"),
    ("g(?=[eiy])", "j"), ("d", "t"), ("b", "p"), ("y(?![aeiou])", ""), ("w(?![aeiou])", ""),
)


def phonetic(word):
    """A small Metaphone-like key: the consonant skeleton; a leading vowel is kept as 'A'."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return ""
    for pattern, replacement in _SOUND_RULES:
        w = re.sub(pattern, replacement, w)
    if not w:
        return "A"  # "why", "y": nothing but glides
    first = "A" if w[0] in "aeiou" else ""
    w = re.sub(r"[aeiouy]", "", w)
    w = re.sub(r"(.)\1+", r"\1", w)
    return (first + w) or "A"


def lev(a, b):
    """Edit distance."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


PHON_LIFT = 0.35  # how far sound may lift a word above its spelling similarity
PRECISION_W = 0.45  # share of a phrase's score that comes from explaining every spoken word
_sim_cache = {}


def word_sim(a, b):
    """1 for the same word, 0.88 for the same stem, else spelling or sound similarity.

    Below 0.65 it is 0."""
    key = (a, b)
    if key in _sim_cache:
        return _sim_cache[key]
    if a == b:
        s = 1.0
    elif stem(a) == stem(b):
        s = 0.88  # "make five copies" should still prefer the phrase with "copies"
    elif len(a) <= 2 or len(b) <= 2:
        s = 0.0
    else:
        s1 = 1 - lev(a, b) / max(len(a), len(b))
        pa, pb = phonetic(a), phonetic(b)
        # Sound counts only for words of four letters or more and similar length ("sun" is not
        # "suzanne"), and can't lift a word far above its spelling ("plane" ~ "boolean").
        ratio = min(len(a), len(b)) / max(len(a), len(b))
        ok = min(len(a), len(b)) >= 4 and ratio >= 0.6 and min(len(pa), len(pb)) >= 2
        s2 = min((1 - lev(pa, pb) / max(len(pa), len(pb), 1)) * 0.92, s1 + PHON_LIFT) if ok else 0
        s = max(s1, s2)
        s = s if s >= 0.65 else 0.0
    if len(_sim_cache) < 100_000:
        _sim_cache[key] = s
    return s


# Slots

UNITS = {"millimeter": 0.001, "millimeters": 0.001, "centimeter": 0.01, "centimeters": 0.01,
         "meter": 1.0, "meters": 1.0}
AXES = {"x": 0, "y": 1, "z": 2, "ex": 0, "why": 1, "zed": 2, "zee": 2}
COUNT_NOUNS = {"copies", "copy", "times", "segments", "segment", "levels", "level", "cuts",
               "steps", "instances"}
SLOT_KEYS_BEFORE = {"level", "levels", "segments", "segment", "steps"}  # "level two"


def extract_slots(ws):
    """Numbers (with unit, count noun and key word), axis, half. Returns (slots, other words)."""
    slots = {"numbers": []}
    rest, i = [], 0
    while i < len(ws):
        w = ws[i]
        val, j = read_number(ws, i)
        if val is None and w in SLOT_NEAR and (
                (i > 0 and ws[i - 1] in SLOT_KEYS_BEFORE) or _at(ws, i + 1) in COUNT_NOUNS):
            val, j = float(SLOT_NEAR[w]), i + 1  # "level to", "to copies"
        if val is not None and math.isnan(val):  # broke off: leave it out rather than guess
            i = j
            continue
        if val is not None:
            item = {"value": val, "unit": None, "noun": None, "key": None}
            if j < len(ws) and ws[j] in UNITS:
                item["unit"] = ws[j]
                j += 1
            elif j < len(ws) and ws[j] == "percent":
                item["unit"] = "percent"
                j += 1
            if j < len(ws) and ws[j] in COUNT_NOUNS:
                item["noun"] = ws[j]  # the noun stays a word too: "copies" means array
            if i > 0 and ws[i - 1] in SLOT_KEYS_BEFORE:
                item["key"] = ws[i - 1]
            slots["numbers"].append(item)
            i = j
            continue
        if w in AXES and (w in "xyz" or (i > 0 and ws[i - 1] in ("on", "along", "the", "in",
                                                                  "around"))):
            slots.setdefault("axis", AXES[w])
            i += 1
            continue
        if w in ("half", "halve"):
            slots["half"] = True
            i += 1
            continue
        if w == "double":
            slots["double"] = True
        rest.append(w)
        i += 1
    return slots, rest


def number_for(slots, nouns=None, keys=None, units=None, unitless=True):
    for n in slots["numbers"]:
        if keys and n["key"] in keys:
            return n
        if nouns and n["noun"] in nouns:
            return n
    for n in slots["numbers"]:
        if units and n["unit"] in units:
            return n
    if unitless:
        for n in slots["numbers"]:
            if n["unit"] is None and n["noun"] is None and n["key"] is None:
                return n
    return None


def length_m(slots, default_unit="millimeters"):
    n = number_for(slots, units=set(UNITS), unitless=True)
    if not n:
        return None
    return n["value"] * UNITS[n["unit"] or default_unit]


# Slot handlers: fill(slots, candidate[, words]) sets props (operator properties) and post
# (modifier properties set afterwards), and may add notes, which keep it from running unasked.


def _levels(s, c):
    n = number_for(s, nouns={"times", "levels", "level"}, keys={"level", "levels"})
    level = int(n["value"]) if n else 1
    c["post"]["levels"] = c["post"]["render_levels"] = max(0, min(level, MAX_SUBSURF_LEVEL))
    if n and level > MAX_SUBSURF_LEVEL:
        c["notes"].append(f"levels capped at {MAX_SUBSURF_LEVEL}")


def _array(s, c):
    n = number_for(s, nouns={"copies", "copy", "times", "instances"})
    if n:
        low, high = ARRAY_COUNT
        c["post"]["count"] = max(low, min(int(n["value"]), high))
    if "axis" in s:
        v = [0.0, 0.0, 0.0]
        v[s["axis"]] = 1.0
        c["post"]["relative_offset_displace"] = v


def _thickness(s, c):
    m = length_m(s)
    if m:
        c["post"]["thickness"] = m


def _bevel(s, c):
    seg = number_for(s, nouns={"segments", "segment"}, keys={"segments", "segment"},
                     unitless=False)
    if seg:
        c["post"]["segments"] = max(1, min(int(seg["value"]), MAX_BEVEL_SEGMENTS))
    n = number_for(s, units=set(UNITS), unitless=not seg)
    if n:
        c["post"]["width"] = n["value"] * UNITS[n["unit"] or "millimeters"]


def _bevel_edit(s, c):
    _bevel(s, c)
    if "width" in c["post"]:
        c["props"]["offset"] = c["post"].pop("width")
    if "segments" in c["post"]:
        c["props"]["segments"] = c["post"].pop("segments")


def _mirror(s, c):
    v = [False, False, False]
    v[s.get("axis", 0)] = True
    c["post"]["use_axis"] = v


def _decimate(s, c):
    n = number_for(s, units={"percent"})
    if n and n["unit"] == "percent":
        c["post"]["ratio"] = max(0.05, min(n["value"] / 100.0, 1.0))
    elif s.get("half") or not n:
        c["post"]["ratio"] = 0.5
    elif n and 0 < n["value"] < 1:
        c["post"]["ratio"] = n["value"]


def _light(s, c, ws):
    for w, kind in (("sun", "SUN"), ("spot", "SPOT"), ("spotlight", "SPOT"), ("area", "AREA"),
                    ("point", "POINT")):
        if w in ws:
            c["props"]["type"] = kind
            return
    c["props"]["type"] = "POINT"


def _apply(s, c, ws):
    which = {k: any(word_sim(w, k) >= 0.85 for w in ws) for k in ("location", "rotation", "scale")}
    if not any(which.values()) or "all" in ws or "everything" in ws:
        which = {"location": True, "rotation": True, "scale": True}
    c["props"].update(which)


def _origin(s, c, ws):
    kind = "ORIGIN_GEOMETRY"
    if "cursor" in ws:
        kind = "ORIGIN_CURSOR"
    elif "geometry" in ws and "origin" in ws and ws.index("geometry") < ws.index("origin"):
        kind = "GEOMETRY_ORIGIN"
    c["props"]["type"] = kind


def _intent(id_, op, say, props=None, post=None, fill=None, needs="MESH", macro=False, edit=None,
            label=None, words_fill=False, edit_only=False, unsupported=None):
    """One intent. say: trigger phrases. needs: "MESH" (a mesh target), "ANY" (any target) or
    None. macro: run in a temporary Edit Mode on the whole mesh. edit: the intent used instead
    in Edit Mode. unsupported: recognized only to refuse it, with this sentence."""
    return {"id": id_, "op": op, "say": say, "props": props or {}, "post": post or {},
            "fill": fill, "needs": needs, "macro": macro, "edit": edit,
            "label": label or say[0], "words_fill": words_fill, "edit_only": edit_only,
            "unsupported": unsupported}


MOD = "object.modifier_add"
INTENTS = [
    _intent("add_monkey", "mesh.primitive_monkey_add",
            ["add a monkey", "monkey", "monkey head", "suzanne", "add suzanne"], needs=None),
    _intent("add_torus", "mesh.primitive_torus_add",
            ["add a torus", "donut", "add a donut", "torus", "ring"], needs=None),
    _intent("add_cone", "mesh.primitive_cone_add", ["add a cone", "cone"], needs=None),
    _intent("add_plane", "mesh.primitive_plane_add",
            ["add a plane", "plane", "ground plane", "floor"], needs=None),
    _intent("add_cylinder", "mesh.primitive_cylinder_add",
            ["add a cylinder", "cylinder", "tube"], needs=None),
    _intent("add_uv_sphere", "mesh.primitive_uv_sphere_add",
            ["add a sphere", "sphere", "uv sphere", "ball"], needs=None),
    _intent("add_ico_sphere", "mesh.primitive_ico_sphere_add",
            ["add an ico sphere", "ico sphere"], needs=None),
    _intent("add_cube", "mesh.primitive_cube_add", ["add a cube", "cube", "box"], needs=None),
    _intent("add_camera", "object.camera_add", ["add a camera", "camera"], needs=None),
    _intent("add_light", "object.light_add",
            ["add a light", "light", "lamp", "sun", "spot light", "area light", "point light"],
            needs=None, fill=_light, words_fill=True),
    _intent("add_empty", "object.empty_add", ["add an empty", "empty"], needs=None),
    _intent("add_text", "object.text_add", ["add text", "text"], needs=None),
    _intent("shade_smooth", "object.shade_smooth",
            ["shade smooth", "smooth shading", "smooth shaded", "shade it smooth"]),
    _intent("shade_flat", "object.shade_flat",
            ["shade flat", "flat shading", "flat shaded", "faceted"]),
    _intent("shade_auto_smooth", "object.shade_auto_smooth", ["shade auto smooth", "auto smooth"]),
    _intent("subsurf", MOD, ["add a subdivision surface", "subdivision surface", "subdivide",
                             "subdivision", "sub surf", "smoother", "make it smoother",
                             "smooth it out", "subdivision surface modifier"],
            props={"type": "SUBSURF"}, fill=_levels, label="Subdivision Surface"),
    _intent("mirror", MOD, ["add a mirror modifier", "mirror", "mirror it", "symmetric",
                            "symmetry", "mirror modifier"],
            props={"type": "MIRROR"}, fill=_mirror, label="Mirror"),
    _intent("solidify", MOD, ["solidify", "make it thicker", "thicker", "thickness", "thick",
                              "thicken", "hollow", "shell", "solidify modifier"],
            props={"type": "SOLIDIFY"}, fill=_thickness, label="Solidify"),
    _intent("decimate", MOD, ["decimate", "simplify", "simplify the mesh", "fewer polygons",
                              "reduce polygon count", "low poly", "poly count", "fewer triangles",
                              "decimate modifier"],
            props={"type": "DECIMATE"}, fill=_decimate, label="Decimate"),
    _intent("bevel", MOD, ["bevel", "bevel the edges", "round the edges", "rounded corners",
                           "round off the corners", "rounded edges", "bevel modifier", "chamfer"],
            props={"type": "BEVEL"}, fill=_bevel, label="Bevel", edit="bevel_edit"),
    _intent("array", MOD, ["add an array", "array", "copies", "make copies", "repeat",
                           "row of copies", "array modifier"],
            props={"type": "ARRAY"}, fill=_array, label="Array"),
    _intent("wireframe", MOD, ["wire frame", "wire frame modifier", "make it a wire frame"],
            props={"type": "WIREFRAME"}, fill=_thickness, label="Wireframe",
            edit="wireframe_edit"),
    _intent("remesh", MOD, ["re mesh", "voxel re mesh", "re mesh modifier"],
            props={"type": "REMESH"}, label="Remesh"),
    _intent("boolean", MOD, ["add a boolean", "boolean", "boolean modifier", "boolean difference"],
            props={"type": "BOOLEAN"}, label="Boolean"),
    _intent("weld", MOD, ["weld", "weld modifier", "weld vertices"], props={"type": "WELD"},
            label="Weld"),
    _intent("screw", MOD, ["screw", "screw modifier"], props={"type": "SCREW"}, label="Screw"),
    _intent("triangulate", MOD, ["triangulate", "triangulate faces", "triangles",
                                 "convert to triangles", "triangulate modifier"],
            props={"type": "TRIANGULATE"}, label="Triangulate", edit="triangulate_edit"),
    _intent("apply_transforms", "object.transform_apply",
            ["apply all transforms", "apply transforms", "apply scale", "apply rotation",
             "apply location", "freeze transforms", "apply rotation and scale"],
            fill=_apply, words_fill=True, label="Apply transforms"),
    _intent("origin_set", "object.origin_set",
            ["origin to geometry", "set origin", "center the origin", "origin to center",
             "center the pivot", "origin to cursor", "geometry to origin",
             "move the origin to the center"],
            fill=_origin, words_fill=True, needs="ANY", label="Set origin"),
    _intent("separate_loose", "mesh.separate",
            ["separate by loose parts", "separate", "split into loose parts", "split apart",
             "break apart", "loose parts"],
            props={"type": "LOOSE"}, macro=True),
    _intent("recalc_normals", "mesh.normals_make_consistent",
            ["recalculate normals", "fix the normals", "recalculate"], props={"inside": False},
            macro=True),
    _intent("flip_normals", "mesh.flip_normals",
            ["flip normals", "reverse normals", "invert normals", "flip"], macro=True),
    _intent("merge_distance", "mesh.remove_doubles",
            ["merge by distance", "remove doubles", "merge vertices", "remove duplicate vertices",
             "merge close vertices", "clean up"], macro=True),
    # factor defaults to 0 from Python, which does nothing (measured)
    _intent("smooth_vertices", "mesh.vertices_smooth", ["smooth vertices", "smooth the vertices"],
            props={"factor": 0.5, "repeat": 5}, macro=True),
    _intent("convert_mesh", "object.convert",
            ["convert to mesh", "convert it to a mesh", "apply modifiers"],
            props={"target": "MESH"}, needs="ANY"),
    # Edit Mode only. Commands are refused while host Blender is in Edit Mode, so these are
    # recognized only to say why they can't run.
    _intent("extrude", "mesh.extrude_region_move",
            ["extrude", "extrude the faces", "extrude it", "pull out"], edit_only=True),
    _intent("inset", "mesh.inset", ["inset", "inset faces", "inset the face"],
            props={"thickness": 0.05}, edit_only=True),
    _intent("bevel_edit", "mesh.bevel", ["bevel"], props={"offset": 0.05, "segments": 2},
            fill=_bevel_edit, edit_only=True, label="Bevel"),
    _intent("triangulate_edit", "mesh.quads_convert_to_tris", ["triangulate"], edit_only=True,
            label="Triangulate faces"),
    _intent("wireframe_edit", "mesh.wireframe", ["wire frame"], edit_only=True,
            label="Wireframe"),
    # Recognized only to refuse them (see the module docstring).
    _intent("duplicate", "object.duplicate",
            ["duplicate", "duplicate it", "make a copy", "copy it", "clone"], needs="ANY",
            unsupported="Duplicate isn't available by voice yet. Use the menu."),
    _intent("join", "object.join", ["join", "join them", "join objects", "combine",
                                    "combine them", "merge the objects"],
            unsupported="Join isn't available by voice. Use host Blender."),
    _intent("hide", "object.hide_view_set", ["hide it", "hide", "hide the object",
                                             "make it invisible", "invisible"], needs="ANY",
            unsupported="Hide isn't available by voice."),
    _intent("unhide", "object.hide_view_clear",
            ["show hidden", "reveal", "show everything", "unhide"], needs=None,
            unsupported="Show hidden isn't available by voice. Use host Blender."),
]
BY_ID = {i["id"]: i for i in INTENTS}
for _i in INTENTS:  # an Edit Mode variant answers to every phrase of its Object Mode intent
    if _i["edit"]:
        _v = BY_ID[_i["edit"]]
        _v["say"] = list(dict.fromkeys(_v["say"] + _i["say"]))

STOP = {"the", "a", "an", "it", "this", "that", "to", "on", "please", "me", "give", "of", "and",
        "i", "want", "some", "can", "you", "could", "would", "will", "let", "us", "lets", "my",
        "its", "is", "be", "now", "just", "with", "by", "in", "for", "into", "unk", "okay", "ok",
        "um", "uh", "so", "then", "them", "these", "those", "one", "object", "selected", "here",
        "there", "new", "put", "create", "insert", "make", "add", "turn", "set", "do", "get",
        "use", "apply", "bit", "little", "more", "along", "axis", "around", "all"}
KEEP_IN_PHRASE = {"apply", "add", "make", "all", "set", "turn", "more"}  # stop words that count
_WEAK = ("modifier", "add", "make", "apply", "set", "turn", "it", "all", "more")


def _content(ws):
    return [w for w in ws if w not in STOP or w in KEEP_IN_PHRASE]


# Word weights: inverse frequency over intents ("modifier", "add", "make" count less).
_intent_words = collections.Counter()
for _it in INTENTS:
    _intent_words.update({w for p in _it["say"] for w in words(p)})


def weight(w):
    if w in STOP and w not in KEEP_IN_PHRASE:
        return 0.0
    base = math.log(1 + len(INTENTS) / (1 + _intent_words.get(w, 0)))
    return base * 0.35 if w in _WEAK else base


_PHRASES = []  # (intent index, content words, their weights, phonetic key)
for _k, _it in enumerate(INTENTS):
    for _p in _it["say"]:
        _cw = [w for w in words(_p) if weight(w) > 0]
        _PHRASES.append((_k, _cw, [weight(w) for w in _cw], "".join(phonetic(w) for w in _cw)))


def phrase_score(uw, ukey, cw, wts, pkey):
    """How well the utterance's content words uw match one phrase: (score 0..1, exact share)."""
    if not cw or not uw:
        return 0.0, 0.0
    used = [False] * len(uw)
    got = exact = 0.0
    for w, wt in zip(cw, wts, strict=True):
        best, bj = 0.0, -1
        for j, u in enumerate(uw):
            if not used[j]:
                s = word_sim(w, u)
                if s > best:
                    best, bj = s, j
        if bj >= 0 and best > 0:
            used[bj] = True
            if w == uw[bj] or stem(w) == stem(uw[bj]):
                exact += wt  # the same word or stem; sound-alikes are never exact
        got += wt * best
    recall = got / sum(wts)
    exact /= sum(wts)
    uwt = [min(max(weight(u), 0.3), 1.5) for u in uw]
    precision = sum(t for t, f in zip(uwt, used, strict=True) if f) / sum(uwt)
    tok = recall * (1 - PRECISION_W + PRECISION_W * precision)
    # The sound of the whole utterance survives split or merged words ("light frame").
    if len(pkey) >= 3 and len(ukey) >= 3:
        phon = 1 - lev(ukey, pkey) / max(len(ukey), len(pkey))
        us, ps = "".join(uw), "".join(cw)
        spell = 1 - lev(us, ps) / max(len(us), len(ps))
        whole = 0.9 * (0.6 * phon + 0.4 * spell)
        if whole >= 0.55 and whole > tok:
            return whole, 0.0  # a sound-alike of the whole utterance is never exact evidence
    return tok, exact


# Decisions, calibrated on the research dev sets and applied unchanged to the held-out ones.
RUN_MIN, RUN_MARGIN, ASK_MIN = 0.85, 0.05, 0.60
EXACT_FOR_RUN = 1.0  # every word of the matched phrase was heard exactly
ASR_RUN_MIN = 0.5  # below this recognizer confidence a candidate is offered, never run
SLOT_BONUS = 0.1
COUNTED = {"array": {"copies", "copy", "times", "instances"},
           "subsurf": {"times", "levels", "level"},
           "bevel": {"segments", "segment"}, "bevel_edit": {"segments", "segment"}}

NO_WORDS = "I didn't hear a command."
NO_MATCH = "I don't know that command."


def _used_counted_slot(intent_id, slots):
    nouns = COUNTED.get(intent_id, set())
    return any(n["noun"] in nouns or n["key"] in nouns for n in slots["numbers"])


def resolve(text, confidence=1.0, context=None):
    """Rank the intents for text. context: mode ("OBJECT" or "EDIT"), active_type (the target's
    Blender type, such as "MESH", or None without one). Returns a dict: decision ("run", "ask"
    or "reject"), reason (a sentence, or None), candidates (up to 3, best first; empty for
    reject), and what was heard (words, slots)."""
    context = context or {}
    mode = context.get("mode", "OBJECT")
    active = context.get("active_type", "MESH")
    ws = words(text)
    unk = sum(1 for w in ws if w == "unk")
    slots, rest = extract_slots(ws)
    uw = _content(rest)
    ukey = "".join(phonetic(w) for w in uw)
    best = {}
    for k, cw, wts, pkey in _PHRASES:
        s, ex = phrase_score(uw, ukey, cw, wts, pkey)
        if s > best.get(k, (0, 0))[0]:
            best[k] = (s, ex)
    ranked = []
    for k, (s, ex) in best.items():
        it = INTENTS[k]
        if mode == "EDIT" and it["edit"]:
            continue  # its Edit Mode variant scores on its own
        why = None
        if it["edit_only"] and mode != "EDIT":
            s *= 0.9
            why = "needs Edit Mode"
        elif it["needs"] == "MESH" and active != "MESH":
            s *= 0.5
            why = "needs an active mesh"
        elif it["needs"] == "ANY" and active is None:
            s *= 0.5
            why = "needs an active object"
        ranked.append((s, k, why, ex))
    ranked.sort(key=lambda x: -x[0])
    out = []
    for s, k, why, ex in ranked[:4]:
        it = INTENTS[k]
        c = {"intent": it["id"], "op": it["op"], "props": dict(it["props"]),
             "post": dict(it["post"]), "label": it["label"], "score": round(s, 3),
             "exact": round(ex, 2), "macro": it["macro"], "needs": it["needs"],
             "notes": [why] if why else []}
        if it["fill"]:
            if it["words_fill"]:
                it["fill"](slots, c, ws)
            else:
                it["fill"](slots, c)
            if _used_counted_slot(it["id"], slots):
                c["score"] = round(min(1.0 + SLOT_BONUS, c["score"] + SLOT_BONUS), 3)
        out.append(c)
    out.sort(key=lambda c: -c["score"])
    out = out[:3]
    decision, reason = _decide(out, uw, unk, confidence)
    out = [] if decision == "reject" else [c for c in out if not _refusal(c)]  # never offered
    return {"decision": decision, "reason": reason, "candidates": out, "words": uw, "slots": slots}


def _refusal(c):
    """Why candidate c can never run here, or None."""
    it = BY_ID[c["intent"]]
    if it["unsupported"]:
        return it["unsupported"]
    if "needs Edit Mode" in c["notes"]:
        return f"{_spoken(c['label'])} needs Edit Mode, which voice can't use yet."
    return None


def _decide(out, uw, unk, confidence):
    s1 = out[0]["score"] if out else 0.0
    s2 = out[1]["score"] if len(out) > 1 else 0.0
    top = out[0] if out else None
    if not uw or (unk and unk >= len(uw)):
        return "reject", NO_WORDS
    if top and s1 >= ASK_MIN and _refusal(top):
        return "reject", _refusal(top)
    if (s1 >= RUN_MIN and s1 - s2 >= RUN_MARGIN and not top["notes"]
            and top["exact"] >= EXACT_FOR_RUN and confidence >= ASR_RUN_MIN):
        return "run", None
    if s1 >= ASK_MIN and any(not _refusal(c) for c in out):
        return "ask", "; ".join(top["notes"]) or None
    return "reject", NO_MATCH


# What each candidate says: "Subdivision Surface, level 2", "Array, 5 copies along Z".


def _spoken(label):
    return label[:1].upper() + label[1:]


def _number(value):
    return f"{round(value, 3):g}"


def _millimeters(meters):
    return f"{_number(meters * 1000)} millimeters"


def say(c):
    """The sentence Unity shows and speaks for a candidate."""
    text, post, props = _spoken(c["label"]), c["post"], c["props"]
    axis = None
    if "relative_offset_displace" in post:
        axis = "XYZ"[post["relative_offset_displace"].index(1.0)]
    elif "use_axis" in post:
        axis = "XYZ"[post["use_axis"].index(True)]
    details = []
    if "levels" in post:
        details.append(f"level {post['levels']}")
    if "count" in post:
        details.append(f"{post['count']} copies")
    if "segments" in post or "segments" in props and c["intent"] == "bevel_edit":
        details.append(f"{post.get('segments', props.get('segments'))} segments")
    if "thickness" in post:
        details.append(_millimeters(post["thickness"]))
    if "width" in post:
        details.append(_millimeters(post["width"]))
    if "ratio" in post:
        details.append(f"{_number(post['ratio'] * 100)} percent")
    if c["intent"] == "add_light":
        details.append(props["type"].lower())
    if c["intent"] == "apply_transforms" and not all(props.get(k) for k in
                                                     ("location", "rotation", "scale")):
        details.append(" and ".join(k for k in ("location", "rotation", "scale") if props.get(k)))
    if c["intent"] == "origin_set":
        details.append({"ORIGIN_GEOMETRY": "to geometry", "ORIGIN_CURSOR": "to the 3D cursor",
                        "GEOMETRY_ORIGIN": "geometry to origin"}[props["type"]])
    if details:
        text += ", " + ", ".join(details)
    if axis is not None:
        text += f" {'on' if c['intent'] == 'mirror' else 'along'} {axis}"
    return text


def wire_candidates(candidates):
    """voice.candidates' `candidates`: what Unity shows, numbered from 1. Display only."""
    return [{"choice": i, "say": say(c), "operator": c["op"], "properties": dict(c["props"]),
             "set": dict(c["post"]), "needs_target": c["needs"] is not None}
            for i, c in enumerate(candidates, 1)]


# The recognizer's phrase list

ABSORBERS = [  # common words, so chatter is heard as chatter, not as commands
    "the", "be", "of", "and", "a", "in", "that", "have", "i", "it", "for", "not", "on", "with",
    "he", "as", "you", "do", "at", "this", "but", "his", "by", "from", "they", "we", "say", "her",
    "she", "or", "an", "will", "my", "one", "all", "would", "there", "their", "what", "so", "up",
    "out", "if", "about", "who", "get", "which", "go", "me", "when", "make", "can", "like", "time",
    "no", "just", "him", "know", "take", "people", "into", "year", "your", "good", "some", "could",
    "them", "see", "other", "than", "then", "now", "look", "only", "come", "its", "over", "think",
    "also", "back", "after", "use", "two", "how", "our", "work", "first", "well", "way", "even",
    "new", "want", "because", "any", "these", "give", "day", "most", "us", "okay", "alright",
    "yeah", "yes", "hello", "hi", "hey", "thanks", "thank", "um", "uh", "oh", "wow", "cool",
    "nice", "great", "sorry", "wait", "right"
]
CHOICE_PHRASES = ("one", "two", "three", "the first one", "the second one", "the third one",
                  "number one", "number two", "number three", "option one", "option two",
                  "option three", "cancel", "never mind", "yes", "no")
CORE_WORDS = [  # VoiceCore's own (Vocabulary.GrammarPhrases) but "to": its commands still work
    "add", "create", "select", "move", "rotate", "turn", "scale", "delete", "remove", "undo",
    "redo", "cancel", "apply", "cube", "sphere", "cylinder", "x", "y", "z", "millimeter",
    "millimeters", "centimeter", "centimeters", "meter", "meters", "degree", "degrees", "percent",
    "times", "up", "down", "minus", "negative", "this", "that", "it", "selected", "the", "a", "an",
    "object", "by", "along", "around", "about", "on", "in", "axis", "please", "and"
]
LEFT_OUT = {"to"}  # sounds like "two"; CommandParser only skips it


def grammar_phrases():
    """Every phrase the recognizer should know, sorted: intent phrases, slots, numbers, choices."""
    phrases = set(ABSORBERS)
    for it in INTENTS:
        if it["unsupported"]:
            continue
        for p in it["say"]:
            spoken = [w for w in words(p) if w not in LEFT_OUT]  # "origin geometry"
            phrases.add(" ".join(spoken))
            if it["op"] == MOD and len(spoken) == 1:
                phrases.add("make it " + spoken[0])
    phrases.update(SMALL[1:] + [t for t in TENS if t] + ["hundred", "point", "half"])
    for n in SMALL[1:6]:
        phrases.update({f"level {n}", f"{n} copies", f"{n} times", f"{n} segments"})
    phrases.update(("millimeters", "centimeters", "meters", "percent"))
    phrases.update(("on x", "on y", "on z", "along x", "along y", "along z", "x", "y", "z"))
    phrases.update(CHOICE_PHRASES)
    phrases.update(("undo", "redo", "undo that", "redo that"))
    phrases.update(CORE_WORDS)
    return sorted(p for p in phrases if p)


GRAMMAR = grammar_phrases()
GRAMMAR_VERSION = hashlib.sha256("\n".join(GRAMMAR).encode()).hexdigest()[:12]


# Messages


def resolve_problem(msg):
    """Why msg doesn't match voice.resolve.schema.json, or None."""
    try:
        commands._envelope(msg)
        p = commands._keys(msg["payload"], "payload", ("text", "confidence"), ("target",))
        if not isinstance(p["text"], str) or not 1 <= len(p["text"]) <= MAX_TEXT:
            raise commands.Invalid(f"text must be a string of 1 to {MAX_TEXT} characters")
        commands._number(p["confidence"], "confidence", (0, 1))
        if "target" in p:
            target = commands._keys(p["target"], "target", ("id", "generation"))
            commands._uuid(target["id"], "target.id")
            commands._revision(target["generation"], "target.generation")
    except commands.Invalid as e:
        return str(e)
    return None


def grammar_query_problem(msg):
    """Why msg doesn't match voice.grammar_query.schema.json, or None."""
    try:
        commands._envelope(msg)
        commands._keys(msg["payload"], "payload", ())
    except commands.Invalid as e:
        return str(e)
    return None


class Voice:
    """voice.resolve and voice.grammar_query for a server, and the executor of voice.run.

    sync: the sync module (find_object, object_id, flush; tests pass a fake). mode: returns
    Blender's context mode ("OBJECT", "EDIT_MESH" ...). clock: seconds, for expiry.
    """

    def __init__(self, sync, mode=None, clock=time.monotonic):
        self.sync = sync
        self.mode = mode or _blender_mode
        self.clock = clock
        self.resolutions = OrderedDict()  # id -> (expires at, candidates, target ID or None)

    def attach(self, srv):
        """Handle voice.resolve and voice.grammar_query on srv. Returns srv."""
        srv.handlers = ChainMap({"voice.resolve": self.on_resolve,
                                 "voice.grammar_query": self.on_grammar_query}, srv.handlers)
        return srv

    def on_grammar_query(self, msg, conn):
        problem = grammar_query_problem(msg)
        if problem:
            re_ = msg["id"] if commands.is_uuid(msg["id"]) else None
            return server.error("invalid_message", f"bad voice.grammar_query: {problem}", re_)
        payload = {"version": GRAMMAR_VERSION, "phrases": list(GRAMMAR)}
        return protocol.message("voice.grammar", payload, re=msg["id"])

    def on_resolve(self, msg, conn):
        problem = resolve_problem(msg)
        if problem:
            re_ = msg["id"] if commands.is_uuid(msg["id"]) else None
            return server.error("invalid_message", f"bad voice.resolve: {problem}", re_)
        p = msg["payload"]
        target = p.get("target")
        obj = self.sync.find_object(target["id"]) if target else None
        mode = self.mode()
        if mode != "OBJECT":
            name = MODE_NAMES.get(mode, mode.replace("_", " ").title())
            result = {"decision": "reject", "candidates": [],
                      "reason": f"Host Blender is in {name}. Switch it to Object Mode first."}
        else:
            context = {"mode": "OBJECT", "active_type": obj.type if obj is not None else None}
            result = resolve(p["text"], p["confidence"], context)
        resolution = uuid.uuid4().hex
        if result["decision"] != "reject":
            self._keep(resolution, result["candidates"], target["id"] if obj else None)
        cands = result["candidates"]
        print(f"Spatial Modeling: voice {p['text']!r} ({p['confidence']:.2f}): "
              f"{result['decision']} {[say(c) for c in cands] or result['reason']}")
        payload = {"resolution": resolution, "decision": result["decision"],
                   "reason": result["reason"], "expires_in": EXPIRES_IN,
                   "candidates": wire_candidates(cands)}
        return protocol.message("voice.candidates", payload, re=msg["id"])

    def _keep(self, resolution, candidates, target_id):
        now = self.clock()
        for rid in [r for r, (expires, _, _) in self.resolutions.items() if expires <= now]:
            del self.resolutions[rid]
        self.resolutions[resolution] = (now + EXPIRES_IN, candidates, target_id)
        while len(self.resolutions) > MAX_RESOLUTIONS:
            self.resolutions.popitem(last=False)

    def take(self, resolution, choice):
        """The candidate voice.run asks for, and the resolution's target ID. Single use:
        raises commands.Refused not_found once it was taken, expired or never offered."""
        kept = self.resolutions.pop(resolution, None)
        if kept is None or kept[0] <= self.clock():
            raise commands.Refused("not_found", "That voice choice has expired. Say it again.")
        _, candidates, target_id = kept
        if not 1 <= choice <= len(candidates):
            raise commands.Refused("not_found", f"There was no choice {choice}. Say it again.")
        return candidates[int(choice) - 1], target_id

    def choose(self, obj, args):
        """voice.run's candidate and the object it runs on (None for an add), or Refused.

        obj: the command's target (a Blender object), or None. Takes the resolution.
        """
        c, target_id = self.take(args["resolution"], args["choice"])
        label = _spoken(c["label"])
        if _refusal(c):
            raise commands.Refused("failed", _refusal(c))
        if c["needs"] is None:
            return c, None  # the target only told the resolver what the user meant
        if obj is None:
            raise commands.Refused("failed", f"{label} needs an object. Select one, then say "
                                   "it again.")
        if target_id is not None and self.sync.find_object(target_id) != obj:
            raise commands.Refused("failed", "That choice was for another object. Say it again.")
        if c["needs"] == "MESH" and obj.type != "MESH":
            raise commands.Refused("failed", f"{label} needs a mesh; {obj.name} is a "
                                   f"{obj.type.lower()}.")
        return c, obj

    # The executor (Blender only)

    def run(self, obj, args):
        """edits.Editor's voice.run: run a candidate this host offered; commands.Applied.

        obj: the command's target, or None. Raises commands.Refused when nothing changed.
        """
        import bpy

        from . import edits, scene

        c, obj = self.choose(obj, args)
        label = _spoken(c["label"])
        if obj is not None and not obj.visible_get():
            raise commands.Refused("failed", f"{obj.name} is hidden in host Blender.")
        if bpy.context.mode != "OBJECT":  # edits.apply checks it first
            raise commands.Refused("failed", "Switch host Blender to Object Mode first.")

        layer = bpy.context.view_layer
        selection = edits._selection()
        before = {o.session_uid for o in layer.objects}
        weight = _weight(bpy, scene, [obj] if obj is not None else [])
        try:
            changed = _execute(bpy, c, obj, label)
        finally:
            edits._restore_selection(selection)  # the host desktop's, not the command's
        created = [o for o in layer.objects if o.session_uid not in before]
        heavy = _too_heavy(bpy, scene, ([obj] if obj is not None else []) + created, weight)
        if heavy:
            name = (created or [obj])[0].name
            _undo(bpy, f"Voice: {label} (too heavy, undone)")
            edits._restore_selection(selection)
            self.sync.flush()  # inside the command's commit: sync sees the scene as it was
            raise commands.Refused("failed", f"That would make {name} too heavy to show in VR "
                                   f"({heavy}), so I undid it.")
        ids = [self.sync.object_id(o) for o in created]  # given inside this Undo step
        where = f" on {obj.name}" if obj is not None else ""
        if created and obj is None:
            summary = f"Voice: added {', '.join(o.name for o in created)}"
        else:
            summary = f"Voice: {say(c)}{where}" + (f" ({changed})" if changed else "")
        return commands.Applied(summary, created=ids)


def _blender_mode():
    import bpy

    return bpy.context.mode


def _override(bpy, obj):
    """context.temp_override for an operator from a timer: a 3D View if there is one, and obj
    as the active, selected and edited object."""
    kw = {}
    wm = bpy.context.window_manager
    for window in wm.windows if wm is not None else ():
        area = next((a for a in window.screen.areas if a.type == "VIEW_3D"), None)
        if area is not None:
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            kw.update(window=window, screen=window.screen, area=area, region=region)
            break
    if obj is not None:
        kw.update(active_object=obj, object=obj, selected_objects=[obj],
                  selected_editable_objects=[obj])
    return bpy.context.temp_override(**kw)


def _select_only(bpy, obj):
    """Make obj the only selected object and the active one: Edit Mode and several operators
    use the view layer's selection, not the context's."""
    layer = bpy.context.view_layer
    for other in layer.objects:
        if other.select_get():
            other.select_set(False)
    if obj is not None:
        obj.select_set(True)
        layer.objects.active = obj


def _execute(bpy, c, obj, label):
    """Run candidate c on obj (or nothing, for an add). Returns what changed, for the summary."""
    module, name = c["op"].split(".")
    operator = getattr(getattr(bpy.ops, module), name)
    _select_only(bpy, obj)
    reused = None
    with _override(bpy, obj):
        try:
            if c["op"] == MOD:
                same = [m for m in obj.modifiers if m.type == c["props"]["type"]]
                if same and c["props"]["type"] in REUSED_MODIFIERS:
                    reused = same[-1]  # "ten copies" after "five copies" changes the array
                    result = {"FINISHED"}
                else:
                    names = {m.name for m in obj.modifiers}
                    result = operator(**c["props"])
            elif c["macro"]:
                bpy.ops.object.mode_set(mode="EDIT")
                try:
                    bpy.ops.mesh.select_all(action="SELECT")
                    result = operator(**c["props"])
                finally:
                    bpy.ops.object.mode_set(mode="OBJECT")
            else:
                result = operator(**c["props"])
        except RuntimeError as e:  # poll() failed: Blender changed nothing
            raise commands.Refused("failed", f"Blender can't {label} here: {e}") from None
    if "FINISHED" not in result:
        raise commands.Refused("failed", f"Blender didn't {label}.")
    if c["op"] != MOD:
        return None
    modifier = reused or next((m for m in obj.modifiers if m.name not in names), None)
    if modifier is None:
        raise RuntimeError(f"Blender reported adding a {label} modifier, but there is none")
    for key, value in c["post"].items():
        if isinstance(value, list):
            getattr(modifier, key)[:] = value
        else:
            setattr(modifier, key, value)
    return "changed the existing one" if reused else None


def _triangles(bpy, scene, objects):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    triangles = 0
    for obj in objects:
        if obj.type not in scene.GEOMETRY_TYPES:
            continue
        evaluated = obj.evaluated_get(depsgraph)
        try:
            mesh = evaluated.to_mesh()
        except RuntimeError:  # "Object does not have geometry data"
            continue
        try:
            triangles += len(mesh.loop_triangles) if mesh is not None else 0
        finally:
            evaluated.to_mesh_clear()
    return triangles


def _bytes(bpy, scene, objects):
    """The objects' mesh JSON as the scene sync will send it."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    unit = float(f"{bpy.context.scene.unit_settings.scale_length:.7g}") or 1.0
    size = 0
    for obj in objects:
        mesh = scene.evaluated_mesh(obj, depsgraph, unit)
        if mesh is not None:
            size += len(json.dumps(mesh.wire(), separators=(",", ":")))
    return size


def _weight(bpy, scene, objects):
    """(triangles, mesh JSON bytes) now; the bytes only when they could be over the limit."""
    triangles = _triangles(bpy, scene, objects)
    if triangles * BYTES_PER_TRIANGLE_MAX <= MAX_MESH_BYTES:
        return triangles, 0
    return triangles, _bytes(bpy, scene, objects)


def _too_heavy(bpy, scene, objects, before):
    """Why the objects' evaluated meshes became too big to sync, or None. before: their
    _weight() before the change; an object that was heavy already may get lighter."""
    triangles = _triangles(bpy, scene, objects)
    if triangles > TRIANGLE_BUDGET and triangles > before[0]:
        return f"{triangles:,} triangles; the limit is {TRIANGLE_BUDGET:,}"
    if triangles * BYTES_PER_TRIANGLE_MAX <= MAX_MESH_BYTES:
        return None  # can't be too big even with every vertex split
    size = _bytes(bpy, scene, objects)
    if size > MAX_MESH_BYTES and size > before[1]:
        return f"{size / 1e6:.1f} MB of mesh; the limit is {MAX_MESH_BYTES / 1e6:.1f} MB"
    return None


def _undo(bpy, label):
    """Take back a change that has no Undo step yet: push one for it, then undo it."""
    bpy.ops.ed.undo_push(message=label)
    if "FINISHED" not in bpy.ops.ed.undo():
        raise RuntimeError("could not undo a voice result that was too heavy")

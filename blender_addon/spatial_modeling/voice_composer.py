"""Deterministic voice plans. No bpy, evaluation, or client-provided operators.

Every editing clause uses a core handler or the existing curated intent registry.
Plans are resolved completely before a single native transaction is admitted.
"""

import copy
import math
import re
import uuid

MAX_STEPS = 24
COLOURS = {
    "red": (0.8, 0.025, 0.025, 1),
    "green": (0.025, 0.5, 0.06, 1),
    "blue": (0.025, 0.12, 0.8, 1),
    "yellow": (0.9, 0.7, 0.02, 1),
    "orange": (0.95, 0.25, 0.015, 1),
    "purple": (0.35, 0.04, 0.65, 1),
    "pink": (0.95, 0.2, 0.45, 1),
    "cyan": (0.025, 0.7, 0.8, 1),
    "white": (0.9, 0.9, 0.9, 1),
    "black": (0.01, 0.01, 0.01, 1),
    "gray": (0.3, 0.3, 0.3, 1),
    "grey": (0.3, 0.3, 0.3, 1),
    "brown": (0.25, 0.08, 0.025, 1),
}
ACTION = r"(?:add|create|move|rotate|turn|scale|select|delete|remove|colour|color|paint|duplicate|reset|set|shade|subdivide|bevel|mirror|solidify|decimate|triangulate|weld|convert|apply|make|smooth|separate|flip|merge|recalculate|round|undo|redo|cancel|save|re\s+mesh)\b"
CONNECTOR = re.compile(r"\b(?:and\s+then|then)\b|;|\band\s+(?=" + ACTION + r")", re.IGNORECASE)
CONTROL = {"undo", "redo", "cancel", "never mind"}
UNITS = {
    "millimeter": 0.001,
    "millimeters": 0.001,
    "mm": 0.001,
    "centimeter": 0.01,
    "centimeters": 0.01,
    "cm": 0.01,
    "meter": 1,
    "meters": 1,
    "m": 1,
}
GRAMMAR = tuple(
    sorted(
        {
            "then",
            "and",
            "and then",
            "colour",
            "color",
            "paint",
            "lighter",
            "darker",
            "lighten",
            "darken",
            "duplicate",
            "reset",
            "rotation",
            "scale",
            "width",
            "height",
            "depth",
            "wide",
            "tall",
            "deep",
            "down",
            "up",
            "negative",
            "positive",
            "half",
            "double",
            "twice",
            "at",
            "along",
            "origin",
            "from",
            "axis",
            "centimeters",
            "centimeter",
            "millimeters",
            "millimeter",
            "meters",
            "meter",
            "degrees",
            "percent",
            "by",
            "factor",
            "distance",
            "copies",
            "selected",
            "object",
            "it",
            "make",
            "its",
            "set",
            "size",
            "times",
            "x",
            "y",
            "z",
            "red",
            "green",
            "blue",
            "yellow",
            "orange",
            "purple",
            "pink",
            "cyan",
            "white",
            "black",
            "gray",
            "grey",
            "brown",
        }
    )
)


class InvalidPlan(ValueError):
    pass


class Missing(Exception):
    def __init__(self, field, question, choices=None):
        self.field, self.question, self.choices = field, question, choices


def handles(text):
    """Only opt in for chains/new syntax; old standalone commands retain their path."""
    t = text.lower()
    return bool(
        CONNECTOR.search(t)
        or re.search(r"\band\b", t)
        or re.search(
            r"\b(colou?r|paint|lighter|darker|lighten|darken|duplicate|reset|width|height|depth|wide|tall|deep)\b",
            t,
        )
        or re.search(r"\bscale\b.*\b(down|up|negative|minus|x|y|z|half|double|twice)\b", t)
        or re.search(r"\bscale\b.*-\s*\d", t)
        or re.search(r"\b(add|create)\b.*\b(along|at|from)\b", t)
    )


def _protect_semantic_and(text):
    # This existing operation contains 'and scale', not a second command.
    return re.sub(
        r"\bapply\s+rotation\s+and\s+scale\b", "apply rotation & scale", text, flags=re.IGNORECASE
    )


def has_chain_connector(text):
    """Recognize an unknown second action too, while retaining legacy semantic phrases."""
    return bool(re.search(r"\b(?:then|and)\b|;", _protect_semantic_and(text), re.IGNORECASE))


def clauses(text):
    text = _protect_semantic_and(text)
    parts = [p.strip(" ,.").replace("&", "and") for p in CONNECTOR.split(text)]
    if not parts or any(not p for p in parts):
        raise InvalidPlan("A sequence needs a command on both sides of then/and.")
    if len(parts) > MAX_STEPS:
        raise InvalidPlan(f"A sequence can contain at most {MAX_STEPS} steps.")
    return parts


def _number(ws, read_number):
    found = []
    at = 0
    while at < len(ws):
        n, end = read_number(ws, at)
        if n is not None:
            found.append((n, at, end))
            at = end
        else:
            at += 1
    if len(found) > 1:
        raise InvalidPlan("Use one amount per step; separate additional edits with then.")
    if not found:
        return None
    n, start, _ = found[0]
    if start and ws[start - 1] in ("negative", "minus"):
        n = -n
    return n


def _axis(ws, required=True):
    axes = [w.upper() for w in ws if w in ("x", "y", "z")]
    if len(set(axes)) > 1:
        raise InvalidPlan("Use one axis per step; separate additional axes with then.")
    if axes:
        return axes[0]
    if "up" in ws or "down" in ws:
        return "Z"
    if required:
        raise Missing("axis", "Which axis for this step: X, Y or Z?")
    return None


def _distance(ws, read_number):
    n = _number(ws, read_number)
    if n is None:
        raise Missing("distance", "How far? Say an amount and millimeters, centimeters or meters.")
    units = {UNITS[w] for w in ws if w in UNITS}
    if len(units) > 1 or any(w in ws for w in ("degrees", "degree", "percent", "times")):
        raise InvalidPlan("This step needs one distance unit: millimeters, centimeters or meters.")
    if not units:
        raise Missing("unit", "In millimeters, centimeters or meters?")
    value = n * next(iter(units))
    if not math.isfinite(value) or abs(value) > 10 or value == 0:
        raise InvalidPlan("Voice distances must be nonzero and at most ten meters.")
    return value


def _check_words(ws, permitted, read_number):
    fillers = {
        "a",
        "an",
        "the",
        "it",
        "this",
        "that",
        "object",
        "selected",
        "please",
        "by",
        "to",
        "on",
        "along",
        "around",
        "axis",
        "of",
        "its",
        "is",
        "at",
        "factor",
        "and",
    }
    at = 0
    while at < len(ws):
        n, end = read_number(ws, at)
        if n is not None:
            at = end
            continue
        if ws[at] not in permitted and ws[at] not in fillers:
            raise InvalidPlan(f"Unsupported word '{ws[at]}' in this step. Nothing was run.")
        at += 1


def parse_step(text, target, known, created, deleted, overrides, index, registry):
    """Return (step, next target). References to future objects are host-only new:N handles."""
    text = re.sub(r"(?<![\w.])(-?)\.(\d+)", r"\g<1>0.\2", text)
    text = re.sub(r"(?<!\w)-(?=\d)", "negative ", text)
    ws = registry.words(text)
    if not ws:
        raise InvalidPlan("An empty step cannot run.")
    if " ".join(ws) in CONTROL or ws[0] in ("undo", "redo", "cancel", "save"):
        raise InvalidPlan(
            "Undo, Redo, Cancel and Save control the whole request; say them separately."
        )
    op = ws[0]
    adding = op in ("add", "create") and not any(
        w in ws for w in ("modifier", "mirror", "array", "subdivision", "boolean")
    )
    # Exact visible names are matched longest-first; names in an Add phrase name the shape instead.
    name_target = None
    if not adding:
        normalized = " " + " ".join(ws) + " "
        matches = []
        for o in known:
            name = " ".join(registry.words(o["name"]))
            # A pronoun already identifies the target. Do not reinterpret a colour,
            # amount or axis as an object with the same visible name.
            pronoun_target = any(w in ("it", "this", "its") for w in ws[1:3])
            explicit_name = any(
                marker + name + " " in normalized for marker in (" of ", " object named ")
            )
            if name and " " + name + " " in normalized and (not pronoun_target or explicit_name):
                matches.append((len(name), o, name))
        if matches:
            longest = max(m[0] for m in matches)
            best = [m for m in matches if m[0] == longest]
            if len(best) != 1:
                raise Missing(
                    "target", "More than one object has that name. Select the intended object."
                )
            _, obj, name = best[0]
            name_target = obj["id"]
            normalized = normalized.replace(" " + name + " ", " it ", 1)
            ws = normalized.split()
    current = name_target or overrides.get((index, "target")) or target
    if current in deleted:
        raise InvalidPlan("A later step refers to an object deleted earlier in this sequence.")
    if (index, "operation") in overrides:
        candidate = overrides[(index, "operation")]
        if candidate["needs"] is not None and current is None:
            raise Missing("target", "Please select the object for this step.")
        step = {"kind": "curated", "candidate": candidate, "target": current}
        if candidate["needs"] is None:
            step["created"] = f"new:{index}"
            current = step["created"]
        return step, current
    suffix = overrides.get((index, "suffix"), "")
    if suffix:
        ws += registry.words(suffix)
    if adding:
        # Compact placement is syntactic sugar for Add followed by Move, not a special executor.
        place_at = next((i for i, w in enumerate(ws) if w in ("along", "at", "from")), None)
        first_number = next(
            (i for i in range(len(ws)) if registry.read_number(ws, i)[0] is not None), None
        )
        if place_at is not None and first_number is not None:
            cut = min(place_at, first_number)
            if "from" in ws:
                raise InvalidPlan(
                    "Distance from an axis is ambiguous. Say at X twenty centimeters, or then move it along X."
                )
            add_text, placement = " ".join(ws[:cut]), " ".join(ws[cut:])
            r = registry.resolve(add_text, 1, {"mode": "OBJECT", "active_type": None})
            if r["decision"] != "run" or r["candidates"][0]["needs"] is not None:
                raise InvalidPlan("Name one supported shape before its placement.")
            axis = _axis(registry.words(placement))
            distance = _distance(registry.words(placement), registry.read_number)
            ref = f"new:{index}"
            return {
                "kind": "add_placed",
                "candidate": r["candidates"][0],
                "axis": axis,
                "distance": distance,
                "absolute": "at" in ws,
                "created": ref,
            }, ref
    if op in ("select",):
        if current is None:
            raise Missing("target", "Select the object for this step.")
        return {"kind": "select", "target": current}, current
    if op in (
        "move",
        "rotate",
        "turn",
        "scale",
        "delete",
        "remove",
        "duplicate",
        "reset",
        "set",
        "colour",
        "color",
        "paint",
        "lighten",
        "darken",
    ) or (op == "make" and any(w in ws for w in (*COLOURS, "lighter", "darker"))):
        if current is None:
            raise Missing("target", "Please select the object for this step.")
        step = {"target": current}
        if op in ("move", "duplicate"):
            if "from" in ws:
                raise InvalidPlan("Say along an axis, not distance from an axis.")
            if op == "duplicate" and not any(
                w in UNITS or w in ("x", "y", "z", "up", "down") for w in ws
            ):
                delta = [0, 0, 0]
            else:
                axis = _axis(ws)
                amount = _distance(ws, registry.read_number)
                if "down" in ws or re.search(r"(?:negative|minus)\s+[xyz]\b", " ".join(ws)):
                    amount = -amount
                delta = [0, 0, 0]
                delta["XYZ".index(axis)] = amount
            _check_words(
                ws,
                set(UNITS)
                | {
                    "move",
                    "duplicate",
                    "x",
                    "y",
                    "z",
                    "up",
                    "down",
                    "negative",
                    "minus",
                    "positive",
                },
                registry.read_number,
            )
            step.update(kind=op, by=delta)
            if op == "duplicate":
                step["created"] = f"new:{index}"
                current = step["created"]
        elif op in ("rotate", "turn"):
            axis = _axis(ws)
            n = _number(ws, registry.read_number)
            if n is None:
                raise Missing("angle", "How many degrees for this rotation?")
            if any(w in UNITS or w in ("percent", "times") for w in ws):
                raise InvalidPlan(
                    "Rotate needs an angle in degrees, not a distance or scale factor."
                )
            if not any(w in ws for w in ("degree", "degrees")):
                raise Missing("angle_unit", "Say the angle in degrees.")
            if not 0 < abs(n) <= 360:
                raise InvalidPlan("Voice rotations must be nonzero and at most 360 degrees.")
            _check_words(
                ws,
                {
                    "rotate",
                    "turn",
                    "x",
                    "y",
                    "z",
                    "degrees",
                    "degree",
                    "negative",
                    "minus",
                    "positive",
                },
                registry.read_number,
            )
            if re.search(r"(?:negative|minus)\s+[xyz]\b", " ".join(ws)):
                n = -n
            step.update(kind="rotate", axis=axis, angle=math.radians(n))
        elif op == "scale":
            axis = next((w.upper() for w in ws if w in ("x", "y", "z")), None)
            # 'down' means shrink, not a spatial axis. Signed factors mean mirror.
            n = _number(ws, registry.read_number)
            if n is None:
                n = 0.5 if "half" in ws else 2 if "double" in ws or "twice" in ws else None
            if n is None:
                raise Missing("factor", "Scale by what factor or percentage?")
            factor = n / 100 if "percent" in ws else n
            if "down" in ws or "up" in ws:
                if "percent" not in ws or n < 0:
                    raise InvalidPlan(
                        "Say scale down/up by a positive percentage, or scale by a signed factor."
                    )
                factor = 1 - n / 100 if "down" in ws else 1 + n / 100
            if not math.isfinite(factor) or not 0.01 <= abs(factor) <= 100:
                raise InvalidPlan(
                    "Scale magnitude must be between 0.01 and 100; zero is not allowed."
                )
            if sum(w in ("x", "y", "z") for w in ws) > 1:
                raise InvalidPlan("Use one scale axis per step.")
            _check_words(
                ws,
                {
                    "scale",
                    "x",
                    "y",
                    "z",
                    "down",
                    "up",
                    "negative",
                    "minus",
                    "positive",
                    "percent",
                    "times",
                    "half",
                    "double",
                    "twice",
                },
                registry.read_number,
            )
            if axis and re.search(r"(?:negative|minus)\s+[xyz]\b", " ".join(ws)):
                factor = -factor
            factors = [1, 1, 1] if axis else [factor] * 3
            if axis:
                factors["XYZ".index(axis)] = factor
            step.update(kind="scale", by=factors)
        elif op in ("delete", "remove"):
            _check_words(ws, {"delete", "remove"}, registry.read_number)
            step.update(kind="delete")
            deleted.add(current)
        elif op == "reset":
            field = (
                "colour"
                if any(w in ws for w in ("colour", "color"))
                else "rotation"
                if "rotation" in ws
                else "scale"
                if "scale" in ws
                else None
            )
            if field is None:
                raise Missing("reset", "Reset rotation, scale or colour?")
            _check_words(ws, {"reset", field, "color"}, registry.read_number)
            step.update(kind="reset", field=field)
        elif op == "set":
            axis = next(
                (
                    a
                    for names, a in (
                        (("width", "wide"), "X"),
                        (("depth", "deep"), "Y"),
                        (("height", "tall"), "Z"),
                    )
                    if any(w in ws for w in names)
                ),
                None,
            )
            if axis is None:
                raise Missing(
                    "dimension", "Set width (local X), depth (local Y) or height (local Z)?"
                )
            distance = _distance(ws, registry.read_number)
            if distance < 0:
                raise InvalidPlan("An exact dimension must be positive.")
            _check_words(
                ws,
                set(UNITS) | {"set", "width", "wide", "depth", "deep", "height", "tall"},
                registry.read_number,
            )
            step.update(kind="dimension", axis=axis, distance=distance)
        else:
            colours = [c for c in COLOURS if c in ws]
            shade = (
                "lighter"
                if any(w in ws for w in ("lighter", "lighten"))
                else "darker"
                if any(w in ws for w in ("darker", "darken"))
                else None
            )
            if len(colours) > 1:
                raise InvalidPlan("Use one colour per step.")
            if not colours and not shade:
                raise Missing("colour", "Which colour? For example red, blue or green.")
            _check_words(
                ws,
                set(COLOURS)
                | {"colour", "color", "paint", "make", "lighter", "darker", "lighten", "darken"},
                registry.read_number,
            )
            step.update(kind="colour", colour=colours[0] if colours else None, shade=shade)
        return step, current
    # All existing supported curated operations use their original registry and parameter fillers.
    known_words = {w for phrase in registry.GRAMMAR for w in registry.words(phrase)} | {"to"}
    if any(w not in known_words for w in ws):
        raise InvalidPlan("An unsupported word occurs in this step. Nothing was run.")
    r = registry.resolve(" ".join(ws), 1, {"mode": "OBJECT", "active_type": "MESH"})
    if r["decision"] == "reject" or not r["candidates"]:
        raise InvalidPlan(r["reason"] or "That step is not a supported editing command.")
    if r["decision"] != "run":
        raise Missing(
            "operation",
            "Which operation for this step? "
            + "; ".join(f"{i}: {registry.say(c)}" for i, c in enumerate(r["candidates"], 1)),
            r["candidates"],
        )
    c = r["candidates"][0]
    if c["needs"] is not None and current is None:
        raise Missing("target", "Please select the object for this step.")
    step = {"kind": "curated", "candidate": c, "target": current}
    if c["needs"] is None:
        step["created"] = f"new:{index}"
        current = step["created"]
    return step, current


class Planner:
    def __init__(self, registry, clock):
        self.registry, self.clock = registry, clock
        self.pending = {}

    def resolve(self, text, target, objects, continuation=None, owner=None, document=None):
        now = self.clock()
        self.pending = {k: v for k, v in self.pending.items() if now < v["expires"]}
        old = self.pending.pop(continuation, None) if continuation else None
        if continuation and (old is None or old["owner"] != owner or old["document"] != document):
            raise InvalidPlan(
                "That unfinished sequence expired or its document changed. Say the full sequence again."
            )
        if old:
            parts, overrides, initial = old["parts"], old["overrides"], old["initial"]
            field, index = old["field"], old["index"]
            # A changed/deleted captured target cancels, rather than silently using a newer object.
            generations = {o["id"]: o["generation"] for o in objects}
            if any(generations.get(i) != g for i, g in old["generations"].items()):
                raise InvalidPlan(
                    "An object changed during clarification. Say the full sequence again."
                )
            if field == "target":
                if target is not None:
                    overrides[(index, "target")] = target
                    if initial is None:
                        initial = target
            elif field == "operation":
                n = _number(self.registry.words(text), self.registry.read_number)
                if n is None or int(n) != n or not 1 <= n <= len(old["choices"]):
                    raise InvalidPlan("Say one of the displayed operation numbers, or cancel.")
                overrides[(index, "operation")] = old["choices"][int(n) - 1]
            else:
                overrides[(index, "suffix")] = (
                    overrides.get((index, "suffix"), "") + " " + text
                ).strip()
        else:
            parts, overrides, initial = clauses(text), {}, target
        current, steps, deleted = initial, [], set()
        for index, part in enumerate(parts):
            try:
                step, current = parse_step(
                    part, current, objects, {}, deleted, overrides, index, self.registry
                )
                steps.append(step)
            except Missing as missing:
                token = uuid.uuid4().hex
                self.pending[token] = {
                    "expires": now + 30,
                    "owner": owner,
                    "document": document,
                    "parts": parts,
                    "overrides": overrides,
                    "initial": initial,
                    "field": missing.field,
                    "index": index,
                    "choices": missing.choices,
                    "generations": {
                        o["id"]: o["generation"]
                        for o in objects
                        if o["id"] in {s.get("target") for s in steps} | {initial}
                        or any(
                            " " + " ".join(self.registry.words(o["name"])) + " "
                            in " " + " ".join(self.registry.words(part)) + " "
                            for part in parts
                        )
                    },
                }
                return {
                    "decision": "clarify",
                    "resolution": token,
                    "reason": f"Step {index + 1} of {len(parts)}: {missing.question}\nPlan: "
                    + "; then ".join(parts),
                    "missing": missing.field,
                    "candidates": [],
                    "expires_in": 30,
                }
        targets = {
            s["target"] for s in steps if s.get("target") and not s["target"].startswith("new:")
        }
        generations = {o["id"]: o["generation"] for o in objects if o["id"] in targets}
        if len(generations) != len(targets):
            raise InvalidPlan("A sequence target is no longer in the current scene.")
        primary = next(iter(sorted(targets)), None)
        label = "; then ".join(parts)
        deleting = [step["target"] for step in steps if step["kind"] == "delete"]
        if deleting:
            names = {o["id"]: o["name"] for o in objects}
            targets_text = ", ".join(
                names[ref]
                if ref in names
                else "new object from step " + str(int(ref.split(":")[1]) + 1)
                for ref in deleting
            )
            if len(targets_text) > 180:
                raise InvalidPlan(
                    "Too many long deletion targets for a readable confirmation. Use a shorter sequence."
                )
            label = "DELETE: " + targets_text + " | " + label

        candidate = {
            "intent": "__sequence",
            "op": "voice.sequence",
            "props": {},
            "post": {},
            "needs": "ANY" if primary else None,
            "label": label[:240],
            "steps": copy.deepcopy(steps),
            "generations": generations,
            "primary": primary,
            "final_target": current,
            "document": document,
            "confirm": any(s["kind"] == "delete" for s in steps),
            "owner": owner,
        }
        return {"decision": "run", "reason": None, "candidates": [candidate]}

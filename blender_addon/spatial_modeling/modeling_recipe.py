"""Bounded AI modeling recipes. Model output is data, never executable code.

Preparation validates the complete ordered plan and captures native identity.
Execution uses the same allowlisted kernels as controller gestures and the
caller's existing single Undo/publication wrapper. No UI selection-all macro.
"""

import copy
import math
import re
import time
import uuid

MAX_STEPS = 24
MAX_INDICES = 16384
TTL = 120.0
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,47}\Z")
_UUID = re.compile(r"[0-9a-f]{32}\Z")
_COMPONENTS = {"object", "vertex", "edge", "face"}


class InvalidRecipe(ValueError):
    pass


class Clarify(InvalidRecipe):
    def __init__(self, field, question):
        self.field = field
        super().__init__(question)


def validate_wire(draft, context):
    """Schema mirror for Blender's dependency-free protocol admission."""
    _keys(draft, ("decision", "steps"), ("missing", "reason", "unhandled_intent"))
    if draft["decision"] not in ("propose", "clarify", "reject"):
        raise InvalidRecipe("Invalid recipe decision")
    steps = draft["steps"]
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        raise InvalidRecipe("Invalid recipe steps")
    for name, limit in (("missing", 128), ("unhandled_intent", 512)):
        if name in draft and (not isinstance(draft[name], list) or len(draft[name]) > 24
                             or any(not isinstance(s, str) or len(s) > limit for s in draft[name])):
            raise InvalidRecipe("Invalid recipe " + name)
    if "reason" in draft and (not isinstance(draft["reason"], str) or len(draft["reason"]) > 2048):
        raise InvalidRecipe("Invalid recipe reason")
    for step in steps:
        _keys(step, ("id", "tool", "target", "selection", "params"))
        if not isinstance(step["id"], str) or not _ID.fullmatch(step["id"]):
            raise InvalidRecipe("Invalid step ID")
        if not isinstance(step["tool"], str) or len(step["tool"]) > 64 or not isinstance(step["params"], dict):
            raise InvalidRecipe("Invalid typed tool")
        for name in ("target", "selection"):
            value = step[name]
            if isinstance(value, dict) and (name == "target" or "step" in value):
                _keys(value, ("step", "output"))
                if any(not isinstance(value[key], str) or len(value[key]) > limit
                       for key, limit in (("step", 48), ("output", 64))):
                    raise InvalidRecipe("Invalid output reference")
            elif name == "target":
                if value is not None and (not isinstance(value, str) or len(value) > 128):
                    raise InvalidRecipe("Invalid object reference")
            elif value != "captured":
                _keys(value, ("component", "indices"))
                if not isinstance(value["component"], str) or value["component"] not in _COMPONENTS or not isinstance(value["indices"], list) or len(value["indices"]) > MAX_INDICES:
                    raise InvalidRecipe("Invalid component selection")
                indices = value["indices"]
                if any(not _integer(i) for i in indices) or len(set(indices)) != len(indices):
                    raise InvalidRecipe("Invalid component indices")
    _keys(context, ("document_id", "open_epoch", "revision", "mode", "native_tool", "topology_token", "selection"),
          ("objects", "options", "gesture_epoch", "gesture_active", "native_selection"))
    if any(not isinstance(context[name], str) or not _UUID.fullmatch(context[name]) for name in ("document_id", "open_epoch")):
        raise InvalidRecipe("Invalid captured document identity")
    for name in ("revision", "gesture_epoch"):
        value = context.get(name, 0)
        if not _integer(value) or (name == "revision" and value > 9007199254740991):
            raise InvalidRecipe("Invalid captured revision/epoch")
    for name, limit in (("mode", 64), ("native_tool", 128), ("topology_token", 128)):
        if not isinstance(context[name], str) or len(context[name]) > limit:
            raise InvalidRecipe("Invalid captured " + name)
    if not isinstance(context["selection"], dict) or ("options" in context and not isinstance(context["options"], dict)):
        raise InvalidRecipe("Invalid captured selection/options")
    if "native_selection" in context and not isinstance(context["native_selection"], dict):
        raise InvalidRecipe("Invalid captured native selection")
    if "gesture_active" in context and type(context["gesture_active"]) is not bool:
        raise InvalidRecipe("Invalid captured gesture flag")
    if "objects" in context and (not isinstance(context["objects"], list) or len(context["objects"]) > 4096 or any(not isinstance(obj, dict) for obj in context["objects"])):
        raise InvalidRecipe("Invalid captured objects")
    selection = context["selection"]
    _selection({"component": selection.get("component", "object"), "indices": selection.get("indices", [])})
    for values in (context.get("objects", []), selection.get("objects", [])):
        if not isinstance(values, list) or len(values) > 4096:
            raise InvalidRecipe("Invalid captured objects")
        for obj in values:
            if not isinstance(obj, dict) or not isinstance(obj.get("id"), str) or not _UUID.fullmatch(obj["id"]) or not _integer(obj.get("generation")):
                raise InvalidRecipe("Invalid captured object identity")


def _integer(value):
    return type(value) is int and value >= 0 or type(value) is float and math.isfinite(value) and value >= 0 and int(value) == value


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise InvalidRecipe("The recipe contains missing or unsupported fields.")


def _numbers(value):
    if isinstance(value, dict):
        for item in value.values():
            _numbers(item)
    elif isinstance(value, list):
        for item in value:
            _numbers(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise InvalidRecipe("Recipe numbers must be finite.")
    elif not isinstance(value, (str, int, float, bool, type(None))):
        raise InvalidRecipe("Recipe parameters must be ordinary JSON data.")


def _selection(value):
    _keys(value, ("component", "indices"))
    if not isinstance(value["component"], str) or value["component"] not in _COMPONENTS:
        raise InvalidRecipe("Choose object, vertex, edge or face selection.")
    indices = value["indices"]
    if not isinstance(indices, list) or len(indices) > MAX_INDICES:
        raise InvalidRecipe("A selection may contain at most 16384 native components.")
    if any(not _integer(i) for i in indices):
        raise InvalidRecipe("Component indices must be nonnegative integers.")
    if len(indices) != len(set(indices)):
        raise InvalidRecipe("Component selections must not repeat indices.")
    if value["component"] != "object" and not indices:
        raise Clarify("selection", "Select the vertices, edges or faces to edit first.")
    if value["component"] == "object" and indices:
        raise InvalidRecipe("An object selection cannot contain component indices.")
    return {"component": value["component"], "indices": [int(i) for i in indices]}


def _reference(value, previous, output_kind=False):
    _keys(value, ("step", "output"))
    if value["step"] not in previous or not isinstance(value["output"], str):
        raise InvalidRecipe("A recipe may reference only an earlier step's declared output.")
    outputs = previous[value["step"]].get("outputs", [])
    names = set(outputs) if isinstance(outputs, (dict, list, tuple)) else set()
    if value["output"] not in names:
        raise InvalidRecipe("That tool does not declare the requested geometry output.")
    return dict(value)


def capture_context(sync):
    """Read native context without assigning IDs, saving files or changing mode."""
    import bpy

    from . import preview_spatial

    doc = sync.describe()
    native = preview_spatial.read_state(bpy.context, sync)
    model = native.get("model_edit", native)
    snapshot = sync.snapshot(doc)
    return {
        "document_id": doc["id"], "open_epoch": doc["open_epoch"],
        "revision": doc.get("revision", 0), "mode": bpy.context.mode,
        "native_tool": model.get("native_tool", ""),
        "topology_token": model.get("topology_token", ""),
        "options": copy.deepcopy(model.get("options", model.get("settings", {}))),
        "native_selection": copy.deepcopy(model.get("selection", {})),
        "objects": [{"id": obj["id"], "name": obj.get("name", ""),
                     "generation": obj["generation"], "type": obj.get("type", "MESH")}
                    for obj in snapshot["objects"] if obj.get("visible", True)],
        "model": model,
    }


def validate_context(expected, actual):
    if not isinstance(expected, dict):
        raise InvalidRecipe("A fresh captured modeling context is required.")
    if expected.get("gesture_active"):
        raise InvalidRecipe("Finish or cancel the active controller edit before requesting a plan.")
    if actual.get("options", {}).get("native_context_fingerprint_unavailable"):
        raise InvalidRecipe("The complete native editing context could not be captured. Narrow the visible scene and request a fresh plan.")
    for name in ("document_id", "open_epoch", "revision", "mode", "native_tool", "topology_token", "options", "native_selection"):
        if name in expected and expected[name] != actual.get(name):
            raise InvalidRecipe("The Blender document, geometry, tool or options changed. Request a fresh plan.")
    available = {obj["id"]: obj["generation"] for obj in actual["objects"]}
    for obj in expected.get("objects", []):
        if not isinstance(obj, dict) or available.get(obj.get("id")) != obj.get("generation"):
            raise InvalidRecipe("The captured object context changed. Request a fresh plan.")
    selected = expected.get("selection", {})
    if not isinstance(selected, dict):
        raise InvalidRecipe("The captured selection is invalid.")
    native = actual.get("native_selection", {})
    if (selected.get("component", "object") != "object" and native
            and (selected.get("component") != native.get("component") or sorted(selected.get("indices", [])) != sorted(native.get("indices", [])))):
        raise InvalidRecipe("The native component selection changed or is still synchronizing. Select again and request a fresh plan.")
    for obj in selected.get("objects", []):
        if not isinstance(obj, dict) or available.get(obj.get("id")) != obj.get("generation"):
            raise InvalidRecipe("A selected object changed or disappeared. Select again and request a fresh plan.")


class Planner:
    def __init__(self, catalog, validator, clock=time.monotonic):
        self.catalog = {item["id"]: copy.deepcopy(item) for item in catalog}
        self.validator, self.clock = validator, clock
        self.plans = {}

    def prepare(self, draft, expected, actual, owner, stage=None):
        _keys(draft, ("decision", "steps"), ("missing", "reason", "unhandled_intent"))
        if draft["decision"] not in ("propose", "clarify", "reject"):
            raise InvalidRecipe("Gemini must propose the whole plan, ask a question or refuse it.")
        if draft.get("unhandled_intent"):
            raise InvalidRecipe("Part of the requested edit could not be expressed. Nothing was run.")
        if draft["decision"] == "reject":
            raise InvalidRecipe(str(draft.get("reason") or "This edit could not be expressed safely.")[:512])
        if draft["decision"] == "clarify" or draft.get("missing"):
            missing = draft.get("missing") or ["detail"]
            raise Clarify(str(missing[0])[:64], str(draft.get("reason") or "Please provide the missing editing detail.")[:512])
        validate_context(expected, actual)
        if not isinstance(draft["steps"], list) or not 1 <= len(draft["steps"]) <= MAX_STEPS:
            raise InvalidRecipe("A recipe must contain between one and 24 ordered steps.")
        objects = {obj["id"]: obj for obj in actual["objects"]}
        aliases = {"object_" + str(i): obj["id"] for i, obj in enumerate(expected.get("objects", actual["objects"]))}
        selected = expected.get("selection", {})
        selected_objects = selected.get("objects", [])
        if len(selected_objects) == 1:
            aliases["selected"] = selected_objects[0]["id"]
        for obj in actual["objects"]:
            if sum(other.get("name") == obj.get("name") for other in actual["objects"]) == 1:
                aliases[obj.get("name", "")] = obj["id"]
        compiled, previous, generations = [], {}, {}
        for step in draft["steps"]:
            _keys(step, ("id", "tool", "target", "selection", "params"))
            sid, tool = step["id"], step["tool"]
            if not isinstance(sid, str) or not _ID.fullmatch(sid) or sid in previous:
                raise InvalidRecipe("Recipe step IDs must be short, unique names.")
            spec = self.catalog.get(tool) if isinstance(tool, str) else None
            if spec is None:
                raise InvalidRecipe("A requested tool is absent from this host's capability catalog.")
            target = step["target"]
            if isinstance(target, dict):
                target = _reference(target, previous, True)
            elif isinstance(target, str):
                target = aliases.get(target, target)
                if target not in objects:
                    raise Clarify("target", "Select or name the exact object for step " + sid + ".")
                generations[target] = objects[target]["generation"]
            elif target is not None:
                raise InvalidRecipe("A recipe target must be an object handle or earlier object output.")
            if target is None and tool != "object.add":
                raise Clarify("target", "Select or name the exact object for step " + sid + ".")
            selection = step["selection"]
            if selection == "captured":
                selection = _selection({"component": selected.get("component", "object"), "indices": selected.get("indices", [])})
            elif isinstance(selection, dict) and "step" in selection:
                selection = _reference(selection, previous)
            else:
                selection = _selection(selection)
            component = selection.get("component")
            if component and spec.get("components") and component not in spec["components"]:
                raise InvalidRecipe("The selected component type cannot be used by " + tool + ".")
            if spec.get("modes") and actual["mode"] not in spec["modes"]:
                raise Clarify("mode", "Choose the Blender mode required by " + tool + " before requesting the plan.")
            params = copy.deepcopy(step["params"])
            if not isinstance(params, dict):
                raise InvalidRecipe("Tool parameters must be typed JSON fields.")
            _numbers(params)
            if tool == "mesh.merge" and params.get("variant") in {"FIRST", "LAST"}:
                native_selection = actual.get("native_selection", {})
                if (not native_selection.get("order_complete")
                        or selection.get("component") != "vertex"
                        or selection.get("indices") != native_selection.get("indices")):
                    raise Clarify("selection", "Merge First/Last needs the current ordered native vertex picks; select vertices individually and request the complete edit again.")
            for name, value in list(params.items()):
                if name.endswith("_id"):
                    value = aliases.get(value, value) if isinstance(value, str) else value
                    if not isinstance(value, str) or value not in objects:
                        raise Clarify(sid + "." + name, "Choose the exact visible object for " + name.replace("_", " ") + ".")
                    params[name] = value
                    generations[value] = objects[value]["generation"]
            required = set(spec.get("parameters", {}).get("required", [])) - set(params)
            if required:
                field = min(required)
                raise Clarify(sid + "." + field, "Step " + sid + " needs " + field.replace("_", " ") + ".")
            try:
                validated = self.validator(tool, params, component)
                if isinstance(validated, dict):
                    params = validated
            except ValueError as exc:
                raise InvalidRecipe(str(exc)) from exc
            compiled.append({"id": sid, "tool": tool, "target": target,
                             "selection": selection, "params": params})
            previous[sid] = spec
        canonical = copy.deepcopy(actual)
        canonical["selection"] = copy.deepcopy(selected)
        staged = stage(compiled, canonical) if stage else {}
        plan_id = uuid.uuid4().hex
        summary = "; then ".join(step["tool"] + " " + str(step["params"]) for step in compiled)
        plan = {"intent": "__recipe", "op": "voice.recipe", "props": {}, "post": {},
                "needs": "ANY" if generations else None, "label": summary[:240],
                "steps": compiled, "generations": generations,
                "primary": next(iter(sorted(generations)), None), "owner": owner,
                "document": (actual["document_id"], actual["open_epoch"]),
                "context": canonical, "confirm": True, "preview": staged or {}}
        now = self.clock()
        self.plans = {pid: item for pid, item in self.plans.items() if item[0] > now}
        self.plans[plan_id] = (now + TTL, plan)
        while len(self.plans) > 64:
            del self.plans[next(iter(self.plans))]
        return plan_id, plan


def execute(voice, candidate, editor):
    """Run one admitted stored plan under Editor's one Undo/publication wrapper."""
    import bpy

    from . import commands, modeling_tools, voice_sequence

    try:
        from . import live_edit
        live_edit.ensure_no_active()
    except ImportError:
        pass
    actual = capture_context(editor.sync)
    validate_context(candidate["context"], actual)
    related = editor.linked(candidate["generations"])
    objects = [editor.sync.find_object(oid) for oid in set(candidate["generations"]) | set(related)]
    original_mode = bpy.context.mode
    if original_mode == "EDIT_MESH":
        for obj in objects:
            if obj is not None:
                obj.update_from_editmode()
    extra_backup = None
    try:
        from . import modeling_extras
        extra_backup = modeling_extras.ExtraBackup(candidate["steps"], editor)
    except ImportError:
        pass  # A host without the optional extra catalog uses the base kernels.
    try:
        backup = voice_sequence.Backup([obj for obj in objects if obj is not None])
    except Exception:
        if extra_backup is not None:
            extra_backup.close(False)
        raise
    outputs, final = {}, {"id": None}
    restored = False
    try:
        for step in candidate["steps"]:
            target_ref = step["target"]
            if isinstance(target_ref, dict):
                ref = outputs[target_ref["step"]][target_ref["output"]]
                oid = ref.get("id") if isinstance(ref, dict) else ref
            else:
                oid = target_ref
            target = editor.sync.find_object(oid) if oid else None
            selection = step["selection"]
            if "step" in selection:
                selection = outputs[selection["step"]][selection["output"]]
            selection = _selection({key: selection[key] for key in ("component", "indices")})
            result = modeling_tools.apply_step(editor, target, step["tool"], copy.deepcopy(step["params"]), selection, outputs)
            if not isinstance(result, dict):
                raise TypeError("A modeling kernel returned no typed result")
            outputs[step["id"]] = copy.deepcopy(result.get("outputs", {}))
            if "selection" in result:
                final = result["selection"] or {"id": None}
            bpy.context.view_layer.update()
    except Exception as exc:
        backup.restore()
        if extra_backup is not None:
            extra_backup.restore()
        restored = True
        if original_mode in {"EDIT_MESH", "POSE"} and bpy.context.view_layer.objects.active is not None:
            # Backup.restore also restores active selection, including an object
            # recreated after deletion. Never reuse an invalid pre-delete RNA ref.
            bpy.ops.object.mode_set(mode="EDIT" if original_mode == "EDIT_MESH" else "POSE")
            if original_mode == "EDIT_MESH":
                backup.restore_native_selection()
        if isinstance(exc, ValueError):
            raise commands.Refused("failed", "The complete recipe was restored: " + str(exc)) from exc
        raise
    finally:
        backup.close(restored)
        if extra_backup is not None:
            extra_backup.close(restored)
    return commands.Applied("AI recipe: " + candidate["label"], selection=copy.deepcopy(final) or {"id": None})

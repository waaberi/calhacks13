"""Native execution of a resolved voice plan inside Editor's single Undo wrapper.

Intermediate steps never flush or push history. A private in-memory backup restores
affected object/data/modifier state on failure; no file/window is saved or reopened.
"""

import copy

import bpy

from . import commands, edits, scene, sync, voice_composer, voice_ops


def _property_value(value):
    if isinstance(value, bpy.types.ID):
        return value
    if hasattr(value, "to_dict"):
        return {k: _property_value(v) for k, v in value.items()}
    if hasattr(value, "to_list"):
        return value.to_list()
    if isinstance(value, dict):
        return {k: _property_value(v) for k, v in value.items()}
    return copy.deepcopy(value)


def _rna_values(value):
    result = {}
    for prop in value.bl_rna.properties:
        if prop.identifier in {"rna_type", "name", "type"} or prop.is_readonly:
            continue
        v = getattr(value, prop.identifier)
        if prop.type == "COLLECTION":
            continue
        result[prop.identifier] = (
            ("__object_uid__", v.session_uid)
            if isinstance(v, bpy.types.Object)
            else tuple(v)
            if prop.is_array
            else v
        )
    return result


def _restore_rna(value, values, objects):
    for key, v in values.items():
        if isinstance(v, tuple) and len(v) == 2 and v[0] == "__object_uid__":
            v = objects.get(v[1])
        setattr(value, key, v)


def _custom_properties(value):
    try:
        return _property_value(dict(value.items()))
    except TypeError:
        return {}  # most fixed-type modifiers do not support IDProperties


class Backup:
    def __init__(self, objects):
        self.before_objects = {o.session_uid for o in bpy.data.objects}
        self.before_materials = {m.session_uid for m in bpy.data.materials}
        self.saved, self.data, self.clones = [], {}, []
        self.selection = edits._selection()
        self.used_clones = set()
        for obj in objects:
            data_uid = obj.data.session_uid if obj.data else None
            if data_uid is not None and data_uid not in self.data:
                self.data[data_uid] = (obj.data, obj.data.copy(), obj.data.name)
                self.data[data_uid][1].name = f".SpatialVoiceBackupData-{data_uid}"
            clone = obj.copy()
            clone.name = f".SpatialVoiceBackup-{obj.session_uid}"
            if data_uid is not None:
                clone.data = self.data[data_uid][1]
            self.clones.append(clone)
            self.before_objects.add(clone.session_uid)
            self.saved.append(
                {
                    "uid": obj.session_uid,
                    "object": obj,
                    "name": obj.name,
                    "clone": clone,
                    "collections": tuple(obj.users_collection),
                    "data": data_uid,
                    "channels": edits._channels(obj),
                    "parent": obj.parent.session_uid if obj.parent else None,
                    "props": _property_value(dict(obj.items())),
                    "colour": tuple(obj.color),
                    "modifiers": [
                        (m.name, m.type, _rna_values(m), _custom_properties(m))
                        for m in obj.modifiers
                    ],
                    "slots": [(slot.link, slot.material) for slot in obj.material_slots],
                }
            )

    def restore(self):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in list(bpy.data.objects):
            if obj.session_uid not in self.before_objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        live = {o.session_uid: o for o in bpy.data.objects}
        restored = {}
        for record in self.saved:
            obj = live.get(record["uid"])
            if obj is None:
                obj = record["clone"]
                self.used_clones.add(obj.session_uid)
                obj.name = record["name"]
                for collection in record["collections"]:
                    collection.objects.link(obj)
            restored[record["uid"]] = obj
        # Remap other users of backed-up shared data too.
        for original, backup, _ in self.data.values():
            for obj in bpy.data.objects:
                if obj.data == original:
                    obj.data = backup
        for record in self.saved:
            obj = restored[record["uid"]]
            if record["data"] is not None:
                obj.data = self.data[record["data"]][1]
            parent = record["parent"]
            obj.parent = restored.get(parent, live.get(parent)) if parent is not None else None
            edits._restore(obj, record["channels"])
            for key in list(obj.keys()):
                del obj[key]
            for key, value in record["props"].items():
                obj[key] = value
            obj.color = record["colour"]
            obj.modifiers.clear()
            for name, kind, values, custom in record["modifiers"]:
                modifier = obj.modifiers.new(name, kind)
                _restore_rna(modifier, values, {**live, **restored})
                for key, value in custom.items():
                    modifier[key] = value
            for slot, (link, material) in zip(obj.material_slots, record["slots"]):
                slot.link, slot.material = link, material
        for material in list(bpy.data.materials):
            if material.session_uid not in self.before_materials and material.users == 0:
                bpy.data.materials.remove(material)
        bpy.context.view_layer.update()
        edits._restore_selection(self.selection)

    def close(self, restored=False):
        for clone in self.clones:
            if clone.session_uid not in self.used_clones:
                bpy.data.objects.remove(clone, do_unlink=True)
        for original, backup, name in self.data.values():
            if restored:
                if original.users == 0:
                    bpy.data.batch_remove(ids=[original])
                    backup.name = name
            elif backup.users == 0:
                bpy.data.batch_remove(ids=[backup])
        edits._restore_selection(self.selection)


def _colour(obj, step):
    if obj.type != "MESH":
        raise commands.Refused("failed", "Colour needs a mesh object.")
    key = "spatial_voice_original_colour"
    if key not in obj:
        obj[key] = {
            "object": list(obj.color),
            "materials": [s.material.name if s.material else "" for s in obj.material_slots],
            "links": [s.link for s in obj.material_slots],
        }
    rgba = (
        voice_composer.COLOURS.get(step["colour"])
        if step.get("colour")
        else scene.color(obj) or tuple(obj.color)
    )
    if step.get("shade") == "lighter":
        rgba = tuple(v + (1 - v) * 0.2 for v in rgba[:3]) + (rgba[3],)
    elif step.get("shade") == "darker":
        rgba = tuple(v * 0.8 for v in rgba[:3]) + (rgba[3],)
    material = bpy.data.materials.new("Voice colour")
    material.diffuse_color = rgba
    material.use_nodes = True
    node = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if node is not None:
        node.inputs["Base Color"].default_value = rgba
    # Object-linked slots prevent colour changes on a shared mesh's other users.
    if not obj.material_slots:
        obj.data = obj.data.copy()
        obj.data.materials.append(material)
    for slot in obj.material_slots:
        slot.link = "OBJECT"
        slot.material = material
    obj.color = rgba
    if not edits._close(scene.color(obj), rgba):
        raise commands.Refused("failed", "Blender did not apply the requested colour.")


def _reset_colour(obj):
    key = "spatial_voice_original_colour"
    original = obj.get(key)
    if original is None:
        return
    names, links = list(original["materials"]), list(original["links"])
    if not names:
        obj.data = obj.data.copy()
        obj.data.materials.clear()
    else:
        if len(obj.material_slots) != len(names):
            raise commands.Refused(
                "failed", "The material slots changed since colouring; restore them in Blender."
            )
        for slot, name, link in zip(obj.material_slots, names, links, strict=True):
            material = bpy.data.materials.get(name) if name else None
            if name and material is None:
                raise commands.Refused(
                    "failed", "An original material was removed; reset colour cannot restore it."
                )
            slot.link, slot.material = link, material
    obj.color = original["object"]
    del obj[key]


def run(voice, candidate, editor):
    """Run every step without nested undo/publish. The caller owns commit/leases."""
    steps = candidate["steps"]
    objects = [voice.sync.find_object(i) for i in candidate["generations"]]
    if any(o is None for o in objects):
        raise commands.Refused("not_found", "A sequence target was deleted.")
    for obj in objects:
        if obj.library is not None or not obj.visible_get():
            raise commands.Refused(
                "failed", "A sequence target is hidden or linked from another file."
            )
    # Include linked-data users and children; native transform/delete dependencies are restored too.
    related = editor.linked(candidate["generations"])
    objects = list(
        {
            o.session_uid: o
            for o in objects + [voice.sync.find_object(i) for i in related]
            if o is not None
        }.values()
    )
    backup = Backup(objects)
    refs, created, removals = {}, [], []
    old_ids = {o.session_uid for o in bpy.context.view_layer.objects}
    restored = False
    try:
        for step in steps:
            ref = step.get("target")
            obj = (
                refs.get(ref)
                if ref and ref.startswith("new:")
                else voice.sync.find_object(ref)
                if ref
                else None
            )
            kind = step["kind"]
            if ref and (obj is None or obj in removals):
                raise commands.Refused("not_found", "A sequence target is unavailable.")
            if obj is not None and (obj.library is not None or not obj.visible_get()):
                raise commands.Refused("failed", "The step needs a visible local object.")
            if kind == "select":
                continue
            if kind in ("curated", "add_placed"):
                c = step["candidate"]
                target = None if c["needs"] is None else obj
                if c["needs"] == "MESH" and (target is None or target.type != "MESH"):
                    raise commands.Refused("failed", "This operation needs a mesh object.")
                weight = voice_ops._weight(bpy, scene, [target] if target else [])
                size = (
                    voice_ops._mesh_size(target)
                    if target and voice_ops.BY_ID[c["intent"]]["keep_size"]
                    else None
                )
                before = {o.session_uid for o in bpy.context.view_layer.objects}
                primitives = {
                    "add_cube": "cube",
                    "add_uv_sphere": "sphere",
                    "add_cylinder": "cylinder",
                }
                if c["intent"] in primitives:
                    # Match the existing VoiceCore Add defaults, including physical units.
                    editor._add(
                        None,
                        {
                            "primitive": primitives[c["intent"]],
                            "location": [0, 0, 0],
                            "dimensions": [0.05, 0.05, 0.05],
                        },
                        stage=True,
                    )
                else:
                    native_candidate = dict(c, post=dict(c["post"]))
                    for key in ("thickness", "width", "offset"):
                        if key in native_candidate["post"]:
                            native_candidate["post"][key] /= edits._unit()
                    voice_ops._execute(
                        bpy,
                        native_candidate,
                        target,
                        c["label"],
                        obj if target is None else None,
                        meters_per_unit=edits._unit(),
                    )
                added = [o for o in bpy.context.view_layer.objects if o.session_uid not in before]
                heavy = voice_ops._too_heavy(
                    bpy, scene, ([target] if target else []) + added, weight
                )
                if heavy or (size and voice_ops._shrunk(size, voice_ops._mesh_size(target))):
                    raise commands.Refused(
                        "failed", "A sequence step exceeds the voice geometry/size limits."
                    )
                if step.get("created"):
                    if len(added) != 1:
                        raise commands.Refused(
                            "failed", "This creation did not produce one unambiguous next target."
                        )
                    refs[step["created"]] = added[0]
                    if kind == "add_placed":
                        axis = "XYZ".index(step["axis"])
                        values = [0.0, 0.0, 0.0]
                        if step["absolute"]:
                            values = [v * edits._unit() for v in added[0].matrix_world.translation]
                            values[axis] = step["distance"]
                        else:
                            values[axis] = step["distance"]
                        editor._move(added[0], {"to" if step["absolute"] else "by": values})
            elif kind == "move":
                editor._move(obj, {"by": step["by"]})
            elif kind == "rotate":
                editor._rotate(obj, {"by": {"axis": step["axis"], "angle": step["angle"]}})
            elif kind == "scale":
                editor._scale(obj, {"by": step["by"]})
            elif kind == "duplicate":
                other = obj.copy()
                if obj.data is not None:
                    other.data = obj.data.copy()
                other.pop(sync.ID_PROPERTY, None)
                other.pop("spatial_voice_original_colour", None)
                for collection in obj.users_collection:
                    collection.objects.link(other)
                bpy.context.view_layer.update()
                editor._move(other, {"by": step["by"]})
                refs[step["created"]] = other
            elif kind == "dimension":
                edits._check_transformable(obj)
                axis = "XYZ".index(step["axis"])
                bpy.context.view_layer.update()
                before = tuple(obj.dimensions)
                if before[axis] <= 1e-12:
                    raise commands.Refused(
                        "failed", "A zero-size axis cannot be given an exact dimension."
                    )
                factors = [1.0, 1.0, 1.0]
                desired = step["distance"] / edits._unit()
                factors[axis] = desired / before[axis]
                editor._scale(obj, {"by": factors})
                bpy.context.view_layer.update()
                wanted = list(before)
                wanted[axis] = desired
                if not edits._close(obj.dimensions, wanted):
                    raise commands.Refused(
                        "failed",
                        "Blender could not set that dimension while preserving the others.",
                    )
            elif kind == "colour":
                _colour(obj, step)
            elif kind == "reset":
                if step["field"] == "colour":
                    _reset_colour(obj)
                elif step["field"] == "rotation":
                    from mathutils import Quaternion

                    edits._check_transformable(obj)
                    position, scale = tuple(obj.location), tuple(obj.scale)
                    edits._set_rotation(obj, Quaternion((1, 0, 0, 0)))
                    bpy.context.view_layer.update()
                    if (
                        abs(edits._rotation(obj).w) < 1 - 1e-5
                        or not edits._close(obj.location, position)
                        or not edits._close(obj.scale, scale)
                    ):
                        raise commands.Refused(
                            "failed", "Blender could not reset local rotation exactly."
                        )
                else:
                    # Reset signed local scale, retaining location/rotation; not Apply Scale.
                    factors = [1 / s if abs(s) > 1e-12 else 0 for s in obj.scale]
                    if 0 in factors:
                        raise commands.Refused("failed", "A zero scale cannot be reset.")
                    editor._scale(obj, {"by": factors})
            elif kind == "delete":
                removals.append(obj)  # irreversible removals wait until every other step succeeded
            else:
                raise commands.Refused("failed", "Unknown sequence step.")
        # Give all creations stable IDs inside the one Undo transaction.
        for obj in bpy.context.view_layer.objects:
            if obj.session_uid not in old_ids and obj not in removals:
                created.append(sync.stage_object_id(obj))
        for obj in removals:
            editor._delete(obj, {})
    except Exception:
        # Nothing was published and no history step was pushed. If rollback itself fails,
        # propagate an unknown outcome; Commands freezes/reconciles instead of lying.
        backup.restore()
        restored = True
        raise
    finally:
        backup.close(restored)
    final_ref = candidate.get("final_target")
    deleted_final = any(step["kind"] == "delete" and step["target"] == final_ref for step in steps)
    if final_ref is None or deleted_final:
        final_obj = None
    elif final_ref.startswith("new:"):
        final_obj = refs.get(final_ref)
    else:
        final_obj = voice.sync.find_object(final_ref)
    final_id = final_obj.get(sync.ID_PROPERTY) if final_obj is not None else None

    return commands.Applied(
        "Sequence: " + candidate["label"], created=created, selection={"id": final_id}
    )

"""Whole native Blender checkpoint capture and undoable main-thread application.

Document datablocks are imported intact. UI/runtime datablocks belong to this
Blender process and are never deleted or replaced. Received Text datablocks are
loaded as data through libraries.load; this module never executes them or enables
script auto-execution preferences.
"""
import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import bpy

UUID_PROPERTY = "spatial_native_uuid"
_KEEPALIVE = "spatial_native_checkpoint_fake_user"
MANIFEST_GROUPS = frozenset({
    "actions", "annotations", "armatures", "brushes", "cache_files", "cameras", "collections",
    "curves", "fonts", "grease_pencils", "hair_curves", "images", "lattices", "lightprobes",
    "lights", "linestyles", "masks", "materials", "meshes", "metaballs", "movieclips",
    "node_groups", "objects", "paint_curves", "palettes", "particles", "pointclouds", "scenes",
    "shape_keys", "sounds", "speakers", "texts", "textures", "volumes", "worlds",
})
_UUID = re.compile(r"[0-9a-f]{32}\Z")
_active = None
_PASSIVE_MODAL_OPERATORS = frozenset({"SPATIAL_MODELING_OT_input_gate"})


class NativeDocumentError(RuntimeError):
    """Checkpoint data cannot safely replace this native document."""


class NativeDocumentBusy(NativeDocumentError):
    """An active native operation must finish before a checkpoint transaction."""


@dataclass(frozen=True)
class Snapshot:
    data: bytes
    sha256: str
    manifest: dict
    active_scene_uuid: str


def _ids():
    return {group: list(getattr(bpy.data, group)) for group in sorted(MANIFEST_GROUPS)
            if hasattr(bpy.data, group)}


def _pointer_map():
    return {item.as_pointer(): item for items in _ids().values() for item in items}


def _alive(item):
    try:
        item.as_pointer()
        _ = item.name
    except ReferenceError:
        return False
    return True


def _modal_busy():
    return any(op.bl_idname not in _PASSIVE_MODAL_OPERATORS
               for window in bpy.context.window_manager.windows
               for op in getattr(window, "modal_operators", ()))


def _validate_manifest(manifest):
    if not isinstance(manifest, dict) or not manifest:
        raise NativeDocumentError("Checkpoint has no native identity manifest")
    for identity, entry in manifest.items():
        if not isinstance(identity, str) or not _UUID.fullmatch(identity):
            raise NativeDocumentError("Checkpoint has an invalid native identity")
        if (not isinstance(entry, dict) or set(entry) != {"group", "name"}
                or entry["group"] not in MANIFEST_GROUPS
                or not isinstance(entry["name"], str) or not entry["name"]
                or len(entry["name"]) > 1024):
            raise NativeDocumentError("Checkpoint has an invalid native datablock record")


def _validate_script_drivers(items):
    # Simple mathematical/property drivers are native data. A general Python
    # expression depends on the receiving user's script trust and must never
    # execute merely because another participant supplied a checkpoint.
    visited = set()
    for item in items:
        for block in (item, getattr(item, "node_tree", None)):
            if block is None or block.as_pointer() in visited:
                continue
            visited.add(block.as_pointer())
            animation = getattr(block, "animation_data", None)
            if animation is None:
                continue
            for curve in animation.drivers:
                driver = curve.driver
                if driver.type == "SCRIPTED" and not driver.is_simple_expression:
                    raise NativeDocumentError("Checkpoint contains a driver requiring trusted Python execution")


def _validate_file(path):
    path = Path(path).resolve()
    if path.suffix.lower() != ".blend" or not path.is_file():
        raise NativeDocumentError("Checkpoint must be an existing native .blend file")
    with path.open("rb") as source:
        header = source.read(17)
    legacy = re.match(rb"BLENDER[_-][vV][0-9]{3}", header)
    extended = re.fullmatch(rb"BLENDER17-01[vV][0-9]{4}", header)
    if legacy is None and extended is None:
        raise NativeDocumentError("Checkpoint is not an uncompressed native Blender document")
    return path


class NativeDocument:
    def __init__(self, schedule=None):
        self._transaction = None
        self._schedule = schedule or (lambda callback, delay: bpy.app.timers.register(
            callback, first_interval=delay))

    @property
    def busy(self):
        return self._transaction is not None or _active is not None

    @staticmethod
    def is_idle():
        """No native modal tool is running, and all edited objects are in Object Mode."""
        if _modal_busy():
            return False
        return not any(obj.mode != "OBJECT" for obj in bpy.data.objects)

    def capture(self, path):
        if self.busy or _modal_busy():
            raise NativeDocumentBusy("Finish the active native operation before sharing a checkpoint")
        if bpy.data.libraries:
            raise NativeDocumentError("Make externally linked libraries local before sharing this document")
        path = Path(path).resolve()
        if path.suffix.lower() != ".blend":
            raise NativeDocumentError("A checkpoint output must use the .blend extension")
        if bpy.data.filepath and path == Path(bpy.data.filepath).resolve():
            raise NativeDocumentError("Checkpoint output cannot overwrite the user's current file")
        path.parent.mkdir(parents=True, exist_ok=True)
        for obj in bpy.data.objects:
            if obj.mode == "EDIT":
                obj.update_from_editmode()
        bpy.context.view_layer.update()
        manifest = {}
        keepalive = []
        seen = set()
        original_path = bpy.data.filepath
        try:
            for group, items in _ids().items():
                for item in items:
                    identity = item.get(UUID_PROPERTY)
                    if not isinstance(identity, str) or not _UUID.fullmatch(identity) or identity in seen:
                        identity = uuid.uuid4().hex
                        item[UUID_PROPERTY] = identity
                    seen.add(identity)
                    manifest[identity] = {"group": group, "name": item.name}
                    if item.users == 0 and not item.use_fake_user:
                        item[_KEEPALIVE] = False
                        item.use_fake_user = True
                        keepalive.append(item)
            active_scene_uuid = bpy.context.scene.get(UUID_PROPERTY)
            result = bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True, compress=False,
                                                relative_remap=False)
            if result != {"FINISHED"} or bpy.data.filepath != original_path:
                raise NativeDocumentError("Native checkpoint copy did not preserve the current file")
            data = path.read_bytes()
            _validate_file(path)
            return Snapshot(data, hashlib.sha256(data).hexdigest(), manifest, active_scene_uuid)
        finally:
            for item in keepalive:
                if _alive(item):
                    item.use_fake_user = False
                    if _KEEPALIVE in item:
                        del item[_KEEPALIVE]

    def apply(self, path, manifest, on_done, on_error, active_scene_uuid=None):
        global _active
        if self.busy or not self.is_idle():
            raise NativeDocumentBusy("Finish the active native operation before receiving a checkpoint")
        if not bpy.context.preferences.edit.use_global_undo:
            raise NativeDocumentError("Native global Undo must be enabled for atomic checkpoint application")
        path = _validate_file(path)
        _validate_manifest(manifest)
        if active_scene_uuid is not None and (active_scene_uuid not in manifest
                or manifest[active_scene_uuid]["group"] != "scenes"):
            raise NativeDocumentError("Checkpoint active scene is not in its native manifest")
        old = _pointer_map()
        old_windows = [(window, window.scene) for window in bpy.context.window_manager.windows]
        transaction = {"old": old, "windows": old_windows, "new": {}, "removed": False,
                       "manifest": manifest, "done": on_done, "error": on_error,
                       "active_scene_uuid": active_scene_uuid}
        self._transaction = transaction
        _active = self
        try:
            bpy.ops.ed.undo_push(message="Before shared native checkpoint")
            with bpy.data.libraries.load(str(path), link=False) as (source, target):
                if source.libraries:
                    raise NativeDocumentError("Received checkpoint contains externally linked libraries")
                for group in sorted(MANIFEST_GROUPS):
                    if hasattr(source, group):
                        setattr(target, group, list(getattr(source, group)))
            transaction["new"] = {ptr: item for ptr, item in _pointer_map().items() if ptr not in old}
            _validate_script_drivers(transaction["new"].values())
            actual_groups = {item.as_pointer(): group for group, items in _ids().items() for item in items}
            found = {item.get(UUID_PROPERTY): item for item in transaction["new"].values()}
            missing = set(manifest) - found.keys()
            if missing:
                raise NativeDocumentError("Checkpoint did not restore every original native datablock")
            if any(actual_groups[found[identity].as_pointer()] != entry["group"]
                   for identity, entry in manifest.items()):
                raise NativeDocumentError("Checkpoint native identity has the wrong datablock type")
            scenes = {item.get(UUID_PROPERTY): item for item in transaction["new"].values()
                      if isinstance(item, bpy.types.Scene)}
            if not scenes:
                raise NativeDocumentError("Checkpoint contains no native scene")
            chosen = scenes.get(active_scene_uuid) or next(iter(scenes.values()))
            for window, previous in old_windows:
                window.scene = scenes.get(previous.get(UUID_PROPERTY), chosen)
            self._schedule(self._remove_old, .02)
        except Exception as error:  # noqa: BLE001 - transaction cleanup owns every staged native ID
            transaction["new"] = {ptr: item for ptr, item in _pointer_map().items() if ptr not in old}
            self._fail(error)

    apply_async = apply

    def _remove_old(self):
        try:
            transaction = self._transaction
            current = _pointer_map()
            bpy.data.batch_remove(ids={current[ptr] for ptr in transaction["old"] if ptr in current})
            transaction["removed"] = True
            self._schedule(self._finish, .02)
        except Exception as error:  # noqa: BLE001 - preserve the pre-transaction undo checkpoint
            self._fail(error)

    def _finish(self):
        try:
            transaction = self._transaction
            manifest = transaction["manifest"]
            for item in transaction["new"].values():
                identity = item.get(UUID_PROPERTY)
                if identity in manifest:
                    item.name = manifest[identity]["name"]
                if _KEEPALIVE in item:
                    item.use_fake_user = bool(item[_KEEPALIVE])
                    del item[_KEEPALIVE]
            bpy.context.view_layer.update()
            bpy.ops.ed.undo_push(message="Shared native checkpoint")
            report = {"datablocks": len(manifest),
                      "active_scene_uuid": bpy.context.scene.get(UUID_PROPERTY)}
            callback = transaction["done"]
            self._clear()
            callback(report)
        except Exception as error:  # noqa: BLE001 - rollback failures never masquerade as apply success
            self._fail(error)

    def _clear(self):
        global _active
        self._transaction = None
        if _active is self:
            _active = None

    def _fail(self, error):
        transaction = self._transaction
        if transaction is None:
            return
        transaction["failure"] = error
        if transaction["removed"]:
            try:
                bpy.ops.ed.undo_push(message="Failed native checkpoint rollback")
                bpy.ops.ed.undo()
            except RuntimeError as rollback_error:
                error = NativeDocumentError(str(error) + "; native rollback failed: " + str(rollback_error))
            callback = transaction["error"]
            self._clear()
            callback(error)
            return
        for window, previous in transaction["windows"]:
            if _alive(previous):
                window.scene = previous
        self._schedule(self._discard_staged, .02)

    def _discard_staged(self):
        transaction = self._transaction
        error = transaction["failure"]
        try:
            current = _pointer_map()
            bpy.data.batch_remove(ids={current[ptr] for ptr in transaction["new"] if ptr in current})
        except RuntimeError as cleanup_error:
            error = NativeDocumentError(str(error) + "; staged cleanup failed: " + str(cleanup_error))
        callback = transaction["error"]
        self._clear()
        callback(error)

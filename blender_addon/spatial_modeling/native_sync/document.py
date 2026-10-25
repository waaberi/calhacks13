"""Whole native Blender checkpoint capture and undoable main-thread application.

Document datablocks are imported intact. UI/runtime datablocks belong to this
Blender process and are never deleted or replaced. Received Text datablocks are
loaded as data through libraries.load; this module never executes them or enables
script auto-execution preferences.
"""
import hashlib
import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import bpy

from .fingerprint import FingerprintError, document_fingerprint

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
_LOG = logging.getLogger(__name__)
_PASSIVE_MODAL_OPERATORS = frozenset({"SPATIAL_MODELING_OT_input_gate"})


class NativeDocumentError(RuntimeError):
    """Checkpoint data cannot safely replace this native document."""


class NativeDocumentCancelled(NativeDocumentError):
    """A user document load superseded a pending checkpoint transaction."""


class NativeDocumentBusy(NativeDocumentError):
    """An active native operation must finish before a checkpoint transaction."""


@dataclass(frozen=True)
class Snapshot:
    data: bytes
    sha256: str
    manifest: dict
    active_scene_uuid: str
    document_hash: str = ""

    def __post_init__(self):
        if not self.document_hash:
            object.__setattr__(self, "document_hash", self.sha256)


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


def _validate_portable_assets(items):
    for item in items:
        if isinstance(item, bpy.types.Image):
            if item.type in {"RENDER_RESULT", "COMPOSITING"}:
                continue
            packed = bool(item.packed_file)
            if item.source == "TILED":
                packed = len(item.packed_files) >= len(item.tiles) > 0
            if not packed:
                raise NativeDocumentError("Pack image resources before sharing this native document")
        elif isinstance(item, bpy.types.Sound) and not item.packed_file:
            raise NativeDocumentError("Pack sound resources before sharing this native document")
        elif isinstance(item, bpy.types.VectorFont):
            if item.filepath not in {"", "<builtin>"} and not item.packed_file:
                raise NativeDocumentError("Pack font resources before sharing this native document")
        elif isinstance(item, (bpy.types.MovieClip, bpy.types.CacheFile, bpy.types.Volume)):
            if getattr(item, "filepath", ""):
                raise NativeDocumentError("External movie, cache and volume assets need a separate resource transfer")


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
        self._identities = {}
        self._schedule = schedule or (lambda callback, delay: bpy.app.timers.register(
            callback, first_interval=delay))

    @property
    def busy(self):
        return self._transaction is not None or _active is not None

    def can_capture(self):
        """An author may checkpoint completed Edit Mode work without leaving Edit Mode."""
        return not self.busy and not _modal_busy()

    @staticmethod
    def is_empty_session():
        """Initial replacement is allowed only before this separate session has user objects/file."""
        return not bpy.data.filepath and len(bpy.data.objects) == 0

    @staticmethod
    def is_idle():
        """No native modal tool is running, and all edited objects are in Object Mode."""
        if _modal_busy():
            return False
        return not any(obj.mode != "OBJECT" for obj in bpy.data.objects)

    def capture(self, path):
        if not self.can_capture():
            raise NativeDocumentBusy("Finish the active native operation before sharing a checkpoint")
        if any(item.library is not None for item in _pointer_map().values()):
            raise NativeDocumentError("Make externally linked libraries local before sharing this document")
        _validate_portable_assets(_pointer_map().values())
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
            records = [(group, item) for group, items in _ids().items() for item in items]
            counts = Counter(item.get(UUID_PROPERTY) for _, item in records
                             if isinstance(item.get(UUID_PROPERTY), str))
            reserved = {self._identities[(group, item.session_uid)] for group, item in records
                        if (group, item.session_uid) in self._identities}
            # Native Duplicate copies ID properties. Previously known session IDs
            # keep their UUID even when a new copy sorts before them by name.
            records.sort(key=lambda pair: (pair[0], pair[1].session_uid) not in self._identities)
            for group, item in records:
                key = (group, item.session_uid)
                identity = self._identities.get(key)
                if identity is None:
                    identity = item.get(UUID_PROPERTY)
                    if isinstance(identity, str) and counts.get(identity, 0) > 1 and identity not in reserved:
                        identity = None
                if not isinstance(identity, str) or not _UUID.fullmatch(identity) or identity in seen:
                    identity = uuid.uuid4().hex
                if item.get(UUID_PROPERTY) != identity:
                    item[UUID_PROPERTY] = identity
                self._identities[key] = identity
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
            model_path = path.with_name(path.stem + ".document.blend")
            bpy.data.libraries.write(str(model_path), set(_pointer_map().values()),
                                     path_remap="NONE", fake_user=False, compress=False)
            try:
                model_hash = document_fingerprint(model_path.read_bytes())
            except FingerprintError as error:
                raise NativeDocumentError("Native model fingerprint could not be verified: " + str(error)) from error
            return Snapshot(data, hashlib.sha256(data).hexdigest(), manifest, active_scene_uuid, model_hash)
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
        transaction = {"old": old, "old_session_ids": {ptr: item.session_uid for ptr, item in old.items()},
                       "windows": old_windows, "new": {}, "removed": False,
                       "manifest": manifest, "done": on_done, "error": on_error,
                       "active_scene_uuid": active_scene_uuid}
        self._transaction = transaction
        _active = self
        try:
            bpy.ops.ed.undo_push(message="Before shared native checkpoint")
            with bpy.data.libraries.load(str(path), link=False) as (source, target):
                for group in sorted(MANIFEST_GROUPS):
                    if hasattr(source, group):
                        setattr(target, group, list(getattr(source, group)))
            transaction["new"] = {ptr: item for ptr, item in _pointer_map().items() if ptr not in old}
            if any(item.library is not None for item in transaction["new"].values()):
                raise NativeDocumentError("Received checkpoint contains externally linked datablocks")
            _validate_portable_assets(transaction["new"].values())
            _validate_script_drivers(transaction["new"].values())
            actual_groups = {item.as_pointer(): group for group, items in _ids().items() for item in items}
            found = {item.get(UUID_PROPERTY): item for item in transaction["new"].values()}
            if len(found) != len(transaction["new"]) or None in found:
                raise NativeDocumentError("Checkpoint contains duplicate or missing native identities")
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
            transaction["new_scenes"] = {item.as_pointer() for item in scenes.values()}
            chosen = scenes.get(active_scene_uuid) or next(iter(scenes.values()))
            for window, previous in old_windows:
                window.scene = scenes.get(previous.get(UUID_PROPERTY), chosen)
            self._schedule(self._remove_old, .02)
        except Exception as error:  # noqa: BLE001 - transaction cleanup owns every staged native ID
            transaction["new"] = {ptr: item for ptr, item in _pointer_map().items() if ptr not in old}
            self._fail(error)

    apply_async = apply

    def _remove_old(self):
        transaction = self._transaction
        if transaction is None:
            return
        try:
            if any(window.scene.as_pointer() not in transaction["new_scenes"]
                   for window in bpy.context.window_manager.windows):
                raise NativeDocumentCancelled("The active native scene changed before checkpoint application")
            current = _pointer_map()
            bpy.data.batch_remove(ids={current[ptr] for ptr, session_id in transaction["old_session_ids"].items()
                if ptr in current and current[ptr].session_uid == session_id})
            transaction["removed"] = True
            self._schedule(self._finish, .02)
        except Exception as error:  # noqa: BLE001 - preserve the pre-transaction undo checkpoint
            self._fail(error)

    def _finish(self):
        transaction = self._transaction
        if transaction is None:
            return
        try:
            manifest = transaction["manifest"]
            for item in transaction["new"].values():
                identity = item.get(UUID_PROPERTY)
                if identity in manifest:
                    item.name = manifest[identity]["name"]
                if _KEEPALIVE in item:
                    item.use_fake_user = bool(item[_KEEPALIVE])
                    del item[_KEEPALIVE]
            for group, items in _ids().items():
                for item in items:
                    self._identities[(group, item.session_uid)] = item.get(UUID_PROPERTY)
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
        windows = {window.as_pointer(): window for window in bpy.context.window_manager.windows}
        for window, previous in transaction["windows"]:
            try:
                current_window = windows.get(window.as_pointer())
            except ReferenceError:
                current_window = None
            if current_window is not None and _alive(previous):
                current_window.scene = previous
        self._schedule(self._discard_staged, .02)

    def _discard_staged(self):
        transaction = self._transaction
        if transaction is None:
            return
        error = transaction["failure"]
        try:
            current = _pointer_map()
            bpy.data.batch_remove(ids={current[ptr] for ptr in transaction["new"] if ptr in current})
        except RuntimeError as cleanup_error:
            error = NativeDocumentError(str(error) + "; staged cleanup failed: " + str(cleanup_error))
        callback = transaction["error"]
        self._clear()
        callback(error)


@bpy.app.handlers.persistent
def _before_file_load(_unused):
    # A real File Open/Revert owns the new document. Pending callbacks must not
    # inspect, delete or roll back any IDs once its load begins.
    document = _active
    if document is None or document._transaction is None:
        return
    callback = document._transaction["error"]
    document._clear()
    try:
        callback(NativeDocumentCancelled("A document load canceled the pending native checkpoint"))
    except Exception:  # noqa: BLE001 - a callback must never prevent the user's document load
        _LOG.exception("Native checkpoint cancellation callback failed during document load")


if _before_file_load not in bpy.app.handlers.load_pre:
    bpy.app.handlers.load_pre.append(_before_file_load)

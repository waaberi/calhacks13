"""Scene sync on the host: stable object IDs, change observation and live scene.update.

Implements "Scene" and "Identity, revisions and units" in contracts/README.md.
host.py starts it with each server (one Document, so one open epoch), polls it
from its drain timer, and gives Session describe() and snapshot() for hello.
scene.py serializes single objects; this module decides what changed.

Interface for the command path (P3A). Main thread only, like all bpy work:

flush() -> int
    Detect every change not sent yet, broadcast it to every client as one
    scene.update (a scene.snapshot after a unit change), and return the current
    revision; the same revision if nothing changed. Call it after a successful
    mutation and before replying `result`, so clients get scene.update, then the
    sender result, then the others activity. The receipt's `revision` is its
    return value. It raises if serialization fails: the outcome is then unknown.
generation(object_id) -> int | None
    The object's generation (the revision at which it last changed) after a
    flush(), or None if no synced object has this ID. Compare it with
    command.target.generation for not_found and stale_revision.
find_object(object_id) -> bpy.types.Object | None
    The synced object with this ID, or None. Look it up again for every command:
    Undo, Redo and file loads replace data-blocks, so references go stale.
object_id(obj) -> str
    The object's ID, given now if it has none yet: for a receipt's `created`.

Which objects: those of the current view layer. Objects in excluded collections
count as removed; hidden ones are sent with `visible` false. Instances
(collection instances, geometry-nodes instances) aren't sent yet.

IDs live in the custom property spatial_modeling_id. Missing or invalid ones
get a new UUID; when several objects carry the same ID (Duplicate copies the
property), the object that had it before keeps it and the others get new ones.
IDs are written outside any Undo step, so an Undo can take the property away
again: the ID given to each object (by its session_uid, which survives
Undo/Redo) is remembered until the next file load and given back.

Change observation: depsgraph_update_post marks the scene as changed and notes
whose geometry changed; undo_post and redo_post mark everything, since Undo
replaces data-blocks. A flush looks every object up again, diffs its record
(name, parent, visibility, transform, color) with what clients have, and
re-evaluates only meshes that may have changed, comparing them by digest. An
update leaves out `mesh` when the mesh didn't change. poll() flushes at most
every MIN_INTERVAL, and waits COST_FACTOR times as long as the last flush took,
so a drag in Blender streams small updates and a heavy mesh can't stall
Blender. It also diffs every RESCAN_INTERVAL as a safety net. A flush that
finds nothing different sends nothing, so our own writes (the IDs) can't loop.
"""

import json
import logging
import re
import time
import uuid

import bpy
from bpy.app.handlers import persistent

from . import document, protocol, scene

ID_PROPERTY = "spatial_modeling_id"
MIN_INTERVAL = 0.05  # s between flushes from poll(): at most 20 scene.updates a second
COST_FACTOR = 3  # and 3x the last flush's duration, so sync uses at most 1/4 of the main thread
RESCAN_INTERVAL = 1.0  # s; poll() diffs this often even without a depsgraph update
RETRY_INTERVAL = 1.0  # s before poll() tries again after a failed flush
FIT_BYTES = protocol.MAX_LINE_BYTES - 64 * 1024  # room for the envelope and document

_UUID = re.compile(r"[0-9a-f]{32}")
log = logging.getLogger(__name__)

_state = None  # the running _Sync, between start() and stop()
_assigned = {}  # session_uid -> the ID we gave that object; cleared when a file loads


class _Entry:
    """One object as clients have it."""

    __slots__ = ("generation", "mesh", "record", "uid")

    def __init__(self, record, mesh, generation, uid):
        self.record = record  # scene.record(): everything but generation and mesh
        self.mesh = mesh  # scene.Mesh or None
        self.generation = generation
        self.uid = uid  # the object's session_uid when we last saw it

    def wire(self, with_mesh):
        """The object in scene.snapshot.schema.json's order; `mesh` only if with_mesh."""
        r = self.record
        out = {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "parent": r["parent"],
            "generation": self.generation,
            "visible": r["visible"],
            "transform": r["transform"],
            "color": r["color"],
        }
        if with_mesh:
            out["mesh"] = self.mesh.wire() if self.mesh is not None else None
        return out


class _Sync:
    def __init__(self, doc, session):
        self.document = doc  # document.Document; its revision is the counter
        self.session = session  # broadcast(msg) reaches every welcomed client
        self.objects = {}  # ID -> _Entry, as of the last flush
        self.started = False  # the first flush only records the scene, at revision 0
        self.pending = True  # something may have changed since the last flush
        self.full = True  # re-evaluate every mesh (after Undo/Redo or a unit change)
        self.dirty = set()  # session_uids of objects and data whose geometry changed
        self.units = None
        self.sent = None  # (name, dirty) of the document as last sent
        self.flushing = False
        self.next_flush = 0.0  # time.monotonic() before which poll() doesn't flush
        self.next_rescan = 0.0


def start(doc, session):
    """Start tracking the scene for a new server: revision 0, nothing sent yet."""
    global _state
    _state = _Sync(doc, session)


def stop():
    global _state
    _state = None


def _valid_id(value):
    return value if isinstance(value, str) and _UUID.fullmatch(value) else None


def _give_id(obj, taken):
    """Give obj an ID nobody in `taken` has, preferring the one it had before an Undo."""
    oid = _assigned.get(obj.session_uid)
    if oid is None or oid in taken:
        oid = uuid.uuid4().hex
        _assigned[obj.session_uid] = oid
    taken.add(oid)
    try:
        obj[ID_PROPERTY] = oid
    except (AttributeError, TypeError, RuntimeError, ValueError):
        pass  # linked from a library: the remembered ID lasts until the file reloads
    return oid


def _identify(st, objects):
    """[(ID, object)] with a unique, valid ID for each object; writes the IDs it gives."""
    holders = {}
    for obj in objects:
        holders.setdefault(_valid_id(obj.get(ID_PROPERTY)), []).append(obj)
    taken = set(holders) - {None}
    result = []
    for oid, group in holders.items():
        if oid is None:
            result.extend((_give_id(obj, taken), obj) for obj in group)
            continue
        if len(group) > 1:  # duplicated: the object that had the ID keeps it
            entry = st.objects.get(oid)
            keep = (
                next((o for o in group if entry is not None and o.session_uid == entry.uid), None)
                or next((o for o in group if _assigned.get(o.session_uid) == oid), None)
                or min(group, key=lambda o: o.name)
            )
            for obj in group:
                if obj.session_uid != keep.session_uid:
                    result.append((_give_id(obj, taken), obj))
            group = [keep]
        result.append((oid, group[0]))
    return result


def _ordered(entries):
    """IDs with every parent before its children, siblings by name."""
    children, roots = {}, []
    for oid, entry in entries.items():
        parent = entry.record["parent"]
        (children.setdefault(parent, []) if parent in entries else roots).append(oid)

    def key(oid):
        return entries[oid].record["name"], oid

    out, stack = [], sorted(roots, key=key, reverse=True)
    while stack:
        oid = stack.pop()
        out.append(oid)
        stack.extend(sorted(children.get(oid, ()), key=key, reverse=True))
    return out


def _same_mesh(a, b):
    if a is None or b is None:
        return a is b
    return a.digest == b.digest


def _size(value):
    text = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return len(text.encode("utf-8"))


def _estimate(objects):
    """An upper bound of the objects' JSON size, without encoding them."""
    size = 4096
    for obj in objects:
        size += 1024
        mesh = obj.get("mesh")
        if mesh:
            size += 12 * len(mesh["positions"]) + 10 * len(mesh["normals"])
            size += 8 * len(mesh["indices"])
    return size


def _fit(payload):
    """Make the payload fit in one line by sending the biggest meshes as null. Rare.

    The contract limits a line to 16 MiB (roughly 90,000 triangles in a
    snapshot). Each object left without its mesh is logged.
    """
    objects = payload["objects"]
    if _estimate(objects) <= FIT_BYTES:
        return payload
    while _size(payload) > FIT_BYTES:
        meshes = [o for o in objects if o.get("mesh")]
        if not meshes:
            break  # protocol.encode will refuse it
        biggest = max(meshes, key=lambda o: len(o["mesh"]["positions"]) + len(o["mesh"]["indices"]))
        text = (f"Spatial Modeling: {biggest['name']}'s mesh ({len(biggest['mesh']['indices']) // 3} "
                "triangles) is too large to send; clients get it without a mesh")
        print(text)
        log.warning(text)
        biggest["mesh"] = None
    return payload


def _snapshot_payload(st, doc):
    objects = [st.objects[oid].wire(True) for oid in _ordered(st.objects)]
    return _fit({"document": doc, "objects": objects, "sketches": []})  # sketches: P3C


def _document_state(doc):
    return doc["name"], doc["dirty"]


def _flush(st):
    depsgraph = bpy.context.evaluated_depsgraph_get()  # evaluates; our handler notes changes
    full, dirty = st.full or not st.started, st.dirty
    st.pending = st.full = False
    st.dirty = set()
    scn = scene.current_scene()
    view_layer = scene.current_view_layer(scn)
    units = document.units(scn)
    scale = units["scale_length"]
    resnapshot = st.started and units != st.units  # every position changed: send everything
    full = full or resnapshot

    ids = _identify(st, view_layer.objects)
    id_of = {obj.session_uid: oid for oid, obj in ids}
    current = {}
    for oid, obj in ids:
        parent = obj.parent
        parent_id = id_of.get(parent.session_uid) if parent is not None else None
        record = scene.record(obj, oid, parent_id, view_layer, depsgraph, scale)
        old = st.objects.get(oid)
        data = obj.data
        stale = (
            full
            or old is None
            or old.record["type"] != record["type"]
            or obj.session_uid in dirty
            or (data is not None and data.session_uid in dirty)
        )
        mesh = old.mesh if old is not None else None
        if stale:
            try:
                mesh = scene.evaluated_mesh(obj, depsgraph, scale)
            except Exception:  # one odd object must not stop the sync of all the others
                log.exception("could not read %s's mesh; clients keep the last one", obj.name)
        current[oid] = _Entry(record, mesh, old.generation if old else 0, obj.session_uid)

    if not st.started:  # what the file had when the server started is revision 0
        st.objects, st.units, st.started = current, units, True
        st.sent = _document_state(st.document.describe())
        return

    changed = []  # (ID, with_mesh)
    for oid, entry in current.items():
        old = st.objects.get(oid)
        if old is None:
            changed.append((oid, True))
            continue
        new_mesh = not _same_mesh(old.mesh, entry.mesh)
        if new_mesh or entry.record != old.record:
            changed.append((oid, new_mesh))
    removed = [oid for oid in st.objects if oid not in current]
    if resnapshot or changed or removed:
        st.document.revision += 1
        touched = current if resnapshot else {oid for oid, _ in changed}
        for oid in touched:
            current[oid].generation = st.document.revision
    st.objects, st.units = current, units

    doc = st.document.describe()
    if resnapshot:
        msg = protocol.message("scene.snapshot", _snapshot_payload(st, doc))
    elif changed or removed or _document_state(doc) != st.sent:
        order = {oid: i for i, oid in enumerate(_ordered(current))}
        changed.sort(key=lambda c: order[c[0]])
        objects = [current[oid].wire(with_mesh) for oid, with_mesh in changed]
        payload = {"document": doc, "objects": objects, "sketches": [], "removed": removed}
        msg = protocol.message("scene.update", _fit(payload))
    else:
        return
    st.sent = _document_state(doc)
    st.session.broadcast(msg)


def flush():
    """Send every change not sent yet as one scene.update; return the current revision.

    See the module docstring. Returns 0 while the host isn't running.
    """
    st = _state
    if st is None:
        return 0
    if st.flushing:  # re-entered, for example from a handler during evaluation
        return st.document.revision
    st.flushing = True
    started = time.monotonic()
    try:
        _flush(st)
    except Exception:
        st.pending = st.full = True  # start over next time
        raise
    finally:
        st.flushing = False
        done = time.monotonic()
        st.next_flush = done + max(MIN_INTERVAL, COST_FACTOR * (done - started))
        st.next_rescan = done + RESCAN_INTERVAL
    return st.document.revision


def poll():
    """Flush if something changed and the last flush was long enough ago. host.py's timer."""
    st = _state
    if st is None or st.flushing:
        return
    now = time.monotonic()
    if not st.pending and now < st.next_rescan:
        if st.sent is None or bpy.data.is_dirty == st.sent[1]:
            return
        st.pending = True  # saved, or an Undo step was pushed after a flush
    if now < st.next_flush:
        return
    try:
        flush()
    except Exception:
        log.exception("scene sync failed")
        st.next_flush = time.monotonic() + RETRY_INTERVAL


def describe():
    """The open document for `welcome`, after a flush, so the snapshot that follows matches."""
    if _state is None:
        raise RuntimeError("scene sync is not running")
    flush()
    return _state.document.describe()


def snapshot(doc):
    """The scene.snapshot payload: every object as of the last flush. Session's hello calls it."""
    st = _state
    if st is None:
        return {"document": doc, "objects": [], "sketches": []}
    return _snapshot_payload(st, doc)


def generation(object_id):
    """The object's generation as of now, or None if no synced object has this ID."""
    if _state is None:
        return None
    flush()
    entry = _state.objects.get(object_id)
    return entry.generation if entry is not None else None


def find_object(object_id):
    """The synced object with this ID in the current view layer, or None."""
    entry = _state.objects.get(object_id) if _state is not None else None
    view_layer = scene.current_view_layer(scene.current_scene())
    match = None
    for obj in view_layer.objects:
        if entry is not None and obj.session_uid == entry.uid:
            return obj  # the same object, even if an Undo took its ID property away
        if match is None and obj.get(ID_PROPERTY) == object_id:
            match = obj
    return match


def object_id(obj):
    """The object's ID, given now (with a flush) if it has none yet."""
    uid = obj.session_uid
    if _state is not None:
        for _ in range(2):
            for oid, entry in _state.objects.items():
                if entry.uid == uid:
                    return oid
            if _state.flushing:
                break
            flush()  # a new object: give it its ID and tell the clients
    oid = _valid_id(obj.get(ID_PROPERTY))  # not in the view layer, or sync isn't running
    return oid or _give_id(obj, set())


@persistent
def _on_depsgraph_update(_scene, depsgraph):
    st = _state
    if st is None:
        return
    st.pending = True
    for update in depsgraph.updates:
        if update.is_updated_geometry:
            st.dirty.add(update.id.original.session_uid)


@persistent
def _on_undo_redo(*_args):
    st = _state
    if st is not None:
        st.pending = st.full = True  # data-blocks were replaced: look everything up again
        st.next_flush = 0.0  # show the Undo at once, even mid-drag


@persistent
def _on_save_pre(*_args):
    st = _state
    if st is not None:  # an Undo may have taken IDs away; save them with the file
        _identify(st, scene.current_view_layer(scene.current_scene()).objects)


@persistent
def _on_save_post(*_args):
    if _state is not None:
        _state.pending = True  # the dirty flag (and maybe the file name) changed


@persistent
def _on_load_pre(*_args):
    _assigned.clear()  # session_uids start over in the next file


_HANDLERS = (
    (bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update),
    (bpy.app.handlers.undo_post, _on_undo_redo),
    (bpy.app.handlers.redo_post, _on_undo_redo),
    (bpy.app.handlers.save_pre, _on_save_pre),
    (bpy.app.handlers.save_post, _on_save_post),
    (bpy.app.handlers.load_pre, _on_load_pre),
)


def register():
    for handlers, fn in _HANDLERS:
        if fn not in handlers:
            handlers.append(fn)


def unregister():
    stop()
    for handlers, fn in _HANDLERS:
        if fn in handlers:
            handlers.remove(fn)

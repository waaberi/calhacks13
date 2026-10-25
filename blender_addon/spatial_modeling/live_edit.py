"""Owned live native edits with immutable-baseline updates and one final Undo.

All messages are main-thread handlers. Preview updates are real native mutations,
but never history steps. Commit reconstructs the baseline before the ordinary
undoable final edit, so live previews cannot become the Undo baseline.
"""

import copy
import hashlib
import json
import logging
import time
import uuid
from collections import ChainMap, OrderedDict
from contextlib import contextmanager

from . import commands, protocol, server

_active = None
TIMEOUT = 15.0
MAX_HISTORY = 256
log = logging.getLogger(__name__)


def is_active(session=None):
    return _active is not None and (session is None or _active.session is session)


def ensure_no_active():
    if is_active():
        raise commands.Refused("lease_conflict", "Finish or cancel the live controller gesture before another native command.")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class NativeBaseline:
    """Native mesh/transform backup. No file I/O, mode switches or Undo calls."""

    def __init__(self, sync, ids):
        import bmesh
        import bpy

        from . import edits, spatial_model_edit

        self.sync, self.mode, self.records = sync, bpy.context.mode, []
        self.selection = edits._selection()
        for oid in ids:
            obj = sync.find_object(oid)
            if obj is None:
                raise commands.Refused("not_found", "A live target no longer exists.")
            record = {"id": oid, "channels": edits._channels(obj), "mesh": None,
                      "history": [], "active_face": None}
            if self.mode == "EDIT_MESH":
                if obj.type != "MESH" or obj.mode != "EDIT":
                    raise commands.Refused("failed", "Every component target must be a native Edit Mode mesh.")
                if obj.data.users != 1 or obj.data.library is not None or obj.data.shape_keys:
                    raise commands.Refused("failed", "Live component editing needs unlinked, single-user mesh data without shape keys.")
                bm = bmesh.from_edit_mesh(obj.data)
                spatial_model_edit._index(bm)
                mesh = bpy.data.meshes.new(".SpatialLiveImmutableBaseline")
                bm.to_mesh(mesh)
                record["mesh"] = mesh
                record["history"] = [(type(element).__name__, element.index) for element in bm.select_history]
                record["active_face"] = bm.faces.active.index if bm.faces.active is not None else None
            self.records.append(record)

    def restore(self):
        import bmesh
        import bpy

        from . import edits, spatial_model_edit

        if bpy.context.mode != self.mode:
            raise commands.Refused("failed", "Native mode changed during the live gesture; refusing to overwrite it.")
        for record in self.records:
            obj = self.sync.find_object(record["id"])
            if obj is None:
                raise commands.Refused("not_found", "A live target was removed outside its transaction.")
            edits._restore(obj, record["channels"])
            if record["mesh"] is not None:
                bm = bmesh.from_edit_mesh(obj.data)
                bm.clear()
                bm.from_mesh(record["mesh"])
                spatial_model_edit._index(bm)
                spatial_model_edit._restore_history(bm, record["history"], record["active_face"])
                bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
                obj.update_from_editmode()
        edits._restore_selection(self.selection)
        bpy.context.view_layer.update()

    def close(self):
        import bpy
        for record in self.records:
            if record["mesh"] is not None:
                bpy.data.meshes.remove(record["mesh"])
                record["mesh"] = None


def native_context():
    import bpy

    from . import spatial_model_edit

    ctx = bpy.context
    tool, reason = spatial_model_edit._tool(ctx)
    if reason:
        raise commands.Refused("failed", reason)
    settings = ctx.tool_settings
    names = ("mesh_select_mode", "transform_pivot_point", "use_snap", "snap_elements",
             "snap_target", "use_snap_grid_absolute", "use_snap_self", "use_snap_edit",
             "use_snap_nonedit", "use_snap_selectable", "use_snap_align_rotation",
             "use_snap_backface_culling", "use_snap_translate", "use_snap_rotate", "use_snap_scale",
             "use_proportional_edit", "use_proportional_edit_objects", "use_proportional_connected",
             "use_proportional_projected", "proportional_edit_falloff", "proportional_distance")
    options = {}
    for name in names:
        if hasattr(settings, name):
            value = getattr(settings, name)
            options[name] = sorted(value) if isinstance(value, set) else list(value) if hasattr(value, "__len__") and not isinstance(value, str) else value
    active = ctx.active_object
    tool_options = getattr(spatial_model_edit, "_options", None)
    selection = {"objects": sorted(obj.get("spatial_modeling_id", "") for obj in ctx.selected_objects)}
    if ctx.mode == "EDIT_MESH" and active is not None:
        import bmesh
        bm = bmesh.from_edit_mesh(active.data)
        spatial_model_edit._index(bm)
        selection.update({domain: [e.index for e in values if e.select and not e.hide]
                          for domain, values in (("vertices", bm.verts), ("edges", bm.edges), ("faces", bm.faces))})
        selection["history"] = [(type(item).__name__, item.index) for item in bm.select_history]
        selection["active_face"] = bm.faces.active.index if bm.faces.active is not None else None
    return {"mode": ctx.mode, "native_tool": tool,
            "active_id": active.get("spatial_modeling_id", "") if active else "",
            "orientation": ctx.scene.transform_orientation_slots[0].type,
            "options": options,
            "selection": selection,
            "tool_options": tool_options(ctx, active, tool) if tool_options and active else {}}


class LiveEdits:
    def __init__(self, session, editor, leases, undoable, kernel=None, baseline=None, context=None, clock=None):
        self.session, self.editor, self.leases, self.undoable = session, editor, leases, undoable
        if kernel is None:
            from . import modeling_tools
            kernel = modeling_tools
        self.kernel = kernel
        self.baseline_factory = baseline or NativeBaseline
        self.context = context or native_context
        self.clock = clock or time.monotonic
        self.current = None
        self.history, self.requests = OrderedDict(), OrderedDict()

    def attach(self, srv):
        srv.handlers = ChainMap({f"live.edit.{name}": self.handler(name)
                                 for name in ("begin", "update", "commit", "cancel")}, srv.handlers)
        previous = srv.on_disconnect
        def disconnected(conn):
            if self.current and self.current["conn"] is conn:
                self._cancel("Controller disconnected", notify=False)
            if previous:
                previous(conn)
        srv.on_disconnect = disconnected
        srv.live_edit = self
        return srv

    def _identity(self, msg, conn):
        p = msg.get("payload")
        if not isinstance(p, dict):
            raise commands.Refused("invalid_message", "Live payload must be an object.")
        commands._uuid(msg.get("id"), "id")
        for field in commands.REQUEST_FIELDS:
            commands._uuid(p.get(field), field)
        actor = self.session.participants.get(conn)
        if not actor or not getattr(conn, "can_edit", False) or actor["role"] != "vr" or actor["actor_id"] != p["actor_id"]:
            raise commands.Refused("permission_denied", "Only this joined editable VR actor can own the live edit.")
        if (p["session_id"], p["host_epoch"]) != (self.session.session_id, self.session.host_epoch):
            raise commands.Refused("wrong_session", "Native host session changed.")
        doc = self.session.document()
        if (p["document_id"], p["open_epoch"]) != (doc["id"], doc["open_epoch"]):
            raise commands.Refused("wrong_document", "Native document changed.")
        return p

    def handler(self, action):
        def handle(msg, conn):
            try:
                p = self._identity(msg, conn)
                digest = _digest(p)
                old = self.requests.get(msg["id"])
                if old is not None:
                    if old[0] != digest or old[1] is not conn:
                        raise commands.Refused("duplicate_request", "Live request ID was already used.")
                    return copy.deepcopy(old[2])
                result = (self._cancel_request if action == "cancel" else getattr(self, "_" + action))(p, conn)
                reply = protocol.message("live.edit.state", result, re=msg["id"])
                self.requests[msg["id"]] = (digest, conn, copy.deepcopy(reply))
                while len(self.requests) > MAX_HISTORY:
                    self.requests.popitem(last=False)
                return reply
            except (commands.Invalid, KeyError, TypeError, ValueError) as exc:
                return server.error("invalid_message", str(exc), msg.get("id"))
            except commands.Refused as exc:
                return server.error(exc.code, exc.message, msg.get("id"), exc.details)
            except Exception as exc:
                log.exception("live.edit.%s failed", action)
                return server.error("internal_error", f"Live edit refused: {type(exc).__name__}: {exc}", msg.get("id"))
        return handle

    def _begin(self, p, conn):
        global _active
        if self.current is not None or is_active():
            raise commands.Refused("lease_conflict", "Another live edit is already active.")
        commands._keys(p, "payload", (*commands.REQUEST_FIELDS, "base_revision", "lease", "targets", "operation"))
        commands._revision(p["base_revision"], "base_revision")
        commands._uuid(p["lease"], "lease")
        if not isinstance(p["targets"], list) or not 1 <= len(p["targets"]) <= 256:
            raise commands.Refused("invalid_message", "Live targets must list 1 to 256 objects.")
        ids = []
        revision = self.editor.flush()
        if revision != p["base_revision"]:
            raise commands.Refused("stale_revision", "Look at the current scene before beginning a live edit.")
        for target in p["targets"]:
            commands._keys(target, "target", ("id", "generation"))
            commands._uuid(target["id"], "target.id")
            commands._revision(target["generation"], "target.generation")
            if self.editor.generation(target["id"]) != target["generation"]:
                raise commands.Refused("stale_revision", "A live target changed; select it again.")
            if target["id"] in ids:
                raise commands.Refused("invalid_message", "Live targets must not repeat.")
            ids.append(target["id"])
        operation = copy.deepcopy(p["operation"])
        if not isinstance(operation, dict):
            raise commands.Refused("invalid_message", "Live operation must be an object.")
        declared = operation.get("targets", ids)
        if set(declared) != set(ids) or operation.get("target_id", ids[0]) not in ids:
            raise commands.Refused("permission_denied", "Operation targets must exactly match admitted lease targets.")
        operation.update(targets=ids, target_id=operation.get("target_id", ids[0]))
        selection_only = operation.get("selection_only", False)
        if type(selection_only) is not bool or (selection_only and operation.get("tool") not in ("object.selection", "mesh.selection")):
            raise commands.Refused("invalid_message", "Only typed native selection operations may skip geometry history.")
        lease = next((lease for lease in self.session.store.leases() if lease["lease_id"] == p["lease"]), None)
        if not lease or lease["owner"]["actor_id"] != p["actor_id"] or lease["mode"] != "exclusive":
            raise commands.Refused("lease_conflict", "A live edit requires this actor's ordinary exclusive lease.")
        from .preview_spatial import modal_operators
        try:
            import bpy
            if modal_operators(bpy.context):
                raise commands.Refused("failed", "Finish native modal input before beginning a live edit.")
        except ImportError:
            pass
        context = self.context()
        if context["mode"] == "OBJECT" and operation.get("tool", operation.get("native_tool")) not in {
                "object.translate", "object.move", "object.rotate", "object.scale", "object.selection",
                "builtin.move", "builtin.rotate", "builtin.scale", "translate", "move", "rotate", "scale"}:
            raise commands.Refused("failed", "Live Object Mode supports transforms and selection; use a reviewed native recipe for creation, deletion or data operations.")
        if operation.get("mode", context["mode"]) != context["mode"] or operation.get("native_tool", context["native_tool"]) != context["native_tool"]:
            raise commands.Refused("stale_revision", "Native tool or mode changed before live permission arrived.")
        if "topology_token" in operation:
            import bpy

            from . import spatial_model_edit
            native = spatial_model_edit.read_state(bpy.context, self.editor.sync)
            if (native.get("topology_token") != operation["topology_token"]
                    or native.get("mode") != operation.get("mode", context["mode"])
                    or native.get("component") != operation.get("selection", {}).get("component", native.get("component"))):
                raise commands.Refused("stale_revision", "Native topology or component context changed before live permission arrived.")
            selection = operation.get("selection", {})
            component = selection.get("component", "object")
            if context["mode"] == "EDIT_MESH":
                if native.get("active_object_id") != operation["target_id"]:
                    raise commands.Refused("failed", "Component edits must target the active native mesh.")
                kind = {"vertex": "vertices", "edge": "edges", "face": "faces"}.get(component)
                valid = {item["index"] for item in native.get(kind, [])} if kind else set()
                picked = selection.get("indices", [])
                if ((not picked and not selection_only)
                        or any(type(index) not in (int, float) or index != int(index) or index not in valid for index in picked)):
                    raise commands.Refused("stale_revision", "A picked native component is missing, hidden or out of date.")
        baseline = self.baseline_factory(self.editor.sync, ids)
        self.current = {"id": uuid.uuid4().hex, "conn": conn, "actor_id": p["actor_id"],
                        "lease": p["lease"], "ids": ids, "operation": operation,
                        "identity": {name: p[name] for name in commands.REQUEST_FIELDS},
                        "context": context, "baseline": baseline, "sequence": 0,
                        "revision": revision, "generations": {oid: self.editor.generation(oid) for oid in ids},
                        "parameters": None, "parameter_digest": None,
                        "selection": operation.get("selection", {}), "last": self.clock()}
        _active = self
        return self._state("active", "Native live edit ready; changes remain cancellable until release.")

    def _owned(self, p, conn):
        token = p.get("edit_session_id")
        commands._uuid(token, "edit_session_id")
        state = self.current
        if state is None or token != state["id"]:
            finished = self.history.get(token)
            if finished and finished[0] is conn:
                return finished[1]
            raise commands.Refused("not_found", "That live edit is no longer active.")
        if state["conn"] is not conn or state["actor_id"] != p["actor_id"]:
            raise commands.Refused("permission_denied", "This connection does not own the live edit.")
        state["last"] = self.clock()
        return None

    def _fence(self, check_context=True):
        state = self.current
        lease = next((lease for lease in self.session.store.leases() if lease["lease_id"] == state["lease"]), None)
        if not lease or lease["owner"]["actor_id"] != state["actor_id"]:
            raise commands.Refused("lease_conflict", "The live edit lease ended.")
        if self.editor.flush() != state["revision"] or any(self.editor.generation(oid) != state["generations"][oid] for oid in state["ids"]):
            raise commands.Refused("stale_revision", "Native data changed outside this live edit; refusing to overwrite it.")
        if check_context and self.context() != state["context"]:
            raise commands.Refused("stale_revision", "Native tool, selection context or settings changed during the live edit.")

    @contextmanager
    def _mutation(self, phase):
        old = getattr(self.session, "live_edit_echo", None)
        self.session.live_edit_echo = {"id": self.current["id"], "actor_id": self.current["actor_id"],
                                      "sequence": self.current["sequence"], "phase": phase}
        try:
            with self.session.commit():
                yield
        finally:
            self.session.live_edit_echo = old

    def _refresh(self):
        state = self.current
        state["revision"] = self.editor.flush()
        state["generations"] = {oid: self.editor.generation(oid) for oid in state["ids"]}
        state["context"] = self.context()

    def _update(self, p, conn):
        commands._keys(p, "payload", (*commands.REQUEST_FIELDS, "edit_session_id", "sequence", "parameters"))
        finished = self._owned(p, conn)
        if finished:
            return finished
        state = self.current
        commands._revision(p["sequence"], "sequence")
        # _revision validates without returning a normalized integer.
        sequence = int(p["sequence"])
        digest = _digest(p["parameters"])
        if sequence == state["sequence"] and digest == state["parameter_digest"]:
            return self._state("updated", "Live preview already applied.")
        if sequence != state["sequence"] + 1:
            raise commands.Refused("duplicate_request", "Live updates must have the next monotonic sequence.")
        self._fence()
        self.kernel.validate_live(state["operation"], p["parameters"])
        if state["operation"].get("selection_only") and p["parameters"]:
            raise commands.Refused("invalid_message", "Selection synchronization takes empty parameters.")
        previous = state["parameters"]
        state["sequence"] = sequence
        try:
            with self._mutation("updated"):
                state["baseline"].restore()
                done = self.kernel.apply_live(self.editor, state["operation"], copy.deepcopy(p["parameters"]))
                state["selection"] = done.selection or state["selection"]
                self._refresh()
        except Exception:
            # Restore the last acknowledged live shape, not a half-applied new
            # sample. This remains owned and cancellable; no Undo is introduced.
            with self._mutation("updated"):
                state["baseline"].restore()
                if previous is not None:
                    self.kernel.apply_live(self.editor, state["operation"], copy.deepcopy(previous))
                self._refresh()
            state["sequence"] -= 1
            raise
        state["parameters"], state["parameter_digest"] = copy.deepcopy(p["parameters"]), digest
        return self._state("updated", "Live Blender preview updated; release commits one Undo, Cancel restores the start.")

    def _commit(self, p, conn):
        commands._keys(p, "payload", (*commands.REQUEST_FIELDS, "edit_session_id", "sequence"))
        finished = self._owned(p, conn)
        if finished:
            return finished
        state = self.current
        if p["sequence"] != state["sequence"] or state["parameters"] is None:
            raise commands.Refused("invalid_message", "Commit requires the latest acknowledged live update.")
        self._fence()
        def final(_obj, _args):
            state["baseline"].restore()
            return self.kernel.apply_live(self.editor, state["operation"], copy.deepcopy(state["parameters"]))
        commit = (final if state["operation"].get("selection_only") else
                  self.undoable(lambda done: done.summary)(self.editor._published(final)))
        try:
            with self._mutation("committed"):
                done = commit(None, {})
                state["selection"] = done.selection or state["selection"]
                self._refresh()
        except Exception:
            with self._mutation("cancelled"):
                state["baseline"].restore()
                self._refresh()
            self._finish("cancelled", "Final native commit failed; starting geometry restored.")
            raise
        return self._finish("committed", done.summary)

    def _cancel(self, reason="Live edit cancelled", notify=True):
        if self.current is None:
            return None
        try:
            self._fence(check_context=False)
            with self._mutation("cancelled"):
                self.current["baseline"].restore()
                self._refresh()
            result = self._finish("cancelled", reason + "; starting native geometry restored without an Undo step.")
        except commands.Refused as exc:
            result = self._finish("conflict", exc.message)
        if notify:
            result_conn = self.history[result["edit_session_id"]][0]
            result_conn.send(protocol.message("live.edit.state", result))
        return result

    def _cancel_request(self, p, conn):
        commands._keys(p, "payload", (*commands.REQUEST_FIELDS, "edit_session_id"), ("reason",))
        finished = self._owned(p, conn)
        return finished or self._cancel(str(p.get("reason", "Controller cancelled the live edit"))[:200], notify=False)

    def _state(self, phase, notice):
        state = self.current
        return {**state["identity"], "edit_session_id": state["id"], "phase": phase,
                "sequence": state["sequence"], "revision": state["revision"],
                "generations": dict(state["generations"]), "selection": copy.deepcopy(state["selection"]),
                "notice": notice}

    def _finish(self, phase, notice):
        global _active
        result = self._state(phase, notice)
        state = self.current
        state["baseline"].close()
        self.history[state["id"]] = (state["conn"], copy.deepcopy(result))
        while len(self.history) > MAX_HISTORY:
            self.history.popitem(last=False)
        self.current = None
        if _active is self:
            _active = None
        return result

    def poll(self):
        if self.current and self.clock() - self.current["last"] > TIMEOUT:
            token, actor = self.current["lease"], self.current["actor_id"]
            self._cancel("Live controller timed out")
            from .session_store import SessionError
            try:
                self.leases.end(token, actor)
            except SessionError as exc:
                if exc.code != "not_found":
                    raise

    def stop(self):
        if self.current:
            self._cancel("Native host stopped", notify=False)



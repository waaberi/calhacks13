"""Read-only P2.5 native tool/selection telemetry, queried by the opted-in VR UI.

This does not evaluate received Python, change native selection, push Undo or
simulate a modal operator. Spatial mutations still use normal typed commands.
"""

import importlib
import os
import uuid
from collections import ChainMap

from . import commands, protocol, server, session_store, sketch

TOOLS = {
    "sketcher.slvs_add_line2d": "line",
    "sketcher.slvs_add_rectangle": "rectangle",
    "sketcher.slvs_add_circle2d": "circle",
    "sketcher.slvs_select": "select",
    "builtin.select_box": "select",
}

IGNORED_MODALS = {"SPATIAL_MODELING_OT_input_gate"}
UNKNOWN_MODAL_STATE = "Modal state unavailable"
MODAL_INSPECTION_ERRORS = (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError)


def modal_operators(context):
    """Blender 5.2 exposes each window's running operators, not just history."""
    found = []
    try:
        for window in context.window_manager.windows:
            for op in window.modal_operators:
                name = op.bl_idname
                if not isinstance(name, str) or not name or name == UNKNOWN_MODAL_STATE:
                    return [UNKNOWN_MODAL_STATE]
                if name not in IGNORED_MODALS:
                    found.append(name)
    except MODAL_INSPECTION_ERRORS:
        return [UNKNOWN_MODAL_STATE]
    return found


class NativePreviewSessions:
    """One UI writer reserves an ordinary exclusive lease as the host desktop.

    Native input is interpreted as desktop Blender work, so a foreign VR lease
    would incorrectly make gate.py block it. The connection owns this reservation
    and cannot transfer/release somebody else's. No separate locking system.
    """
    def __init__(self, session, leases, context):
        self.session, self.leases, self.context = session, leases, context
        self.owner = self.lease = self.token = None
        self.writer = None
        self.ending = False
        self.seen = set()

    def _modals(self):
        try:
            return modal_operators(self.context())
        except MODAL_INSPECTION_ERRORS:
            return [UNKNOWN_MODAL_STATE]

    def _clear(self):
        if self.owner is not None:
            self.owner.preview_ui_active = False
        self.owner = self.lease = self.token = None
        self.writer = None
        self.ending = False

    def _identity(self, msg, conn, end=False):
        fields = (*commands.REQUEST_FIELDS, *(('ui_session_id',) if end else ()))
        try:
            commands._uuid(msg["id"], "id")
            p = commands._keys(msg["payload"], "payload", fields)
            for name in fields:
                commands._uuid(p[name], name)
        except (KeyError, commands.Invalid) as exc:
            raise session_store.SessionError("invalid_message", str(exc)) from exc
        actor = self.session.participants.get(conn)
        if not getattr(conn, "can_edit", False) or not actor or actor["role"] != "vr" or p["actor_id"] != actor["actor_id"]:
            raise session_store.SessionError("permission_denied", "Only the joined local editable VR connection can own native preview input.")
        if (p["session_id"], p["host_epoch"]) != (self.session.session_id, self.session.host_epoch):
            raise session_store.SessionError("wrong_session", "Native host session changed; reconnect.")
        doc = self.session.document()
        if (p["document_id"], p["open_epoch"]) != (doc["id"], doc["open_epoch"]):
            raise session_store.SessionError("wrong_document", "Native document changed; reconnect.")
        return p

    def state(self, conn):
        self.poll()
        actor = self.writer
        modals = self._modals()
        return {"process_id": os.getpid(), "input_allowed": conn is self.owner and not self.ending
                and self.lease is not None and UNKNOWN_MODAL_STATE not in modals,
                "ui_session_id": self.token if conn is self.owner else "", "ui_owner": dict(actor) if actor else None,
                "ui_ending": self.ending, "modal_operators": modals, "modal_active": bool(modals)}

    def display_leases(self):
        """Presentation only: identify the VR writer behind the desktop lease.

        Admission still uses the host actor so injected native input does not
        deadlock its own gate. Keep the writer name across modal cleanup after
        disconnect, without rewriting the actual lease owner or permissions.
        """
        return [{**lease, "owner": dict(self.writer)}
                if self.writer and self.lease and lease["lease_id"] == self.lease["lease_id"] else lease
                for lease in self.session.store.leases()]

    def begin(self, msg, conn):
        try:
            self._identity(msg, conn)
            if self.owner is conn:
                # The same connected owner may resume its retained reservation
                # to send Enter/Escape after a focus-loss suspend. No new lease
                # or actor is admitted while its native modal tool is running.
                if UNKNOWN_MODAL_STATE in self._modals():
                    raise session_store.SessionError("busy", "Native modal state is unavailable; restore it before resuming preview input.")
                self.ending = False
                conn.preview_ui_active = True
                return protocol.message("preview.ui.granted", self.state(conn), re=msg["id"])
            if msg["id"] in self.seen or len(self.seen) >= 10000:
                raise session_store.SessionError("duplicate_request", "This native UI request already ended or the session history is full; use a fresh session.")
            if self.owner is not None:
                raise session_store.SessionError("lease_conflict", "Another preview writer owns the native UI or its modal operation is still ending.")
            # Also preserve explicit host-desktop reservations instead of silently
            # nesting a second lease on behalf of another UI.
            if self.session.store.leases():
                raise session_store.SessionError("lease_conflict", "Finish the current native/remote edit before enabling preview input.")
            if UNKNOWN_MODAL_STATE in self._modals():
                raise session_store.SessionError("busy", "Native modal state is unavailable; restore it before starting preview input.")
            # An explicit request may adopt an already-running desktop modal.
            # The ordinary host lease lets that same native operation continue;
            # it does not invoke/confirm/cancel it or change native Undo history.
            self.lease = self.leases.grant(self.session.host["actor_id"], "exclusive")
            self.owner, self.token = conn, uuid.uuid4().hex
            self.writer = dict(self.session.participants[conn])
            # Only server.py's scene-free built-in ping may use this marker.
            # It is not edit permission and survives a retained modal cleanup.
            conn.preview_ui_active = True
            self.seen.add(msg["id"])
            return protocol.message("preview.ui.granted", self.state(conn), re=msg["id"])
        except session_store.SessionError as exc:
            return server.error(exc.code, exc.message, msg.get("id"), exc.details)

    def end(self, msg, conn):
        try:
            p = self._identity(msg, conn, end=True)
            if conn is not self.owner or p["ui_session_id"] != self.token:
                raise session_store.SessionError("permission_denied", "This connection does not own that native preview session.")
            self.ending = True
            self.poll()
            return protocol.message("preview.ui.ended", self.state(conn), re=msg["id"])
        except session_store.SessionError as exc:
            return server.error(exc.code, exc.message, msg.get("id"), exc.details)

    def disconnected(self, conn):
        if conn is self.owner:
            self.ending = True
            self.poll()

    def poll(self):
        if self.lease is not None and not any(
                lease["lease_id"] == self.lease["lease_id"] for lease in self.session.store.leases()):
            self._clear()
        # Keep the ordinary exclusive lease across mouse release, disconnection
        # and Escape until Blender confirms no native modal operator is running.
        if self.ending and not self._modals():
            self.leases.end(self.lease["lease_id"], self.session.host["actor_id"])
            self._clear()


def editing_mode(context):
    return "shared" if getattr(getattr(context, "scene", None),
                               "spatial_editing_mode", "EXCLUSIVE") == "SHARED" else "exclusive"


def read_state(context):
    """Read the pinned CAD API's actual workspace tool and active sketch object.

    Ambiguous tools across Blender windows are not silently resolved to the
    first window. Input capture binding is a separate identity check.
    """
    dependency = sketch.dependency_status()
    state = {"available": dependency["available"], "reason": dependency.get("reason", ""),
             "tool": "", "native_tool": "", "sketch_id": "", "mode": context.mode,
             "editing_mode": editing_mode(context),
             "selected_entities": [], "unsupported_options": [],
             "unsupported_sketches": sketch.snapshot_problems()}
    if not dependency["available"]:
        return state
    group = getattr(context.scene, "sketcher", None)
    obj = getattr(group, "active_sketch_object", None)
    if obj is not None and sketch.is_sketch(obj):
        state["sketch_id"] = obj.get("spatial_modeling_id", "")
        if obj.get("is_3d_sketch", False):
            state["reason"] = "Direct VR drawing supports a planar native sketch."
    tools = []
    for window in context.window_manager.windows:
        if not any(area.type == "VIEW_3D" for area in window.screen.areas):
            continue
        tool = window.workspace.tools.from_space_view3d_mode(context.mode, create=False)
        if tool is not None:
            tools.append(tool)
    if len({tool.idname for tool in tools}) > 1:
        state["reason"] = "Different Blender windows have different active tools; use one native workspace."
        return state
    if tools:
        tool = tools[0]
        state["native_tool"] = tool.idname
        state["tool"] = TOOLS.get(tool.idname, "")
        if tool.idname == "sketcher.slvs_add_line2d":
            props = tool.operator_properties("view3d.slvs_add_line2d")
            if props.continuous_draw:
                state["unsupported_options"].append("Continuous Draw")
    # These native modal features are not reproduced by the typed point bridge.
    # Refuse spatial arming rather than silently ignoring visible tool settings.
    for prop, label in (("auto_axis_constraints", "Auto Constraints"),
                        ("use_snap_project", "Live Project Snaps")):
        if getattr(group, prop, False):
            state["unsupported_options"].append(label)
    if obj is not None:
        try:
            api = sketch._adapter()._api()
            package = sketch._adapter()._module().__name__
            selection = importlib.import_module(f"{package}.drawing.selection")
            native_ids = set(api["curves"].read_uuid_list(obj.data, "curve_id"))
            state["selected_entities"] = [cid for cid in selection.selected if cid in native_ids]
        except (AttributeError, RuntimeError, ValueError):
            # Native selection is advisory; never invent an entity ID.
            state["selected_entities"] = []
    return state


def attach(srv, session, leases):
    def context():
        import bpy
        return bpy.context
    ui = NativePreviewSessions(session, leases, context)
    def query(msg, _conn):
        if msg["payload"]:
            from . import server
            return server.error("invalid_message", "preview.state.query takes an empty payload", msg["id"])
        state = read_state(context())
        doc = session.document()
        state.update(session_id=session.session_id, host_epoch=session.host_epoch,
                     document_id=doc["id"], open_epoch=doc["open_epoch"])
        state.update(ui.state(_conn))
        return protocol.message("preview.state", state, re=msg["id"])
    srv.handlers = ChainMap({"preview.state.query": query, "preview.ui.begin": ui.begin,
                             "preview.ui.end": ui.end}, srv.handlers)
    previous = srv.on_disconnect
    def disconnected(conn):
        ui.disconnected(conn)
        if previous:
            previous(conn)
    srv.on_disconnect = disconnected
    srv.preview_ui = ui
    return srv

"""Client role. Connect explicitly from a separate empty Blender.

The mirror is read-only: every edit is a request to the host (requests.py), and
the local scene changes only when the host's scene.update arrives.
"""

import copy
import queue

from .presence import Presence
from .requests import EditBlocked, RequestTracker
from .state import SceneState

state = SceneState()
presence = Presence()
requests = RequestTracker()
_link = _mirror = None
_draw_handle = None
_can_edit = False


def controlled_edit_enabled():
    """The actual welcomed host capability; never a locally inferred permission."""
    return bool(_can_edit and state.current and _link is not None and _link.healthy)


def ownership_state():
    """Full current leases, this mirror's actual actor ID, and honest scene status."""
    if not state.current or _link is None or not _link.healthy:
        return [], "", state.status
    return copy.deepcopy(presence.leases), presence.actor_id, state.status


def edit_blocked():
    """None when a Client edit may be sent now, otherwise the reason to show."""
    if _link is None:
        return "Not connected to the host"
    return requests.blocked(state.current, _can_edit, _link.healthy)


def send_edit(op, label, args=None, target_id=None):
    """Send one edit request to the host. Returns its request ID; raises EditBlocked."""
    reason = edit_blocked()
    if reason:
        raise EditBlocked(reason)
    target = None
    if target_id is not None:
        target = state.objects.get(target_id)
        if target is None:
            raise EditBlocked("That object isn't in the host scene any more")
    msg = requests.build(op, label, state.document, args, target)
    if not _link.send(msg):
        requests.disconnected()
        raise EditBlocked("Not connected to the host")
    return msg["id"]


def acknowledge_unknown():
    requests.acknowledge_unknown()


def _send_queries(payloads):
    from .. import protocol
    for payload in payloads:
        query = protocol.message("receipt.query", payload)
        if _link.send(query):
            requests.query_sent(query["id"], payload)


def participants():
    return copy.deepcopy(presence.participants) if ownership_state()[1] else []


def connect(address, token, version, name="Blender viewer", port=8767, tls=True):
    global _link, _mirror, state, requests
    from .mirror import Mirror
    from .transport import ReadOnlyLink
    disconnect()
    _mirror = Mirror()
    state = SceneState()
    requests = RequestTracker()
    try:
        _link = ReadOnlyLink(address, token, version, name, port, tls)
    except Exception:
        _mirror.clear()
        _mirror = None
        raise
    import bpy
    if not bpy.app.timers.is_registered(poll):
        bpy.app.timers.register(poll, first_interval=0.02)


def poll():
    global _can_edit
    import bpy
    if _link is None:
        return None
    if not _link.thread.is_alive():
        requests.disconnected()
        _can_edit = False
        presence.clear()
        if not state.status.startswith("Connection refused"):  # keep why the host refused
            state.stale("Connection stopped — reconnect explicitly; last scene is stale")
    try:
        for _ in range(32):
            try:
                kind, payload = _link.events.get_nowait()
            except queue.Empty:
                break
            if kind in ("scene.snapshot", "scene.update"):
                state.receive(payload, kind == "scene.snapshot")
                _mirror.apply(state)
            elif kind == "welcome":
                presence.welcomed(payload)
                _can_edit = payload.get("can_edit") is True
                state.stale("Receiving a fresh host snapshot — read-only")
                _send_queries(requests.welcomed(payload))
            elif kind == "result":
                requests.on_result(payload)
            elif kind == "receipts":
                requests.on_receipts(*payload)
            elif kind == "reply_error":
                requests.on_reply_error(*payload)
            elif kind in ("session.update", "activity"):
                # Presence changes must never invalidate an otherwise current
                # scene or apply geometry/materials to the read-only mirror.
                try:
                    if kind == "session.update":
                        presence.receive(payload)
                    else:
                        presence.activity(payload)
                except (ValueError, KeyError, TypeError):
                    presence.clear()
                    _can_edit = False
            elif kind == "error":
                requests.disconnected()
                _can_edit = False
                presence.clear()
                state.stale("Host scene unavailable — last scene is stale; awaiting a fresh snapshot"
                            if payload == "failed" else
                            f"Connection refused ({payload}) — reconnect explicitly")
            else:
                if kind == "disconnected":
                    requests.disconnected()
                _can_edit = False
                presence.clear()
                state.stale(payload or "Connecting — last scene is stale")
    except (ValueError, KeyError, TypeError, RuntimeError):
        _can_edit = False
        presence.clear()
        state.stale("Scene could not be verified/applied — reconnect for a fresh snapshot")
        _link.stop()
    if state.current and not _link.healthy:
        requests.disconnected()
        _can_edit = False
        presence.clear()
        state.stale("Host is not responding — last scene is stale")
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in ("PREFERENCES", "VIEW_3D"):
                area.tag_redraw()
    return 0.02


def disconnect():
    global _link, _mirror, _can_edit
    from .. import remote_test_ui
    remote_test_ui.cancel_before_send()
    import bpy
    if _link is not None:
        _link.stop()
    _link = None
    requests.disconnected()
    _can_edit = False
    presence.clear()
    if bpy.app.timers.is_registered(poll):
        bpy.app.timers.unregister(poll)
    state.stale("Disconnected — read-only mirror stopped")
    if _mirror is not None:
        _mirror.clear()
        _mirror = None


def _draw_status():
    import blf
    import bpy
    prefs = bpy.context.preferences.addons.get(__package__.rsplit(".", 1)[0])
    if prefs is None or prefs.preferences.role != "CLIENT":
        return
    blf.position(0, 20, 45, 0)
    blf.size(0, 18)
    blf.color(0, *((0.7, 1, 0.7, 1) if state.current else (1, 0.5, 0.15, 1)))
    blf.draw(0, state.status)


def register():
    global _draw_handle
    import bpy
    bpy.app.handlers.persistent(_before_load)
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_status, (), "WINDOW", "POST_PIXEL")
    if _before_load not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_before_load)


def _before_load(*_):
    disconnect()


def unregister():
    global _draw_handle
    import bpy
    disconnect()
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, "WINDOW")
        _draw_handle = None
    if _before_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_before_load)

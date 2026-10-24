"""Host role lifecycle: run the server while this Blender is the host.

The server runs while the add-on is enabled in Host role. It stops when the
add-on is disabled, when the role changes to Client and while another .blend
file loads, then starts again after the load. A timer drains its queue on
Blender's main thread, so handlers may use bpy.

It always serves the Unity app on 127.0.0.1:8765. When the preferences allow
Client-role Blenders on the LAN, it also listens on port 8767 (lan.py). If the
LAN port can't start, the localhost port still does. Changing a LAN preference
restarts the server, which closes every connection; clients reconnect.

Every start makes a new Document (a new open epoch) and a new Session (a new
host_epoch), so stopping always closes every connection and clients rejoin.
Scene sync (sync.py) starts with them at revision 0; the drain timer also
polls it, so direct edits in this Blender reach every client as scene.update.
Commands (commands.py, applied by edits.py) and their receipts live as long as
the session.

Undo: operators run from a timer don't push their own undo step, so an edit
silently merges into the previous one and a single Undo reverts both. Every
function that changes Blender data goes through undoable(), which pushes one
named step after it succeeds: a message handler, or an edit in edits.py.
Read-only handlers such as ping must not push, nor must Undo, Redo and Save.
A function that changes the scene calls sync.flush() before it returns, so IDs
given during the flush are in the same Undo step and every client has the
scene.update before the sender has the result.
"""

import functools
import uuid

import bpy
from bpy.app.handlers import persistent

from . import commands, document, edits, lan, server, session
from . import sync as scene_sync  # host.sync() is the role switch below

DRAIN_INTERVAL = 0.02  # seconds between queue drains
LAN_ROLES = ("blender-client",)  # 8765 admits only the Unity app (server.Listener's default)

_server = None
_session = None
_document = None
_commands = None
_session_id = None  # used only while the add-on preferences aren't available
_starting = False
status = "Stopped"  # shown in the add-on preferences; never contains the token
lan_status = "Off"


def undoable(label):
    """Wrap a function that changes Blender data so each success is one Undo step.

    Usage: server.HANDLERS["object.add"] = undoable("Add Object")(add_object)
    No step is pushed when the function raises or returns an `error` message.
    label may also be a function of what the wrapped function returned, so
    edits.py names each step after its edit ("Moved Shaft 10 mm along X").
    """

    def wrap(fn):
        @functools.wraps(fn)
        def run(*args):
            reply = fn(*args)
            if not (isinstance(reply, dict) and reply.get("type") == "error"):
                bpy.ops.ed.undo_push(message=label(reply) if callable(label) else label)
            return reply

        return run

    return wrap


def participants():
    """The connected participants, for the preferences panel."""
    return list(_session.participants.values()) if _session is not None else []


def _prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def _role():
    prefs = _prefs()
    return prefs.role if prefs else "HOST"


def _get_session_id():
    """The session_id kept in the add-on preferences, so it survives restarts."""
    global _session_id
    prefs = _prefs()
    if prefs is not None and session.is_uuid(prefs.session_id):
        return prefs.session_id
    _session_id = _session_id or uuid.uuid4().hex
    if prefs is not None:
        prefs.session_id = _session_id
    return _session_id


def _participants_changed():
    names = ", ".join(f"{a['name']} ({a['role']})" for a in participants()) or "nobody"
    print("Spatial Modeling: connected:", names)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "PREFERENCES":
                area.tag_redraw()


def _drain():
    if _server is None:
        return None  # unregisters this timer
    _document.tick()
    _server.drain()
    scene_sync.poll()  # direct edits in this Blender reach clients as scene.update
    return DRAIN_INTERVAL


def _lan_listener(prefs):
    """The LAN listener the preferences ask for, or None with lan_status saying why."""
    global lan_status
    if prefs is None or not prefs.lan_enabled:
        lan_status = "Off"
        return None
    if not prefs.session_token.strip():
        prefs.session_token = lan.new_token()  # kept in the user's Blender preferences only
    token = prefs.session_token
    try:
        lan.normalize_token(token)
        tls = lan.server_tls_context(token) if prefs.lan_security == "TLS" else None
    except (lan.TokenError, NotImplementedError, OSError) as e:  # OSError: ssl.SSLError
        lan_status = f"Not listening: {e}"
        return None
    address = prefs.lan_address.strip() or lan.ALL_INTERFACES
    return server.Listener(
        address, lan.PORT, ssl=tls, token=None if tls else token, roles=LAN_ROLES
    )


def _describe_lan(listener):
    if listener.host == lan.ALL_INTERFACES:
        here = lan.local_address()
        where = f"all interfaces, port {listener.port}" + (f" (this PC: {here})" if here else "")
    else:
        where = f"{listener.host}:{listener.port}"
    how = "TLS with the session token" if listener.ssl else "NO TLS, token in hello"
    return f"Listening on {where}, {how}"


def _start_server(extra, sess, cmds):
    srv = cmds.attach(sess.attach(server.Server(extra_listeners=[extra] if extra else [])))
    srv.start()
    return srv


def start():
    global _server, _session, _document, _commands, _starting, status, lan_status
    if _server is not None:
        return
    _starting = True  # setting a generated token must not restart us from its update callback
    extra = None
    prefs = _prefs()
    doc = document.Document()
    sess = session.Session(  # hello gets the document and snapshot from scene sync
        scene_sync.describe, scene_sync.snapshot, _get_session_id(),
        on_change=_participants_changed,
        name=prefs.host_name if prefs else None,
        client_can_edit=bool(prefs and prefs.client_edits),
    )
    cmds = commands.Commands(sess, edits.Editor(scene_sync, undoable, doc))
    try:
        extra = _lan_listener(prefs)
        try:
            srv = _start_server(extra, sess, cmds)
        except OSError as e:
            if extra is None:
                raise
            srv = _start_server(None, sess, cmds)  # raises again if the localhost port failed
            lan_status = f"Not listening: {e}"  # so it was the LAN port
            extra = None
    except OSError as e:
        status = f"Could not listen on {server.HOST}:{server.PORT}: {e}"
        if extra is not None:
            lan_status = "Not listening: the localhost port could not start"
        print("Spatial Modeling:", status)
        return
    finally:
        _starting = False
    _server, _session, _document, _commands = srv, sess, doc, cmds
    scene_sync.start(doc, sess)
    status = f"Listening on {srv.host}:{srv.port}"
    if extra is not None:
        lan_status = _describe_lan(extra)
    bpy.app.timers.register(_drain, first_interval=DRAIN_INTERVAL, persistent=True)
    print("Spatial Modeling:", status, "| LAN:", lan_status)


def stop():
    global _server, _session, _document, _commands, status, lan_status
    if bpy.app.timers.is_registered(_drain):
        bpy.app.timers.unregister(_drain)
    scene_sync.stop()
    if _server is not None:
        _server.stop()
        _server = None
        print("Spatial Modeling: stopped the host server")
    _session = _document = _commands = None
    status = "Stopped"
    lan_status = "Off"


def sync():
    """Start or stop the server to match the role preference."""
    global status
    if _role() == "HOST":
        start()
    else:
        stop()
        status = "Not hosting: this Blender is a Client"


def restart():
    """Apply changed LAN or editing preferences. Closes every connection; clients reconnect."""
    if _starting:
        return
    stop()
    sync()


def rename():
    """Apply a changed "Your name": everyone gets session.update, nobody is disconnected."""
    prefs = _prefs()
    if _session is not None and prefs is not None:
        _session.rename_host(prefs.host_name)


@persistent
def _on_load_pre(*_args):
    stop()


@persistent
def _on_load_post(*_args):
    sync()


@persistent
def _on_save_pre(*_args):
    if _document is not None:
        _document.store()  # an Undo may have removed the document ID


_HANDLERS = (
    (bpy.app.handlers.load_pre, _on_load_pre),
    (bpy.app.handlers.load_post, _on_load_post),
    (bpy.app.handlers.save_pre, _on_save_pre),
)


def register():
    for handlers, fn in _HANDLERS:
        handlers.append(fn)
    scene_sync.register()
    sync()


def unregister():
    for handlers, fn in _HANDLERS:
        if fn in handlers:
            handlers.remove(fn)
    stop()
    scene_sync.unregister()

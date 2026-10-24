"""Host role lifecycle: run the server while this Blender is the host.

The server runs while the add-on is enabled in Host role. It stops when the
add-on is disabled, when the role changes to Client and while another .blend
file loads, then starts again after the load. A timer drains its queue on
Blender's main thread, so handlers may use bpy.

It always serves the Unity app on 127.0.0.1:8765. When the preferences allow
Client-role Blenders on the LAN, it also listens on port 8767 (lan.py). If the
LAN port can't start, the localhost port still does. Changing a LAN preference
restarts the server, which closes every connection; clients reconnect.

Undo: operators run from a timer don't push their own undo step, so an edit
silently merges into the previous one and a single Undo reverts both. Register
every handler that changes Blender data through undoable(), which pushes one
named step after it succeeds. Read-only handlers such as ping must not push.
"""

import functools

import bpy
from bpy.app.handlers import persistent

from . import lan, server

DRAIN_INTERVAL = 0.02  # seconds between queue drains

_server = None
_starting = False
status = "Stopped"  # shown in the add-on preferences; never contains the token
lan_status = "Off"


def undoable(label):
    """Wrap a handler that changes Blender data so each success is one Undo step.

    Usage: server.HANDLERS["object.add"] = undoable("Add Object")(add_object)
    No step is pushed when the handler raises or replies with an `error`.
    """

    def wrap(handler):
        @functools.wraps(handler)
        def run(msg):
            reply = handler(msg)
            if reply is None or reply["type"] != "error":
                bpy.ops.ed.undo_push(message=label)
            return reply

        return run

    return wrap


def _prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def _role():
    prefs = _prefs()
    return prefs.role if prefs else "HOST"


def _drain():
    if _server is None:
        return None  # unregisters this timer
    _server.drain()
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
    except (lan.TokenError, NotImplementedError) as e:
        lan_status = f"Not listening: {e}"
        return None
    address = prefs.lan_address.strip() or lan.ALL_INTERFACES
    return server.Listener(address, lan.PORT, ssl=tls, token=None if tls else token)


def _describe_lan(listener):
    if listener.host == lan.ALL_INTERFACES:
        here = lan.local_address()
        where = f"all interfaces, port {listener.port}" + (f" (this PC: {here})" if here else "")
    else:
        where = f"{listener.host}:{listener.port}"
    how = "TLS with the session token" if listener.ssl else "NO TLS, token in hello"
    return f"Listening on {where}, {how}"


def _start_server(extra):
    srv = server.Server(extra_listeners=[extra] if extra else [])
    srv.start()
    return srv


def start():
    global _server, _starting, status, lan_status
    if _server is not None:
        return
    _starting = True  # setting a generated token must not restart us from its update callback
    try:
        extra = _lan_listener(_prefs())
        try:
            srv = _start_server(extra)
        except OSError as e:
            if extra is None:
                raise
            srv = _start_server(None)  # raises again if the localhost port is the problem
            lan_status = f"Not listening: {e}"  # so it was the LAN port
            extra = None
    except OSError as e:
        status = f"Could not listen on {server.HOST}:{server.PORT}: {e}"
        lan_status = "Off: the host server could not start" if lan_status != "Off" else "Off"
        print("Spatial Modeling:", status)
        return
    finally:
        _starting = False
    _server = srv
    status = f"Listening on {srv.host}:{srv.port}"
    if extra is not None:
        lan_status = _describe_lan(extra)
    bpy.app.timers.register(_drain, first_interval=DRAIN_INTERVAL, persistent=True)
    print("Spatial Modeling:", status, "| LAN:", lan_status)


def stop():
    global _server, status, lan_status
    if bpy.app.timers.is_registered(_drain):
        bpy.app.timers.unregister(_drain)
    if _server is not None:
        _server.stop()
        _server = None
        print("Spatial Modeling: stopped the host server")
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
    """Apply changed LAN preferences. Closes every connection; clients reconnect."""
    if _starting:
        return
    stop()
    sync()


@persistent
def _on_load_pre(*_args):
    stop()


@persistent
def _on_load_post(*_args):
    sync()


def register():
    bpy.app.handlers.load_pre.append(_on_load_pre)
    bpy.app.handlers.load_post.append(_on_load_post)
    sync()


def unregister():
    for handlers, fn in (
        (bpy.app.handlers.load_pre, _on_load_pre),
        (bpy.app.handlers.load_post, _on_load_post),
    ):
        if fn in handlers:
            handlers.remove(fn)
    stop()

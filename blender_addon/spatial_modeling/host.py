"""Host role lifecycle: run the localhost server while this Blender is the host.

The server runs while the add-on is enabled in Host role. It stops when the
add-on is disabled, when the role changes to Client and while another .blend
file loads, then starts again after the load. A timer drains its queue on
Blender's main thread, so handlers may use bpy.

Undo: operators run from a timer don't push their own undo step, so an edit
silently merges into the previous one and a single Undo reverts both. Register
every handler that changes Blender data through undoable(), which pushes one
named step after it succeeds. Read-only handlers such as ping must not push.
"""

import functools

import bpy
from bpy.app.handlers import persistent

from . import server

DRAIN_INTERVAL = 0.02  # seconds between queue drains

_server = None
status = "Stopped"  # shown in the add-on preferences


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


def _role():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences.role if addon and addon.preferences else "HOST"


def _drain():
    if _server is None:
        return None  # unregisters this timer
    _server.drain()
    return DRAIN_INTERVAL


def start():
    global _server, status
    if _server is not None:
        return
    srv = server.Server()
    try:
        srv.start()
    except OSError as e:
        status = f"Could not listen on {srv.host}:{srv.port}: {e}"
        print("Spatial Modeling:", status)
        return
    _server = srv
    status = f"Listening on {srv.host}:{srv.port}"
    bpy.app.timers.register(_drain, first_interval=DRAIN_INTERVAL, persistent=True)
    print("Spatial Modeling:", status)


def stop():
    global _server, status
    if bpy.app.timers.is_registered(_drain):
        bpy.app.timers.unregister(_drain)
    if _server is not None:
        _server.stop()
        _server = None
        print("Spatial Modeling: stopped the host server")
    status = "Stopped"


def sync():
    """Start or stop the server to match the role preference."""
    global status
    if _role() == "HOST":
        start()
    else:
        stop()
        status = "Not hosting: this Blender is a Client"


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

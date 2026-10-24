"""Install the add-on into a real Blender and check the Host server's lifecycle and ping.

BLENDER_USER_RESOURCES must point at a throwaway directory, so your own Blender
preferences and extensions are untouched:

  BLENDER_USER_RESOURCES=$(mktemp -d) python tests/backend/blender_check.py   # bpy module
  BLENDER_USER_RESOURCES=$(mktemp -d) blender --factory-startup --python tests/backend/blender_check.py

In bpy-module mode timers never fire, so this script calls the add-on's drain
function itself. In GUI Blender the add-on's own timer does it. test_blender.py
runs both from pytest. Exits 0 if every check passed.
"""

import os
import socket
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from pathlib import Path

import bpy

# isort: split
import addon_utils  # importable only after bpy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ping_client import Client, protocol

ADDON_DIR = HERE.parents[1] / "blender_addon" / "spatial_modeling"
MODULE = "bl_ext.user_default.spatial_modeling"
PORT = 8765
GUI = not bpy.app.background


def log(*args):
    print("[blender_check]", *args, flush=True)


def install():
    zip_path = Path(tempfile.mkdtemp()) / "spatial_modeling.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        for f in ADDON_DIR.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, f.relative_to(ADDON_DIR))
    bpy.ops.extensions.package_install_files(
        filepath=str(zip_path), repo="user_default", enable_on_install=False
    )


def listening():
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
        return True
    except OSError:
        return False


def mod(name):
    return sys.modules[f"{MODULE}.{name}"]


def wait(cond, what, timeout=10):
    """Yield to Blender until cond() is true."""
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        yield


def request(msg):
    """Send msg from a worker thread, like an external client; yields until the reply."""
    box = []

    def run():
        try:
            with Client(port=PORT) as client:
                client.send(msg)
                box.append(client.recv())
        except (OSError, protocol.ProtocolError) as e:
            box.append(e)

    threading.Thread(target=run, daemon=True).start()
    yield from wait(lambda: box, f"a reply to {msg['type']}")
    if isinstance(box[0], Exception):
        raise box[0]
    return box[0]


def ping():
    msg = protocol.message("ping")
    reply = yield from request(msg)
    assert reply["type"] == "pong" and reply["re"] == msg["id"], reply


def assert_stopped():
    host = mod("host")
    assert not listening(), "port 8765 is still open"
    assert host._server is None and not bpy.app.timers.is_registered(host._drain)


def checks():
    install()
    addon_utils.enable(MODULE, default_set=True)
    assert listening(), "nothing listens on 8765 after enabling in Host role"
    assert bpy.app.timers.is_registered(mod("host")._drain)
    log("enabled in Host role:", mod("host").status)

    server = mod("server")
    threads = []

    def recording_ping(msg):
        threads.append(threading.get_ident())
        return server.ping(msg)

    server.HANDLERS["ping"] = recording_ping
    before = (bpy.data.is_dirty, sorted((o.name, tuple(o.matrix_world.translation))
                                        for o in bpy.data.objects))
    yield from ping()
    server.HANDLERS["ping"] = server.ping
    assert threads == [threading.main_thread().ident], "ping was not handled on the main thread"
    after = (bpy.data.is_dirty, sorted((o.name, tuple(o.matrix_world.translation))
                                       for o in bpy.data.objects))
    assert before == after, "ping changed scene data"
    log("ping/pong OK; handled on the main thread; scene data unchanged")

    # An edit through undoable() is its own Undo step, not merged into the previous one.
    def add_cube(msg):
        bpy.ops.mesh.primitive_cube_add(location=(0, 3, 0))
        return protocol.message("test.done", re=msg["id"])

    server.HANDLERS["test.add_cube"] = mod("host").undoable("Add Cube")(add_cube)
    bpy.data.objects["Cube"].location.x = 5
    bpy.ops.ed.undo_push(message="Move Cube")
    count = len(bpy.data.objects)
    reply = yield from request(protocol.message("test.add_cube"))
    del server.HANDLERS["test.add_cube"]
    assert reply["type"] == "test.done" and len(bpy.data.objects) == count + 1, reply
    bpy.ops.ed.undo()
    assert len(bpy.data.objects) == count, "Undo did not remove the added cube"
    assert bpy.data.objects["Cube"].location.x == 5, "Undo also reverted the earlier edit"
    bpy.ops.ed.redo()
    assert len(bpy.data.objects) == count + 1, "Redo did not restore the cube"
    log("undoable(): one Undo reverts exactly the handler's edit; Redo restores it")

    prefs = bpy.context.preferences.addons[MODULE].preferences
    prefs.role = "CLIENT"
    assert_stopped()
    prefs.role = "HOST"
    assert listening()
    yield from ping()
    log("role Client stops the server; role Host starts it again")

    blend = Path(tempfile.mkdtemp()) / "other.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True)
    old = mod("host")._server
    held = Client(port=PORT)
    yield from wait(lambda: old._writers, "the server to accept a connection")
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    assert held.recv() is None, "a connection survived loading another file"
    held.close()
    assert mod("host")._server not in (None, old) and listening()
    yield from ping()
    log("loading another .blend closes connections and restarts the server")

    for _ in range(2):
        addon_utils.disable(MODULE, default_set=True)
        assert_stopped()
        host = mod("host")
        assert host._on_load_pre not in bpy.app.handlers.load_pre
        assert host._on_load_post not in bpy.app.handlers.load_post
        addon_utils.enable(MODULE, default_set=True)
        assert listening()
        assert bpy.app.handlers.load_pre[:].count(host._on_load_pre) == 1
        yield from ping()
    addon_utils.disable(MODULE, default_set=True)
    assert_stopped()
    log("disable/enable twice: port, timer and load handlers come and go cleanly")


def finish(code):
    log(("PASS" if code == 0 else "FAIL") + (" (GUI Blender)" if GUI else " (bpy module)"))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def main():
    if not os.environ.get("BLENDER_USER_RESOURCES"):
        log("set BLENDER_USER_RESOURCES to a throwaway directory first")
        finish(2)
    log("Blender", bpy.app.version_string)
    steps = checks()
    if GUI:
        def tick():
            try:
                next(steps)
                return 0.01
            except StopIteration:
                finish(0)
            except Exception:  # noqa: BLE001 - any failure fails the check
                traceback.print_exc()
                finish(1)

        bpy.app.timers.register(tick, first_interval=1.0, persistent=True)
        return
    try:
        for _ in steps:
            host = sys.modules.get(f"{MODULE}.host")
            if host is not None:
                host._drain()  # what the add-on's timer does in GUI Blender
            time.sleep(0.005)
    except Exception:  # noqa: BLE001 - any failure fails the check
        traceback.print_exc()
        finish(1)
    finish(0)


main()

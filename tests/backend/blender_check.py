"""Install the add-on into a real Blender and check the Host server's lifecycle, ping and LAN port.

BLENDER_USER_RESOURCES must point at a throwaway directory, so your own Blender
preferences and extensions are untouched:

  BLENDER_USER_RESOURCES=$(mktemp -d) python tests/backend/blender_check.py   # bpy module
  BLENDER_USER_RESOURCES=$(mktemp -d) blender --factory-startup --python tests/backend/blender_check.py

In bpy-module mode timers never fire, so this script calls the add-on's drain
function itself. In GUI Blender the add-on's own timer does it. test_blender.py
runs both from pytest. Exits 0 if every check passed.

The LAN port is checked on 127.0.0.1, so nothing is exposed on this PC's
network, with clients both inside this Blender and in a separate process
(ping_client.py run by this Blender's own Python, sys.executable).
"""

import os
import socket
import ssl
import subprocess
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
from ping_client import TOKEN_ENV, Client, hello, lan, protocol

ADDON_DIR = HERE.parents[1] / "blender_addon" / "spatial_modeling"
MODULE = "bl_ext.user_default.spatial_modeling"
PORT = 8765
LAN_PORT = lan.PORT
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


def listening(port=PORT):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
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


def request(*msgs, port=PORT, **client_args):
    """Send msgs from a worker thread, like an external client; yields until the replies.

    Returns the reply to each message, None after the host closed the connection.
    """
    box = []

    def run():
        try:
            with Client(port=port, **client_args) as client:
                replies = []
                for msg in msgs:
                    try:
                        client.send(msg)
                        replies.append(client.answer_to(msg))
                    except (BrokenPipeError, ConnectionResetError):
                        replies.append(None)  # the host had closed the connection
                box.append(replies)
        except (OSError, protocol.ProtocolError) as e:
            box.append(e)

    threading.Thread(target=run, daemon=True).start()
    yield from wait(lambda: box, f"a reply to {msgs[-1]['type']}")
    if isinstance(box[0], Exception):
        raise box[0]
    return box[0] if len(msgs) > 1 else box[0][0]


def ping(port=PORT, **client_args):
    msg = protocol.message("ping")
    reply = yield from request(msg, port=port, **client_args)
    assert reply["type"] == "pong" and reply["re"] == msg["id"], reply


def ping_client(token, *args):
    """Run ping_client.py in a separate process with this Blender's Python. Yields until done."""
    proc = subprocess.Popen(
        [sys.executable, "-I", str(HERE / "ping_client.py"), "--token", *args],
        env={**os.environ, TOKEN_ENV: token},  # not on the command line
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
    )
    yield from wait(lambda: proc.poll() is not None, "ping_client.py to finish", timeout=30)
    return proc.returncode, proc.stdout.read()


def assert_stopped():
    host = mod("host")
    assert not listening(), "port 8765 is still open"
    assert not listening(LAN_PORT), "port 8767 is still open"
    assert host._server is None and not bpy.app.timers.is_registered(host._drain)


def lan_checks(prefs):
    host = mod("host")
    assert not listening(LAN_PORT) and host.lan_status == "Off", "LAN port open before it was on"
    prefs.lan_address = "127.0.0.1"  # keep this PC's network out of the test
    prefs.lan_enabled = True
    token = prefs.session_token
    assert len(lan.normalize_token(token)) == lan.TOKEN_LENGTH, "no session token was generated"
    assert listening(LAN_PORT) and "TLS with the session token" in host.lan_status, host.lan_status
    assert token not in host.status + host.lan_status
    log(f"LAN port on: {host.lan_status}; {ssl.OPENSSL_VERSION}, HAS_PSK={ssl.HAS_PSK}")

    # TLS-PSK from inside this Blender, as the Client role will connect.
    yield from ping(LAN_PORT, token=token)
    yield from ping()  # the localhost port is still plain TCP
    assert mod("host")._server.listeners[0].ssl is None
    with Client(port=LAN_PORT) as plain:  # plain TCP to the TLS port
        plain.send(protocol.message("ping"))
        assert plain.recv() is None, "the TLS port answered plain TCP"
    try:
        Client(port=LAN_PORT, token=lan.new_token()).close()
        raise AssertionError("a wrong token completed the TLS handshake")
    except lan.HandshakeError:
        pass
    log("TLS-PSK in this Blender's Python: right token pings; wrong token and plain TCP fail")

    # TLS-PSK from a separate process running this Blender's own Python.
    code, good = yield from ping_client(token, "--host", "127.0.0.1")
    assert code == 0 and "TLS OK: TLSv1.3" in good and "OK" in good, good
    code, out = yield from ping_client(lan.new_token(), "--host", "127.0.0.1")
    assert code != 0 and "TLS handshake" in out, out
    log(f"separate process ({sys.executable}): {good.splitlines()[0]}; wrong token fails")

    # Fallback: no TLS, the token in hello.
    prefs.lan_security = "TOKEN"
    assert listening(LAN_PORT) and "NO TLS" in host.lan_status, host.lan_status
    code, out = yield from ping_client(token, "--host", "127.0.0.1", "--no-tls", "--name", "Lee")
    assert code == 0 and "hello accepted" in out, out
    for greeting in (hello("Lee", lan.new_token()), hello("Lee")):
        reply, after = yield from request(
            greeting, protocol.message("ping"), port=LAN_PORT, token=token, tls=False
        )
        assert reply["payload"]["code"] == "permission_denied" and after is None, reply
    yield from ping()
    log("without TLS: right token in hello admitted; wrong and missing token refused and closed")

    prefs.lan_security = "TLS"
    if GUI:  # the background clipboard is not the desktop's; restore the user's afterwards
        saved = bpy.context.window_manager.clipboard
        bpy.ops.spatial_modeling.copy_session_token()
        copied = bpy.context.window_manager.clipboard
        bpy.context.window_manager.clipboard = saved
        assert copied == token, "Copy did not put the token on the clipboard"
    bpy.ops.spatial_modeling.new_session_token()
    assert prefs.session_token != token and listening(LAN_PORT)
    yield from ping(LAN_PORT, token=prefs.session_token)
    try:
        Client(port=LAN_PORT, token=token).close()
        raise AssertionError("the old token still works after New Session Token")
    except lan.HandshakeError:
        pass
    log("New Session Token restarts the LAN port; the old token stops working"
        + ("; Copy puts the token on the clipboard" if GUI else ""))


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
    yield from lan_checks(prefs)

    prefs.role = "CLIENT"
    assert_stopped()
    prefs.role = "HOST"
    assert listening() and listening(LAN_PORT)
    yield from ping()
    yield from ping(LAN_PORT, token=prefs.session_token)
    log("role Client stops the server and the LAN port; role Host starts both again")

    blend = Path(tempfile.mkdtemp()) / "other.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True)
    old = mod("host")._server
    held = Client(port=PORT)
    held_lan = Client(port=LAN_PORT, token=prefs.session_token)
    yield from wait(lambda: len(old._writers) == 2, "the server to accept both connections")
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    assert held.recv() is None, "a connection survived loading another file"
    assert held_lan.recv() is None, "a LAN connection survived loading another file"
    held.close()
    held_lan.close()
    assert mod("host")._server not in (None, old) and listening() and listening(LAN_PORT)
    yield from ping()
    yield from ping(LAN_PORT, token=prefs.session_token)
    log("loading another .blend closes connections and restarts both ports")

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
    mode = "GUI Blender" if GUI else "blender -b" if bpy.app.binary_path else "bpy module"
    log(f"{'PASS' if code == 0 else 'FAIL'} ({mode}, Python {sys.version.split()[0]})")
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

"""Install the add-on into a real Blender and check the Host role: lifecycle, ping, LAN port, Connecting.

BLENDER_USER_RESOURCES must point at a throwaway directory, so your own Blender
preferences and extensions are untouched:

  BLENDER_USER_RESOURCES=$(mktemp -d) python tests/backend/blender_check.py   # bpy module
  BLENDER_USER_RESOURCES=$(mktemp -d) blender --factory-startup --python tests/backend/blender_check.py

In bpy-module mode timers never fire, so this script calls the add-on's drain
function itself. In GUI Blender the add-on's own timer does it. If
SPATIAL_MODELING_CHECK_MESSAGES names a file, every message received is written
there as JSON lines, so test_blender.py can check them against contracts/schemas
(Blender has no jsonschema). test_blender.py runs both modes from pytest. Exits 0
if every check passed.

The LAN port is checked on 127.0.0.1, so nothing is exposed on this PC's
network, with clients both inside this Blender and in a separate process
(ping_client.py run by this Blender's own Python, sys.executable).
"""

import json
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
import hello_client
from ping_client import TOKEN_ENV, Client, hello, lan, protocol

ADDON_DIR = HERE.parents[1] / "blender_addon" / "spatial_modeling"
MODULE = "bl_ext.user_default.spatial_modeling"
PORT = 8765
LAN_PORT = lan.PORT
GUI = not bpy.app.background
RECEIVED = []  # every message any Peer got, for the schema check


def log(*args):
    print("[blender_check]", *args, flush=True)


class Peer(Client):
    """A client that records what it receives. With a token, on the LAN port."""

    def __init__(self, port=PORT, **client_args):
        super().__init__(port=port, **client_args)

    def recv(self):
        msg = super().recv()
        if msg is not None:
            RECEIVED.append(msg)
        return msg


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


def off_thread(fn, what):
    """Run fn() on a worker thread, like an external client; yields until it returns."""
    box = []

    def run():
        try:
            box.append((True, fn()))
        except Exception as e:  # noqa: BLE001 - re-raised on the main thread
            box.append((False, e))

    threading.Thread(target=run, daemon=True).start()
    yield from wait(lambda: box, what)
    ok, value = box[0]
    if not ok:
        raise value
    return value


def request(*msgs, port=PORT, **client_args):
    """Send msgs from a worker thread, like an external client; yields until the replies.

    Returns the reply to each message, None after the host closed the connection.
    """

    def run():
        with Peer(port=port, **client_args) as client:
            replies = []
            for msg in msgs:
                try:
                    client.send(msg)
                    replies.append(client.answer_to(msg))
                except (BrokenPipeError, ConnectionResetError):
                    replies.append(None)  # the host had closed the connection
            return replies

    replies = yield from off_thread(run, f"a reply to {msgs[-1]['type']}")
    return replies if len(msgs) > 1 else replies[0]


def ping(port=PORT, **client_args):
    msg = protocol.message("ping")
    reply = yield from request(msg, port=port, **client_args)
    assert reply["type"] == "pong" and reply["re"] == msg["id"], reply


def joined(name, via=None, **hello_args):
    """Connect (via: Peer arguments) and join; yields until welcomed.

    Returns (peer, welcome payload, session.update).
    """
    peer = Peer(**(via or {}))
    msgs = yield from off_thread(lambda: hello_client.join(peer, name=name, **hello_args),
                                 f"{name}'s welcome")
    assert [m and m["type"] for m in msgs] == ["welcome", "scene.snapshot", "session.update"], msgs
    welcome, snapshot, update = msgs
    assert snapshot["payload"] == {
        "document": welcome["payload"]["document"], "objects": [], "sketches": []
    }, snapshot
    return peer, welcome["payload"], update


def refused(code, via=None, **hello_args):
    """Send a hello that must be refused with `code` and the connection closed."""
    peer = Peer(**(via or {}))
    msg = hello_client.hello(**hello_args)
    peer.send(msg)
    reply, after = yield from off_thread(lambda: (peer.recv(), peer.recv()), f"error {code}")
    peer.close()
    assert reply["type"] == "error" and reply["payload"]["code"] == code, reply
    assert reply["re"] == msg["id"] and after is None, (reply, after)
    return reply["payload"]


def names(update):
    return [p["name"] for p in update["payload"]["participants"]]


def next_update(peer, what):
    return (yield from off_thread(peer.recv, what))


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


def connecting():
    host, server, session = mod("host"), mod("server"), mod("session")
    scene = bpy.context.scene
    units = scene.unit_settings
    units.system, units.length_unit, units.scale_length = "METRIC", "MILLIMETERS", 0.001
    units.system_rotation = "RADIANS"
    dirty = bpy.data.is_dirty

    msg = protocol.message("command")
    reply = yield from request(msg)
    assert reply["payload"]["code"] == "permission_denied" and reply["re"] == msg["id"], reply

    talia, welcome, update = yield from joined("Talia")
    doc = welcome["document"]
    prefs = bpy.context.preferences.addons[MODULE].preferences
    assert welcome["session_id"] == prefs.session_id and session.is_uuid(prefs.session_id)
    assert welcome["host_epoch"] == host._session.host_epoch
    assert welcome["can_edit"] is True and welcome["app"] == session.APP
    assert session.is_uuid(doc["id"]) and session.is_uuid(doc["open_epoch"])
    assert scene["spatial_modeling_document_id"] == doc["id"], "document ID not stored in the scene"
    assert doc["name"] is None and doc["revision"] == 0 and doc["dirty"] is dirty, doc
    assert bpy.data.is_dirty is dirty, "storing the document ID marked the file as changed"
    assert doc["units"] == {"system": "METRIC", "length_unit": "MILLIMETERS",
                            "rotation_unit": "RADIANS", "scale_length": 0.001}, doc["units"]
    assert names(update) == ["Host Blender", "Talia"], update
    assert [a["name"] for a in host.participants()] == ["Talia"]
    log("hello -> welcome, scene.snapshot, session.update; document", doc["id"], doc["units"])

    other, _, update = yield from joined("Second")
    assert names(update) == ["Host Blender", "Talia", "Second"]
    update = yield from next_update(talia, "Talia's session.update for Second")
    assert names(update) == ["Host Blender", "Talia", "Second"], update
    other.close()
    update = yield from next_update(talia, "Talia's session.update after Second left")
    assert names(update) == ["Host Blender", "Talia"], update
    log("join and leave: everyone gets session.update")

    yield from refused("permission_denied", role="blender-client")
    log("a blender-client hello on 8765 is refused with permission_denied and closed")

    server.HEARTBEAT_TIMEOUT = 0.5
    try:
        silent, _, _ = yield from joined("Silent")
        update = yield from next_update(talia, "Talia's session.update for Silent")
        assert names(update)[-1] == "Silent"
        update = yield from next_update(talia, "Silent to time out")
        assert names(update) == ["Host Blender", "Talia"], update
        assert (yield from off_thread(silent.recv, "Silent's socket to close")) is None
        silent.close()
    finally:
        server.HEARTBEAT_TIMEOUT = 6.0
    log("heartbeat: a participant silent for the timeout is closed and leaves")
    talia.close()


def edits_are_undo_steps():
    # An edit through undoable() is its own Undo step, not merged into the previous one.
    server, host = mod("server"), mod("host")

    def add_cube(msg, conn):
        bpy.ops.mesh.primitive_cube_add(location=(0, 3, 0))
        return protocol.message("test.done", re=msg["id"])

    server.HANDLERS["test.add_cube"] = host.undoable("Add Cube")(add_cube)
    bpy.data.objects["Cube"].location.x = 5
    bpy.ops.ed.undo_push(message="Move Cube")
    count = len(bpy.data.objects)
    peer, _, _ = yield from joined("Undo tester")
    msg = protocol.message("test.add_cube")
    peer.send(msg)
    reply = yield from off_thread(lambda: peer.answer_to(msg), "test.done")
    peer.close()
    del server.HANDLERS["test.add_cube"]
    assert reply["type"] == "test.done" and len(bpy.data.objects) == count + 1, reply
    bpy.ops.ed.undo()
    assert len(bpy.data.objects) == count, "Undo did not remove the added cube"
    assert bpy.data.objects["Cube"].location.x == 5, "Undo also reverted the earlier edit"
    bpy.ops.ed.redo()
    assert len(bpy.data.objects) == count + 1, "Redo did not restore the cube"
    log("undoable(): one Undo reverts exactly the handler's edit; Redo restores it")


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

    # The Client role joins over TLS and shares the session with the VR app on 8765.
    via_tls = {"port": LAN_PORT, "token": token}
    talia, _, _ = yield from joined("Talia")
    lee, welcome, update = yield from joined("Lee", via=via_tls, role="blender-client")
    assert welcome["can_edit"] is False, welcome  # until P3A-W-3
    assert names(update) == ["Host Blender", "Talia", "Lee"], update
    update = yield from next_update(talia, "Talia's session.update for Lee")
    assert [(p["name"], p["role"]) for p in update["payload"]["participants"]] == [
        ("Host Blender", "host"), ("Talia", "vr"), ("Lee", "blender-client")], update
    lee.close()
    update = yield from next_update(talia, "Talia's session.update after Lee left")
    assert names(update) == ["Host Blender", "Talia"], update
    talia.close()
    yield from refused("permission_denied", via=via_tls, name="VR on LAN")
    yield from refused("unsupported_version", via=via_tls, role="blender-client", version="0.0.1")
    log("over TLS: Client role welcomed read-only, both ports see each other join and leave; "
        "vr on the LAN port and another add-on version are refused")

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
    assert code == 0 and "hello accepted: got welcome" in out, out
    for greeting in (hello("Lee", lan.new_token()), hello("Lee")):
        reply, after = yield from request(
            greeting, protocol.message("ping"), port=LAN_PORT, token=token, tls=False
        )
        assert reply["payload"]["code"] == "permission_denied" and after is None, reply
    via_plain = {"port": LAN_PORT, "token": token, "tls": False}
    lee, welcome, _ = yield from joined("Lee", via=via_plain, role="blender-client", token=token)
    lee.close()
    yield from ping()
    assert lan.normalize_token(token) not in json.dumps(RECEIVED).replace("-", "").lower(), (
        "the token came back in a message")
    log("without TLS: right token in hello welcomed; wrong and missing token refused and "
        "closed; no message ever carried the token")

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


def role_switch(prefs):
    host = mod("host")
    session_id, host_epoch = host._session.session_id, host._session.host_epoch
    prefs.role = "CLIENT"
    assert_stopped()
    prefs.role = "HOST"
    assert listening() and listening(LAN_PORT)
    yield from ping()
    yield from ping(LAN_PORT, token=prefs.session_token)
    peer, welcome, _ = yield from joined("After restart")
    peer.close()
    assert welcome["session_id"] == session_id and welcome["host_epoch"] != host_epoch
    log("role Client stops the server and the LAN port; role Host starts both again; "
        "same session_id, new host_epoch")


def document_identity(prefs):
    host = mod("host")
    held, welcome, _ = yield from joined("Before load")
    before = welcome["document"]

    blend = Path(tempfile.mkdtemp()) / "other.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True)
    old = host._server
    held_lan = Peer(port=LAN_PORT, token=prefs.session_token)
    yield from wait(lambda: len(old._writers) == 2, "the server to accept both connections")
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    assert (yield from off_thread(held.recv, "the held connection to close")) is None, (
        "a connection survived loading another file")
    assert held_lan.recv() is None, "a LAN connection survived loading another file"
    held.close()
    held_lan.close()
    assert host._server not in (None, old) and listening() and listening(LAN_PORT)
    yield from ping()
    yield from ping(LAN_PORT, token=prefs.session_token)
    peer, welcome, _ = yield from joined("After load")
    peer.close()
    loaded = welcome["document"]
    assert loaded["id"] == before["id"], "the document ID did not survive save and reopen"
    assert loaded["open_epoch"] != before["open_epoch"]
    assert loaded["name"] == "other.blend" and loaded["revision"] == 0, loaded
    # bpy-module Blender keeps is_dirty set across this load after the Undo check above;
    # GUI Blender clears it. Either way the host must report Blender's own flag.
    assert loaded["dirty"] is bpy.data.is_dirty, loaded
    if GUI:
        assert loaded["dirty"] is False, loaded
    log("loading another .blend closes connections on both ports and restarts them; "
        "same document ID, new open epoch")

    stale = {"id": before["id"], "open_epoch": before["open_epoch"]}
    via_tls = {"port": LAN_PORT, "token": prefs.session_token}
    error = yield from refused("wrong_document", via=via_tls, name="Stale", role="blender-client",
                               document=stale)
    assert error["details"]["document"] == {
        k: loaded[k] for k in ("id", "open_epoch", "name")}, error
    current = {"id": loaded["id"], "open_epoch": loaded["open_epoch"]}
    peer, _, _ = yield from joined("Current", via=via_tls, role="blender-client", document=current)
    peer.close()
    log("Client role expecting the old open epoch gets wrong_document; the current one is welcomed")

    bpy.ops.wm.revert_mainfile()
    peer, welcome, _ = yield from joined("After revert")
    peer.close()
    reverted = welcome["document"]
    assert reverted["id"] == loaded["id"] and reverted["open_epoch"] != loaded["open_epoch"]
    bpy.ops.wm.read_homefile()
    peer, welcome, _ = yield from joined("New file")
    peer.close()
    fresh = welcome["document"]
    assert fresh["id"] != loaded["id"] and fresh["name"] is None, fresh
    log("revert keeps the ID with a new open epoch; a new file gets a new document ID")


def checks():
    install()
    addon_utils.enable(MODULE, default_set=True)
    assert listening(), "nothing listens on 8765 after enabling in Host role"
    assert bpy.app.timers.is_registered(mod("host")._drain)
    log("enabled in Host role:", mod("host").status)

    server = mod("server")
    threads = []

    def recording_ping(msg, conn):
        threads.append(threading.get_ident())
        return server.ping(msg, conn)

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

    yield from connecting()
    yield from edits_are_undo_steps()
    prefs = bpy.context.preferences.addons[MODULE].preferences
    yield from lan_checks(prefs)
    yield from role_switch(prefs)
    yield from document_identity(prefs)

    for _ in range(2):
        addon_utils.disable(MODULE, default_set=True)
        assert_stopped()
        host = mod("host")
        assert host._on_load_pre not in bpy.app.handlers.load_pre
        assert host._on_save_pre not in bpy.app.handlers.save_pre
        assert host._on_load_post not in bpy.app.handlers.load_post
        addon_utils.enable(MODULE, default_set=True)
        assert listening()
        assert bpy.app.handlers.load_pre[:].count(host._on_load_pre) == 1
        yield from ping()
    addon_utils.disable(MODULE, default_set=True)
    assert_stopped()
    log("disable/enable twice: port, timer and load handlers come and go cleanly")


def finish(code):
    out = os.environ.get("SPATIAL_MODELING_CHECK_MESSAGES")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(msg) + "\n" for msg in RECEIVED)
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

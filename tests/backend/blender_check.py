"""Install the add-on into a real Blender and check the Host role: lifecycle, ping, LAN port,
Connecting, the live scene (snapshots and scene.update for direct edits, Undo/Redo, add,
duplicate and delete, on both ports) and native commands.

BLENDER_USER_RESOURCES must point at a throwaway directory, so your own Blender
preferences and extensions are untouched:

  BLENDER_USER_RESOURCES=$(mktemp -d) python tests/backend/blender_check.py   # bpy module
  BLENDER_USER_RESOURCES=$(mktemp -d) blender --factory-startup --python tests/backend/blender_check.py

In bpy-module mode timers never fire and nothing evaluates the depsgraph, so this
script calls the add-on's drain function and evaluates the depsgraph itself. In
GUI Blender the add-on's own timer and Blender's event loop do it. If
SPATIAL_MODELING_CHECK_MESSAGES names a file, every message received is written
there as JSON lines, so test_blender.py can check them against contracts/schemas
(Blender has no jsonschema). test_blender.py runs both modes from pytest. Exits 0
if every check passed.

The LAN port is checked on 127.0.0.1, so nothing is exposed on this PC's
network, with clients both inside this Blender and in a separate process
(ping_client.py run by this Blender's own Python, sys.executable).

The command check edits a millimeter scene from a VR-role client, reads every
result back from Blender's own data, checks Undo/Redo, deduplication and
receipts, saves, and reopens the file in a fresh Blender process. Then the
Client role edits once with "Let the Client role edit (test only)" on.

The recovery check (P5) drops the Client role between a command and its result,
rejoins and gets the true receipt with receipt.query; forces an unknown outcome
and sees writes refused on both ports until the add-on's timer sends both the
fresh snapshot; and restarts the server, after which the old requests are
answered `unknown`.

The lease check (P3B) has two VR clients lease objects in this Blender: the
same object conflicts and a different one doesn't, a second object sharing the
mesh is covered, Undo is refused while the other client holds a lease, and a
closed connection frees its leases.
"""

import json
import math
import os
import socket
import ssl
import struct
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
ID = "spatial_modeling_id"
GEOMETRY_TYPES = {"MESH", "CURVE", "SURFACE", "FONT", "META"}
RECEIVED = []  # every message any Peer got, for the schema check
SNAPSHOTS = {}  # name of whoever joined -> the objects of their snapshot, by object name


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
    SNAPSHOTS[name] = assert_scene(snapshot["payload"], welcome["payload"]["document"])
    return peer, welcome["payload"], update


def assert_scene(payload, doc):
    """payload is a snapshot of this Blender's view layer for doc; returns its objects by name."""
    assert payload["document"] == doc and payload["sketches"] == [], (payload["document"], doc)
    objects = {o["name"]: o for o in payload["objects"]}
    view_layer = bpy.context.view_layer
    assert set(objects) == {o.name for o in view_layer.objects}, sorted(objects)
    for obj in view_layer.objects:
        record = objects[obj.name]
        assert record["id"] == obj.get(ID) and record["type"] == obj.type, (obj.name, record)
        assert (record["mesh"] is not None) == (obj.type in GEOMETRY_TYPES), obj.name
        assert record["generation"] <= doc["revision"], record
    return objects


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
    # The unit change above is a change like any other: a fresh snapshot at revision 1.
    assert doc["name"] is None and doc["revision"] == 1 and doc["dirty"] is dirty, doc
    cube = SNAPSHOTS["Talia"]["Cube"]
    assert cube["generation"] == 1 and cube["mesh"]["positions"][:3] == [0.001] * 3, cube
    assert bpy.data.is_dirty is dirty, "storing the document ID marked the file as changed"
    assert doc["units"] == {"system": "METRIC", "length_unit": "MILLIMETERS",
                            "rotation_unit": "RADIANS", "scale_length": 0.001}, doc["units"]
    assert names(update) == ["Host Blender", "Talia"], update
    assert [a["name"] for a in host.participants()] == ["Talia"]
    log("hello -> welcome, scene.snapshot, session.update; document", doc["id"], doc["units"],
        "objects", sorted(SNAPSHOTS["Talia"]))

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
    clipboard = GUI and owns_clipboard()
    if clipboard:  # the background clipboard is not the desktop's; restore the user's afterwards
        wm = bpy.context.window_manager
        saved = wm.clipboard
        bpy.ops.spatial_modeling.copy_session_token()
        copied = wm.clipboard
        wm.clipboard = saved
        assert copied == token, "Copy did not put the token on the clipboard"
    elif GUI:
        log("NOTE: skipped the Copy Session Token check: this Blender can't own the clipboard "
            "(no focused window, for example on a headless display)")
    bpy.ops.spatial_modeling.new_session_token()
    assert prefs.session_token != token and listening(LAN_PORT)
    yield from ping(LAN_PORT, token=prefs.session_token)
    try:
        Client(port=LAN_PORT, token=token).close()
        raise AssertionError("the old token still works after New Session Token")
    except lan.HandshakeError:
        pass
    log("New Session Token restarts the LAN port; the old token stops working"
        + ("; Copy puts the token on the clipboard" if clipboard else ""))


def owns_clipboard():
    """Whether a value written to the clipboard reads back, which needs a focused window."""
    wm = bpy.context.window_manager
    saved = wm.clipboard
    probe = f"spatial_modeling clipboard probe {time.monotonic()}"
    wm.clipboard = probe
    owned = wm.clipboard == probe
    wm.clipboard = saved
    return owned


class Watcher:
    """Collects everything a joined peer receives, on its own thread, like a client's reader."""

    def __init__(self, peer):
        self.peer = peer
        self.messages = []
        peer.sock.settimeout(None)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while (msg := self.peer.recv()) is not None:
                self.messages.append(msg)
        except OSError:
            pass

    def updates(self, since=0):
        return [m["payload"] for m in self.messages[since:] if m["type"] == "scene.update"]


def by_name(update):
    return {o["name"]: o for o in update["objects"]}


def scene_update(watchers, marks, what, test):
    """Yield until each watcher got a scene.update passing test() after its mark; return it.

    Every watcher must get the same updates, in the same order.
    """
    def found():
        return all(any(test(u) for u in w.updates(m)) for w, m in zip(watchers, marks))

    yield from wait(found, what)
    first = [next(u for u in w.updates(m) if test(u)) for w, m in zip(watchers, marks)]
    assert all(u == first[0] for u in first), f"clients got different updates for {what}"
    return first[0]


def select_only(obj):
    view_layer = bpy.context.view_layer
    for other in view_layer.objects:
        other.select_set(other == obj)
    view_layer.objects.active = obj


def live_scene(prefs):
    """Direct edits in this Blender reach the VR app and the Client role as scene.update."""
    server, sync = mod("server"), mod("sync")
    server.HEARTBEAT_TIMEOUT = 120.0  # the watchers don't ping
    try:
        yield from watched_edits(prefs, sync)
    finally:
        server.HEARTBEAT_TIMEOUT = 6.0


def watched_edits(prefs, sync):
    talia, _, _ = yield from joined("Talia")
    via_tls = {"port": LAN_PORT, "token": prefs.session_token}
    lee, welcome, _ = yield from joined("Lee", via=via_tls, role="blender-client")
    assert welcome["can_edit"] is False, welcome
    assert SNAPSHOTS["Lee"] == SNAPSHOTS["Talia"], "the Client role got another snapshot"
    watchers = [Watcher(talia), Watcher(lee)]
    scale = bpy.context.scene.unit_settings.scale_length
    log("Client role over TLS gets the same snapshot as the VR app, read-only")

    def marks():
        return [len(w.messages) for w in watchers]

    def changes(name, key=None):
        return lambda u: name in by_name(u) and (key is None or key(by_name(u)[name]))

    cube = bpy.data.objects["Cube"]
    cube_id = cube[ID]
    m = marks()
    revision = mod("host")._document.revision
    cube.location.x += 10  # a direct edit, made by this timer-driven script
    x = round(cube.location.x * scale, 6)
    u = yield from scene_update(watchers, m, "the Cube's move", changes("Cube"))
    moved = by_name(u)["Cube"]
    assert moved["id"] == cube_id and "mesh" not in moved, moved
    assert moved["transform"]["location"][0] == x, moved
    assert moved["generation"] == u["document"]["revision"] > revision, u["document"]
    log("a direct edit reaches both clients as scene.update, without the mesh")

    bpy.ops.ed.undo_push(message="Before drag")
    m = marks()
    started = time.monotonic()
    for step in range(1, 41):  # 40 mouse moves, one per Blender event loop turn
        cube.location.y = step
        yield
    took = time.monotonic() - started
    final = round(40 * scale, 6)
    yield from scene_update(watchers, m, "the end of the drag",
                            changes("Cube", lambda o: o["transform"]["location"][1] == final))
    stream = [u for u in watchers[0].updates(m[0]) if "Cube" in by_name(u)]
    revisions = [u["document"]["revision"] for u in stream]
    assert revisions == sorted(set(revisions)), revisions
    assert all(len(u["objects"]) == 1 and "mesh" not in u["objects"][0] for u in stream), stream
    assert 2 <= len(stream) <= took / sync.MIN_INTERVAL + 3, (len(stream), took)
    sizes = sorted(len(protocol.encode(protocol.message("scene.update", u))) for u in stream)
    log(f"drag: 40 moves in {took:.2f} s -> {len(stream)} scene.updates of "
        f"{sizes[0]}-{sizes[-1]} bytes, revisions {revisions[0]}..{revisions[-1]}")

    bpy.ops.ed.undo_push(message="Drag")
    m = marks()
    bpy.ops.ed.undo()
    u = yield from scene_update(watchers, m, "the Undo of the drag", changes("Cube"))
    assert by_name(u)["Cube"]["transform"]["location"][1] == 0, u
    m = marks()
    bpy.ops.ed.redo()
    u = yield from scene_update(watchers, m, "the Redo of the drag", changes("Cube"))
    assert by_name(u)["Cube"]["transform"]["location"][1] == final, u
    assert sync.find_object(cube_id).location.y == 40
    log("Undo and Redo send the Cube back and forth with the same ID")

    m = marks()
    bpy.ops.mesh.primitive_uv_sphere_add(radius=5, location=(0, 0, 50))
    bpy.ops.ed.undo_push(message="Add Sphere")
    u = yield from scene_update(watchers, m, "the new Sphere", changes("Sphere"))
    sphere = by_name(u)["Sphere"]
    assert sphere["mesh"] and len(sphere["mesh"]["indices"]) > 0, sphere
    sphere_id = sphere["id"]

    select_only(sync.find_object(cube_id))  # Undo/Redo replaced the Cube: look it up again
    m = marks()
    bpy.ops.object.duplicate()
    copy_name = bpy.context.view_layer.objects.active.name
    bpy.ops.ed.undo_push(message="Duplicate")
    u = yield from scene_update(watchers, m, "the duplicate", changes(copy_name))
    copy = by_name(u)[copy_name]
    assert copy["id"] not in (cube_id, sphere_id) and copy["mesh"] is not None, copy
    assert bpy.data.objects["Cube"][ID] == cube_id, "the original lost its ID to the duplicate"

    m = marks()
    bpy.data.objects.remove(bpy.data.objects["Sphere"])
    bpy.ops.ed.undo_push(message="Delete Sphere")
    u = yield from scene_update(watchers, m, "the deletion", lambda u: sphere_id in u["removed"])
    assert u["objects"] == [], u
    log("add, duplicate (new ID) and delete reach both clients")

    m = marks()
    bpy.ops.ed.undo()  # the Sphere comes back with its ID
    u = yield from scene_update(watchers, m, "the Undo of the deletion", changes("Sphere"))
    assert by_name(u)["Sphere"]["id"] == sphere_id and by_name(u)["Sphere"]["mesh"], u
    m = marks()
    bpy.ops.ed.undo()  # and the duplicate goes away
    u = yield from scene_update(watchers, m, "the Undo of the duplicate",
                                lambda u: copy["id"] in u["removed"])
    m = marks()
    bpy.ops.ed.redo()
    u = yield from scene_update(watchers, m, "the Redo of the duplicate", changes(copy_name))
    assert by_name(u)[copy_name]["id"] == copy["id"], "the duplicate got another ID on Redo"
    log("Undo/Redo of delete and duplicate: the objects come back with the same IDs")

    m = marks()
    bpy.data.objects["Cube"].modifiers.new("Bevel", "BEVEL")
    u = yield from scene_update(watchers, m, "the Bevel", changes("Cube", lambda o: "mesh" in o))
    assert len(by_name(u)["Cube"]["mesh"]["indices"]) > 36, u
    log("a modifier sends the evaluated mesh")
    talia.close()
    lee.close()


def f32(x):
    """x as Blender stores it: a 32-bit float."""
    return struct.unpack("f", struct.pack("f", x))[0]


def ask(peer, msg):
    """Send msg from a worker thread; yields until its reply. Returns (messages before, reply)."""

    def run():
        peer.send(msg)
        before = []
        while (reply := peer.recv()) is not None and reply.get("re") != msg["id"]:
            before.append(reply)
        return before, reply

    return (yield from off_thread(run, f"the reply to {msg['payload'].get('op', msg['type'])}"))


class Commander:
    """Sends one joined client's commands, built as an up-to-date client would."""

    def __init__(self, peer, welcome):
        self.peer, self.welcome = peer, welcome

    def command(self, op, target=None, args=None, generation=None):
        """A command at the current revision, for the target's current generation."""
        w = self.welcome
        payload = {
            "session_id": w["session_id"], "host_epoch": w["host_epoch"],
            "document_id": w["document"]["id"], "open_epoch": w["document"]["open_epoch"],
            "actor_id": w["actor_id"],
            "base_revision": mod("host")._session.document()["revision"],  # after a flush
            "source": "ui", "op": op, "args": args or {},
        }
        if target is not None:
            current = mod("sync").generation(target)
            payload["target"] = {"id": target,
                                 "generation": current if generation is None else generation}
        return protocol.message("command", payload)

    def send(self, msg):
        """Yields until msg's result. Returns (receipt, the scene.updates before it)."""
        before, reply = yield from ask(self.peer, msg)
        assert reply is not None and reply["type"] == "result", reply
        assert all(m["type"] == "scene.update" for m in before), [m["type"] for m in before]
        return reply["payload"], [m["payload"] for m in before]

    def run(self, op, target=None, args=None, watcher=None):
        """Send a command that must be applied. Returns (receipt, command, its scene.update).

        Exactly one scene.update arrives before the result, with the receipt's revision.
        The watcher (another client) must get it too, then the receipt as activity.
        """
        msg = self.command(op, target, args)
        receipt, before = yield from self.send(msg)
        assert receipt["outcome"] == "applied", receipt
        assert len(before) == 1, f"{len(before)} scene.updates before the result of {op}: {before}"
        (update,) = before
        assert update["document"]["revision"] == receipt["revision"], (update, receipt)
        if watcher is not None:
            got = yield from off_thread(lambda: [watcher.recv(), watcher.recv()],
                                        f"the watcher's update and activity for {op}")
            assert [m["type"] for m in got] == ["scene.update", "activity"], got
            assert got[0]["payload"] == update, "the watcher got another update"
            assert got[1]["payload"] == receipt, (got[1], receipt)
        return receipt, msg, update


def by_id(object_id):
    return next((o for o in bpy.data.objects if o.get(ID) == object_id), None)


def selection():
    layer = bpy.context.view_layer
    active = layer.objects.active
    return sorted(o.name for o in layer.objects if o.select_get()), active and active.name


REOPEN = (
    "import bpy, json\n"
    "print('REOPENED ' + json.dumps({o.get('spatial_modeling_id') or o.name: {'name': o.name,"
    " 'location': list(o.location), 'rotation': list(o.rotation_euler), 'scale': list(o.scale),"
    " 'dimensions': list(o.dimensions)} for o in bpy.data.objects}), flush=True)\n"
)


def reopened(blend):
    """Open blend in a fresh Blender process; yields until done. Returns its objects by ID."""
    if bpy.app.binary_path:
        cmd = [bpy.app.binary_path, "-b", "--factory-startup", str(blend), "--python-expr", REOPEN]
    else:  # the bpy module: a fresh Python with bpy
        opener = "import sys, bpy\nbpy.ops.wm.open_mainfile(filepath=sys.argv[1])\n"
        cmd = [sys.executable, "-c", opener + REOPEN, str(blend)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, text=True)
    out = yield from off_thread(lambda: proc.communicate(timeout=120)[0],
                                "the fresh Blender to open the file")
    line = next((x for x in out.splitlines() if x.startswith("REOPENED ")), None)
    assert proc.returncode == 0 and line, out
    return json.loads(line.removeprefix("REOPENED "))


def nobody_joined():
    """Yields until earlier clients have left, so their session.updates can't arrive later."""
    yield from wait(lambda: not mod("host").participants(), "the earlier clients to leave")


def commands(prefs):
    """Commands from the VR app and the Client role change Blender natively (P3A)."""
    server = mod("server")
    server.HEARTBEAT_TIMEOUT = 120.0  # these clients don't ping
    try:
        yield from native_commands(prefs)
        yield from lease_checks()
        yield from client_role_commands(prefs)
    finally:
        server.HEARTBEAT_TIMEOUT = 6.0


def native_commands(prefs):
    # The scene is in millimeters (connecting() set it): 1 Blender unit is 1 mm.
    host = mod("host")
    blend = Path(tempfile.mkdtemp()) / "assembly.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))  # Save As happens at the host desktop
    cube = bpy.data.objects["Cube"]
    cube_id = cube[ID]
    cube.location, cube.rotation_euler, cube.scale = (5, 0, 0), (0, 0, 0), (1, 1, 1)
    bpy.ops.ed.undo_push(message="Command check set-up")
    kept = selection()

    yield from nobody_joined()
    talia, welcome, _ = yield from joined("Talia")
    watcher, _, _ = yield from joined("Jihyeon")
    yield from next_update(talia, "Talia's session.update for Jihyeon")
    prefs.host_name = "  Waaberi at the desk "
    for peer in (talia, watcher):
        update = yield from next_update(peer, "session.update with the host's name")
        assert update["payload"]["participants"][0] == {
            **host._session.host, "name": "Waaberi at the desk", "role": "host"}, update
    prefs.host_name = ""
    for peer in (talia, watcher):
        update = yield from next_update(peer, "session.update with the default name")
        assert names(update)[0] == "Host Blender", update
    log("'Your name' renames the host participant for everyone; blank means Host Blender")

    vr = Commander(talia, welcome)
    add, _, update = yield from vr.run("object.add", args={
        "primitive": "cylinder", "location": [0, 0.03, 0.005], "dimensions": [0.02, 0.02, 0.04]},
        watcher=watcher)
    (new_id,) = add["created"]
    new = by_id(new_id)
    assert new is not None and new.name == "Cylinder" and new.type == "MESH", new
    assert all(abs(a - b) < 1e-4 for a, b in zip(new.dimensions, (20, 20, 40), strict=True)), (
        tuple(new.dimensions))
    assert tuple(new.location) == (0, 30, 5), tuple(new.location)
    sent = by_name(update)["Cylinder"]
    assert sent["id"] == new_id and sent["generation"] == add["revision"] and sent["mesh"], sent
    assert sent["transform"]["location"] == [0, 0.03, 0.005], sent["transform"]
    log(f"object.add: {add['summary']}; {tuple(new.dimensions)} mm at {tuple(new.location)} mm; "
        "its scene.update (with the mesh) came before the result")

    move, move_msg, update = yield from vr.run("object.move", cube_id, {"by": [0.01, 0, 0]},
                                               watcher=watcher)
    assert move["summary"] == "Moved Cube 10 mm along X", move
    assert tuple(cube.location) == (15, 0, 0), tuple(cube.location)
    assert by_name(update)["Cube"]["transform"]["location"] == [0.015, 0, 0], update
    rotate, _, update = yield from vr.run(
        "object.rotate", cube_id, {"by": {"axis": "Z", "angle": math.pi / 2}}, watcher=watcher)
    assert tuple(cube.rotation_euler) == (0, 0, f32(math.pi / 2)), tuple(cube.rotation_euler)
    bpy.context.view_layer.update()
    m = cube.matrix_world
    exact = ((0, -1, 0, 15), (1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
    worst = max(abs(m[i][j] - exact[i][j]) for i in range(4) for j in range(4))
    assert worst < 1e-7, m
    assert by_name(update)["Cube"]["transform"]["rotation"] == [0.707107, 0, 0, 0.707107], update
    scale, scale_msg, _ = yield from vr.run("object.scale", cube_id, {"by": [1, 1, 1.5]},
                                            watcher=watcher)
    assert tuple(cube.scale) == (1, 1, 1.5), tuple(cube.scale)
    delete, _, update = yield from vr.run("object.delete", new_id, watcher=watcher)
    assert by_id(new_id) is None and delete["summary"] == "Deleted Cylinder", delete
    assert update["removed"] == [new_id], update
    assert selection() == kept, "a command changed the host's selection"
    log(f"{move['summary']}: location {tuple(cube.location)} mm; {rotate['summary']}: "
        f"rotation_euler.z == float32(pi/2), world matrix within {worst:.1e} of the exact 90° turn;"
        f" {scale['summary']}; {delete['summary']}; the host's selection stayed")

    undo, _, update = yield from vr.run("history.undo", watcher=watcher)
    assert undo["summary"] == "Undid: Deleted Cylinder", undo
    cube = bpy.data.objects["Cube"]  # Undo reloads Blender's data
    assert by_id(new_id) is not None and tuple(cube.scale) == (1, 1, 1.5), "Undo did more"
    assert by_name(update)["Cylinder"]["id"] == new_id, update
    undo, _, _ = yield from vr.run("history.undo", watcher=watcher)
    assert undo["summary"] == "Undid: Scaled Cube by 1 x 1 x 1.5", undo
    cube = bpy.data.objects["Cube"]
    assert tuple(cube.scale) == (1, 1, 1), tuple(cube.scale)
    assert tuple(cube.rotation_euler) == (0, 0, f32(math.pi / 2)), "Undo reverted the rotation too"
    for summary in ("Redid: Scaled Cube by 1 x 1 x 1.5", "Redid: Deleted Cylinder"):
        redo, _, _ = yield from vr.run("history.redo", watcher=watcher)
        assert redo["summary"] == summary, redo
    cube = bpy.data.objects["Cube"]
    assert tuple(cube.scale) == (1, 1, 1.5) and by_id(new_id) is None
    assert selection() == kept, "Undo or Redo changed the host's selection"
    log("one Undo reverts exactly one command, Redo reapplies it; the host's selection stays")

    again, before = yield from vr.send(scale_msg)  # the same request ID and payload
    assert again == scale and before == [], (again, scale)
    assert tuple(bpy.data.objects["Cube"].scale) == (1, 1, 1.5), "a repeat was applied again"
    changed = json.loads(json.dumps(scale_msg))
    changed["payload"]["args"]["by"] = [2, 2, 2]
    duplicate, _ = yield from vr.send(changed)
    assert duplicate["error"]["code"] == "duplicate_request", duplicate
    stale, _ = yield from vr.send(vr.command("object.move", cube_id, {"by": [0.01, 0, 0]},
                                             generation=move["revision"]))
    assert stale["error"]["code"] == "stale_revision", stale
    assert stale["error"]["details"] == {"generation": mod("sync").generation(cube_id)}, stale
    assert tuple(bpy.data.objects["Cube"].location) == (15, 0, 0)
    query = protocol.message("receipt.query", {"host_epoch": welcome["host_epoch"],
                                               "request_ids": [move_msg["id"], "0" * 32]})
    _, receipts = yield from ask(talia, query)
    assert receipts["payload"] == {"receipts": [move], "missing": ["0" * 32], "unknown": []}, (
        receipts)
    log("a repeated request ID gets the stored result and isn't applied twice; a changed one is "
        "duplicate_request; a stale generation is refused; receipt.query finds receipts")

    assert bpy.data.is_dirty
    saved_at = blend.stat().st_mtime_ns
    save, _, update = yield from vr.run("document.save", watcher=watcher)
    assert save["summary"] == "Saved assembly.blend", save
    assert update["document"]["dirty"] is False and update["objects"] == [], update
    assert blend.stat().st_mtime_ns > saved_at, "the file wasn't written"
    if GUI:
        yield from wait(lambda: not bpy.data.is_dirty, "Blender to clear is_dirty after Save")
    else:  # background Blender never clears is_dirty after a save, and a tick later we say so
        for peer in (talia, watcher):
            msg = yield from next_update(peer, "the dirty flag of background Blender")
            assert msg["type"] == "scene.update" and msg["payload"]["objects"] == [], msg
            assert msg["payload"]["document"]["dirty"] is True, msg
    _, _, update = yield from vr.run("object.move", cube_id, {"by": [0.01, 0, 0]},
                                     watcher=watcher)
    assert update["document"]["dirty"] is True, "the update after Save says nothing changed"
    assert tuple(bpy.data.objects["Cube"].location) == (25, 0, 0)
    log(f"document.save: {save['summary']}, dirty false; the next edit's update says dirty again")
    talia.close()
    watcher.close()

    objects = yield from reopened(blend)
    saved = objects[cube_id]
    assert saved["location"] == [15, 0, 0], saved  # as saved, without the edit after Save
    assert saved["rotation"] == [0, 0, f32(math.pi / 2)], saved
    assert saved["scale"] == [1, 1, 1.5], saved
    assert new_id not in objects, "the deleted cylinder came back"
    log(f"a fresh Blender process reopens {blend.name} with the edits: Cube at "
        f"{saved['location']} mm, rotation {saved['rotation']}, scale {saved['scale']}")


def acquire(welcome, mode, targets):
    w = welcome
    return protocol.message("lease.acquire", {
        "session_id": w["session_id"], "host_epoch": w["host_epoch"],
        "document_id": w["document"]["id"], "open_epoch": w["document"]["open_epoch"],
        "actor_id": w["actor_id"], "mode": mode, "targets": list(targets)})


def leased(peer, welcome, mode, targets):
    """Acquire a lease that must be granted; yields until it is. Returns the lease."""
    before, reply = yield from ask(peer, acquire(welcome, mode, targets))
    assert reply is not None and reply["type"] == "lease.granted", reply
    updates = [m for m in before if m["type"] == "session.update"]
    assert updates and reply["payload"]["lease"] in updates[-1]["payload"]["leases"], before
    return reply["payload"]["lease"]


def session_update(peer, what, until):
    """Yields until peer gets a session.update for which until(payload) is true."""
    while True:
        msg = yield from off_thread(peer.recv, what)
        assert msg is not None, f"the connection closed while waiting for {what}"
        if msg["type"] == "session.update" and until(msg["payload"]):
            return msg["payload"]


def lease_checks():
    """Leases on objects in this Blender (P3B), between two VR clients."""
    host, sync = mod("host"), mod("sync")
    collection = bpy.context.scene.collection
    cube = bpy.data.objects["Cube"]
    twin = bpy.data.objects.new("Cube twin", cube.data)  # a linked duplicate: same mesh
    lone = bpy.data.objects.new("Lone", bpy.data.meshes.new("Lone"))
    collection.objects.link(twin)
    collection.objects.link(lone)
    bpy.ops.ed.undo_push(message="Lease check set-up")
    cube_id, twin_id, lone_id = (sync.object_id(o) for o in (cube, twin, lone))

    yield from nobody_joined()
    talia, tw = (yield from joined("Talia"))[:2]
    jihyeon, jw = (yield from joined("Jihyeon"))[:2]
    yield from next_update(talia, "Talia's session.update for Jihyeon")
    t, j = Commander(talia, tw), Commander(jihyeon, jw)

    lease = yield from leased(talia, tw, "shared", [cube_id])
    assert lease["targets"] == [cube_id, twin_id], (lease, twin_id)
    assert host.may_write([twin]) == lease and host.may_write([lone]) is None
    log(f"Talia's shared lease on Cube also covers {twin.name}, which shares its mesh")

    for target in (cube_id, twin_id):
        _, reply = yield from ask(jihyeon, acquire(jw, "shared", [target]))
        assert reply["type"] == "error" and reply["payload"]["code"] == "lease_conflict", reply
        assert reply["payload"]["details"]["lease"] == lease, reply
    x = twin.location.x
    receipt, _ = yield from j.send(j.command("object.move", twin_id, {"by": [0.001, 0, 0]}))
    assert receipt["error"]["code"] == "lease_conflict", receipt
    assert receipt["error"]["details"]["lease"]["owner"]["name"] == "Talia", receipt
    assert twin.location.x == x, "a refused move changed Blender"
    own = yield from leased(jihyeon, jw, "shared", [lone_id])
    assert own["targets"] == [lone_id], own
    receipt, _, _ = yield from j.run("object.move", lone_id, {"by": [0.001, 0, 0]})
    assert lone.location.x == 1, tuple(lone.location)
    log("Jihyeon: Cube and its twin get lease_conflict (Blender unchanged); a different object "
        "is leased and moved")

    for commander, holder in ((j, "Talia"), (t, "Jihyeon")):
        _, reply = yield from ask(commander.peer, commander.command("history.undo"))
        receipt = reply["payload"]  # Talia also has Jihyeon's move and lease waiting
        assert receipt["error"]["code"] == "lease_conflict", receipt
        assert receipt["error"]["details"]["lease"]["owner"]["name"] == holder, receipt
    assert lone.location.x == 1, "a refused Undo changed Blender"
    log("Undo is refused with lease_conflict for each while the other holds a lease")

    talia.close()
    update = yield from session_update(jihyeon, "the session.update after Talia left",
                                       lambda p: "Talia" not in [a["name"] for a in
                                                                 p["participants"]])
    assert update["leases"] == [own], update
    assert host.may_write([cube]) is None
    receipt, _, _ = yield from j.run("object.move", twin_id, {"by": [0.001, 0, 0]})
    assert twin.location.x == f32(x + 1), tuple(twin.location)
    jihyeon.send(protocol.message("lease.release", {"lease_id": own["lease_id"]}))
    yield from session_update(jihyeon, "the session.update after the release",
                              lambda p: p["leases"] == [])
    receipt, _, _ = yield from j.run("history.undo")
    twin = bpy.data.objects["Cube twin"]  # Undo replaced the data-blocks
    assert twin.location.x == x, "Undo didn't revert the twin's move"
    jihyeon.close()
    log("closing Talia's connection freed her lease (one session.update); Jihyeon then moved "
        "the twin, released her lease and undid the move")


def client_role_commands(prefs):
    # The LAN port is on (lan_checks), with TLS, on 127.0.0.1.
    cube_id = bpy.data.objects["Cube"][ID]
    via_tls = {"port": LAN_PORT, "token": prefs.session_token}
    assert prefs.client_edits is False, "the Client-role flag must be off by default"
    yield from nobody_joined()
    lee, welcome, _ = yield from joined("Lee", via=via_tls, role="blender-client")
    assert welcome["can_edit"] is False, welcome
    x = bpy.data.objects["Cube"].location.x
    lee_commands = Commander(lee, welcome)
    receipt, _ = yield from lee_commands.send(
        lee_commands.command("object.move", cube_id, {"by": [0.001, 0, 0]}))
    assert receipt["error"]["code"] == "permission_denied", receipt
    assert bpy.data.objects["Cube"].location.x == x
    lee.close()

    prefs.client_edits = True  # restarts the server; everyone reconnects
    try:
        talia, _, _ = yield from joined("Talia")
        lee, welcome, _ = yield from joined("Lee", via=via_tls, role="blender-client")
        assert welcome["can_edit"] is True, welcome
        yield from next_update(talia, "Talia's session.update for Lee")
        receipt, _, _ = yield from Commander(lee, welcome).run(
            "object.move", cube_id, {"by": [0.001, 0, 0]}, watcher=talia)
        assert receipt["actor"]["role"] == "blender-client", receipt
        assert bpy.data.objects["Cube"].location.x == f32(x + 1), "Lee's move didn't apply"
        lee.close()
        talia.close()
    finally:
        prefs.client_edits = False
    lee, welcome, _ = yield from joined("Lee", via=via_tls, role="blender-client")
    assert welcome["can_edit"] is False
    lee.close()
    log("Client role: read-only (permission_denied) with the flag off; with it on, can_edit "
        "and its move applies in Blender and reaches VR as activity")


def query(peer, host_epoch, *request_ids):
    """receipt.query from peer; yields until the answer. Returns its payload."""
    msg = protocol.message("receipt.query", {"host_epoch": host_epoch,
                                             "request_ids": list(request_ids)})
    _, reply = yield from ask(peer, msg)
    assert reply["type"] == "receipts", reply
    return reply["payload"]


def quiet(peer):
    """Nothing is waiting for peer: the next message answers a ping. Yields until it does."""
    msg = protocol.message("ping")
    before, reply = yield from ask(peer, msg)
    assert before == [] and reply["type"] == "pong", (before, reply)


def hang_up(peer, msg):
    """Send msg and drop the connection without reading its result. Yields until closed."""

    def run():
        peer.send(msg)
        peer.sock.shutdown(socket.SHUT_WR)
        try:
            while peer.sock.recv(65536):  # never read: the acknowledgement is lost
                pass
        except OSError:
            pass
        peer.close()

    yield from off_thread(run, "the host to close the dropped connection")


def recovery(prefs):
    """P5: reconnect, lost acknowledgement, unknown outcome and host restart, on both ports."""
    server = mod("server")
    server.HEARTBEAT_TIMEOUT = 120.0  # these clients don't ping
    prefs.client_edits = True  # restarts the server; the Client role may edit
    try:
        yield from recovered(prefs)
    finally:
        server.HEARTBEAT_TIMEOUT = 6.0
        prefs.client_edits = False


def recovered(prefs):
    host = mod("host")
    via_tls = {"port": LAN_PORT, "token": prefs.session_token}
    cube_id = bpy.data.objects["Cube"][ID]
    yield from nobody_joined()
    talia, talia_welcome, _ = yield from joined("Talia")
    lee, welcome, _ = yield from joined("Lee", via=via_tls, role="blender-client")
    yield from next_update(talia, "Talia's session.update for Lee")

    # Lost acknowledgement on the LAN port: the move applies, its result never reaches Lee.
    x = bpy.data.objects["Cube"].location.x
    lost = Commander(lee, welcome).command("object.move", cube_id, {"by": [0.001, 0, 0]})
    yield from hang_up(lee, lost)
    got = yield from off_thread(lambda: [talia.recv() for _ in range(3)], "Talia's messages")
    assert [m["type"] for m in got] == ["scene.update", "activity", "session.update"], got
    activity = got[1]["payload"]
    assert activity["request_id"] == lost["id"] and activity["outcome"] == "applied", activity
    assert bpy.data.objects["Cube"].location.x == f32(x + 1), "the lost move didn't apply"

    again, again_welcome, _ = yield from joined("Lee", via=via_tls, role="blender-client")
    yield from next_update(talia, "Talia's session.update for Lee's return")
    assert again_welcome["actor_id"] != welcome["actor_id"]
    scale = bpy.context.scene.unit_settings.scale_length
    sent_x = SNAPSHOTS["Lee"]["Cube"]["transform"]["location"][0]
    assert abs(sent_x - f32(x + 1) * scale) < 1e-6, "the fresh snapshot lacks the lost move"
    yield from quiet(again)  # nothing replayed after the handshake
    answer = yield from query(again, welcome["host_epoch"], lost["id"])
    assert answer == {"receipts": [activity], "missing": [], "unknown": []}, answer
    _, same = yield from ask(again, lost)  # the same request again, old actor_id and all
    assert same["payload"] == activity, same
    assert bpy.data.objects["Cube"].location.x == f32(x + 1), "a resent request applied twice"
    yield from quiet(talia)
    log("lost acknowledgement: Lee dropped before the result, rejoined over TLS with a fresh "
        "snapshot and nothing replayed, and receipt.query gave the true receipt (old actor_id); "
        "resending it returned that receipt and Blender moved once")

    # A direct edit after the reconnect reaches both ports alike.
    bpy.data.objects["Cube"].location.z += 3
    updates = yield from off_thread(lambda: [talia.recv(), again.recv()], "the direct edit")
    assert [m["type"] for m in updates] == ["scene.update"] * 2, updates
    assert updates[0]["payload"] == updates[1]["payload"], "the two ports got different updates"
    log("a direct edit in Blender reaches the Unity port and the LAN port as the same update")

    # Unknown outcome: Blender applied it, the host lost track; writes freeze until reconciled.
    editor, sess = host._commands, host._session
    real_apply, real_snapshot = editor.editor.apply, sess.snapshot

    def apply_then_fail(*args):
        editor.editor.apply = real_apply
        real_apply(*args)
        raise RuntimeError("check: the host lost track after Blender committed")

    def no_snapshot(document):
        raise RuntimeError("check: the scene can't be read yet")

    editor.editor.apply = apply_then_fail
    sess.snapshot = no_snapshot
    try:
        vr = Commander(talia, talia_welcome)
        unknown, before = yield from vr.send(vr.command("object.move", cube_id, {"by": [0.001, 0, 0]}))
        assert unknown["outcome"] == "unknown" and editor.frozen, unknown
        assert len(before) == 1, before
        update = yield from next_update(again, "Lee's update for the unknown move")
        assert update["payload"] == before[0], "the ports got different updates"
        moved = bpy.data.objects["Cube"].location.x
        for peer, w in ((talia, talia_welcome), (again, again_welcome)):
            refused_write, _ = yield from Commander(peer, w).send(
                Commander(peer, w).command("object.move", cube_id, {"by": [0.001, 0, 0]}))
            assert refused_write["error"]["code"] == "permission_denied", refused_write
        assert bpy.data.objects["Cube"].location.x == moved
        yield from quiet(talia)
        yield from quiet(again)
    finally:
        editor.editor.apply = real_apply
        sess.snapshot = real_snapshot
    # The add-on's timer re-reads the scene by itself and sends everyone the fresh snapshot.
    snapshots = yield from off_thread(lambda: [talia.recv(), again.recv()], "the fresh snapshots")
    assert [m["type"] for m in snapshots] == ["scene.snapshot"] * 2, snapshots
    assert snapshots[0]["payload"] == snapshots[1]["payload"]
    assert not editor.frozen
    resumed, _, _ = yield from Commander(again, again_welcome).run(
        "object.move", cube_id, {"by": [0.001, 0, 0]}, watcher=talia)
    assert bpy.data.objects["Cube"].location.x == f32(moved + 1), "writes didn't resume"
    log("unknown outcome: both ports' writes got permission_denied until the add-on's timer "
        "re-read the scene and sent both the same fresh snapshot; then Lee's move applied")

    # Host restart: receipts are gone, and the old ones come back unknown, never missing.
    talia.close()
    again.close()
    yield from nobody_joined()
    old_epoch = again_welcome["host_epoch"]
    prefs.client_edits = False  # a preference change restarts the server
    prefs.client_edits = True
    after, after_welcome, _ = yield from joined("Lee", via=via_tls, role="blender-client")
    assert after_welcome["host_epoch"] != old_epoch
    ids = [lost["id"], unknown["request_id"], resumed["request_id"]]
    answer = yield from query(after, old_epoch, *ids)
    assert answer == {"receipts": [], "missing": [], "unknown": ids}, answer
    x = bpy.data.objects["Cube"].location.x
    old, _ = yield from Commander(after, after_welcome).send(lost)
    assert old["outcome"] == "rejected", old
    assert bpy.data.objects["Cube"].location.x == x, "an old request applied after the restart"
    after.close()
    log("host restart: the old host_epoch's requests are answered unknown (never missing); "
        "resending one is refused and Blender doesn't change")


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
    ids = {name: o["id"] for name, o in SNAPSHOTS["Before load"].items()}

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
    assert {name: o["id"] for name, o in SNAPSHOTS["After load"].items()} == ids, (
        "object IDs did not survive save and reopen")
    assert all(o["generation"] == 0 for o in SNAPSHOTS["After load"].values())
    # bpy-module Blender keeps is_dirty set across this load after the Undo check above;
    # GUI Blender clears it. Either way the host must report Blender's own flag.
    assert loaded["dirty"] is bpy.data.is_dirty, loaded
    if GUI:
        assert loaded["dirty"] is False, loaded
    log("loading another .blend closes connections on both ports and restarts them; "
        "same document ID and object IDs, new open epoch, revision 0")

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
    yield from live_scene(prefs)
    yield from commands(prefs)
    yield from recovery(prefs)
    yield from role_switch(prefs)
    yield from document_identity(prefs)

    for _ in range(2):
        addon_utils.disable(MODULE, default_set=True)
        assert_stopped()
        host = mod("host")
        assert host._on_load_pre not in bpy.app.handlers.load_pre
        assert host._on_save_pre not in bpy.app.handlers.save_pre
        assert host._on_load_post not in bpy.app.handlers.load_post
        sync = mod("sync")
        assert sync._on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post
        assert sync._on_undo_redo not in bpy.app.handlers.undo_post and sync._state is None
        addon_utils.enable(MODULE, default_set=True)
        assert listening()
        assert bpy.app.handlers.load_pre[:].count(host._on_load_pre) == 1
        assert bpy.app.handlers.depsgraph_update_post[:].count(
            mod("sync")._on_depsgraph_update) == 1
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
                bpy.context.evaluated_depsgraph_get()  # what Blender's event loop does
                host._drain()  # what the add-on's timer does in GUI Blender
            time.sleep(0.005)
    except Exception:  # noqa: BLE001 - any failure fails the check
        traceback.print_exc()
        finish(1)
    finish(0)


main()

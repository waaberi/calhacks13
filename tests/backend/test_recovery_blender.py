"""Recovery and publishing in Blender, on the Unity port and the TLS LAN port at once.

Needs the bpy module (pip install bpy==5.2.2); skipped without it, as in CI. The
host runs as in test_edits.py (real edits.py and sync.py, Blender's main thread
draining the server) with a Client-role listener next to the Unity one and "Let
the Client role edit" on. Checks that commands from either port, direct edits in
host Blender and Undo/Redo reach both clients as the same scene.update, that
nothing goes out before Blender confirmed it, and the lost-acknowledgement and
unknown-outcome recoveries with Blender's own data. Every message is checked
against contracts/schemas (Peer from test_commands.py).
"""

import contextlib
import socket

import pytest
from test_edits import CUBE, SESSION_ID, Blender, bpy, fresh_scene, obj, world

# isort: split
from spatial_modeling import commands, document, edits, host, lan, server, session, sync
from test_commands import TOKEN, Peer, assert_rejected

pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")

MOVE = {"by": [0.01, 0, 0]}


class BothPorts(Blender):
    def vr(self, name="Talia"):
        return self.peer(name)

    def lee(self, name="Lee"):
        peer = Peer(self.srv.listeners[1].port, token=TOKEN)
        self.call(peer.join, name, role="blender-client")
        return peer

    def expect(self, peer, *types):
        return self.call(peer.expect, *types)

    def quiet(self, *peers):
        for peer in peers:
            self.call(peer.assert_quiet)


@contextlib.contextmanager
def blender_on_both_ports():
    fresh_scene()
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, SESSION_ID, client_can_edit=True)
    sync.register()
    sync.start(doc, sess)
    heartbeat, server.HEARTBEAT_TIMEOUT = server.HEARTBEAT_TIMEOUT, 120.0  # the peers don't ping
    try:
        cmds = commands.Commands(sess, edits.Editor(sync, host.undoable, doc))
        lan_listener = server.Listener("127.0.0.1", 0, ssl=lan.server_tls_context(TOKEN),
                                       roles=("blender-client",))
        srv = cmds.attach(sess.attach(server.Server(port=0, extra_listeners=[lan_listener])))
        srv.start()
        try:
            yield BothPorts(srv, sess, cmds, doc)
        finally:
            srv.stop()
    finally:
        server.HEARTBEAT_TIMEOUT = heartbeat
        sync.unregister()


@contextlib.contextmanager
def talia_and_lee():
    with blender_on_both_ports() as b, b.vr() as talia, b.lee() as lee:
        b.expect(talia, "session.update")  # Lee joined
        yield b, talia, lee


def test_commands_from_either_port_reach_both_alike_after_blender_confirms():
    with talia_and_lee() as (b, talia, lee):
        for sender, watcher, dx in ((talia, lee, 0.01), (lee, talia, 0.02)):
            x = world(obj(CUBE)).translation.x
            before, result = b.ask(sender, b.command(sender, "object.move", CUBE,
                                                     {"by": [dx, 0, 0]}))
            receipt = result["payload"]
            assert receipt["outcome"] == "applied", receipt
            assert [m["type"] for m in before] == ["scene.update"], before  # before the result
            update, activity = b.expect(watcher, "scene.update", "activity")
            assert update["payload"] == before[0]["payload"] and activity["payload"] == receipt
            assert abs(world(obj(CUBE)).translation.x - x - dx) < 1e-6  # Blender has it
            assert update["payload"]["document"]["revision"] == receipt["revision"]
        b.quiet(talia, lee)


def test_direct_edits_and_host_desktop_undo_redo_reach_both_ports_alike():
    with talia_and_lee() as (b, talia, lee):
        cube = obj(CUBE)
        cube.location.x += 1  # an edit at the host desktop, not a command
        bpy.ops.ed.undo_push(message="Direct move")
        sync.flush()  # what host.py's timer does through sync.poll()
        updates = [b.expect(peer, "scene.update")[0]["payload"] for peer in (talia, lee)]
        assert updates[0] == updates[1]
        moved = updates[0]["objects"][0]
        assert moved["id"] == CUBE and moved["transform"]["location"][0] == 1.0
        b.quiet(talia, lee)  # no result, no activity

        for step, x in ((bpy.ops.ed.undo, 0.0), (bpy.ops.ed.redo, 1.0)):
            step()
            sync.flush()
            updates = [b.expect(peer, "scene.update")[0]["payload"] for peer in (talia, lee)]
            assert updates[0] == updates[1], step
            assert {o["id"]: o for o in updates[0]["objects"]}[CUBE]["transform"]["location"][0] \
                == x
        b.quiet(talia, lee)


def test_undo_and_redo_commands_reach_both_ports_alike():
    with talia_and_lee() as (b, talia, lee):
        b.run(talia, "object.move", CUBE, MOVE)
        b.expect(lee, "scene.update", "activity")
        for sender, watcher, op, x in ((lee, talia, "history.undo", 0.0),
                                       (talia, lee, "history.redo", 0.01)):
            before, result = b.ask(sender, b.command(sender, op))
            assert result["payload"]["outcome"] == "applied", result
            update, activity = b.expect(watcher, "scene.update", "activity")
            assert [m["payload"] for m in before] == [update["payload"]]
            assert activity["payload"] == result["payload"]
            location = {o["id"]: o for o in update["payload"]["objects"]}[CUBE]["transform"]
            assert abs(location["location"][0] - x) < 1e-6, location
            assert abs(world(obj(CUBE)).translation.x - x) < 1e-6


def test_an_edit_blender_refuses_reaches_nobody():
    with talia_and_lee() as (b, talia, lee):
        driver = obj(CUBE).driver_add("location", 0).driver
        driver.expression = "0.5"
        world(obj(CUBE))
        sync.flush()  # the driver's own change goes out first
        b.call(lambda: [p.recv() for p in (talia, lee)])
        for sender in (talia, lee):
            before, result = b.ask(sender, b.command(sender, "object.move", CUBE, MOVE))
            assert before == [] and result["type"] == "result"
            assert_rejected(result["payload"], "failed")
        sync.flush()  # Blender put the Cube back: nothing to send
        b.quiet(talia, lee)


@pytest.mark.parametrize("port", ["vr", "lan"])
def test_a_lost_result_is_found_after_reconnecting_and_blender_moved_once(port):
    with talia_and_lee() as (b, talia, lee):
        sender, watcher = (talia, lee) if port == "vr" else (lee, talia)
        msg = b.command(sender, "object.move", CUBE, MOVE)

        def hang_up():
            sender.send(msg)
            sender.sock.shutdown(socket.SHUT_WR)
            sender.sock.settimeout(5)
            while sender.sock.recv(65536):  # never read: the result is lost
                pass

        b.call(hang_up)
        _, activity, _ = b.expect(watcher, "scene.update", "activity", "session.update")
        again = b.vr("Talia again") if port == "vr" else b.lee("Lee again")
        b.expect(watcher, "session.update")
        b.call(again.assert_quiet)  # nothing replayed
        assert again.revision == activity["payload"]["revision"]
        reply = b.call(again.query, msg["id"])
        assert reply["receipts"] == [activity["payload"]] and reply["missing"] == []
        before, same = b.ask(again, msg)  # resent as it was: the stored receipt
        assert before == [] and same["payload"] == activity["payload"]
        assert abs(world(obj(CUBE)).translation.x - 0.01) < 1e-6, "moved twice"
        b.quiet(watcher)
        again.close()


def test_an_unknown_outcome_freezes_both_ports_until_the_fresh_snapshot():
    with talia_and_lee() as (b, talia, lee):
        editor, real_apply = b.cmds.editor, b.cmds.editor.apply
        real_snapshot = b.sess.snapshot

        def apply_then_fail(*args):
            editor.apply = real_apply
            real_apply(*args)  # Blender committed and published it...
            raise RuntimeError("...but the host lost track afterwards")

        def no_snapshot(document):
            raise RuntimeError("the scene can't be read yet")

        editor.apply = apply_then_fail
        b.sess.snapshot = no_snapshot
        receipt = b.run(talia, "object.move", CUBE, MOVE)
        assert receipt["outcome"] == "unknown" and b.cmds.frozen
        b.expect(lee, "scene.update")  # the move itself was published before the failure
        for sender in (lee, talia):
            assert_rejected(b.run(sender, "object.move", CUBE, MOVE), "permission_denied")
        assert abs(world(obj(CUBE)).translation.x - 0.01) < 1e-6
        b.quiet(talia, lee)

        b.sess.snapshot = real_snapshot
        b.cmds._retry_at = 0
        b.cmds.poll()  # host.py's timer
        for peer in (talia, lee):
            (snapshot,) = b.expect(peer, "scene.snapshot")
            cube = {o["id"]: o for o in snapshot["payload"]["objects"]}[CUBE]
            assert abs(cube["transform"]["location"][0] - 0.01) < 1e-6
        assert not b.cmds.frozen
        assert b.run(lee, "object.move", CUBE, MOVE)["outcome"] == "applied"
        b.expect(talia, "scene.update", "activity")
        assert abs(world(obj(CUBE)).translation.x - 0.02) < 1e-6

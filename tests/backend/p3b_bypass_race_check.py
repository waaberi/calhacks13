"""Actual bpy + real joined connection reproduce reconciliation admission race.

No yield separates a leased native RNA bypass from the next command handler.
The handler and the write are the production classes, with tracing wrappers
only. Socket delivery is observed by the existing test peer's reader thread.
"""

import json
import os
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p3b_gate_check import bc
from p3b_gate_check import gate_check as gc


def race_check():
    bc.install()
    import addon_utils
    addon_utils.enable(bc.MODULE, default_set=True)
    host, sync, server, gate = (bc.mod(n) for n in ("host", "sync", "server", "gate"))
    server.HEARTBEAT_TIMEOUT = 600
    cube = bpy.data.objects["Cube"]
    spare = bpy.data.objects.new("RaceUnrelatedSpare", cube.data.copy())
    bpy.context.scene.collection.objects.link(spare)
    spare.location.x = 4
    bpy.ops.ed.undo_push(message="P3B bypass race setup")
    yield from gc.pause(0.5)
    peer, welcome, _ = yield from bc.joined("Native Race Validation")
    lee = gc.Lee(peer, welcome)
    cube_id, spare_id = sync.object_id(cube), sync.object_id(spare)
    lease = yield from lee.lease("shared", [cube_id])
    yield from gc.pause(0.25)
    commander = bc.Commander(peer, welcome)
    msg = commander.command("object.move", spare_id, {"by": [0.01, 0, 0]})
    conn = next(c for c, actor in host._session.participants.items()
                if actor["actor_id"] == welcome["actor_id"])
    events = []
    block_snapshot = os.environ.get("P3B_BLOCK_SNAPSHOT") == "1"
    broadcast, apply, send = host._session.broadcast, host._commands.editor.apply, conn.send

    def traced_broadcast(message, *args, **kwargs):
        events.append({"event": "broadcast", "type": message["type"]})
        if block_snapshot and message["type"] == "scene.snapshot":
            raise RuntimeError("P3B intentional reconciliation snapshot failure")
        return broadcast(message, *args, **kwargs)

    def traced_apply(*args, **kwargs):
        events.append({"event": "apply", "op": args[0],
                       "frozen": host._commands.frozen,
                       "pending_gate_bypasses": len(gate._pending)})
        return apply(*args, **kwargs)

    def traced_send(message):
        if message["type"] == "result":
            events.append({"event": "result", "outcome": message["payload"]["outcome"]})
        return send(message)

    host._session.broadcast = traced_broadcast
    host._commands.editor.apply = traced_apply
    conn.send = traced_send
    old_cube, old_spare = cube.location.x, spare.location.x
    messages_at = len(lee.messages)
    # This is the precise single main-thread sequence under review.
    cube.location.x += 1
    events.append({"event": "native_bypass", "cube_x": cube.location.x})
    host._commands.command(msg, conn)
    events.append({"event": "handler_return", "cube_x": cube.location.x,
                   "spare_x": spare.location.x, "frozen": host._commands.frozen,
                   "pending_gate_bypasses": len(gate._pending)})
    yield from bc.wait(lambda: any(m.get("re") == msg["id"] for m in lee.messages),
                       "race command receipt")
    yield from gc.pause(0.5)
    reply = next(m for m in lee.messages if m.get("re") == msg["id"])
    apply_i = next((i for i, e in enumerate(events) if e["event"] == "apply"), None)
    snapshot_i = next((i for i, e in enumerate(events)
                       if e.get("type") == "scene.snapshot"), None)
    race = apply_i is not None and (snapshot_i is None or apply_i < snapshot_i)
    result = {"strict_lock_race_reproduced": race, "events": events,
              "reconciliation_snapshot_blocked": block_snapshot,
              "receipt": reply, "wire_order": [m["type"] for m in lee.messages[messages_at:]],
              "cube_before_after": [old_cube, cube.location.x],
              "spare_before_after": [old_spare, spare.location.x],
              "apply_index": apply_i, "first_snapshot_index": snapshot_i,
              "method": "real GUI bpy, production dispatcher and joined connection; no yield "
                        "between RNA bypass and command; instrumentation only",
              "lease_id": lease["lease_id"]}
    out = os.environ.get("P3B_RACE_RESULT")
    if out:
        Path(out).write_text(json.dumps(result, indent=2), "utf-8")
    bc.log("BYPASS RACE RESULT", result)
    expected = os.environ.get("P3B_EXPECT_RACE", "0") == "1"
    assert race == expected, (expected, result)
    if block_snapshot:
        assert reply["payload"]["outcome"] == "rejected", reply
        assert reply["payload"]["error"]["code"] == "permission_denied", reply
        assert spare.location.x == old_spare
        assert host._commands.frozen
    else:
        assert reply["payload"]["outcome"] == "applied", reply
        assert abs(spare.location.x - old_spare - 0.01) < 1e-5
    lee.close()
    addon_utils.disable(bc.MODULE, default_set=True)


if __name__ == "__main__":
    bc.main(race_check)

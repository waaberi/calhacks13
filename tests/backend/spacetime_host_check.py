"""The host add-on with a real SpacetimeDB server (#165): leases are decided in Blender and
copied to the server by MirroredStore's thread.

Two VR clients join this Blender. Talia leases the Cube; Jihyeon's lease on it is refused with
lease_conflict; SpacetimeDB's lease table shows Talia's lease; after she releases it the table
is empty. test_session_store.py runs this against a freshly published database:

  BLENDER_USER_RESOURCES=$(mktemp -d) blender -b --factory-startup \\
      --python tests/backend/spacetime_host_check.py -- URL DATABASE
"""

import sys
import time
from pathlib import Path

import bpy

# isort: split
import addon_utils  # importable only after bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blender_check as bc

URL, DATABASE = sys.argv[sys.argv.index("--") + 1:][:2]


def lease_rows(store):
    rows = yield from bc.off_thread(lambda: store._remote.select("SELECT * FROM lease"),
                                    "SpacetimeDB's lease table")
    return [(r["lease_id"], r["owner_id"], list(r["targets"])) for r in rows]


def checks():
    bc.install()
    addon_utils.enable(bc.MODULE, default_set=True)
    host, sync = bc.mod("host"), bc.mod("sync")
    host.SPACETIME_DATABASE = DATABASE
    bpy.context.preferences.addons[bc.MODULE].preferences.spacetime_url = URL  # restarts
    store = host._session.store
    yield from bc.wait(lambda: store.status.startswith("Sharing"), "the SpacetimeDB copy", 20)
    bc.log(store.status)

    cube_id = sync.object_id(bpy.data.objects["Cube"])
    talia, tw = (yield from bc.joined("Talia"))[:2]
    jihyeon, jw = (yield from bc.joined("Jihyeon"))[:2]
    yield from bc.next_update(talia, "Talia's session.update for Jihyeon")
    start = time.perf_counter()
    lease = yield from bc.leased(talia, tw, "shared", [cube_id])
    _, reply = yield from bc.ask(jihyeon, bc.acquire(jw, "shared", [cube_id]))
    took = (time.perf_counter() - start) * 1000
    assert reply["type"] == "error" and reply["payload"]["code"] == "lease_conflict", reply
    bc.log(f"Jihyeon's lease on the Cube: lease_conflict, {reply['payload']['message']!r}; "
           f"both answers in {took:.0f} ms")

    yield from bc.wait(lambda: store.wait_idle(0), "the copy to catch up")
    rows = yield from lease_rows(store)
    assert rows == [(lease["lease_id"], tw["actor_id"], lease["targets"])], rows
    bc.log("SpacetimeDB's lease table:", rows)

    talia.send(bc.protocol.message("lease.release", {"lease_id": lease["lease_id"]}))
    yield from bc.session_update(talia, "the session.update after the release",
                                 lambda p: p["leases"] == [])
    yield from bc.wait(lambda: store.wait_idle(0), "the copy to catch up")
    rows = yield from lease_rows(store)
    assert rows == [], rows
    bc.log("after Talia's release the table is empty")
    talia.close()
    jihyeon.close()
    addon_utils.disable(bc.MODULE, default_set=True)


if __name__ == "__main__":
    bc.main(checks)

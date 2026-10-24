"""SpacetimeDB from Blender's own Python: pass criteria 3 and 4 of the spike.

Run twice, as two separate Blender processes, against a running server:

  blender --background --factory-startup --python spacetime_blender_check.py -- \
      first  TOKEN_PATH URL DATABASE STATE_JSON
  blender --background --factory-startup --python spacetime_blender_check.py -- \
      second TOKEN_PATH URL DATABASE STATE_JSON

`first` acquires a lease through a reducer with urllib (via session_store.SpacetimeStore),
checks that a second acquire of the same object is rejected, records a receipt and quits.
`second` is the restarted Blender: the lease and the receipt must still be there, and the
same acquire must still be rejected. test_session_store.py runs both. Exits 0 on success.
"""

import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "blender_addon" / "spatial_modeling"))
from session_store import SessionError, SpacetimeStore


def log(*args):
    print("[spacetime_blender_check]", *args, flush=True)


def rejected(call):
    start = time.perf_counter()
    try:
        call()
    except SessionError as e:
        return e, (time.perf_counter() - start) * 1000
    raise AssertionError("the second acquire was granted")


def first(store, state_path):
    talia = {"actor_id": uuid.uuid4().hex, "name": "Talia", "role": "vr"}
    lee = {"actor_id": uuid.uuid4().hex, "name": "Lee Jae-yeon", "role": "blender-client"}
    store.join(talia)
    store.join(lee)
    target = uuid.uuid4().hex
    start = time.perf_counter()
    lease = store.acquire(talia["actor_id"], "shared", [target])
    log(f"acquired lease {lease['lease_id']} in {(time.perf_counter() - start) * 1000:.1f} ms")
    e, ms = rejected(lambda: store.acquire(lee["actor_id"], "shared", [target]))
    assert e.code == "lease_conflict" and e.details["lease"] == lease, e
    log(f"second acquire rejected in {ms:.1f} ms: {e.code}: {e.message}")
    receipt = {
        "request_id": uuid.uuid4().hex,
        "op": "object.move",
        "target": target,
        "actor": talia,
        "source": "voice",
        "outcome": "applied",
        "revision": 1,
        "summary": "Moved Shaft 10 mm along X",
        "at": time.time_ns() // 1_000_000,
    }
    store.record_receipt(receipt, "digest")
    state = {"lee": lee, "lease": lease, "receipt": receipt, "pid": os.getpid()}
    Path(state_path).write_text(json.dumps(state), encoding="utf-8")


def second(store, state_path):
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    assert state["pid"] != os.getpid(), "the second phase must be a new Blender process"
    lease, receipt = state["lease"], state["receipt"]
    assert lease in store.leases(), f"lease lost: {store.leases()}"
    log(f"after the restart lease {lease['lease_id']} is still held by {lease['owner']['name']}")
    assert store.receipts([receipt["request_id"]]) == ([receipt], []), "receipt lost"
    log(f"after the restart receipt {receipt['request_id']} is still in the log")
    e, _ = rejected(lambda: store.acquire(state["lee"]["actor_id"], "shared", lease["targets"]))
    assert e.code == "lease_conflict", e
    log("a second acquire of the same object is still rejected")
    for p in store.participants():
        store.leave(p["actor_id"])


def main():
    phase, token, url, database, state_path = sys.argv[sys.argv.index("--") + 1 :]
    log("Blender", bpy.app.version_string, "Python", sys.version.split()[0], sys.executable)
    try:
        store = SpacetimeStore(token, url=url, database=database, lease_ttl_ms=120_000)
        {"first": first, "second": second}[phase](store, state_path)
    except Exception:  # noqa: BLE001 - any failure fails the check
        traceback.print_exc()
        log("FAIL", phase)
        sys.stdout.flush()
        os._exit(1)
    log("PASS", phase)
    sys.stdout.flush()
    os._exit(0)


main()

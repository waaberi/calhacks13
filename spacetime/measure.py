"""Measure the SpacetimeDB spike: HTTP round trips from Python and live-subscription latency.

Needs a running server (`spacetime start --listen-addr 127.0.0.1:3000`), the spacetime CLI,
`npm install` done in spacetime/, the .NET SDK, and C# bindings generated into
LatencyProbe/module_bindings (see README.md). It publishes a fresh database named
spatial-modeling-bench, so the real session database is never touched.

  python spacetime/measure.py            # prints a summary; --json FILE also saves the samples

1. HTTP round trips, standard library only, as the host add-on makes them: a reducer call, a
   one-table SQL query, session() (participants and leases: what the host polls) and
   acquire() including its read-back.
2. Subscription latency: LatencyProbe (the official C# SDK, standing in for Unity) subscribes
   to the lease table; Python calls `acquire` and `release` and the probe stamps each row
   callback. Latency = callback time - time just before the Python call. Run with FrameTick
   every 1 ms and every 11 ms (one 90 Hz frame, as in Unity).
"""

import argparse
import json
import math
import os
import queue
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "blender_addon" / "spatial_modeling"))
from session_store import SpacetimeStore

DATABASE = "spatial-modeling-bench"


def stats(samples):
    s = sorted(samples)

    def rank(q):  # nearest-rank percentile
        return s[max(0, math.ceil(q * len(s)) - 1)]

    return {"n": len(s), "median": rank(0.5), "p95": rank(0.95), "max": s[-1]}


def timed(fn, n, warmup=20):
    for _ in range(warmup):
        fn()
    out = []
    for _ in range(n):
        start = time.perf_counter()
        fn()
        out.append((time.perf_counter() - start) * 1000)
    return out


def find_dotnet():
    found = shutil.which("dotnet")
    if found:
        return found
    home = Path.home() / ".dotnet" / ("dotnet.exe" if os.name == "nt" else "dotnet")
    if home.exists():
        return str(home)
    sys.exit("can't find the dotnet CLI")


def publish(url):
    cli = shutil.which("spacetime") or sys.exit("can't find the spacetime CLI")
    cmd = [cli, "publish", "--no-config", "--server", url, "--module-path", str(HERE)]
    subprocess.run(cmd + ["--delete-data=always", "--yes", DATABASE], check=True)


def round_trips(store, actors, n):
    talia, lee = actors
    target = uuid.uuid4().hex

    def acquire_release():
        lease = store.acquire(lee["actor_id"], "shared", [target])
        store.release(lease["lease_id"], lee["actor_id"])

    results = {
        "reducer call (renew)": timed(lambda: store.renew(talia["actor_id"]), n),
        "SQL query (one table)": timed(lambda: store.select("SELECT * FROM lease"), n),
        "session() (2 queries)": timed(store.session, n),
    }
    acquire_ms = []
    for _ in range(n // 2):
        start = time.perf_counter()
        lease = store.acquire(lee["actor_id"], "shared", [target])
        acquire_ms.append((time.perf_counter() - start) * 1000)
        store.release(lease["lease_id"], lee["actor_id"])
    results["acquire() with read-back"] = acquire_ms
    return results


def subscription_latency(store, owner, dotnet, dll, url, tick_ms, n):
    probe = subprocess.Popen(
        [dotnet, str(dll), url, DATABASE, str(tick_ms)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(x) for x in probe.stdout], daemon=True).start()

    def wait_for(prefix, timeout=5.0):
        deadline = time.monotonic() + timeout
        while True:
            line = lines.get(timeout=max(0.001, deadline - time.monotonic())).split()
            if line[0] == "error":
                sys.exit(" ".join(line))
            if line[0] == prefix[0] and line[1:2] == prefix[1:]:
                return int(line[-1]) if len(line) > 2 else None

    try:
        wait_for(["ready"], timeout=30)
        inserts, deletes, calls = [], [], []
        for _ in range(n):
            lease_id = uuid.uuid4().hex
            args = {
                "lease_id": lease_id,
                "owner_id": owner["actor_id"],
                "mode": "shared",
                "targets": [uuid.uuid4().hex],
                "ttl_ms": 60_000,
            }
            t0 = time.time_ns() // 1000
            store.call("acquire", args)
            calls.append((time.time_ns() // 1000 - t0) / 1000)
            inserts.append((wait_for(["insert", lease_id]) - t0) / 1000)
            time.sleep(random.uniform(0.02, 0.05))  # don't line up with the probe's tick
            t0 = time.time_ns() // 1000
            store.call("release", {"lease_id": lease_id, "owner_id": owner["actor_id"]})
            deletes.append((wait_for(["delete", lease_id]) - t0) / 1000)
            time.sleep(random.uniform(0.02, 0.05))
        return {
            f"insert callback, tick {tick_ms} ms": inserts,
            f"delete callback, tick {tick_ms} ms": deletes,
            f"reducer call returned, tick {tick_ms} ms": calls,
        }
    finally:
        probe.stdin.close()
        probe.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="http://127.0.0.1:3000")
    parser.add_argument("--n", type=int, default=200, help="samples per measurement")
    parser.add_argument("--json", help="also write every sample to this file")
    args = parser.parse_args()

    publish(args.url)
    dotnet = find_dotnet()
    project = HERE / "LatencyProbe"
    subprocess.run(
        [dotnet, "build", str(project), "-c", "Release", "-v", "q", "-nologo"], check=True
    )
    dll = project / "bin" / "Release" / "net10.0" / "LatencyProbe.dll"

    with tempfile.TemporaryDirectory() as tmp:
        store = SpacetimeStore(
            Path(tmp) / "token", url=args.url, database=DATABASE, lease_ttl_ms=60_000
        )
        talia = {"actor_id": uuid.uuid4().hex, "name": "Talia", "role": "vr"}
        lee = {"actor_id": uuid.uuid4().hex, "name": "Lee Jae-yeon", "role": "blender-client"}
        store.join(talia)
        store.join(lee)
        results = round_trips(store, (talia, lee), args.n)
        for tick in (1, 11):
            results.update(subscription_latency(store, talia, dotnet, dll, args.url, tick, args.n))

    print(f"\n{'measurement (ms)':44} {'n':>5} {'median':>8} {'p95':>8} {'max':>8}")
    for name, samples in results.items():
        s = stats(samples)
        print(f"{name:44} {s['n']:5} {s['median']:8.2f} {s['p95']:8.2f} {s['max']:8.2f}")
    if args.json:
        Path(args.json).write_text(json.dumps(results), encoding="utf-8")


if __name__ == "__main__":
    main()

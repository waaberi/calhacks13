# SpacetimeDB session state

The SpacetimeDB spike (issue #16, [PHASE_PLAN.md › SpacetimeDB session state](../PHASE_PLAN.md#spacetimedb-session-state)). Owner: Waaberi.

The module holds the session state the host shares: **participants**, **object leases** and the **receipt log** (activity is the receipts of applied commands). It never holds geometry, scene snapshots or native commands; those stay on the direct host connection. The wire format in [contracts/README.md](../contracts/README.md) doesn't change: the host builds `session.update`, `lease.granted` and `receipts` from these tables, or from memory if SpacetimeDB isn't used.

| File | What it is |
| --- | --- |
| [`src/index.ts`](src/index.ts) | The module: tables `participant`, `lease`, `receipt` (public) and `authority` (private), and the reducers. |
| [`../blender_addon/spatial_modeling/session_store.py`](../blender_addon/spatial_modeling/session_store.py) | The host's side: one `SessionStore` interface, `MemoryStore` (fallback) and `SpacetimeStore` (stdlib HTTP). |
| [`LatencyProbe/`](LatencyProbe/) | C# console app on the official C# SDK; stands in for the Unity app. |
| [`measure.py`](measure.py) | Measures HTTP round trips and subscription latency (stdlib only). |
| [`../tests/backend/test_session_store.py`](../tests/backend/test_session_store.py) | Runs every store test against both stores; the SpacetimeDB half is skipped when no server is running. |
| [`../tests/backend/spacetime_blender_check.py`](../tests/backend/spacetime_blender_check.py) | Criteria 3 and 4 in Blender's own Python. |

## Verdict

**All four pass criteria pass on Waaberi's Linux PC; two still need the real hardware.** Criterion 1 still has to be run on Talia's Windows PC, and criterion 2 was measured with a C# console app on the same SDK, not with the Unity app. Recommendation: **use SpacetimeDB for session state**, behind `SessionStore`, and keep `MemoryStore` as the fallback the host picks when no server is running. It costs Talia one extra window (`spacetime start`) and a one-time Node.js install. Latency is about 4 ms, 60 times under the target. Each call blocks Blender's main thread for 1 to 5 ms; an acquire with its read-back takes 12 ms at p95.

| # | Criterion | Result | Measured |
| --- | --- | --- | --- |
| 1 | `spacetime start` on localhost; the module publishes | Pass (Linux; Windows still to do) | Server up on `127.0.0.1:3000` at once; `spacetime publish` builds and publishes in 0.8 s. |
| 2 | A subscriber sees a lease change within 250 ms | Pass (C# console app, not Unity yet) | Python reducer call to C# `OnInsert` callback: median 4.0 ms, p95 5.0 ms, max 20.5 ms. With `FrameTick()` once per 90 Hz frame, as in Unity: median 8.9 ms, p95 14.0 ms, max 30.5 ms. |
| 3 | Blender's own Python acquires through a reducer with `urllib`; a second acquire of the same object is rejected | Pass | Blender 5.2.2's bundled Python 3.13.13, background and GUI: acquire in 3 to 6 ms, the second acquire rejected with `lease_conflict` ("Talia is editing this") in 3 to 5 ms. |
| 4 | Restarting Blender loses neither the receipt log nor the current leases | Pass, but see below | A new Blender process with the same host token reads the same lease and receipt, and the same acquire is still rejected. Both also survive a restart of the SpacetimeDB server, including `kill -9`. |

**About criterion 4.** The rows survive. But under the contract, the owners' connections close when the host restarts, and every reconnect gets a new `actor_id`, so nobody can renew those leases afterwards. With the contract's 6 s TTL they lapse on their own, as the contract wants. The check used a 120 s TTL to show the data survives. What a restart really preserves is the **receipt log**: after a crash, `receipt.query` can answer for requests the host recorded before it went down. That is the one thing `MemoryStore` can't do.

### Measured numbers

AMD Ryzen AI 9 HX 370, Fedora 44, SpacetimeDB 2.13.0 standalone, Node.js 26.12.0, .NET SDK 10.0.402, Blender 5.2.2. Server, Python and probe on one machine over `127.0.0.1`. Two runs of `python spacetime/measure.py` (n = 200, then n = 300; the table shows the second run, and the first agrees within about 1 ms). Milliseconds:

| Measurement | median | p95 | max |
| --- | --- | --- | --- |
| Reducer call over HTTP (`renew`), back to back | 1.8 | 2.6 | 11.8 |
| Reducer call over HTTP (`acquire`), 20 to 50 ms apart | 3.7 | 4.4 | 13.9 |
| SQL query, one table | 0.9 | 1.4 | 2.4 |
| `session()`: participants and leases, 2 queries (one poll) | 2.4 | 3.2 | 12.5 |
| `acquire()` including its read-back | 4.4 | 12.3 | 18.4 |
| Subscription: reducer call to C# `OnInsert`, `FrameTick` every 1 ms | 4.0 | 5.0 | 20.5 |
| Subscription: reducer call to C# `OnDelete`, `FrameTick` every 1 ms | 4.0 | 4.8 | 10.1 |
| Subscription: `OnInsert`, `FrameTick` every 11 ms (90 Hz) | 8.9 | 14.0 | 30.5 |
| Subscription: `OnDelete`, `FrameTick` every 11 ms (90 Hz) | 9.2 | 14.0 | 14.9 |

Spaced-out calls take about 2 ms longer than back-to-back ones. I haven't checked why; the CPU waking from idle is a guess. Expect the spaced figure in real use. The subscriber's callback arrives about 0.3 ms after the HTTP call returns.

**How often the host can poll:** it doesn't have to. The host is the only writer, so it reads `session()` (about 2.5 ms) only after its own writes, to send `session.update`. Leases that expire need no poll either: `leases()` already leaves them out, and the host calls `expire()` on its own schedule so subscribers stop showing them. If polling is ever needed, 10 polls a second would take about 25 ms of every second, 2.5 % of the main thread. Renewing on every client heartbeat (every 2 s per client) is under 2 calls a second.

## Setup on Talia's Windows PC

PowerShell, as Talia (not as administrator). Pin version **2.13.0** of everything: the CLI and server, the npm package (pinned in `package-lock.json`) and the client SDK.

1. **Node.js** builds the module. Install the LTS: `winget install OpenJS.NodeJS.LTS`, then open a new terminal and check `node --version`. (Tested here with Node 26; I haven't tried the LTS.)
2. **SpacetimeDB CLI and server:**

   ```powershell
   iwr https://windows.spacetimedb.com -useb | iex
   # open a new terminal so `spacetime` is on PATH
   spacetime version install 2.13.0
   spacetime version use 2.13.0
   spacetime --version            # must say 2.13.0
   ```

   If the Visual C++ runtime is missing, the installer downloads and installs it, which shows a UAC prompt. The installer prints where it keeps its configuration and data; note both paths.
3. **Start the server on localhost only**, in its own terminal, and keep it open while you work:

   ```powershell
   spacetime start --listen-addr 127.0.0.1:3000
   ```

   Always pass `--listen-addr 127.0.0.1:3000`. Without it, the server listens on every network interface (`0.0.0.0:3000`) with no TLS. If Windows Firewall asks whether to allow access, choose **Cancel**. If port 3000 is taken, use another port here and give the same URL to the add-on and the Unity app.
4. **Publish the module**, from a checkout of this repo:

   ```powershell
   cd spacetime
   npm ci
   spacetime publish -y           # spacetime.json: local server, database "spatial-modeling"
   spacetime sql spatial-modeling "SELECT * FROM lease"   # an empty table
   ```

   The first publish logs the CLI into the local server. That CLI identity owns the database. Publish again after a module change; the data is kept unless the schema changes incompatibly.
5. **The host claims the database** the first time the add-on connects (in P3B). To see who holds it, run `spacetime sql spatial-modeling "SELECT * FROM authority"`: slot 0 is the publisher and slot 1 the host. Only the owner can read that table. If the host's token is lost, free the slot with `spacetime call spatial-modeling reset_host`, then restart the host.
6. *(Optional)* **Measure on this PC.** Install the .NET SDK (`winget install Microsoft.DotNet.SDK.10`) and generate the probe's bindings (`spacetime generate --lang csharp --out-dir LatencyProbe\module_bindings --module-path . -y`). Then run the measurement with Blender's own Python, so no other Python is needed: `& "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" measure.py`. It publishes its own `spatial-modeling-bench` database and leaves `spatial-modeling` alone.

**Windows risks** (none of this has been tried on Windows yet):

- Connecting to a closed port on Windows takes about 2 s rather than failing at once. So the host should create the `SpacetimeStore` once, when it starts, and fall back to `MemoryStore` if that raises `StoreUnavailable`. It shouldn't retry on every request. The store's timeout is 1 s.
- urllib uses the Windows proxy settings. `SpacetimeStore` turns proxies off, so a system proxy can't capture localhost traffic.
- Port 3000 is a common development port; it may already be in use.
- The server signs tokens with keys in the CLI's configuration directory (`--jwt-key-dir`). Deleting that directory makes every token invalid, the publisher's included. `SpacetimeStore` gets a new identity when its token is refused, but it can't claim a database that still names the old host. I haven't tested recovery; it probably means wiping the server's data directory and publishing again. Back up the configuration directory, and don't delete it.
- I haven't tried `spacetime publish` on Windows for a TypeScript module.

## For Jihyeon: the Unity subscription

1. **SDK:** in Package Manager, choose **+ › Add package from git URL** and enter `https://github.com/clockworklabs/com.clockworklabs.spacetimedbsdk.git#v2.13.0`. The same SDK is on NuGet as `SpacetimeDB.ClientSDK` 2.13.0, which is what `LatencyProbe` uses.
2. **Bindings:** generate them from the module, for example from the repo root:

   ```sh
   spacetime generate --lang csharp --out-dir app/Assets/SpacetimeDB/module_bindings --module-path spacetime -y
   ```

   Pick the folder inside `app/` yourself, commit the generated files with their `.meta` files, and generate again whenever `spacetime/src/` changes. Generating needs `npm ci` in `spacetime/` first. The "could not format generated files" warning just means `dotnet` isn't on PATH, and is harmless.
3. **Connect and subscribe.** [`LatencyProbe/Program.cs`](LatencyProbe/Program.cs) is a complete example: `DbConnection.Builder().WithUri("http://127.0.0.1:3000").WithDatabaseName("spatial-modeling")`, then subscribe to `SELECT * FROM lease` and `SELECT * FROM participant`. In Unity, the SDK's `SpacetimeDBNetworkManager` calls `FrameTick()` every frame.
4. **What the rows mean.** `lease.owner_id` is the owner's `actor_id`; look up the name with `conn.Db.Participant.ActorId.Find(ownerId)`. An `exclusive` lease has no targets and covers the whole document. Times are Unix milliseconds (`ulong`). Every renewal rewrites `expires_at`, so handle `OnUpdate` as well as `OnInsert` and `OnDelete`, and treat a lease as gone once `expires_at` has passed.
5. **Read only.** The bindings include the reducers, but only the host can call them; Unity gets `permission_denied`. Lease requests stay `lease.acquire` over the host connection. `session.update` over that connection carries the same lists, so the app must keep working without SpacetimeDB.
6. **Criterion 2 in Unity:** in `OnInsert`, log `DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - (long)row.AcquiredAt`. `acquired_at` is the server's clock when the reducer ran, on the same PC. The target is under 250 ms.

## For the host (P3B)

- Pick the store once, at host start: `SpacetimeStore(token_path)`, and fall back to `MemoryStore()` on `StoreUnavailable`. Show which one is in use in the add-on status. Never switch during a session; that would split the state.
- Keep the token outside Git and outside the `.blend` file, for example in `bpy.utils.user_resource('CONFIG', path="spatial_modeling", create=True)`.
- Call `renew(actor_id)` whenever a client is heard from, `leave(actor_id)` when its connection closes, and `expire()` now and then. For a command sent without a lease, check `conflict(...)`. Record a receipt as `pending` before applying and as final afterwards, so a crash between the two leaves a record.
- Every call blocks Blender's main thread for its round trip. If a server stalls, a call waits up to the 1 s timeout and then raises `StoreUnavailable`. Treat that like `internal_error`: the outcome is unknown.

**Where the host is now (#75).** Leases and presence go through `SessionStore`: `session.Session(store=...)` takes one, and `host.start()` passes none, so the host uses `MemoryStore(lease_ttl_ms=None)`. There, leases end only on release or when the owner's connection closes; the server closes a connection it hasn't heard from for 6 s, timed on its reader thread. SpacetimeDB isn't wired in yet, on purpose, until criterion 1 passes on Windows (#16). Before switching, settle these:

- **Renewal while Blender is busy.** `renew()` would run on the main thread, which stops during a render. A render over 6 s would let every lease lapse in SpacetimeDB although the clients kept pinging, and `renew()` doesn't revive a lapsed lease. Renew from the reader thread's last-heard times when the main thread resumes, before anything else, or give the rows a longer TTL and let the host end them on leave.
- **Cost per command.** Step 6 of every command reads the leases: two SQL queries, about 2.5 ms each time, on the main thread.
- **Receipts** still live in `commands.py`, not in the store.

## Security notes

- Only the identity that called `claim_host` first can write. That is the first caller, so the host must claim right after the first publish. Check this before a demo (step 5). Anonymous HTTP callers get a fresh identity each time and are rejected.
- SQL `INSERT`, `UPDATE` and `DELETE` are refused for everyone except the database owner (tested), so the reducers are the only way to write.
- The server sends `Access-Control-Allow-Origin: *`. Any web page open in a browser on Talia's PC can read the public tables: names, lease targets and receipt summaries. It can't write. Keep secrets out of these tables; there are none now.
- Session tokens and SpacetimeDB tokens stay out of Git. `spacetime/.gitignore` covers `node_modules/`, `dist/` and the generated bindings.

# SpacetimeDB session state

The SpacetimeDB spike (issue #16, [PHASE_PLAN.md › SpacetimeDB session state](../PHASE_PLAN.md#spacetimedb-session-state)). Owner: Waaberi.

The module holds the session state the host shares: **participants**, **object leases**, the **receipt log**, object **labels** and lease **refusals**. Its `acquire` reducer decides who may edit what. It also relays the host connection between PCs on different networks ([below](#across-the-internet-166)), as TLS ciphertext it can't read; it never stores geometry, snapshots or commands as such. The wire format in [contracts/README.md](../contracts/README.md) doesn't change: the host builds `session.update`, `lease.granted` and `receipts` from these tables, or from memory if SpacetimeDB isn't used.

| File | What it is |
| --- | --- |
| [`src/index.ts`](src/index.ts) | The module: tables `participant`, `lease`, `receipt` (public) and `authority` (private), and the reducers. |
| [`../blender_addon/spatial_modeling/session_store.py`](../blender_addon/spatial_modeling/session_store.py) | The host's side: one `SessionStore` interface, `MemoryStore`, `SpacetimeStore` (stdlib HTTP) and `MirroredStore`, which the host uses: SpacetimeDB's `acquire` reducer decides leases on a background thread. |
| [`board/`](board/) | The session board: a live page subscribed to the module with the TypeScript SDK. |
| [`bridge/`](bridge/) | The internet bridge: carries a remote Blender's connection to the host through the module (#166). |
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
5. **The host claims the database** the first time the add-on connects (as soon as the host starts with this server running). To see who holds it, run `spacetime sql spatial-modeling "SELECT * FROM authority"`: slot 0 is the publisher and slot 1 the host. Only the owner can read that table. If the host's token is lost, free the slot with `spacetime call spatial-modeling reset_host`, then restart the host.
6. *(Optional)* **Measure on this PC.** Install the .NET SDK (`winget install Microsoft.DotNet.SDK.10`) and generate the probe's bindings (`spacetime generate --lang csharp --out-dir LatencyProbe\module_bindings --module-path . -y`). Then run the measurement with Blender's own Python, so no other Python is needed: `& "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" measure.py`. It publishes its own `spatial-modeling-bench` database and leaves `spatial-modeling` alone.

**Windows risks** (none of this has been tried on Windows yet):

- Connecting to a closed port on Windows takes about 2 s rather than failing at once. That happens on the copy thread, so Blender doesn't notice. The store's timeout is 1 s.
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

## For the host (P3B, #165): SpacetimeDB decides who may edit what

The host add-on uses SpacetimeDB through `MirroredStore` in `session_store.py`, whenever the server the **SpacetimeDB** preference names answers (`http://127.0.0.1:3000` by default; blank turns it off). The preferences show which of the two is deciding.

- **SpacetimeDB decides.** When a client (VR or the remote Blender) asks for a lease, the add-on hands the request to a background thread (`spacetime-mirror`). The thread calls the module's `acquire` reducer, which grants or refuses it atomically, and the host answers the client with that decision. A lease that only SpacetimeDB holds still refuses the request (`test_spacetimedb_decides_against_a_real_server`).
- **Blender never waits.** The main thread only hands the request over; the answer goes out on the add-on's next 20 ms drain. On localhost a client waits about 5 to 25 ms in all. In Blender the longest drain measured 4.4 ms with the server running (`tests/backend/spacetime_host_check.py`).
- **Every read is local.** The leases SpacetimeDB granted are kept in memory, so each command's lease check, the desktop lock and `session.update` never touch the network.
- **The rest is copied, in order.** Joins, leaves, releases and the host desktop's own leases change memory at once. The thread copies them in the order leave, release, join, acquire, so the reducer always decides against the current session. The reducers check those copies too; a disagreement is logged.
- **Refusals and names.** The thread notes each refusal in the `refusal` table and the names of leased objects in `label`, for the session board.
- **No server.** Blender decides every lease in memory, exactly as before. The thread tries again every 5 s. When the server is back, it clears what an earlier host left and copies memory there. If a reducer call fails midway, memory decides that request, and SpacetimeDB gets memory's state on reconnect.
- **Lifetime.** Rows get the contract's 6 s TTL, and the thread renews them every 2 s, even while a render keeps Blender busy. If Blender quits or crashes, subscribers stop seeing its leases within 6 s.
- **Token.** It's kept in Blender's config folder as `spatial_modeling/spacetime-host-token`. If the preferences say "another identity is already the host", run `spacetime call spatial-modeling reset_host` and re-enter the SpacetimeDB preference.
- **Not stored there yet:** the receipt log (still in `commands.py`).

The remote Blender client joins through the host's TLS LAN port (8767): directly on a LAN, or through the bridges [across the internet](#across-the-internet-166).

## The session board

A live page of who's connected, who's editing what, and every SpacetimeDB decision as it happens, including "SpacetimeDB refused Lee's request for Cube: Talia is editing Cube", each with how fast the subscription pushed it. It only reads.

```sh
cd spacetime
npm ci                 # once, and after pulling module changes
npm run board          # then open http://127.0.0.1:3100
npm run board -- --url http://127.0.0.1:3000 --database spatial-modeling --port 3100   # the defaults
```

[`board/server.ts`](board/server.ts) subscribes with the official TypeScript SDK (Node 22 or later), and pushes each change to [`board/index.html`](board/index.html) over Server-Sent Events. It listens on 127.0.0.1 only. `board/module_bindings/` is generated. After changing `src/`, regenerate it with `spacetime generate --lang typescript --out-dir board/module_bindings --module-path . -y`.

## Across the internet (#166)

**Draft, not yet run on two networks.** For two PCs with no shared network: no LAN address, port forwarding or VPN. Both PCs connect out to the same database on Maincloud. A small Node bridge on each PC carries the host connection through it, so neither add-on changes how it connects.

```
remote Blender --TLS-PSK--> join bridge --wss--> Maincloud <--wss-- host bridge --> host Blender :8767
  (127.0.0.1:8767)                         room / pipe / frame                       (LAN port on)
```

- **What SpacetimeDB does.** Each TCP connection is a `pipe`. The bytes travel as numbered `frame` rows: `send` checks that the caller owns the pipe and that frames arrive in order, and the receiver deletes them with `ack`. At most 64 frames of 64 KiB are in flight per direction, so the table stays under 4 MiB per connection. When a bridge's connection drops, `on_disconnect` closes its room or pipes, and Blender reconnects as after any lost connection.
- **Encryption stays end to end.** The bridges pass the TLS-PSK bytes through unchanged, so Maincloud only stores ciphertext. The join bridge refuses a connection that doesn't start a TLS handshake. That way the add-on's no-TLS fallback can't send the token through the relay.
- **Read isolation.** `room`, `pipe` and `frame` are private. A bridge sees only its own rows, through the `my_pipe` and `my_frame` views. The session token never leaves either PC. The bridge sends a room id and a proof, both hashes of the key `lan.py` derives from the token, so only someone with the token can open the room or connect into it. Tested: an anonymous caller can't read `frame` or `pipe`, and can't call `open_pipe` or `send`. The lease tables are still public, so anyone who knows the database name can read names, lease targets and receipt summaries.
- **Leases.** Point the host's **SpacetimeDB** preference at `https://maincloud.spacetimedb.com` and set **Database** to the published name. The same `acquire` reducer then decides leases there. Blender's bundled Python reaches Maincloud with its own CA bundle (certifi). Each call takes about 300 ms from here, on the mirror thread, so Blender never waits.

**Measured here, with everything on one PC against a local server** (`127.0.0.1:3017`, so these numbers don't include internet latency):

- The existing two-Blender client test passes with the client going through both bridges. That test is `tests/backend/run_p3_client.py --relay http://127.0.0.1:3017 relay-test`, and it covers a lease, a native move with its receipt, the live mirror, Cancel and reconnect. All relay tables are empty afterwards.
- A 200-byte round trip takes 9.6 ms median (15.0 ms p95). Connecting with the TLS handshake takes 55 ms. A 16 MiB snapshot echoed both ways arrives intact in 3.0 s. Over the internet, add about two round trips to Maincloud per message.

**Run it.** Every PC needs Node 22 or later and `npm ci` in `spacetime/`.

1. **Publish once** (Waaberi's account until #166 decides): `spacetime login`, then `spacetime publish -s maincloud -y <database>`. Maincloud names are global, so pick a unique one. Then start the host straight away, so its add-on claims the database before anyone else can.
2. **Host PC:** in the add-on, turn on the LAN port with TLS, set **SpacetimeDB** to `https://maincloud.spacetimedb.com` and **Database** to the name. Then run `npm run bridge -- host --database <database>` and paste the session token when asked.
3. **Remote PC:** run `npm run bridge -- join --database <database>` with the same token. In the Client-role add-on, connect to `127.0.0.1` port `8767` with that token and **Use TLS with the token** on.

Both bridges take `--url` (default `https://maincloud.spacetimedb.com`). The host bridge also takes `--blender HOST:PORT`, and the join bridge `--listen HOST:PORT`, both defaulting to `127.0.0.1:8767`. Set `SPATIAL_MODELING_TOKEN` to skip the prompt. The bridge uses generated bindings in `bridge/module_bindings/`. After changing `src/`, regenerate them like the board's: `spacetime generate --lang typescript --out-dir bridge/module_bindings --module-path . -y`.

**Not done yet:**

- One real run on two home networks (Talia).
- Windows packaging of the bridge (Lee).
- Unity reaching a remote host. The VR app still talks to its own PC's host on `127.0.0.1:8765`, so the headset must sit with the host.
- Maincloud's own limits on message size and rate. This draft stays at 64 KiB frames.
- Claiming the host on Maincloud is first come, first served: the add-on claims as soon as it connects, so there's a short window after publishing.

## Security notes

- Only the identity that called `claim_host` first can write. That is the first caller, so the host must claim right after the first publish. Check this before a demo (step 5). Anonymous HTTP callers get a fresh identity each time and are rejected.
- SQL `INSERT`, `UPDATE` and `DELETE` are refused for everyone except the database owner (tested), so the reducers are the only way to write.
- The server sends `Access-Control-Allow-Origin: *`. Any web page open in a browser on Talia's PC can read the public tables: names, lease targets and receipt summaries. It can't write. Keep secrets out of these tables; there are none now.
- Session tokens and SpacetimeDB tokens stay out of Git. `spacetime/.gitignore` covers `node_modules/`, `dist/` and the generated bindings.

# SpacetimeDB session state

The SpacetimeDB module is Coplanar's session authority. Its `acquire` reducer decides who may edit which object, its tables hold who is connected and what each person is editing, and on Maincloud it relays the second Blender's connection between networks ([below](#across-the-internet)). It only relays that connection as TLS ciphertext it can't read, and it never stores geometry, snapshots or commands. The wire format in [contracts/README.md](../contracts/README.md) doesn't change: the host builds `session.update`, `lease.granted` and refusals from these tables.

| File | What it is |
| --- | --- |
| [`src/index.ts`](src/index.ts) | The module: its tables, reducers and views. |
| [`../blender_addon/spatial_modeling/session_store.py`](../blender_addon/spatial_modeling/session_store.py) | The host's side: the `SessionStore` interface, `SpacetimeStore` (stdlib HTTP), `MemoryStore`, and `MirroredStore`, which the host uses to send lease requests to SpacetimeDB on a background thread. |
| [`board/`](board/) | The session board: a live page subscribed to the module with the TypeScript SDK. |
| [`bridge/`](bridge/) | The internet bridge: carries a remote Blender's connection to the host through the module. |
| [`LatencyProbe/`](LatencyProbe/) | A C# console app on the official C# SDK that measures subscription latency. |
| [`measure.py`](measure.py) | Measures reducer, SQL and subscription round trips (stdlib only). |
| [`../tests/backend/test_session_store.py`](../tests/backend/test_session_store.py) | Runs every store test against both stores; the SpacetimeDB half is skipped when no server is running. |

## The module

| Table | Visibility | Holds |
| --- | --- | --- |
| `participant` | public | Everyone in the session: actor ID, name and role (VR, Blender client or host). |
| `lease` | public | Who is editing which objects, and when each lease expires. |
| `label` | public | The names of leased objects, for the session board. |
| `refusal` | public | The latest refused lease requests: who asked, for what, and the lease that blocked them. |
| `receipt` | public | Summaries of applied requests. The host currently answers `receipt.query` from its own log in `commands.py`. |
| `authority` | private | The host's identity. Only the host can call the session reducers. |
| `room`, `pipe`, `frame` | private | The internet relay. Each bridge reads its own rows through the `my_pipe` and `my_frame` views. |

Reducers: `claim_host` and `reset_host`; `join`, `leave`, `acquire`, `renew`, `release` and `expire` for the session; `record_receipt`, `set_labels` and `note_refusal`; `open_room`, `open_pipe`, `send`, `ack` and `close_pipe` for the relay.

## Setup

Pin version **2.13.0** of everything: the CLI and server, the npm package (pinned in `package-lock.json`) and any client SDK.

1. **Node.js 22 or later** builds the module. On Windows: `winget install OpenJS.NodeJS.LTS`, then open a new terminal.
2. **SpacetimeDB CLI and server.** On Windows, in PowerShell: `iwr https://windows.spacetimedb.com -useb | iex`. On Linux or macOS: `curl -sSf https://install.spacetimedb.com | sh`. Then, in a new terminal:

   ```sh
   spacetime version install 2.13.0
   spacetime version use 2.13.0
   spacetime --version            # must say 2.13.0
   ```

3. **Start the server on localhost only**, in its own terminal, and keep it open while you work:

   ```sh
   spacetime start --listen-addr 127.0.0.1:3000
   ```

   Always pass `--listen-addr 127.0.0.1:3000`. Without it, the server listens on every network interface (`0.0.0.0:3000`) with no TLS. If Windows Firewall asks whether to allow access, choose **Cancel**. If port 3000 is taken, use another port here and give the same URL to the add-on.
4. **Publish the module**, from a checkout of this repo:

   ```sh
   cd spacetime
   npm ci
   spacetime publish -y           # spacetime.json: local server, database "spatial-modeling"
   spacetime sql spatial-modeling "SELECT * FROM lease"   # an empty table
   ```

   The first publish logs the CLI into the local server, and that CLI identity owns the database. Publish again after a module change; the data is kept unless the schema changes incompatibly.
5. **Start the host.** The host claims the database the first time the add-on connects. To see who holds it, run `spacetime sql spatial-modeling "SELECT * FROM authority"`: slot 0 is the publisher and slot 1 the host. If the host's token is lost, free the slot with `spacetime call spatial-modeling reset_host`, then restart the host.

## How the host uses it

The host add-on uses SpacetimeDB through `MirroredStore` in `session_store.py`. The **SpacetimeDB** preference picks **This PC** (`http://127.0.0.1:3000` by default) or **Maincloud**, and the preferences show which store is deciding.

- **SpacetimeDB decides.** When a client (VR or the remote Blender) asks for a lease, the add-on hands the request to a background thread (`spacetime-mirror`). The thread calls the module's `acquire` reducer, which grants or refuses it atomically, and the host answers the client with that decision. A lease that only SpacetimeDB holds still refuses the request.
- **Blender never waits.** The main thread only hands the request over; the answer goes out on the add-on's next 20 ms drain. On localhost a client gets its answer in about 5 to 25 ms.
- **Every read is local.** The host keeps the leases SpacetimeDB granted in memory, so each command's lease check, the desktop lock and `session.update` never touch the network.
- **The rest is copied, in order.** Joins, leaves, releases and the host desktop's own leases apply locally at once. The thread copies them in the order leave, release, join, acquire, so the reducer always decides against the current session. The reducers check those copies too, and a disagreement is logged.
- **Refusals and names.** The thread records each refusal in the `refusal` table and the names of leased objects in `label`, for the session board.
- **Lifetime.** Leases have the contract's 6 s TTL, and the thread renews them every 2 s, even while a render keeps Blender busy. If Blender quits or crashes, subscribers stop seeing its leases within 6 s.
- **If the server drops.** Blender keeps deciding leases in memory and retries every 5 s. When the server is back, the thread clears what an earlier host left and copies the current session there. If a reducer call fails midway, memory decides that request, and SpacetimeDB gets the current state on reconnect.
- **Token.** It's kept in Blender's config folder as `spatial_modeling/spacetime-host-token` (`spacetime-host-token-maincloud` for Maincloud). If the preferences say "another identity is already the host", run `spacetime call spatial-modeling reset_host` and re-enter the SpacetimeDB preference.

The remote Blender client joins through the host's TLS LAN port (8767): directly on a LAN, or through the bridges [across the internet](#across-the-internet).

## The session board

A live page of who's connected, who's editing what, and every SpacetimeDB decision as it happens, such as "SpacetimeDB refused Lee's request for Cube: Talia is editing Cube", each with how fast the subscription pushed it. It only reads.

```sh
cd spacetime
npm ci                 # once, and after pulling module changes
npm run board          # then open http://127.0.0.1:3100
npm run board -- --url http://127.0.0.1:3000 --database spatial-modeling --port 3100   # the defaults
```

[`board/server.ts`](board/server.ts) subscribes with the official TypeScript SDK and pushes each change to [`board/index.html`](board/index.html) over Server-Sent Events. It listens on 127.0.0.1 only. `board/module_bindings/` is generated; after changing `src/`, regenerate it with `spacetime generate --lang typescript --out-dir board/module_bindings --module-path . -y`.

## Across the internet

For two PCs with no shared network, so no LAN address, port forwarding or VPN is needed. Both PCs connect out to the same database on Maincloud, and a small Node bridge on each PC carries the host connection through it. Neither add-on changes how it connects.

```
remote Blender --TLS-PSK--> join bridge --wss--> Maincloud <--wss-- host bridge --> host Blender :8767
  (127.0.0.1:8767)                         room / pipe / frame                       (LAN port on)
```

The module is published on Maincloud as `calhacks13-spatial-modeling`. The add-on and both bridges use that name by default.

### Run it

Every PC needs Node 22 or later and `npm ci` in `spacetime/`.

1. **Host PC:** in the add-on, turn on the LAN port with TLS and switch **SpacetimeDB** to **Maincloud**. Then run `npm run bridge -- host` and paste the session token when asked.
2. **Remote PC:** run `npm run bridge -- join` with the same token. In the Client-role add-on, connect to `127.0.0.1` port `8767` with that token and turn on **Use TLS with the token**.

Both bridges take `--url` (default `https://maincloud.spacetimedb.com`) and `--database` (default `calhacks13-spatial-modeling`). The host bridge also takes `--blender HOST:PORT`, and the join bridge takes `--listen HOST:PORT`. Both default to `127.0.0.1:8767`. Set `SPATIAL_MODELING_TOKEN` to skip the token prompt.

### Changing the module

After changing `src/`, regenerate the bridge's bindings and republish (this needs the publisher's `spacetime login`):

```
spacetime generate --lang typescript --out-dir bridge/module_bindings --module-path . -y
spacetime publish -s maincloud -y calhacks13-spatial-modeling
```

The first add-on to connect in Maincloud mode becomes the host. If the wrong identity claims it, or the host's token is lost, the publisher frees the slot with `spacetime call -s maincloud calhacks13-spatial-modeling reset_host`.

### How the relay works

- **Relay.** Each TCP connection is a `pipe`, and its bytes travel as numbered `frame` rows. `send` checks that the caller owns the pipe and that frames arrive in order, and the receiver deletes them with `ack`. At most 64 frames of 64 KiB are in flight in each direction. When a bridge disconnects, `on_disconnect` closes its room or pipes, and Blender reconnects as it does after any lost connection.
- **Encryption.** The bridges pass the TLS-PSK bytes through unchanged, so Maincloud only stores ciphertext. The join bridge refuses any connection that doesn't start with a TLS handshake, so the add-on's no-TLS fallback can't send the token through the relay.
- **Access.** `room`, `pipe` and `frame` are private. Each bridge sees only its own rows, through the `my_pipe` and `my_frame` views. The session token never leaves either PC. A bridge sends a room ID and a proof, both derived from the token, so only someone with the token can open the room or connect to it.
- **Local or cloud.** Either way, the same `acquire` reducer decides leases. Each server has its own host token, so the host keeps its claim on both when you switch between them. Calls to Maincloud take a few hundred milliseconds, but they run on the mirror thread, so Blender never waits for them.

The VR headset stays at the host's PC: the Unity app talks to its own PC's host on `127.0.0.1:8765`.

## Security

- Only the identity that called `claim_host` first can write, so the host should connect right after the first publish (setup step 5). Anonymous HTTP callers get a fresh identity each time and are rejected.
- SQL `INSERT`, `UPDATE` and `DELETE` are refused for everyone except the database owner, so the reducers are the only way to write.
- The session tables are public. Anyone who knows the database name can read participant names, lease targets, refusals and receipt summaries, and the local server sends `Access-Control-Allow-Origin: *`, so any web page on the host PC can read them too. Nobody else can write, and no secrets are stored there.
- Session tokens and SpacetimeDB tokens stay out of Git. `spacetime/.gitignore` covers `node_modules/`, `dist/` and the generated bindings.

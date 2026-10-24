# Contracts

The wire formats between our processes (see "Architecture" in [PHASE_PLAN.md](../PHASE_PLAN.md)). Owner: Waaberi. Any change updates the sender, the receiver and this file in the same PR.

- **Schemas:** [`schemas/<type>.schema.json`](schemas/), JSON Schema draft 2020-12. They `$ref` the shared [`envelope.schema.json`](schemas/envelope.schema.json) (and each other) by file name.
- **Examples:** [`examples/<type>.json`](examples/), plus `<type>.<variant>.json` where one example isn't enough (for example one per command `op`). Fake servers and clients can replay them; they tell one story with the same IDs.
- **Check:** `pytest tests/backend/test_contracts.py` validates every example and a list of broken messages.

## Host connection

Used by the Unity app and by Client-role add-ons to talk to the Host-role add-on.

- **Transport:** TCP. The Unity app connects to `127.0.0.1:8765`: plain TCP, localhost only. Client-role add-ons connect to the host's LAN address on port `8767` (see [LAN port](#lan-port)).
- **Framing:** one UTF-8 JSON object per line, ending in `\n`. A line longer than 16 MiB closes the connection. `NaN` and `Infinity` aren't JSON; receivers reject them, and numbers too large for a double (such as `1e999`).
- **Coordinates and units:** Blender's own: right-handed, Z up, meters, radians. Unity converts in one place: see [Blender to Unity](#blender-to-unity) and [Identity, revisions and units](#identity-revisions-and-units).
- **Implementation:** framing in [`protocol.py`](../blender_addon/spatial_modeling/protocol.py), the host's transport in [`server.py`](../blender_addon/spatial_modeling/server.py) and [Connecting](#connecting) in [`session.py`](../blender_addon/spatial_modeling/session.py). [`tests/backend/hello_client.py`](../tests/backend/hello_client.py) joins a running host from a terminal.

Every message has this envelope:

| Field | Type | Meaning |
| --- | --- | --- |
| `v` | integer | Contract version, currently `1`. On a mismatch, the receiver replies `error` and closes. |
| `type` | string | Message type, for example `ping`. |
| `id` | string | Unique ID of this message: 32 lowercase hex digits (Python `uuid4().hex`, C# `Guid.ToString("N")`). For a request it is the request ID, which deduplicates it. |
| `re` | string, optional | The `id` of the request this message answers. |
| `payload` | object | Type-specific content. Unknown fields are rejected. |

### Message types

| Type | Direction | Payload | Phase |
| --- | --- | --- | --- |
| `hello` | client → host | `role` (`vr` or `blender-client`), `name` of the person, `app` name and version; optional `document` it expects; `token` on the LAN port without TLS | P1 |
| `welcome` | host → client, answers `hello` | `session_id`, `host_epoch`, this connection's `actor_id`, `can_edit`, host `app`, `document` (ID, open epoch, file name, revision, dirty, units) | P1 |
| `error` | either way | `code`, `message`, optional `details` | P0 |
| `ping` | either way | `{}`. Also the heartbeat | P0 |
| `pong` | either way, answers `ping` | `{}` | P0 |
| `scene.snapshot` | host → client | `document`, every object and sketch | P1 (empty lists), P2 |
| `scene.update` | host → every client | `document`, changed objects and sketches, `removed` IDs | P2 |
| `command` | client → host | request fields, `base_revision`, `source`, `op`, `target`, `args`, optional `lease` | P3A |
| `result` | host → sender, answers `command` | the command's receipt: `outcome`, `revision`, `error` if rejected | P3A |
| `activity` | host → every other client | the receipt of a command someone applied, or of an edit made directly in host Blender | P2, P3B, P5 |
| `receipt.query` | client → host | `host_epoch` the requests were sent under, `request_ids` (1 to 100) | P5 |
| `receipts` | host → client, answers `receipt.query` | `receipts`; `missing` IDs the host never received (never applied); `unknown` IDs it has no record of but may have applied | P5 |
| `lease.acquire` | client → host | request fields, `mode` (`exclusive` or `shared`), `targets` | P3B |
| `lease.granted` | host → client, answers `lease.acquire` | the `lease` | P3B |
| `lease.release` | client → host | `lease_id`; no reply on success | P3B |
| `session.update` | host → every client | every participant and every lease | P1, P3B, P5 |

There is no voice message type and no frame message type; see [Voice](#voice) and [Blender screen](#blender-screen).

### LAN port

The host listens on `8767` only while "Let a Client-role Blender join over the LAN" is on in its add-on preferences, on all interfaces unless a single address is entered there. The preferences also show the **session token**: generated when the port first starts, or typed in (at least 16 characters). Case, spaces and dashes in it don't matter. Keep it out of Git and logs. [`lan.py`](../blender_addon/spatial_modeling/lan.py) implements both ends; clients use `lan.connect()` or `lan.client_tls_context()`.

- **TLS (default):** TLS 1.3 with the token as an external pre-shared key, no certificates. TLS 1.2 is accepted only with `ECDHE-PSK-CHACHA20-POLY1305`. PSK identity `spatial_modeling/1`; key = PBKDF2-HMAC-SHA256 of the token (lowercase, without spaces and dashes), salt `spatial_modeling LAN PSK v1`, 200,000 rounds, 32 bytes. A wrong or missing token fails the handshake, and the client must refuse a host that presents a certificate instead. The host drops a handshake that takes over 10 s.
- **Without TLS (fallback):** for a network where TLS-PSK fails, and only on an isolated route, because the token and every message can be read on the network. The first message must be a `hello` carrying `token` within 10 s (see [Connecting](#connecting)).

## Connecting

1. The client connects and sends `hello`. Until it has been welcomed, the host answers only `hello` and `ping`; anything else gets `error` `permission_denied` and the connection stays open. A `hello` that doesn't match its schema gets `invalid_message` and the connection stays open; so does a second `hello` on a welcomed connection.
   - On the LAN port with TLS, the handshake has already checked the token.
   - On the LAN port without TLS, the first message must be `hello` with the right `token`. Otherwise the host replies `error` `permission_denied` (`invalid_message` if it isn't a message at all) and closes, before any other check. The host removes `token` before any handler sees the `hello`, and ignores it on the other ports.
2. The host replies `welcome`, then sends `scene.snapshot`, then `session.update` to every participant on either port, the new one included. A reconnect is a new connection like any other: a new `actor_id`, a fresh snapshot, and nothing replayed (see [Reconnecting](#reconnecting)). The client is connected once it has the snapshot. It sends no `command` or `lease.acquire` before that. Both ports get the same snapshot and every `scene.update` after it (see [Scene](#scene)); `sketches` stays empty until P3C. (A P1 host sent empty `objects` too; that didn't mean the file was empty.)
3. If the host refuses the `hello`, it replies `error` (with `re`) and closes the connection. It checks in this order:
   - `permission_denied`: the host doesn't admit this client here. `127.0.0.1:8765` admits only role `vr`, the LAN port only `blender-client`.
   - `unsupported_version`: the envelope's `v` differs, or a Client-role add-on's `app.version` differs from the host's (P5-M1-3). The Unity app's version isn't compared.
   - `wrong_document`: the `hello` named a `document` and the host has another one (or another opening of it) open. `details.document` has the host's `id`, `open_epoch` and `name`.
4. `welcome` makes the connection a participant with its own `actor_id`. `can_edit` is true for `vr`. For `blender-client` it is false unless the host turned on "Let the Client role edit (test only)" in its add-on preferences (P3A-W-3; off by default, and changing it reconnects everyone). A connection that can't edit gets `permission_denied` for every `command`. Whenever someone joins or leaves (its connection closes for any reason), every participant gets `session.update`.
5. Loading another `.blend` (or reverting), disabling the add-on and switching the role all close every connection. Clients reconnect and get the new document in `welcome`. A connection never spans two documents.
6. **Heartbeat:** clients send `ping` every 2 s. A client that hears nothing from the host for 6 s shows "Blender is not responding" and disables edits; a closed socket means disconnected. The host treats a client it hasn't heard from for 6 s as gone: when no complete line has arrived for 6 s it closes the connection, which also ends its leases. The host reads on its own thread, so a busy Blender (a render, a long operator) doesn't drop clients; their pongs just wait.

**Starting and attaching.** The pieces can start in any order. Blender with the add-on enabled in Host role listens on 8765 from startup and again after every file load, so attaching the app to an already open Blender (with unsaved work) needs nothing from Blender. The Unity app connects, and reconnects every 2 s while it can't (see Disconnected below). The capture helper serves 8766 on its own and is independent of the add-on. Closing Blender closes the connection; the app keeps the stale scene until Blender is back.

The connection states the app shows are worked out by the client, not sent as messages:

| State | The client knows because |
| --- | --- |
| Connecting | The socket is open and no `welcome` has arrived. |
| Connected | `welcome` and `scene.snapshot` have arrived. |
| Not responding | Nothing from the host for 6 s on an open socket. Edits stay disabled until the host answers again. |
| Disconnected | The socket closed. Keep showing the last scene, marked as stale, with edits disabled (P5-M2-3). Reconnect every 2 s; the fresh snapshot replaces the stale scene. |
| Wrong document | `welcome.document.id` or `open_epoch` differs from the document the client had. Drop drafts, pending voice commands and anything held for the old document, and show the new file name. The VR app then follows the host's document. The Client role instead sends `document` in `hello` and gets `error` `wrong_document`, so it never mixes two documents in one session file. |
| Version mismatch | `error` `unsupported_version`. |

## Errors

`error` payload: `code`, `message` (short, safe to show the user) and, for some codes, `details`.

A `command` gets exactly one `result`, and a rejected command's reason is in `result.payload.error`. The exception is a command that never reached its handler: it gets an `error` with `re` set (`invalid_message`, `unknown_type`, `busy` or `internal_error`). Any other failed message gets an `error`, with `re` set when its `id` could be read.

The first six codes are the transport-level codes that [`server.py`](../blender_addon/spatial_modeling/server.py) sends. It also sends `permission_denied` for anything but `hello` and `ping` before `welcome`:

| Code | Meaning | Then |
| --- | --- | --- |
| `invalid_message` | Not JSON, a bad envelope, or a payload that doesn't match its schema (unknown `op`, missing field, number out of bounds). | Connection stays open. |
| `unsupported_version` | Wrong `v`, or a Client-role add-on version that differs from the host's. | Host closes. |
| `message_too_large` | A line over 16 MiB. | Host closes. |
| `unknown_type` | Nothing handles this `type`. | |
| `busy` | Too many messages are waiting for Blender. The message was dropped and never applied. | The same message can be sent again later. |
| `internal_error` | The handler failed. | For a command, the outcome is unknown (see [Outcomes](#outcomes)). |
| `permission_denied` | Not welcomed yet, read-only (`can_edit` is false), `actor_id` isn't this connection's, or the host has stopped writes while it reconciles. A `lease.release` or a command's `lease` names someone else's lease, or that lease doesn't cover the command's target. On the LAN port without TLS: the first message wasn't `hello` with the right `token`. | After a token failure, host closes. |
| `wrong_session` | `session_id` or `host_epoch` is not the current one: the request was built before the host restarted. | Reconnect. |
| `wrong_document` | `document_id` or `open_epoch` is not the open document, or `hello` expected another document. `details.document`: the open one. | |
| `not_found` | The target, lease or sketch entity doesn't exist (for example it was deleted, or the lease ended). | |
| `stale_revision` | The target changed since the client saw it, or Undo/Redo was sent from an old revision. `details.generation` or `details.revision`: the current value. | Look again, then make a new request. |
| `lease_conflict` | Another participant's lease covers the target or the document. `details.lease`: that lease, with the owner's name. | |
| `duplicate_request` | A request ID was reused with a different payload, or arrived after `receipt.query` had reported it `missing` or `unknown` (see [Reconnecting](#reconnecting)). | Use a new ID. |
| `solver_conflict` | The sketch solver can't satisfy the constraints. The sketch is unchanged. | |
| `failed` | Blender refused (nothing to undo, a file that was never saved). Nothing changed. | |

## Identity, revisions and units

| Name | What it is |
| --- | --- |
| Object ID | UUID hex in the custom property `spatial_modeling_id` on each Blender object. It survives renames, Undo and save/reopen. The host assigns missing IDs and gives a duplicated object a new one (the object that had the ID keeps it). It writes them outside any Undo step, so an Undo can take one away again; the host remembers which object it gave each ID until the next file load and gives the same one back. Sketches have the same kind of ID. |
| Sketch entity and constraint IDs | Strings of 1 to 64 letters, digits, `_` or `-`, unique within their sketch and stable across Undo/Redo and save/reopen. The CAD adapter picks them. |
| `document.id` | UUID hex the host stores in the `.blend` file the first time it opens it (the custom property `spatial_modeling_document_id` on every scene); it survives save/reopen. A file that is closed without saving gets a new one next time. |
| `open_epoch` | New UUID hex every time the host opens or reloads the file, and whenever its revision counter restarts. |
| `revision` | Starts at 0 for each open epoch and goes up with every accepted change: commands and direct edits in host Blender alike. It can jump by more than one when the host batches changes. Revisions are only comparable within one open epoch. Leases, presence, selection and Save don't change it. |
| `generation` | On each object and sketch: the revision at which it last changed. |
| `session_id` | UUID hex of the hosting session, kept with the session token in the host's add-on preferences. It stays the same when the host restarts. |
| `host_epoch` | New UUID hex every time the host's server starts. |
| `actor_id` | New for every connection, given in `welcome`. The host's own Blender is the participant with role `host`: whoever works at the host desktop. Its name is the "Your name" add-on preference, or `Host Blender` if that is blank; a change reaches everyone as `session.update`. Its `actor_id` is new with every `host_epoch`. |

**Units.** Numbers on the wire are always meters and radians. The host converts Blender units to meters by multiplying by the scene's Unit Scale (`scale_length`), so a 100 mm part is `0.1` whatever the scene settings. `document.units` copies the scene's settings for display only: Unity shows millimeters when `length_unit` is `MILLIMETERS`, and the Client role copies the settings into its session file. Field names carry no unit suffix; the contract fixes the units, and the schema bounds catch the worst slips (an angle of 90 is rejected).

**Transforms** are in world space: `location` in meters, `rotation` as a quaternion in Blender's order `[w, x, y, z]` (Unity's `Quaternion` is `x, y, z, w`), and `scale` factors. The host decomposes the object's world matrix; shear from a non-uniformly scaled parent is lost. `parent` gives the hierarchy.

## Scene

`scene.snapshot` describes everything and replaces what the client had. The host sends it after `welcome`, and again to everyone whenever it can't describe a change as an update (after the unit settings change, every object's generation is the new revision). It lists every object in the view layer the host Blender shows: objects in excluded collections are left out, hidden ones are sent with `visible` false. Collection and geometry-nodes instances aren't sent yet. Parents come before their children.

`scene.update` carries changes in order, after Blender has committed them. `objects` and `sketches` hold complete records that replace those with the same `id`. An object in an update leaves out `mesh` when only its transform, name, color or visibility changed. `removed` lists deleted object and sketch IDs. `document` carries the new revision and the dirty flag, so an update with empty lists means only the dirty flag or file name changed (after Save). Each update raises `revision` by one, and every object in it has that `generation`. Moving a parent also sends its children, whose world transforms changed.

**Direct edits in host Blender** are changes like any other. The host watches Blender (its depsgraph, Undo, Redo and file loads; [`sync.py`](../blender_addon/spatial_modeling/sync.py)) and sends what changed as one `scene.update` to every client, at most 20 a second and less often while heavy meshes are re-sent, so a drag in Blender streams small updates with the latest state. Clients never echo them. They also get `activity`, with `actor` the host's own participant (role `host`), so VR and the Client role see what the host desktop did; that isn't sent yet, and its receipt fields (`request_id`, `op`, `source`) are settled when it is.

| Object field | Meaning |
| --- | --- |
| `id`, `name` | Stable ID and Blender name. |
| `type` | Blender object type: `MESH`, `CURVE`, `FONT`, `EMPTY`, `CAMERA`, `LIGHT` and so on. |
| `parent` | Parent object ID, or `null`. |
| `generation` | Revision of its last change. |
| `visible` | Shown in the viewport: not hidden, and neither are its collections. |
| `transform` | World `location`, `rotation`, `scale`. |
| `color` | Linear RGBA (0 to 1) of the first material's Base Color, or `null` without a material. |
| `mesh` | The evaluated mesh, or `null` for objects without geometry (cameras, lights, empties, armatures and so on). |

**Mesh encoding.** The mesh is evaluated (after modifiers; curves, surfaces, text and metaballs converted to a mesh) and triangulated, in the object's local space in meters. `positions` and `normals` hold 3 numbers per vertex, and `indices` 3 vertex indices per triangle, counter-clockwise seen from the front (Blender's winding; Unity flips it when it converts handedness, see [Blender to Unity](#blender-to-unity)). Vertices are split only where normals differ, so Unity can use the arrays as they are: a smooth mesh keeps Blender's vertices, and flat faces get their own, shared by coplanar neighbours. Positions are rounded to 1 µm, normals and rotations to 6 decimals, and scale factors to 6 significant digits. Plain JSON arrays are simple but large. A binary or delta encoding is a later optimization, and `v` lets us change the format. Until then a message has to fit in one 16 MiB line: measured, a 100,000-vertex smooth mesh (200,000 triangles) is 7 MB, and a flat-shaded sphere of 80,000 triangles (no two faces coplanar, so 3 vertices each) 15 MB. When a snapshot or update wouldn't fit, the host sends the biggest meshes as `null` and says so in Blender's console.

## Blender to Unity

The wire stays in Blender's frame. The Unity app converts in exactly one place, where it reads and writes messages (P2-W-2). [`tests/backend/test_coordinates.py`](../tests/backend/test_coordinates.py) checks these formulas numerically against Unity's own math, and `test_scene.py` applies them to real Blender objects.

Blender is right-handed with Z up; Unity is left-handed with Y up. Swapping Y and Z maps one onto the other: Blender's X (right), Y (away from you in Blender's Front view) and Z (up) become Unity's X, Z (forward) and Y (up), so Blender's Front view looks like Unity's default view.

| Wire (Blender) | Unity |
| --- | --- |
| Point or direction `[x, y, z]`: `location`, mesh `positions` and `normals`, `object.move` arguments | `new Vector3(x, z, y)` |
| `rotation` `[w, x, y, z]` | `new Quaternion(-x, -z, -y, w)` |
| `scale` `[x, y, z]`, `object.scale` arguments | `new Vector3(x, z, y)` |
| `indices`: each triangle `a, b, c` | `a, c, b` |
| Lengths in meters | Unity units: 1 unit is 1 m, whatever `document.units` says |

Commands go back the same way: Unity's `Vector3(x, y, z)` is `[x, z, y]` and `Quaternion(x, y, z, w)` is `[w, -x, -z, -y]`. An `object.rotate` `by` about Unity's X, Y or Z axis is `axis` `X`, `Z` or `Y` with the angle negated.

- **Rotations:** the swap is a mirror. A mirrored rotation turns by the same angle about the mirrored axis, but the other way round, so the quaternion's vector part changes sign. Blender's +90° about Z (X turns towards Y) is Unity's −90° about Y (X turns towards Z).
- **Triangles:** a mirror also reverses every triangle. Blender's front faces are counter-clockwise seen from the front; Unity's are clockwise seen from the camera. Swapping two indices per triangle keeps the outside out, so back-face culling works. Normals convert like positions and stay unit length.
- **World transforms:** put every object directly under the table's display root and set its `localPosition`, `localRotation` and `localScale` from the converted `transform`. Don't nest the Unity objects by `parent`, or the parents' transforms apply twice; `parent` is for selection and outlines. Moving, rotating or scaling the table changes only that root (P2-M2-2).
- **Units:** meters on the wire and in Unity. `document.units` only chooses how to show them: with `length_unit` `MILLIMETERS`, show 1000 × meters with "mm".

```csharp
// Blender's frame (right-handed, Z up) to Unity's (left-handed, Y up). The way back is the same swap.
static Vector3 Point(float x, float y, float z) => new Vector3(x, z, y);  // positions, normals, location, scale
static Quaternion Rotation(float w, float x, float y, float z) => new Quaternion(-x, -z, -y, w);  // wire [w, x, y, z]
static void FlipTriangles(int[] t) { for (int i = 0; i < t.Length; i += 3) (t[i + 1], t[i + 2]) = (t[i + 2], t[i + 1]); }
```

## Commands

Every client request that changes or reserves something (`command`, `lease.acquire`) repeats these request fields, copied from `welcome`. The envelope `id` is the request ID.

| Field | From `welcome` |
| --- | --- |
| `session_id` | `session_id` |
| `host_epoch` | `host_epoch` |
| `document_id` | `document.id` |
| `open_epoch` | `document.open_epoch` |
| `actor_id` | `actor_id` |

A `command` adds:

| Field | Meaning |
| --- | --- |
| `base_revision` | The latest revision this client had applied. |
| `source` | `ui` or `voice`: how the user asked. Shown in receipts and activity. |
| `op` | What to do (table below). Unknown ops are `invalid_message`. |
| `target` | `{id, generation}` of the object or sketch to change, with the generation the client last saw. Required for the ops that have a target, forbidden for the others. |
| `args` | The op's arguments. Ops without arguments send `{}`. |
| `lease` | Optional `lease_id` of a lease this actor holds that covers the target. A lease that has ended is `not_found`; someone else's, or one that doesn't cover the target, is `permission_denied`. See [Leases and presence](#leases-and-presence). |

| `op` | Target | `args` | Notes |
| --- | --- | --- | --- |
| `object.add` | none | `primitive` (`cube`, `sphere`, `cylinder`), `location` [x, y, z], `dimensions` [x, y, z] | `dimensions` is the bounding box; a cylinder's diameter is X and Y and its depth is Z. The receipt's `created` has the new ID. |
| `object.move` | object | `by` [dx, dy, dz] or `to` [x, y, z] | World space. |
| `object.rotate` | object | `by` {`axis`: `X`, `Y` or `Z`, `angle`} or `to` [w, x, y, z] | `by` turns about a world axis through the object's origin. |
| `object.scale` | object | `by` [sx, sy, sz] or `to` [sx, sy, sz] | Along the object's own axes; `by` multiplies. |
| `object.delete` | object | `{}` | |
| `history.undo`, `history.redo` | none | `{}` | Blender's shared history. `base_revision` must equal the current revision, so nobody undoes a change they haven't seen. Refused with `lease_conflict` while another participant holds a lease. |
| `document.save` | none | `{}` | Saves to the current file; `failed` if it was never saved. Save As is done only at the host desktop, in host Blender: there is no Save As over the wire, so no client sends file paths. |
| `sketch.*` | sketch | see [Sketches](#sketches) | |

**Selection is local to each client.** There is no select command: selecting in VR or in the Client role's Blender changes nothing on the host (not the host Blender's selection, not the revision, not the Undo history), and the host desktop's selection isn't sent to anyone. Others' selections may show up through presence later.

**Bounds** (enforced by the schemas): coordinates within ±1000 m, lengths from 1 µm to 1000 m, scale factors from 0.001 to 1000, `rotate.by` angles within ±2π, sketch angles above 0 and up to π.

**How the host checks a command,** in this order:

1. Schema: otherwise `error` `invalid_message`.
2. Request ID: a repeat with an identical payload gets the stored result again and is never re-applied (if it is still running, the host answers once when it finishes). This comes before admission, so a repeat sent after a reconnect, with the old `actor_id`, still gets its stored result. A repeat with a different payload, a new `actor_id` included, is rejected with `duplicate_request`.
3. Admission: welcomed, `can_edit`, `actor_id` is this connection's. Otherwise `permission_denied`.
4. `session_id` and `host_epoch`, otherwise `wrong_session`; `document_id` and `open_epoch`, otherwise `wrong_document`.
5. The target exists (`not_found`) and its generation is current; for Undo/Redo, `base_revision` is current (`stale_revision`).
6. Leases, immediately before the write: the command's own `lease`, if it names one, then nobody else's lease may cover what would change (`lease_conflict`). See [Leases and presence](#leases-and-presence).
7. Apply on Blender's main thread, push one Undo step, read the result back. Then send `scene.update` to every client, `result` to the sender and `activity` to the others, in that order. When a `result` arrives, the sender's scene already includes the change.

**In host Blender**, [`commands.py`](../blender_addon/spatial_modeling/commands.py) runs these checks and [`edits.py`](../blender_addon/spatial_modeling/edits.py) applies the command. It changes Blender's data directly, so the host desktop's selection and active object stay as they are, and each applied command is one Undo step named after its `summary`. It reads every edit back, and what Blender can't do exactly is refused with `failed`, leaving nothing changed:

- host Blender isn't in Object Mode (Save works in any mode);
- the target has constraints, is linked from another file, or doesn't end up where asked (a driver, or a parent scaled unevenly);
- a move would end more than 100 km from the origin, or a scale would leave the range 10⁻⁶ to 10⁶;
- `rotate.to` isn't a unit quaternion (within 0.001);
- nothing to undo or redo; Save of a file that was never saved.

`object.add` names the object as Blender's Add menu does (`Cube`, `Sphere`, `Cylinder`, then `.001` and so on), with 32 segments (and 16 rings for the sphere), centered on `location`, in the active collection. `object.delete` leaves the deleted object's children where they are. Undo and Redo say which command they undid in `summary` ("Undid: Moved Cube 10 mm along X"), or "Undid a change made in host Blender". Until P3C sketch ops get `failed`. The host keeps the receipts of the newest 10,000 requests, for deduplication and `receipt.query`, until its server restarts (see [Reconnecting](#reconnecting)).

### Outcomes

| `outcome` | Meaning |
| --- | --- |
| `applied` | Blender committed the change; `revision` is the new revision. |
| `rejected` | Nothing changed; `error` says why. |
| `unknown` | The host can't tell whether Blender changed, for example after a failure halfway through. The host refuses writes (`permission_denied`) until it has re-read the scene and sent every client a fresh snapshot; if it can't re-read it straight away, it keeps trying every 0.5 s. |
| `pending` | Only in `receipts`: the host has the command but hasn't finished it. |

A client treats an `internal_error` reply to a command, or a connection lost before the `result`, as unknown too. While any of its outcomes is unknown, the client stops sending edits. It reconnects if needed, asks with `receipt.query`, and waits for the fresh snapshot. It never resends a command whose outcome is unknown.

**Receipt fields** (the payload of `result` and `activity`, and the items of `receipts`): `request_id`, `op`, `target` (if any), `actor` (`actor_id`, `name`, `role`), `source`, `outcome`, `revision`, `created` (new IDs, if any), `solver` (sketch ops), `summary` (one line for activity lists, for example "Moved Shaft 10 mm along X"), `error` (if rejected or unknown) and `at` (Unix ms).

### Reconnecting

Recovery never replays anything: the host doesn't resend old results or activity to a connection, and clients don't queue edits while offline or resend them afterwards.

1. **Reconnect** on the same port, every 2 s (see [Connecting](#connecting)). The new `welcome` brings a new `actor_id`, and the `host_epoch` tells whether the host's server restarted in between. The fresh `scene.snapshot` replaces the stale scene; send no `command` before it has arrived. If `document.id` or `open_epoch` changed, drop everything held for the old document (Wrong document above).
2. **Ask about outstanding requests:** every command sent without a `result` (or answered with `internal_error`) goes into one `receipt.query` per `host_epoch` it was sent under, with that `host_epoch`. Requests sent under an earlier `actor_id` are found too: receipts are keyed by request ID alone, and any participant may ask about any request (the others saw it as `activity` anyway).
3. **Read the answer:**
   - In `receipts`: what happened, as the `result` would have said. `applied` means it happened, and the fresh snapshot already shows it; `rejected` means nothing changed; `unknown` means wait for the host's fresh snapshot (it follows straight away unless the host is still re-reading the scene).
   - `missing`: the host never received it in its current `host_epoch`, so it wasn't applied. From then on the host refuses that ID with `duplicate_request` rather than apply it, even if it arrives late over a half-open connection. Make a new request, with a new ID, if the user still wants it.
   - `unknown`: the host has no record and can't rule out that it applied it: the request was sent under an earlier `host_epoch` (the host restarted, which drops every receipt), or the host had dropped it from its 10,000 newest. Treat it like outcome `unknown`: the fresh snapshot shows what is true; tell the user to check before redoing it.
4. **Resume editing** once nothing is unknown any more and the snapshot has arrived.

Never resend instead of asking. A client that does anyway still can't apply anything twice: an identical repeat gets its stored `result`, one rebuilt with the new `actor_id` gets `duplicate_request`, and after a host restart the old request carries the old `host_epoch` and `actor_id` and is refused.

**Bounded receipt capacity.** After the first eviction from the 10,000-entry receipt/fence store, an unseen request ID may be an old applied request or a fenced late request. The host refuses every unseen command ID with `duplicate_request`; it never guesses that such an ID is new. Retained identical receipts remain readable and replayable. Use native File > Save in host Blender, then restart the hosting session to obtain fresh epochs and resume new edits; remote/VR `document.save` is also refused after capacity is exhausted. Reconnecting a client alone does not reset this safety boundary. Receipt queries can fill the same bounded store, including queries from a read-only participant; this can require an earlier session restart, but cannot cause a repeated native edit.

**Host restarts.** The host's server restarts when it loads a file (open, revert, new file), when the role, the LAN or the editing preferences change, and when the add-on or Blender restarts. Every restart starts a new `host_epoch` and a new `open_epoch`, and drops every receipt. Receipts aren't kept on disk: an old receipt couldn't be checked against the reopened scene, and a crash between Blender's commit and the receipt would still lose it, so a client must trust the snapshot either way. That is why the host answers an earlier `host_epoch`'s requests as `unknown`, never as `missing`. If the SpacetimeDB receipt log ([`session_store.py`](../blender_addon/spatial_modeling/session_store.py), not wired into the host yet) is added later, old requests it finds come back in `receipts`; `unknown` stays for the rest.

## Leases and presence

The host checks permission before every native change (P3B). [`leases.py`](../blender_addon/spatial_modeling/leases.py) implements this section; participants and leases live behind one interface, [`session_store.py`](../blender_addon/spatial_modeling/session_store.py), in memory unless SpacetimeDB is used (see below).

- **Exclusive** (`mode: "exclusive"`, `targets: []`) reserves the whole document. It is granted only while no other participant holds a lease. While it is held, other participants' commands get `lease_conflict` and the host blocks its own desktop edits (see The host desktop, below). For Exclusive editing mode, acquire it before the first native write (Apply, or the start of a drag) and release it after the commit or cancel.
- **Shared** (`mode: "shared"`) reserves the listed objects and sketches, plus their linked data; `lease.granted` lists what was actually reserved: the targets asked for, in order, then the linked data. Two shared leases conflict when their targets overlap. A sketch edit leases the whole sketch by its ID.
- **Linked data** of an object, followed transitively: the other objects that share its data (a mesh or curve, so editing it edits theirs), its children (their world transforms follow it, and deleting it re-parents them), and the objects whose modifiers or constraints use it (a Boolean cutter, a Mirror or Array object, a constraint target, a Geometry Nodes object input). Leasing Base plate in the examples also reserves Shaft, its child. A command's target is expanded again when it is checked, so links made after a lease was granted still count.
- A command without `lease` gets a lease for just that command: the host checks that no other participant's lease covers the target or its linked data, and holds nothing afterwards. That suits one-shot menu and voice commands. Drags, numeric edits and sketch sessions acquire a lease so that others see the ownership for the whole edit.
- A command with `lease` must name a live lease of its own that covers its target (an exclusive lease covers everything; a command without a target accepts any of its own leases). Nobody else's lease may cover the target either.
- `object.add`, `document.save` and `sketch.create` have no target, so only another participant's exclusive lease blocks them. `history.undo` and `history.redo` are refused with `lease_conflict` while another participant holds any lease.
- A participant's own leases never conflict with each other.
- **Expiry:** a lease ends when it is released, when its owner's connection closes, or when the host hasn't heard from the owner for 6 s: the host then closes the connection (see Heartbeat). The host times that on its reader thread, so a busy Blender doesn't end the leases of a client that keeps pinging. Expiry never interrupts a commit in progress: commits run one at a time on Blender's main thread, and a connection that closes during one keeps its leases until the commit has finished.

**Requesting.** `lease.acquire` is checked like a command: schema (`invalid_message`), request ID (the same ID with the same payload gets the same answer again and reserves nothing new; a changed payload gets `error` `duplicate_request`), admission (`permission_denied`), session and document (`wrong_session`, `wrong_document`), the targets exist (`not_found`), then conflicts (`lease_conflict` with `details.lease`, the blocking lease with its owner's name). A refusal is an `error` with `re`. When it is granted, every participant gets `session.update` with the new lease, and then the sender gets `lease.granted` with `re`, so the sender already sees itself as the owner. `lease.release` has no reply on success; everyone gets `session.update` without the lease. Releasing a lease that has ended is `not_found`, and someone else's lease `permission_denied`.

`session.update` always carries the complete lists, which replace the previous ones: `participants` (including the host's own Blender, role `host`) and `leases` (every participant's, the host's own included; the host desktop doesn't lease its own edits yet, it only waits for others' leases). It is sent whenever either list changes. Show a pink outline and the owner's name on the targets of other participants' leases, and "Two people are editing" while leases from two participants exist.

**The host desktop** ([`gate.py`](../blender_addon/spatial_modeling/gate.py), P3B) asks before its own edits too: while another participant's lease covers what an edit would change (anything at all for an exclusive lease, everything for Undo/Redo), host Blender refuses it before anything changes and says why in its status bar ("Lee is editing Cube", "Lee is editing — wait for Apply", "… so Undo and Redo wait until they finish"). Viewing, navigation and selection are never refused. Gated before the change: Blender's default editing shortcuts (transform, clear, Delete, the Add, Apply and context menus, duplicate, join, parent, Subdivision Set, Tab, Undo, Redo, and the Properties editor's and Outliner's Delete, Apply and Duplicate keys), clicks and button hotkeys in the Properties editor's object tabs and the 3D View sidebar's Item tab, the transform gizmo, the tools' drags, and Edit Mode (entered by another route, it is left again at once). Not gated: header menus, F3 search, the Python console, scripts, other add-ons, Outliner renaming and drag and drop, custom key bindings, and an edit already under way when a lease begins. A change by such a route to what someone else's lease covers is a **bypass**: strict locking did not hold. The host logs `STRICT LOCK BYPASSED`, warns in Blender and, as after an `unknown` outcome, refuses commands (`permission_denied`) until it has re-read the scene and sent every client a fresh `scene.snapshot`. Clients see a `scene.update` and then that snapshot; a command built on the old generation gets `stale_revision`.

**An edit begins** when its lease is granted, so the `session.update` that lists a lease you haven't seen before is the notice that someone started editing: show "Lee Jae-yeon started editing Base plate" from its `owner` and `targets`. There is no separate message for it; one would only repeat the lease row (who, what, `acquired_at`). A one-shot command without `lease` begins and ends in one step, so it shows up only as its `activity` after it is applied.

**SpacetimeDB.** A participant is an `actor` row and a lease a `lease` row, so if the spike passes, the host can call reducers and relay those tables as `session.update`, and Unity may subscribe to the tables directly instead. `lease.acquire` and `lease.release` still go through the host, which checks leases before every native write. If the spike fails, the host keeps the same rows in memory and nothing on the wire changes. Until the Windows run passes (issue #16), the host uses memory.

## Voice

VoiceCore runs inside the Unity app, so voice adds no message type: a completed voice command is an ordinary `command` with `source: "voice"`, and its receipt and activity carry that source so the host and the other participant see who said what. Clarifying questions stay inside Unity; VoiceCore builds the command only once it is complete, using the target's current generation, and drops a pending command when the client sees Wrong document or Disconnected.

## Sketches

CAD sketches use CAD Sketcher through Lee Jae-yeon's adapter on the host (P3C). They arrive in `sketches` in the snapshot and updates. `plane` is the sketch plane's world `location` and `rotation`; sketch coordinates `[u, v]` are meters along the plane's local X and Y.

| Entity `kind` | Fields |
| --- | --- |
| `point` | `at` [u, v] |
| `line` | `points` [point ID, point ID] |
| `circle` | `center` point ID, `radius` in meters |

| Constraint `kind` | `entities` | `value` |
| --- | --- | --- |
| `coincident` | 2 (point and point, or point and line) | none |
| `horizontal`, `vertical` | 1 line, or 2 points | none |
| `distance` | 1 line (its length), or 2 entities | meters |
| `angle` | 2 lines | radians |
| `diameter` | 1 circle | meters |
| `fixed` | 1 point | none |

Entity and constraint kinds outside these tables are left out of the snapshot; the solver state still accounts for them. `solver.status` is `free` (degrees of freedom left), `fully_constrained` or `conflicting`, and `solver.dof` is the remaining degrees of freedom, or `null` if the solver can't tell.

| `op` | `args` | Creates |
| --- | --- | --- |
| `sketch.create` | `plane`: `XY`, `XZ` or `YZ` (through the world origin); no target | the sketch |
| `sketch.add_line` | `start`, `end` [u, v] | 2 points and a line |
| `sketch.add_rectangle` | `corner`, `opposite` [u, v] | 4 points, 4 lines sharing them, 2 horizontal and 2 vertical constraints |
| `sketch.add_circle` | `center` [u, v], `radius` | a point and a circle |
| `sketch.constrain` | `kind`, `entities`, `value` for distance, angle and diameter | the constraint |
| `sketch.set_dimension` | `constraint` ID, new `value` | nothing |

Every sketch op except `sketch.create` targets the sketch, with its generation. The receipt lists the new IDs in `created` and the solver state in `solver`. A constraint or dimension the solver can't satisfy is refused: the result is `rejected` with `solver_conflict` and `solver.status` `conflicting`, and the sketch keeps its last valid geometry and constraints. A sketch is reported as `conflicting` in the scene only if it got that way outside our commands, for example by an edit made directly in host Blender.

## Blender screen

The capture helper serves the newest frame of the selected Blender window. Only the newest frame is kept. This is HTTP, not the host connection, so there is no envelope.

- **Transport:** HTTP on `127.0.0.1:8766`.
- `GET /frame` returns `200` with `Content-Type: image/jpeg` and the newest frame. Response headers:
  - `ETag`: the frame number.
  - `X-Captured-At`: capture time in Unix milliseconds.
  - `X-Window`: window title.
  - `X-Size`: `WIDTHxHEIGHT`.

  Send `If-None-Match` with the last `ETag` to get `304` when nothing changed. Returns `503` with the status JSON below when no frame is available.
- `GET /status` returns the status JSON ([schema](schemas/capture.status.schema.json), [example](examples/capture.status.json)). Every field is always present:

  | Field | Meaning |
  | --- | --- |
  | `state` | `capturing`, `no_window`, `minimized` or `error`. |
  | `window` | Title of the selected window, or `null` if none is selected. |
  | `frame` | Number of the newest frame kept (its `ETag`), or `null` before the first frame. |
  | `width`, `height` | Size of that frame in pixels, or `null`. |
  | `fps` | Measured capture rate; `0` when not capturing. |
  | `message` | Why the state isn't `capturing`; empty while capturing. |

Unity polls `/frame` at a modest rate. Start at 10 per second and measure.

## Fakes

**Test data only.** The fakes stand in for Blender or for a client while the real one isn't ready. Nothing seen through them counts as acceptance evidence: a mock response is not native acceptance ([PHASE_PLAN.md](../PHASE_PLAN.md)). They use only the standard library and run on Python 3.9 or newer, so the `python3` that comes with macOS will do.

**Fake host** ([`fakes/fake_host.py`](fakes/fake_host.py)), for building the Unity app without Blender:

```sh
python3 contracts/fakes/fake_host.py            # 127.0.0.1:8765; Ctrl-C stops it
```

It serves the scene from the examples, with the same IDs, as `fake_bracket.blend`: Base plate (100 × 60 × 10 mm box), Shaft (cylinder, 20 mm diameter, 40 mm tall) standing on it as its child, a Camera without a mesh, and the 100 × 60 mm sketch. The meshes are real and render. It follows [Connecting](#connecting), answers `ping`, and applies `object.add`, `object.move`, `object.rotate`, `object.scale`, `object.delete`, `history.undo`, `history.redo` and `document.save` as [Commands](#commands) describes: scene.update to everyone, then result, then activity, with request-ID deduplication and `receipt.query` as [Reconnecting](#reconnecting) describes (stop and start it again to simulate a host restart: a new `host_epoch`, no receipts). Sketch ops get `rejected` with `failed`. It grants and checks leases with the host's rules and messages ([Leases and presence](#leases-and-presence)); its linked data is an object's descendants and the objects sharing its mesh, so leasing Base plate also reserves Shaft. A sketch can be leased by its ID. Each run starts at revision 0 with a new `open_epoch`.

| Flag | What it does | Tests the app's |
| --- | --- | --- |
| `--animate` | Turns Shaft about Z at 20°/s, one scene.update every 0.25 s. | Live updates |
| `--drop-after S` | Closes each connection S seconds after it opens. The fresh snapshot keeps the changes made so far. | Disconnected, reconnect |
| `--stall-after S` | S seconds after each connection opens, sends it nothing: no pong, no updates. The socket stays open. Add `--stall-for S2` to answer again after S2 seconds. | Not responding |
| `--wrong-document` | Refuses every `hello` with `wrong_document`, then closes. | Wrong document error |
| `--port N`, `--idle-timeout S`, `-v` | Another port; the heartbeat timeout (6 s, `0` turns it off); log every message. | |

**Fake client** ([`fakes/fake_client.py`](fakes/fake_client.py)), for testing a host (this fake or the Host-role add-on) and for debugging. It does the handshake, pings every 2 s, and prints the snapshot and every update, activity, session and result message. Type commands while it runs, or give them as arguments:

```sh
python3 contracts/fakes/fake_client.py                                   # watch
python3 contracts/fakes/fake_client.py "move Shaft 10mm 0 0" "undo" --exit
```

Shortcuts include `move OBJ DX DY DZ`, `rotate OBJ Z 90deg`, `scale OBJ 1 1 1.5`, `add cube X Y Z DX DY DZ`, `delete OBJ`, `undo`, `redo`, `save`, `lease OBJ...` (shared), `lease all` (exclusive), `release [LEASE]` and `again` (resend the last command with the same ID). It prints "… started editing …" when someone else's lease appears. For [Reconnecting](#reconnecting): `lose COMMAND` sends the command and drops the connection before its `result`, reconnects and asks for it with `receipt.query`; `query [ID ...]` asks about the last command or the given IDs. JSON gives any command or message. Bare numbers are meters and radians, as on the wire; `--help` lists everything. `--reconnect` reconnects every 2 s, `--role blender-client` acts like the Client role, and `--check` validates every message against [`schemas/`](schemas/) (needs `pip install jsonschema`). It speaks plain TCP only: the [LAN port](#lan-port)'s TLS and token aren't in it yet, so it reaches the host's port 8765 or a fake host.

**Check:** `pytest tests/backend/test_fakes.py` runs the two fakes against each other through a recording proxy and validates every message they send against the schemas.

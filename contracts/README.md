# Contracts

The wire formats between our processes (see "Architecture" in [PHASE_PLAN.md](../PHASE_PLAN.md)). Owner: Waaberi. Any change updates the sender, the receiver and this file in the same PR.

- **Schemas:** [`schemas/<type>.schema.json`](schemas/), JSON Schema draft 2020-12. They `$ref` the shared [`envelope.schema.json`](schemas/envelope.schema.json) (and each other) by file name.
- **Examples:** [`examples/<type>.json`](examples/), plus `<type>.<variant>.json` where one example isn't enough (for example one per command `op`). Fake servers and clients can replay them; they tell one story with the same IDs.
- **Check:** `pytest tests/backend/test_contracts.py` validates every example and a list of broken messages.

## Host connection

Used by the Unity app and by Client-role add-ons to talk to the Host-role add-on.

- **Transport:** TCP. The Unity app connects to `127.0.0.1:8765`. Client-role add-ons connect to the host's LAN address on port `8767` over TLS, using the session token as a pre-shared key.
- **Framing:** one UTF-8 JSON object per line, ending in `\n`. A line longer than 16 MiB closes the connection. `NaN` and `Infinity` aren't JSON; receivers reject them.
- **Coordinates and units:** Blender's own: right-handed, Z up, meters, radians. Unity converts in one place. Details under [Identity, revisions and units](#identity-revisions-and-units).
- **Implementation:** [`blender_addon/spatial_modeling/protocol.py`](../blender_addon/spatial_modeling/protocol.py).

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
| `hello` | client → host | `role` (`vr` or `blender-client`), `name` of the person, `app` name and version; optional `document` it expects | P1 |
| `welcome` | host → client, answers `hello` | `session_id`, `host_epoch`, this connection's `actor_id`, `can_edit`, host `app`, `document` (ID, open epoch, file name, revision, dirty, units) | P1 |
| `error` | either way | `code`, `message`, optional `details` | P0 |
| `ping` | either way | `{}`. Also the heartbeat | P0 |
| `pong` | either way, answers `ping` | `{}` | P0 |
| `scene.snapshot` | host → client | `document`, every object and sketch | P2 |
| `scene.update` | host → every client | `document`, changed objects and sketches, `removed` IDs | P2 |
| `command` | client → host | request fields, `base_revision`, `source`, `op`, `target`, `args`, optional `lease` | P3A |
| `result` | host → sender, answers `command` | the command's receipt: `outcome`, `revision`, `error` if rejected | P3A |
| `activity` | host → every other client | the receipt of a command someone applied | P3B, P5 |
| `receipt.query` | client → host | `request_ids` (1 to 100) | P5 |
| `receipts` | host → client, answers `receipt.query` | `receipts`, and `missing` IDs the host has no record of | P5 |
| `lease.acquire` | client → host | request fields, `mode` (`exclusive` or `shared`), `targets` | P3B |
| `lease.granted` | host → client, answers `lease.acquire` | the `lease` | P3B |
| `lease.release` | client → host | `lease_id` | P3B |
| `session.update` | host → every client | every participant and every lease | P3B, P5 |

There is no voice message type and no frame message type; see [Voice](#voice) and [Blender screen](#blender-screen).

## Connecting

1. The client connects and sends `hello`. Until it has been welcomed, the host answers only `hello` and `ping`; anything else gets `error` `permission_denied`.
2. The host replies `welcome`, then sends `scene.snapshot`, then `session.update`. The client is connected once it has the snapshot. It sends no `command` or `lease.acquire` before that.
3. If the host refuses the `hello`, it replies `error` (with `re`) and closes the connection:
   - `unsupported_version`: the envelope's `v` differs, or a Client-role add-on's `app.version` differs from the host's (P5-M1-3).
   - `wrong_document`: the `hello` named a `document` and the host has another one (or another opening of it) open. `details.document` has the host's `id`, `open_epoch` and `name`.
   - `permission_denied`: the host doesn't admit this client.
4. Loading another `.blend` (or reverting), disabling the add-on and switching the role all close every connection. Clients reconnect and get the new document in `welcome`. A connection never spans two documents.
5. **Heartbeat:** clients send `ping` every 2 s. A client that hears nothing from the host for 6 s shows "Blender is not responding" and disables edits; a closed socket means disconnected. The host treats a client it hasn't heard from for 6 s as gone: it closes the connection, which also ends its leases.

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

The first six codes are the transport-level codes that [`server.py`](../blender_addon/spatial_modeling/server.py) sends:

| Code | Meaning | Then |
| --- | --- | --- |
| `invalid_message` | Not JSON, a bad envelope, or a payload that doesn't match its schema (unknown `op`, missing field, number out of bounds). | Connection stays open. |
| `unsupported_version` | Wrong `v`, or a Client-role add-on version that differs from the host's. | Host closes. |
| `message_too_large` | A line over 16 MiB. | Host closes. |
| `unknown_type` | Nothing handles this `type`. | |
| `busy` | Too many messages are waiting for Blender. The message was dropped and never applied. | The same message can be sent again later. |
| `internal_error` | The handler failed. | For a command, the outcome is unknown (see [Outcomes](#outcomes)). |
| `permission_denied` | Not welcomed yet, read-only (`can_edit` is false), `actor_id` isn't this connection's, or the host has stopped writes while it reconciles. | |
| `wrong_session` | `session_id` or `host_epoch` is not the current one: the request was built before the host restarted. | Reconnect. |
| `wrong_document` | `document_id` or `open_epoch` is not the open document, or `hello` expected another document. `details.document`: the open one. | |
| `not_found` | The target, lease or sketch entity doesn't exist (for example it was deleted). | |
| `stale_revision` | The target changed since the client saw it, or Undo/Redo was sent from an old revision. `details.generation` or `details.revision`: the current value. | Look again, then make a new request. |
| `lease_conflict` | Another participant's lease covers the target or the document. `details.lease`: that lease, with the owner's name. | |
| `duplicate_request` | A request ID was reused with a different payload. | |
| `solver_conflict` | The sketch solver can't satisfy the constraints. The sketch is unchanged. | |
| `failed` | Blender refused (nothing to undo, a file that was never saved). Nothing changed. | |

## Identity, revisions and units

| Name | What it is |
| --- | --- |
| Object ID | UUID hex in the custom property `spatial_modeling_id` on each Blender object. It survives renames, Undo and save/reopen. The host assigns missing IDs and gives a duplicated object a new one. Sketches have the same kind of ID. |
| Sketch entity and constraint IDs | Strings of 1 to 64 letters, digits, `_` or `-`, unique within their sketch and stable across Undo/Redo and save/reopen. The CAD adapter picks them. |
| `document.id` | UUID hex the host stores in the `.blend` file the first time it opens it; it survives save/reopen. |
| `open_epoch` | New UUID hex every time the host opens or reloads the file, and whenever its revision counter restarts. |
| `revision` | Starts at 0 for each open epoch and goes up with every accepted change: commands and direct edits in host Blender alike. It can jump by more than one when the host batches changes. Revisions are only comparable within one open epoch. Leases, presence, selection and Save don't change it. |
| `generation` | On each object and sketch: the revision at which it last changed. |
| `session_id` | UUID hex of the hosting session, kept with the session token in the host's add-on preferences. It stays the same when the host restarts. |
| `host_epoch` | New UUID hex every time the host's server starts. |
| `actor_id` | New for every connection, given in `welcome`. The host's own Blender is the participant with role `host`. |

**Units.** Numbers on the wire are always meters and radians. The host converts Blender units to meters by multiplying by the scene's Unit Scale (`scale_length`), so a 100 mm part is `0.1` whatever the scene settings. `document.units` copies the scene's settings for display only: Unity shows millimeters when `length_unit` is `MILLIMETERS`, and the Client role copies the settings into its session file. Field names carry no unit suffix; the contract fixes the units, and the schema bounds catch the worst slips (an angle of 90 is rejected).

**Transforms** are in world space: `location` in meters, `rotation` as a quaternion in Blender's order `[w, x, y, z]` (Unity's `Quaternion` is `x, y, z, w`), and `scale` factors. The host decomposes the object's world matrix; shear from a non-uniformly scaled parent is lost. `parent` gives the hierarchy.

## Scene

`scene.snapshot` describes everything and replaces what the client had. The host sends it after `welcome`, and again whenever it can't describe a change as an update (for example after the unit settings change).

`scene.update` carries changes in order, after Blender has committed them. `objects` and `sketches` hold complete records that replace those with the same `id`. An object in an update may leave out `mesh` when only its transform, name, color or visibility changed. `removed` lists deleted object and sketch IDs. `document` carries the new revision and the dirty flag, so an update with empty lists means only the dirty flag changed (after Save).

| Object field | Meaning |
| --- | --- |
| `id`, `name` | Stable ID and Blender name. |
| `type` | Blender object type: `MESH`, `CURVE`, `FONT`, `EMPTY`, `CAMERA`, `LIGHT` and so on. |
| `parent` | Parent object ID, or `null`. |
| `generation` | Revision of its last change. |
| `visible` | Shown in the viewport. |
| `transform` | World `location`, `rotation`, `scale`. |
| `color` | Linear RGBA (0 to 1) of the first material's Base Color, or `null` without a material. |
| `mesh` | The evaluated mesh, or `null` for objects without geometry (cameras, lights, empties). |

**Mesh encoding.** The mesh is evaluated (after modifiers; curves and text converted to a mesh) and triangulated, in the object's local space in meters. `positions` and `normals` hold 3 numbers per vertex, and `indices` 3 vertex indices per triangle, counter-clockwise seen from the front (Blender's winding; Unity flips it when it converts handedness). Vertices are split where normals differ, so Unity can use the arrays as they are; the host may simply send three vertices per triangle. Values are rounded to 1 µm. Plain JSON arrays are simple but large. A binary or delta encoding is a later optimization, and `v` lets us change the format. Until then a snapshot has to fit in one 16 MiB line, roughly 90,000 triangles in total.

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
| `lease` | Optional `lease_id` of a lease this actor holds that covers the target. See [Leases and presence](#leases-and-presence). |

| `op` | Target | `args` | Notes |
| --- | --- | --- | --- |
| `object.add` | none | `primitive` (`cube`, `sphere`, `cylinder`), `location` [x, y, z], `dimensions` [x, y, z] | `dimensions` is the bounding box; a cylinder's diameter is X and Y and its depth is Z. The receipt's `created` has the new ID. |
| `object.select` | none | `ids` | Replaces the host Blender's selection so the host screen shows it; the first ID becomes active and `[]` deselects. Selection is inspection: no lease, no revision change, no Undo step. |
| `object.move` | object | `by` [dx, dy, dz] or `to` [x, y, z] | World space. |
| `object.rotate` | object | `by` {`axis`: `X`, `Y` or `Z`, `angle`} or `to` [w, x, y, z] | `by` turns about a world axis through the object's origin. |
| `object.scale` | object | `by` [sx, sy, sz] or `to` [sx, sy, sz] | Along the object's own axes; `by` multiplies. |
| `object.delete` | object | `{}` | |
| `history.undo`, `history.redo` | none | `{}` | Blender's shared history. `base_revision` must equal the current revision, so nobody undoes a change they haven't seen. Refused with `lease_conflict` while another participant holds a lease. |
| `document.save` | none | `{}` | Saves to the current file; `failed` if it was never saved. There is no Save As over the wire, so no client sends file paths. |
| `sketch.*` | sketch | see [Sketches](#sketches) | |

**Bounds** (enforced by the schemas): coordinates within ±1000 m, lengths from 1 µm to 1000 m, scale factors from 0.001 to 1000, `rotate.by` angles within ±2π, sketch angles above 0 and up to π.

**How the host checks a command,** in this order:

1. Schema: otherwise `error` `invalid_message`.
2. Request ID: a repeat with an identical payload gets the stored result again and is never re-applied (if it is still running, the host answers once when it finishes). A repeat with a different payload is rejected with `duplicate_request`.
3. Admission: welcomed, `can_edit`, `actor_id` is this connection's. Otherwise `permission_denied`.
4. `session_id` and `host_epoch`, otherwise `wrong_session`; `document_id` and `open_epoch`, otherwise `wrong_document`.
5. The target exists (`not_found`) and its generation is current; for Undo/Redo, `base_revision` is current (`stale_revision`).
6. Leases (`lease_conflict`), described below.
7. Apply on Blender's main thread, push one Undo step, read the result back. Then send `scene.update` to every client, `result` to the sender and `activity` to the others, in that order. When a `result` arrives, the sender's scene already includes the change.

### Outcomes

| `outcome` | Meaning |
| --- | --- |
| `applied` | Blender committed the change; `revision` is the new revision. |
| `rejected` | Nothing changed; `error` says why. |
| `unknown` | The host can't tell whether Blender changed, for example after a failure halfway through. The host refuses writes (`permission_denied`) until it has re-read the scene and sent a fresh snapshot. |
| `pending` | Only in `receipts`: the host has the command but hasn't finished it. |

A client treats an `internal_error` reply to a command, or a connection lost before the `result`, as unknown too. While any of its outcomes is unknown, the client stops sending edits. It reconnects if needed, asks with `receipt.query`, and waits for the fresh snapshot. It never resends a command whose outcome is unknown. `missing` in `receipts` means the host has no record of the request; if the host restarted in between, that doesn't prove the command never ran, so trust the snapshot.

**Receipt fields** (the payload of `result` and `activity`, and the items of `receipts`): `request_id`, `op`, `target` (if any), `actor` (`actor_id`, `name`, `role`), `source`, `outcome`, `revision`, `created` (new IDs, if any), `solver` (sketch ops), `summary` (one line for activity lists, for example "Moved Shaft 10 mm along X"), `error` (if rejected or unknown) and `at` (Unix ms).

## Leases and presence

The host checks permission before every native change (P3B).

- **Exclusive** (`mode: "exclusive"`, `targets: []`) reserves the whole document. It is granted only while no other participant holds a lease. While it is held, other participants' commands get `lease_conflict` and the host blocks its own desktop edits. For Exclusive editing mode, acquire it before the first native write (Apply, or the start of a drag) and release it after the commit or cancel.
- **Shared** (`mode: "shared"`) reserves the listed objects and sketches. The host may add linked data, such as other objects that share the mesh; `lease.granted` lists what was actually reserved. Two shared leases conflict when their targets overlap. A sketch edit leases the whole sketch by its ID.
- A command without `lease` gets a lease for just that command: the host checks that no other participant's lease covers the target and holds nothing afterwards. That suits one-shot menu and voice commands. Drags, numeric edits and sketch sessions acquire a lease so that others see the ownership for the whole edit.
- A participant's own leases never conflict with each other.
- **Expiry:** a lease ends when it is released, when its owner's connection closes, or when the host hasn't heard from the owner for 6 s (see Heartbeat). Expiry never interrupts a commit in progress, because commits run one at a time on Blender's main thread.

`session.update` always carries the complete lists, which replace the previous ones: `participants` (including the host's own Blender, role `host`) and `leases`. Show a pink outline and the owner's name on the targets of other participants' leases, and "Two people are editing" while leases from two participants exist.

**SpacetimeDB.** A participant is an `actor` row and a lease a `lease` row, so if the spike passes, the host can call reducers and relay those tables as `session.update`, and Unity may subscribe to the tables directly instead. `lease.acquire` and `lease.release` still go through the host, which checks leases before every native write. If the spike fails, the host keeps the same rows in memory and nothing on the wire changes.

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

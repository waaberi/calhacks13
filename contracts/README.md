# Contracts

The wire formats between our processes (see "Architecture" in [PHASE_PLAN.md](../PHASE_PLAN.md)). Owner: Waaberi. Any change updates the sender, the receiver and this file in the same PR.

## Host connection

Used by the Unity app and by Client-role add-ons to talk to the Host-role add-on.

- **Transport:** TCP. The Unity app connects to `127.0.0.1:8765`. Client-role add-ons connect to the host's LAN address on port `8767` over TLS, using the session token as a pre-shared key.
- **Framing:** one UTF-8 JSON object per line, ending in `\n`. A line longer than 16 MiB closes the connection.
- **Coordinates and units:** Blender's own: right-handed, Z up, meters, radians. Unity converts in one place.
- **Implementation:** [`blender_addon/spatial_modeling/protocol.py`](../blender_addon/spatial_modeling/protocol.py).

Every message has this envelope:

| Field | Type | Meaning |
| --- | --- | --- |
| `v` | integer | Contract version, currently `1`. On a mismatch, the receiver replies `error` and closes. |
| `type` | string | Message type, for example `ping`. |
| `id` | string | Unique ID of this message (UUID hex). Requests are deduplicated by it. |
| `re` | string, optional | The `id` of the request this message answers. |
| `payload` | object | Type-specific content. |

| Type | Direction | Payload |
| --- | --- | --- |
| `ping` / `pong` | either way | `{}`; the `pong` sets `re` |
| `error` | either way | `{"code": "...", "message": "..."}` |

The scene, command, result, lock, voice and sketch types are added here with their examples in P0-W-1. Put examples in `contracts/examples/<type>.json` and schemas in `contracts/schemas/<type>.schema.json`.

## Blender screen

The capture helper serves the newest frame of the selected Blender window. Only the newest frame is kept.

- **Transport:** HTTP on `127.0.0.1:8766`.
- `GET /frame` returns `200` with `Content-Type: image/jpeg` and the newest frame. Response headers:
  - `ETag`: the frame number.
  - `X-Captured-At`: capture time in Unix milliseconds.
  - `X-Window`: window title.
  - `X-Size`: `WIDTHxHEIGHT`.

  Send `If-None-Match` with the last `ETag` to get `304` when nothing changed. Returns `503` with the status JSON below when no frame is available.
- `GET /status` returns `{"state": "capturing" | "no_window" | "minimized" | "error", "window": "...", "frame": 42, "width": 1920, "height": 1080, "fps": 12.0, "message": "..."}`.

Unity polls `/frame` at a modest rate. Start at 10 per second and measure.

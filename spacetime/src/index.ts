// Shared session state for Spatial Modeling: participants, object leases and the receipt log.
//
// The host add-on is the only writer: it calls these reducers over HTTP, from a background
// thread, after it has checked a request against contracts/README.md. `acquire` decides who
// may edit what: the host grants a client's lease.acquire only if this reducer accepts it. The
// Unity app only subscribes.
//
// Rooms, pipes and frames (the end of this file) carry the host connection itself between two
// bridges (bridge/) when the host and a remote Blender are on different networks (#166). They
// carry TLS-PSK bytes this module can't read; geometry and commands are never stored as such.
//
// Rows mirror the contract: a `participant` row is an `actor`, a `lease` row is a `lease`
// (its owner's name and role come from `participant`), and a `receipt` row stores one receipt.
// Times are Unix milliseconds, like every timestamp on the wire.
//
// Reducers reject with SenderError("<contract error code>: <detail>"), so the host can map a
// rejection straight to the error it sends its client.

import { schema, table, t, SenderError, type InferSchema, type ReducerCtx } from 'spacetimedb/server';

const participant = table(
  { name: 'participant', public: true },
  {
    actor_id: t.string().primaryKey(),
    name: t.string(),
    role: t.string(), // "vr", "blender-client" or "host"
    joined_at: t.u64(),
    last_seen: t.u64(),
  }
);

const lease = table(
  { name: 'lease', public: true },
  {
    lease_id: t.string().primaryKey(),
    mode: t.string(), // "exclusive" (targets empty: the whole document) or "shared"
    owner_id: t.string().index('btree'),
    targets: t.array(t.string()),
    acquired_at: t.u64(),
    // Not live from this time on. The host renews the leases of owners it hears from, so a lease
    // outlives its owner (or a crashed host) by at most one TTL.
    expires_at: t.u64(),
  }
);

const receipt = table(
  { name: 'receipt', public: true },
  {
    request_id: t.string().primaryKey(),
    at: t.u64().index('btree'),
    actor_id: t.string(),
    op: t.string(),
    outcome: t.string(), // "pending", "applied", "rejected" or "unknown"
    digest: t.string(), // the host's fingerprint of the request payload, for duplicate checks
    body: t.string(), // the complete receipt as JSON, exactly as the host sends it
  }
);

// Object names for the IDs in lease targets, so subscribers can show "Talia is editing Cube".
// The host writes the names of what a lease covers just before it asks `acquire` for the lease.
const label = table(
  { name: 'label', public: true },
  {
    object_id: t.string().primaryKey(),
    name: t.string(),
  }
);

// Lease requests that `acquire` refused, the newest MAX_REFUSALS. A rejected reducer changes
// nothing, so the host notes each refusal right after `acquire` turned it down.
const refusal = table(
  { name: 'refusal', public: true },
  {
    refusal_id: t.u64().primaryKey().autoInc(),
    at: t.u64(),
    actor_id: t.string(), // who asked
    blocking_lease_id: t.string(), // the live lease that stopped it
    targets: t.array(t.string()), // what was asked for; empty for the whole document
  }
);

// Who may do what. Private: clients can't see or subscribe to it.
// Slot OWNER is the CLI identity that published the database; slot HOST is the host add-on.
const authority = table(
  { name: 'authority' },
  {
    slot: t.u8().primaryKey(),
    identity: t.identity(),
  }
);

// The relay (#166). All three are private: a bridge sees only its own pipes and frames, through
// the my_pipe and my_frame views.
//
// A room is one host bridge. Its id and proof both come from the session token, so only someone
// with the token can open the room or a pipe into it; the module never sees the token itself.
const room = table(
  { name: 'room' },
  {
    room_id: t.string().primaryKey(),
    proof: t.string(),
    host: t.identity(),
    host_connection: t.connectionId(),
    opened_at: t.u64(),
  }
);

// A pipe is one TCP connection from a remote Blender to the host's LAN port. The two sides
// number their frames 1, 2, 3... *_sent is the last frame each side sent and *_acked the last
// frame each side wrote to its Blender, so a sender knows how much is still in flight.
const pipe = table(
  { name: 'pipe' },
  {
    pipe_id: t.string().primaryKey(),
    room_id: t.string().index('btree'),
    host: t.identity().index('btree'),
    client: t.identity().index('btree'),
    client_connection: t.connectionId(),
    opened_at: t.u64(),
    host_sent: t.u64(),
    client_sent: t.u64(),
    host_acked: t.u64(), // the host's last frame from the client
    client_acked: t.u64(), // the client's last frame from the host
  }
);

// Bytes on their way. The receiving bridge deletes them with `ack` once it has written them.
const frame = table(
  { name: 'frame' },
  {
    frame_id: t.u64().primaryKey().autoInc(),
    pipe_id: t.string().index('btree'),
    to: t.identity().index('btree'),
    seq: t.u64(),
    data: t.byteArray(),
  }
);

const spacetimedb = schema({ participant, lease, receipt, label, refusal, authority, room, pipe, frame });
export default spacetimedb;

type Ctx = ReducerCtx<InferSchema<typeof spacetimedb>>;

const OWNER = 0;
const HOST = 1;
const UUID = /^[0-9a-f]{32}$/;
const ROLES = new Set(['vr', 'blender-client', 'host']);
const OUTCOMES = new Set(['pending', 'applied', 'rejected', 'unknown']);
const MAX_TTL_MS = 3_600_000n;
const MAX_TARGETS = 1000;
const MAX_REFUSALS = 50n;

function nowMs(ctx: Ctx): bigint {
  return ctx.timestamp.microsSinceUnixEpoch / 1000n;
}

function reject(code: string, detail: string): never {
  throw new SenderError(`${code}: ${detail}`);
}

function is(ctx: Ctx, slot: number): boolean {
  const row = ctx.db.authority.slot.find(slot);
  return row !== null && row.identity.equals(ctx.sender);
}

function requireHost(ctx: Ctx): void {
  if (!is(ctx, HOST)) reject('permission_denied', 'only the host add-on writes session state');
}

function requireUuid(field: string, value: string): void {
  if (!UUID.test(value)) reject('invalid_message', `${field} must be 32 lowercase hex digits`);
}

function requireTtl(ttlMs: bigint): void {
  if (ttlMs <= 0n || ttlMs > MAX_TTL_MS) reject('invalid_message', `ttl_ms must be 1 to ${MAX_TTL_MS}`);
}

type LeaseRow = { mode: string; owner_id: string; targets: string[] };

function overlaps(a: LeaseRow, b: LeaseRow): boolean {
  if (a.mode === 'exclusive' || b.mode === 'exclusive') return true;
  const theirs = new Set(a.targets);
  return b.targets.some(id => theirs.has(id));
}

function dropLeasesOf(ctx: Ctx, actorId: string): void {
  for (const row of [...ctx.db.lease.owner_id.filter(actorId)]) {
    ctx.db.lease.lease_id.delete(row.lease_id);
  }
}

export const init = spacetimedb.init(ctx => {
  ctx.db.authority.insert({ slot: OWNER, identity: ctx.sender });
});

// The first caller becomes the host; afterwards only that identity can write. The host keeps its
// token on disk, so it stays the host across restarts. If the token is lost, the publisher frees
// the slot with `spacetime call <database> reset_host`.
export const claim_host = spacetimedb.reducer(ctx => {
  const row = ctx.db.authority.slot.find(HOST);
  if (row === null) {
    ctx.db.authority.insert({ slot: HOST, identity: ctx.sender });
  } else if (!row.identity.equals(ctx.sender)) {
    reject('permission_denied', 'another identity is already the host');
  }
});

export const reset_host = spacetimedb.reducer(ctx => {
  if (!is(ctx, OWNER)) reject('permission_denied', 'only the publisher can reset the host');
  ctx.db.authority.slot.delete(HOST);
});

export const join = spacetimedb.reducer(
  { actor_id: t.string(), name: t.string(), role: t.string() },
  (ctx, { actor_id, name, role }) => {
    requireHost(ctx);
    requireUuid('actor_id', actor_id);
    if (name.length < 1 || name.length > 256) reject('invalid_message', 'name must be 1 to 256 characters');
    if (!ROLES.has(role)) reject('invalid_message', `unknown role ${role}`);
    const now = nowMs(ctx);
    const old = ctx.db.participant.actor_id.find(actor_id);
    if (old === null) {
      ctx.db.participant.insert({ actor_id, name, role, joined_at: now, last_seen: now });
    } else {
      ctx.db.participant.actor_id.update({ ...old, name, role, last_seen: now });
    }
  }
);

// The participant's connection closed or went silent: it and all of its leases are gone.
export const leave = spacetimedb.reducer({ actor_id: t.string() }, (ctx, { actor_id }) => {
  requireHost(ctx);
  dropLeasesOf(ctx, actor_id);
  ctx.db.participant.actor_id.delete(actor_id);
});

// Atomic: either no other owner's live lease overlaps and the lease is inserted, or nothing
// changes and the reducer fails with "lease_conflict: <lease_id of the blocking lease>".
export const acquire = spacetimedb.reducer(
  {
    lease_id: t.string(),
    owner_id: t.string(),
    mode: t.string(),
    targets: t.array(t.string()),
    ttl_ms: t.u64(),
  },
  (ctx, { lease_id, owner_id, mode, targets, ttl_ms }) => {
    requireHost(ctx);
    requireUuid('lease_id', lease_id);
    requireTtl(ttl_ms);
    if (mode === 'exclusive') {
      if (targets.length !== 0) reject('invalid_message', 'an exclusive lease has no targets');
    } else if (mode === 'shared') {
      if (targets.length < 1 || targets.length > MAX_TARGETS) {
        reject('invalid_message', `a shared lease has 1 to ${MAX_TARGETS} targets`);
      }
      if (new Set(targets).size !== targets.length) reject('invalid_message', 'targets repeat');
      targets.forEach(id => requireUuid('target', id));
    } else {
      reject('invalid_message', `unknown mode ${mode}`);
    }
    if (ctx.db.participant.actor_id.find(owner_id) === null) {
      reject('not_found', `no participant ${owner_id}`);
    }
    if (ctx.db.lease.lease_id.find(lease_id) !== null) {
      reject('duplicate_request', `lease ${lease_id} already exists`);
    }
    const now = nowMs(ctx);
    const wanted = { mode, owner_id, targets };
    for (const other of [...ctx.db.lease.iter()]) {
      if (other.expires_at <= now) {
        ctx.db.lease.lease_id.delete(other.lease_id); // expired: not live, clean it up
      } else if (other.owner_id !== owner_id && overlaps(other, wanted)) {
        reject('lease_conflict', other.lease_id);
      }
    }
    ctx.db.lease.insert({ lease_id, mode, owner_id, targets, acquired_at: now, expires_at: now + ttl_ms });
  }
);

// The host heard from this participant: extend its live leases and record that it is present.
export const renew = spacetimedb.reducer(
  { actor_id: t.string(), ttl_ms: t.u64() },
  (ctx, { actor_id, ttl_ms }) => {
    requireHost(ctx);
    requireTtl(ttl_ms);
    const who = ctx.db.participant.actor_id.find(actor_id);
    if (who === null) reject('not_found', `no participant ${actor_id}`);
    const now = nowMs(ctx);
    ctx.db.participant.actor_id.update({ ...who, last_seen: now });
    for (const row of [...ctx.db.lease.owner_id.filter(actor_id)]) {
      if (row.expires_at > now) ctx.db.lease.lease_id.update({ ...row, expires_at: now + ttl_ms });
    }
  }
);

export const release = spacetimedb.reducer(
  { lease_id: t.string(), owner_id: t.string() },
  (ctx, { lease_id, owner_id }) => {
    requireHost(ctx);
    const row = ctx.db.lease.lease_id.find(lease_id);
    if (row === null || row.expires_at <= nowMs(ctx)) reject('not_found', `no lease ${lease_id}`);
    if (row.owner_id !== owner_id) reject('permission_denied', `lease ${lease_id} belongs to someone else`);
    ctx.db.lease.lease_id.delete(lease_id);
  }
);

// Delete every lease that is no longer live, so subscribers stop showing it.
export const expire = spacetimedb.reducer(ctx => {
  requireHost(ctx);
  const now = nowMs(ctx);
  for (const row of [...ctx.db.lease.iter()]) {
    if (row.expires_at <= now) ctx.db.lease.lease_id.delete(row.lease_id);
  }
});

// Append a receipt, or complete a pending one. A final receipt never changes.
export const record_receipt = spacetimedb.reducer(
  {
    request_id: t.string(),
    at: t.u64(),
    actor_id: t.string(),
    op: t.string(),
    outcome: t.string(),
    digest: t.string(),
    body: t.string(),
  },
  (ctx, args) => {
    requireHost(ctx);
    requireUuid('request_id', args.request_id);
    if (!OUTCOMES.has(args.outcome)) reject('invalid_message', `unknown outcome ${args.outcome}`);
    const old = ctx.db.receipt.request_id.find(args.request_id);
    if (old === null) {
      ctx.db.receipt.insert(args);
    } else if (old.outcome === 'pending') {
      ctx.db.receipt.request_id.update(args);
    } else if (old.body !== args.body || old.digest !== args.digest) {
      reject('duplicate_request', `receipt ${args.request_id} is final`);
    }
  }
);

// Name the objects a lease will cover: ids[i] is called names[i]. Upserts; names never expire.
export const set_labels = spacetimedb.reducer(
  { ids: t.array(t.string()), names: t.array(t.string()) },
  (ctx, { ids, names }) => {
    requireHost(ctx);
    if (ids.length !== names.length || ids.length > MAX_TARGETS) {
      reject('invalid_message', `ids and names must pair up, at most ${MAX_TARGETS}`);
    }
    ids.forEach((object_id, i) => {
      requireUuid('id', object_id);
      const name = names[i].slice(0, 256);
      if (ctx.db.label.object_id.find(object_id) === null) {
        ctx.db.label.insert({ object_id, name });
      } else {
        ctx.db.label.object_id.update({ object_id, name });
      }
    });
  }
);

// `acquire` refused actor_id's request for targets because of blocking_lease_id.
export const note_refusal = spacetimedb.reducer(
  { actor_id: t.string(), blocking_lease_id: t.string(), targets: t.array(t.string()) },
  (ctx, { actor_id, blocking_lease_id, targets }) => {
    requireHost(ctx);
    requireUuid('actor_id', actor_id);
    if (targets.length > MAX_TARGETS) reject('invalid_message', `at most ${MAX_TARGETS} targets`);
    ctx.db.refusal.insert({ refusal_id: 0n, at: nowMs(ctx), actor_id, blocking_lease_id, targets });
    while (ctx.db.refusal.count() > MAX_REFUSALS) {
      let oldest: bigint | null = null;
      for (const row of ctx.db.refusal.iter()) {
        if (oldest === null || row.refusal_id < oldest) oldest = row.refusal_id;
      }
      ctx.db.refusal.refusal_id.delete(oldest!);
    }
  }
);

// The relay (#166) ------------------------------------------------------------------------------

const HEX64 = /^[0-9a-f]{64}$/;
const MAX_FRAME_BYTES = 65_536;
const MAX_IN_FLIGHT = 64n; // frames per direction not yet acked: 4 MiB
const MAX_PIPES_PER_ROOM = 8;

function closePipe(ctx: Ctx, pipeId: string): void {
  for (const row of [...ctx.db.frame.pipe_id.filter(pipeId)]) ctx.db.frame.frame_id.delete(row.frame_id);
  ctx.db.pipe.pipe_id.delete(pipeId);
}

function closeRoom(ctx: Ctx, roomId: string): void {
  for (const row of [...ctx.db.pipe.room_id.filter(roomId)]) closePipe(ctx, row.pipe_id);
  ctx.db.room.room_id.delete(roomId);
}

function myPipe(ctx: Ctx, pipeId: string) {
  const row = ctx.db.pipe.pipe_id.find(pipeId);
  if (row === null) reject('not_found', `no pipe ${pipeId}`);
  const asHost = row.host.equals(ctx.sender);
  if (!asHost && !row.client.equals(ctx.sender)) reject('permission_denied', 'not your pipe');
  return { row, asHost };
}

// A host bridge opens its room. A second bridge with the same token takes the room over and
// closes the first one's pipes, so a restarted bridge never waits for the old connection to time out.
export const open_room = spacetimedb.reducer(
  { room_id: t.string(), proof: t.string() },
  (ctx, { room_id, proof }) => {
    requireUuid('room_id', room_id);
    if (!HEX64.test(proof)) reject('invalid_message', 'proof must be 64 lowercase hex digits');
    if (ctx.connectionId === null) reject('invalid_message', 'open a room over a live connection');
    const old = ctx.db.room.room_id.find(room_id);
    if (old !== null) {
      if (old.proof !== proof) reject('permission_denied', 'wrong proof for this room');
      closeRoom(ctx, room_id);
    }
    ctx.db.room.insert({ room_id, proof, host: ctx.sender, host_connection: ctx.connectionId, opened_at: nowMs(ctx) });
  }
);

// A remote bridge opens a pipe into a room for one TCP connection; the host bridge sees it in
// my_pipe and connects to its Blender.
export const open_pipe = spacetimedb.reducer(
  { pipe_id: t.string(), room_id: t.string(), proof: t.string() },
  (ctx, { pipe_id, room_id, proof }) => {
    requireUuid('pipe_id', pipe_id);
    if (ctx.connectionId === null) reject('invalid_message', 'open a pipe over a live connection');
    const r = ctx.db.room.room_id.find(room_id);
    if (r === null || r.proof !== proof) reject('not_found', 'no host is open for this session token');
    if (r.host.equals(ctx.sender)) reject('invalid_message', 'the host bridge cannot join its own room');
    if (ctx.db.pipe.pipe_id.find(pipe_id) !== null) reject('duplicate_request', `pipe ${pipe_id} exists`);
    if ([...ctx.db.pipe.room_id.filter(room_id)].length >= MAX_PIPES_PER_ROOM) {
      reject('busy', `at most ${MAX_PIPES_PER_ROOM} connections per room`);
    }
    ctx.db.pipe.insert({
      pipe_id, room_id, host: r.host, client: ctx.sender, client_connection: ctx.connectionId,
      opened_at: nowMs(ctx), host_sent: 0n, client_sent: 0n, host_acked: 0n, client_acked: 0n,
    });
  }
);

// Frames must arrive numbered 1, 2, 3...; a gap or a full window closes nothing but fails the
// call, and the bridge then closes the pipe (Blender reconnects).
export const send = spacetimedb.reducer(
  { pipe_id: t.string(), seq: t.u64(), data: t.byteArray() },
  (ctx, { pipe_id, seq, data }) => {
    const { row, asHost } = myPipe(ctx, pipe_id);
    if (data.length < 1 || data.length > MAX_FRAME_BYTES) reject('invalid_message', `1 to ${MAX_FRAME_BYTES} bytes per frame`);
    const last = asHost ? row.host_sent : row.client_sent;
    const acked = asHost ? row.client_acked : row.host_acked;
    if (seq !== last + 1n) reject('invalid_message', `expected frame ${last + 1n}, got ${seq}`);
    if (seq - acked > MAX_IN_FLIGHT) reject('busy', 'too many frames in flight');
    ctx.db.frame.insert({ frame_id: 0n, pipe_id, to: asHost ? row.client : row.host, seq, data });
    ctx.db.pipe.pipe_id.update(asHost ? { ...row, host_sent: seq } : { ...row, client_sent: seq });
  }
);

// The caller has written every frame up to `upto` to its Blender: delete them.
export const ack = spacetimedb.reducer({ pipe_id: t.string(), upto: t.u64() }, (ctx, { pipe_id, upto }) => {
  const { row, asHost } = myPipe(ctx, pipe_id);
  const sent = asHost ? row.client_sent : row.host_sent;
  const acked = asHost ? row.host_acked : row.client_acked;
  if (upto > sent) reject('invalid_message', `frame ${upto} was never sent`);
  if (upto <= acked) return;
  for (const f of [...ctx.db.frame.pipe_id.filter(pipe_id)]) {
    if (f.to.equals(ctx.sender) && f.seq <= upto) ctx.db.frame.frame_id.delete(f.frame_id);
  }
  ctx.db.pipe.pipe_id.update(asHost ? { ...row, host_acked: upto } : { ...row, client_acked: upto });
});

export const close_pipe = spacetimedb.reducer({ pipe_id: t.string() }, (ctx, { pipe_id }) => {
  if (ctx.db.pipe.pipe_id.find(pipe_id) === null) return; // the other side closed it first
  myPipe(ctx, pipe_id);
  closePipe(ctx, pipe_id);
});

// A bridge's connection dropped: close its room or its pipes. Matched by connection, not identity,
// because a bridge may share its identity with other connections.
export const on_disconnect = spacetimedb.clientDisconnected(ctx => {
  const gone = ctx.connectionId;
  if (gone === null) return;
  for (const r of [...ctx.db.room.iter()]) if (r.host_connection.isEqual(gone)) closeRoom(ctx, r.room_id);
  for (const p of [...ctx.db.pipe.iter()]) if (p.client_connection.isEqual(gone)) closePipe(ctx, p.pipe_id);
});

export const my_pipe = spacetimedb.view({ name: 'my_pipe', public: true }, t.array(pipe.rowType), ctx => [
  ...ctx.db.pipe.host.filter(ctx.sender),
  ...ctx.db.pipe.client.filter(ctx.sender),
]);

export const my_frame = spacetimedb.view({ name: 'my_frame', public: true }, t.array(frame.rowType), ctx => [
  ...ctx.db.frame.to.filter(ctx.sender),
]);

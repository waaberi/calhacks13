// Shared session state for Spatial Modeling: participants, object leases and the receipt log.
//
// The host add-on is the only writer: it calls these reducers over HTTP, from a background
// thread, after it has checked a request against contracts/README.md. `acquire` decides who
// may edit what: the host grants a client's lease.acquire only if this reducer accepts it. The Unity app only subscribes. Geometry, scene snapshots
// and native commands never come here; they stay on the direct host connection.
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

const spacetimedb = schema({ participant, lease, receipt, label, refusal, authority });
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

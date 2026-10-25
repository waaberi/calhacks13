// The session board: a live view of who is connected and who is editing what, straight from
// SpacetimeDB. It subscribes to the module's participant, lease, label and refusal tables with
// the official TypeScript SDK and pushes every change to the page (index.html) over
// Server-Sent Events. It only reads: the host add-on is the only writer.
//
//   npm run board                       # http://127.0.0.1:3100, server http://127.0.0.1:3000
//   npm run board -- --url http://127.0.0.1:3017 --database spatial-modeling-test --port 3101
//
// Listens on 127.0.0.1 only. Node 22 or later (it needs the global WebSocket).

import { readFileSync } from 'node:fs';
import { createServer, type ServerResponse } from 'node:http';
import { join } from 'node:path';
import { DbConnection } from './module_bindings';

function option(name: string, fallback: string): string {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback;
}

const URL = option('url', 'http://127.0.0.1:3000');
const DATABASE = option('database', 'spatial-modeling');
const PORT = Number(option('port', '3100'));
const PAGE = readFileSync(join(__dirname, '..', 'index.html'));
const MAX_EVENTS = 40;

type Event = { id: number; at: number; kind: string; text: string; pushedMs: number | null };

let conn: DbConnection | null = null;
let connected = false;
let problem = '';
const events: Event[] = [];
const watchers = new Set<ServerResponse>();
const known = new Map<string, string>(); // actor_id -> name, kept after they leave
let nextEvent = 1;

// Whether a row callback is news (a reducer just ran), not a row the subscription started with.
function happened(ctx: { event: { tag: string } }): boolean {
  return ctx.event.tag === 'Reducer' || ctx.event.tag === 'Transaction';
}

function name(actorId: string): string {
  return conn?.db.participant.actor_id.find(actorId)?.name ?? known.get(actorId) ?? 'Someone';
}

const JOINED: Record<string, string> = { vr: 'joined in VR', 'blender-client': 'joined from a remote Blender', host: 'is hosting' };

function what(targets: string[]): string {
  if (targets.length === 0) return 'the whole document';
  const names = targets.map(id => conn?.db.label.object_id.find(id)?.name ?? `object ${id.slice(0, 6)}`);
  return names.length > 3 ? `${names.slice(0, 3).join(', ')} and ${names.length - 3} more` : names.join(', ');
}

function holder(leaseId: string): string {
  const lease = conn?.db.lease.lease_id.find(leaseId);
  return lease ? `${name(lease.ownerId)} is editing ${what(lease.targets)}` : 'someone else holds it';
}

// at: the server's clock when the reducer ran (Unix ms). The board runs on the same PC, so the
// difference is how long SpacetimeDB took to push the change here.
function note(kind: string, text: string, at?: bigint): void {
  const now = Date.now();
  const pushedMs = at === undefined ? null : Math.max(0, now - Number(at));
  events.unshift({ id: nextEvent++, at: now, kind, text, pushedMs });
  events.length = Math.min(events.length, MAX_EVENTS);
  send();
}

function state() {
  const now = BigInt(Date.now());
  const db = conn?.db;
  const participants = db ? [...db.participant.iter()].sort((a, b) => Number(a.joinedAt - b.joinedAt)) : [];
  const leases = db ? [...db.lease.iter()].filter(l => l.expiresAt > now) : [];
  return {
    url: URL,
    database: DATABASE,
    connected,
    problem,
    participants: participants.map(p => ({ id: p.actorId, name: p.name, role: p.role })),
    leases: leases
      .sort((a, b) => Number(a.acquiredAt - b.acquiredAt))
      .map(l => ({
        id: l.leaseId,
        mode: l.mode,
        owner: name(l.ownerId),
        ownerId: l.ownerId,
        what: what(l.targets),
        since: Number(l.acquiredAt),
      })),
    events,
  };
}

let pending = false;
function send(): void {
  if (pending) return;
  pending = true;
  queueMicrotask(() => {
    pending = false;
    const data = `data: ${JSON.stringify(state())}\n\n`;
    for (const res of watchers) res.write(data);
  });
}

function connect(): void {
  conn = DbConnection.builder()
    .withUri(URL)
    .withDatabaseName(DATABASE)
    .onConnect(c => {
            c.db.participant.onInsert((ctx, p) => {
        known.set(p.actorId, p.name);
        if (happened(ctx)) note('join', `${p.name} ${JOINED[p.role] ?? 'joined'}`, p.joinedAt);
      });
      c.db.participant.onDelete((ctx, p) => happened(ctx) && note('leave', `${p.name} left`));
      c.db.participant.onUpdate((_ctx, _old, p) => {
        known.set(p.actorId, p.name);
        send();
      });
      c.db.lease.onInsert((ctx, l) =>
        happened(ctx) && note('grant', `SpacetimeDB let ${name(l.ownerId)} edit ${what(l.targets)}`, l.acquiredAt));
      c.db.lease.onDelete((ctx, l) =>
        happened(ctx) && note('release', `${name(l.ownerId)} finished editing ${what(l.targets)}`));
      c.db.lease.onUpdate(() => send()); // a renewal
      c.db.label.onInsert(() => send());
      c.db.label.onUpdate(() => send());
      c.db.refusal.onInsert((ctx, r) =>
        happened(ctx) && note('refusal', `SpacetimeDB refused ${name(r.actorId)}'s request for ${what(r.targets)}: ${holder(r.blockingLeaseId)}`, r.at));
      c.subscriptionBuilder()
        .onApplied(() => {
          connected = true;
          problem = '';
          console.log(`Subscribed to ${DATABASE} at ${URL}`);
          send();
        })
        .onError(() => {
          problem = 'The subscription failed. Is the module published?';
          send();
        })
        .subscribe([
          'SELECT * FROM participant',
          'SELECT * FROM lease',
          'SELECT * FROM label',
          'SELECT * FROM refusal',
        ]);
    })
    .onConnectError((_ctx, e) => retry(`Can't reach SpacetimeDB at ${URL}: ${e.message}`))
    .onDisconnect((_ctx, e) => retry(`Lost SpacetimeDB${e ? `: ${e.message}` : ''}`))
    .build();
}

let retrying: NodeJS.Timeout | null = null;
function retry(why: string): void {
  connected = false;
  problem = why;
  console.log(why);
  send();
  if (retrying === null) {
    retrying = setTimeout(() => {
      retrying = null;
      connect();
    }, 2000);
  }
}

createServer((req, res) => {
  if (req.url === '/events') {
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
    watchers.add(res);
    req.on('close', () => watchers.delete(res));
    res.write(`data: ${JSON.stringify(state())}\n\n`);
    return;
  }
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(PAGE);
}).listen(PORT, '127.0.0.1', () => console.log(`Session board: http://127.0.0.1:${PORT}`));

setInterval(send, 1000); // leases lapse by time too
connect();

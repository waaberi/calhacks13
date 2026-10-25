// The internet bridge (#166): lets a remote Blender reach the host's LAN port through SpacetimeDB,
// when the two PCs share no network. Each end runs one bridge; both connect out to the same
// database (Maincloud), so nobody needs a LAN address, port forwarding or a VPN.
//
//   host PC:   npm run bridge -- host     # carries connections to this PC's Blender, 127.0.0.1:8767
//   remote PC: npm run bridge -- join     # remote Blender connects to 127.0.0.1:8767 as if on a LAN
//
// Options (defaults shown): --url https://maincloud.spacetimedb.com  --database spatial-modeling
//   host: --blender 127.0.0.1:8767     join: --listen 127.0.0.1:8767
// The session token comes from SPATIAL_MODELING_TOKEN or is asked for. It never leaves this PC:
// the room id and proof sent to SpacetimeDB are hashes of the key lan.py derives from it.
//
// Bytes pass through unchanged, so the TLS-PSK session between the two Blenders stays end to end;
// SpacetimeDB only ever stores ciphertext. The join bridge refuses a connection that doesn't
// start a TLS handshake, so the add-on's no-TLS fallback can't leak the token to the relay.
// Each TCP connection becomes one pipe (spacetime/src/index.ts). If anything goes wrong with a
// pipe, the bridge closes it and Blender reconnects, as it does after any lost connection.

import { createHash, pbkdf2Sync, randomBytes } from 'node:crypto';
import { connect as tcpConnect, createServer, type Socket } from 'node:net';
import { createInterface } from 'node:readline/promises';
import { DbConnection } from './module_bindings';

const FRAME_BYTES = 65_536; // the module's MAX_FRAME_BYTES
const WINDOW = 48n; // frames in flight per pipe; the module refuses more than 64
const TLS_HANDSHAKE = 0x16; // first byte of every TLS connection

function option(name: string, fallback: string): string {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback;
}

function hostPort(text: string): { host: string; port: number } {
  const i = text.lastIndexOf(':');
  return { host: text.slice(0, i), port: Number(text.slice(i + 1)) };
}

const MODE = process.argv[2];
const URL = option('url', 'https://maincloud.spacetimedb.com');
const DATABASE = option('database', 'spatial-modeling');
const BLENDER = hostPort(option('blender', '127.0.0.1:8767'));
const LISTEN = hostPort(option('listen', '127.0.0.1:8767'));

// The same key as lan.psk(token), so a token that works on the LAN works here.
function room(token: string): { roomId: string; proof: string } {
  const normalized = token.toLowerCase().replace(/[\s-]/g, '');
  if (normalized.length < 16) throw new Error('The session token needs at least 16 characters');
  const key = pbkdf2Sync(normalized, 'spatial_modeling LAN PSK v1', 200_000, 32, 'sha256');
  const hash = (label: string) => createHash('sha256').update(label).update(key).digest('hex');
  return { roomId: hash('spatial_modeling relay room v1').slice(0, 32), proof: hash('spatial_modeling relay proof v1') };
}

async function askToken(): Promise<string> {
  if (process.env.SPATIAL_MODELING_TOKEN) return process.env.SPATIAL_MODELING_TOKEN;
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  const token = await rl.question('Session token (from the host\'s add-on preferences): ');
  rl.close();
  return token;
}

let conn: DbConnection | null = null;
const pipes = new Map<string, Pipe>();

// One TCP connection, carried as numbered frames in each direction.
class Pipe {
  private sent = 0n; // last frame this side sent
  private peerAcked = 0n; // last frame of ours the other side wrote out
  private written = 0n; // last frame from the other side written to the socket
  private early = new Map<bigint, Uint8Array>();
  private acking = false;
  private closed = false;

  constructor(readonly id: string, readonly asHost: boolean, readonly socket: Socket) {
    pipes.set(id, this);
    socket.setNoDelay(true);
    socket.on('data', chunk => this.outgoing(chunk));
    socket.on('drain', () => this.ack());
    socket.on('close', () => this.close('closed'));
    socket.on('error', () => this.close('closed'));
  }

  private outgoing(chunk: Buffer): void {
    for (let at = 0; at < chunk.length; at += FRAME_BYTES) {
      const seq = ++this.sent;
      conn!.reducers
        .send({ pipeId: this.id, seq, data: new Uint8Array(chunk.subarray(at, at + FRAME_BYTES)) })
        .catch(e => this.close(`send failed: ${e?.message ?? e}`));
    }
    if (this.sent - this.peerAcked >= WINDOW) this.socket.pause();
  }

  // The pipe row changed: the other side may have written more of our frames.
  progress(row: { hostAcked: bigint; clientAcked: bigint }): void {
    this.peerAcked = this.asHost ? row.clientAcked : row.hostAcked;
    if (this.sent - this.peerAcked < WINDOW && this.socket.isPaused()) this.socket.resume();
  }

  incoming(seq: bigint, data: Uint8Array): void {
    if (seq <= this.written) return;
    this.early.set(seq, data);
    let next: Uint8Array | undefined;
    while ((next = this.early.get(this.written + 1n)) !== undefined) {
      this.early.delete(++this.written);
      this.socket.write(next);
    }
    if (this.socket.writableNeedDrain) return; // ack after 'drain', so a slow Blender slows the sender
    this.ack();
  }

  // One ack in flight at a time; it covers every frame written so far.
  private ack(): void {
    if (this.acking || this.closed) return;
    this.acking = true;
    queueMicrotask(() => {
      const upto = this.written; // after every frame this transaction delivered
      conn!.reducers
        .ack({ pipeId: this.id, upto })
        .catch(() => {})
        .finally(() => {
          this.acking = false;
          if (this.written > upto && !this.socket.writableNeedDrain) this.ack();
        });
    });
  }

  close(why: string, tellRelay = true): void {
    if (this.closed) return;
    this.closed = true;
    pipes.delete(this.id);
    this.socket.destroy();
    if (tellRelay) conn?.reducers.closePipe({ pipeId: this.id }).catch(() => {});
    console.log(`Connection ${this.id.slice(0, 6)} ${why}`);
  }
}

function start(token: { roomId: string; proof: string }): void {
  let opened = false;
  conn = DbConnection.builder()
    .withUri(URL)
    .withDatabaseName(DATABASE)
    .onConnect(c => {
      const me = c.identity!;
      c.db.myPipe.onInsert((_ctx, row) => {
        if (MODE === 'host' && row.host.isEqual(me) && !pipes.has(row.pipeId)) {
          const socket = tcpConnect(BLENDER.port, BLENDER.host);
          new Pipe(row.pipeId, true, socket);
          socket.on('connect', () => console.log(`Remote Blender ${row.pipeId.slice(0, 6)} connected`));
        }
        pipes.get(row.pipeId)?.progress(row);
      });
      c.db.myPipe.onUpdate((_ctx, _old, row) => pipes.get(row.pipeId)?.progress(row));
      c.db.myPipe.onDelete((_ctx, row) =>
        setImmediate(() => {
          if (![...c.db.myPipe.iter()].some(p => p.pipeId === row.pipeId)) {
            pipes.get(row.pipeId)?.close('closed by the other side', false);
          }
        })
      );
      c.db.myFrame.onInsert((_ctx, f) => pipes.get(f.pipeId)?.incoming(f.seq, f.data));
      c.subscriptionBuilder()
        .onApplied(async () => {
          if (MODE === 'host') {
            try {
              await c.reducers.openRoom(token);
              console.log(`Hosting through ${DATABASE} at ${URL}; remote Blenders reach ${BLENDER.host}:${BLENDER.port}`);
            } catch (e: any) {
              console.log(`Couldn't open the room: ${e?.message ?? e}`);
              process.exit(1);
            }
          } else if (!opened) {
            opened = true;
            listen(token);
          }
        })
        .onError(() => console.log('The subscription failed. Is the module published to this database?'))
        .subscribe(['SELECT * FROM my_pipe', 'SELECT * FROM my_frame']);
    })
    .onConnectError((_ctx, e) => retry(`Can't reach SpacetimeDB at ${URL}: ${e.message}`, token))
    .onDisconnect((_ctx, e) => retry(`Lost SpacetimeDB${e ? `: ${e.message}` : ''}`, token))
    .build();
}

let retrying: NodeJS.Timeout | null = null;
function retry(why: string, token: { roomId: string; proof: string }): void {
  console.log(`${why}; trying again`);
  for (const p of [...pipes.values()]) p.close('lost with SpacetimeDB', false);
  if (retrying === null) retrying = setTimeout(() => ((retrying = null), start(token)), 2000);
}

// join: each connection from the local Blender becomes a pipe into the host's room.
function listen(token: { roomId: string; proof: string }): void {
  createServer(socket => {
    socket.pause();
    socket.once('readable', async () => {
      const first: Buffer | null = socket.read();
      if (first === null || first[0] !== TLS_HANDSHAKE) {
        console.log('Refused a connection without TLS: turn on "Use TLS with the token" in the add-on');
        socket.destroy();
        return;
      }
      socket.unshift(first);
      const pipeId = randomBytes(16).toString('hex');
      try {
        await conn!.reducers.openPipe({ pipeId, ...token });
      } catch (e: any) {
        console.log(`Couldn't reach the host: ${e?.message ?? e}`);
        socket.destroy();
        return;
      }
      new Pipe(pipeId, false, socket);
      socket.resume();
      console.log(`Blender connected; carrying it to the host as ${pipeId.slice(0, 6)}`);
    });
  }).listen(LISTEN.port, LISTEN.host, () =>
    console.log(`Joined through ${DATABASE} at ${URL}. In the add-on, connect to ${LISTEN.host} port ${LISTEN.port}.`)
  );
}

if (MODE !== 'host' && MODE !== 'join') {
  console.log('Usage: npm run bridge -- host|join [--url URL] [--database NAME] [--blender|--listen HOST:PORT]');
  process.exit(2);
}
askToken().then(t => start(room(t)));

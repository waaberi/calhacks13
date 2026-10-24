"""Host role's server: JSON lines over TCP, served from a background thread.

It always listens on the localhost port for the Unity app, plain TCP on
127.0.0.1 only. Extra listeners, such as the LAN port for Client-role add-ons
(lan.py), share its reader, queue and handlers; each has its own address and
optionally TLS or a hello token.

The network thread only reads, decodes and writes. Decoded messages, and an
event whenever a connection opens or closes, go on one queue in the order they
happened. drain() handles them on whichever thread calls it: Blender's main
thread, through the timer in host.py. This module must not import bpy, so it
stays testable outside Blender.

A connection joins when the hello handler welcomes it (session.py sets
conn.joined). Until then only OPEN_TYPES are handled. broadcast() reaches joined
connections only, on every listener. A connection that sends no line for
HEARTBEAT_TIMEOUT seconds is closed; clients ping every 2 s.

Error codes sent in `error` payloads:

- invalid_message: not JSON, not an object or a bad envelope. The line is dropped.
- unsupported_version: wrong `v`. The connection is closed.
- message_too_large: a line over protocol.MAX_LINE_BYTES. The connection is closed.
- unknown_type: no handler for this `type`.
- busy: too many messages are waiting for Blender. The message is dropped.
- internal_error: the handler failed.
- permission_denied: anything but OPEN_TYPES before the connection joined. And on
  a listener with a token, the first message wasn't `hello` with that token; then
  the connection is closed.
"""

import asyncio
import functools
import itertools
import json
import logging
import queue
import threading

try:
    from . import lan, protocol
except ImportError:  # imported directly by the tests, outside Blender
    import lan
    import protocol

HOST = "127.0.0.1"  # never 0.0.0.0: this port must not reach the LAN
PORT = 8765
MAX_PENDING = 1000  # decoded messages waiting for the main thread
MAX_WRITE_BUFFER = 4 * protocol.MAX_LINE_BYTES  # unread replies before we drop a client
HEARTBEAT_TIMEOUT = 6.0  # seconds without a line from a client before we close it
OPEN_TYPES = frozenset({"hello", "ping"})  # handled before a connection has joined

_OPENED = object()  # inbox events, queued with the messages so they stay in order
_CLOSED = object()

log = logging.getLogger(__name__)


def error(code, text, re=None, details=None):
    payload = {"code": code, "message": text[:1024]}  # the schema's limit
    if details is not None:
        payload["details"] = details
    return protocol.message("error", payload, re=re)


def ping(msg, conn):
    """Answer a ping. Touches no scene data."""
    return protocol.message("pong", re=msg["id"])


# Message type -> handler(msg, conn) returning a reply or None. Runs on the main thread.
# Handlers that change Blender data must be wrapped with host.undoable(label).
HANDLERS = {"ping": ping}


def _rejection(line, exc):
    """Return (error reply, close?) for a line that protocol.decode rejected."""
    try:
        raw = json.loads(line)
    except (ValueError, RecursionError):
        raw = None
    if not isinstance(raw, dict):
        return error("invalid_message", str(exc)), False
    re = raw["id"] if isinstance(raw.get("id"), str) else None
    if raw.get("v") != protocol.VERSION:
        return error("unsupported_version", str(exc), re), True
    return error("invalid_message", str(exc), re), False


class Listener:
    """One address the server listens on.

    ssl: an ssl.SSLContext (lan.server_tls_context) to require TLS, or None for plain TCP.
    token: only without TLS: the first message must be `hello` carrying this session
        token, or the host replies permission_denied and closes. Until then the
        connection can't reach the queue or receive anything sent to clients.
    roles: the hello roles admitted here; session.py refuses others with
        permission_denied. The localhost port is the Unity app's.
    """

    def __init__(self, host, port, ssl=None, token=None, roles=("vr",)):
        self.host = host
        self.port = port  # the bound port after Server.start(), useful with port=0
        self.ssl = ssl
        self.token = token
        self.roles = tuple(roles)


class Connection:
    """One client connection, as handlers see it. send() and close() are safe from any thread."""

    def __init__(self, server, listener, number, peer):
        self.server = server
        self.listener = listener  # where it connected
        self.number = number  # unique within its server, for logs
        self.peer = peer  # the client's (address, port)
        self.joined = False  # welcomed; set by the hello handler on the main thread
        self.can_edit = False  # may send commands; set with joined (session.py)
        self.closing = False  # close() was called; drain() ignores its remaining messages

    def send(self, *msgs):
        self.server.send(self, *msgs)

    def close(self):
        self.server.close(self)

    def __repr__(self):
        return f"<connection {self.number} from {self.peer}>"


class Server:
    """Listening sockets and their connections, on an asyncio loop in a daemon thread.

    The first listener is always the plain localhost one (host, port);
    extra_listeners come after it. handlers maps a message type to
    handler(msg, conn). on_connect(conn) and on_disconnect(conn) are called when
    a connection opens (after any token check) and closes. All of them run
    inside drain(), in the order things happened on the connection.
    """

    def __init__(self, host=HOST, port=PORT, handlers=None, extra_listeners=(),
                 on_connect=None, on_disconnect=None):
        self.listeners = [Listener(host, port), *extra_listeners]
        self.handlers = HANDLERS if handlers is None else handlers
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.connections = set()  # open connections as drain() has seen them; main thread
        self.inbox = queue.Queue()  # (Connection, message or _OPENED or _CLOSED)
        self._slots = threading.Semaphore(MAX_PENDING)  # room for messages; events always fit
        self._numbers = itertools.count(1)
        self._writers = {}  # Connection -> StreamWriter; touched only on the loop thread
        self._loop = None
        self._thread = None
        self._start_error = None

    @property
    def host(self):
        return self.listeners[0].host

    @property
    def port(self):
        return self.listeners[0].port

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout=5.0):
        """Bind and start serving. Raises OSError if the port can't be bound."""
        if self._thread is not None:
            raise RuntimeError("server already started")
        self.inbox = queue.Queue()  # never run requests left from a previous run
        self._slots = threading.Semaphore(MAX_PENDING)
        self.connections = set()
        self._start_error = None
        ready = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, args=(ready,), name="spatial_modeling host server", daemon=True
        )
        self._thread.start()
        if not ready.wait(timeout):
            self.stop()
            raise TimeoutError(f"server did not start within {timeout} s")
        if self._start_error is not None:
            self._thread.join(timeout)
            self._thread = self._loop = None
            raise self._start_error

    def stop(self, timeout=2.0):
        """Close every connection and the listening socket, stop the loop, join the thread."""
        loop, thread = self._loop, self._thread
        if thread is None:
            return
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:  # the loop already closed
            pass
        thread.join(timeout)
        if thread.is_alive():
            log.warning("host server thread did not stop within %s s", timeout)
        self._thread = self._loop = None

    def send(self, conn, *msgs):
        """Send msgs to conn, in order. Safe from any thread; a no-op once it's gone.

        Every message is encoded before any is sent, so an error sends none of them.
        """
        data = b"".join(protocol.encode(msg) for msg in msgs)
        self._call(self._write, conn, data)

    def broadcast(self, msg, exclude=None):
        """Send msg to every joined connection except `exclude`. Main thread only."""
        data = protocol.encode(msg)
        for conn in self.connections:
            if conn.joined and not conn.closing and conn is not exclude:
                self._call(self._write, conn, data)

    def close(self, conn):
        """Close conn once what was sent to it is written. Safe from any thread."""
        conn.closing = True
        self._call(self._drop, conn)

    def drain(self, limit=100):
        """Handle up to `limit` queued messages and events on the calling thread.

        Returns how many it handled.
        """
        for count in range(limit):
            try:
                conn, item = self.inbox.get_nowait()
            except queue.Empty:
                return count
            if item is _OPENED:
                self.connections.add(conn)
                self._notify(self.on_connect, conn)
            elif item is _CLOSED:
                self.connections.discard(conn)
                self._notify(self.on_disconnect, conn)
            else:
                self._slots.release()
                self._handle(conn, item)
        return limit

    def _handle(self, conn, msg):
        if conn.closing:
            return  # being closed, for example after a refused hello
        type_ = msg["type"]
        if not conn.joined and type_ not in OPEN_TYPES:
            self.send(conn, error("permission_denied", f"send hello before {type_!r}", msg["id"]))
            return
        handler = self.handlers.get(type_)
        if handler is None:
            self.send(conn, error("unknown_type", f"no handler for {type_!r}", msg["id"]))
            return
        try:
            reply = handler(msg, conn)
            if reply is not None:
                self.send(conn, reply)
        except Exception as e:
            log.exception("handler for %r failed", type_)
            self.send(conn, error("internal_error", str(e), msg["id"]))

    @staticmethod
    def _notify(hook, conn):
        if hook is None:
            return
        try:
            hook(conn)
        except Exception:
            log.exception("connection hook failed for %r", conn)

    def _call(self, fn, *args):
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:  # the loop closed in the meantime
            pass

    # Everything below runs on the server thread.

    def _run(self, ready):
        loop = self._loop
        servers = []
        try:
            for listener in self.listeners:  # all or nothing
                servers.append(loop.run_until_complete(self._listen(listener)))
        except OSError as e:
            self._start_error = e
            ready.set()
            loop.run_until_complete(self._close(servers))
            loop.close()
            return
        ready.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(self._close(servers))
            loop.close()

    async def _listen(self, listener):
        tls = {}
        if listener.ssl is not None:
            tls = {"ssl": listener.ssl, "ssl_handshake_timeout": lan.HANDSHAKE_TIMEOUT}
        server = await asyncio.start_server(
            functools.partial(self._serve, listener),
            listener.host,
            listener.port,
            limit=protocol.MAX_LINE_BYTES - 1,
            **tls,  # a failed handshake closes that connection; _serve never sees it
        )
        listener.port = server.sockets[0].getsockname()[1]
        return server

    async def _close(self, servers):
        for server in servers:
            server.close()  # stop listening
            server.abort_clients()
        tasks = asyncio.all_tasks() - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(asyncio.gather(*(s.wait_closed() for s in servers)), 1)
        except TimeoutError:
            log.warning("host server connections did not close within 1 s")

    def _write(self, conn, data):
        writer = self._writers.get(conn)
        if writer is None or writer.is_closing():
            return
        writer.write(data)
        if writer.transport.get_write_buffer_size() > MAX_WRITE_BUFFER:
            log.warning("%r is not reading its replies; dropping it", conn)
            writer.transport.abort()

    def _drop(self, conn):
        writer = self._writers.get(conn)
        if writer is not None:
            writer.close()  # after the buffered replies; _serve then sees EOF and cleans up

    async def _serve(self, listener, reader, writer):
        conn = Connection(self, listener, next(self._numbers), writer.get_extra_info("peername"))
        try:
            hello = None
            if listener.token is not None:
                hello = await self._admit(listener, reader, writer)
                if hello is None:
                    return
            self._writers[conn] = writer
            self.inbox.put((conn, _OPENED))
            try:
                if hello is not None:
                    self._enqueue(conn, hello)
                await self._read_lines(conn, reader)
            finally:
                del self._writers[conn]
                self.inbox.put((conn, _CLOSED))
        except OSError:  # the client went away; on the LAN port also ssl.SSLError
            pass
        except Exception:
            log.exception("%r failed", conn)
        finally:
            writer.close()  # flushes any error reply first

    async def _admit(self, listener, reader, writer):
        """Return the first message if it's `hello` with the listener's token, else refuse.

        A refusal writes one `error` and returns None; the caller closes the connection.
        """
        try:
            async with asyncio.timeout(lan.HANDSHAKE_TIMEOUT):
                line = b""
                while not line.strip():
                    line = await reader.readuntil(b"\n")
        except (asyncio.IncompleteReadError, TimeoutError):
            return None
        except asyncio.LimitOverrunError:
            text = f"line is longer than {protocol.MAX_LINE_BYTES} bytes"
            writer.write(protocol.encode(error("message_too_large", text)))
            return None
        try:
            msg = protocol.decode(line)
        except protocol.ProtocolError as e:
            writer.write(protocol.encode(_rejection(line, e)[0]))
            return None
        token = msg["payload"].pop("token", None) if msg["type"] == "hello" else None
        if msg["type"] != "hello":
            text = "send hello with the session token first"
        elif token is None:
            text = "hello has no session token"
        elif not lan.tokens_match(listener.token, token):
            text = "wrong session token"
        else:
            return msg
        writer.write(protocol.encode(error("permission_denied", text, msg["id"])))
        return None

    def _enqueue(self, conn, msg):
        if not self._slots.acquire(blocking=False):
            text = "too many messages are waiting for Blender; try again"
            self._write(conn, protocol.encode(error("busy", text, msg["id"])))
            return
        self.inbox.put((conn, msg))

    async def _read_lines(self, conn, reader):
        while True:
            try:
                async with asyncio.timeout(HEARTBEAT_TIMEOUT):
                    line = await reader.readuntil(b"\n")
            except TimeoutError:
                log.info("%r: nothing heard for %s s; closing it", conn, HEARTBEAT_TIMEOUT)
                return
            except asyncio.IncompleteReadError:
                return  # the client hung up
            except asyncio.LimitOverrunError:
                text = f"line is longer than {protocol.MAX_LINE_BYTES} bytes"
                self._write(conn, protocol.encode(error("message_too_large", text)))
                return
            if not line.strip():
                continue
            try:
                msg = protocol.decode(line)
            except protocol.ProtocolError as e:
                reply, close = _rejection(line, e)
                self._write(conn, protocol.encode(reply))
                if close:
                    return
                continue
            if msg["type"] == "hello":
                msg["payload"].pop("token", None)  # checked by _admit; no handler or log sees it
            self._enqueue(conn, msg)

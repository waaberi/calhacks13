"""Host role's localhost server: JSON lines over TCP, served from a background thread.

The network thread only reads, decodes and writes. Decoded messages go on a
queue, and drain() runs their handlers on whichever thread calls it: Blender's
main thread, through the timer in host.py. This module must not import bpy, so
it stays testable outside Blender.

Error codes sent in `error` payloads:

- invalid_message: not JSON, not an object or a bad envelope. The line is dropped.
- unsupported_version: wrong `v`. The connection is closed.
- message_too_large: a line over protocol.MAX_LINE_BYTES. The connection is closed.
- unknown_type: no handler for this `type`.
- busy: too many messages are waiting for Blender. The message is dropped.
- internal_error: the handler failed.
"""

import asyncio
import itertools
import json
import logging
import queue
import threading

try:
    from . import protocol
except ImportError:  # imported directly by the tests, outside Blender
    import protocol

HOST = "127.0.0.1"  # never 0.0.0.0: this port must not reach the LAN
PORT = 8765
MAX_PENDING = 1000  # decoded messages waiting for the main thread
MAX_WRITE_BUFFER = 4 * protocol.MAX_LINE_BYTES  # unread replies before we drop a client

log = logging.getLogger(__name__)


def error(code, text, re=None):
    return protocol.message("error", {"code": code, "message": text}, re=re)


def ping(msg):
    """Answer a ping. Touches no scene data."""
    return protocol.message("pong", re=msg["id"])


# Message type -> handler(msg) returning a reply or None. Runs on the main thread.
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


class Server:
    """One listening socket and its connections, on an asyncio loop in a daemon thread."""

    def __init__(self, host=HOST, port=PORT, handlers=None):
        self.host = host
        self.port = port  # the bound port after start(), useful with port=0
        self.handlers = HANDLERS if handlers is None else handlers
        self.inbox = queue.Queue(MAX_PENDING)  # (connection id, message)
        self._ids = itertools.count(1)
        self._writers = {}  # connection id -> StreamWriter; touched only on the loop thread
        self._loop = None
        self._thread = None
        self._start_error = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout=5.0):
        """Bind and start serving. Raises OSError if the port can't be bound."""
        if self._thread is not None:
            raise RuntimeError("server already started")
        self.inbox = queue.Queue(MAX_PENDING)  # never run requests left from a previous run
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

    def send(self, conn, msg):
        """Send msg to connection conn. Safe from any thread; a no-op once it's gone."""
        data = protocol.encode(msg)
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._write, conn, data)
        except RuntimeError:  # the loop closed in the meantime
            pass

    def drain(self, limit=100):
        """Handle up to `limit` queued messages on the calling thread. Returns how many."""
        for count in range(limit):
            try:
                conn, msg = self.inbox.get_nowait()
            except queue.Empty:
                return count
            handler = self.handlers.get(msg["type"])
            if handler is None:
                self.send(conn, error("unknown_type", f"no handler for {msg['type']!r}", msg["id"]))
                continue
            try:
                reply = handler(msg)
                if reply is not None:
                    self.send(conn, reply)
            except Exception as e:
                log.exception("handler for %r failed", msg["type"])
                self.send(conn, error("internal_error", str(e), msg["id"]))
        return limit

    # Everything below runs on the server thread.

    def _run(self, ready):
        loop = self._loop
        try:
            server = loop.run_until_complete(
                asyncio.start_server(
                    self._serve, self.host, self.port, limit=protocol.MAX_LINE_BYTES - 1
                )
            )
        except OSError as e:
            self._start_error = e
            ready.set()
            loop.close()
            return
        self.port = server.sockets[0].getsockname()[1]
        ready.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(self._close(server))
            loop.close()

    async def _close(self, server):
        server.close()  # stop listening
        server.abort_clients()
        tasks = asyncio.all_tasks() - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(server.wait_closed(), 1)
        except TimeoutError:
            log.warning("host server connections did not close within 1 s")

    def _write(self, conn, data):
        writer = self._writers.get(conn)
        if writer is None or writer.is_closing():
            return
        writer.write(data)
        if writer.transport.get_write_buffer_size() > MAX_WRITE_BUFFER:
            log.warning("connection %s is not reading its replies; dropping it", conn)
            writer.transport.abort()

    async def _serve(self, reader, writer):
        conn = next(self._ids)
        self._writers[conn] = writer
        try:
            await self._read_lines(conn, reader)
        except ConnectionError:
            pass
        except Exception:
            log.exception("connection %s failed", conn)
        finally:
            del self._writers[conn]
            writer.close()  # flushes any error reply first

    async def _read_lines(self, conn, reader):
        while True:
            try:
                line = await reader.readuntil(b"\n")
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
            try:
                self.inbox.put_nowait((conn, msg))
            except queue.Full:
                text = "too many messages are waiting for Blender; try again"
                self._write(conn, protocol.encode(error("busy", text, msg["id"])))

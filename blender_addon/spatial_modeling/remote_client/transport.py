"""Background connection to the host. Reuses the host's framing and TLS-PSK helpers.

Receives the scene for the mirror and, for Client edits (requests.py), sends the
messages handed to send(): commands and receipt.query. Nothing is queued while
disconnected: send() refuses, and anything not yet written when the connection
drops is discarded, never sent on the next connection.
"""

import queue
import re
import socket
import threading
import time

from .. import lan, protocol


class ReadOnlyLink:
    def __init__(self, address, token, version, name="Blender viewer", port=lan.PORT,
                 tls=True, retry=2.0):
        self.events = queue.Queue(maxsize=128)
        self.expected = None
        self._outbox = queue.Queue()
        self._hello_id = None
        self._stop = threading.Event()
        self._socket = None
        self.last_received = 0
        self._args = address, token, version, name, port, tls, retry
        self.thread = threading.Thread(target=self._run, daemon=True, name="Blender read-only client")
        self.thread.start()

    @property
    def healthy(self):
        return (self._socket is not None and self.thread.is_alive()
                and time.monotonic() - self.last_received < 6)

    def send(self, msg):
        """Queue msg for the current connection. False (nothing queued) when not connected."""
        if self._socket is None or self._stop.is_set():
            return False
        self._outbox.put(msg)
        return True

    def _drain_outbox(self):
        while True:
            try:
                self._outbox.get_nowait()
            except queue.Empty:
                return

    def stop(self):
        self._stop.set()
        sock = self._socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        self.thread.join(timeout=0.5)

    def _post(self, kind, payload):
        # Back-pressure never drops a scene delta silently. A full consumer pauses
        # reception; host queue limits and the heartbeat force a fresh reconnect.
        while not self._stop.is_set():
            try:
                self.events.put((kind, payload), timeout=0.2)
                return
            except queue.Full:
                continue

    def _run(self):
        address, token, version, name, port, tls, retry = self._args
        while not self._stop.is_set():
            try:
                with lan.connect(address, token, port=port, tls=tls, timeout=2) as sock:
                    if self._stop.is_set():
                        return
                    self._socket = sock
                    sock.settimeout(0.25)
                    payload = {"role": "blender-client", "name": name,
                               "app": {"name": "SpatialModeling", "version": version}}
                    if not tls:
                        payload["token"] = token
                    if self.expected:
                        payload["document"] = self.expected.copy()
                    self._drain_outbox()  # never carry an edit over to a new connection
                    hello = protocol.message("hello", payload)
                    self._hello_id = hello["id"]
                    sock.sendall(protocol.encode(hello))
                    self._post("connecting", None)
                    buffer = bytearray()
                    received = pinged = time.monotonic()
                    while not self._stop.is_set():
                        now = time.monotonic()
                        while True:
                            try:
                                outgoing = self._outbox.get_nowait()
                            except queue.Empty:
                                break
                            sock.sendall(protocol.encode(outgoing))
                        if now - pinged >= 2:
                            sock.sendall(protocol.encode(protocol.message("ping")))
                            pinged = now
                        if now - received > 6:
                            raise TimeoutError("Host is not responding")
                        try:
                            data = sock.recv(65536)
                        except TimeoutError:
                            continue
                        if not data:
                            raise ConnectionError("Host disconnected")
                        buffer.extend(data)
                        while b"\n" in buffer:
                            line, _, rest = buffer.partition(b"\n")
                            buffer = bytearray(rest)
                            msg = protocol.decode(line)
                            received = time.monotonic()
                            self.last_received = received
                            kind, body = msg["type"], msg["payload"]
                            if kind == "welcome":
                                doc = body["document"]
                                if not all(isinstance(doc.get(k), str) and re.fullmatch("[0-9a-f]{32}", doc[k])
                                           for k in ("id", "open_epoch")):
                                    raise ValueError("Invalid host document identity")
                                self.expected = {k: doc[k] for k in ("id", "open_epoch")}
                            elif kind in ("scene.snapshot", "scene.update"):
                                doc = body["document"]
                                if self.expected is None or any(doc.get(k) != self.expected[k]
                                                                for k in ("id", "open_epoch")):
                                    self._post("error", "wrong_document")
                                    self._stop.set()
                                    break
                            reply_to = msg.get("re")
                            if kind == "error" and reply_to and reply_to != self._hello_id:
                                # An error answering one of our commands or queries: it
                                # concerns that request, not the connection or the scene.
                                code = body.get("code")
                                code = code if isinstance(code, str) else ""
                                self._post("reply_error", (reply_to, code))
                            elif kind == "error":
                                # Error text is intentionally not echoed: a remote host
                                # can send arbitrary text. Codes are sufficient for UI.
                                code = body.get("code", "invalid_message")
                                if code not in ("wrong_document", "unsupported_version", "permission_denied",
                                                "invalid_message", "busy", "internal_error", "failed"):
                                    code = "invalid_message"
                                self._post("error", code)
                                if code in ("wrong_document", "unsupported_version", "permission_denied"):
                                    self._stop.set()
                                    break
                            elif kind in ("welcome", "scene.snapshot", "scene.update",
                                          "session.update", "activity", "result"):
                                self._post(kind, body)
                            elif kind == "receipts":
                                self._post(kind, (reply_to, body))
                        if len(buffer) > protocol.MAX_LINE_BYTES:
                            raise protocol.ProtocolError("Host message exceeds size limit")
            except (OSError, ValueError, KeyError, TypeError, AttributeError, NotImplementedError):
                # Never include credentials or received text in a diagnostic.
                self._post("disconnected", "Disconnected — reconnecting; last scene is stale")
            finally:
                self._socket = None
                self._drain_outbox()
            self._stop.wait(retry)

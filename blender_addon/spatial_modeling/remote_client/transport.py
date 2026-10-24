"""Background read-only connection. Reuses the host's framing and TLS-PSK helpers."""

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
                    sock.sendall(protocol.encode(protocol.message("hello", payload)))
                    self._post("connecting", None)
                    buffer = bytearray()
                    received = pinged = time.monotonic()
                    while not self._stop.is_set():
                        now = time.monotonic()
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
                            if kind == "error":
                                # Error text is intentionally not echoed: a remote host
                                # can send arbitrary text. Codes are sufficient for UI.
                                code = body.get("code", "invalid_message")
                                if code not in ("wrong_document", "unsupported_version", "permission_denied",
                                                "invalid_message", "busy", "internal_error"):
                                    code = "invalid_message"
                                self._post("error", code)
                                if code in ("wrong_document", "unsupported_version", "permission_denied"):
                                    self._stop.set()
                                    break
                            elif kind in ("welcome", "scene.snapshot", "scene.update"):
                                self._post(kind, body)
                        if len(buffer) > protocol.MAX_LINE_BYTES:
                            raise protocol.ProtocolError("Host message exceeds size limit")
            except (OSError, ValueError, KeyError, TypeError, AttributeError, NotImplementedError):
                # Never include credentials or received text in a diagnostic.
                self._post("disconnected", "Disconnected — reconnecting; last scene is stale")
            finally:
                self._socket = None
            self._stop.wait(retry)

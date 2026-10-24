"""Send one ping to the Host-role add-on and print the pong.

Usage: python tests/backend/ping_client.py [--host 127.0.0.1] [--port 8765]

Blender must be running with the add-on enabled in Host role. The pong is sent
from Blender's main thread, so it waits while Blender is busy (for example,
rendering). The tests reuse Client.
"""

import argparse
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "blender_addon" / "spatial_modeling"))
import protocol


class Client:
    """A blocking JSON-lines connection to the host."""

    def __init__(self, host="127.0.0.1", port=8765, timeout=5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self._buf = b""

    def send(self, msg):
        """Send a message dict, or raw bytes for malformed-input tests."""
        self.sock.sendall(msg if isinstance(msg, bytes) else protocol.encode(msg))

    def recv(self):
        """Return the next message, or None once the host has closed the connection."""
        while b"\n" not in self._buf:
            try:
                chunk = self.sock.recv(65536)
            except ConnectionResetError:
                chunk = b""
            if not chunk:
                return None
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return protocol.decode(line)

    def close(self):
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def main():
    parser = argparse.ArgumentParser(description="Ping the Host-role add-on.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    try:
        client = Client(args.host, args.port)
    except OSError as e:
        sys.exit(f"Could not connect to {args.host}:{args.port} ({e}). "
                 "Is Blender running with the add-on enabled in Host role?")
    ping = protocol.message("ping")
    with client:
        started = time.perf_counter()
        client.send(ping)
        try:
            reply = client.recv()
        except TimeoutError:
            sys.exit("No reply within 5 s. Is Blender's main thread busy?")
    ms = (time.perf_counter() - started) * 1000
    print("sent:", ping)
    print(f"got:  {reply}  ({ms:.1f} ms)")
    if not reply or reply["type"] != "pong" or reply.get("re") != ping["id"]:
        sys.exit("FAIL: expected a pong answering this ping")
    print("OK")


if __name__ == "__main__":
    main()

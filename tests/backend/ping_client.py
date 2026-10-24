"""Ping the Host-role add-on, locally or over the LAN, and print the pong.

  python tests/backend/ping_client.py                        # Unity's port, 127.0.0.1:8765
  python tests/backend/ping_client.py --host 192.168.1.20 --token -   # LAN port 8767, TLS
  python tests/backend/ping_client.py --host 192.168.1.20 --token - --no-tls

--token - asks for the token without echoing it. A bare --token uses
$SPATIAL_MODELING_TOKEN, or asks if it is unset. Avoid --token VALUE outside
tests: it ends up in your shell history. Without TLS the client first sends hello with the token,
as the host requires in that mode.

Blender must be running with the add-on enabled in Host role, and for the LAN
port with "Let a Client-role Blender join over the LAN" on. The pong is sent
from Blender's main thread, so it waits while Blender is busy (for example,
rendering). The tests reuse Client. Exits 0 if the ping was answered.
"""

import argparse
import getpass
import os
import socket
import sys
import time
import tomllib
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parents[2] / "blender_addon" / "spatial_modeling"
sys.path.insert(0, str(ADDON_DIR))
import lan
import protocol

TOKEN_ENV = "SPATIAL_MODELING_TOKEN"


class Client:
    """A blocking JSON-lines connection to the host. With a token, to its LAN port."""

    def __init__(self, host="127.0.0.1", port=8765, timeout=5.0, token=None, tls=True):
        if token is None:
            self.sock = socket.create_connection((host, port), timeout=timeout)
        else:
            self.sock = lan.connect(host, token, port=port, tls=tls, timeout=timeout)
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

    def answer_to(self, msg):
        """Skip other messages (snapshots, updates) until the reply to msg; None if closed."""
        while (reply := self.recv()) is not None and reply.get("re") != msg["id"]:
            pass
        return reply

    def close(self):
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def hello(name, token=None):
    """A Client-role hello, with the add-on's own version; token only for the no-TLS mode."""
    manifest = tomllib.loads((ADDON_DIR / "blender_manifest.toml").read_text("utf-8"))
    payload = {
        "role": "blender-client",
        "name": name,
        "app": {"name": manifest["id"], "version": manifest["version"]},
    }
    if token is not None:
        payload["token"] = token
    return protocol.message("hello", payload)


def read_token(arg):
    """--token VALUE, else $SPATIAL_MODELING_TOKEN for a bare --token, else ask."""
    if arg == "" and os.environ.get(TOKEN_ENV):
        return os.environ[TOKEN_ENV]
    if arg in ("", "-"):
        return getpass.getpass("Session token (from the host's add-on preferences): ")
    return arg


def main():
    parser = argparse.ArgumentParser(description="Ping the Host-role add-on.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, help="default 8765, or 8767 with --token")
    parser.add_argument(
        "--token",
        nargs="?",
        const="",
        help=f"connect to the LAN port with this token; bare: ${TOKEN_ENV} or ask; '-': ask",
    )
    parser.add_argument("--no-tls", action="store_true", help="the host's LAN port runs without TLS")
    parser.add_argument("--name", default="ping_client", help="name sent in hello without TLS")
    args = parser.parse_args()
    if args.no_tls and args.token is None:
        parser.error("--no-tls needs --token")

    token = None if args.token is None else read_token(args.token)
    port = args.port or (lan.PORT if token is not None else 8765)
    tls = not args.no_tls
    try:
        client = Client(args.host, port, token=token, tls=tls)
    except (lan.TokenError, NotImplementedError, lan.HandshakeError) as e:
        sys.exit(f"FAIL: {e}")
    except OSError as e:
        sys.exit(f"FAIL: could not connect to {args.host}:{port} ({e}). Is Blender running "
                 "with the add-on in Host role, and the LAN port on? Is a firewall in the way?")
    with client:
        if token is not None and tls:
            print(f"TLS OK: {client.sock.version()}, {client.sock.cipher()[0]}, no certificate")
        elif token is not None:
            greeting = hello(args.name, token)
            client.send(greeting)
            reply = client.answer_to(greeting)
            if reply is None:
                sys.exit("FAIL: the host closed the connection after hello. Does it use TLS?")
            code = reply["payload"].get("code") if reply["type"] == "error" else None
            if code == "permission_denied":
                sys.exit(f"FAIL: the host refused the token ({reply['payload']['message']})")
            print(f"hello accepted: got {reply['type']}" + (f" {code}" if code else ""))
            if reply["type"] == "error" and code != "unknown_type":  # unknown_type: no hello yet
                sys.exit(f"FAIL: {reply['payload']['message']}")
        ping = protocol.message("ping")
        started = time.perf_counter()
        client.send(ping)
        try:
            reply = client.answer_to(ping)
        except TimeoutError:
            sys.exit("FAIL: no reply within 5 s. Is Blender's main thread busy?")
    ms = (time.perf_counter() - started) * 1000
    print("sent:", ping)
    print(f"got:  {reply}  ({ms:.1f} ms)")
    if not reply or reply["type"] != "pong":
        sys.exit("FAIL: expected a pong answering this ping")
    print("OK")


if __name__ == "__main__":
    main()

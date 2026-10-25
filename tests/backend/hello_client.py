"""Join the Host-role add-on from a terminal: hello, then print what the host sends.

  python tests/backend/hello_client.py --name Talia [--stay]           # as the VR app, 8765
  python tests/backend/hello_client.py --host 192.168.1.20 --token -   # as the Client role, LAN
  python tests/backend/hello_client.py --host 192.168.1.20 --token - --no-tls

Blender must be running with the add-on enabled in Host role (and for the LAN,
with "Let a Client-role Blender join" on). Prints welcome,
scene.snapshot and session.update. With --stay it keeps the connection, pings
every 2 s like a real client and prints every message until Ctrl-C, so you can
watch others join and leave. --token works as in ping_client.py and is never
printed. Try the refusals:

  --document ID:OPEN_EPOCH       expect another document: wrong_document
  --role blender-client          on 8765: permission_denied
  --version 0.0.1 with --token   another add-on version: unsupported_version

The tests reuse hello() and join().
"""

import argparse
import json
import sys
import threading
import time

from ping_client import Client, lan, protocol, read_token

# isort: split
import session  # the add-on's, for its version; ping_client put the add-on on sys.path

VERSION = session.APP["version"]


def hello(name="Terminal", role="vr", version=VERSION, document=None, token=None):
    """A hello; token only for the LAN port without TLS."""
    payload = {"role": role, "name": name, "app": {"name": "spatial_modeling", "version": version}}
    if document is not None:
        payload["document"] = document
    if token is not None:
        payload["token"] = token
    return protocol.message("hello", payload)


def join(client, **hello_args):
    """Send hello and return [welcome, scene.snapshot, session.update], or [error] if refused."""
    msg = hello(**hello_args)
    client.send(msg)
    reply = client.recv()
    if reply is None or reply["type"] != "welcome":
        return [reply]
    assert reply["re"] == msg["id"], reply
    return [reply, client.recv(), client.recv()]


def show(msg):
    text = json.dumps(msg, indent=2) if msg is not None else "(the host closed the connection)"
    print(text, flush=True)  # live, even when piped


def main():
    parser = argparse.ArgumentParser(description="Join the Host-role add-on.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, help="default 8765, or 8767 with --token")
    parser.add_argument("--token", nargs="?", const="",
                        help="join on the LAN port; bare: $SPATIAL_MODELING_TOKEN or ask; '-': ask")
    parser.add_argument("--no-tls", action="store_true", help="the host's LAN port runs without TLS")
    parser.add_argument("--name", default="Terminal")
    parser.add_argument("--role", choices=["vr", "blender-client"],
                        help="default vr, or blender-client with --token")
    parser.add_argument("--version", default=VERSION, help="app version to send")
    parser.add_argument("--document", metavar="ID:OPEN_EPOCH", help="the document you expect")
    parser.add_argument("--stay", action="store_true", help="stay connected and keep printing")
    args = parser.parse_args()
    if args.no_tls and args.token is None:
        parser.error("--no-tls needs --token")
    token = None if args.token is None else read_token(args.token)
    port = args.port or (lan.PORT if token is not None else 8765)
    role = args.role or ("blender-client" if token is not None else "vr")
    document = None
    if args.document:
        doc_id, _, epoch = args.document.partition(":")
        document = {"id": doc_id, "open_epoch": epoch}

    try:
        client = Client(args.host, port, token=token, tls=not args.no_tls)
    except (lan.TokenError, NotImplementedError, lan.HandshakeError) as e:
        sys.exit(f"FAIL: {e}")
    except OSError as e:
        sys.exit(f"Could not connect to {args.host}:{port} ({e}). "
                 "Is Blender running with the add-on enabled in Host role?")
    with client:
        try:
            msgs = join(client, name=args.name, role=role, version=args.version,
                        document=document, token=token if args.no_tls else None)
        except TimeoutError:
            sys.exit("No reply within 5 s. Is Blender's main thread busy?")
        for msg in msgs:
            show(msg)
        if msgs[0] is None or msgs[0]["type"] != "welcome":
            sys.exit("FAIL: the host did not welcome us")
        doc = msgs[0]["payload"]["document"]
        print(f"OK: joined {doc['name'] or 'an unsaved file'} "
              f"(--document {doc['id']}:{doc['open_epoch']})", flush=True)
        if not args.stay:
            return

        def heartbeat():
            while True:
                time.sleep(2)
                try:
                    client.send(protocol.message("ping"))
                except OSError:
                    return

        threading.Thread(target=heartbeat, daemon=True).start()
        client.sock.settimeout(None)
        try:
            while (msg := client.recv()) is not None:
                if msg["type"] != "pong":
                    show(msg)
        except KeyboardInterrupt:
            return
        show(None)


if __name__ == "__main__":
    main()

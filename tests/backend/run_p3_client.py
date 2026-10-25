"""Run two isolated real Blenders; preserve outputs, keep credentials temporary.

With --relay URL DATABASE the client reaches the host through two internet bridges
(spacetime/bridge/, #166) and that SpacetimeDB database instead of connecting directly.
Build the bridge first: `npm ci && npx tsc -p bridge` in spacetime/.
"""
import argparse
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path

BRIDGE = Path(__file__).resolve().parents[2] / "spacetime" / "bridge" / "dist" / "bridge.js"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _bridges(relay, token, host_port, output):
    """Start the host and join bridges; returns (processes, the port the client should use)."""
    url, database = relay
    join_port = _free_port()
    env = {**os.environ, "SPATIAL_MODELING_TOKEN": token}
    common = ["--url", url, "--database", database]
    procs = []
    host = subprocess.Popen(["node", str(BRIDGE), "host", *common, "--blender", f"127.0.0.1:{host_port}"],
                            env=env, stdout=(output / "bridge-host.log").open("w"), stderr=subprocess.STDOUT)
    procs.append(host)
    deadline = time.monotonic() + 20
    while b"Hosting through" not in (output / "bridge-host.log").read_bytes():
        if host.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError("Host bridge did not open its room; see bridge-host.log")
        time.sleep(.1)
    join = subprocess.Popen(["node", str(BRIDGE), "join", *common, "--listen", f"127.0.0.1:{join_port}"],
                            env=env, stdout=(output / "bridge-join.log").open("w"), stderr=subprocess.STDOUT)
    procs.append(join)
    while b"Joined through" not in (output / "bridge-join.log").read_bytes():
        if join.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError("Join bridge did not start; see bridge-join.log")
        time.sleep(.1)
    return procs, join_port


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--scale", type=float, choices=(1.0, .001), required=True)
    parser.add_argument("--ownership", action="store_true")
    parser.add_argument("--relay", nargs=2, metavar=("URL", "DATABASE"))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).parent
    with tempfile.TemporaryDirectory(prefix="p3-client-") as tmp:
        folder = Path(tmp)
        (folder / "config.json").write_text(json.dumps({"token": secrets.token_hex(24),
            "scale": args.scale, "ownership": args.ownership}))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        bridges = []
        with (output / "host.log").open("w", encoding="utf-8") as log:
            (folder / "host-temp").mkdir()
            (folder / "client-temp").mkdir()
            env = {**os.environ, "BLENDER_USER_RESOURCES": str(folder / "host-resources"),
                   "TEMP": str(folder / "host-temp"), "TMP": str(folder / "host-temp")}
            host = subprocess.Popen([args.blender, "--factory-startup", "--python",
                str(scripts / "p3_client_host_check.py"), "--", str(folder)],
                env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
            try:
                deadline = time.monotonic() + 40
                while not (folder / "ready.json").exists():
                    if host.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Isolated host did not start; see host.log")
                    time.sleep(.1)
                if args.relay:
                    time.sleep(.2)  # ready.json is written in one call, but be sure it's complete
                    ready = json.loads((folder / "ready.json").read_text())
                    bridges, ready["port"] = _bridges(args.relay, json.loads(
                        (folder / "config.json").read_text())["token"], ready["port"], output)
                    (folder / "ready.json").write_text(json.dumps(ready), encoding="utf-8")
                env["BLENDER_USER_RESOURCES"] = str(folder / "client-resources")
                env["TEMP"] = env["TMP"] = str(folder / "client-temp")
                env["SPATIAL_MODELING_TEST_TOOLS"] = "1"  # registers remote_test_ui's test move
                client = subprocess.run([args.blender, "--background", "--factory-startup",
                    "--python-exit-code", "1", "--python", str(scripts / "p3_client_operator_check.py"),
                    "--", str(folder)], env=env, capture_output=True, text=True, timeout=120,
                    creationflags=flags, check=False)
                (output / "client.log").write_text(client.stdout + client.stderr, encoding="utf-8")
                for name in ("host-result.json", "client-result.json", "host-error.txt", "client-error.txt"):
                    source = folder / name
                    if source.exists():
                        (output / name).write_bytes(source.read_bytes())
                if client.returncode != 0 or not (folder / "client-result.json").exists():
                    raise RuntimeError("Production Client operator test failed; see preserved logs")
                host.wait(timeout=12)
                print((output / "client-result.json").read_text())
            finally:
                for proc in bridges:
                    proc.terminate()
                if host.poll() is None:
                    host.terminate()  # Only our freshly launched process.
                    host.wait(timeout=10)


if __name__ == "__main__":
    main()

"""Launch only owned private-loopback experimental peers with separate profiles."""
import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--research", required=True)
    parser.add_argument("--blender", required=True)
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    research = Path(args.research).resolve()
    scripts = Path(__file__).resolve().parent
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    private = out / "private"
    private.mkdir()
    (private / "config.json").write_text(json.dumps({"port": port,
        "zip": str(research / "multi_user-0.8.2.zip"), "dependencies": str(research / "dependencies"),
        "server_password": secrets.token_hex(24), "admin_password": secrets.token_hex(24)}))
    startup = None
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    processes, logs = [], []
    try:
        env = dict(os.environ, PYTHONPATH=str(research / "dependencies"),
                   SPATIAL_NATIVE_SYNC_TEST="1", PYTHONDONTWRITEBYTECODE="1")
        log = (out / "server.log").open("w")
        logs.append(log)
        processes.append(subprocess.Popen([sys.executable, str(scripts / "multiuser_private_server.py"), str(private)],
            env=env, stdout=log, stderr=subprocess.STDOUT, startupinfo=startup,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
        deadline = time.monotonic() + 10
        while not (private / "server-ready").exists():
            assert processes[0].poll() is None and time.monotonic() < deadline
            time.sleep(.05)
        for side in ("host", "client"):
            for suffix in ("profile", "temp"):
                (private / f"{side}-{suffix}").mkdir()
            child_env = dict(env, BLENDER_USER_RESOURCES=str(private / f"{side}-profile"),
                             TEMP=str(private / f"{side}-temp"), TMP=str(private / f"{side}-temp"))
            log = (out / (side + ".log")).open("w")
            logs.append(log)
            proc = subprocess.Popen([args.blender, "--factory-startup", "--disable-autoexec", "--threads", "2",
                "--python", str(scripts / "multiuser_peer.py"), "--", str(private), side], env=child_env,
                stdout=log, stderr=subprocess.STDOUT, startupinfo=startup,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            processes.append(proc)
            (out / "owned-processes.json").write_text(json.dumps([p.pid for p in processes]))
            if side == "host":
                deadline = time.monotonic() + 65
                while not (private / "host-initial.json").exists():
                    if proc.poll() is not None or (private / "host-error.txt").exists() or time.monotonic() > deadline:
                        raise RuntimeError("Experimental Host did not initialize; inspect logs")
                    time.sleep(.1)
            else:
                proc.wait(timeout=145)
        processes[1].wait(timeout=10)
        assert (private / "host-received.json").exists(), "No automatic native edit receipt"
        assert (private / "client-received.json").exists(), "No reverse automatic native edit receipt"
        print((private / "host-received.json").read_text())
    finally:
        (private / "stop-server").touch()
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()

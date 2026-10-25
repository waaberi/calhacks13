"""Run two disposable full Blender GUI peers over TLS or the existing bridge."""
import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--relay", nargs=2)
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    folder = out / "private"
    folder.mkdir()
    (folder / "config.json").write_text(json.dumps({"token": secrets.token_hex(24), "timeout": 240}))
    procs, logs, bridges = [], [], []
    startup = None
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    try:
        for side in ("host", "client"):
            for suffix in ("profile", "temp"):
                (folder / (side + "-" + suffix)).mkdir()
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith("BLENDER_USER_")}
            env.update(SPATIAL_NATIVE_SYNC_TEST="1", PYTHONDONTWRITEBYTECODE="1",
                BLENDER_USER_RESOURCES=str(folder / (side + "-profile")),
                TEMP=str(folder / (side + "-temp")), TMP=str(folder / (side + "-temp")))
            log = (out / (side + ".log")).open("w", encoding="utf-8")
            logs.append(log)
            child = subprocess.Popen([args.blender, "--background", "--factory-startup", "--disable-autoexec",
                "--threads", "2", "--python", str(Path(__file__).with_name("network_" + side + ".py")),
                "--", str(folder)], env=env, stdout=log, stderr=subprocess.STDOUT,
                startupinfo=startup, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            procs.append(child)
            (out / "owned-processes.json").write_text(json.dumps([p.pid for p in procs]))
            if side == "host":
                deadline = time.monotonic() + 35
                while not (folder / "ready.json").exists():
                    if child.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("Native Host failed to start; see host.log")
                    time.sleep(.1)
                if args.relay:
                    sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))
                    from run_p3_client import _bridges
                    ready = json.loads((folder / "ready.json").read_text())
                    token = json.loads((folder / "config.json").read_text())["token"]
                    bridges, ready["port"] = _bridges(args.relay, token, ready["port"], out)
                    (folder / "ready.json").write_text(json.dumps(ready))
            else:
                child.wait(timeout=250)
        for name in ("client-result.json", "host-result.json", "client-error.txt", "host-error.txt"):
            source = folder / name
            if source.exists():
                (out / name).write_bytes(source.read_bytes())
        result = json.loads((out / "client-result.json").read_text())
        assert result["passed"], result
        procs[0].wait(timeout=10)
        print(json.dumps(result, indent=2))
    finally:
        for child in [*bridges, *procs]:
            if child.poll() is None:
                child.terminate()  # only exact disposable processes created above
                child.wait(timeout=10)
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()

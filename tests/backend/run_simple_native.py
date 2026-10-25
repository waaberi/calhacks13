"""Launch only owned disposable GUI Blenders for native Client object checks."""
import argparse
import json
import os
import secrets
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--store", nargs=2)
    parser.add_argument("--relay", nargs=2)
    parser.add_argument("--keyboard-events", action="store_true",
                        help="Also dispatch Ctrl+Z through this test window; needs active GUI keymap dispatch")
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    folder = out / "private"
    folder.mkdir()  # Fresh evidence only: never reuse stale ready/results or private credentials.
    config = {"token": secrets.token_hex(24), "scale": 1.0, "test_timeout": 190,
              "store": args.store, "keyboard_events": args.keyboard_events}
    (folder / "config.json").write_text(json.dumps(config))
    scripts = Path(__file__).parent
    startup = None
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    procs = []
    bridges = []
    logs = []
    try:
        for side in ("host", "client"):
            for suffix in ("temp", "profile"):
                (folder / f"{side}-{suffix}").mkdir(exist_ok=True)
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith("BLENDER_USER_")}
            env.update(BLENDER_USER_RESOURCES=str(folder / f"{side}-profile"),
                       TEMP=str(folder / f"{side}-temp"), TMP=str(folder / f"{side}-temp"),
                       PYTHONDONTWRITEBYTECODE="1")
            args_ = [args.blender, "--factory-startup", "--disable-autoexec", "--threads", "2"]
            if side == "client":
                args_.append("--enable-event-simulate")
                if args.keyboard_events:
                    # The first-run Quick Setup popup consumes normal keyboard
                    # events. Seed preferences only in this disposable profile.
                    with (out / "client-profile-bootstrap.log").open("w") as bootstrap_log:
                        subprocess.run([args.blender, "--background", "--factory-startup",
                            "--disable-autoexec", "--threads", "2", "--python-expr",
                            "import bpy; bpy.context.preferences.view.show_splash=False; "
                            "bpy.ops.wm.save_userpref()"], env=env, stdout=bootstrap_log,
                            stderr=subprocess.STDOUT, startupinfo=startup, timeout=25,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
                    args_.remove("--factory-startup")
            log = (out / f"{side}.log").open("w", encoding="utf-8")
            logs.append(log)
            p = subprocess.Popen([*args_, "--python", str(scripts / f"simple_native_{side}_check.py"),
                                  "--", str(folder)], env=env, stdout=log,
                                 stderr=subprocess.STDOUT, startupinfo=startup,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            procs.append(p)
            (out / "owned-processes.json").write_text(json.dumps([p.pid for p in procs]))
            if side == "host":
                deadline = time.monotonic() + 40
                while not (folder / "ready.json").exists():
                    if p.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Disposable host failed to become ready")
                    time.sleep(.05)
                if args.relay:
                    from run_p3_client import _bridges
                    ready = json.loads((folder / "ready.json").read_text())
                    bridges, ready["port"] = _bridges(args.relay, config["token"], ready["port"], out)
                    (folder / "ready.json").write_text(json.dumps(ready))
            else:
                p.wait(timeout=170)
        for name in ["client-result.json", "host-result.json", "client-error.txt", "host-error.txt"]:
            path = folder / name
            if path.exists():
                (out / name).write_bytes(path.read_bytes())
        if not (out / "client-result.json").exists():
            raise RuntimeError("Native Client checks failed; see preserved log/error")
        assert json.loads((out / "client-result.json").read_text())["passed"]
        procs[0].wait(timeout=10)
        print((out / "client-result.json").read_text())
    finally:
        for proc in [*bridges, *procs]:
            if proc.poll() is None:
                proc.terminate()  # Only exact Popen processes created above.
                proc.wait(timeout=10)
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()

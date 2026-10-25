"""Create/edit/Undo/Redo/reopen original native data in owned factory Blenders."""
import argparse
import json
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    private = out / "private"
    private.mkdir()
    startup = None
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    script = Path(__file__).with_name("native_fixture_gate.py")
    for phase in ("create", "reopen"):
        for name in ("temp", "profile"):
            (private / (phase + "-" + name)).mkdir()
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("BLENDER_USER_")}
        env.update(SPATIAL_NATIVE_SYNC_TEST="1", PYTHONDONTWRITEBYTECODE="1",
                   TEMP=str(private / (phase + "-temp")), TMP=str(private / (phase + "-temp")),
                   BLENDER_USER_RESOURCES=str(private / (phase + "-profile")))
        command = [args.blender, "--factory-startup", "--disable-autoexec", "--threads", "2"]
        if phase == "reopen":
            command.append(str(out / "client-edited.blend"))
        command += ["--python", str(script), "--", "--output", str(out)]
        if phase == "reopen":
            command.append("--reopen")
        with (out / (phase + ".log")).open("w", encoding="utf-8") as log:
            child = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                startupinfo=startup, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            (out / (phase + "-process.json")).write_text(json.dumps({"pid": child.pid, "command": command}))
            try:
                child.wait(timeout=60)
            finally:
                if child.poll() is None:
                    child.terminate()  # Only this launcher's exact owned disposable process.
                    child.wait(timeout=10)
        result_path = out / ("fixture-result.json" if phase == "create" else "reopen-result.json")
        result = json.loads(result_path.read_text())
        print(json.dumps(result, indent=2), flush=True)
        assert child.returncode == 0 and result["passed"], "See preserved native fidelity error"


if __name__ == "__main__":
    main()

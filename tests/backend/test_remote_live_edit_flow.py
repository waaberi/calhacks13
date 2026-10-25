"""Runs live_edit_flow_check.py (fake bpy, so it works in CI) in its own process."""
import subprocess
import sys
from pathlib import Path


def test_live_edit_flow():
    script = Path(__file__).with_name("live_edit_flow_check.py")
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=False,
                          cwd=script.parent, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr

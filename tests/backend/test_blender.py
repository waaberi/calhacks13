"""Run blender_check.py in real Blender: the bpy module when installed, GUI Blender when $BLENDER is set.

Both are skipped in CI. The GUI run briefly opens a Blender window:
  BLENDER=/path/to/blender pytest tests/backend/test_blender.py
"""

import importlib.util
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

CHECK = Path(__file__).with_name("blender_check.py")


def run_check(cmd, tmp_path):
    try:
        socket.create_connection(("127.0.0.1", 8765), timeout=1).close()
        pytest.skip("port 8765 is in use; is a Host-role Blender running?")
    except OSError:
        pass
    env = {**os.environ, "BLENDER_USER_RESOURCES": str(tmp_path)}  # keep real prefs untouched
    result = subprocess.run(cmd, check=False, env=env, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(importlib.util.find_spec("bpy") is None, reason="needs the bpy module")
def test_addon_in_bpy_module(tmp_path):
    run_check([sys.executable, str(CHECK)], tmp_path)


@pytest.mark.skipif(not os.environ.get("BLENDER"), reason="set BLENDER=/path/to/blender")
def test_addon_in_gui_blender(tmp_path):
    run_check([os.environ["BLENDER"], "--factory-startup", "--python", str(CHECK)], tmp_path)

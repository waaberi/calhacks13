"""Run blender_check.py in real Blender: the bpy module when installed, GUI Blender when $BLENDER is set.

Both are skipped in CI. The GUI run briefly opens a Blender window:
  BLENDER=/path/to/blender pytest tests/backend/test_blender.py

Afterwards every message the add-on sent is checked against contracts/schemas.
"""

import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_contracts import REGISTRY, SCHEMAS

CHECK = Path(__file__).with_name("blender_check.py")
SENT = {"welcome", "scene.snapshot", "scene.update", "session.update", "error", "pong", "result",
        "activity", "receipts"}


def run_check(cmd, tmp_path):
    for port in (8765, 8767):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            pytest.skip(f"port {port} is in use; is a Host-role Blender running?")
        except OSError:
            pass
    messages = tmp_path / "messages.jsonl"
    env = {
        **os.environ,
        "BLENDER_USER_RESOURCES": str(tmp_path / "blender"),  # keep real prefs untouched
        "SPATIAL_MODELING_CHECK_MESSAGES": str(messages),
    }
    result = subprocess.run(cmd, check=False, env=env, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr

    received = [json.loads(line) for line in messages.read_text("utf-8").splitlines()]
    for msg in received:
        if msg["type"] in SCHEMAS:  # not test.done, the check's own handler
            Draft202012Validator(SCHEMAS[msg["type"]], registry=REGISTRY).validate(msg)
    assert SENT <= {msg["type"] for msg in received}


@pytest.mark.skipif(importlib.util.find_spec("bpy") is None, reason="needs the bpy module")
def test_addon_in_bpy_module(tmp_path):
    run_check([sys.executable, str(CHECK)], tmp_path)


@pytest.mark.skipif(not os.environ.get("BLENDER"), reason="set BLENDER=/path/to/blender")
def test_addon_in_gui_blender(tmp_path):
    run_check([os.environ["BLENDER"], "--factory-startup", "--python", str(CHECK)], tmp_path)

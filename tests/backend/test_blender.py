"""Run blender_check.py in real Blender: the bpy module when installed, GUI Blender when $BLENDER is set.

Both are skipped in CI. The GUI runs briefly open a Blender window:
  BLENDER=/path/to/blender pytest tests/backend/test_blender.py
The gate check (gate_check.py) simulates input in GUI Blender with a pointer:
  BLENDER_EVENTS=/path/to/blender pytest tests/backend/test_blender.py -k gate

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
GATE_CHECK = Path(__file__).with_name("gate_check.py")
VOICE_CHECK = Path(__file__).with_name("voice_blender_check.py")
SENT = {"welcome", "scene.snapshot", "scene.update", "session.update", "error", "pong", "result",
        "activity", "receipts", "lease.granted"}


def run_check(cmd, tmp_path, sent=SENT, timeout=180):
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
    result = subprocess.run(cmd, check=False, env=env, capture_output=True, text=True,
                            timeout=timeout)
    assert result.returncode == 0, result.stdout + result.stderr

    received = [json.loads(line) for line in messages.read_text("utf-8").splitlines()]
    for msg in received:
        if msg["type"] in SCHEMAS:  # not test.done, the check's own handler
            Draft202012Validator(SCHEMAS[msg["type"]], registry=REGISTRY).validate(msg)
    assert sent <= {msg["type"] for msg in received}


@pytest.mark.skipif(importlib.util.find_spec("bpy") is None, reason="needs the bpy module")
def test_addon_in_bpy_module(tmp_path):
    run_check([sys.executable, str(CHECK)], tmp_path)


@pytest.mark.skipif(not os.environ.get("BLENDER"), reason="set BLENDER=/path/to/blender")
def test_addon_in_gui_blender(tmp_path):
    run_check([os.environ["BLENDER"], "--factory-startup", "--python", str(CHECK)], tmp_path)


@pytest.mark.skipif(not os.environ.get("BLENDER_EVENTS"),
                    reason="set BLENDER_EVENTS=/path/to/blender on a display with a pointer")
def test_gate_in_gui_blender(tmp_path):
    """Real key presses and clicks while a VR client holds a lease (#77); see gate_check.py.

    BLENDER_EVENTS is a GUI Blender on a display with a pointer device (a desktop, or
    Xwayland): on a headless Wayland display without one Blender crashes when it changes
    the cursor.
    """
    run_check([os.environ["BLENDER_EVENTS"], "--factory-startup", "--enable-event-simulate",
               "--python", str(GATE_CHECK)], tmp_path, timeout=300,
              sent={"welcome", "scene.snapshot", "scene.update", "session.update", "result",
                    "lease.granted"})


@pytest.mark.skipif(not os.environ.get("BLENDER"), reason="set BLENDER=/path/to/blender")
def test_voice_in_gui_blender(tmp_path):
    """Every voice operation through commands.py, Undo, selection and the mesh budget."""
    run_check([os.environ["BLENDER"], "--factory-startup", "--python", str(VOICE_CHECK)],
              tmp_path, timeout=600,
              sent={"welcome", "scene.snapshot", "scene.update", "session.update", "pong",
                    "result", "activity", "voice.candidates"})

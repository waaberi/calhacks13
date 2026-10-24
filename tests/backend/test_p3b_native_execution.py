"""Opt-in real Blender lease lifetime during a real native command."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_contracts import REGISTRY, SCHEMAS


@pytest.mark.skipif(not os.environ.get("P3B_EXECUTION_BLENDER"),
                    reason="set P3B_EXECUTION_BLENDER for actual GUI native execution")
@pytest.mark.parametrize("mode", ["disconnect", "timeout"])
def test_lease_lives_through_actual_native_execution(mode, tmp_path):
    root = Path(os.environ.get("P3B_EXECUTION_EVIDENCE", tmp_path)) / mode
    root.mkdir(parents=True, exist_ok=True)
    assert not any((root / name).exists() for name in ("result.json", "stdout.log")), (
        "Choose a fresh evidence directory; existing runs are preserved")
    env = {**os.environ, "P3B_EXECUTION_MODE": mode, "P3B_EXECUTION_OUTPUT": str(root),
           "BLENDER_USER_RESOURCES": str(root / "blender-resources")}
    startup = None
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    result = subprocess.run([os.environ["P3B_EXECUTION_BLENDER"], "--factory-startup", "--python",
        str(Path(__file__).with_name("p3b_native_execution_check.py"))], env=env,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=90,
        startupinfo=startup)
    (root / "stdout.log").write_text(result.stdout + result.stderr, "utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((root / "result.json").read_text("utf-8"))
    assert report["status"] == "PASS", report.get("error")
    assert report["source_unchanged_during_run"]
    assert report["harness_sha256"] == report["harness_sha256_after"]
    for peer in report["peers"]:
        for msg in peer["messages"]:
            Draft202012Validator(SCHEMAS[msg["type"]], registry=REGISTRY).validate(msg)

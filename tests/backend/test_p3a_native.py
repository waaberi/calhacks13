"""Opt-in actual Blender P3A proof, using unique resources and ephemeral ports.

Set P3A_BLENDER to a Blender executable. P3A_EVIDENCE_ROOT optionally preserves
the .blend, stdout and raw protocol report outside pytest's temporary folder.
No live application, default port or existing Blender preferences are used.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_contracts import REGISTRY, SCHEMAS

CHECK = Path(__file__).with_name("p3a_native_check.py")


@pytest.mark.skipif(not os.environ.get("P3A_BLENDER"), reason="set P3A_BLENDER for real Blender")
@pytest.mark.parametrize("unit_scale", [1.0, 0.001], ids=["meters", "millimeters"])
def test_real_p3a_native_transactions(unit_scale, tmp_path):
    root = Path(os.environ.get("P3A_EVIDENCE_ROOT", tmp_path))
    output = root / f"scale-{unit_scale}"
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "BLENDER_USER_RESOURCES": str(output / "blender-resources"),
           "P3A_OUTPUT_DIR": str(output), "P3A_UNIT_SCALE": str(unit_scale)}
    cmd = [os.environ["P3A_BLENDER"], "--factory-startup", "--python", str(CHECK)]
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          env=env, timeout=300, check=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    (output / "stdout.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads((output / "result.json").read_text("utf-8"))
    assert result["outcome"] == "pass", result.get("error")
    assert result["source_unchanged_during_run"], "implementation changed during run; rerun"
    for msg in result["messages"]:
        Draft202012Validator(SCHEMAS[msg["type"]], registry=REGISTRY).validate(msg)
    assert len(result["checks"]) == 8
    assert result["physical_headset"] == "not tested"
    assert result["second_pc"] == "not tested"

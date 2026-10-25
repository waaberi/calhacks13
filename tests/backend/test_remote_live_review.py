"""Run independent Client event-ordering and cancellation regressions in isolation."""
import subprocess
import sys
from pathlib import Path


def test_client_live_review_regressions():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("live_edit_review_check.py"))],
        check=False, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

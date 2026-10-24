"""Pure runner outcome gates; never imports bpy or launches a native process."""

import pytest
from run_native_preview_navigation import classify_result, classify_run


def test_pending_panel_observation_is_explicit_and_not_a_pass():
    assert classify_result({"required_passed": True, "pending": ["Toolbar background property incomplete"]}) == "pending"


def test_required_failure_cannot_be_hidden_by_optional_pending():
    assert classify_result({"required_passed": False, "pending": ["Sidebar background property incomplete"]}) == "failed"


def test_complete_required_result_without_pending_passes():
    assert classify_result({"required_passed": True, "pending": []}) == "passed"


def test_missing_or_malformed_native_result_cannot_be_a_pass():
    assert classify_result({}) == "failed"
    assert classify_result({"passed": True}) == "failed"


@pytest.mark.parametrize("process_exit,sources_unchanged,bytecode_unchanged", [
    (1, True, True), (0, False, True), (0, True, False),
])
def test_native_success_cannot_override_failed_process_or_isolation(process_exit, sources_unchanged, bytecode_unchanged):
    assert classify_run({"required_passed": True, "pending": []}, process_exit=process_exit,
                        sources_unchanged=sources_unchanged, bytecode_unchanged=bytecode_unchanged) == "failed"


def test_clean_run_preserves_pending_native_observations():
    assert classify_run({"required_passed": True, "pending": ["missing editor"]}, process_exit=0,
                        sources_unchanged=True, bytecode_unchanged=True) == "pending"


def test_clean_complete_native_run_passes():
    assert classify_run({"required_passed": True, "pending": []}, process_exit=0,
                        sources_unchanged=True, bytecode_unchanged=True) == "passed"

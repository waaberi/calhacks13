"""Pure runner outcome gates; never imports bpy or launches a native process."""

from run_native_preview_navigation import classify_result


def test_pending_panel_observation_is_explicit_and_not_a_pass():
    assert classify_result({"required_passed": True, "pending": ["Toolbar background property incomplete"]}) == "pending"


def test_required_failure_cannot_be_hidden_by_optional_pending():
    assert classify_result({"required_passed": False, "pending": ["Sidebar background property incomplete"]}) == "failed"


def test_complete_required_result_without_pending_passes():
    assert classify_result({"required_passed": True, "pending": []}) == "passed"


def test_missing_or_malformed_native_result_cannot_be_a_pass():
    assert classify_result({}) == "failed"
    assert classify_result({"passed": True}) == "failed"

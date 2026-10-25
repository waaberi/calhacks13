"""Ownership display uses real lease identities without editing native objects."""

import ownership_state


def lease(actor, name, mode="shared", targets=("cube",)):
    return {"owner": {"actor_id": actor, "name": name}, "mode": mode, "targets": targets}


def test_linked_objects_and_missing_target_display():
    held = [lease("lee", "Lee Jae-yeon", targets=("cube", "linked", "deleted"))]
    assert ownership_state.markers(held, ("cube", "linked", "free")) == {
        "cube": ("Lee Jae-yeon",), "linked": ("Lee Jae-yeon",)}
    assert ownership_state.markers(held, ("cube",), "lee") == {}


def test_exclusive_marks_all_and_release_removes_feedback():
    held = [lease("talia", "Talia", "exclusive", ())]
    assert ownership_state.markers(held, ("cube", "sphere")) == {
        "cube": ("Talia",), "sphere": ("Talia",)}
    assert ownership_state.markers([], ("cube", "sphere")) == {}
    assert "wait for Apply" in ownership_state.activity_text(held, "host")


def test_real_participant_names_and_two_editor_notice():
    held = [lease("a", "Alex"), lease("b", "Talia", targets=("sphere",))]
    assert ownership_state.activity_text(held, "a") == "Two people are editing: Alex, Talia"
    assert ownership_state.activity_text(held[:1], "a") == ""
    assert ownership_state.activity_text(held[:1], "b") == "Alex is editing the pink objects"

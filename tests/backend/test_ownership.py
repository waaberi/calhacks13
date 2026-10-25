"""Ownership display uses real lease identities without editing native objects."""

import ownership_state


def lease(actor, name, mode="shared", targets=("cube",), role="blender-client"):
    return {"owner": {"actor_id": actor, "name": name, "role": role}, "mode": mode,
            "targets": targets}


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


def test_vr_owner_is_named_as_vr():
    vr = [lease("t", "Talia", role="vr")]
    assert ownership_state.activity_text(vr, "host") == "VR is editing: Talia"
    exclusive = [lease("t", "Talia", "exclusive", (), role="vr")]
    assert ownership_state.activity_text(exclusive, "host") == "VR is editing: Talia — wait for Apply"
    assert ownership_state.activity_text(vr, "t") == ""


def test_object_label_uses_the_owner_names():
    assert ownership_state.object_label(("Alex",)) == "Alex is editing this object"
    assert ownership_state.object_label(("Alex", "Talia")) == "Alex, Talia are editing this object"


def test_connection_lost_only_when_the_link_is_gone():
    lost = {
        "Disconnected — reconnecting; last scene is stale":
            "Connection lost — Disconnected — reconnecting; last scene is stale",
        "Host is not responding — last scene is stale":
            "Connection lost — Host is not responding — last scene is stale",
        "Connection stopped — reconnect explicitly; last scene is stale":
            "Connection lost — Connection stopped — reconnect explicitly; last scene is stale",
        "Connection lost — edits disabled": "Connection lost — edits disabled",
    }
    for status, text in lost.items():
        assert ownership_state.connection_text(status) == text
    for status in ("Connected — bracket.blend, revision 3 — read-only",
                   "Listening on 127.0.0.1:8765", "Connecting — last scene is stale", "", None):
        assert ownership_state.connection_text(status) == ""

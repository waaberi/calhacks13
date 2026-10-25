"""Sketch dispatch uses the existing transaction, revision and receipt boundary."""

from commands import Applied, Refused
from test_commands import SKETCH, FakeEditor, assert_rejected, hosting


class SketchEditor(FakeEditor):
    supports_sketches = True

    def generation(self, object_id):
        return 0 if object_id == SKETCH else super().generation(object_id)

    def apply(self, op, target, args):
        assert self.session.committing
        assert op == "sketch.add_circle"
        if args["radius"] > 1:
            raise Refused("solver_conflict", "The constraint conflicts with the sketch.",
                          solver={"status": "conflicting", "dof": None})
        self.applied.append((op, target, args))
        return Applied("Added circle", ["circle_1"], self.revision,
                       solver={"status": "free", "dof": 3})


def test_applied_and_refused_solver_state_reaches_schema_valid_receipt():
    editor = SketchEditor()
    with hosting(editor=editor) as host, host.vr() as vr:
        applied = vr.run("sketch.add_circle", SKETCH, {"center": [0, 0], "radius": 0.01})
        assert applied["solver"] == {"status": "free", "dof": 3}
        assert applied["created"] == ["circle_1"]
        refused = vr.run("sketch.add_circle", SKETCH, {"center": [0, 0], "radius": 2})
        assert_rejected(refused, "solver_conflict")
        assert refused["solver"] == {"status": "conflicting", "dof": None}
        assert len(host.editor.applied) == 1
        assert vr.query(applied["request_id"], refused["request_id"])["receipts"] == [
            applied, refused]


def test_sketch_capability_is_explicitly_disabled_by_default():
    with hosting() as host, host.vr() as vr:
        assert vr.welcome["capabilities"] == {"sketch": False}


def test_native_capability_callback_is_advertised_at_handshake():
    with hosting(capabilities=lambda: {"sketch": True}) as host, host.vr() as vr:
        assert vr.welcome["capabilities"] == {"sketch": True}

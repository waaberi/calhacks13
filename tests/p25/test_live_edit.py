"""Live authority/ordering/failure tests, independent of Blender and rendering."""

import copy
import importlib
import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "native_live_unit"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "blender_addon" / "spatial_modeling")]
sys.modules.setdefault(PACKAGE, package)
live = importlib.import_module(PACKAGE + ".live_edit")
sessions = importlib.import_module(PACKAGE + ".session")
leases_module = importlib.import_module(PACKAGE + ".leases")
OID = "a" * 32


@pytest.fixture
def fixture():
    document = {"id": uuid.uuid4().hex, "open_epoch": uuid.uuid4().hex, "revision": 0, "name": "isolated.blend"}
    value = {"geometry": 0, "native_selection": 0, "published": 0, "generation": 0, "revision": 0,
             "undo": 0, "step": "preexisting", "context": {"mode": "OBJECT", "native_tool": "builtin.move"}}
    class Editor:
        sync = None
        def flush(self):
            if value["geometry"] != value["published"]:
                value["revision"] += 1
                value["generation"] = value["revision"]
                value["published"] = value["geometry"]
            return value["revision"]
        def generation(self, oid):
            return value["generation"] if oid == OID else None
        def linked(self, ids):
            return ids
        def _published(self, fn):
            def run(obj, args):
                done = fn(obj, args)
                value["step"] = done.summary
                done.revision = self.flush()
                return done
            return run
    editor = Editor()
    editor.sync = editor
    sess = sessions.Session(lambda: dict(document, revision=value["revision"]), lambda _doc: {}, uuid.uuid4().hex)
    lses = leases_module.Leases(sess, editor)
    class Connection:
        can_edit = True
        def __init__(self):
            self.messages = []
        def send(self, message):
            self.messages.append(message)
    conn, other = Connection(), Connection()
    actors = []
    for c in (conn, other):
        actor = {"actor_id": uuid.uuid4().hex, "name": "Isolated unit", "role": "vr"}
        actors.append(actor)
        sess.participants[c] = actor
        sess.store.join(actor)
    class Baseline:
        def __init__(self, _sync, _ids):
            self.geometry, self.selection = value["geometry"], value["native_selection"]
        def restore(self):
            value["geometry"], value["native_selection"] = self.geometry, self.selection
        def close(self):
            pass
    def apply(_editor, operation, parameters):
        if operation.get("selection_only"):
            value["native_selection"] = 42
        else:
            value["geometry"] += parameters["amount"]
        if parameters.get("fail"):
            raise live.commands.Refused("failed", "Injected after real fake-data mutation")
        return live.commands.Applied("Owned live edit", selection={"id": OID})
    def undoable(_name):
        def wrap(fn):
            def run(*args):
                result = fn(*args)
                value["undo"] += 1
                return result
            return run
        return wrap
    clock = [0.0]
    manager = live.LiveEdits(sess, editor, lses, undoable,
                            kernel=NS(validate_live=lambda *_: None, apply_live=apply),
                            baseline=Baseline, context=lambda: copy.deepcopy(value["context"]),
                            clock=lambda: clock[0])
    def identity(c=conn):
        return {"session_id": sess.session_id, "host_epoch": sess.host_epoch,
                "document_id": document["id"], "open_epoch": document["open_epoch"],
                "actor_id": sess.participants[c]["actor_id"]}
    def ask(action, c=conn, request_id=None, **payload):
        msg = {"v": 1, "type": "live.edit." + action, "id": request_id or uuid.uuid4().hex,
               "payload": identity(c) | payload}
        return manager.handler(action)(msg, c)
    def begin(operation=None):
        lease = lses.grant(actors[0]["actor_id"], "exclusive")
        return ask("begin", base_revision=editor.flush(), lease=lease["lease_id"],
                   targets=[{"id": OID, "generation": editor.generation(OID)}],
                   operation=operation or {"tool": "object.move", "target_id": OID})
    box = NS(manager=manager, value=value, clock=clock, ask=ask, begin=begin,
             conn=conn, other=other, session=sess, editor=editor, leases=lses)
    try:
        yield box
    finally:
        manager.stop()


def token(f):
    result = f.begin()
    assert result["type"] == "live.edit.state", result
    return result["payload"]["edit_session_id"]


def test_updates_are_live_cumulative_and_one_final_history_step(fixture):
    f = fixture
    edit = token(f)
    for seq, amount in ((1, 2), (2, 5)):
        result = f.ask("update", edit_session_id=edit, sequence=seq, parameters={"amount": amount})
        assert result["payload"]["phase"] == "updated"
        assert f.value["geometry"] == amount
        assert f.value["undo"] == 0
    result = f.ask("commit", edit_session_id=edit, sequence=2)
    assert result["payload"]["phase"] == "committed"
    assert f.value["geometry"] == 5 and f.value["undo"] == 1
    assert not live.is_active()


def test_cancel_restores_exact_baseline_without_history(fixture):
    f = fixture
    edit = token(f)
    f.ask("update", edit_session_id=edit, sequence=1, parameters={"amount": 5})
    result = f.ask("cancel", edit_session_id=edit, reason="Explicit cancel")
    assert result["payload"]["phase"] == "cancelled"
    assert f.value["geometry"] == f.value["undo"] == 0
    assert f.value["step"] == "preexisting"


def test_selection_only_commit_never_pushes_undo_or_changes_step(fixture):
    f = fixture
    result = f.begin({"tool": "object.selection", "selection_only": True})
    edit = result["payload"]["edit_session_id"]
    f.ask("update", edit_session_id=edit, sequence=1, parameters={})
    result = f.ask("commit", edit_session_id=edit, sequence=1)
    assert result["payload"]["phase"] == "committed"
    assert f.value["native_selection"] == 42
    assert f.value["undo"] == f.value["geometry"] == f.value["revision"] == 0
    assert f.value["step"] == "preexisting"


def test_sequence_replay_deduplicates_and_changed_payload_is_refused(fixture):
    f = fixture
    edit = token(f)
    rid = uuid.uuid4().hex
    first = f.ask("update", request_id=rid, edit_session_id=edit, sequence=1, parameters={"amount": 5})
    assert f.ask("update", request_id=rid, edit_session_id=edit, sequence=1, parameters={"amount": 5}) == first
    assert f.value["geometry"] == 5
    assert f.ask("update", request_id=rid, edit_session_id=edit, sequence=1, parameters={"amount": 7})["payload"]["code"] == "duplicate_request"
    assert f.ask("update", edit_session_id=edit, sequence=3, parameters={"amount": 7})["payload"]["code"] == "duplicate_request"


def test_foreign_connection_and_commands_cannot_use_owned_live_session(fixture):
    f = fixture
    edit = token(f)
    result = f.ask("update", c=f.other, edit_session_id=edit, sequence=1, parameters={"amount": 5})
    assert result["payload"]["code"] == "permission_denied"
    with pytest.raises(live.commands.Refused, match="live controller gesture"):
        live.ensure_no_active()
    assert f.value["geometry"] == 0


def test_failed_sample_restores_last_acknowledged_geometry(fixture):
    f = fixture
    edit = token(f)
    f.ask("update", edit_session_id=edit, sequence=1, parameters={"amount": 3})
    result = f.ask("update", edit_session_id=edit, sequence=2, parameters={"amount": 9, "fail": True})
    assert result["payload"]["code"] == "failed"
    assert f.value["geometry"] == 3 and f.manager.current["sequence"] == 1
    assert f.value["undo"] == 0


def test_external_geometry_is_never_overwritten_by_cancel(fixture):
    f = fixture
    edit = token(f)
    f.ask("update", edit_session_id=edit, sequence=1, parameters={"amount": 3})
    f.value["geometry"] = 99
    result = f.ask("cancel", edit_session_id=edit)
    assert result["payload"]["phase"] == "conflict"
    assert f.value["geometry"] == 99 and f.value["undo"] == 0


def test_tool_change_refuses_next_update_but_cancel_restores_owned_geometry(fixture):
    f = fixture
    edit = token(f)
    f.ask("update", edit_session_id=edit, sequence=1, parameters={"amount": 3})
    f.value["context"]["native_tool"] = "builtin.rotate"
    assert f.ask("update", edit_session_id=edit, sequence=2, parameters={"amount": 5})["payload"]["code"] == "stale_revision"
    assert f.ask("cancel", edit_session_id=edit)["payload"]["phase"] == "cancelled"
    assert f.value["geometry"] == 0


def test_timeout_restores_geometry_and_releases_ordinary_lease(fixture):
    f = fixture
    edit = token(f)
    f.ask("update", edit_session_id=edit, sequence=1, parameters={"amount": 3})
    f.clock[0] = 16
    f.manager.poll()
    assert f.value["geometry"] == 0 and not f.session.store.leases()
    assert f.conn.messages[-1]["payload"]["phase"] == "cancelled"

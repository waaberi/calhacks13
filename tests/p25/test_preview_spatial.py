"""Native preview admission and unsupported-sketch isolation, without bpy/socket/UI."""

import importlib
import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "p25_spatial_backend"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT / "blender_addon" / "spatial_modeling")]
    sys.modules[PACKAGE] = package

native = importlib.import_module(PACKAGE + ".preview_spatial")
session_module = importlib.import_module(PACKAGE + ".session")
leases_module = importlib.import_module(PACKAGE + ".leases")


class Connection:
    def __init__(self, can_edit=True):
        self.can_edit = can_edit


@pytest.fixture
def setup():
    document = {"id": uuid.uuid4().hex, "open_epoch": uuid.uuid4().hex, "revision": 0, "name": "copy.blend"}
    session = session_module.Session(lambda: document, lambda doc: {}, uuid.uuid4().hex)
    editor = NS(linked=lambda ids: [])
    leases = leases_module.Leases(session, editor)
    window = NS(modal_operators=[])
    context = NS(window_manager=NS(windows=[window]))
    ui = native.NativePreviewSessions(session, leases, lambda: context)
    connections = [Connection(), Connection()]
    for index, conn in enumerate(connections):
        actor = {"actor_id": uuid.uuid4().hex, "name": f"VR {index}", "role": "vr"}
        session.participants[conn] = actor
        session.store.join(actor)
    def request(conn=connections[0], end=False):
        msg = {"id": uuid.uuid4().hex, "payload": {
            "session_id": session.session_id, "host_epoch": session.host_epoch,
            "document_id": document["id"], "open_epoch": document["open_epoch"],
            "actor_id": session.participants[conn]["actor_id"]}}
        if end:
            msg["payload"]["ui_session_id"] = ui.token
        return msg
    return NS(ui=ui, session=session, leases=leases, window=window, context=context,
              a=connections[0], b=connections[1], request=request)


def test_host_desktop_lease_admits_native_input_and_blocks_other_supported_writers(setup):
    s = setup
    assert not s.ui.state(s.a)["input_allowed"]
    reply = s.ui.begin(s.request(), s.a)
    assert reply["type"] == "preview.ui.granted"
    assert reply["payload"]["input_allowed"]
    lease = s.session.store.leases()[0]
    assert lease["owner"] == s.session.host
    assert lease["mode"] == "exclusive"
    assert s.leases.may_write([], whole=True) is None
    assert s.leases.check(s.session.participants[s.b]["actor_id"], "object.add")[0] == "lease_conflict"
    assert not s.ui.state(s.b)["input_allowed"]
    assert s.ui.begin(s.request(s.b), s.b)["payload"]["code"] == "lease_conflict"


@pytest.mark.parametrize("field", ["actor_id", "document_id", "open_epoch", "session_id", "host_epoch"])
def test_wrong_identity_never_grants(setup, field):
    s = setup
    msg = s.request()
    msg["payload"][field] = uuid.uuid4().hex
    assert s.ui.begin(msg, s.a)["type"] == "error"
    assert s.session.store.leases() == []


def test_readonly_cannot_request_raw_ui(setup):
    s = setup
    s.a.can_edit = False
    assert s.ui.begin(s.request(), s.a)["payload"]["code"] == "permission_denied"


def test_modal_at_begin_is_refused_without_any_lease(setup):
    s = setup
    s.window.modal_operators = [NS(bl_idname="TRANSFORM_OT_translate")]
    assert s.ui.begin(s.request(), s.a)["payload"]["code"] == "busy"
    assert not s.session.store.leases()


def test_native_modal_keeps_reservation_after_explicit_end_then_releases(setup):
    s = setup
    s.ui.begin(s.request(), s.a)
    s.window.modal_operators = [NS(bl_idname="TRANSFORM_OT_translate")]
    reply = s.ui.end(s.request(end=True), s.a)
    assert reply["type"] == "preview.ui.ended"
    assert reply["payload"]["ui_ending"]
    assert not reply["payload"]["input_allowed"]
    assert len(s.session.store.leases()) == 1
    s.window.modal_operators = []
    s.ui.poll()
    assert not s.session.store.leases()
    assert s.ui.owner is None


def test_disconnect_does_not_release_while_native_tool_runs(setup):
    s = setup
    s.ui.begin(s.request(), s.a)
    s.window.modal_operators = [NS(bl_idname="SKETCHER_OT_line")]
    s.ui.disconnected(s.a)
    s.session.left(s.a)
    assert len(s.session.store.leases()) == 1  # belongs to host, not departed VR actor
    assert not s.ui.state(s.a)["input_allowed"]
    s.window.modal_operators = []
    s.ui.poll()
    assert not s.session.store.leases()


def test_same_connected_owner_can_resume_retained_modal_session(setup):
    s = setup
    s.ui.begin(s.request(), s.a)
    token, lease = s.ui.token, s.ui.lease
    s.window.modal_operators = [NS(bl_idname="TRANSFORM_OT_translate")]
    s.ui.end(s.request(end=True), s.a)
    assert s.ui.ending
    assert s.ui.begin(s.request(s.b), s.b)["payload"]["code"] == "lease_conflict"
    resumed = s.ui.begin(s.request(), s.a)
    assert resumed["payload"]["input_allowed"]
    assert not resumed["payload"]["ui_ending"]
    assert s.ui.token == token and s.ui.lease == lease
    assert len(s.session.store.leases()) == 1


def test_foreign_connection_cannot_end_the_ui_session(setup):
    s = setup
    s.ui.begin(s.request(), s.a)
    assert s.ui.end(s.request(s.b, end=True), s.b)["payload"]["code"] == "permission_denied"
    assert s.ui.state(s.a)["input_allowed"]


def test_existing_reservation_and_replayed_ended_begin_cannot_be_reused(setup):
    s = setup
    held = s.leases.grant(s.session.host["actor_id"], "exclusive")
    assert s.ui.begin(s.request(), s.a)["payload"]["code"] == "lease_conflict"
    s.leases.end(held["lease_id"], s.session.host["actor_id"])
    request = s.request()
    s.ui.begin(request, s.a)
    token = s.ui.token
    assert s.ui.begin(request, s.a)["payload"]["ui_session_id"] == token
    s.ui.end(s.request(end=True), s.a)
    assert s.ui.begin(request, s.a)["payload"]["code"] == "duplicate_request"


def test_our_gate_observer_does_not_count_as_an_active_edit(setup):
    s = setup
    s.window.modal_operators = [NS(bl_idname="SPATIAL_MODELING_OT_input_gate")]
    assert s.ui.begin(s.request(), s.a)["type"] == "preview.ui.granted"


def test_a_released_native_reservation_never_keeps_input_allowed(setup):
    s = setup
    s.ui.begin(s.request(), s.a)
    s.leases.end(s.ui.lease["lease_id"], s.session.host["actor_id"])
    assert not s.ui.state(s.a)["input_allowed"]
    assert s.ui.owner is None


def test_missing_modal_information_fails_closed(setup):
    s = setup
    del s.window.modal_operators
    assert s.ui.begin(s.request(), s.a)["payload"]["code"] == "busy"


def test_native_tool_and_unimplemented_options_are_reported(monkeypatch):
    monkeypatch.setattr(native.sketch, "dependency_status", lambda: {"available": True, "reason": ""})
    monkeypatch.setattr(native.sketch, "snapshot_problems", lambda: [{"id": "bad", "reason": "scaled plane"}])
    tool = NS(idname="sketcher.slvs_add_line2d", operator_properties=lambda op: NS(continuous_draw=True))
    window = NS(screen=NS(areas=[NS(type="VIEW_3D")]), workspace=NS(tools=NS(from_space_view3d_mode=lambda *a, **k: tool)))
    context = NS(mode="OBJECT", scene=NS(sketcher=NS(active_sketch_object=None, auto_axis_constraints=True, use_snap_project=True)), window_manager=NS(windows=[window]))
    state = native.read_state(context)
    assert state["tool"] == "line"
    assert state["unsupported_options"] == ["Continuous Draw", "Auto Constraints", "Live Project Snaps"]
    assert state["unsupported_sketches"] == [{"id": "bad", "reason": "scaled plane"}]


def test_unsupported_sketch_is_isolated_without_dropping_other_native_sketches(monkeypatch):
    fake_bpy = NS(context=NS(view_layer=NS(objects=[])))
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    monkeypatch.setitem(sys.modules, "mathutils", NS(Euler=object))
    adapter = importlib.import_module(PACKAGE + ".sketch.adapter")
    class Object(dict):
        type = "CURVES"
        name = "Sketch"
    good = Object(is_cad_sketch=True, spatial_modeling_id="good")
    bad = Object(is_cad_sketch=True, spatial_modeling_id="bad")
    fake_bpy.context.view_layer.objects = [bad, good]
    monkeypatch.setattr(adapter, "dependency_status", lambda: {"available": True})
    monkeypatch.setattr(adapter, "_api", dict)
    def record(obj, api):
        if obj is bad:
            raise ValueError("Unsupported scale/reflection")
        return {"id": obj["spatial_modeling_id"]}
    monkeypatch.setattr(adapter, "_record", record)
    assert adapter.snapshot() == [{"id": "good"}]
    assert adapter.snapshot_problems == [{"id": "bad", "name": "Sketch", "reason": "Unsupported scale/reflection"}]

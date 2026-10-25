"""Opt-in controlled remote move; the ordinary P2 mirror stays read-only.

A test tool: its panel and operators are registered only when Blender starts with
SPATIAL_MODELING_TEST_TOOLS=1 in the environment (run_p3_client.py sets it).
"""

import os
import queue
import threading

import bpy

from . import remote_control, session

_job = None
_results = queue.SimpleQueue()
_blocked_state = None
_blocked_request = None
_enum_cache = []
_last_outcome = None
_job_context = None
_registered = False
TEST_TOOLS_ENV = "SPATIAL_MODELING_TEST_TOOLS"


def cancel_before_send():
    """Also called synchronously by the mirror's disconnect path."""
    return bool(_job_context is not None and _job_context[3].cancel())


def _state():
    from . import remote_client
    return getattr(remote_client, "state", None)


def _prefs(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None else None


def _targets(_self, _context):
    global _enum_cache
    state = _state()
    _enum_cache = [("NONE", "Select a current host object", "")]
    if state is not None and state.current:
        _enum_cache += [(oid, record.get("name", oid), "Host object " + oid)
                        for oid, record in sorted(state.objects.items())]
    return _enum_cache


def run_controlled_move(config, document, target_id, generation, *, enabled=False,
                        on_event=None, cancelled=None):
    """The registered operator's worker entry point; contains no bpy access."""
    return remote_control.move_selected(config, document, target_id, generation,
                                        enabled=enabled, on_event=on_event, cancelled=cancelled)


def _finish():
    global _job, _job_context, _blocked_state, _blocked_request, _last_outcome
    if _job_context is not None:
        started, target, generation, cancellation = _job_context
        current = _state()
        if (current is not started or not current.current
                or current.objects.get(target, {}).get("generation") != generation):
            cancellation.cancel()
    try:
        outcome, started_state = _results.get_nowait()
    except queue.Empty:
        return 0.05
    _job = None
    _job_context = None
    _last_outcome = outcome
    wm = bpy.context.window_manager
    wm.spatial_remote_test_status = outcome.message
    if outcome.blocked:
        _blocked_state, _blocked_request = started_state, outcome.request_id
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    return None


class SPATIAL_OT_remote_move_test(bpy.types.Operator):
    """Request one host-confirmed +10 mm X move of the chosen mirrored object"""

    bl_idname = "spatial_modeling.remote_move_test"
    bl_label = "Move host object +10 mm X"
    target_id: bpy.props.StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        from . import remote_client
        state, prefs = _state(), _prefs(context)
        return (getattr(context.window_manager, "spatial_remote_test_enabled", False)
                and _job is None and _blocked_state is None and state is not None
                and state.current and prefs is not None and prefs.role == "CLIENT"
                and remote_client.controlled_edit_enabled()
                and all(hasattr(prefs, k) for k in ("client_address", "client_port",
                                                   "client_token", "client_tls")))

    def execute(self, context):
        global _job, _job_context, _last_outcome
        state, prefs = _state(), _prefs(context)
        if not self.poll(context):
            self.report({"WARNING"}, "Enable the test flag and connect a fresh Client mirror first.")
            return {"CANCELLED"}
        target = self.target_id or context.window_manager.spatial_remote_test_target
        if target == "NONE" and context.active_object is not None:
            target = context.active_object.get("spatial_modeling_id", "NONE")
        record = state.objects.get(target)
        if record is None:
            self.report({"WARNING"}, "Select a current host object in the test target list.")
            return {"CANCELLED"}
        config = remote_control.RemoteConfig(prefs.client_address, prefs.client_port,
            prefs.client_token, session.APP["version"], prefs.host_name or "Controlled Blender editor",
            prefs.client_tls)
        expected = {k: state.document[k] for k in ("id", "open_epoch")}
        generation = record["generation"]
        context.window_manager.spatial_remote_test_status = "Waiting for host confirmation…"
        _last_outcome = None
        cancellation = remote_control.MoveCancellation()
        _job_context = state, target, generation, cancellation

        def worker():
            outcome = run_controlled_move(config, expected, target, generation, enabled=True,
                                          cancelled=cancellation)
            _results.put((outcome, state))

        _job = threading.Thread(target=worker, name="Spatial controlled remote move", daemon=True)
        _job.start()
        if not bpy.app.timers.is_registered(_finish):
            bpy.app.timers.register(_finish, first_interval=0.05)
        return {"FINISHED"}  # only means queued; status remains pending until the native receipt


class SPATIAL_OT_remote_cancel_test(bpy.types.Operator):
    """Cancel the draft before its command is sent; a sent command needs a receipt"""

    bl_idname = "spatial_modeling.remote_cancel_test"
    bl_label = "Cancel before send"

    @classmethod
    def poll(cls, _context):
        return _job_context is not None and not _job_context[3].sent

    def execute(self, context):
        if not cancel_before_send():
            self.report({"WARNING"}, "Command already sent; wait for the host receipt.")
            return {"CANCELLED"}
        context.window_manager.spatial_remote_test_status = "Cancelling before native send…"
        return {"FINISHED"}


class SPATIAL_OT_remote_retry_after_reconnect(bpy.types.Operator):
    """Allow an explicit new request only after reconnecting and checking the host scene"""

    bl_idname = "spatial_modeling.remote_retry_after_reconnect"
    bl_label = "I checked the reconnected scene; allow a new request"

    @classmethod
    def poll(cls, _context):
        state = _state()
        return (_job is None and _blocked_state is not None and state is not None
                and state is not _blocked_state and state.current)

    def execute(self, context):
        global _blocked_state, _blocked_request
        if not self.poll(context):
            return {"CANCELLED"}
        _blocked_state = _blocked_request = None
        context.window_manager.spatial_remote_test_status = (
            "Fresh mirror verified. A new move requires another explicit button press.")
        return {"FINISHED"}


class SPATIAL_PT_remote_test(bpy.types.Panel):
    bl_label = "Controlled remote test"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Spatial"

    @classmethod
    def poll(cls, context):
        prefs = _prefs(context)
        return prefs is not None and prefs.role == "CLIENT"

    def draw(self, context):
        layout, wm = self.layout, context.window_manager
        layout.prop(wm, "spatial_remote_test_enabled", text="Enable controlled remote test")
        layout.label(text="Ordinary mirror remains read-only.")
        layout.label(text="Host must enable Client edits (test only).")
        state = _state()
        row = layout.column()
        row.enabled = bool(state is not None and state.current)
        row.prop(wm, "spatial_remote_test_target", text="Host object")
        row.operator(SPATIAL_OT_remote_move_test.bl_idname)
        if _job_context is not None:
            row.operator(SPATIAL_OT_remote_cancel_test.bl_idname)
        if state is None or not state.current:
            layout.label(text="Connect a fresh Client mirror first.", icon="ERROR")
        if _blocked_state is not None:
            layout.label(text="Unknown outcome — reconnect and inspect first.", icon="ERROR")
            if _blocked_request:
                layout.label(text="Request: " + _blocked_request)
            layout.operator(SPATIAL_OT_remote_retry_after_reconnect.bl_idname)
        if wm.spatial_remote_test_status:
            layout.label(text=wm.spatial_remote_test_status)


CLASSES = (SPATIAL_OT_remote_move_test, SPATIAL_OT_remote_cancel_test,
           SPATIAL_OT_remote_retry_after_reconnect,
           SPATIAL_PT_remote_test)


def register():
    global _registered
    if os.environ.get(TEST_TOOLS_ENV) != "1":
        return  # never in normal use: the fixed +10 mm move is only for the P3 checks
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.spatial_remote_test_enabled = bpy.props.BoolProperty(default=False, options={"SKIP_SAVE"})
    wm.spatial_remote_test_target = bpy.props.EnumProperty(items=_targets, options={"SKIP_SAVE"})
    wm.spatial_remote_test_status = bpy.props.StringProperty(options={"SKIP_SAVE"})
    _registered = True


def unregister():
    global _registered
    if not _registered:
        return
    # An already sent command must finish and keep its unknown-state latch. Refuse
    # unloading while it runs instead of discarding its result and allowing replay.
    if _job is not None:
        raise RuntimeError("Wait for the controlled remote command before disabling the add-on")
    if bpy.app.timers.is_registered(_finish):
        bpy.app.timers.unregister(_finish)
    for name in ("spatial_remote_test_enabled", "spatial_remote_test_target",
                 "spatial_remote_test_status"):
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _registered = False

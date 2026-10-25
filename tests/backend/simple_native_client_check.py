"""Real GUI Blender Client: native object operators plus production TLS authority.

This runs only in a disposable factory process launched by run_simple_native.py.
It uses Blender's own event queue for modal cancellation and native operators for
G/R/S/delete; it never types into or targets another running Blender window.
"""
import hashlib
import json
import math
import sys
import time
import traceback
import urllib.request
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
import spatial_modeling as addon
from spatial_modeling import remote_client as rc

folder = Path(sys.argv[sys.argv.index("--") + 1])
config = json.loads((folder / "config.json").read_text())
ready = json.loads((folder / "ready.json").read_text())
oid = ready["cube_id"]
checks = []
source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (ROOT / "blender_addon/spatial_modeling").rglob("*.py")}
modal_evidence = []
started = time.monotonic()
waiting = None
waiting_since = 0
_action_result = None


def obj():
    return rc._mirror.objects[oid]


def choose():
    bpy.ops.object.select_all(action="DESELECT")
    target = obj()
    target.hide_select = False
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    return target


def native(op, **kwargs):
    choose()
    if config.get("keyboard_events"):
        keys = {"translate": [("G", ""), ("X", ""), ("ZERO", "0"),
                              ("PERIOD", "."), ("ZERO", "0"), ("ONE", "1"), ("FIVE", "5")],
                "rotate": [("R", ""), ("Z", ""), ("FOUR", "4"), ("FIVE", "5")],
                "resize": [("S", ""), ("ONE", "1"), ("PERIOD", "."), ("FIVE", "5")]}
        region = bpy.context.region
        x, y = region.x + region.width // 2, region.y + region.height // 2
        window = bpy.context.window
        window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
        for key, char in [*keys[op], ("RET", "")]:
            window.event_simulate(type=key, value="PRESS", unicode=char, x=x, y=y)
            window.event_simulate(type=key, value="RELEASE", x=x, y=y)
        return
    assert getattr(bpy.ops.transform, op)(**kwargs) == {"FINISHED"}
    bpy.context.view_layer.update()


def action(name):
    global _action_result
    if config.get("control_url"):
        # Cross-OS disposable fixture control only. Edits use production TLS.
        request = urllib.request.Request(config["control_url"],
            data=json.dumps({"action": name}).encode(),
            headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=config.get("condition_timeout", 15)) as reply:
            _action_result = json.load(reply)["native"]
        return lambda: True
    (folder / "action-result.json").unlink(missing_ok=True)
    tmp = folder / "action-native.tmp"
    tmp.write_text(json.dumps({"action": name}))
    tmp.replace(folder / "action.json")
    return lambda: (folder / "action-result.json").exists()


def result():
    if config.get("control_url"):
        return _action_result
    return json.loads((folder / "action-result.json").read_text())["native"]


def idle():
    return (rc.edit_blocked() is None and not rc.live.sent and
            not rc.live.wait_revision and not rc.live.held)


def location(x, y=0):
    return abs(obj().location.x - x) < 1e-6 and abs(obj().location.y - y) < 1e-6


def history(op):
    if not config.get("keyboard_events"):
        assert getattr(bpy.ops.spatial_modeling, "client_" + op)() == {"FINISHED"}
        return
    region = bpy.context.region
    x, y = region.x + region.width // 2, region.y + region.height // 2
    window = bpy.context.window
    window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    window.event_simulate(type="LEFT_CTRL", value="PRESS", x=x, y=y, ctrl=True)
    if op == "redo":
        window.event_simulate(type="LEFT_SHIFT", value="PRESS", x=x, y=y, ctrl=True, shift=True)
    window.event_simulate(type="Z", value="PRESS", x=x, y=y, ctrl=True, shift=op == "redo")
    window.event_simulate(type="Z", value="RELEASE", x=x, y=y)
    window.event_simulate(type="LEFT_CTRL", value="RELEASE", x=x, y=y)
    if op == "redo":
        window.event_simulate(type="LEFT_SHIFT", value="RELEASE", x=x, y=y)


def history_done(op, before):
    return idle() and sum(r.op == "history." + op for r in rc.requests.requests.values()) > before


def seq():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    original_sync = addon.host.sync
    addon.host.sync = lambda: None
    bpy.context.preferences.addons.new().module = "spatial_modeling"
    addon.register()
    prefs = bpy.context.preferences.addons["spatial_modeling"].preferences
    prefs.role = "CLIENT"
    addon.host.sync = original_sync
    prefs.client_address, prefs.client_port = config.get("host_address", "127.0.0.1"), ready["port"]
    prefs.client_token, prefs.client_tls = config["token"], True
    assert bpy.ops.spatial_modeling.connect_readonly() == {"FINISHED"}
    yield lambda: rc.state.current
    assert not rc.controlled_edit_enabled() and obj().hide_select
    yield action("probe")
    assert result()["command_count"] == 0
    checks.append("permission false: actual welcome leaves mirror unselectable and host unchanged")
    yield action("flag_on")
    yield lambda: rc.controlled_edit_enabled() and rc._mirror.editable
    assert not obj().hide_select
    native("translate", value=(.015, 0, 0))
    yield lambda: location(.025) and idle() and len(rc.requests.requests) >= 1
    yield action("probe")
    assert result()["command_count"] == 1 and abs(result()["x_meters"] - .025) < 1e-6
    assert result()["commands"][-1]["payload"]["op"] == "object.move"
    checks.append("native transform.translate (G/gizmo operator) reaches original host exactly once")
    native("rotate", value=math.pi / 4, orient_axis="Z")
    yield lambda: idle() and len(rc.requests.requests) >= 2
    yield action("probe")
    assert result()["command_count"] == 2
    assert result()["commands"][-1]["payload"]["op"] == "object.rotate"
    assert abs(result()["commands"][-1]["payload"]["args"]["to"][0] - math.cos(math.pi/8)) < 1e-5
    checks.append("native transform.rotate reaches host quaternion exactly once")
    native("resize", value=(1.5, 1.5, 1.5))
    yield lambda: idle() and len(rc.requests.requests) >= 3
    yield action("probe")
    assert result()["command_count"] == 3 and all(abs(v-1.5)<1e-5 for v in result()["object_scale"])
    checks.append("native transform.resize reaches host scale exactly once")
    # A real native modal transform is pending across GUI event-loop ticks.
    choose()
    assert bpy.ops.transform.translate("INVOKE_DEFAULT") == {"RUNNING_MODAL"}
    yield lambda: bool(bpy.context.window.modal_operators)
    modal_evidence.extend(op.bl_idname for op in bpy.context.window.modal_operators)
    assert rc._transforming(), modal_evidence
    bpy.context.window.event_simulate(type="ESC", value="PRESS")
    yield lambda: not rc._transforming()
    yield action("probe")
    assert result()["command_count"] == 3
    checks.append("real Window.modal_operators detects native G; actual ESC cancels without a command")
    # Host edits are received as state, without bouncing back as Client commands.
    yield action("native_move")
    yield lambda: location(.025, .03) and idle()
    yield action("probe")
    assert result()["command_count"] == 3
    checks.append("host native move propagates to Client with no resend")
    choose()
    assert bpy.ops.transform.translate("INVOKE_DEFAULT") == {"RUNNING_MODAL"}
    yield lambda: rc._transforming()
    yield action("native_move")
    yield lambda: abs(rc.state.objects[oid]["transform"]["location"][1]-.06)<1e-6
    assert location(.025, .03), "Host snapshot overwrote active native drag"
    bpy.context.window.event_simulate(type="ESC", value="PRESS")
    yield lambda: not rc._transforming() and location(.025, .06) and idle()
    yield action("probe")
    assert result()["command_count"] == 3
    checks.append("host change during real modal G is held; native ESC restores latest host state without resend")
    yield action("ownership_on")
    yield lambda: bool(rc.ownership_state()[0])
    choose()
    assert bpy.ops.transform.translate(value=(.04, 0, 0)) == {"FINISHED"}
    bpy.context.view_layer.update()
    yield lambda: bool(rc.live.error) and location(.025, .06) and idle()
    yield action("probe")
    rejected_count = result()["command_count"]
    assert rejected_count == 4 and abs(result()["x_meters"]-.025)<1e-6
    pause_until = time.monotonic() + .4
    yield lambda: time.monotonic() > pause_until
    yield action("probe")
    assert result()["command_count"] == rejected_count
    checks.append("real conflicting host lease rejects native move; Client snaps back once and never resends")
    yield action("ownership_off")
    yield lambda: not rc.ownership_state()[0]
    before_undo = sum(r.op == "history.undo" for r in rc.requests.requests.values())
    history("undo")
    yield lambda: history_done("undo", before_undo)
    yield action("probe")
    assert result()["commands"][-1]["payload"]["op"] == "history.undo"
    assert all(abs(v-1)<1e-5 for v in result()["object_scale"])
    before_redo = sum(r.op == "history.redo" for r in rc.requests.requests.values())
    history("redo")
    yield lambda: history_done("redo", before_redo)
    yield action("probe")
    assert result()["commands"][-1]["payload"]["op"] == "history.redo"
    assert all(abs(v-1.5)<1e-5 for v in result()["object_scale"])
    checks.append("registered Client Undo/Redo operators change authoritative native host history")
    choose()
    assert bpy.ops.object.delete(use_global=False) == {"FINISHED"}
    yield lambda: oid not in rc.state.objects and idle()
    yield action("probe")
    assert not result()["exists"] and result()["commands"][-1]["payload"]["op"] == "object.delete"
    checks.append("native object.delete removes authoritative object and mirror")
    assert bpy.ops.spatial_modeling.client_undo() == {"FINISHED"}
    yield lambda: oid in rc.state.objects and idle()
    yield action("probe")
    assert result()["exists"]
    count = result()["command_count"]
    rc.disconnect()
    assert rc._link is None
    assert bpy.ops.spatial_modeling.connect_readonly() == {"FINISHED"}
    yield lambda: rc.state.current and rc.controlled_edit_enabled()
    yield action("probe")
    assert result()["command_count"] == count
    checks.append("explicit disconnect/reconnect loads authoritative snapshot without repeating prior edits")
    yield action("flag_off")
    yield lambda: rc.state.current and not rc.controlled_edit_enabled()
    assert obj().hide_select
    yield action("probe")
    assert result()["command_count"] == count
    checks.append("permission revoked: native mirror is unselectable; no write or resend")
    rc.disconnect()
    yield action("finish")
    assert source_hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in (ROOT / "blender_addon/spatial_modeling").rglob("*.py")}
    (folder / "client-result.json").write_text(json.dumps({"passed": True, "checks": checks,
        "actual_modal_operator_ids": modal_evidence, "source_hashes": source_hashes, "physical_mouse_keyboard": False, "simulated_ctrl_z_keymap": bool(config.get("keyboard_events")),
        "simulated_native_g_r_s_keymaps": bool(config.get("keyboard_events")),
        "headset": False, "full_native_data_sync": False}, indent=2))


def tick():
    global waiting, waiting_since
    try:
        if (folder / "host-error.txt").exists():
            raise RuntimeError((folder / "host-error.txt").read_text())
        if time.monotonic() - started > config.get("client_test_timeout", 150):
            raise TimeoutError("Native Client overall deadline")
        area = next(a for a in bpy.context.window.screen.areas if a.type == "VIEW_3D")
        region = next(r for r in area.regions if r.type == "WINDOW")
        with bpy.context.temp_override(area=area, region=region):
            if waiting is not None:
                if not waiting():
                    if time.monotonic() - waiting_since > config.get("condition_timeout", 15):
                        raise TimeoutError("Native step timeout: " + str(checks) + " / " + str(rc.live.__dict__) + " / " + str(rc.edit_blocked()) + " / " + str({k:v.__dict__ for k,v in rc.requests.requests.items()}) + " / " + rc.state.status)
                    return .02
                waiting = None
            waiting = next(scenario)
            waiting_since = time.monotonic()
        return .02
    except StopIteration:
        bpy.ops.wm.quit_blender()
    except Exception:  # noqa: BLE001 - preserve errors before disposable GUI process exits
        (folder / "client-error.txt").write_text(traceback.format_exc())
        try:
            rc.disconnect()
        finally:
            bpy.ops.wm.quit_blender()
    return None


scenario = seq()
bpy.app.timers.register(tick, first_interval=1)

"""Actual registered operator plus production P2 mirror; no state/prefs adapters."""
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
import spatial_modeling as addon
from spatial_modeling import remote_client, remote_test_ui

folder = Path(sys.argv[sys.argv.index("--") + 1])
config = json.loads((folder / "config.json").read_text())
ready = json.loads((folder / "ready.json").read_text())
cube_id = ready["cube_id"]
checks = []
hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in (ROOT / "blender_addon/spatial_modeling").rglob("*.py")}


def wait_for(test, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (folder / "host-error.txt").exists():
            raise RuntimeError((folder / "host-error.txt").read_text())
        if remote_client._link is not None:
            remote_client.poll()
        if remote_test_ui._job is not None:
            remote_test_ui._finish()  # Background Blender does not service GUI timers.
        bpy.context.view_layer.update()
        if test():
            return
        time.sleep(.01)
    raise TimeoutError("Client condition: " + remote_client.state.status)


def action(name):
    response = folder / "action-result.json"
    response.unlink(missing_ok=True)
    temp = folder / "action.tmp"
    temp.write_text(json.dumps({"action": name}))
    temp.replace(folder / "action.json")
    wait_for(lambda: response.exists())
    return json.loads(response.read_text())["native"]


def mirror_x():
    return remote_client._mirror.objects[cube_id].location.x


try:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    # Stop the default Host startup only. Actual preferences, Client connection,
    # bpy operators and state/mirror objects are used without replacement.
    original_sync = addon.host.sync
    addon.host.sync = lambda: None
    bpy.context.preferences.addons.new().module = "spatial_modeling"
    addon.register()
    prefs = bpy.context.preferences.addons["spatial_modeling"].preferences
    prefs.role = "CLIENT"
    addon.host.sync = original_sync
    prefs.client_address, prefs.client_port = "127.0.0.1", ready["port"]
    prefs.client_token, prefs.client_tls = config["token"], True
    assert bpy.ops.spatial_modeling.connect_readonly() == {"FINISHED"}
    wait_for(lambda: remote_client.state.current)
    assert abs(mirror_x() - .01) < 1e-7
    wm = bpy.context.window_manager
    assert not wm.spatial_remote_test_enabled
    wm.spatial_remote_test_enabled = True
    assert not bpy.ops.spatial_modeling.remote_move_test.poll(), "Host flag-off route enabled"
    assert action("probe")["command_count"] == 0
    checks.append("actual welcome.can_edit false disables operator; native unchanged")
    action("flag_on")
    wait_for(lambda: remote_client.controlled_edit_enabled())
    assert bpy.ops.spatial_modeling.remote_move_test.poll()
    if config.get("ownership"):
        mirror = remote_client._mirror.objects[cube_id]
        before_color = list(mirror.color)
        before_materials = [(m.name, list(m.diffuse_color)) for m in mirror.data.materials]
        revision = remote_client.state.document["revision"]
        action("ownership_on")
        wait_for(lambda: len(remote_client.ownership_state()[0]) == 1)
        held, actor, status = remote_client.ownership_state()
        assert held[0]["owner"]["name"] == "Native Client Owner"
        assert held[0]["targets"] == [cube_id] and actor != held[0]["owner"]["actor_id"]
        assert actor in {a["actor_id"] for a in remote_client.participants()}
        assert remote_client.state.current and remote_client.state.document["revision"] == revision
        assert list(mirror.color) == before_color
        assert [(m.name, list(m.diffuse_color)) for m in mirror.data.materials] == before_materials
        # The pink overlay's own data path in the Client role: the mirror object
        # carrying the host ID is marked with the owner's name (#78).
        from spatial_modeling import ownership, ownership_state
        marks = ownership._marks()
        assert [(obj, names) for obj, names in marks] == [(mirror, ("Native Client Owner",))], marks
        assert ownership_state.object_label(marks[0][1]) == \
            "Native Client Owner is editing this object"
        assert ownership_state.activity_text(held, actor) == \
            "Native Client Owner is editing the pink objects"
        action("ownership_off")
        wait_for(lambda: not remote_client.ownership_state()[0])
        assert not ownership.marked_objects()
        checks.append("actual full session names/leases and release; scene/materials unchanged; "
                      "Client overlay marks the mirror object with the owner's name, then clears")
    # Actual current target list, not a generated ID or a fake cached object.
    assert cube_id in {entry[0] for entry in remote_test_ui._targets(None, bpy.context)}
    wm.spatial_remote_test_target = cube_id
    before = mirror_x()
    assert bpy.ops.spatial_modeling.remote_move_test() == {"FINISHED"}
    assert "Waiting" in wm.spatial_remote_test_status
    assert mirror_x() == before, "Operator optimistically edited local mirror"
    wait_for(lambda: remote_test_ui._job is None)
    result = remote_test_ui._last_outcome
    assert result.outcome == "applied", result
    wait_for(lambda: abs(mirror_x() - .02) < 1e-7)
    after = action("probe")
    assert after["command_count"] == 1 and abs(after["x_meters"] - .02) < 1e-7
    assert abs(after["x_native"] - .02 / config["scale"]) < 1e-6
    assert result.receipt["actor"]["role"] == "blender-client"
    if config.get("ownership"):
        wait_for(lambda: len(remote_client.presence.activities) == 1)
        assert remote_client.presence.activities[0]["request_id"] == result.request_id
    assert after["commands"][0]["payload"]["lease"]
    wait_for(lambda: not action("probe")["leases"])
    checks.append("actual bpy operator, target list, lease, native receipt and live mirror +10mm")
    action("delay_on")
    assert bpy.ops.spatial_modeling.remote_move_test() == {"FINISHED"}
    assert bpy.ops.spatial_modeling.remote_cancel_test() == {"FINISHED"}
    wait_for(lambda: remote_test_ui._job is None)
    assert remote_test_ui._last_outcome.code == "cancelled"
    time.sleep(.7)
    assert action("probe")["command_count"] == 1
    checks.append("actual Cancel operator before delayed permission: no second native command")
    assert bpy.ops.spatial_modeling.remote_move_test() == {"FINISHED"}
    remote_client.disconnect()
    if config.get("ownership"):
        assert remote_client.ownership_state()[0:2] == ([], "")
        assert not remote_client.participants() and not remote_client.presence.activities
    wait_for(lambda: remote_test_ui._job is None)
    assert remote_test_ui._last_outcome.code == "cancelled"
    time.sleep(.7)
    assert action("probe")["command_count"] == 1
    checks.append("actual mirror disconnect cancels pending draft; no late-grant mutation")
    action("delay_off")
    assert bpy.ops.spatial_modeling.connect_readonly() == {"FINISHED"}
    wait_for(lambda: remote_client.state.current)
    assert abs(mirror_x() - .02) < 1e-7
    checks.append("fresh production mirror reconnect retains exactly one accepted move")
    remote_client.disconnect()
    action("finish")
    assert hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (ROOT / "blender_addon/spatial_modeling").rglob("*.py")}
    report = {"passed": True, "checks": checks, "unit_scale": config["scale"],
              "receipt": result.receipt, "source_hashes": hashes,
              "headset": "not tested", "second_pc": "not tested"}
    (folder / "client-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
except Exception:
    (folder / "client-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    raise
finally:
    remote_client.disconnect()
    if remote_test_ui._job is not None:
        wait_for(lambda: remote_test_ui._job is None)
    if bpy.context.preferences.addons.get("spatial_modeling"):
        addon.unregister()

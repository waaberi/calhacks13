"""Real second Blender process; uses the Client role with the real TLS host."""
import json
import sys
import time
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
import spatial_modeling as addon
from spatial_modeling import remote_client

folder = Path(sys.argv[sys.argv.index("--") + 1])
config = json.loads((folder / "config.json").read_text())
ready = json.loads((folder / "ready.json").read_text())
cube_id = ready["cube_id"]
checks = []


def wait_for(test, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (folder / "host-error.txt").exists():
            raise RuntimeError((folder / "host-error.txt").read_text())
        if remote_client._link is not None:
            remote_client.poll()
        bpy.context.view_layer.update()
        if test():
            return
        time.sleep(.02)
    raise TimeoutError("P2 client condition: " + remote_client.state.status)


def action(name):
    response = folder / "action-result.json"
    response.unlink(missing_ok=True)
    temp = folder / "action.tmp"
    temp.write_text(json.dumps({"action": name}))
    temp.replace(folder / "action.json")
    wait_for(lambda: response.exists() and json.loads(response.read_text())["action"] == name)


try:
    # A personal scene must be refused before any connection is opened.
    from spatial_modeling.remote_client.mirror import Mirror
    try:
        Mirror()
        raise AssertionError("Factory objects were silently replaced")
    except ValueError:
        checks.append("refuses nonempty/personal session")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    # Exercise the actual add-on lifecycle, preferences, role and operator without
    # starting its default Host listener on the running P1 app's port.
    original_sync = addon.host.sync
    addon.host.sync = lambda: None
    bpy.context.preferences.addons.new().module = "spatial_modeling"
    addon.register()
    prefs = bpy.context.preferences.addons["spatial_modeling"].preferences
    prefs.role = "CLIENT"
    addon.host.sync = original_sync
    prefs.client_address = "127.0.0.1"
    prefs.client_token = config["token"]
    prefs.client_port = ready["port"]
    assert bpy.ops.spatial_modeling.connect_readonly() == {"FINISHED"}
    wait_for(lambda: remote_client.state.current)
    state = remote_client.state
    report = state.check_reference({cube_id: [.01, 0, 0]})
    assert report["scale_length"] == .001
    obj = remote_client._mirror.objects[cube_id]
    assert abs(obj.dimensions.x - .02) < .000001, obj.dimensions[:]
    checks.append("TLS real snapshot; stable ID, meter position, 20mm dimensions, mm host units")
    healthy_until = time.monotonic() + 2.5
    while time.monotonic() < healthy_until:
        remote_client.poll()
        assert remote_client.state.current, remote_client.state.status
        time.sleep(.02)
    checks.append("background ping/pong keeps the read-only session healthy")
    action("undo_invariance")
    checks.append("native host Undo/Redo unchanged by read-only connection")
    # A local mirror edit cannot become a host command; next authoritative update restores it.
    obj.location.x = 50
    mesh_name = obj.data.name
    action("move")
    wait_for(lambda: remote_client.state.objects[cube_id]["transform"]["location"][0] == .02)
    assert abs(remote_client._mirror.objects[cube_id].location.x - .02) < .000001
    assert remote_client._mirror.objects[cube_id].data.name == mesh_name
    checks.append("live transform, mesh reuse, local changes never echoed")
    action("add")
    wait_for(lambda: len(remote_client.state.objects) == 2)
    action("delete")
    wait_for(lambda: len(remote_client.state.objects) == 1)
    checks.append("live native add/delete in second Blender")
    action("drop")
    wait_for(lambda: not remote_client.state.current)
    wait_for(lambda: remote_client.state.current)
    assert len(remote_client._mirror.objects) == 1
    checks.append("stale warning on drop; fresh reconnect snapshot")
    action("new_epoch")
    wait_for(lambda: not remote_client._link.thread.is_alive())
    remote_client.poll()
    assert not remote_client.state.current
    checks.append("wrong-document epoch refused; stale scene never presented current")
    remote_client.disconnect()
    assert not any(o.get("spatial_readonly_mirror") for o in bpy.data.objects)
    checks.append("disconnect removes only owned mirror data")
    action("finish")
    (folder / "mirror-result.json").write_text(json.dumps({"passed": True, "checks": checks}), encoding="utf-8")
except Exception:
    (folder / "mirror-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    raise
finally:
    remote_client.disconnect()
    if bpy.context.preferences.addons.get("spatial_modeling"):
        addon.unregister()

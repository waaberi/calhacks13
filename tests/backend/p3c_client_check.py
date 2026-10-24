"""Real read-only Client against a pinned native CAD host, without a solver."""
import hashlib
import json
import math
import sys
import time
import traceback
from pathlib import Path

import bpy
from mathutils import Quaternion

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
from spatial_modeling import remote_client
from spatial_modeling.remote_client.mirror import SKETCH_RECORD

folder = Path(sys.argv[sys.argv.index("--") + 1])
config = json.loads((folder / "config.json").read_text())
ready = json.loads((folder / "ready.json").read_text())
output, info = Path(config["output"]), ready["info"]
checks = []
sources = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
           for p in (ROOT / "blender_addon/spatial_modeling/remote_client").glob("*.py")}


def wait_for(test, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (folder / "host-error.txt").exists():
            raise RuntimeError((folder / "host-error.txt").read_text())
        if remote_client._link is not None:
            remote_client.poll()
        bpy.context.view_layer.update()
        if test():
            return
        time.sleep(.01)
    raise TimeoutError("CAD Client condition: " + remote_client.state.status)


def action(name):
    response = folder / "action-result.json"
    response.unlink(missing_ok=True)
    temp = folder / "action.tmp"
    temp.write_text(json.dumps({"action": name}))
    temp.replace(folder / "action.json")
    wait_for(lambda: response.exists())
    return json.loads(response.read_text())


def connect():
    remote_client.connect("127.0.0.1", config["token"], "0.1.0", "Read-only CAD peer", ready["port"])
    wait_for(lambda: remote_client.state.current)


def same(snapshot):
    expected = {r["id"]: r for r in snapshot["sketches"]}
    wait_for(lambda: remote_client.state.sketches == expected)
    for sid, record in expected.items():
        obj = remote_client._mirror.sketches[sid]
        assert obj.type == "CURVE" and obj.hide_select
        assert json.loads(obj[SKETCH_RECORD]) == record
        assert len(obj.data.materials) == 0
        assert list(obj.location) == record["plane"]["location"]
        assert abs(abs(obj.matrix_world.to_quaternion().dot(Quaternion(
            record["plane"]["rotation"]))) - 1) < 1e-5
    return expected


def curve_points(sid):
    return [point.co[:3] for spline in remote_client._mirror.sketches[sid].data.splines
            for point in spline.points]


def rectangle_width():
    points = curve_points(info["rect"])
    return max(p[0] for p in points) - min(p[0] for p in points)


try:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    assert "CAD_Sketcher" not in sys.modules and "slvs" not in sys.modules
    connect()
    same(ready["snapshot"])
    assert len(remote_client.state.sketches) == 3
    assert bpy.context.scene.unit_settings.scale_length == 1
    if config["phase"] == "create" and not config.get("faults_only"):
        assert math.isclose(rectangle_width(), .1, abs_tol=1e-7)
        checks.append("real native anchored100x60mm XY, circle XZ, angle YZ rendered without Client solver")
        changed = action("dimensions")
        same(changed["snapshot"])
        assert math.isclose(rectangle_width(), .12, abs_tol=1e-7)
        record = remote_client.state.sketches[info["circle"]]
        center_id = next(e["center"] for e in record["entities"] if e["kind"] == "circle")
        center = next(e["at"] for e in record["entities"] if e["id"] == center_id)
        radii = [math.hypot(p[0]-center[0], p[1]-center[1]) for p in curve_points(info["circle"])]
        assert all(math.isclose(r, .015, abs_tol=1e-7) for r in radii), (record, min(radii), max(radii))
        lines = remote_client._mirror.sketches[info["angle"]].data.splines
        u = lines[0].points[1].co.xyz - lines[0].points[0].co.xyz
        v = lines[1].points[1].co.xyz - lines[1].points[0].co.xyz
        assert math.isclose(u.angle(v), math.pi/3, abs_tol=1e-6)
        checks.append("live actual native solved120x60mm, diameter30mm and60degree curve points")
        before = json.dumps(remote_client.state.sketches, sort_keys=True)
        rejected = action("conflict")
        assert rejected["conflict_preserved"]
        same(rejected["snapshot"])
        assert json.dumps(remote_client.state.sketches, sort_keys=True) == before
        checks.append("actual solver conflict preserves last valid native and mirrored records")
        saved = action("save")
        same(saved["snapshot"])
        metadata = {sid: json.loads(obj[SKETCH_RECORD]) for sid, obj in remote_client._mirror.sketches.items()}
        (output / "mirror-meta.json").write_text(json.dumps(metadata))
        bpy.ops.wm.save_as_mainfile(filepath=str(output / "mirror.blend"), copy=True)
        checks.append("native Save and full editable read-only JSON metadata saved in mirror copy")
    elif config["phase"] == "reopen":
        assert math.isclose(rectangle_width(), .12, abs_tol=1e-7)
        changed = action("reedit")
        same(changed["snapshot"])
        assert math.isclose(rectangle_width(), .13, abs_tol=1e-7)
        checks.append("fresh native reopen preserves IDs/constraints and solves130x60mm into fresh Client")
    else:
        checks.append("focused fault/reconnect run from actual native baseline; dimension/reopen gates not run")
    action("ownership_on")
    wait_for(lambda: len(remote_client.ownership_state()[0]) == 1)
    held, actor, _ = remote_client.ownership_state()
    assert held[0]["targets"] == [info["rect"]] and held[0]["owner"]["name"] == "CAD Host Owner"
    assert remote_client._mirror.sketches[info["rect"]]["spatial_modeling_id"] == held[0]["targets"][0]
    action("ownership_off")
    wait_for(lambda: not remote_client.ownership_state()[0])
    checks.append("actual whole-sketch ownership targets the displayed stable sketch ID")
    statuses = []
    stale = remote_client.state.stale

    def observed_stale(reason="Disconnected — last scene is stale"):
        statuses.append(reason)
        return stale(reason)

    remote_client.state.stale = observed_stale
    action("fault")
    wait_for(lambda: not remote_client.state.current)
    assert not remote_client.ownership_state()[0]
    assert any("Host scene unavailable" in status for status in statuses), statuses
    restored = action("restore")
    wait_for(lambda: remote_client.state.current)
    same(restored["snapshot"])
    checks.append("real unsupported-frame serialization error closes/stales Client; fresh snapshot recovers")
    deleted = action("delete")
    same(deleted["snapshot"])
    assert info["circle"] not in remote_client._mirror.sketches
    checks.append("native sketch deletion removes only its owned Client Curve")
    snapshot = action("probe")["snapshot"]
    remote_client.disconnect()
    connect()
    same(snapshot)
    checks.append("explicit reconnect replaces editable records and solved geometry without echo")
    remote_client.disconnect()
    assert not any(obj.get("spatial_readonly_mirror") for obj in bpy.data.objects)
    final = action("finish")
    assert set(final["inbound_types"]) <= {"hello", "ping"}
    assert sources == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (ROOT / "blender_addon/spatial_modeling/remote_client").glob("*.py")}
    (folder / "client-result.json").write_text(json.dumps({"passed": True, "checks": checks,
        "source_hashes": sources, "native_identity": ready["identity"], "headset": "not tested",
        "second_pc": "not tested"}, indent=2))
except Exception:
    (folder / "client-error.txt").write_text(traceback.format_exc())
    raise
finally:
    remote_client.disconnect()

"""Actual production Client/controller path with ordinary native Blender edits."""
import json
import os
import sys
import time
import traceback
from pathlib import Path

import bpy

assert os.environ.get("SPATIAL_NATIVE_SYNC_TEST") == "1"
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "blender_addon"), str(Path(__file__).parent)]
import spatial_modeling as addon
from native_fixture import edit_fixture, edit_topology_fixture
from native_graph import capture_graph, differences
from spatial_modeling import remote_client as rc
from spatial_modeling.native_sync.document import NativeDocument
from spatial_modeling.session import APP

folder = Path(sys.argv[sys.argv.index("--") + 1])
config = json.loads((folder / "config.json").read_text())
ready = json.loads((folder / "ready.json").read_text())
report = {"passed": False, "network_sync_tested": True, "checks": []}
started = time.monotonic()
waiting = None
waiting_since = 0.0
scheduled = []
finished = False


def schedule(callback, delay):
    scheduled.append((time.monotonic() + delay, callback))


class ObservedDocument(NativeDocument):
    def capture(self, path):
        try:
            return super().capture(path)
        except (OSError, RuntimeError, ValueError):
            (folder / "capture-error.txt").write_text(traceback.format_exc())
            raise


def status():
    try:
        return json.loads((folder / "host-status.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def same(expected):
    try:
        return not differences(expected, capture_graph())
    except (KeyError, RuntimeError):
        return False


def host_same(expected):
    actual = status().get("graph")
    return actual is not None and not differences(expected, actual)


def host_changed_and_client_matches(before):
    actual = status().get("graph")
    return actual is not None and differences(before, actual) and settled() and same(actual)


def duplicate_shared():
    ids = status().get("native_ids", {})
    copy = ids.get("AAA_NativeSync_Copy", {})
    original = ids.get("NativeSync_Cube", {})
    return (settled() and copy.get("id") and original.get("id")
            and copy.get("id") != original.get("id")
            and copy.get("uuid") != original.get("uuid"))


def action(name):
    temp = folder / "action.tmp"
    temp.write_text(json.dumps({"action": name}))
    temp.replace(folder / "action.json")


def settled():
    n = rc.native_client
    return (n is not None and n.applied_head is not None and not n.applying
            and not n.watcher.has_local_changes and not n.error)


def steps():
    # No original/user scene is opened. This is a factory, unsaved empty process.
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    original_sync = addon.host.sync
    addon.host.sync = lambda: None
    bpy.context.preferences.addons.new().module = "spatial_modeling"
    addon.register()
    addon.host.sync = original_sync
    prefs = bpy.context.preferences.addons["spatial_modeling"].preferences
    prefs.role = "CLIENT"
    rc.connect("127.0.0.1", config["token"], APP["version"], "Native full-data test",
               port=ready["port"], tls=True, native=True)
    rc.native_client.document = ObservedDocument(schedule=schedule)
    yield "initial original topology and full dependency graph", lambda: (
        rc.native_client is not None and rc.native_client.has_native_document
        and settled() and same(ready["graph"]))
    before = capture_graph()
    action("edit")
    yield "Host native Edit Mode UV modifier material custom-property edits reach Client", lambda: (
        host_changed_and_client_matches(before))
    host_edit = capture_graph()
    assert rc.native_client.take_edit_turn(), rc.native_client.error
    yield "exclusive edit turn refreshes complete original data", lambda: (
        rc.native_client.is_editing and settled())
    edit_fixture("client")
    bpy.ops.ed.undo_push(message="Client native tools")
    expected = capture_graph()
    rc.native_client.mark_dirty()
    yield "Client native mesh UV modifier material node-group shape-key and rig edits reach Host", lambda: (
        settled() and host_same(expected))
    bpy.ops.ed.undo()
    assert same(host_edit), differences(host_edit, capture_graph())
    rc.native_client.mark_dirty()
    yield "ordinary local Blender Undo synchronizes and preserves preceding Host work", lambda: (
        settled() and host_same(host_edit))
    bpy.ops.ed.redo()
    assert same(expected), differences(expected, capture_graph())
    rc.native_client.mark_dirty()
    yield "ordinary Blender Redo restores full Client data on both peers", lambda: (
        settled() and host_same(expected))
    edit_topology_fixture()
    bpy.ops.ed.undo_push(message="Client native Extrude and shader node")
    topology = capture_graph()
    rc.native_client.mark_dirty()
    yield "native Extrude topology new shader node custom attributes packed image and linked data survive", lambda: (
        settled() and host_same(topology))
    original_uuid = bpy.data.objects["NativeSync_Cube"]["spatial_native_uuid"]
    bpy.ops.object.select_all(action="DESELECT")
    original = bpy.data.objects["NativeSync_Cube"]
    original.select_set(True)
    bpy.context.view_layer.objects.active = original
    bpy.ops.object.duplicate()
    bpy.context.object.name = "AAA_NativeSync_Copy"
    bpy.ops.ed.undo_push(message="Native Duplicate")
    rc.native_client.mark_dirty()
    yield "native Duplicate gets a distinct Host ID without stealing the original UUID", duplicate_shared
    first_ids = status()["native_ids"]
    assert bpy.data.objects["NativeSync_Cube"]["spatial_native_uuid"] == original_uuid
    bpy.data.objects["AAA_NativeSync_Copy"]["native_second_edit"] = 42
    bpy.ops.ed.undo_push(message="Native duplicated object follow-up")
    rc.native_client.mark_dirty()
    yield "Host canonical IDs survive repeated native checkpoints of new Client objects", lambda: (
        duplicate_shared() and status()["native_ids"]["AAA_NativeSync_Copy"]
        == first_ids["AAA_NativeSync_Copy"])
    assert rc.native_client.finish_edit_turn()
    yield "finishing edit turn waits for native receipt then releases ownership", lambda: (
        not rc.native_client.lease_id and not status().get("leases") and settled())
    assert same(topology)
    rc.disconnect()
    assert same(topology), "Disconnect must preserve the full native document"
    report["checks"].append("disconnect preserves original native document instead of deleting a mirror")
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / "verified-client.blend"), copy=True, compress=False)
    report["final_graph"] = topology
    action("finish")
    yield "Host finishes cleanly with no leaked native edit reservation", lambda: (
        folder / "host-result.json").exists()


def finish():
    global finished
    finished = True
    native = getattr(rc, "native_client", None)
    report["client_status"] = native.status if native else "Disconnected"
    report["client_error"] = native.error if native else ""
    report["blender_version"] = bpy.app.version_string
    (folder / "client-result.json").write_text(json.dumps(report, indent=2))
    rc.disconnect()
    bpy.ops.wm.quit_blender()


scenario = steps()


def tick():
    global waiting, waiting_since
    try:
        if waiting is not None:
            label, condition = waiting
            if not condition():
                if time.monotonic() - waiting_since > 40:
                    native = getattr(rc, "native_client", None)
                    summary = ({key: getattr(native, key) for key in (
                        "status", "error", "has_native_document", "applying", "head", "applied_head")}
                        if native else {})
                    raise TimeoutError(label + "; native=" + str(summary)
                                       + "; host_head=" + str(status().get("head")))
                return .05
            report["checks"].append(label)
            print("PASS:", label, flush=True)
            waiting = None
        if time.monotonic() - started > config.get("timeout", 240):
            raise TimeoutError("Full native protocol scenario timed out")
        area = next(area for area in bpy.context.window.screen.areas if area.type == "VIEW_3D")
        region = next(region for region in area.regions if region.type == "WINDOW")
        with bpy.context.temp_override(area=area, region=region):
            waiting = next(scenario)
        waiting_since = time.monotonic()
        return .05
    except StopIteration:
        report["passed"] = True
        finish()
    except Exception:  # noqa: BLE001 - preserve exact owned fixture failure before quitting
        report["error"] = traceback.format_exc()
        (folder / "client-error.txt").write_text(report["error"])
        finish()


while not finished:
    for entry in list(scheduled):
        if time.monotonic() >= entry[0]:
            scheduled.remove(entry)
            with bpy.context.temp_override(window=bpy.context.window):
                entry[1]()
    with bpy.context.temp_override(window=bpy.context.window):
        if rc._link is not None:
            rc.poll()
        tick()
    time.sleep(.05)

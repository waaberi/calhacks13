"""Isolated real Blender host for the no-XR Unity P3 menu smoke.

Run in a GUI Blender with --factory-startup --python THIS_FILE. Required env:
P3_SMOKE_OUTPUT (fresh directory outside OneDrive) and BLENDER_USER_RESOURCES
(a directory below it). P3_SMOKE_PORT defaults to 18766; P3_SMOKE_SECONDS to
900. No add-on registration, default listener, LAN listener or XR is started.

ready.json identifies the process and document. report.json is live native
readback; commands.jsonl preserves every command and its before/after state.
Creating OUTPUT/stop.signal closes this host and quits only this Blender.
"""

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import traceback
import uuid
from collections import ChainMap
from datetime import UTC, datetime
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))

from spatial_modeling import commands, document, edits, host, leases, server, session, sync

OUTPUT = None
SRV = None
DOC = None
SESS = None
CMDS = None
STARTED = time.monotonic()
DEADLINE = None
LAST_REPORT = 0.0
RECEIPTS = []
REPORT = {"status": "starting", "physical_headset": "not tested", "second_pc": "not tested",
          "mode": "isolated GUI Blender, production native command path, loopback only"}


def utc_now():
    return datetime.now(UTC).isoformat()


def source_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "blender_addon" / "spatial_modeling").rglob("*.py"))}


def write_json(name, value):
    target = OUTPUT / name
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(target)


def native_state():
    """Read actual Blender data, including Blender units and SI values separately."""
    bpy.context.view_layer.update()
    scale = float(bpy.context.scene.unit_settings.scale_length)
    objects = []
    for obj in sorted(bpy.data.objects, key=lambda value: value.name):
        oid = obj.get(sync.ID_PROPERTY)
        matrix = obj.matrix_world
        objects.append({
            "id": oid, "generation": sync.generation(oid) if oid else None,
            "name": obj.name, "type": obj.type,
            "location_blender_units": list(obj.location),
            "location_meters": [float(v) * scale for v in obj.location],
            "world_location_meters": [float(v) * scale for v in matrix.translation],
            "rotation_euler_radians": list(obj.rotation_euler),
            "rotation_quaternion_wxyz": list(matrix.to_quaternion()),
            "scale": list(obj.scale), "dimensions_blender_units": list(obj.dimensions),
            "dimensions_meters": [float(v) * scale for v in obj.dimensions],
            "mesh_vertices": len(obj.data.vertices) if obj.type == "MESH" else None,
            "selected": obj.select_get(),
        })
    return {"observed_utc": utc_now(), "document": DOC.describe() if DOC else None,
            "native_dirty": bool(bpy.data.is_dirty), "filepath": bpy.data.filepath,
            "unit_scale": scale, "objects": objects,
            "participants": list(SESS.participants.values()) if SESS else [],
            "leases": SESS.store.leases() if SESS else [],
            "commands_frozen": CMDS.frozen if CMDS else None,
            "receipt_history_evicted": CMDS.evicted if CMDS else None}


def write_report():
    REPORT.update(updated_utc=utc_now(), elapsed_seconds=time.monotonic() - STARTED,
                  native=native_state(), receipts=RECEIPTS)
    write_json("report.json", REPORT)


def logged_command(msg, conn):
    """Observe the real handler without changing dispatch, permissions or receipts."""
    before = native_state()
    reply = None
    error = None
    try:
        reply = CMDS.command(msg, conn)
        return reply
    except Exception:
        error = traceback.format_exc()
        raise
    finally:
        receipt = None
        if reply and reply.get("type") == "result":
            receipt = reply["payload"]
        elif reply is None:
            stored = CMDS.receipts.get(msg.get("id"))
            if stored is not None:
                receipt = stored[1]
        event = {"observed_utc": utc_now(), "request": msg, "receipt": receipt,
                 "response": reply, "exception": error,
                 "before": before, "after": native_state()}
        with (OUTPUT / "commands.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, allow_nan=False) + "\n")
        if receipt is not None:
            RECEIPTS.append(receipt)
        write_report()
        print("P3_SMOKE_COMMAND " + json.dumps({"request_id": msg.get("id"),
              "receipt": receipt, "exception": error}), flush=True)


def finish(reason, error=None):
    """Stop our server first; this script never finds or terminates other processes."""
    if SRV is not None:
        SRV.stop()
    if OUTPUT is not None:
        REPORT.update(status="failed" if error else "stopped", stop_reason=reason,
                      error=error, stopped_utc=utc_now(), final_source_hashes=source_hashes())
        REPORT["source_unchanged_during_run"] = (
            REPORT.get("source_hashes") == REPORT["final_source_hashes"])
        write_report()
        ready = OUTPUT / "ready.json"
        if ready.exists():
            identity = json.loads(ready.read_text(encoding="utf-8"))
            identity.update(status=REPORT["status"], stopped_utc=REPORT["stopped_utc"])
            write_json("ready.json", identity)
    sync.unregister()
    print("P3_SMOKE_STOPPED " + reason, flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    if error:
        os._exit(1)
    bpy.ops.wm.quit_blender()


def tick():
    global LAST_REPORT
    try:
        if (OUTPUT / "stop.signal").exists():
            finish("stop.signal")
            return None
        if time.monotonic() >= DEADLINE:
            finish("maximum duration")
            return None
        DOC.tick()
        SRV.drain()
        sync.poll()
        CMDS.poll()
        if time.monotonic() - LAST_REPORT >= 0.5:
            write_report()
            LAST_REPORT = time.monotonic()
        return 0.02
    except Exception:  # noqa: BLE001 - retain failures and stop our isolated server
        finish("host tick failed", traceback.format_exc())
        return None


def start():
    global OUTPUT, SRV, DOC, SESS, CMDS, DEADLINE
    output = Path(os.environ["P3_SMOKE_OUTPUT"]).resolve()
    resources = Path(os.environ["BLENDER_USER_RESOURCES"]).resolve()
    if not output.is_absolute() or any("onedrive" in p.lower() for p in output.parts):
        raise ValueError("P3_SMOKE_OUTPUT must be an absolute directory outside OneDrive")
    if not resources.is_relative_to(output) or resources == output:
        raise ValueError("BLENDER_USER_RESOURCES must be a dedicated subdirectory of output")
    if bpy.app.background:
        raise ValueError("Use GUI Blender (no --background) for actual native Undo/Redo")
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in
           ("ready.json", "report.json", "p3-smoke.blend", "commands.jsonl", "stop.signal")):
        raise FileExistsError("Use a fresh output directory; existing evidence is preserved")
    OUTPUT = output
    port = int(os.environ.get("P3_SMOKE_PORT", "18766"))
    seconds = float(os.environ.get("P3_SMOKE_SECONDS", "900"))
    if not 1024 <= port <= 65535 or port in (8765, 8766, 8767):
        raise ValueError("Use an isolated nonstandard port, default 18766")
    if not 1 <= seconds <= 900:
        raise ValueError("P3_SMOKE_SECONDS must be between 1 and 900")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))  # fail before scene work if already occupied
    try:
        commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                         text=True).strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    REPORT.update(pid=os.getpid(), blender=bpy.app.version_string, python=sys.version,
                  binary=bpy.app.binary_path, source_root=str(ROOT), source_commit=commit,
                  source_hashes=source_hashes(),
                  harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  started_utc=utc_now(), host="127.0.0.1", port=port,
                  output=str(OUTPUT), resources=str(resources), maximum_seconds=seconds,
                  limits="No gate/UI locking, capture, XR, LAN, or second-PC acceptance")
    # --factory-startup is mandatory: all scene changes below belong to this process only.
    if "--factory-startup" not in sys.argv:
        raise ValueError("Launch with --factory-startup to preserve personal Blender work")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.mesh.primitive_cube_add(size=0.02, location=(0, 0, 0))
    bpy.context.object.name = "P3_Smoke_Reference"
    units = bpy.context.scene.unit_settings
    units.system, units.length_unit, units.scale_length = "METRIC", "MILLIMETERS", 1.0
    DOC = document.Document()
    DOC.store()
    sync.object_id(bpy.context.object)
    fixture = OUTPUT / "p3-smoke.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(fixture))
    bpy.ops.ed.undo_push(message="P3 smoke saved baseline")
    SESS = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex,
                           name="P3 isolated host", client_can_edit=False,
                           capabilities=lambda: {"sketch": False})
    sync.register()
    sync.start(DOC, SESS)
    editor = edits.Editor(sync, host.undoable, DOC)
    held = leases.Leases(SESS, editor)
    CMDS = commands.Commands(SESS, editor, leases=held)
    SRV = held.attach(CMDS.attach(SESS.attach(server.Server(host="127.0.0.1", port=port))))
    SRV.handlers = ChainMap({"command": logged_command}, SRV.handlers)
    SRV.start()  # binding is the final authority if another process raced the probe
    sync.flush()
    DEADLINE = time.monotonic() + seconds
    REPORT.update(status="ready", fixture=str(fixture),
                  initial_fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest())
    write_report()
    ready = {k: REPORT[k] for k in ("status", "pid", "blender", "binary", "host", "port",
             "started_utc", "source_commit", "harness_sha256", "fixture", "maximum_seconds")}
    ready.update(document=DOC.describe(), session_id=SESS.session_id, host_epoch=SESS.host_epoch,
                 can_edit_vr=True, capabilities={"sketch": False},
                 reference_id=bpy.context.object.get(sync.ID_PROPERTY))
    write_json("ready.json", ready)
    print("P3_SMOKE_READY " + json.dumps(ready), flush=True)
    bpy.app.timers.register(tick, first_interval=0.02)


def main():
    # Defer creation until the GUI event loop exists, as the real P3A harness does.
    def initialize():
        try:
            return start()
        except Exception:  # noqa: BLE001 - preserve startup diagnostics in evidence
            error = traceback.format_exc()
            print(error, flush=True)
            finish("startup failed", error)
            return None

    bpy.app.timers.register(initialize, first_interval=1.0)


if __name__ == "__main__":
    main()

"""Real typed object commands/receipts in disposable background Blender.

No desktop input, capture, GUI, listener, Player or headset is used. Native object
results are independently measured; UI button routing remains a separate gate.
"""

import argparse
import hashlib
import json
import logging
import math
import os
import sys
import tempfile
import traceback
import uuid
from pathlib import Path

import bpy

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
from native_preview_workflows import Connection, LocalDispatch
from native_spatial_gate import setup


def multiply(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def rotation_matrix(axis, angle):
    c, s = math.cos(angle), math.sin(angle)
    return {"X": [[1, 0, 0], [0, c, -s], [0, s, c]],
            "Y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
            "Z": [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]


def main(args, report):
    assert bpy.app.background, "This native gate must never launch a GUI"
    profile = args.private_profile.resolve()
    assert profile.is_relative_to(args.output.resolve())
    for name, value in os.environ.items():
        if name.upper().startswith("BLENDER_USER_") or name.upper() in ("TEMP", "TMP", "TMPDIR"):
            assert value and Path(value).resolve().is_relative_to(profile), name
    tempfile.tempdir = str(profile / "temp")
    assert Path(bpy.app.tempdir).resolve().is_relative_to(profile)
    assert Path(tempfile.gettempdir()).resolve().is_relative_to(profile)
    report["isolation"] = {"profile": str(profile), "tempfile_directory": tempfile.gettempdir(),
                           "blender_temp_directory": bpy.app.tempdir, "dont_write_bytecode": sys.dont_write_bytecode,
                           "cad_file_handlers": []}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if args.extension:
        report["identity"] = setup(args)
        handlers = [Path(handler.baseFilename).resolve() for handler in logging.getLogger("CAD_Sketcher").handlers
                    if isinstance(handler, logging.FileHandler)]
        assert handlers and all(path.is_relative_to(profile) and path.is_file() for path in handlers)
        report["isolation"]["cad_file_handlers"] = [str(path) for path in handlers]
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "blender_addon"))
        report["identity"] = {"blender": bpy.app.version_string, "cad_enabled": False}
    from spatial_modeling import (
        commands,
        document,
        edits,
        host,
        leases,
        protocol,
        session,
        sketch,
        sync,
    )

    report["identity"].update(process_id=os.getpid(), **sketch.dependency_status())
    path, metadata = args.output / "typed-object-actions.blend", args.output / "typed-object-actions.json"
    if args.phase == "reopen":
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    else:
        bpy.context.scene.unit_settings.system = "METRIC"
        bpy.context.scene.unit_settings.scale_length = args.unit_scale
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex)
    dispatch = LocalDispatch()
    sess.attach(dispatch)
    sync.register()
    sync.start(doc, sess)
    sync.flush()
    editor = edits.Editor(sync, host.undoable, doc)
    manager = leases.Leases(sess, editor)
    commander = commands.Commands(sess, editor, leases=manager)
    manager.attach(dispatch)
    commander.attach(dispatch)
    bpy.context.preferences.edit.use_global_undo = True
    bpy.ops.ed.undo_push(message="Typed P2.5 object actions baseline")

    def check(name, okay, details=None):
        entry = {"name": name, "passed": bool(okay)}
        if details is not None:
            entry["details"] = details
        report["checks"].append(entry)
        assert okay, entry

    def join(name):
        conn = Connection()
        dispatch.connections.append(conn)
        sess.hello(protocol.message("hello", {"role": "vr", "name": name,
                   "app": {"name": "P2.5 typed object gate", "version": "0.1.0"}}), conn)
        assert conn.joined
        return conn

    owner, peer = join("Typed object owner"), join("Competing typed owner")

    def identity(conn=owner):
        return {"session_id": sess.session_id, "host_epoch": sess.host_epoch,
                "document_id": doc.id, "open_epoch": doc.open_epoch,
                "actor_id": sess.participants[conn]["actor_id"]}

    def records():
        bpy.context.view_layer.update()
        sync.flush()
        return {record["id"]: record for record in sync.snapshot(doc.describe())["objects"]}

    def payload(op, oid=None, values=None, conn=owner):
        sync.flush()
        p = {**identity(conn), "base_revision": doc.revision, "source": "ui", "op": op, "args": values or {}}
        if oid:
            p["target"] = {"id": oid, "generation": sync.generation(oid)}
        return p

    def dispatch_command(message, conn=owner):
        start = len(conn.messages)
        reply = commander.command(message, conn)
        if reply:
            conn.send(reply)
        results = [msg["payload"] for msg in conn.messages[start:]
                   if msg["type"] == "result" and msg["payload"]["request_id"] == message["id"]]
        assert len(results) == 1, (message, conn.messages[start:])
        receipt = results[0]
        report["receipts"].append(receipt)
        return receipt

    def run(op, oid=None, values=None, expected="applied", code=None, custom=None, leased=True):
        p = custom or payload(op, oid, values)
        lease = None
        if leased:
            granted = manager.acquire(protocol.message("lease.acquire", {**identity(), "mode": "exclusive", "targets": []}), owner)
            assert granted["type"] == "lease.granted", granted
            lease = granted["payload"]["lease"]["lease_id"]
            p["lease"] = lease
        msg = protocol.message("command", p)
        try:
            receipt = dispatch_command(msg)
            check(op + " native receipt " + expected, receipt["outcome"] == expected
                  and (code is None or receipt.get("error", {}).get("code") == code), receipt)
        finally:
            if lease:
                reply = manager.release(protocol.message("lease.release", {"lease_id": lease}), owner)
                assert reply is None, reply
        return receipt, msg

    def near(actual, wanted, tolerance=2e-6):
        return len(actual) == len(wanted) and all(math.isclose(a, b, abs_tol=tolerance, rel_tol=1e-5)
                                                for a, b in zip(actual, wanted, strict=True))

    def normalized(records_):
        return {oid: {key: value for key, value in record.items() if key != "generation"}
                for oid, record in records_.items()}

    if args.phase == "reopen":
        saved = json.loads(metadata.read_text(encoding="utf-8"))
        check("native object UUIDs/meshes/transforms persist through fresh reopen", normalized(records()) == saved["records"])
        check("native document identity persists with a new open epoch", doc.id == saved["document_id"]
              and doc.open_epoch != saved["open_epoch"])
        old = payload("object.move", saved["targets"]["cube"], {"by": [.01, 0, 0]})
        old["open_epoch"] = saved["open_epoch"]
        run("object.move", expected="rejected", code="wrong_document", custom=old)
        oid = saved["targets"]["cylinder"]
        before = list(sync.find_object(oid).matrix_world.translation)
        run("object.move", oid, {"by": [0, .01, 0]})
        actual = [value * args.unit_scale for value in sync.find_object(oid).matrix_world.translation]
        check("fresh reopen typed re-edit uses the exact selected UUID", near(actual, [before[0] * args.unit_scale,
              before[1] * args.unit_scale + .01, before[2] * args.unit_scale]))
        run("document.save")
        check("fresh reopen Save leaves no live edit permission", not sess.store.leases())
        return

    run("document.save", expected="rejected", code="failed")
    targets = {}
    for primitive in ("cube", "sphere", "cylinder"):
        for size in (.02, .05, .1):
            receipt, _ = run("object.add", values={"primitive": primitive, "location": [0, 0, 0], "dimensions": [size] * 3})
            oid = receipt["created"][0]
            native = sync.find_object(oid)
            check(f"{primitive} {size}m native dimensions and explicit UUID",
                  near([value * args.unit_scale for value in native.dimensions], [size] * 3)
                  and oid in records() and len(records()[oid]["mesh"]["indices"]) > 0)
            if size == .05:
                targets[primitive] = oid
    check("all primitive/size combinations are distinct native UUIDs", len(records()) == 9)

    identity_matrix = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    for primitive, oid in targets.items():
        untouched = {key: record for key, record in normalized(records()).items() if key != oid}
        for axis_index, axis in enumerate("XYZ"):
            for step in (.001, .01, .1):
                for sign in (1, -1):
                    before = [value * args.unit_scale for value in sync.find_object(oid).matrix_world.translation]
                    delta = [0, 0, 0]
                    delta[axis_index] = sign * step
                    run("object.move", oid, {"by": delta})
                    wanted = [a + b for a, b in zip(before, delta, strict=True)]
                    check(f"{primitive} {sign * step}m world {axis}", near(
                        [value * args.unit_scale for value in sync.find_object(oid).matrix_world.translation], wanted))
        expected_rotation = identity_matrix
        for axis in "XYZ":
            for degrees in (15, 45, 90):
                for sign in (1, -1):
                    angle = math.radians(degrees * sign)
                    run("object.rotate", oid, {"by": {"axis": axis, "angle": angle}})
                    expected_rotation = multiply(rotation_matrix(axis, angle), expected_rotation)
                    native = sync.find_object(oid).matrix_world.to_3x3()
                    check(f"{primitive} {sign * degrees}deg world {axis}", near(
                        [native[i][j] for i in range(3) for j in range(3)],
                        [value for row in expected_rotation for value in row], 2e-5))
        for factor in (1.1, 1 / 1.1):
            before = [abs(value) for value in sync.find_object(oid).matrix_world.to_scale()]
            run("object.scale", oid, {"by": [factor] * 3})
            check(f"{primitive} native uniform scale {factor}", near(
                list(sync.find_object(oid).matrix_world.to_scale()), [factor * value for value in before]))
        check(primitive + " actions preserve every other explicit native UUID",
              {key: record for key, record in normalized(records()).items() if key != oid} == untouched)

    cube = targets["cube"]
    run("object.rotate", cube, {"by": {"axis": "Z", "angle": math.pi / 4}})
    run("object.rotate", cube, {"by": {"axis": "X", "angle": math.pi / 12}})
    wanted = multiply(rotation_matrix("X", math.pi / 12), rotation_matrix("Z", math.pi / 4))
    native = sync.find_object(cube).matrix_world.to_3x3()
    check("composite turns use world axes rather than local axes", near(
        [native[i][j] for i in range(3) for j in range(3)], [value for row in wanted for value in row], 2e-5))
    run("object.move", cube, {"by": [.01, 0, 0]})
    check("move remains world-axis after object rotation", near(
        [value * args.unit_scale for value in sync.find_object(cube).matrix_world.translation], [.01, 0, 0]))

    receipt, sent = run("object.move", cube, {"by": [.001, 0, 0]})
    before, revision = normalized(records()), doc.revision
    repeated = dispatch_command(sent)
    check("exact request replay returns the stored receipt without repeating geometry", repeated == receipt
          and normalized(records()) == before and doc.revision == revision)
    changed = json.loads(json.dumps(sent))
    changed["payload"]["args"] = {"by": [.1, 0, 0]}
    refused = dispatch_command(changed)
    check("changed-payload request ID is rejected without native mutation", refused["outcome"] == "rejected"
          and refused["error"]["code"] == "duplicate_request" and normalized(records()) == before)
    stale = payload("object.move", cube, {"by": [.1, 0, 0]})
    run("object.move", cube, {"by": [.001, 0, 0]})
    before = normalized(records())
    run("object.move", expected="rejected", code="stale_revision", custom=stale)
    check("stale target generation changes no native object", normalized(records()) == before)
    stale = payload("history.undo")
    stale["base_revision"] = 0
    run("history.undo", expected="rejected", code="stale_revision", custom=stale)
    check("stale Undo revision changes no native object", normalized(records()) == before)

    native = sync.find_object(cube)
    native.select_set(True)
    bpy.context.view_layer.objects.active = native
    bpy.ops.object.mode_set(mode="EDIT")
    run("object.move", cube, {"by": [.1, 0, 0]}, expected="rejected", code="failed")
    bpy.ops.object.mode_set(mode="OBJECT")
    check("wrong-mode refusal preserves native transforms", normalized(records()) == before)
    granted = manager.acquire(protocol.message("lease.acquire", {**identity(peer), "mode": "shared", "targets": [cube]}), peer)
    held = granted["payload"]["lease"]["lease_id"]
    run("object.move", cube, {"by": [.1, 0, 0]}, expected="rejected", code="lease_conflict", leased=False)
    check("competing target lease changes no geometry", normalized(records()) == before)
    manager.release(protocol.message("lease.release", {"lease_id": held}), peer)

    for primitive, oid in targets.items():
        before = normalized(records())
        run("object.delete", oid)
        check(primitive + " Delete removes only its explicit UUID", oid not in records() and set(records()) == set(before) - {oid})
        run("history.undo")
        check(primitive + " Undo restores original native UUID and geometry", normalized(records()) == before)
        run("history.redo")
        check(primitive + " Redo deletes original target again", oid not in records())
        run("history.undo")
        check(primitive + " final Undo restores the saved target", normalized(records()) == before)

    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    doc.saved()
    run("document.save")
    saved = {"document_id": doc.id, "open_epoch": doc.open_epoch, "targets": targets, "records": normalized(records())}
    metadata.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    check("all nine native objects are persisted without a live lease", len(saved["records"]) == 9
          and path.is_file() and not sess.store.leases())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--private-profile", required=True, type=Path)
    parser.add_argument("--unit-scale", type=float, required=True)
    parser.add_argument("--phase", choices=("create", "reopen"), required=True)
    parser.add_argument("--extension", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    report = {"phase": args.phase, "unit_scale": args.unit_scale, "checks": [], "receipts": [], "passed": False,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "limits": {"button_delivery": False, "capture": False, "os_input": False, "headset": False, "socket": False}}
    code = 0
    try:
        main(args, report)
        report["passed"] = True
    except Exception:  # noqa: BLE001 - retain exact native failures and return nonzero
        report["error"] = traceback.format_exc()
        traceback.print_exc()
        code = 1
    finally:
        (args.output / f"object-{args.phase}-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("P25_NATIVE_OBJECT_ACTIONS", "PASS" if code == 0 else "FAIL", args.phase, len(report["checks"]), flush=True)
    sys.exit(code)

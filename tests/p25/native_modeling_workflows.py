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

import bmesh
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
    path, metadata = args.output / "numeric-common-workflows.blend", args.output / "numeric-common-workflows.json"
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
        entry = {"name": name, "method": report.get("active_method", "typed command"), "passed": bool(okay)}
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


    def native_step(name):
        doc.edited()
        records()
        bpy.ops.ed.undo_push(message=name)

    def qmultiply(a, b):
        aw, ax, ay, az = a
        bw, bx, by, bz = b
        return [aw * bw - ax * bx - ay * by - az * bz,
                aw * bx + ax * bw + ay * bz - az * by,
                aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw]

    def euler_oracle(degrees):
        x, y, z = [math.radians(value) for value in degrees]
        qx = [math.cos(x / 2), math.sin(x / 2), 0, 0]
        qy = [math.cos(y / 2), 0, math.sin(y / 2), 0]
        qz = [math.cos(z / 2), 0, 0, math.sin(z / 2)]
        return qmultiply(qz, qmultiply(qy, qx)), multiply(rotation_matrix("Z", z),
                multiply(rotation_matrix("Y", y), rotation_matrix("X", x)))

    def basis_matches(oid, rotation, scale):
        native = sync.find_object(oid).matrix_world.to_3x3()
        return near([native[i][j] for i in range(3) for j in range(3)],
                    [rotation[i][j] * scale[j] for i in range(3) for j in range(3)], 2e-5)

    if args.phase == "reopen":
        saved = json.loads(metadata.read_text(encoding="utf-8"))
        check("exact transforms and common native mesh geometry persist", normalized(records()) == saved["records"])
        check("saved document UUID persists with a fresh open epoch", doc.id == saved["document_id"] and doc.open_epoch != saved["open_epoch"])
        mesh = sync.find_object(saved["mesh_id"])
        check("native common mesh remains editable after reopen", len(mesh.data.vertices) == saved["mesh_vertices"]
              and len(mesh.data.polygons) == saved["mesh_faces"] and saved["mesh_faces"] > 6)
        target = saved["targets"]["sphere"]
        wanted = [-.0123456, .0076543, -.002468]
        run("object.move", target, {"to": wanted})
        check("fresh reopen numeric absolute move reaches exact native target", near(
            [value * args.unit_scale for value in sync.find_object(target).matrix_world.translation], wanted))
        run("document.save")
        check("fresh reopen has no leaked native permission", not sess.store.leases())
        return

    targets = {}
    location, dimensions = [-.012345, .006789, -.00321], [.013, .027, .039]
    for primitive in ("cube", "sphere", "cylinder"):
        done, _ = run("object.add", values={"primitive": primitive, "location": location, "dimensions": dimensions})
        oid = targets[primitive] = done["created"][0]
        native = sync.find_object(oid)
        check(primitive + " custom numeric location/dimensions", near([v * args.unit_scale for v in native.matrix_world.translation], location)
              and near([v * args.unit_scale for v in native.dimensions], dimensions))
        wanted = [-.004321, .012345, -.000125]
        run("object.move", oid, {"to": wanted})
        delta = [.000111, -.000222, .000333]
        run("object.move", oid, {"by": delta})
        wanted = [a + b for a, b in zip(wanted, delta, strict=True)]
        check(primitive + " fractional signed world position", near(
            [v * args.unit_scale for v in sync.find_object(oid).matrix_world.translation], wanted))
        quaternion, rotation = euler_oracle([23, -37, 61])
        run("object.rotate", oid, {"to": quaternion})
        check(primitive + " absolute native EulerXYZ qz*qy*qx", basis_matches(oid, rotation, [1, 1, 1]))
        angle = -math.pi / 7
        run("object.rotate", oid, {"by": {"axis": "Y", "angle": angle}})
        rotation = multiply(rotation_matrix("Y", angle), rotation)
        check(primitive + " world-axis turn on nontrivial native rotation", basis_matches(oid, rotation, [1, 1, 1]))
        scale = [.75, 1.25, 2.5]
        run("object.scale", oid, {"to": scale})
        check(primitive + " absolute nonuniform scale on rotated target", basis_matches(oid, rotation, scale))
        by = [1.1, .8, 1.4]
        run("object.scale", oid, {"by": by})
        scale = [a * b for a, b in zip(scale, by, strict=True)]
        check(primitive + " multiplicative independent-axis scale", basis_matches(oid, rotation, scale))
        quaternion, rotation = euler_oracle([-11, 28, -53])
        run("object.rotate", oid, {"to": quaternion})
        check(primitive + " absolute rotation preserves existing nonuniform scale and world position",
              basis_matches(oid, rotation, scale)
              and near([v * args.unit_scale for v in sync.find_object(oid).matrix_world.translation], wanted))

    cube = targets["cube"]
    before = normalized(records())
    invalid = (("object.move", {"to": [1001, 0, 0]}), ("object.move", {"by": ["bad", 0, 0]}),
               ("object.scale", {"to": [0, 1, 1]}), ("object.scale", {"by": [-1, 1, 1]}))
    for op, values in invalid:
        error = commander.command(protocol.message("command", payload(op, cube, values)), owner)
        check("invalid numeric arguments refuse before native mutation: " + op,
              error["type"] == "error" and error["payload"]["code"] == "invalid_message" and normalized(records()) == before)
    for value in (math.nan, math.inf, -math.inf):
        try:
            protocol.encode(protocol.message("command", payload("object.move", cube, {"to": [value, 0, 0]})))
            raise AssertionError("nonfinite numeric JSON was encoded")
        except protocol.ProtocolError:
            check("nonfinite numeric JSON refuses before dispatch", normalized(records()) == before)
    run("object.rotate", cube, {"to": [0, 0, 0, 0]}, expected="rejected", code="failed")
    absent = payload("object.move", cube, {"to": [0, 0, 0]})
    absent["target"]["id"] = uuid.uuid4().hex
    run("object.move", expected="rejected", code="not_found", custom=absent)
    stale = payload("object.scale", cube, {"to": [1, 1, 1]})
    stale["target"]["generation"] -= 1
    run("object.scale", expected="rejected", code="stale_revision", custom=stale)
    check("numeric/unit/target rejections preserve all native objects", normalized(records()) == before)
    grant = manager.acquire(protocol.message("lease.acquire", {**identity(peer), "mode": "shared", "targets": [cube]}), peer)
    lease = grant["payload"]["lease"]["lease_id"]
    run("object.move", cube, {"to": [0, 0, 0]}, expected="rejected", code="lease_conflict", leased=False)
    manager.release(protocol.message("lease.release", {"lease_id": lease}), peer)
    sync.find_object(cube).select_set(True)
    bpy.context.view_layer.objects.active = sync.find_object(cube)
    bpy.ops.object.mode_set(mode="EDIT")
    run("object.scale", cube, {"to": [1, 1, 1]}, expected="rejected", code="failed")
    bpy.ops.object.mode_set(mode="OBJECT")
    done, message = run("object.move", cube, {"by": [.000123, 0, 0]})
    once = normalized(records())
    check("numeric command replay applies once", dispatch_command(message) == done and normalized(records()) == once)

    done, _ = run("object.add", values={"primitive": "cube", "location": [.2, 0, 0], "dimensions": [.02, .02, .02]})
    mesh_id = done["created"][0]
    window = bpy.context.window or bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    report["native_operator_context"] = {"previous_area": bpy.context.area.type if bpy.context.area else None,
                                         "mode": bpy.context.mode, "override_editor": "VIEW_3D", "region": "WINDOW"}
    with bpy.context.temp_override(window=window, area=area, region=region):
        report["active_method"] = "native bpy operator"

        def activate():
            bpy.ops.object.select_all(action="DESELECT")
            native = sync.find_object(mesh_id)
            native.select_set(True)
            bpy.context.view_layer.objects.active = native
            return native

        revision = doc.revision
        bpy.ops.object.select_all(action="SELECT")
        check("native Select All selects all objects", len(bpy.context.selected_objects) == 4)
        bpy.ops.object.select_all(action="INVERT")
        check("native Invert selection deselects the complete set", not bpy.context.selected_objects)
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.select_all(action="DESELECT")
        check("native Deselect changes no shared geometry", not bpy.context.selected_objects and records() and doc.revision == revision)
        activate()
        bpy.ops.object.duplicate()
        duplicate_id = sync.object_id(bpy.context.object)
        native_step("Native common Duplicate")
        check("native Duplicate has its own synchronized UUID", duplicate_id != mesh_id and len(records()) == 5)
        bpy.ops.object.delete()
        native_step("Native common Delete object")
        check("native Delete removes only the duplicate", duplicate_id not in records() and mesh_id in records() and len(records()) == 4)
        activate()
        bpy.ops.object.hide_view_set(unselected=False)
        native_step("Native Hide")
        check("native Hide reaches synchronized visibility", not records()[mesh_id]["visible"])
        bpy.ops.object.hide_view_clear(select=False)
        native_step("Native Unhide")
        check("native Unhide reaches synchronized visibility", records()[mesh_id]["visible"])
        native = activate()
        native.rotation_euler.z = .3
        native.scale = (1.2, .8, 1.1)
        native_step("Native transform setup")
        def world_vertices(obj):
            return sorted(tuple(round(value * args.unit_scale, 6) for value in obj.matrix_world @ vertex.co) for vertex in obj.data.vertices)
        vertices = world_vertices(native)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        native_step("Native Apply Rotation Scale")
        check("native Apply Rotation/Scale preserves world geometry", world_vertices(sync.find_object(mesh_id)) == vertices
              and near(list(sync.find_object(mesh_id).scale), [1, 1, 1]))
        bpy.ops.object.shade_smooth()
        native_step("Native Shade Smooth")
        check("native Shade Smooth changes normals in synchronized geometry", all(face.use_smooth for face in sync.find_object(mesh_id).data.polygons)
              and len(records()[mesh_id]["mesh"]["positions"]) // 3 == 8)

        def edit_operation(name, function):
            native = activate()
            bpy.ops.object.mode_set(mode="EDIT")
            function(native)
            bm = bmesh.from_edit_mesh(native.data)
            expected = sum(len(face.verts) - 2 for face in bm.faces)
            counts = (len(bm.verts), len(bm.faces))
            check(name + " completes and its live native mesh reaches sync", len(records()[mesh_id]["mesh"]["indices"]) // 3 == expected,
                  {"native_vertices": counts[0], "native_faces": counts[1], "expected_triangles": expected})
            bpy.ops.object.mode_set(mode="OBJECT")
            native_step(name)
            return counts

        def select_top(native):
            bpy.ops.mesh.select_mode(type="FACE")
            bpy.ops.mesh.select_all(action="DESELECT")
            bm = bmesh.from_edit_mesh(native.data)
            top = max(bm.faces, key=lambda face: face.calc_center_median().z)
            top.select_set(True)
            bm.select_flush_mode()
            bmesh.update_edit_mesh(native.data)

        def extrude(native):
            select_top(native)
            assert "FINISHED" in bpy.ops.mesh.extrude_region_move(TRANSFORM_OT_translate={"value": (0, 0, .005 / args.unit_scale)})
        counts = edit_operation("Native Extrude", extrude)
        check("native Extrude creates real new faces", counts[0] > 8 and counts[1] > 6)
        def inset(native):
            select_top(native)
            assert "FINISHED" in bpy.ops.mesh.inset(thickness=.001 / args.unit_scale, depth=0)
        after = edit_operation("Native Inset", inset)
        check("native Inset creates real new topology", after[0] > counts[0] and after[1] > counts[1])
        counts = after
        def bevel(_native):
            bpy.ops.mesh.select_mode(type="EDGE")
            bpy.ops.mesh.select_all(action="SELECT")
            assert "FINISHED" in bpy.ops.mesh.bevel(offset=.0002 / args.unit_scale, segments=1, affect="EDGES")
        after = edit_operation("Native Bevel", bevel)
        check("native Bevel creates real new topology", after[0] > counts[0] and after[1] > counts[1])
        counts = after
        def subdivide(_native):
            bpy.ops.mesh.select_all(action="SELECT")
            assert "FINISHED" in bpy.ops.mesh.subdivide(number_cuts=1)
        after = edit_operation("Native Subdivide", subdivide)
        check("native Subdivide creates real new topology", after[0] > counts[0] and after[1] > counts[1])
        solid = normalized(records())
        def merge(_native):
            bpy.ops.mesh.select_all(action="SELECT")
            assert "FINISHED" in bpy.ops.mesh.merge(type="CENTER")
        merged = edit_operation("Native Merge", merge)
        check("native Merge combines selected vertices", merged == (1, 0))
        bpy.ops.ed.undo()
        check("native Undo restores complete pre-Merge mesh and UUID", normalized(records()) == solid)
        bpy.ops.ed.redo()
        check("native Redo restores Merge result", len(sync.find_object(mesh_id).data.vertices) == 1)
        bpy.ops.ed.undo()
        check("native Undo preserves modeled solid for further editing", normalized(records()) == solid)
        def delete_mesh(_native):
            bpy.ops.mesh.select_all(action="SELECT")
            assert "FINISHED" in bpy.ops.mesh.delete(type="VERT")
        deleted = edit_operation("Native Delete mesh vertices", delete_mesh)
        check("native mesh Delete removes selected mesh data", deleted == (0, 0))
        bpy.ops.ed.undo()
        check("native Undo restores deleted mesh geometry", normalized(records()) == solid)
        bpy.ops.ed.redo()
        check("native Redo removes mesh geometry again", len(sync.find_object(mesh_id).data.vertices) == 0)
        bpy.ops.ed.undo()
        check("native Undo leaves editable modeled geometry intact", normalized(records()) == solid)
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    doc.saved()
    report["active_method"] = "typed command"
    run("document.save")
    native = sync.find_object(mesh_id)
    metadata.write_text(json.dumps({"document_id": doc.id, "open_epoch": doc.open_epoch, "targets": targets,
                        "mesh_id": mesh_id, "mesh_vertices": len(native.data.vertices), "mesh_faces": len(native.data.polygons),
                        "records": normalized(records())}, indent=2), encoding="utf-8")
    check("exact numeric objects and native modeled mesh save without leaked leases", not sess.store.leases() and path.is_file())


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
        (args.output / f"modeling-{args.phase}-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("P25_NATIVE_MODELING_WORKFLOWS", "PASS" if code == 0 else "FAIL", args.phase, len(report["checks"]), flush=True)
    sys.exit(code)

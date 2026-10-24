"""Underlying native preview workflows in private background Blender only.

These are actual native operations and host handlers, not mouse/button/hover,
Windows focus, capture, modal event-loop, Player or headset acceptance.
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
from types import SimpleNamespace

import bpy

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
from native_spatial_gate import setup


class Connection:
    def __init__(self):
        self.joined = self.can_edit = self.closing = False
        self.listener = SimpleNamespace(roles=("vr",))
        self.messages = []

    def send(self, *messages):
        self.messages.extend(messages)

    def close(self):
        self.closing = True


class LocalDispatch:
    """Actual handlers/session, deliberately no sockets, timers or listeners."""
    def __init__(self):
        self.handlers = {}
        self.on_disconnect = None
        self.messages = []
        self.connections = []

    def broadcast(self, message, exclude=None):
        self.messages.append(message)
        for connection in self.connections:
            if connection is not exclude and not connection.closing:
                connection.send(message)


def main(args, report):
    assert bpy.app.background, "This gate must never open an interactive Blender"
    profile = args.private_profile.resolve()
    assert profile.is_relative_to(args.output.resolve()), "Private profile must be inside this evidence directory"
    for name, value in os.environ.items():
        if name.upper().startswith("BLENDER_USER_") or name.upper() in ("TEMP", "TMP", "TMPDIR"):
            assert value and Path(value).resolve().is_relative_to(profile), f"Nonprivate child environment: {name}"
    # Blender/another startup import may already have cached tempfile's choice.
    # Reset it before the pinned CAD logger opens its default FileHandler.
    tempfile.tempdir = str(profile / "temp")
    assert Path(tempfile.gettempdir()).resolve().is_relative_to(profile)
    assert Path(bpy.app.tempdir).resolve().is_relative_to(profile), "Blender startup temp directory escaped the profile"
    report["isolation"] = {"profile": str(profile), "tempfile_directory": tempfile.gettempdir(),
                           "blender_temp_directory": bpy.app.tempdir,
                           "dont_write_bytecode": sys.dont_write_bytecode, "cad_file_handlers": []}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if args.without_cad:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "blender_addon"))
        report["identity"] = {"blender": bpy.app.version_string, "cad_enabled": False}
    else:
        report["identity"] = setup(args)
    from spatial_modeling import (
        commands,
        document,
        edits,
        host,
        leases,
        preview_spatial,
        protocol,
        session,
        sketch,
        sync,
    )

    report["identity"].update(process_id=os.getpid(), background=bpy.app.background,
                              addon_source=str(Path(host.__file__).parent), **sketch.dependency_status())
    if not args.without_cad:
        handlers = [Path(handler.baseFilename).resolve() for handler in logging.getLogger("CAD_Sketcher").handlers
                    if isinstance(handler, logging.FileHandler)]
        assert handlers and all(path.is_relative_to(profile) for path in handlers), handlers
        assert all(path.is_file() for path in handlers), handlers
        report["isolation"]["cad_file_handlers"] = [str(path) for path in handlers]
    report["limits"] = {"button_delivery": False, "mouse_hover": False, "os_focus": False,
                       "native_modal_event_loop": False, "headset": False, "server_socket": False}
    assert report["identity"]["available"] != args.without_cad, report["identity"]
    path, metadata = args.output / "native-preview.blend", args.output / "native-preview.json"
    if args.phase == "reopen":
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    else:
        bpy.context.scene.unit_settings.system = "METRIC"
        bpy.context.scene.unit_settings.scale_length = args.unit_scale
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex,
                           capabilities=lambda: {"sketch": sketch.dependency_status()["available"], "preview_spatial": True})
    dispatch = LocalDispatch()
    sess.attach(dispatch)
    sync.register()
    sync.start(doc, sess)
    sync.flush()
    editor = edits.Editor(sync, host.undoable, doc)
    lease_manager = leases.Leases(sess, editor)
    command_manager = commands.Commands(sess, editor, leases=lease_manager)
    command_manager.attach(dispatch)
    lease_manager.attach(dispatch)
    preview_spatial.attach(dispatch, sess, lease_manager)
    bpy.context.preferences.edit.use_global_undo = True
    bpy.ops.ed.undo_push(message="P2.5 underlying native workflow baseline")

    def check(label, okay=True, details=None):
        entry = {"name": label, "passed": bool(okay)}
        if details is not None:
            entry["details"] = details
        report["checks"].append(entry)
        assert okay, entry

    def snapshot():
        bpy.context.view_layer.update()
        sync.flush()
        return sync.snapshot(doc.describe())

    def objects():
        return {record["id"]: record for record in snapshot()["objects"]}

    def native_step(label):
        doc.edited()
        result = snapshot()
        bpy.ops.ed.undo_push(message=label)
        return result

    def join(name):
        connection = Connection()
        dispatch.connections.append(connection)
        sess.hello(protocol.message("hello", {"role": "vr", "name": name,
                   "app": {"name": "P2.5 isolated native gate", "version": "0.1.0"}}), connection)
        check("actual session welcome " + name, connection.joined)
        welcome = next(message["payload"] for message in connection.messages if message["type"] == "welcome")
        return connection, welcome

    owner, welcome = join("Native preview owner")
    peer, peer_welcome = join("Competing editor")

    def identity(w=welcome):
        return {"session_id": w["session_id"], "host_epoch": w["host_epoch"],
                "document_id": w["document"]["id"], "open_epoch": w["document"]["open_epoch"],
                "actor_id": w["actor_id"]}

    def native_request(kind, payload=None, connection=owner):
        msg = protocol.message(kind, payload or {})
        return dispatch.handlers[kind](msg, connection)

    def normalized(record):
        return {key: value for key, value in record.items() if key != "generation"}

    current = native_request("preview.state.query")["payload"]
    check("real native context reports exact background process/document",
          current["process_id"] == os.getpid() and current["document_id"] == doc.id
          and current["open_epoch"] == doc.open_epoch and current["mode"] == "OBJECT")
    check("real native modal introspection is available",
          all(hasattr(window, "modal_operators") for window in bpy.context.window_manager.windows),
          current["modal_operators"])
    check("native CAD capability matches actual dependency state", current["available"] != args.without_cad
          and welcome["capabilities"]["sketch"] != args.without_cad)

    if args.phase == "reopen":
        saved = json.loads(metadata.read_text(encoding="utf-8"))
        check("document UUID persists and open epoch changes",
              doc.id == saved["document_id"] and doc.open_epoch != saved["open_epoch"])
        actual = {oid: normalized(record) for oid, record in objects().items()}
        check("all native object UUIDs/names/transforms/material/modifier meshes reopen unchanged",
              actual == saved["objects"])
        check("native CAD entity/constraint UUIDs reopen unchanged", sketch.snapshot() == saved["sketches"])
        old = identity()
        old["open_epoch"] = saved["open_epoch"]
        refused = native_request("preview.ui.begin", old)
        check("old document-open epoch cannot authorize native UI", refused["type"] == "error"
              and refused["payload"]["code"] == "wrong_document")
        cube = sync.find_object(saved["cube_id"])
        cube.name += "・再編集"
        native_step("Reopened Unicode name edit")
        check("fresh native re-edit remains synchronized", objects()[saved["cube_id"]]["name"] == cube.name)
        report["passed"] = True
        return

    granted = native_request("preview.ui.begin", identity())
    check("actual native UI reservation grants host-desktop lease", granted["type"] == "preview.ui.granted"
          and granted["payload"]["input_allowed"]
          and sess.store.leases()[0]["owner"] == sess.host)
    check("host desktop native operations are admitted", lease_manager.may_write(whole=True) is None)
    if args.without_cad:
        check("ordinary native preview remains admitted without CAD Sketcher",
              native_request("preview.state.query")["payload"]["input_allowed"]
              and not native_request("preview.state.query")["payload"]["available"])
    denied = native_request("preview.ui.begin", identity(peer_welcome), peer)
    check("competing native UI owner is denied", denied["type"] == "error"
          and denied["payload"]["code"] == "lease_conflict")
    payload = {**identity(peer_welcome), "base_revision": doc.revision, "source": "ui", "op": "object.add",
               "args": {"primitive": "cube", "location": [0, 0, 0], "dimensions": [.01, .01, .01]}}
    command_manager.command(protocol.message("command", payload), peer)
    denied = peer.messages[-1]
    check("real command dispatcher refuses a supported competing edit", denied["type"] == "result"
          and denied["payload"]["outcome"] == "rejected" and denied["payload"]["error"]["code"] == "lease_conflict")
    unit = float(f"{bpy.context.scene.unit_settings.scale_length:.7g}")
    bpy.ops.mesh.primitive_cube_add(size=.02 / unit)
    cube = bpy.context.object
    native_step("Native Add Cube")
    cube_id = sync.object_id(cube)
    check("native Add Cube exports complete geometry", objects()[cube_id]["mesh"] is not None)

    cube.name = "P2.5 Café 接続 🔧"
    native_step("Native Unicode rename")
    check("native Unicode name synchronizes with stable UUID", objects()[cube_id]["name"] == cube.name
          and sync.object_id(cube) == cube_id)
    bpy.ops.transform.translate(value=(.01 / unit, -.02 / unit, .03 / unit))
    native_step("Native Move")
    check("native move exports meters", objects()[cube_id]["transform"]["location"] == [.01, -.02, .03])
    bpy.ops.transform.rotate(value=math.pi / 2, orient_axis="Z")
    native_step("Native Rotate")
    rotation = objects()[cube_id]["transform"]["rotation"]
    check("native rotation exports expected quaternion", abs(rotation[0] - math.sqrt(.5)) < 1e-5
          and abs(rotation[3] - math.sqrt(.5)) < 1e-5 and abs(rotation[1]) + abs(rotation[2]) < 1e-5)
    bpy.ops.transform.resize(value=(2, .5, 1.5), orient_type="LOCAL")
    native_step("Native Scale")
    check("native scale exports independent axes", objects()[cube_id]["transform"]["scale"] == [2, .5, 1.5])
    revision = doc.revision
    bpy.ops.object.select_all(action="DESELECT")
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    check("native selection changes no shared geometry revision", snapshot()["document"]["revision"] == revision
          and bpy.context.view_layer.objects.active == cube and cube.select_get())
    cube.hide_set(True)
    native_step("Native Hide")
    check("native hide reaches synchronized visibility", objects()[cube_id]["visible"] is False)
    cube.hide_set(False)
    native_step("Native Show")
    check("native unhide reaches synchronized visibility", objects()[cube_id]["visible"] is True)

    before_triangles = len(objects()[cube_id]["mesh"]["indices"]) // 3
    modifier = cube.modifiers.new("Native Bevel", "BEVEL")
    modifier.width, modifier.segments = .001 / unit, 2
    native_step("Native Bevel Modifier")
    evaluated = cube.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    try:
        native_triangles = sum(len(polygon.vertices) - 2 for polygon in evaluated.polygons)
    finally:
        cube.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
    check("native modifier evaluated geometry reaches sync", native_triangles > before_triangles
          and len(objects()[cube_id]["mesh"]["indices"]) // 3 == native_triangles)
    material = bpy.data.materials.new("Native blue")
    material.use_nodes = True
    material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (.2, .4, .8, 1)
    cube.data.materials.append(material)
    native_step("Native Material Color")
    check("native material Base Color reaches sync", objects()[cube_id]["color"] == [.2, .4, .8, 1])

    cube.select_set(True)
    bpy.ops.object.duplicate()
    duplicate = bpy.context.object
    native_step("Native Duplicate")
    duplicate_id = sync.object_id(duplicate)
    check("native duplicate receives distinct stable UUID", duplicate_id != cube_id and cube_id in objects())
    bpy.ops.object.delete()
    native_step("Native Delete")
    check("native delete removes only duplicate", duplicate_id not in objects() and cube_id in objects()
          and any(duplicate_id in msg["payload"].get("removed", []) for msg in dispatch.messages))
    cube = sync.find_object(cube_id)
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    cube.modifiers["Native Bevel"].show_viewport = False
    native_step("Native Modifier Viewport Toggle")
    bpy.ops.object.mode_set(mode="EDIT")
    editing = native_request("preview.state.query")["payload"]
    check("real native Edit Mode is reported safely", editing["mode"] == "EDIT_MESH"
          and editing["process_id"] == os.getpid() and editing["input_allowed"])
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.subdivide(number_cuts=1)
    in_edit_mode = snapshot()["objects"]
    edit_record = next(record for record in in_edit_mode if record["id"] == cube_id)
    check("native completed mesh edit reaches sync while Edit Mode remains active",
          len(edit_record["mesh"]["indices"]) // 3 == 48,
          {"expected_subdivided_cube_triangles": 48, "actual_wire_triangles": len(edit_record["mesh"]["indices"]) // 3})
    bpy.ops.object.mode_set(mode="OBJECT")
    native_step("Return to native Object Mode")

    # Workspace/editor controls are native presentation state, distinct from
    # shared geometry. Do not claim their mouse-accessibility from these reads.
    if not args.without_cad:
        window = bpy.context.window_manager.windows[0]
        area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
        region = next(region for region in area.regions if region.type == "WINDOW")
        revision = doc.revision
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name="builtin.move")
            state = native_request("preview.state.query")["payload"]
            check("actual built-in toolbar tool is reflected in native telemetry", state["native_tool"] == "builtin.move"
                  and state["tool"] == "" and state["input_allowed"])
            area.spaces.active.show_region_ui = not area.spaces.active.show_region_ui
            area.spaces.active.overlay.show_overlays = not area.spaces.active.overlay.show_overlays
            check("native sidebar/overlay controls leave shared geometry unchanged", snapshot()["document"]["revision"] == revision)
            bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
            check("actual native Select toolbar tool is reflected", native_request("preview.state.query")["payload"]["tool"] == "select")

    previous_name = cube.name
    cube.name = "Native Undo checkpoint"
    native_step("Native Rename Undo Checkpoint")
    check("native Undo is available in private background scene", bpy.ops.ed.undo.poll())
    bpy.ops.ed.undo()
    sync.flush()
    check("native Undo restores name and stable UUID", objects()[cube_id]["name"] == previous_name)
    bpy.ops.ed.redo()
    sync.flush()
    check("native Redo restores renamed object", objects()[cube_id]["name"] == "Native Undo checkpoint")

    ui_token = granted["payload"]["ui_session_id"]
    end = native_request("preview.ui.end", {**identity(), "ui_session_id": ui_token})
    check("actual nonmodal native reservation ends and releases", end["type"] == "preview.ui.ended"
          and not end["payload"]["input_allowed"] and sess.store.leases() == [])
    check("supported command admission resumes after native UI release",
          lease_manager.check(welcome["actor_id"], "object.move", cube_id) is None)
    granted = native_request("preview.ui.begin", identity())
    dispatch.on_disconnect(owner)
    check("actual native disconnect releases a nonmodal reservation", not sess.store.leases()
          and not dispatch.preview_ui.state(peer)["input_allowed"])

    if not args.without_cad:
        valid_id = editor.apply("sketch.create", None, {"plane": "XY"}).created[0]
        editor.apply("sketch.add_line", valid_id, {"start": [0, 0], "end": [.04, .02]})
        invalid_id = editor.apply("sketch.create", None, {"plane": "XZ"}).created[0]
        editor.apply("sketch.add_circle", invalid_id, {"center": [.01, .02], "radius": .005})
        invalid = sketch.find(invalid_id)
        invalid.scale = (2, 1, 1)
        snapshot()
        check("one unsupported native sketch is isolated and explicitly reported",
              sync.generation(invalid_id) is None and sync.generation(valid_id) is not None
              and cube_id in objects() and any(problem["id"] == invalid_id for problem in sketch.snapshot_problems()))
        cube = sync.find_object(cube_id)
        cube.location.x += .005 / unit
        native_step("Ordinary object update beside unsupported sketch")
        check("ordinary native updates continue beside unsupported sketch",
              objects()[cube_id]["transform"]["location"] == [.015, -.02, .03])
        invalid.scale = (1, 1, 1)
        snapshot()
        check("restored native sketch resumes synchronization", sync.generation(invalid_id) is not None)

    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    doc.saved()
    check("native Save As creates a real isolated file", path.is_file() and path.stat().st_size > 512)
    before = {oid: normalized(record) for oid, record in objects().items()}
    metadata.write_text(json.dumps({"document_id": doc.id, "open_epoch": doc.open_epoch,
                                   "cube_id": cube_id, "objects": before, "sketches": sketch.snapshot()},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
    bpy.ops.wm.save_mainfile()
    check("native Save persists the existing isolated document", path.stat().st_size > 512)
    report["passed"] = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--phase", choices=("create", "reopen"), required=True)
    parser.add_argument("--unit-scale", type=float, default=1)
    parser.add_argument("--without-cad", action="store_true")
    parser.add_argument("--private-profile", required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"phase": args.phase, "unit_scale": args.unit_scale, "checks": [], "passed": False,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    code = 0
    try:
        main(args, report)
    except Exception:  # noqa: BLE001 - preserve the exact native failure and return nonzero
        report["error"] = traceback.format_exc()
        traceback.print_exc()
        code = 1
    finally:
        (args.output / f"preview-{args.phase}-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("P25_NATIVE_PREVIEW", "PASS" if code == 0 else "FAIL", args.phase, len(report["checks"]), flush=True)
    sys.exit(code)

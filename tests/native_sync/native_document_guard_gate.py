"""Headless admission/security/portable-resource checks for native checkpoints."""
import json
import sys
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
from spatial_modeling.native_sync.document import (
    NativeDocument,
    NativeDocumentBusy,
    NativeDocumentError,
    _validate_script_drivers,
)

out = Path(sys.argv[sys.argv.index("--") + 1])
out.mkdir(parents=True, exist_ok=True)
report = {"passed": False, "checks": [], "headless": bpy.app.background}
try:
    document = NativeDocument()
    original_path = bpy.data.filepath
    image = bpy.data.images.new("NativeSync_UnpackedInput", width=2, height=2)
    try:
        document.capture(out / "unpacked.blend")
        raise AssertionError("Unpacked native resource was silently omitted")
    except NativeDocumentError as error:
        assert "Pack image" in str(error)
    assert image.packed_file is None and bpy.data.filepath == original_path
    assert not (out / "unpacked.blend").exists()
    bpy.data.images.remove(image)
    report["checks"].append("unpacked image input fails closed before output or original document mutation")
    material = bpy.data.materials.new("NativeSync_DriverGuard")
    material.use_nodes = True
    node = material.node_tree.nodes.new("ShaderNodeValue")
    driver = node.outputs[0].driver_add("default_value").driver
    variable = driver.variables.new()
    variable.name, variable.type = "native_value", "SINGLE_PROP"
    variable.targets[0].id = bpy.data.objects["Cube"]
    bpy.data.objects["Cube"]["native_guard_value"] = .5
    variable.targets[0].data_path = '["native_guard_value"]'
    driver.expression = "native_value * 10"
    _validate_script_drivers([material])
    driver.expression = "__import__('os').getpid()"
    try:
        _validate_script_drivers([material])
        raise AssertionError("General Python driver was silently admitted")
    except NativeDocumentError:
        pass
    assert bpy.data.filepath == original_path
    report["checks"].append("native math driver allowed; arbitrary Python driver rejected without changing trust preferences")
    bpy.data.materials.remove(material)
    checkpoint = document.capture(out / "valid.blend")
    original_identity = cube_identity = bpy.data.objects["Cube"]["spatial_native_uuid"]
    bpy.ops.ed.undo_push(message="Before native duplicate identity test")
    copied = bpy.data.objects["Cube"].copy()
    copied.name = "AAA NativeSync copied Cube"
    bpy.context.collection.objects.link(copied)
    document.capture(out / "duplicated.blend")
    assert bpy.data.objects["Cube"]["spatial_native_uuid"] == original_identity
    assert copied["spatial_native_uuid"] != original_identity
    copied_identity = copied["spatial_native_uuid"]
    bpy.ops.ed.undo_push(message="After native duplicate identity test")
    bpy.ops.ed.undo()
    assert bpy.data.objects["Cube"]["spatial_native_uuid"] == cube_identity
    bpy.ops.ed.redo()
    document.capture(out / "duplicated-redo.blend")
    assert bpy.data.objects["Cube"]["spatial_native_uuid"] == original_identity
    assert bpy.data.objects["AAA NativeSync copied Cube"]["spatial_native_uuid"] == copied_identity
    report["checks"].append("native Duplicate renamed before original preserves original UUID and new copy UUID across Undo/Redo")
    invalid = {identity: dict(entry) for identity, entry in checkpoint.manifest.items()}
    next(iter(invalid.values()))["group"] = "screens"
    try:
        document.apply(out / "valid.blend", invalid, lambda _: None, lambda _: None)
        raise AssertionError("UI runtime IDs were admitted as document data")
    except NativeDocumentError:
        pass
    assert not document.busy
    report["checks"].append("UI datablock manifest rejected before native transaction starts")
    bpy.ops.object.select_all(action="DESELECT")
    cube = bpy.data.objects["Cube"]
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    original_vertices = [list(vertex.co) for vertex in cube.data.vertices]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.ed.undo_push(message="Before authored Edit Mode move")
    bpy.ops.transform.translate(value=(.125, 0, 0))
    bpy.ops.ed.undo_push(message="Authored Edit Mode move")
    assert document.can_capture() and not document.is_idle()
    edit_snapshot = document.capture(out / "settled-edit-mode.blend")
    assert bpy.context.object.mode == "EDIT"
    edited_vertices = [list(vertex.co) for vertex in bpy.data.objects["Cube"].data.vertices]
    assert edited_vertices != original_vertices
    bpy.ops.ed.undo()
    bpy.data.objects["Cube"].update_from_editmode()
    assert [list(vertex.co) for vertex in bpy.data.objects["Cube"].data.vertices] == original_vertices
    bpy.ops.ed.redo()
    bpy.data.objects["Cube"].update_from_editmode()
    assert [list(vertex.co) for vertex in bpy.data.objects["Cube"].data.vertices] == edited_vertices
    assert edit_snapshot.data and bpy.context.object.mode == "EDIT"
    bpy.ops.object.mode_set(mode="OBJECT")
    report["checks"].append("settled Edit Mode checkpoint flushes native geometry while preserving mode and Undo/Redo history")
    bpy.ops.object.select_all(action="DESELECT")
    cube = bpy.data.objects["Cube"]
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    response = bpy.ops.transform.translate("INVOKE_DEFAULT")
    if response == {"RUNNING_MODAL"}:
        assert not document.is_idle()
        try:
            document.capture(out / "busy.blend")
            raise AssertionError("Active native modal transform was admitted")
        except NativeDocumentBusy:
            pass
        report["checks"].append("actual native modal tool blocks capture and preserves its unfinished operation")
    else:
        report["modal_check_deferred"] = str(response)
    report["passed"] = True
except Exception:  # noqa: BLE001 - preserve owned headless guard failures
    report["error"] = traceback.format_exc()
finally:
    (out / "RESULT.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)

"""Real shared kernels through owned live protocol; fresh factory Blender only."""

import argparse
import hashlib
import json
import sys
import traceback
import uuid
from pathlib import Path

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))

from spatial_modeling import (
    document,
    edits,
    host,
    leases,
    live_edit,
    modeling_tools,
    session,
    spatial_model_edit,
    sync,
)


def run(output):
    assert "--factory-startup" in sys.argv, "Use a new factory process only"
    bpy.utils.keyconfig_init()
    from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active
    VIEW3D_PT_tools_active.register_ensure()
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.preferences.filepaths.temporary_directory = str(output.parent)
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex)
    sync.register()
    sync.start(doc, sess)
    sync.flush()
    editor = edits.Editor(sync, host.undoable, document=doc)
    lses = leases.Leases(sess, editor)
    class Connection:
        can_edit = True
        def send(self, *_messages):
            pass
    conn = Connection()
    actor = {"actor_id": uuid.uuid4().hex, "name": "Isolated live kernels", "role": "vr"}
    sess.participants[conn] = actor
    sess.store.join(actor)
    manager = live_edit.LiveEdits(sess, editor, lses, host.undoable, kernel=modeling_tools)
    report = {"passed": False, "headset_acceptance": False, "checks": [], "blender": bpy.app.version_string}
    def identity():
        native = sess.document()
        return {"session_id": sess.session_id, "host_epoch": sess.host_epoch,
                "document_id": native["id"], "open_epoch": native["open_epoch"], "actor_id": actor["actor_id"]}
    def ask(action, **fields):
        reply = manager.handler(action)({"v": 1, "type": "live.edit." + action,
                                        "id": uuid.uuid4().hex, "payload": identity() | fields}, conn)
        assert reply["type"] == "live.edit.state", reply
        return reply["payload"]
    def mesh_state(oid):
        obj = sync.find_object(oid)
        bm = bmesh.from_edit_mesh(obj.data)
        spatial_model_edit._index(bm)
        # Native Undo can reorder edge/face storage and reverse an undirected
        # edge. Compare oriented topology and each UV corner without treating
        # those native storage choices as a geometry/history change.
        layers = list(bm.loops.layers.uv.values())
        faces = []
        for face in bm.faces:
            corners = [(loop.vert.index, tuple(tuple(loop[layer].uv) for layer in layers)) for loop in face.loops]
            start = min(range(len(corners)), key=lambda i: corners[i][0])
            faces.append((tuple(corners[start:] + corners[:start]), face.material_index))
        return {"verts": [tuple(v.co) for v in bm.verts],
                "edges": sorted(tuple(sorted(v.index for v in edge.verts)) for edge in bm.edges),
                "faces": sorted(faces), "uv_layers": [layer.name for layer in layers]}
    def fresh(component, unit, native_tool):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for item in list(bpy.context.scene.objects):
            bpy.data.objects.remove(item, do_unlink=True)
        mesh = bpy.data.meshes.new("Isolated live mesh")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=.2 / unit)
        uv = bm.loops.layers.uv.new("Native UV")
        for face in bm.faces:
            for loop in face.loops:
                loop[uv].uv = (loop.vert.co.x * unit, loop.vert.co.y * unit)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new("Isolated live mesh", mesh)
        bpy.context.collection.objects.link(obj)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.context.scene.unit_settings.scale_length = unit
        bpy.context.tool_settings.mesh_select_mode = tuple(value == component for value in ("vertex", "edge", "face"))
        bpy.context.tool_settings.use_proportional_edit = False
        bpy.context.tool_settings.use_snap = False
        bpy.ops.object.mode_set(mode="EDIT")
        area = next(a for a in bpy.context.window.screen.areas if a.type == "VIEW_3D")
        with bpy.context.temp_override(window=bpy.context.window, area=area,
                                       region=next(r for r in area.regions if r.type == "WINDOW")):
            bpy.ops.wm.tool_set_by_id(name=native_tool)
        oid = sync.object_id(obj)
        sync.flush()
        bm = bmesh.from_edit_mesh(obj.data)
        spatial_model_edit._index(bm)
        bm.verts[7].co.z += .001 / unit
        bmesh.update_edit_mesh(obj.data)
        obj.update_from_editmode()
        sync.flush()
        bpy.ops.ed.undo_push(message="Existing native work before live tool")
        return oid
    def begin(oid, tool, component, indices):
        native = spatial_model_edit.read_state(bpy.context, sync)
        assert native["available"], native
        lease = lses.grant(actor["actor_id"], "exclusive")
        operation = {"tool": tool, "native_tool": native["native_tool"], "mode": "EDIT_MESH",
                     "target_id": oid, "selection": {"component": component, "indices": indices},
                     "topology_token": native["topology_token"], "settings": native["settings"]}
        state = ask("begin", base_revision=sync.flush(), lease=lease["lease_id"],
                    targets=[{"id": oid, "generation": sync.generation(oid)}], operation=operation)
        return state["edit_session_id"], lease
    cases = [
        ("mesh.extrude", "builtin.extrude_region", "face", [0], {"translation_m": [0, 0, .01]}, {"translation_m": [0, 0, .025]}),
        ("mesh.inset", "builtin.inset_faces", "face", [0], {"thickness_m": .005}, {"thickness_m": .012}),
        ("mesh.bevel", "builtin.bevel", "edge", [0], {"width_m": .004, "segments": 2}, {"width_m": .009, "segments": 3}),
        ("mesh.loop_cut", "builtin.loop_cut", "edge", [0], {"cuts": 1, "slide": .1}, {"cuts": 3, "slide": .2}),
        ("mesh.merge", "builtin.move", "vertex", [0, 1], {"variant": "CENTER"}, {"variant": "LAST"}),
        ("mesh.dissolve", "builtin.move", "edge", [0], {}, {}),
        ("mesh.delete", "builtin.move", "face", [0], {"domain": "FACES_ONLY"}, {"domain": "FACES_ONLY"}),
        ("mesh.translate", "builtin.move", "vertex", [0],
         {"translation_m": [.008, 0, 0], "proportional_radius_m": .3, "proportional_falloff": "SMOOTH", "connected": True},
         {"translation_m": [.018, 0, 0], "proportional_radius_m": .3, "proportional_falloff": "SMOOTH", "connected": True}),
    ]
    try:
        for unit in (1, .001):
            for tool, native_tool, component, indices, first, final in cases:
                oid = fresh(component, unit, native_tool)
                before = mesh_state(oid)
                marker = bpy.context.scene.get(edits.STEP_PROPERTY)
                edit_id, lease = begin(oid, tool, component, indices)
                ask("update", edit_session_id=edit_id, sequence=1, parameters=first)
                assert mesh_state(oid) != before, f"{tool} must actually change native data while held"
                ask("update", edit_session_id=edit_id, sequence=2, parameters=final)
                final_mesh = mesh_state(oid)
                assert bpy.context.scene.get(edits.STEP_PROPERTY) == marker, "Held samples must not introduce history markers"
                ask("commit", edit_session_id=edit_id, sequence=2)
                lses.end(lease["lease_id"], actor["actor_id"])
                redo_mesh = mesh_state(oid)
                assert redo_mesh == final_mesh, {"tool": tool, "before_redo": final_mesh, "after_redo": redo_mesh}
                editor.apply("history.undo", None, {})
                assert mesh_state(oid) == before, f"{tool} one Undo must retain preexisting native mesh/UV data"
                editor.apply("history.redo", None, {})
                assert mesh_state(oid) == final_mesh
                oid = fresh(component, unit, native_tool)
                before = mesh_state(oid)
                marker = bpy.context.scene.get(edits.STEP_PROPERTY)
                edit_id, lease = begin(oid, tool, component, indices)
                ask("update", edit_session_id=edit_id, sequence=1, parameters=first)
                ask("update", edit_session_id=edit_id, sequence=2, parameters=final)
                assert mesh_state(oid) != before
                ask("cancel", edit_session_id=edit_id, reason="Actual native cancel proof")
                lses.end(lease["lease_id"], actor["actor_id"])
                assert mesh_state(oid) == before and bpy.context.scene.get(edits.STEP_PROPERTY) == marker
                report["checks"].append({"tool": tool, "unit": unit, "live_updates": 2,
                                         "undo_redo": True, "cancel": True})
        report["passed"] = True
        report["kernel_sha256"] = {name: hashlib.sha256((ROOT / "blender_addon/spatial_modeling" / name).read_bytes()).hexdigest()
                                    for name in ("modeling_tools.py", "modeling_mesh.py", "tool_catalog.py")}
    except Exception:
        report["error"] = traceback.format_exc()
        raise
    finally:
        manager.stop()
        sync.unregister()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    print(json.dumps(run(args.output)))

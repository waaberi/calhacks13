"""Private initialized factory GUI: native tool selection -> production live mesh ops."""
import argparse
import copy
import json
import os
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
    protocol,
    session,
    spatial_model_edit,
    sync,
)
from spatial_modeling import native_modeling_toolbar as toolbar


def run(output):
    bpy.utils.keyconfig_init()
    from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active
    VIEW3D_PT_tools_active.register_ensure()
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.preferences.filepaths.temporary_directory = os.environ["TEMP"]
    toolbar.register(); toolbar.register()
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex)
    sync.register(); sync.start(doc, sess); sync.flush()
    editor = edits.Editor(sync, host.undoable, document=doc)
    lses = leases.Leases(sess, editor)
    manager = live_edit.LiveEdits(sess, editor, lses, host.undoable, kernel=modeling_tools)
    report = {"passed": False, "physical_acceptance": False, "checks": [], "cases": []}
    class Connection:
        can_edit = True
        def send(self, *_messages):
            pass
    conn = Connection()
    actor = {"actor_id": uuid.uuid4().hex, "name": "Private native toolbar", "role": "vr"}
    sess.participants[conn] = actor; sess.store.join(actor)
    window = bpy.context.window
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")

    def ask(action, **fields):
        native = sess.document()
        identity = {"session_id": sess.session_id, "host_epoch": sess.host_epoch, "document_id": native["id"],
                    "open_epoch": native["open_epoch"], "actor_id": actor["actor_id"]}
        reply = manager.handler(action)(protocol.message("live.edit."+action, identity | fields), conn)
        assert reply["type"] == "live.edit.state", reply
        return reply["payload"]

    def state(oid):
        bm = bmesh.from_edit_mesh(sync.find_object(oid).data); spatial_model_edit._index(bm)
        return {"v": [tuple(v.co) for v in bm.verts],
                "e": [(tuple(v.index for v in e.verts), e.select, e.hide) for e in bm.edges],
                "f": [(tuple(v.index for v in f.verts), f.select, f.hide) for f in bm.faces],
                "vs": [(v.select, v.hide) for v in bm.verts],
                "uv": {uv.name: [[tuple(l[uv].uv) for l in f.loops] for f in bm.faces] for uv in bm.loops.layers.uv.values()}}

    def geometry(value):
        return {"v": value["v"], "e": sorted(tuple(sorted(e[0])) for e in value["e"]),
                "f": sorted(tuple(sorted(f[0])) for f in value["f"])}

    def fresh(component):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for item in list(bpy.context.scene.objects):
            bpy.data.objects.remove(item, do_unlink=True)
        mesh = bpy.data.meshes.new("Private toolbar mesh")
        bm = bmesh.new(); bmesh.ops.create_cube(bm, size=.2)
        uv = bm.loops.layers.uv.new("Private native UV")
        for face in bm.faces:
            for loop in face.loops:
                loop[uv].uv = (loop.vert.co.x, loop.vert.co.z)
        bm.to_mesh(mesh); bm.free()
        target = bpy.data.objects.new("Private toolbar mesh", mesh)
        bpy.context.collection.objects.link(target)
        target.select_set(True); bpy.context.view_layer.objects.active = target
        bpy.context.tool_settings.mesh_select_mode = tuple(component == c for c in ("vertex", "edge", "face"))
        bpy.ops.object.mode_set(mode="EDIT")
        oid = sync.object_id(target)
        bm = bmesh.from_edit_mesh(target.data); spatial_model_edit._index(bm)
        bm.verts[7].co.z += .003
        for values in (bm.faces, bm.edges, bm.verts):
            for value in values:
                value.select = False
        values = {"vertex": bm.verts, "edge": bm.edges, "face": bm.faces}[component]
        indices = [0, 1] if component == "vertex" else [0]
        for index in indices:
            values[index].select_set(True)
            bm.select_history.add(values[index])
        bmesh.update_edit_mesh(target.data); target.update_from_editmode(); sync.flush()
        bpy.ops.ed.undo_push(message="Prior work before toolbar gesture")
        return oid, indices

    try:
        for native, tool, component, wanted in (
                (toolbar.MERGE, "mesh.merge", "vertex", {"variant": "LAST", "distance_m": .002}),
                (toolbar.DISSOLVE, "mesh.dissolve", "edge", {"variant": "AUTO", "angle_limit": .2}),
                (toolbar.DELETE, "mesh.delete", "face", {"domain": "ONLY_FACE"})):
            for cancel in (False, True):
                oid, indices = fresh(component)
                before = state(oid); marker = bpy.context.scene.get(edits.STEP_PROPERTY)
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.wm.tool_set_by_id(name=native)
                    chosen = window.workspace.tools.from_space_view3d_mode("EDIT_MESH", create=False)
                    assert chosen.idname == native
                    props = chosen.operator_properties(toolbar.OPERATORS[native])
                    for key, value in wanted.items():
                        setattr(props, "distance" if key == "distance_m" else key, value)
                assert state(oid) == before and bpy.context.scene.get(edits.STEP_PROPERTY) == marker
                telemetry = spatial_model_edit.read_state(bpy.context, sync)
                assert telemetry["available"] and telemetry["tool"] == tool, telemetry
                for key, value in wanted.items():
                    actual = telemetry["settings"][key]
                    assert actual == value if isinstance(value, str) else abs(actual-value) < 1e-6
                operation = {"tool": telemetry["tool"], "native_tool": native, "mode": "EDIT_MESH", "target_id": oid,
                             "selection": {"component": component, "indices": indices}, "topology_token": telemetry["topology_token"],
                             "settings": copy.deepcopy(telemetry["settings"])}
                lease = lses.grant(actor["actor_id"], "exclusive")
                begin = ask("begin", base_revision=sync.flush(), lease=lease["lease_id"],
                            targets=[{"id": oid, "generation": sync.generation(oid)}], operation=operation)
                token = begin["edit_session_id"]
                for sequence in (1, 2):
                    ask("update", edit_session_id=token, sequence=sequence, parameters=wanted)
                    assert geometry(state(oid)) != geometry(before), tool
                    assert bpy.context.scene.get(edits.STEP_PROPERTY) == marker
                final = state(oid)
                if cancel:
                    result = ask("cancel", edit_session_id=token, reason="Private toolbar Cancel")
                    assert result["phase"] == "cancelled" and state(oid) == before
                    assert bpy.context.scene.get(edits.STEP_PROPERTY) == marker
                else:
                    result = ask("commit", edit_session_id=token, sequence=2)
                    assert result["phase"] == "committed" and geometry(state(oid)) == geometry(final)
                lses.end(lease["lease_id"], actor["actor_id"])
                if not cancel:
                    editor.apply("history.undo", None, {})
                    assert geometry(state(oid)) == geometry(before)
                    editor.apply("history.redo", None, {})
                    assert geometry(state(oid)) == geometry(final)
                report["cases"].append({"native_tool": native, "tool": tool, "cancel": cancel, "held_updates": 2})

        for variant in ("FIRST", "LAST"):
            oid, _ = fresh("vertex")
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.wm.tool_set_by_id(name=toolbar.MERGE)
                properties = window.workspace.tools.from_space_view3d_mode("EDIT_MESH", create=False).operator_properties(toolbar.OPERATORS[toolbar.MERGE])
                properties.variant = "CENTER"
            native = spatial_model_edit.read_state(bpy.context, sync)
            ordered = [5, 0, 3]
            # This is the production selection-only ACK route used by three
            # successive controller picks; it introduces no geometry Undo.
            selection_operation = {"tool": "mesh.selection", "selection_only": True, "native_tool": toolbar.MERGE,
                "mode": "EDIT_MESH", "target_id": oid, "selection": {"component": "vertex", "indices": ordered},
                "topology_token": native["topology_token"], "settings": copy.deepcopy(native["settings"])}
            lease = lses.grant(actor["actor_id"], "exclusive")
            begin = ask("begin", base_revision=sync.flush(), lease=lease["lease_id"],
                targets=[{"id": oid, "generation": sync.generation(oid)}], operation=selection_operation)
            ask("update", edit_session_id=begin["edit_session_id"], sequence=1, parameters={})
            ask("commit", edit_session_id=begin["edit_session_id"], sequence=1)
            lses.end(lease["lease_id"], actor["actor_id"])
            properties.variant = variant
            native = spatial_model_edit.read_state(bpy.context, sync)
            assert native["available"] and native["selection"]["indices"] == ordered, native
            before = state(oid)
            wanted_position = before["v"][ordered[0 if variant == "FIRST" else -1]]
            operation = {"tool": "mesh.merge", "native_tool": toolbar.MERGE, "mode": "EDIT_MESH", "target_id": oid,
                "selection": {"component": "vertex", "indices": native["selection"]["indices"]},
                "topology_token": native["topology_token"], "settings": copy.deepcopy(native["settings"])}
            lease = lses.grant(actor["actor_id"], "exclusive")
            begin = ask("begin", base_revision=sync.flush(), lease=lease["lease_id"],
                targets=[{"id": oid, "generation": sync.generation(oid)}], operation=operation)
            ask("update", edit_session_id=begin["edit_session_id"], sequence=1, parameters={"variant": variant})
            final = state(oid)
            assert len(final["v"]) == 6 and wanted_position in final["v"], (variant, ordered, wanted_position, final)
            ask("commit", edit_session_id=begin["edit_session_id"], sequence=1)
            lses.end(lease["lease_id"], actor["actor_id"])
            editor.apply("history.undo", None, {})
            assert geometry(state(oid)) == geometry(before)
            editor.apply("history.redo", None, {})
            assert geometry(state(oid)) == geometry(final)
        oid, _ = fresh("vertex")
        bm = bmesh.from_edit_mesh(sync.find_object(oid).data)
        bm.select_history.clear()
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name=toolbar.MERGE)
            properties = window.workspace.tools.from_space_view3d_mode("EDIT_MESH", create=False).operator_properties(toolbar.OPERATORS[toolbar.MERGE])
            properties.variant = "FIRST"
        native = spatial_model_edit.read_state(bpy.context, sync)
        assert not native["available"] and "ordered vertex picks" in native["reason"], native
        report["checks"].append("Merge_First_Last_preserves_three_pick_native_ACK_order_and_refuses_missing_history")

        # Desktop/controller clicks in the 2D Blender view remain actual native ops.
        for native, component in ((toolbar.MERGE, "vertex"), (toolbar.DISSOLVE, "edge"), (toolbar.DELETE, "face")):
            oid, _ = fresh(component); before = geometry(state(oid))
            operator = getattr(bpy.ops.spatial_modeling, toolbar.OPERATORS[native].split(".")[1])
            result = operator('EXEC_DEFAULT')
            assert result == {'FINISHED'} and geometry(state(oid)) != before, (native, result)
        report["checks"].append("native_2D_operator_paths_preserved")
        oid, _ = fresh("vertex")
        bpy.context.scene.unit_settings.scale_length = .001
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name=toolbar.MERGE)
            chosen = window.workspace.tools.from_space_view3d_mode("EDIT_MESH", create=False)
            props = chosen.operator_properties(toolbar.OPERATORS[toolbar.MERGE])
            props.variant, props.distance = "DISTANCE", 2
        assert abs(spatial_model_edit.read_state(bpy.context, sync)["settings"]["distance_m"]-.002) < 1e-8
        bpy.context.scene.unit_settings.scale_length = 1
        report["checks"].append("native_distance_property_converts_millimeter_units_once")
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name=toolbar.DELETE)
        before = state(oid)
        toolbar.unregister(); toolbar.unregister()
        current = window.workspace.tools.from_space_view3d_mode("EDIT_MESH", create=False)
        assert current.idname == "builtin.select_box" and state(oid) == before
        toolbar.register()
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name=toolbar.MERGE)
        bpy.ops.object.mode_set(mode="OBJECT")
        toolbar.unregister()
        bpy.ops.object.mode_set(mode="EDIT")
        assert all(not hasattr(tool, "_bl_tool") for tool in toolbar.TOOLS)
        # Blender owns inactive mode ID caches; removed definitions/keymaps have
        # no executable adapter. Native tool selection remains functional.
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
        assert window.workspace.tools.from_space_view3d_mode("EDIT_MESH", create=False).idname == "builtin.select_box"
        report["checks"].extend(["selecting_native_toolbar_arms_only_no_geometry_or_Undo", "editable_native_properties_roundtrip_in_telemetry",
                                 "three_native_intents_reach_production_live_kernels", "held_preview_one_Undo_Redo_and_exact_Cancel",
                                 "idempotent_registration_active_unregister_no_document_change"])
        report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc(); raise
    finally:
        manager.stop(); toolbar.unregister(); sync.unregister()
        output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:]); args.output.parent.mkdir(parents=True, exist_ok=True)
    def entry():
        try:
            print(json.dumps(run(args.output)))
        except Exception:  # noqa: BLE001 - retain evidence and quit the owned factory GUI
            traceback.print_exc()
            if not args.output.exists():
                args.output.write_text(json.dumps({"passed": False, "error": traceback.format_exc()}), encoding="utf-8")
        finally:
            bpy.ops.wm.quit_blender()
    bpy.app.timers.register(entry, first_interval=1.0)

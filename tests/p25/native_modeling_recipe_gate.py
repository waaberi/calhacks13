"""Production whole-recipe gate in a fresh private factory Blender process only.

No network listener, existing file, Player, headset or other Blender session is
used. The provider draft is fixed typed data; this is not live Gemini acceptance.
"""
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
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
from spatial_modeling import (
    commands,
    document,
    edits,
    host,
    leases,
    modeling_recipe,
    modeling_tools,
    protocol,
    session,
    sync,
    voice_ops,
)


def run(output):
    bpy.utils.keyconfig_init()
    from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active
    VIEW3D_PT_tools_active.register_ensure()
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.preferences.filepaths.temporary_directory = os.environ["TEMP"]
    report = {"passed": False, "physical_acceptance": False, "live_gemini_api": False,
              "blender": bpy.app.version_string, "checks": [], "receipts": []}
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex)
    sync.register()
    sync.start(doc, sess)
    sync.flush()
    voice = voice_ops.Voice(sync)
    editor = edits.Editor(sync, host.undoable, document=doc, voice=voice)
    lses = leases.Leases(sess, editor)
    cmds = commands.Commands(sess, editor, leases=lses)
    host._session, host._leases, host._commands = sess, lses, cmds

    class Connection:
        can_edit = True
        def __init__(self):
            self.sent = []
        def send(self, *messages):
            self.sent.extend(messages)

    conn, other = Connection(), Connection()
    actor = {"actor_id": uuid.uuid4().hex, "name": "Private recipe gate", "role": "vr"}
    other_actor = {"actor_id": uuid.uuid4().hex, "name": "Private foreign actor", "role": "vr"}
    for connection, participant in ((conn, actor), (other, other_actor)):
        sess.participants[connection] = participant
        sess.store.join(participant)
    area = next(a for a in bpy.context.window.screen.areas if a.type == "VIEW_3D")
    override = {"window": bpy.context.window, "area": area,
                "region": next(r for r in area.regions if r.type == "WINDOW")}

    def tool(name):
        with bpy.context.temp_override(**override):
            bpy.ops.wm.tool_set_by_id(name=name)

    def obj(oid):
        return sync.find_object(oid)

    def identity(connection=conn):
        native = sess.document()
        return {"session_id": sess.session_id, "host_epoch": sess.host_epoch,
                "document_id": native["id"], "open_epoch": native["open_epoch"],
                "actor_id": sess.participants[connection]["actor_id"]}

    def command(op, arguments=None, target=None, expected="applied", connection=conn):
        lease = lses.grant(sess.participants[connection]["actor_id"], "exclusive")
        try:
            payload = identity(connection) | {"base_revision": sync.flush(), "source": "voice", "op": op,
                                               "args": arguments or {}, "lease": lease["lease_id"]}
            if target:
                payload["target"] = {"id": target, "generation": sync.generation(target)}
            message = protocol.message("command", payload)
            immediate = cmds.command(message, connection)
            result = immediate or connection.sent[-1]
            assert result["type"] == "result", result
            receipt = result["payload"]
            assert receipt["outcome"] == expected, receipt
            report["receipts"].append({"op": op, "outcome": receipt["outcome"],
                                       "selection": receipt.get("selection"), "error": receipt.get("error")})
            return receipt
        finally:
            lses.end(lease["lease_id"], sess.participants[connection]["actor_id"])

    def frozen():
        sync.flush()
        value = modeling_recipe.capture_context(sync)
        value.pop("model", None)
        value["selection"] = copy.deepcopy(value.get("native_selection", {}))
        if not value["selection"]:
            active = bpy.context.active_object
            value["selection"] = {"component": "object", "indices": [],
                                  "objects": [{"id": sync.object_id(active), "generation": sync.generation(sync.object_id(active))}]}
        return value

    def prepare(steps, decision="run", context=None, **extra):
        before = fingerprint()
        revision = sync.flush()
        message = protocol.message("voice.resolve", {"text": "Complete native recipe gate", "confidence": 1,
            "composition": True, "recipe": {"decision": "propose", "steps": steps} | extra,
            "context": context or frozen()})
        response = voice.on_resolve(message, conn)
        assert response["type"] == "voice.candidates", response
        result = response["payload"]
        assert result["decision"] == decision, result
        assert fingerprint() == before, "Recipe preparation mutated the native scene"
        assert sync.flush() == revision, "Recipe preparation published a geometry change"
        if decision == "run":
            assert result["candidates"][0]["requires_confirmation"] is True
            assert len(result["recipe_plan"]["steps"]) == len(steps)
        else:
            assert result["candidates"] == []
        return result

    def execute(result, expected="applied", connection=conn):
        candidates = result["candidates"]
        target = candidates[0].get("target_id") if candidates else None
        return command("voice.run", {"resolution": result["resolution"], "choice": 1}, target, expected, connection)

    def step(tool_id, params, selection="captured", target="selected", sid="one"):
        return {"id": sid, "tool": tool_id, "params": params, "selection": selection, "target": target}

    def fingerprint():
        edit_history = {}
        if bpy.context.mode == "EDIT_MESH":
            for target in bpy.context.objects_in_mode:
                target.update_from_editmode()
                bm = bmesh.from_edit_mesh(target.data)
                for domain in (bm.verts, bm.edges, bm.faces):
                    domain.index_update()
                edit_history[target.get("spatial_modeling_id", "")] = {
                    "ordered": [(type(e).__name__, e.index) for e in bm.select_history],
                    "active_face": bm.faces.active.index if bm.faces.active is not None else None,
                }
        result = {}
        for target in bpy.context.scene.objects:
            mesh = None
            if target.type == "MESH":
                mesh = {"v": [tuple(v.co) for v in target.data.vertices],
                        "e": [tuple(e.vertices) for e in target.data.edges],
                        "f": [tuple(f.vertices) for f in target.data.polygons],
                        "uv": [[tuple(v.uv) for v in layer.data] for layer in target.data.uv_layers],
                        "groups": [(g.name, g.lock_weight) for g in target.vertex_groups],
                        "weights": [[(g.group, g.weight) for g in v.groups] for v in target.data.vertices]}
            result[target.name] = {"matrix": [tuple(row) for row in target.matrix_world], "mesh": mesh,
                                   "materials": [(s.link, s.material.name if s.material else None) for s in target.material_slots],
                                   "collections": sorted(c.name for c in target.users_collection), "selected": target.select_get(),
                                   "hidden": target.hide_get(), "hide_render": target.hide_render,
                                   "action": target.animation_data.action.name if target.animation_data and target.animation_data.action else None}
        return {"objects": result, "edit_history": edit_history, "collections": sorted(c.name for c in bpy.data.collections),
                "actions": sorted(a.name for a in bpy.data.actions), "frame": bpy.context.scene.frame_current,
                "active": bpy.context.active_object.name if bpy.context.active_object else None,
                "mode": bpy.context.mode, "components": copy.deepcopy(modeling_recipe.capture_context(sync).get("native_selection", {}))}

    def counts(oid):
        target = obj(oid)
        if bpy.context.mode == "EDIT_MESH":
            bm = bmesh.from_edit_mesh(target.data)
            return len(bm.verts), len(bm.edges), len(bm.faces)
        return len(target.data.vertices), len(target.data.edges), len(target.data.polygons)

    def check(name):
        report["checks"].append(name)

    def late_failure(result, failing_tool):
        before = fingerprint()
        sent_before = len(conn.sent)
        original = modeling_tools.apply_step
        calls = []
        def injected(*args, **kwargs):
            calls.append(args[2])
            if args[2] == failing_tool:
                raise ValueError("Injected late native recipe failure")
            return original(*args, **kwargs)
        modeling_tools.apply_step = injected
        try:
            receipt = execute(result, "rejected")
            assert receipt["error"]["code"] == "failed", receipt
        finally:
            modeling_tools.apply_step = original
        assert len(calls) >= 2, calls
        assert not [m for m in conn.sent[sent_before:] if m["type"] == "scene.update"], "A rejected recipe published a valid prefix"
        after = fingerprint()
        assert after == before, ("Late failure did not exactly restore native geometry/UV/materials/selection",
                                 {key: (before[key], after[key]) for key in before if before[key] != after[key]})

    try:
        tool("builtin.move")
        base = sync.object_id(bpy.context.active_object)
        command("object.move", {"by": [.013, 0, 0]}, base)
        baseline = obj(base).location.copy()
        creation = [step("object.add", {"primitive": "cube", "location": [0, 0, .1], "dimensions": [.04, .04, .04]},
                         {"component": "object", "indices": []}, None),
                    step("object.translate", {"translation_m": [.02, 0, 0]}, {"component": "object", "indices": []},
                         {"step": "one", "output": "object"}, "two"),
                    step("object.scale", {"scale": [-1, 1.2, 1]}, {"component": "object", "indices": []},
                         {"step": "one", "output": "object"}, "three")]
        prepared = prepare(creation)
        native_apply = modeling_tools.apply_step
        creation_start = len(conn.sent)
        def creation_kernel(*args, **kwargs):
            result = native_apply(*args, **kwargs)
            assert not [m for m in conn.sent[creation_start:] if m["type"] == "scene.update"], "A recipe published before all kernels completed"
            return result
        modeling_tools.apply_step = creation_kernel
        try:
            receipt = execute(prepared)
        finally:
            modeling_tools.apply_step = native_apply
        created = receipt["selection"]["id"]
        assert created and created != base and obj(created) is not None
        assert (obj(created).location - Vector((.02, 0, .1))).length < 1e-6
        assert obj(created).scale.x < 0
        command("history.undo")
        assert obj(created) is None and (obj(base).location - baseline).length < 1e-6
        command("history.redo")
        assert obj(created) is not None and (obj(created).location - Vector((.02, 0, .1))).length < 1e-6
        check("object_creation_output_refs_final_actual_selection_one_Undo_Redo_prior_work_preserved")
        duplicate = execute(prepared, "rejected")
        assert duplicate["error"]["code"] == "not_found"
        check("review_requires_confirmation_and_stored_plan_is_single_use")

        # A late failure after creation must remove its new object and all prefix mutations.
        late_failure(prepare(creation), "object.scale")
        check("late_creation_chain_failure_exact_rollback_no_valid_prefix")

        result = prepare([step("object.translate", {"translation_m": [.003, 0, 0]})])
        foreign = execute(result, "rejected", other)
        assert foreign["error"]["code"] == "permission_denied"
        now = voice.clock
        voice.clock = lambda: now() + modeling_recipe.TTL + 1
        try:
            expired = execute(result, "rejected")
            assert expired["error"]["code"] == "not_found"
        finally:
            voice.clock = now
        check("foreign_connection_and_expired_review_cannot_execute")

        prepare([step("object.translate", {})], "clarify")
        prepare([step("object.translate", {"translation_m": [.001, 0, 0]}), step("arbitrary.python", {}, sid="bad")], "reject")
        check("missing_value_clarification_and_unsupported_tail_do_not_execute_prefix")

        # Work on the existing small created cube in native Edit Mode, one face only.
        for target in bpy.context.selected_objects:
            target.select_set(False)
        obj(created).select_set(True)
        bpy.context.view_layer.objects.active = obj(created)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        tool("builtin.inset")
        bm = bmesh.from_edit_mesh(obj(created).data)
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            face.select_set(False)
        for edge in bm.edges:
            edge.select_set(False)
        for vertex in bm.verts:
            vertex.select_set(False)
        bm.faces[0].select_set(True)
        bmesh.update_edit_mesh(obj(created).data)
        sync.flush()
        bpy.ops.ed.undo_push(message="Native selected face before recipe")
        before_counts = counts(created)
        mesh_recipe = [step("mesh.inset", {"thickness_m": .002}, target=created),
                       step("mesh.extrude", {"translation_m": [0, 0, .005]}, {"step": "one", "output": "inner_faces"}, created, "two"),
                       step("mesh.bevel", {"width_m": .0003, "segments": 2}, {"step": "one", "output": "boundary_edges"}, created, "three")]
        prepared = prepare(mesh_recipe)
        native_apply = modeling_tools.apply_step
        actual_steps = []
        def record_kernel(*args, **kwargs):
            result = native_apply(*args, **kwargs)
            actual_steps.append(copy.deepcopy(result))
            return result
        modeling_tools.apply_step = record_kernel
        try:
            receipt = execute(prepared)
        finally:
            modeling_tools.apply_step = native_apply
        assert receipt["selection"]["id"] == created
        final_components = actual_steps[-1]["selection"]
        native_components = modeling_recipe.capture_context(sync)["native_selection"]
        assert native_components["component"] == final_components["component"], (native_components, final_components)
        assert sorted(native_components["indices"]) == sorted(final_components["indices"]), (native_components, final_components)
        assert receipt["selection"].get("component") == final_components["component"], receipt
        assert sorted(receipt["selection"].get("indices", [])) == sorted(final_components["indices"]), receipt
        after_counts = counts(created)
        assert after_counts[0] > before_counts[0] and after_counts[2] > before_counts[2]
        command("history.undo")
        assert counts(created) == before_counts
        command("history.redo")
        assert counts(created) == after_counts
        check("Edit_Mode_inset_extrude_bevel_real_output_refs_actual_final_target_one_Undo_Redo")

        mesh_selected = modeling_recipe.capture_context(sync)["native_selection"]
        assert mesh_selected["component"] in ("vertex", "edge", "face")
        assert mesh_selected["indices"], mesh_selected
        check("native_final_component_selection_is_actual_nonempty_kernel_result")

        # Capture then change only native component selection; no geometry revision needed.
        prepared = prepare([step("mesh.translate", {"translation_m": [.001, 0, 0]}, target=created)])
        bm = bmesh.from_edit_mesh(obj(created).data)
        for face in bm.faces:
            face.select_set(False)
        for edge in bm.edges:
            edge.select_set(False)
        for vertex in bm.verts:
            vertex.select_set(False)
        bm.select_history.clear()
        bm.faces.ensure_lookup_table()
        bm.faces[-1].select_set(True)
        bm.select_history.add(bm.faces[-1])
        bmesh.update_edit_mesh(obj(created).data)
        stale = execute(prepared, "rejected")
        assert stale["error"]["code"] == "stale_revision", stale
        check("native_selection_change_invalidates_prepared_recipe_without_geometry_change")

        # UV changes and geometry prefix both restore on a later forced kernel failure.
        bm = bmesh.from_edit_mesh(obj(created).data)
        uv = bm.loops.layers.uv.verify()
        for face in bm.faces:
            for loop in face.loops:
                loop[uv].uv = (loop.vert.co.x, loop.vert.co.y)
        bmesh.update_edit_mesh(obj(created).data)
        sync.flush()
        mesh_recipe = [step("uv.transform", {"translation": [.1, -.2]}, target=created),
                       step("mesh.translate", {"translation_m": [.001, 0, 0]}, target=created, sid="two"),
                       step("mesh.scale", {"scale": [1.1, 1.1, 1.1]}, target=created, sid="three")]
        late_failure(prepare(mesh_recipe), "mesh.scale")
        check("Edit_Mode_UV_geometry_and_native_selection_exact_late_failure_rollback")

        bpy.ops.object.mode_set(mode="OBJECT")
        tool("builtin.move")
        material = bpy.data.materials.new("Private baseline material")
        material.use_nodes = True
        obj(created).data.materials.clear()
        obj(created).data.materials.append(material)
        sync.flush()
        mixed = [step("material.principled", {"roughness": .123, "base_colour": [.1, .2, .3, 1]}, target=created),
                 step("vertex_group.create", {"name": "Private recipe group"}, target=created, sid="two"),
                 step("collection.create", {"name": "Private recipe collection"}, target=created, sid="three"),
                 step("object.translate", {"translation_m": [.02, 0, 0]}, target=created, sid="four")]
        late_failure(prepare(mixed), "object.translate")
        assert obj(created).data.materials[0] == material
        assert not obj(created).vertex_groups.get("Private recipe group")
        assert not bpy.data.collections.get("Private recipe collection")
        check("mixed_material_vertex_groups_collection_recipe_ExtraBackup_exact_rollback")
        metadata = [step("object.rename", {"name": "Private temporarily renamed"}, target=created),
                    step("animation.keyframe", {"channel": "location", "frame": 10}, target=created, sid="two"),
                    step("animation.frame", {"frame": 15}, target=created, sid="three"),
                    step("object.translate", {"translation_m": [.01, 0, 0]}, target=created, sid="four")]
        late_failure(prepare(metadata), "object.translate")
        check("object_rename_animation_frame_and_new_action_exact_rollback")

        # A referenced operand is a captured target too, even when no step edits it.
        parent_plan = prepare([step("object.parent", {"parent_id": base, "keep_transform": True}, target=created)])
        before_parent = obj(created).parent
        command("object.move", {"by": [.001, 0, 0]}, base)
        rejected = execute(parent_plan, "rejected")
        assert rejected["error"]["code"] == "stale_revision" and obj(created).parent == before_parent
        obj(base).hide_set(True)
        sync.flush()
        prepare([step("object.parent", {"parent_id": base, "keep_transform": True}, target=created)], "clarify")
        obj(base).hide_set(False)
        sync.flush()
        check("operand_generation_and_visible_native_handle_fences")

        light = next(o for o in bpy.context.scene.objects if o.type == "LIGHT")
        prepared = prepare([step("object.translate", {"translation_m": [.001, 0, 0]}, target=created)])
        old_energy = light.data.energy
        revision = sync.flush()
        light.data.energy = old_energy + 7
        assert sync.flush() == revision, "Light freshness fixture unexpectedly changed streamed geometry"
        rejected = execute(prepared, "rejected")
        assert rejected["error"]["code"] == "stale_revision"
        light.data.energy = old_energy
        check("native_Light_change_without_geometry_revision_invalidates_AI_plan")

        # Native Select All on an ordinary grid must exceed the legacy 256 limit.
        for target in bpy.context.selected_objects:
            target.select_set(False)
        mesh = bpy.data.meshes.new("Private 625 vertex recipe grid")
        bm = bmesh.new()
        vertices = [[bm.verts.new((x*.004, y*.004, 0)) for x in range(25)] for y in range(25)]
        for y in range(24):
            for x in range(24):
                bm.faces.new((vertices[y][x], vertices[y][x+1], vertices[y+1][x+1], vertices[y+1][x]))
        bm.to_mesh(mesh)
        bm.free()
        grid = bpy.data.objects.new("Private 625 vertex recipe grid", mesh)
        bpy.context.collection.objects.link(grid)
        grid.select_set(True)
        bpy.context.view_layer.objects.active = grid
        grid_id = sync.object_id(grid)
        bpy.context.tool_settings.mesh_select_mode = (True, False, False)
        bpy.ops.object.mode_set(mode="EDIT")
        tool("builtin.move")
        bm = bmesh.from_edit_mesh(grid.data)
        bm.verts.ensure_lookup_table()
        bm.verts[0].co.z = .005
        for vertex in bm.verts:
            vertex.select_set(True)
        bmesh.update_edit_mesh(grid.data)
        grid.update_from_editmode()
        sync.flush()
        bpy.ops.ed.undo_push(message="Prior native grid work before recipe")
        original_grid = [tuple(v.co) for v in bm.verts]
        prepared = prepare([step("mesh.translate", {"translation_m": [.003, -.002, .001]}, target=grid_id)])
        assert len(prepared["recipe_plan"]["steps"][0]["selection"]["indices"]) == 625
        receipt = execute(prepared)
        assert len(receipt["selection"]["indices"]) == 625
        translated_grid = [tuple(v.co) for v in bmesh.from_edit_mesh(obj(grid_id).data).verts]
        assert all((Vector(after)-Vector(before)-Vector((.003, -.002, .001))).length < 2e-6
                   for before, after in zip(original_grid, translated_grid))
        command("history.undo")
        assert [tuple(v.co) for v in bmesh.from_edit_mesh(obj(grid_id).data).verts] == original_grid
        command("history.redo")
        assert [tuple(v.co) for v in bmesh.from_edit_mesh(obj(grid_id).data).verts] == translated_grid
        late_failure(prepare([step("mesh.translate", {"translation_m": [.001, 0, 0]}, target=grid_id),
                              step("mesh.scale", {"scale": [1.1, 1.1, 1.1]}, target=grid_id, sid="two")]), "mesh.scale")
        check("625_selected_vertices_translate_one_Undo_Redo_and_exact_late_failure_rollback")

        # Native First/Last merge uses ordered selection, not only selection flags.
        for variant in ("FIRST", "LAST"):
            bm = bmesh.from_edit_mesh(obj(grid_id).data)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            for face in bm.faces:
                face.select_set(False)
            for edge in bm.edges:
                edge.select_set(False)
            for vertex in bm.verts:
                vertex.select_set(False)
            bm.select_history.clear()
            ordered = [13, 0, 12]
            expected = bm.verts[ordered[0 if variant == "FIRST" else -1]].co.copy()
            other_points = [bm.verts[i].co.copy() for i in ordered if (bm.verts[i].co - expected).length > 1e-7]
            for index in ordered:
                bm.verts[index].select_set(True)
                bm.select_history.add(bm.verts[index])
            bm.faces.active = bm.faces[5]
            bmesh.update_edit_mesh(obj(grid_id).data)
            sync.flush()
            late_failure(prepare([step("mesh.translate", {"translation_m": [.001, 0, 0]}, target=grid_id),
                                  step("mesh.scale", {"scale": [1.1, 1.1, 1.1]}, target=grid_id, sid="two")]), "mesh.scale")
            bm = bmesh.from_edit_mesh(obj(grid_id).data)
            assert [e.index for e in bm.select_history] == ordered
            assert bm.faces.active.index == 5
            with modeling_tools.native_context(obj(grid_id)):
                assert bpy.ops.mesh.merge('EXEC_DEFAULT', False, type=variant) == {'FINISHED'}
            bm = bmesh.from_edit_mesh(obj(grid_id).data)
            selected = [v for v in bm.verts if v.select]
            assert len(selected) == 1 and (selected[0].co - expected).length < 1e-7
            assert all(not any((v.co - other).length < 1e-7 for v in bm.verts) for other in other_points)
            check("late_failure_preserves_ordered_vertex_selection_active_face_and_native_" + variant + "_merge")

        # Deleting the final target must clear the previous step's selection.
        bpy.ops.object.mode_set(mode="OBJECT")
        tool("builtin.move")
        deletion = prepare([step("object.translate", {"translation_m": [.001, 0, 0]}, target=grid_id),
                            step("object.delete", {}, target=grid_id, sid="two")])
        receipt = execute(deletion)
        assert receipt["selection"] == {"id": None} and obj(grid_id) is None
        command("history.undo")
        assert obj(grid_id) is not None
        command("history.redo")
        assert obj(grid_id) is None
        check("final_object_delete_clears_stale_target_selection_one_Undo_Redo")
        report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc()
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        sync.unregister()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    def entry():
        try:
            print(json.dumps(run(args.output)))
        except Exception:  # noqa: BLE001 - always retain isolated native evidence and quit
            traceback.print_exc()
            if not args.output.exists():
                args.output.write_text(json.dumps({"passed": False, "error": traceback.format_exc()}), encoding="utf-8")
        finally:
            bpy.ops.wm.quit_blender()
    bpy.app.timers.register(entry, first_interval=1.0)

"""Disposable real-Blender direct-model gate. Never opens an existing user file.

Run ONLY in a fresh factory process, optionally without --background for native
history availability. --output records software evidence, never headset acceptance.
"""

import argparse
import json
import sys
import traceback
import uuid
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))

from spatial_modeling import (
    commands,
    document,
    edits,
    gate,
    host,
    leases,
    preview_spatial,
    session,
    sync,
)
from spatial_modeling import spatial_model_edit as spatial


def run(args):
    assert "--factory-startup" in sys.argv, "Use a new factory process only"
    # Background startup skips the native default keymap. Extrude's ToolDef
    # retains a callable until the same installed startup registration used by
    # the GUI materializes it. Initialize that real keyconfig in this disposable
    # process; never invent a tool id or replace the production toolbar path.
    bpy.utils.keyconfig_init()
    from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active
    VIEW3D_PT_tools_active.register_ensure()
    bpy.context.preferences.edit.use_global_undo = True
    report = {"blender": bpy.app.version_string, "checks": [], "passed": False,
              "headset_acceptance": False}
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex)
    sync.register()
    sync.start(doc, sess)
    sync.flush()
    editor = edits.Editor(sync, host.undoable, document=doc)
    lses = leases.Leases(sess, editor)
    cmds = commands.Commands(sess, editor, leases=lses)
    host._session, host._leases, host._commands = sess, lses, cmds
    # Match the ordinary joined connection's identity and outbound receipt path.
    class Connection:
        can_edit = True
        def send(self, *messages):
            self.sent.extend(messages)
    connection = Connection()
    connection.sent = []
    actor = {"actor_id": uuid.uuid4().hex, "name": "Isolated direct gate", "role": "vr"}
    sess.participants[connection] = actor
    sess.store.join(actor)
    ui = preview_spatial.NativePreviewSessions(sess, lses, lambda: bpy.context)
    target_id = sync.object_id(bpy.context.active_object)
    view = next(area for area in bpy.context.window.screen.areas if area.type == "VIEW_3D")
    override = {"window": bpy.context.window, "area": view,
                "region": next(region for region in view.regions if region.type == "WINDOW")}

    def tool(name, component=None):
        if component:
            bpy.context.tool_settings.mesh_select_mode = tuple(component == c for c in ("vertex", "edge", "face"))
        with bpy.context.temp_override(**override):
            bpy.ops.wm.tool_set_by_id(name=name)
        state = spatial.read_state(bpy.context, sync)
        assert state["available"], state
        return state

    def identity():
        native_doc = sess.document()
        return {"session_id": sess.session_id, "host_epoch": sess.host_epoch,
                "document_id": native_doc["id"], "open_epoch": native_doc["open_epoch"],
                "actor_id": actor["actor_id"]}

    def command(op, args_=None, target=None, lease=None, expected="applied", **fields):
        revision = sync.flush()
        payload = dict(identity(), base_revision=revision, source="ui", op=op, args=args_ or {})
        if target is not None:
            payload["target"] = {"id": target, "generation": sync.generation(target)}
        if lease:
            payload["lease"] = lease["lease_id"]
        payload.update(fields)
        msg = {"v": 1, "type": "command", "id": uuid.uuid4().hex, "payload": payload}
        immediate = cmds.command(msg, connection)
        result = immediate or connection.sent[-1]
        assert result["type"] == "result", result
        receipt = result["payload"]
        assert receipt["outcome"] == expected, receipt
        return receipt

    def gesture(state, delta, indices=None):
        return {name: state[name] for name in ("native_tool", "mode", "component", "topology_token")} | {
            "indices": indices or [], "delta": delta}

    def apply(state, delta, indices=None, expected="applied"):
        lease = lses.grant(actor["actor_id"], "exclusive")
        try:
            gate._watch_modes()
            assert bpy.context.mode == state["mode"], "A legitimate native-preview handoff must retain Edit Mode"
            return command("object.spatial_edit", gesture(state, delta, indices), target_id, lease, expected)
        finally:
            lses.end(lease["lease_id"], actor["actor_id"])

    def obj():
        return sync.find_object(target_id)

    def position(index):
        mesh = bmesh.from_edit_mesh(obj().data)
        mesh.verts.ensure_lookup_table()
        return (obj().matrix_world @ mesh.verts[index].co) * spatial._unit(bpy.context)

    def close(actual, wanted, tolerance=2e-6):
        assert (Vector(actual) - Vector(wanted)).length < tolerance, (tuple(actual), tuple(wanted))

    def passed(name):
        report["checks"].append(name)

    def native_mesh_state():
        """Exact document data the direct rollback promises to retain."""
        mesh = bmesh.from_edit_mesh(obj().data)
        spatial._index(mesh)
        return {
            "vertices": [(tuple(v.co), v.select, v.hide) for v in mesh.verts],
            "edges": [(tuple(v.index for v in e.verts), e.select, e.hide,
                       e.seam, e.smooth) for e in mesh.edges],
            "faces": [(tuple(v.index for v in f.verts), f.material_index,
                       f.select, f.hide, f.smooth) for f in mesh.faces],
            "materials": [material.name if material else None for material in obj().data.materials],
            "active_face": mesh.faces.active.index if mesh.faces.active is not None else None,
            "history": [(type(element).__name__, element.index) for element in mesh.select_history],
            "uv": {layer.name: [[tuple(loop[layer].uv) for loop in face.loops] for face in mesh.faces]
                   for layer in mesh.loops.layers.uv.values()},
        }

    try:
        # Object tools preserve native object selection and active object.
        state = tool("builtin.move")
        gate._watch_modes()
        original = obj().matrix_world.translation.copy()
        bpy.ops.ed.undo_push(message="Native data before controller gesture")
        receipt = apply(state, {"translation": [.02, -.01, .005]})
        close(obj().matrix_world.translation, original + Vector((.02, -.01, .005)))
        assert receipt["selection"] == {"id": target_id}
        passed("object_move_native_commit_and_receipt_selection")
        if not bpy.ops.ed.undo.poll():
            raise AssertionError("This Blender process cannot run native Undo; rerun in a fresh disposable GUI process")
        command("history.undo")
        close(obj().matrix_world.translation, original)
        command("history.redo")
        close(obj().matrix_world.translation, original + Vector((.02, -.01, .005)))
        passed("one_object_gesture_native_undo_redo")
        state = tool("builtin.scale")
        apply(state, {"scale": [-1, 1, .8]})
        assert obj().scale.x < 0
        passed("signed_object_mirror")
        state = tool("builtin.rotate")
        before = obj().matrix_world.copy()
        turn = Quaternion((0, 0, 1), .25)
        apply(state, {"rotation": list(turn)})
        expected = turn.to_matrix().to_4x4() @ before.to_3x3().to_4x4()
        expected.translation = before.translation
        assert max(abs(obj().matrix_world[i][j] - expected[i][j])
                   for i in range(4) for j in range(4)) < 2e-6
        passed("world_controller_object_rotation")

        # Native 2D input owns a genuine host lease while choosing Edit Mode/tool.
        # Observe the mode through the actual gate BEFORE acknowledged release;
        # a later normal remote lease must not impersonate a new mode entry.
        begin = {"id": uuid.uuid4().hex, "payload": identity()}
        granted = ui.begin(begin, connection)
        assert granted["type"] == "preview.ui.granted", granted
        with bpy.context.temp_override(**override):
            bpy.ops.object.mode_set(mode="EDIT")
        state = tool("builtin.move", "vertex")
        gate._watch_modes()
        ended = ui.end({"id": uuid.uuid4().hex,
                        "payload": identity() | {"ui_session_id": ui.token}}, connection)
        assert ended["type"] == "preview.ui.ended" and ui.owner is None, ended
        assert not sess.store.leases()
        passed("acknowledged_native_preview_release_and_fresh_editmode_handoff")

        # Preexisting local geometry is the Undo baseline, not part of the new
        # controller edit. Every command uses current identity/generation/lease.
        native_mesh = bmesh.from_edit_mesh(obj().data)
        native_mesh.verts.ensure_lookup_table()
        native_mesh.verts[1].co.z += .031
        bmesh.update_edit_mesh(obj().data)
        obj().update_from_editmode()
        sync.flush()
        bpy.ops.ed.undo_push(message="Preexisting native Edit Mode work")
        prior_other = position(1).copy()
        before = position(0).copy()
        state = spatial.read_state(bpy.context, sync)
        assert state["triangles"] and state["generation"] == sync.generation(target_id)
        apply(state, {"translation": [.015, -.006, .003]}, [0])
        after = before + Vector((.015, -.006, .003))
        close(position(0), after)
        close(position(1), prior_other)
        passed("base_vertex_edit_live_mesh_sync_preserves_prior_native_work")
        command("history.undo")
        assert bpy.context.mode == "EDIT_MESH"
        close(position(0), before)
        close(position(1), prior_other)
        command("history.redo")
        close(position(0), after)
        close(position(1), prior_other)
        passed("one_mesh_gesture_native_undo_redo_preserves_prior_editmode_work")

        state = tool("builtin.move", "edge")
        edge = state["edges"][0]
        edge_before = {index: position(index).copy() for index in edge["vertices"]}
        apply(state, {"translation": [0, .004, 0]}, [edge["index"]])
        for index, point in edge_before.items():
            close(position(index), point + Vector((0, .004, 0)))
        passed("edge_component_moves_exact_base_endpoints")

        state = tool("builtin.rotate", "face")
        face = state["faces"][0]
        points = {index: position(index).copy() for index in face["vertices"]}
        pivot = sum(points.values(), Vector()) / len(points)
        turn = Quaternion((0, 1, 0), .2)
        apply(state, {"rotation": list(turn)}, [face["index"]])
        for index, point in points.items():
            close(position(index), pivot + turn @ (point - pivot))
        passed("face_controller_rotation_world_pivot")

        state = tool("builtin.scale", "face")
        apply(state, {"scale": [-1, .9, 1]}, [state["faces"][0]["index"]])
        passed("signed_face_scale")
        state = tool("builtin.extrude_region", "face")
        native_mesh = bmesh.from_edit_mesh(obj().data)
        native_mesh.faces.ensure_lookup_table()
        while len(obj().data.materials) < 2:
            obj().data.materials.append(bpy.data.materials.new("Isolated extrusion material"))
        native_mesh.faces[state["faces"][0]["index"]].material_index = 1
        bmesh.update_edit_mesh(obj().data)
        obj().update_from_editmode()
        sync.flush()
        state = spatial.read_state(bpy.context, sync)
        counts = len(state["vertices"]), len(state["edges"]), len(state["faces"])
        apply(state, {"translation": [0, 0, .012]}, [state["faces"][0]["index"]])
        following = spatial.read_state(bpy.context, sync)
        assert len(following["vertices"]) == counts[0] + 4
        assert len(following["faces"]) == counts[2] + 4, (counts, following)
        native_mesh = bmesh.from_edit_mesh(obj().data)
        assert all(len(edge.link_faces) == 2 for edge in native_mesh.edges), "Closed-solid extrusion must remain manifold without an internal source cap"
        cap_faces = [face for face in native_mesh.faces if all(vertex.index >= counts[0] for vertex in face.verts)]
        assert len(cap_faces) == 1 and cap_faces[0].material_index == 1, "Extruded cap must retain native material data"
        passed("native_face_region_extrusion_topology_and_sync")

        state = tool("builtin.move", "vertex")
        stale = gesture(state, {"translation": [.1, 0, 0]}, [0])
        tool("builtin.rotate", "vertex")
        receipt = command("object.spatial_edit", stale, target_id, expected="rejected")
        assert receipt["error"]["code"] == "stale_revision"
        passed("changed_native_toolbar_refuses_frozen_gesture")
        state = tool("builtin.move", "vertex")
        stale = gesture(state, {"translation": [.1, 0, 0]}, [0])
        stale["topology_token"] = "0" * 64
        receipt = command("object.spatial_edit", stale, target_id, expected="rejected")
        assert receipt["error"]["code"] == "stale_revision"
        passed("changed_topology_token_refuses_without_mutation")
        before = position(0).copy()
        bad = gesture(state, {"translation": [.1, 0, 0]}, [16000])
        command("object.spatial_edit", bad, target_id, expected="rejected")
        close(position(0), before)
        passed("invalid_component_rolls_back_without_partial_edit")

        # Inject a failure ONLY after the production code writes the real live
        # Edit Mode mesh. A refusal before mutation is not rollback evidence.
        native_mesh = bmesh.from_edit_mesh(obj().data)
        spatial._index(native_mesh)
        native_mesh.select_history.clear()
        native_mesh.verts[0].select_set(True)
        native_mesh.select_history.add(native_mesh.verts[0])
        native_mesh.faces.active = native_mesh.faces[2]
        bmesh.update_edit_mesh(obj().data)
        obj().update_from_editmode()
        revision_before_failure = sync.flush()
        exact_before_failure = native_mesh_state()
        step_before_failure = bpy.context.scene.get(edits.STEP_PROPERTY)
        original_token, original_restore = spatial._token, spatial._restore_history
        injection = {"after_live_write": False, "fired": False}

        def observe_live_write(mesh, history, active_face):
            original_restore(mesh, history, active_face)
            injection["after_live_write"] = True

        def reject_live_readback(context, target, native_tool, component, mesh=None):
            digest = original_token(context, target, native_tool, component, mesh)
            if (injection["after_live_write"] and not injection["fired"]
                    and mesh is not None and mesh.is_wrapped):
                injection["fired"] = True
                # Verify the injected error truly observes changed native data.
                assert native_mesh_state() != exact_before_failure
                return ("1" if digest[0] != "1" else "2") + digest[1:]
            return digest

        try:
            spatial._restore_history = observe_live_write
            spatial._token = reject_live_readback
            state = spatial.read_state(bpy.context, sync)
            receipt = apply(state, {"translation": [.007, -.003, .002]}, [0], expected="rejected")
        finally:
            spatial._token, spatial._restore_history = original_token, original_restore
        assert injection["fired"], "Failure must have occurred after a real live mesh write"
        assert receipt["error"]["code"] == "failed" and "nothing changed" in receipt["error"]["message"]
        assert native_mesh_state() == exact_before_failure, "Live-write failure must restore exact geometry, topology, materials, UVs, selection, active face and history"
        assert sync.flush() == revision_before_failure
        assert bpy.context.scene.get(edits.STEP_PROPERTY) == step_before_failure
        # A real native Undo must still reach the preceding successful extrusion
        # immediately, proving the refused write did not add an Undo step.
        undo = command("history.undo")
        assert undo["summary"].startswith("Undid: Direct extrude_region")
        undone_mesh = bmesh.from_edit_mesh(obj().data)
        assert len(undone_mesh.faces) == counts[2]
        redo = command("history.redo")
        assert redo["summary"].startswith("Redid: Direct extrude_region")
        redone_mesh = bmesh.from_edit_mesh(obj().data)
        assert len(redone_mesh.faces) == counts[2] + 4
        passed("post_live_write_failure_exact_rollback_no_revision_or_undo_step")

        with bpy.context.temp_override(**override):
            bpy.ops.object.mode_set(mode="OBJECT")
        # A transformed parent and mm units must apply a meter-world delta once.
        parent = bpy.data.objects.new("Isolated rotated parent", None)
        bpy.context.scene.collection.objects.link(parent)
        parent.rotation_euler.z = .43
        parent.scale = (2, 2, 2)
        obj().parent = parent
        bpy.context.scene.unit_settings.scale_length = .001
        bpy.context.view_layer.update()
        sync.flush()
        with bpy.context.temp_override(**override):
            bpy.ops.object.mode_set(mode="EDIT")
        state = tool("builtin.move", "vertex")
        gate._watch_modes()
        before = position(0).copy()
        apply(state, {"translation": [.02, .005, -.003]}, [0])
        close(position(0), before + Vector((.02, .005, -.003)))
        passed("millimeter_units_rotated_scaled_parent_world_delta_once")
        with bpy.context.temp_override(**override):
            bpy.ops.object.mode_set(mode="OBJECT")
        parent.scale = (2, 1, 1)
        obj().rotation_euler.z = .3
        bpy.context.view_layer.update()
        with bpy.context.temp_override(**override):
            bpy.ops.object.mode_set(mode="EDIT")
        state = spatial.read_state(bpy.context, sync)
        assert not state["available"] and "shear" in state["reason"]
        passed("unrepresentable_parent_shear_refused")
        with bpy.context.temp_override(**override):
            bpy.ops.object.mode_set(mode="OBJECT")
        obj().parent = None
        obj().matrix_world = Matrix.Identity(4)
        twin = obj().copy()
        bpy.context.scene.collection.objects.link(twin)
        with bpy.context.temp_override(**override):
            bpy.ops.object.mode_set(mode="EDIT")
        state = spatial.read_state(bpy.context, sync)
        assert not state["available"] and "shared" in state["reason"]
        passed("shared_mesh_data_refused_no_silent_linked_mutation")
        report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc()
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        sync.unregister()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parsed = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    try:
        print(json.dumps(run(parsed)))
    except Exception:
        traceback.print_exc()
        if not bpy.app.background:
            bpy.ops.wm.quit_blender()
        raise
    if not bpy.app.background:
        bpy.ops.wm.quit_blender()

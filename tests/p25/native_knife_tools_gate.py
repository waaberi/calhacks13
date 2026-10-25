"""Private factory GUI: production live Knife, frozen Unity camera, native history."""
import argparse
import copy
import hashlib
import json
import math
import os
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


def unity_projection(perspective, kind="uniform"):
    """Actual column-vector P * WTC * primaryMap * Swap from DirectLiveController."""
    swap = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    flip = Matrix.Diagonal((1, 1, -1, 1))  # Unity camera looks +Z; camera matrix uses -Z
    rotation = Quaternion(Vector((.2, 1, -.3)).normalized(), .49).to_matrix().to_4x4()
    scale = Matrix.Diagonal((2.4, 2.4, 2.4, 1))
    if kind == "nonuniform":
        scale = Matrix.Diagonal((1.8, 2.4, 1.3, 1))
    elif kind == "mirrored":
        scale = Matrix.Diagonal((-2.4, 2.4, 2.4, 1))
    elif kind == "sheared":
        scale[0][1] = .7
    display = Matrix.Translation(Vector((.7, 1.2, 2))) @ rotation @ scale
    eye = display @ swap @ Vector((0, -.65, 0))
    focus = display @ swap @ Vector((0, 0, 0))
    forward = (focus-eye).normalized()
    up_hint = (display @ swap).to_3x3() @ Vector((0, 0, 1))
    right = up_hint.cross(forward).normalized()
    up = forward.cross(right).normalized()
    camera = Matrix.Identity(4)
    for axis, col in ((right, 0), (up, 1), (forward, 2)):
        for row in range(3):
            camera[row][col] = axis[row]
    camera.translation = eye
    if perspective:
        near, far = .01, 10
        f = 1/math.tan(math.radians(65)/2)
        p = Matrix(((f/1.2, 0, 0, 0), (0, f, 0, 0),
                    (0, 0, -(far+near)/(far-near), -2*far*near/(far-near)), (0, 0, -1, 0)))
    else:
        p = Matrix(((2/.8, 0, 0, 0), (0, 2/.6, 0, 0), (0, 0, -2/10, 0), (0, 0, 0, 1)))
    result = p @ flip @ camera.inverted() @ display @ swap
    return [float(v) for row in result for v in row]


def run(output):
    assert not bpy.app.background, "Requires an initialized private GUI"
    bpy.utils.keyconfig_init()
    from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active
    VIEW3D_PT_tools_active.register_ensure()
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.preferences.filepaths.temporary_directory = os.environ["TEMP"]
    report = {"passed": False, "physical_acceptance": False, "checks": [], "cases": [], "affine": [], "blender": bpy.app.version_string}
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex)
    sync.register(); sync.start(doc, sess); sync.flush()
    editor = edits.Editor(sync, host.undoable, document=doc)
    lses = leases.Leases(sess, editor)
    host._session, host._leases = sess, lses

    class Connection:
        can_edit = True
        def send(self, *_messages):
            pass
    conn = Connection()
    actor = {"actor_id": uuid.uuid4().hex, "name": "Private live Knife", "role": "vr"}
    sess.participants[conn] = actor
    sess.store.join(actor)
    manager = live_edit.LiveEdits(sess, editor, lses, host.undoable, kernel=modeling_tools)
    area = next(a for a in bpy.context.window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    rv = area.spaces.active.region_3d

    def view_state():
        return ([float(v) for row in rv.view_matrix for v in row], rv.view_perspective)

    def same_view(before):
        after = view_state()
        assert before[1] == after[1] and max(abs(a-b) for a, b in zip(before[0], after[0])) < 3e-5, (before, after)
        assert not any(o.name.startswith("__spatial_knife") for o in bpy.data.objects), "Private cutter leaked"
        assert not any(m.name.startswith("__spatial_knife") for m in bpy.data.meshes), "Private mesh leaked"

    def ask(action, **fields):
        native = sess.document()
        identity = {"session_id": sess.session_id, "host_epoch": sess.host_epoch, "document_id": native["id"],
                    "open_epoch": native["open_epoch"], "actor_id": actor["actor_id"]}
        reply = manager.handler(action)(protocol.message("live.edit."+action, identity | fields), conn)
        assert reply["type"] == "live.edit.state", reply
        return reply["payload"]

    def fresh(component, unit):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for item in list(bpy.context.scene.objects):
            bpy.data.objects.remove(item, do_unlink=True)
        mesh = bpy.data.meshes.new("Private live Knife mesh")
        bm = bmesh.new(); bmesh.ops.create_cube(bm, size=.2/unit)
        uv = bm.loops.layers.uv.new("Private native UV")
        for face in bm.faces:
            for loop in face.loops:
                loop[uv].uv = (loop.vert.co.x*unit, loop.vert.co.z*unit)
        bm.to_mesh(mesh); bm.free()
        target = bpy.data.objects.new("Private live Knife", mesh)
        bpy.context.collection.objects.link(target)
        target.select_set(True); bpy.context.view_layer.objects.active = target
        bpy.context.scene.unit_settings.scale_length = unit
        bpy.context.tool_settings.mesh_select_mode = tuple(component == c for c in ("vertex", "edge", "face"))
        bpy.ops.object.mode_set(mode="EDIT")
        with bpy.context.temp_override(window=bpy.context.window, area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name="builtin.knife")
        bm = bmesh.from_edit_mesh(target.data); spatial_model_edit._index(bm)
        bm.verts[7].co.z += .003/unit  # independent preexisting native work
        for values in (bm.faces, bm.edges, bm.verts):
            for value in values:
                value.select = False
        front = min(bm.faces, key=lambda f: sum(v.co.y for v in f.verts))
        picked = front if component == "face" else front.edges[0] if component == "edge" else front.verts[0]
        picked.select_set(True); bm.select_history.add(picked); bm.faces.active = front
        bmesh.update_edit_mesh(target.data); target.update_from_editmode()
        oid = sync.object_id(target); sync.flush()
        bpy.ops.ed.undo_push(message="Prior native work before live Knife")
        return oid, [picked.index]

    def mesh_state(oid):
        bm = bmesh.from_edit_mesh(sync.find_object(oid).data); spatial_model_edit._index(bm)
        return {"verts": [tuple(v.co) for v in bm.verts],
                "edges": [(tuple(v.index for v in e.verts), bool(e.select), bool(e.hide)) for e in bm.edges],
                "faces": [(tuple(v.index for v in f.verts), bool(f.select), bool(f.hide), f.material_index) for f in bm.faces],
                "vertex_selection": [(bool(v.select), bool(v.hide)) for v in bm.verts],
                "uv": {uv.name: [[tuple(loop[uv].uv) for loop in f.loops] for f in bm.faces] for uv in bm.loops.layers.uv.values()},
                "history": [(type(e).__name__, e.index) for e in bm.select_history], "active_face": bm.faces.active.index if bm.faces.active else None}

    def geometry(state):
        # Native Knife may enumerate equivalent new topology differently after
        # a baseline copy; compare metric geometry and corner UVs, not allocator IDs.
        unit = bpy.context.scene.unit_settings.scale_length
        positions = [tuple(round(v*unit, 5) for v in point) for point in state["verts"]]
        faces = []
        for i, row in enumerate(state["faces"]):
            corners = []
            for j, index in enumerate(row[0]):
                uv = tuple((name, tuple(round(v, 5) for v in layer[i][j])) for name, layer in state["uv"].items())
                corners.append((positions[index], uv))
            faces.append((tuple(sorted(corners)), row[3]))
        return {"verts": sorted(positions), "edges": sorted(tuple(sorted(positions[i] for i in r[0])) for r in state["edges"]),
                "faces": sorted(faces)}

    def begin(oid, component, indices):
        native = spatial_model_edit.read_state(bpy.context, sync)
        assert native["available"] and native["native_tool"] == "builtin.knife", native
        lease = lses.grant(actor["actor_id"], "exclusive")
        operation = {"tool": "mesh.knife", "native_tool": native["native_tool"], "mode": "EDIT_MESH", "target_id": oid,
                     "selection": {"component": component, "indices": indices}, "topology_token": native["topology_token"], "settings": copy.deepcopy(native["settings"])}
        state = ask("begin", base_revision=sync.flush(), lease=lease["lease_id"], targets=[{"id": oid, "generation": sync.generation(oid)}], operation=operation)
        return state["edit_session_id"], lease

    def parameters(projection, through=False, selected=False, final=False):
        path = [[-.2, -.1, -.025], [.2, -.1, -.025]]
        if final:
            path.append([.2, -.1, .035])
        return {"path_m": path, "projection": projection, "cut_through": through, "selected_only": selected}

    try:
        for perspective, unit, component, through, selected in (
                (True, 1, "face", False, False), (True, 1, "vertex", True, False), (True, 1, "face", True, True),
                (False, .001, "edge", False, False), (False, .001, "face", True, False), (False, .001, "face", True, True)):
            projection = unity_projection(perspective)
            first, final = parameters(projection, through, selected), parameters(projection, through, selected, True)
            oid, indices = fresh(component, unit); saved = view_state()
            result = modeling_tools.apply_step(editor, sync.find_object(oid), "mesh.knife", final, {"component": component, "indices": indices})
            expected = geometry(mesh_state(oid)); same_view(saved)
            assert result["outputs"]["new_edges"]["indices"]
            oid, indices = fresh(component, unit)
            before, saved = mesh_state(oid), view_state(); marker = bpy.context.scene.get(edits.STEP_PROPERTY)
            edit_id, lease = begin(oid, component, indices)
            baseline_counts = []; original_apply = modeling_tools.apply_step
            def record_baseline(*args, _counts=baseline_counts, _apply=original_apply, **kwargs):
                _counts.append(len(bmesh.from_edit_mesh(args[1].data).verts))
                return _apply(*args, **kwargs)
            modeling_tools.apply_step = record_baseline
            try:
                ask("update", edit_session_id=edit_id, sequence=1, parameters=first)
                assert geometry(mesh_state(oid)) != geometry(before), "No native change while held"
                same_view(saved)
                ask("update", edit_session_id=edit_id, sequence=2, parameters=final)
                held = mesh_state(oid)
                if geometry(held) != expected:
                    report["geometry_mismatch"] = {"expected": expected, "actual": geometry(held), "baseline_counts": baseline_counts}
                    raise AssertionError("Second live sample accumulated earlier cuts or changed projection")
                assert bpy.context.scene.get(edits.STEP_PROPERTY) == marker
                same_view(saved)
                committed = ask("commit", edit_session_id=edit_id, sequence=2)
                assert committed["phase"] == "committed" and committed["selection"]["indices"]
                assert geometry(mesh_state(oid)) == expected and baseline_counts == [8, 8, 8], baseline_counts
            finally:
                modeling_tools.apply_step = original_apply; lses.end(lease["lease_id"], actor["actor_id"])
            editor.apply("history.undo", None, {})
            assert geometry(mesh_state(oid)) == geometry(before), "One Undo lost prior native mesh/UV work"
            editor.apply("history.redo", None, {})
            assert geometry(mesh_state(oid)) == expected, "One Redo did not restore full final Knife"
            same_view(saved)
            old = {tuple(round(v*unit, 5) for v in p) for p in before["verts"]}
            new = [tuple(v*unit for v in p) for p in held["verts"] if tuple(round(v*unit, 5) for v in p) not in old]
            assert new
            if not through or selected:
                assert all(abs(p[1]+.1) < 2e-5 for p in new), (through, selected, new)
            else:
                assert any(p[1] > .099 for p in new), new
            oid, indices = fresh(component, unit)
            before, saved = mesh_state(oid), view_state(); marker = bpy.context.scene.get(edits.STEP_PROPERTY)
            edit_id, lease = begin(oid, component, indices)
            ask("update", edit_session_id=edit_id, sequence=1, parameters=first)
            ask("update", edit_session_id=edit_id, sequence=2, parameters=final)
            cancelled = ask("cancel", edit_session_id=edit_id, reason="Private exact Knife Cancel")
            lses.end(lease["lease_id"], actor["actor_id"])
            assert cancelled["phase"] == "cancelled" and mesh_state(oid) == before, "Cancel failed exact UV/selection/history/hiding restoration"
            assert bpy.context.scene.get(edits.STEP_PROPERTY) == marker; same_view(saved)
            report["cases"].append({"perspective": perspective, "unit": unit, "component": component, "cut_through": through,
                                    "selected_only": selected, "updates": 2, "baseline_counts": baseline_counts, "undo_redo": True, "cancel": True})
        report["checks"].extend(["Unity_camera_handedness_perspective_ortho", "two_actual_held_updates_each_from_baseline",
                                "one_Undo_Redo_preserves_prior_mesh_UV", "exact_Cancel_selection_history_hiding_UV",
                                "front_only_cut_through_selected_only", "view_restored_no_private_cutter_leaks"])
        for perspective, kind, through in ((p, k, t) for p in (True, False) for k in ("nonuniform", "mirrored", "sheared") for t in (False, True)):
            oid, indices = fresh("face", 1); before, saved = mesh_state(oid), view_state()
            projection = unity_projection(perspective, kind); params = parameters(projection, through=through)
            try:
                modeling_tools.apply_step(editor, sync.find_object(oid), "mesh.knife", params, {"component": "face", "indices": indices})
            except ValueError as exc:
                assert mesh_state(oid) == before, "Unsupported camera partially cut geometry"
                report["affine"].append({"kind": kind, "perspective": perspective, "cut_through": through, "outcome": "safe_refusal", "reason": str(exc)})
            else:
                after = mesh_state(oid); assert len(after["verts"]) > len(before["verts"])
                old = {tuple(round(v, 5) for v in p) for p in before["verts"]}
                new = [p for p in after["verts"] if tuple(round(v, 5) for v in p) not in old]
                if not through:
                    assert all(abs(p[1]+.1) < 2e-5 for p in new), (kind, perspective, "front-only cut hit rear geometry", new)
                matrix = Matrix([projection[i:i+4] for i in range(0, 16, 4)])
                a, b = [matrix @ Vector((*p, 1)) for p in params["path_m"]]
                a, b = Vector((a.x/a.w, a.y/a.w)), Vector((b.x/b.w, b.y/b.w))
                for point in new:
                    q = matrix @ Vector((*point, 1)); q = Vector((q.x/q.w, q.y/q.w))
                    assert abs((b-a).cross(q-a))/(b-a).length < 2e-5, (kind, point, a, b, q)
                    fraction = (q-a).dot(b-a)/(b-a).length_squared
                    assert -2e-5 <= fraction <= 1+2e-5, (kind, point, fraction)
                report["affine"].append({"kind": kind, "perspective": perspective, "cut_through": through, "outcome": "exact_projected_cut", "new_vertices": len(new)})
            same_view(saved)
        report["kernel_sha256"] = {n: hashlib.sha256((ROOT/"blender_addon/spatial_modeling"/n).read_bytes()).hexdigest() for n in ("modeling_knife.py", "modeling_tools.py", "live_edit.py")}
        report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc(); raise
    finally:
        manager.stop(); sync.unregister()
        output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:]); args.output.parent.mkdir(parents=True, exist_ok=True)
    def entry():
        try:
            print(json.dumps(run(args.output)))
        except Exception:  # noqa: BLE001 - preserve evidence, then quit this owned process
            traceback.print_exc()
            if not args.output.exists():
                args.output.write_text(json.dumps({"passed": False, "error": traceback.format_exc()}), encoding="utf-8")
        finally:
            bpy.ops.wm.quit_blender()
    bpy.app.timers.register(entry, first_interval=1.0)

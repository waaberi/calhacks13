"""P2.5 exact adapter/editor gate. Isolated background Blender only, never a personal file.

blender --background --factory-startup --python check_sketch.py --
  --extension /installed/CAD_Sketcher --output /isolated/evidence --phase create
Repeat with --phase reopen in a fresh process. GUI history mode is documented.
"""

import argparse
import hashlib
import json
import math
import sys
import traceback
import zipfile
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]


def setup(args):
    args.output.mkdir(parents=True, exist_ok=True)
    wheel = args.extension / "wheels/slvs-3.2-cp313-cp313-win_amd64.whl"
    solver = args.output / "wheel"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(solver)
    sys.path[:0] = [str(solver), str(args.extension.parent), str(ROOT / "blender_addon")]
    import CAD_Sketcher
    bpy.context.preferences.addons.new().module = "CAD_Sketcher"
    CAD_Sketcher.register()
    return {"blender": bpy.app.version_string,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "manifest_sha256": hashlib.sha256((args.extension / "blender_manifest.toml").read_bytes()).hexdigest()}


def main(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    identity = setup(args)
    from spatial_modeling import document, edits, host, preview_spatial, sketch, sync
    from spatial_modeling.commands import Refused
    identity.update(sketch.dependency_status())
    assert identity["available"], identity
    report = {"identity": identity, "checks": [], "snapshots": {}}
    messages = []
    class Session:
        def broadcast(self, msg):
            messages.append(msg)
    doc = document.Document()
    sync.register()
    sync.start(doc, Session())
    sync.flush()
    bpy.context.preferences.edit.use_global_undo = True
    bpy.ops.ed.undo_push(message="P2.5 native baseline")
    editor = edits.Editor(sync, host.undoable, document=doc)
    report["modal_state_inspectable"] = all(hasattr(window, "modal_operators") for window in bpy.context.window_manager.windows)
    report["active_modals"] = preview_spatial.modal_operators(bpy.context)

    def call(op, target=None, **kwargs):
        done = editor.apply(op, target, kwargs)
        bpy.context.view_layer.update()  # include the pinned add-on's real validation handlers
        sync.flush()
        report["checks"].append({"op": op, "solver": done.solver, "created": done.created})
        return done

    def read(sid):
        return next(record for record in sketch.snapshot() if record["id"] == sid)

    def dimension(sid, kind, ids, value=None):
        args_ = {"kind": kind, "entities": ids}
        if value is not None:
            args_["value"] = value
        return call("sketch.constrain", sid, **args_).created[0]

    def bounds(record):
        pts = [entity["at"] for entity in record["entities"] if entity["kind"] == "point"]
        return [max(point[i] for point in pts) - min(point[i] for point in pts) for i in (0, 1)]

    def close(actual, expected):
        assert math.isclose(actual, expected, abs_tol=1e-7), (actual, expected)

    path = args.output / "editable.blend"
    metadata = args.output / "editable.json"
    if args.phase == "reopen":
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
        saved = json.loads(metadata.read_text())
        sync.stop()
        sync.start(document.Document(), Session())
        sync.flush()
        assert sketch.snapshot() == saved["records"], "all native entity/constraint identities must reopen"
        assert read(saved["rectangle"]) == saved["record"]
        call("sketch.set_dimension", saved["rectangle"], constraint=saved["width"], value=.13)
        record = read(saved["rectangle"])
        close(bounds(record)[0], .13)
        close(bounds(record)[1], .06)
        assert record["solver"] == {"status": "fully_constrained", "dof": 0}
        report["snapshots"]["reopened_reedited_130x60"] = record
        report["fresh_process_reopen_edit"] = True
    else:
        bpy.context.scene.unit_settings.system = "METRIC"
        bpy.context.scene.unit_settings.scale_length = args.unit_scale
        sid = call("sketch.create", plane="XY").created[0]
        created = call("sketch.add_rectangle", sid, corner=[0, 0], opposite=[.1, .06]).created
        p1, _p2, _p3, _p4, l1, l2, l3, _l4 = created[:8]
        assert read(sid)["solver"]["status"] == "free"
        dimension(sid, "fixed", [p1])
        width = dimension(sid, "distance", [l1], .1)
        dimension(sid, "distance", [l2], .06)
        record = read(sid)
        assert record["solver"] == {"status": "fully_constrained", "dof": 0}, record
        close(bounds(record)[0], .1)
        close(bounds(record)[1], .06)
        report["snapshots"]["anchored_100x60"] = record
        call("sketch.set_dimension", sid, constraint=width, value=.12)
        record = read(sid)
        close(bounds(record)[0], .12)
        close(bounds(record)[1], .06)
        assert record["entities"][0]["at"] == [0, 0]
        report["snapshots"]["anchored_120x60"] = record
        report["native_history"] = {"available": bool(bpy.ops.ed.undo.poll()), "passed": False}
        if bpy.ops.ed.undo.poll():
            editor.apply("history.undo", None, {})
            close(bounds(read(sid))[0], .1)
            editor.apply("history.redo", None, {})
            close(bounds(read(sid))[0], .12)
            assert read(sid) == record, "Undo/Redo changed native identities or solved geometry"
            report["native_history"]["passed"] = True
        else:
            report["native_history"]["reason"] = "Blender background context has no native Undo operator; a coordinated GUI native gate is still required."
            assert not args.require_history, report["native_history"]
        before = json.dumps(read(sid), sort_keys=True)
        revision = sync.flush()
        try:
            dimension(sid, "distance", [l3], .11)
            raise AssertionError("inconsistent constraint was accepted")
        except Refused as exc:
            assert exc.code == "solver_conflict", exc
            assert exc.solver == {"status": "conflicting", "dof": None}
        assert json.dumps(read(sid), sort_keys=True) == before
        assert sync.flush() == revision
        report["conflict_rollback"] = True

        circle_id = call("sketch.create", plane="XZ").created[0]
        center, circle = call("sketch.add_circle", circle_id, center=[.03, .03], radius=.005).created
        dimension(circle_id, "fixed", [center])
        diameter = dimension(circle_id, "diameter", [circle], .02)
        call("sketch.set_dimension", circle_id, constraint=diameter, value=.03)
        record = read(circle_id)
        close(next(e for e in record["entities"] if e["kind"] == "circle")["radius"], .015)
        assert record["solver"]["dof"] == 0
        report["snapshots"]["circle_diameter_30mm"] = record

        angle_id = call("sketch.create", plane="YZ").created[0]
        a, b, baseline = call("sketch.add_line", angle_id, start=[0, 0], end=[.1, 0]).created
        c, d, angled = call("sketch.add_line", angle_id, start=[0, 0], end=[.07, .07]).created
        dimension(angle_id, "fixed", [a])
        dimension(angle_id, "horizontal", [baseline])
        dimension(angle_id, "distance", [baseline], .1)
        dimension(angle_id, "coincident", [c, a])
        dimension(angle_id, "distance", [angled], .1)
        angle = dimension(angle_id, "angle", [baseline, angled], math.pi / 4)
        call("sketch.set_dimension", angle_id, constraint=angle, value=math.pi / 3)
        record = read(angle_id)
        points = {e["id"]: e["at"] for e in record["entities"] if e["kind"] == "point"}
        u = [points[b][i] - points[a][i] for i in (0, 1)]
        v = [points[d][i] - points[c][i] for i in (0, 1)]
        measured = math.acos(sum(u[i] * v[i] for i in (0, 1)) / math.hypot(*u) / math.hypot(*v))
        close(measured, math.pi / 3)
        assert record["solver"]["dof"] == 0
        report["snapshots"]["angle_60degrees"] = record
        report["measured_angle_radians"] = measured
        # A redundant equal driving dimension is still satisfiable. Changing
        # either one inconsistently must refuse set_dimension and restore both.
        duplicate = dimension(circle_id, "diameter", [circle], .03)
        before_circle = read(circle_id)
        native_data_count = len(bpy.data.hair_curves)
        try:
            call("sketch.set_dimension", circle_id, constraint=duplicate, value=.04)
            raise AssertionError("conflicting dimension edit was accepted")
        except Refused as exc:
            assert exc.code == "solver_conflict", exc
        assert read(circle_id) == before_circle
        assert len(bpy.data.hair_curves) == native_data_count
        report["set_dimension_conflict_rollback"] = True
        # Independently measure native circle data close to the dependency's
        # local geometry epsilon; a solver flag alone is insufficient evidence.
        tiny = call("sketch.create", plane="XY").created[0]
        _, tiny_circle = call("sketch.add_circle", tiny, center=[0, 0], radius=.005).created
        tiny_dimension = dimension(tiny, "diameter", [tiny_circle], .01)
        call("sketch.set_dimension", tiny, constraint=tiny_dimension, value=1e-6 * args.unit_scale)
        from spatial_modeling.sketch import adapter
        api = adapter._api()
        native = api["sketch"].Sketch(sketch.find(tiny))
        raw_radius = api["ref"].CircleRef(native, tiny_circle).radius
        report["tiny_circle_native_readback"] = {
            "requested_native_diameter": 1e-6, "actual_native_diameter": raw_radius * 2}
        close(raw_radius * 2, 1e-6)
        for i in range(adapter.MAX_ENTITIES - len(native.data.curves)):
            api["ref"].PointRef.create(native, (i + 1, 0), fixed=True)
        assert len(native.data.curves) == adapter.MAX_ENTITIES
        call("sketch.set_dimension", tiny, constraint=tiny_dimension, value=.01)
        bounded_before = read(tiny)
        try:
            call("sketch.add_line", tiny, start=[0, 0], end=[.01, 0])
            raise AssertionError("entity limit overshoot was accepted")
        except Refused as exc:
            assert exc.code == "failed"
        assert read(tiny) == bounded_before
        original_limit = adapter.MAX_CONSTRAINTS
        try:
            adapter.MAX_CONSTRAINTS = 1  # exercise the exact native constraint boundary cheaply
            call("sketch.set_dimension", tiny, constraint=tiny_dimension, value=.012)
            bounded_before = read(tiny)
            try:
                dimension(tiny, "diameter", [tiny_circle], .012)
                raise AssertionError("constraint limit overshoot was accepted")
            except Refused as exc:
                assert exc.code == "failed"
            assert read(tiny) == bounded_before
        finally:
            adapter.MAX_CONSTRAINTS = original_limit
        report["dimension_edit_at_entity_limit"] = adapter.MAX_ENTITIES
        report["constraint_limit_postedit_rollback"] = True
        tiny_obj = sketch.find(tiny)
        tiny_obj.scale = (2, 1, 1)
        bpy.context.view_layer.update()
        isolated = sketch.snapshot()
        assert all(record["id"] != tiny for record in isolated)
        assert len(isolated) == 3, "one unsupported sketch stopped unrelated native sketch export"
        assert any(problem["id"] == tiny and "scale" in problem["reason"] for problem in sketch.snapshot_problems())
        sync.flush()
        assert sync.generation(sid) is not None, "unrelated valid sketch became unavailable"
        report["unsupported_sketch_isolated"] = True
        try:
            call("sketch.set_dimension", tiny, constraint=tiny_dimension, value=.02)
            raise AssertionError("nonrigid sketch plane was edited")
        except Refused as exc:
            assert exc.code == "failed" and "scale" in exc.message
        tiny_obj.scale = (1, 1, 1)
        bpy.context.view_layer.update()
        report["nonrigid_plane_refused"] = True
        tiny_obj = sketch.find(tiny)
        tiny_data = tiny_obj.data
        bpy.data.objects.remove(tiny_obj, do_unlink=True)
        bpy.data.hair_curves.remove(tiny_data)
        api["global"].needs_solve = False
        sync.flush()
        assert sync.generation(tiny) is None
        assert any(tiny in msg["payload"].get("removed", []) for msg in messages)
        report["sketch_removal_sync"] = True
        snap = sync.snapshot(sync.describe())
        assert len(snap["sketches"]) == 3
        assert not snap["objects"]
        assert sync.generation(sid) is not None
        report["sync_generation"] = sync.generation(sid)
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        metadata.write_text(json.dumps({"rectangle": sid, "width": width, "record": read(sid),
                                        "records": sketch.snapshot()}), encoding="utf-8")
        report["editable_native_constraints"] = sum(1 for obj in bpy.context.scene.objects
                                                   if sketch.is_sketch(obj) for _ in obj.data.sketch_constraints.all)
    report["passed"] = True
    (args.output / f"{args.phase}-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.output / f"{args.phase}-messages.json").write_text(json.dumps(messages, indent=2), encoding="utf-8")
    print("NATIVE_SKETCH_PASS", args.phase, len(report["checks"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("create", "reopen"), required=True)
    parser.add_argument("--unit-scale", type=float, default=1.0)
    parser.add_argument("--require-history", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    try:
        main(args)
    except Exception:  # noqa: BLE001 - any failure exits the native gate nonzero
        traceback.print_exc()
        print("NATIVE_SKETCH_FAILED", flush=True)
        sys.exit(1)

"""Repeated real depsgraph edits with a direct native UUID oracle and cold reopen.

Use the same --extension/--output options as check_sketch.py. Run --phase create
then --phase reopen in a different Blender process. No private/production files.
"""

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from check_sketch import setup


def main(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    identity = setup(args)
    from spatial_modeling import document, sketch, sync
    from spatial_modeling.commands import Refused
    from spatial_modeling.sketch import adapter
    api = adapter._api()
    events, failures = [], []
    real_read = api["curves"].read_uuid_list
    trial = None

    def checked_read(data, field):
        cached = real_read(data, field)
        lo, hi = (data.attributes.get(f".{field}_{suffix}") for suffix in ("lo", "hi"))
        actual = [api["curves"]._pairs_to_hex(tuple(lo.data[i].value), tuple(hi.data[i].value))
                  for i in range(len(data.curves))] if lo and hi else [""] * len(data.curves)
        if cached != actual:
            events.append({"trial": trial, "data": data.name, "field": field,
                           "cached": list(cached), "native_attributes": actual})
        return cached

    api["curves"].read_uuid_list = checked_read

    class Session:
        def broadcast(self, _message):
            pass

    def call(op, sid=None, **values):
        done = sketch.apply(op, sid, values)
        bpy.context.view_layer.update()
        sync.flush()
        return done.created

    def constrain(sid, kind, entities, value=None):
        values = {"kind": kind, "entities": entities}
        if value is not None:
            values["value"] = value
        return call("sketch.constrain", sid, **values)[0]

    def records():
        return {record["id"]: record for record in sketch.snapshot()}

    fixture = args.output / "depsgraph-editable.blend"
    metadata = args.output / "depsgraph-editable.json"
    if args.phase == "reopen":
        bpy.ops.wm.open_mainfile(filepath=str(fixture), load_ui=False)
        bpy.context.view_layer.update()
        sync.start(document.Document(), Session())
        sync.flush()
        expected = json.loads(metadata.read_text())
        assert records() == expected["records"], "fresh process changed native entity/constraint IDs"
        call("sketch.set_dimension", expected["rectangle"],
             constraint=expected["width"], value=.13)
        rectangle = records()[expected["rectangle"]]
        points = [entity["at"] for entity in rectangle["entities"] if entity["kind"] == "point"]
        assert math.isclose(max(point[0] for point in points), .13, abs_tol=1e-7)
        assert rectangle["solver"] == {"status": "fully_constrained", "dof": 0}
    else:
        for trial in range(args.cycles):
            for obj in list(bpy.data.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            for data in list(bpy.data.hair_curves):
                if data.users == 0:
                    bpy.data.hair_curves.remove(data)
            bpy.context.scene.unit_settings.scale_length = .001
            sync.start(document.Document(), Session())
            sync.flush()
            try:
                rectangle = call("sketch.create", plane="XY")[0]
                ids = call("sketch.add_rectangle", rectangle, corner=[0, 0], opposite=[.1, .06])
                constrain(rectangle, "fixed", [ids[0]])
                width = constrain(rectangle, "distance", [ids[4]], .1)
                constrain(rectangle, "distance", [ids[5]], .06)
                circle = call("sketch.create", plane="XZ")[0]
                center, rim = call("sketch.add_circle", circle, center=[.03, .03], radius=.01)
                constrain(circle, "fixed", [center])
                diameter = constrain(circle, "diameter", [rim], .02)
                angle = call("sketch.create", plane="YZ")[0]
                a, _b, baseline = call("sketch.add_line", angle, start=[0, 0], end=[.1, 0])
                c, _d, angled = call("sketch.add_line", angle, start=[0, 0], end=[.07, .07])
                constrain(angle, "fixed", [a])
                constrain(angle, "horizontal", [baseline])
                constrain(angle, "distance", [baseline], .1)
                constrain(angle, "coincident", [c, a])
                constrain(angle, "distance", [angled], .1)
                angle_dimension = constrain(angle, "angle", [baseline, angled], math.pi / 4)
                call("sketch.set_dimension", rectangle, constraint=width, value=.12)
                call("sketch.set_dimension", circle, constraint=diameter, value=.03)
                call("sketch.set_dimension", angle, constraint=angle_dimension, value=math.pi / 3)
                before = records()
                try:
                    constrain(rectangle, "distance", [ids[6]], .11)
                    raise AssertionError("conflicting dimension accepted")
                except Refused as exc:
                    assert exc.code == "solver_conflict"
                bpy.context.view_layer.update()
                assert records() == before, "rollback changed native identities or values"
                assert all(record["solver"] == {"status": "fully_constrained", "dof": 0}
                           for record in before.values())
                assert not events, "dependency cached UUIDs differ from real native attributes"
            except Exception:  # noqa: BLE001 - retain each failing fixture rather than hide retries
                failures.append({"trial": trial, "error": traceback.format_exc()})
                print("IDENTITY_CYCLE_FAIL", trial, flush=True)
            else:
                print("IDENTITY_CYCLE_PASS", trial, flush=True)
        assert not failures, failures
        bpy.ops.wm.save_as_mainfile(filepath=str(fixture))
        metadata.write_text(json.dumps({"records": records(), "rectangle": rectangle, "width": width}))
    assert not events, events
    result = {"passed": True, "identity": identity, "phase": args.phase,
              "cycles": args.cycles if args.phase == "create" else None,
              "cache_mismatches": events, "failures": failures}
    (args.output / f"identity-{args.phase}-result.json").write_text(json.dumps(result, indent=2))
    print("NATIVE_DEPSGRAPH_IDENTITY_PASS", args.phase, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("create", "reopen"), required=True)
    parser.add_argument("--cycles", type=int, default=30)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    try:
        main(args)
    except Exception:  # noqa: BLE001 - a failed native gate must exit nonzero
        traceback.print_exc()
        sys.exit(1)

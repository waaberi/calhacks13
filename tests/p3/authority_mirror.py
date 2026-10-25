"""Narrow native UI/gesture prototype against a separate authoritative worker.

Opt-in diagnostic only. Local native operators are deliberately untrusted.
Only explicitly mapped native panel operators and typed planar strokes are sent.
No production registration, generic RNA diff translation or OS input.
"""

import argparse
import copy
import json
import math
import os
import sys
import traceback
from pathlib import Path

import bpy

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
from spatial_modeling import lan, protocol, remote_control, session
from spatial_modeling.remote_client.mirror import Mirror
from spatial_modeling.remote_client.state import SceneState


class MirrorCommands:
    """Reuse production wire, scene validation, mirror, leases and commands."""

    def __init__(self, ready):
        self.ready = ready
        self.state = SceneState()
        self.mirror = Mirror()
        self.messages = []
        self.socket = lan.connect("127.0.0.1", os.environ["P3_PROTOTYPE_TOKEN"],
                                  port=ready["port"], tls=True, timeout=5)
        self.wire = remote_control._Wire(self.socket, on_event=self.receive)
        hello = protocol.message("hello", {"role": "blender-client", "name": "Private native UI mirror",
            "app": session.APP, "document": {k: ready["document"][k] for k in ("id", "open_epoch")}})
        self.wire.send(hello)
        reply = self.wire.wait(lambda m: m.get("re") == hello["id"], 10)
        assert reply["type"] == "welcome" and reply["payload"]["can_edit"], reply
        self.identity = {k: reply["payload"][k] for k in ("session_id", "host_epoch", "actor_id")}
        self.identity.update(document_id=ready["document"]["id"], open_epoch=ready["document"]["open_epoch"])
        self.wire.wait(lambda m: m["type"] == "scene.snapshot", 10)

    def receive(self, message):
        self.messages.append(message)
        if message["type"] in ("scene.snapshot", "scene.update"):
            self.state.receive(message["payload"], message["type"] == "scene.snapshot")
            self.mirror.apply(self.state)

    def command(self, op, args=None, target=None, generation=None):
        lease = protocol.message("lease.acquire", {**self.identity,
            "mode": "shared" if target else "exclusive", "targets": [target] if target else []})
        self.wire.send(lease)
        granted = self.wire.wait(lambda m: m.get("re") == lease["id"], 10)
        assert granted["type"] == "lease.granted", granted
        p = {**self.identity, "base_revision": self.state.document["revision"], "source": "ui",
             "op": op, "args": args or {}, "lease": granted["payload"]["lease"]["lease_id"]}
        if target:
            record = self.state.objects.get(target, self.state.sketches.get(target))
            p["target"] = {"id": target, "generation": record["generation"] if generation is None else generation}
        request = protocol.message("command", p)
        self.wire.send(request)
        answer = self.wire.wait(lambda m: m["type"] == "result"
                                and m["payload"]["request_id"] == request["id"], 10)
        self.wire.send(protocol.message("lease.release", {"lease_id": p["lease"]}))
        # A ping fence drains preceding command/release events without sleeping.
        self.fence()
        return answer["payload"]

    def fence(self):
        request = protocol.message("ping", {})
        self.wire.send(request)
        self.wire.wait(lambda m: m.get("re") == request["id"] and m["type"] == "pong", 10)

    def authoritative_snapshot(self):
        # A new production read-only Client connection is the authority oracle;
        # no local mirror geometry, delta inference or fixture data substitutes.
        sock = lan.connect("127.0.0.1", os.environ["P3_PROTOTYPE_TOKEN"],
                           port=self.ready["port"], tls=True, timeout=5)
        try:
            wire = remote_control._Wire(sock)
            request = protocol.message("hello", {"role": "blender-client", "name": "Authority observer",
                "app": session.APP})
            wire.send(request)
            wire.wait(lambda m: m.get("re") == request["id"], 10)
            return wire.wait(lambda m: m["type"] == "scene.snapshot", 10)["payload"]
        finally:
            sock.close()


bridge = None


class NativeMirrorMove(bpy.types.Operator):
    """Prototype mapped native UI action, using host-confirmed meters"""

    bl_idname = "spatial_prototype.move"
    bl_label = "Move host object +10 mm"

    def execute(self, context):
        receipt = bridge.command("object.move", {"by": [.01, 0, 0]}, bridge.ready["cube_id"])
        assert receipt["outcome"] == "applied", receipt
        return {"FINISHED"}


class NativeMirrorPanel(bpy.types.Panel):
    bl_label = "Private authority prototype"
    bl_idname = "SPATIAL_PROTOTYPE_PT_native"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Spatial prototype"

    def draw(self, context):
        self.layout.label(text="Prototype: mapped +10 mm and typed planar strokes only")
        self.layout.operator(NativeMirrorMove.bl_idname)
        self.layout.label(text="Other native tools change only this disposable mirror.")


def main(args):
    global bridge
    assert bpy.app.background
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ready = json.loads((args.output / "ready.json").read_text())
    bridge = MirrorCommands(ready)
    checks = []
    def check(name, condition):
        checks.append({"name": name, "passed": bool(condition)})
        assert condition, name
    bpy.utils.register_class(NativeMirrorMove)
    bpy.utils.register_class(NativeMirrorPanel)
    try:
        check("actual native panel operator sends validated command", bpy.ops.spatial_prototype.move() == {"FINISHED"})
        authoritative = bridge.authoritative_snapshot()
        cube = next(o for o in authoritative["objects"] if o["id"] == ready["cube_id"])
        check("authority independently reports 10 mm", abs(cube["transform"]["location"][0] - .01) < 1e-7)
        before = copy.deepcopy(authoritative)
        obj = bridge.mirror.objects[ready["cube_id"]]
        bpy.context.preferences.edit.use_global_undo = True
        bpy.ops.ed.undo_push(message="Mirror bypass baseline")
        bypasses = []
        def unchanged(name):
            bridge.fence()
            after = bridge.authoritative_snapshot()
            check(name + " cannot mutate authority geometry/history revision", after == before)
            bypasses.append(name)
        obj.location.x += 5
        unchanged("direct RNA location")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        check("unwrapped modifier operator executes locally", bpy.ops.object.modifier_add(type="BEVEL") == {"FINISHED"})
        unchanged("unwrapped modifier creation")
        bpy.data.objects.remove(bridge.mirror.objects[ready["child_id"]], do_unlink=True)
        unchanged("direct child deletion")
        bpy.ops.ed.undo_push(message="Mirror bypasses")
        check("scripted native Undo really executes locally", bpy.ops.ed.undo() == {"FINISHED"})
        unchanged("scripted native Undo")
        # Native UI menu/F3 operators are represented by their real execution,
        # not claimed as GUI click delivery. The authoritative worker is separate.
        obj = next(o for o in bpy.data.objects if o.get("spatial_modeling_id") == ready["cube_id"])
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.transform.translate(value=(2, 0, 0))
        unchanged("native transform operator (menu/F3 execution)")
        obj.name = "Local Outliner rename"
        collection = bpy.data.collections.new("Local Outliner collection")
        bpy.context.scene.collection.children.link(collection)
        collection.objects.link(obj)
        unchanged("Outliner rename/collection data")
        # Reset only the disposable mirror; authoritative IDs/generations come
        # from a new complete snapshot. No upload of native mirror diffs exists.
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bridge.mirror = Mirror()
        bridge.state = SceneState()
        bridge.state.receive(bridge.authoritative_snapshot(), True)
        bridge.mirror.apply(bridge.state)
        receipt = bridge.command("sketch.create", {"plane": "XY"})
        check("typed plane/sketch creation reaches native CAD", receipt["outcome"] == "applied")
        sid = receipt["created"][0]
        receipt = bridge.command("sketch.add_rectangle", {"corner": [0, 0], "opposite": [.1, .06]}, sid)
        check("same typed direct gesture route reaches authority", receipt["outcome"] == "applied")
        record = bridge.state.sketches[sid]
        points = [e["at"] for e in record["entities"] if e["kind"] == "point"]
        check("authoritative rectangle independently measures 100 x 60 mm",
              all(math.isclose(max(p[i] for p in points) - min(p[i] for p in points), v, abs_tol=1e-7)
                  for i, v in enumerate((.1, .06))))
        # Exact native entity IDs from the direct-stroke receipt; dimensions use
        # the same authority command path, without translating arbitrary RNA.
        p0, _p1, _p2, _p3, width_line, height_line, _l2, _l3 = receipt["created"][:8]
        bridge.command("sketch.constrain", {"kind": "fixed", "entities": [p0]}, sid)
        width = bridge.command("sketch.constrain", {"kind": "distance", "entities": [width_line], "value": .1}, sid)["created"][0]
        bridge.command("sketch.constrain", {"kind": "distance", "entities": [height_line], "value": .06}, sid)
        receipt = bridge.command("sketch.set_dimension", {"constraint": width, "value": .12}, sid)
        check("same native sketch accepts 120 mm width", receipt["outcome"] == "applied"
              and bridge.state.sketches[sid]["solver"] == {"status": "fully_constrained", "dof": 0})
        valid = copy.deepcopy(bridge.state.sketches[sid])
        receipt = bridge.command("sketch.constrain", {"kind": "distance", "entities": [width_line], "value": .13}, sid)
        check("conflict refuses with exact last-valid rollback", receipt["outcome"] == "rejected"
              and bridge.state.sketches[sid] == valid)
        receipt = bridge.command("history.undo")
        check("authorized global Undo reaches authority", receipt["outcome"] == "applied")
        receipt = bridge.command("history.redo")
        check("authorized global Redo reaches authority", receipt["outcome"] == "applied")
        mirror_sketch = bridge.mirror.sketches[sid]
        coverage_limit = {"mirror_type": mirror_sketch.type,
                          "native_cad_constraints_present": hasattr(mirror_sketch.data, "sketch_constraints"),
                          "automatic_native_tool_translation": False}
        check("full native CAD UI incompatibility is explicit", coverage_limit["mirror_type"] == "CURVE"
              and not coverage_limit["native_cad_constraints_present"])
        native = copy.deepcopy(bridge.state.sketches[sid])
        receipt = bridge.command("sketch.add_line", {"start": [0, 0], "end": [.01, 0]}, sid, generation=999)
        check("stale generation refused before authoritative mutation", receipt["outcome"] == "rejected"
              and bridge.state.sketches[sid] == native)
        receipt = bridge.command("document.save")
        check("native save confirmed", receipt["outcome"] == "applied")
        report = {"passed": True, "checks": checks, "bypasses": bypasses,
                  "gui_delivery": False, "production_architecture_replaced": False,
                  "strict_full_blender_acceptance": False, "snapshot": bridge.authoritative_snapshot(),
                  "full_native_ui_coverage_limit": coverage_limit,
                  "unsupported": ["generic native edits/diff upload", "native mesh Edit Mode", "modifiers",
                      "arbitrary scripts", "Outliner changes", "full native modal tools", "generic constraints UI",
                      "direct VR gesture/controller delivery", "real second-PC/WAN", "host OS/process isolation"]}
        (args.output / "mirror-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        bridge.socket.close()
        bpy.utils.unregister_class(NativeMirrorPanel)
        bpy.utils.unregister_class(NativeMirrorMove)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    try:
        main(args)
    except Exception:
        (args.output / "mirror-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise

"""Exercise real lease ownership draw handlers in an isolated GUI Blender."""

import json
import os
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p3b_gate_check import bc
from p3b_gate_check import gate_check as gc

COUNTS = {"lines": 0, "names": 0}
ERRORS = []


def instrument(ownership, name, key):
    original = getattr(ownership, name)

    def draw():
        COUNTS[key] += 1
        try:
            original()
        except Exception as exc:
            ERRORS.append(repr(exc))
            raise

    setattr(ownership, name, draw)


def materials():
    return {obj.name: {"color": tuple(obj.color),
                       "materials": [mat.name if mat else None for mat in obj.data.materials]}
            for obj in bpy.data.objects if obj.type == "MESH"}


def ownership_check():
    bc.install()
    from importlib import import_module

    import addon_utils
    ownership = import_module(f"{bc.MODULE}.ownership")
    instrument(ownership, "_draw_lines", "lines")
    instrument(ownership, "_draw_names", "names")
    addon_utils.enable(bc.MODULE, default_set=True)
    server, host, sync = bc.mod("server"), bc.mod("host"), bc.mod("sync")
    server.HEARTBEAT_TIMEOUT = 600
    yield from gc.pause(0.5)
    window = bpy.context.window_manager.windows[0]
    screen, ui = gc.Screen(window), gc.Input(window)
    ui.click(*gc.center(screen.region("OUTLINER"), 0.5, 0.05))
    yield from gc.pause()
    cube = bpy.data.objects["Cube"]
    twin = bpy.data.objects.new("OwnershipLinkedTwin", cube.data)
    bpy.context.scene.collection.objects.link(twin)
    twin.location.x = 3
    cube.data.materials.append(bpy.data.materials.new("OwnershipOriginalMaterial"))
    cube.color = (0.2, 0.4, 0.6, 1)
    twin.color = (0.6, 0.4, 0.2, 1)
    gc.select_only(cube, twin)
    with screen.override():
        bpy.ops.view3d.view_selected(use_all_regions=False)
    gc.select_only(cube)
    bpy.ops.ed.undo_push(message="P3B ownership setup")
    yield from gc.pause(0.5)
    peer, welcome, _ = yield from bc.joined("Native Ownership Validation")
    lee = gc.Lee(peer, welcome)
    before = materials()
    shared = yield from lee.lease("shared", [sync.object_id(cube)])
    yield from bc.wait(lambda: bool(ownership.marked_objects()), "ownership marks")
    actual = {o.name: name for o, name in ownership.marked_objects()}
    assert actual == {"Cube": "Native Ownership Validation",
                      "OwnershipLinkedTwin": "Native Ownership Validation"}, actual
    count_before = dict(COUNTS)
    for area in window.screen.areas:
        area.tag_redraw()
    ui.move(*gc.center(screen.region("VIEW_3D")))
    yield from bc.wait(lambda: all(COUNTS[k] > count_before[k] for k in COUNTS),
                       "both actual ownership draw callbacks")
    yield from gc.pause(0.5)
    assert not ERRORS, ERRORS
    assert before == materials(), (before, materials())
    shot = os.environ.get("P3B_OWNERSHIP_SCREENSHOT")
    if shot:
        with screen.override():
            bpy.ops.screen.screenshot(filepath=shot)
    bc.log("OWNERSHIP shared linked-object markers", actual, "draw calls", COUNTS)
    yield from lee.release(shared)
    yield from gc.gate_ended(window, ui)
    assert not ownership.marked_objects()
    yield from lee.lease("exclusive")
    yield from gc.pause(0.5)
    all_visible = {o.name for o in bpy.context.view_layer.objects if o.visible_get()}
    exclusive_marks = {o.name: n for o, n in ownership.marked_objects()}
    assert set(exclusive_marks) == all_visible, exclusive_marks
    assert set(exclusive_marks.values()) == {"Native Ownership Validation"}
    assert before == materials()
    lee.close()
    yield from bc.wait(lambda: not host.current_leases(), "disconnect release")
    yield from gc.gate_ended(window, ui)
    assert not ownership.marked_objects()
    assert before == materials()
    result = {"status": "PASS", "scope": "real Blender GUI simulated-input test",
              "shared_markers": actual, "exclusive_markers": exclusive_marks,
              "draw_counts": COUNTS, "draw_errors": ERRORS,
              "materials_and_object_colors_unchanged": before == materials(),
              "release_and_disconnect_remove_marks": True,
              "strict_locking": "not established; four separately observed bypass routes fail"}
    path = os.environ.get("P3B_OWNERSHIP_RESULT")
    if path:
        Path(path).write_text(json.dumps(result, indent=2), "utf-8")
    addon_utils.disable(bc.MODULE, default_set=True)
    yield from gc.pause()
    assert not ownership._handles
    bc.log("OWNERSHIP PASS", result)


if __name__ == "__main__":
    bc.main(ownership_check)

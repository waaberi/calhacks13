"""Finish GUI gate routes with a modifier fixture and discovered hover target.

The original harness assumes a modifier survives the native Undo bypass and
uses a fixed hover point. Preserve its first failure in r1, then make this
follow-up explicit about its independent unlocked modifier fixture.
"""

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p3b_gate_check import bc
from p3b_gate_check import gate_check as gc

original_allowed = gc.allowed


def followup_allowed(gate, what, act, check):
    if "X over Cube's modifier after Lee disconnected" not in what:
        yield from original_allowed(gate, what, act, check)
        return
    window = bpy.context.window_manager.windows[0]
    screen, ui = gc.Screen(window), gc.Input(window)
    cube = bpy.data.objects["Cube"]
    bc.log("FOLLOWUP original fixture modifier count", len(cube.modifiers))
    if not cube.modifiers:
        cube.modifiers.new("P3B unlocked modifier fixture", "BEVEL")
        bpy.ops.ed.undo_push(message="P3B unlocked modifier fixture")
    yield from gc.pause()
    count = len(cube.modifiers)
    refused_count = len(gate.refusals)
    region = screen.region("PROPERTIES")
    found = None
    for dy in range(40, min(550, region.height - 10), 16):
        for fx in (0.5, 0.75, 0.9, 0.3):
            ui.move(region.x + region.width * fx, region.y + region.height - dy)
            yield from gc.pause(0.06)
            ui.key("X")
            yield from gc.pause(0.08)
            if len(bpy.data.objects["Cube"].modifiers) == count - 1:
                found = (ui.x, ui.y)
                break
        if found:
            break
    assert found, "No native modifier X target removed the explicit unlocked fixture"
    assert len(gate.refusals) == refused_count
    gc.ROUTES.append((what, "allowed after explicit modifier-fixture/hover recovery", str(found)))
    bc.log("FOLLOWUP allowed native modifier X at", found)


gc.allowed = followup_allowed
bc.main(gc.gate_checks)

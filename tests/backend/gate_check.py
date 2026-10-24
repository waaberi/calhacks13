"""Press Blender's own keys and click its own buttons while a VR client holds a lease (#77).

GUI Blender only, started with --enable-event-simulate: Blender then takes input
only from Window.event_simulate, so every key and click here goes through
Blender's own event handling, keymaps, buttons and gizmo, as the user's would.
test_blender.py runs it:

  BLENDER=/path/to/blender pytest tests/backend/test_blender.py -k gate

Lee, a VR client, leases Cube (which also covers Twin, sharing its mesh). Every
supported route must then be refused with nothing changed and a reason, while
an unrelated object stays editable; changes by routes the gate doesn't cover
(the Python console's RNA path, an operator, Undo from a script) must be
recorded as bypasses, with a fresh snapshot for Lee. Then the same with an
exclusive lease, the automatic unlock on release and on disconnect, and
disabling the add-on while the gate runs.

It needs a display with a pointer. On a headless Wayland display without one,
Blender 5.2.2 crashes (in wl_proxy_get_version) as soon as it changes the cursor,
when hovering a number field or starting a transform; Xwayland on the same
headless compositor works. test_blender.py takes that Blender from
$BLENDER_EVENTS.
"""

import json
import os
import socket
import sys
import time
from pathlib import Path

import bpy

# isort: split
import addon_utils  # importable only after bpy
from bpy_extras import view3d_utils

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blender_check as bc
from blender_check import log, mod
from ping_client import protocol

GATE_OP = "SPATIAL_MODELING_OT_input_gate"
ROUTES = []  # (route, how it went), for the summary


class Input:
    """Simulated input in one window, at the last mouse position."""

    MODIFIERS = (("ctrl", "LEFT_CTRL"), ("shift", "LEFT_SHIFT"), ("alt", "LEFT_ALT"))

    def __init__(self, window):
        self.window = window
        self.x = self.y = 0

    def _send(self, type_, value, **mods):
        self.window.event_simulate(type_, value, x=self.x, y=self.y, **mods)

    def move(self, x, y):
        self.x, self.y = int(x), int(y)
        self._send("MOUSEMOVE", "NOTHING")

    def key(self, type_, text=None, **mods):
        """Press and release type_ with the modifier keys in mods held."""
        held = [key for name, key in self.MODIFIERS if mods.get(name)]
        flags = {name: True for name, _ in self.MODIFIERS if mods.get(name)}
        for key in held:
            self._send(key, "PRESS", **flags)
        self._send(type_, "PRESS", **flags, **({"unicode": text} if text else {}))
        if not type_.startswith("WHEEL"):
            self._send(type_, "RELEASE", **flags)
        for key in reversed(held):
            self._send(key, "RELEASE")

    def type_text(self, text):
        names = {".": "PERIOD", "-": "MINUS"}
        for ch in text:
            name = names.get(ch) or {"0": "ZERO", "1": "ONE", "2": "TWO", "3": "THREE",
                                     "4": "FOUR", "5": "FIVE", "6": "SIX", "7": "SEVEN",
                                     "8": "EIGHT", "9": "NINE"}[ch]
            self.key(name, text=ch)

    def click(self, x=None, y=None, button="LEFTMOUSE", double=False):
        if x is not None:
            self.move(x, y)
        for _ in range(2 if double else 1):
            self._send(button, "PRESS")
            self._send(button, "RELEASE")

    def drag(self, x0, y0, x1, y1, steps=6):
        self.move(x0, y0)
        self._send("LEFTMOUSE", "PRESS")
        for i in range(1, steps + 1):
            self.move(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
        self._send("LEFTMOUSE", "RELEASE")


def pause(seconds=0.25):
    """Yield to Blender's event loop for a while, so simulated events are handled."""
    end = time.monotonic() + seconds
    yield from bc.wait(lambda: time.monotonic() >= end, "a pause", timeout=seconds + 10)


def state():
    """Everything a refused edit must leave alone."""
    out = {"mode": bpy.context.mode, "units": bpy.context.scene.unit_settings.scale_length}
    for obj in bpy.data.objects:
        mesh = obj.data if obj.type == "MESH" else None
        out[obj.name] = (
            tuple(round(v, 6) for v in obj.location), tuple(round(v, 6) for v in obj.rotation_euler),
            tuple(round(v, 6) for v in obj.scale), obj.mode, obj.parent and obj.parent.name,
            tuple((m.name, m.type, getattr(m, "levels", None), m.show_viewport)
                  for m in obj.modifiers),
            mesh and (len(mesh.vertices), mesh.name),
        )
    return out


def running(window, idname):
    return any(op.bl_idname == idname for op in window.modal_operators)


def gate_ended(window, ui):
    """Yields until the input gate has ended. It ends on its next event, so send some."""
    def ended():
        ui.move(ui.x + 1, ui.y)
        return not running(window, GATE_OP)

    yield from bc.wait(ended, "the input gate to end")


def select_only(*objects):
    layer = bpy.context.view_layer
    for obj in layer.objects:
        obj.select_set(obj in objects)
    layer.objects.active = objects[0] if objects else None


class Lee:
    """A VR client that keeps everything it receives, read on its own thread."""

    def __init__(self, peer, welcome):
        self.peer, self.welcome = peer, welcome
        self.watcher = bc.Watcher(peer)

    @property
    def messages(self):
        return self.watcher.messages

    def close(self):
        """Hang up; shutdown() first, so the host sees it while the reader thread waits in recv."""
        try:
            self.peer.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.peer.close()

    def answer(self, msg, what):
        self.peer.send(msg)
        yield from bc.wait(lambda: any(m.get("re") == msg["id"] for m in self.messages), what)
        return next(m for m in self.messages if m.get("re") == msg["id"])

    def lease(self, mode, targets=()):
        reply = yield from self.answer(bc.acquire(self.welcome, mode, targets), "lease.granted")
        assert reply["type"] == "lease.granted", reply
        return reply["payload"]["lease"]

    def release(self, lease):
        self.peer.send(protocol.message("lease.release", {"lease_id": lease["lease_id"]}))
        yield from bc.wait(lambda: lease["lease_id"] not in [
            x["lease_id"] for x in mod("host").current_leases()], "the release")

    def command(self, op, target=None, args=None, lease=None, generation=None):
        msg = bc.Commander(self.peer, self.welcome).command(op, target, args, generation)
        if lease is not None:
            msg["payload"]["lease"] = lease["lease_id"]
        reply = yield from self.answer(msg, f"the result of {op}")
        assert reply["type"] == "result", reply
        return reply["payload"]


class Screen:
    """The factory startup screen's areas and regions, looked up again each time."""

    def __init__(self, window):
        self.window = window

    def area(self, kind):
        return next(a for a in self.window.screen.areas if a.type == kind)

    def region(self, kind, region="WINDOW"):
        return next(r for r in self.area(kind).regions if r.type == region)

    def view3d(self):
        return self.area("VIEW_3D"), self.region("VIEW_3D")

    def override(self, kind="VIEW_3D"):
        return bpy.context.temp_override(window=self.window, screen=self.window.screen,
                                         area=self.area(kind), region=self.region(kind))


def center(region, fx=0.5, fy=0.5):
    return region.x + region.width * fx, region.y + region.height * fy


def find_field(ui, region, obj, xs=(0.55, 0.75)):
    """Window coordinates of a number field in region that Ctrl+Wheel changes on obj.

    Scans down from the top; the change it makes is put back afterwards. None if none.
    """
    for dy in range(40, min(region.height, 700), 12):
        for fx in xs:
            before = state()[obj.name]
            saved = (obj.location.copy(), obj.rotation_euler.copy(), obj.scale.copy())
            ui.move(region.x + region.width * fx, region.y + region.height - dy)
            yield from pause(0.06)
            ui.key("WHEELUPMOUSE", ctrl=True)
            yield from pause(0.06)
            if state()[obj.name] != before:
                obj.location, obj.rotation_euler, obj.scale = saved
                bpy.ops.ed.undo_push(message="Put the field back")
                return ui.x, ui.y
    return None


def refused(gate, what, act, reason):
    """act() (a generator) must be refused before anything changes, with reason in the reason."""
    window = bpy.context.window_manager.windows[0]
    before, count = state(), len(gate.refusals)
    yield from act()
    yield from pause()
    after = state()
    changed = {k: (before.get(k), after.get(k)) for k in set(before) | set(after)
               if before.get(k) != after.get(k)}
    assert not changed, f"{what} changed Blender: {changed}"
    assert len(gate.refusals) > count, f"{what} wasn't refused (no reason shown)"
    by, shown = gate.refusals[-1]
    assert reason in shown, (what, shown)
    assert not any(op.bl_idname.startswith("TRANSFORM_OT") for op in window.modal_operators)
    how = "input gate" if " in " in by else "gate key"  # see gate._refuse's callers
    ROUTES.append((what, f"gated before the change ({how})", shown))
    log(f"refused before any change by the {how} ({by}): {what}: {shown!r}")


def allowed(gate, what, act, check):
    """act() must go through to Blender's own tool: check() is true afterwards, nothing refused."""
    count = len(gate.refusals)
    yield from act()
    yield from pause()
    assert len(gate.refusals) == count, (what, list(gate.refusals)[count:])
    assert check(), f"{what} didn't do what Blender does"
    ROUTES.append((what, "allowed", ""))
    log(f"allowed: {what}")


def keymap_table(gate):
    """Every gate key matches one of Blender 5.2's own items, and comes before it."""
    wm = bpy.context.window_manager
    for key in gate.SHORTCUTS:
        name = key["keymap"][0]
        mods = {m: int(bool(key["mods"].get(m))) for m in ("shift", "ctrl", "alt")}

        def same(i, key=key, mods=mods):
            return (i.type == key["type"] and i.value == key["value"] and i.active
                    and all(int(getattr(i, m)) == v for m, v in mods.items()))

        own = [i for i in wm.keyconfigs.default.keymaps[name].keymap_items
               if i.idname == key["tool"] and same(i)
               and (key["menu"] is None or i.properties.name == key["menu"])]
        assert own, f"Blender has no {key['tool']} {key['menu'] or ''} on {key} in {name!r}"
        items = list(wm.keyconfigs.user.keymaps[name].keymap_items)
        first = next(n for n, i in enumerate(items) if same(i))
        assert items[first].idname == "spatial_modeling.gate", (name, key, items[first].idname)
    log(f"{len(gate.SHORTCUTS)} gate keys match Blender's own and come first in their keymaps")


def gate_checks():
    assert bc.GUI, "the gate check needs GUI Blender with --enable-event-simulate"
    assert bpy.app.use_event_simulate, "start Blender with --enable-event-simulate"
    bc.install()
    addon_utils.enable(bc.MODULE, default_set=True)
    gate, host, server, sync = mod("gate"), mod("host"), mod("server"), mod("sync")
    server.HEARTBEAT_TIMEOUT = 600.0  # Lee sends no pings during the long check
    yield from pause(0.5)  # Blender merges the add-on's keymap items in its event loop
    keymap_table(gate)

    window = bpy.context.window_manager.windows[0]
    screen, ui = Screen(window), Input(window)
    ui.click(*center(screen.region("OUTLINER"), 0.5, 0.05))  # the window takes keys after a click
    yield from pause()

    collection = bpy.context.scene.collection
    cube = bpy.data.objects["Cube"]
    cube.location = (0.5, 0, 0)
    cube.modifiers.new("Subdivision", "SUBSURF").levels = 1
    twin = bpy.data.objects.new("Twin", cube.data)  # a linked duplicate: same mesh
    lone = bpy.data.objects.new("Lone", cube.data.copy())
    spare = bpy.data.objects.new("Spare", cube.data.copy())
    kid = bpy.data.objects.new("Kid", None)  # Cube's child: covered by a lease on Cube
    for obj, x in ((twin, 4), (lone, -4), (spare, -8), (kid, 0)):
        collection.objects.link(obj)
        obj.location = (x, 0, 0)
    kid.parent = cube
    select_only(cube)
    area, _ = screen.view3d()
    area.spaces.active.show_region_ui = True  # the sidebar, on its Item tab
    props = screen.area("PROPERTIES").spaces.active
    props.context = "OBJECT"
    bpy.ops.ed.undo_push(message="Gate check set-up")
    yield from pause(0.5)

    with screen.override():
        assert not bpy.ops.spatial_modeling.gate.poll(), "the gate keys are live with no lease"
    assert not running(window, GATE_OP)
    sidebar_field = yield from find_field(ui, screen.region("VIEW_3D", "UI"), cube)
    select_only(cube)
    props.context = "OBJECT"  # never scan another tab: Ctrl+Wheel would flip render engines
    yield from pause(0.3)
    assert props.context == "OBJECT", props.context
    props_field = yield from find_field(ui, screen.region("PROPERTIES"), cube)
    assert sidebar_field and props_field, (sidebar_field, props_field)
    log(f"with no lease: gate keys off, no input gate; Location fields found at {sidebar_field} "
        f"(sidebar) and {props_field} (Properties) by Ctrl+Wheel")

    peer, welcome, _ = yield from bc.joined("Lee")
    lee = Lee(peer, welcome)
    cube_id, twin_id, kid_id = (sync.object_id(o) for o in (cube, twin, kid))
    with screen.override():
        bpy.ops.object.mode_set(mode="EDIT")  # the host is in Edit Mode when the lease begins
    yield from pause()
    shared = yield from lee.lease("shared", [cube_id])
    assert shared["targets"][0] == cube_id and set(shared["targets"]) == {
        cube_id, twin_id, kid_id}, shared
    yield from bc.wait(lambda: running(window, GATE_OP), "the input gate to start")
    yield from pause(0.5)
    assert bpy.data.objects["Cube"].mode == "EDIT", "the gate threw the host out of Edit Mode"
    with screen.override():
        bpy.ops.object.mode_set(mode="OBJECT")  # nothing was edited: no bypass
    yield from pause(0.5)
    assert not gate.bypasses, list(gate.bypasses)
    log("already in Edit Mode when the lease began: stays there; leaving unchanged is no bypass")
    log("Lee holds a shared lease on Cube (and Twin, sharing its mesh, and Kid, its child); "
        "the input gate runs")
    yield from shared_mode(gate, host, screen, ui, lee, shared, sidebar_field, props_field)

    yield from lee.release(shared)
    yield from gate_ended(window, ui)
    yield from unlocked(gate, screen, ui, sidebar_field, "after the release")

    exclusive = yield from lee.lease("exclusive")
    yield from bc.wait(lambda: running(window, GATE_OP), "the input gate to start again")
    yield from exclusive_mode(gate, screen, ui, sidebar_field)
    lee.close()
    yield from bc.wait(lambda: not host.current_leases(), "Lee's leases to end on disconnect")
    yield from gate_ended(window, ui)
    assert exclusive["lease_id"] not in [x["lease_id"] for x in host.current_leases()]
    yield from unlocked(gate, screen, ui, sidebar_field, "after Lee disconnected", delete=True)

    peer, welcome, _ = yield from bc.joined("Lee again")
    lee = Lee(peer, welcome)
    yield from lee.lease("shared", [sync.object_id(bpy.data.objects["Cube"])])
    yield from bc.wait(lambda: running(window, GATE_OP), "the input gate to start")
    addon_utils.disable(bc.MODULE, default_set=True)
    yield from pause()
    assert not running(window, GATE_OP), "the input gate outlived the add-on"
    lee.close()
    ui.click(*center(screen.region("VIEW_3D")))
    yield from pause()
    log("disabling the add-on while the input gate ran ended it; Blender carries on")

    server.HEARTBEAT_TIMEOUT = 6.0
    out = os.environ.get("SPATIAL_MODELING_GATE_ROUTES")
    if out:
        Path(out).write_text(json.dumps(ROUTES, indent=1), "utf-8")
    for route, how, shown in ROUTES:
        log(f"  {how:28} {route}" + (f" ({shown})" if shown else ""))


def shared_mode(gate, host, screen, ui, lee, lease, sidebar_field, props_field):
    cube, twin = bpy.data.objects["Cube"], bpy.data.objects["Twin"]
    lone, spare = bpy.data.objects["Lone"], bpy.data.objects["Spare"]
    view = screen.region("VIEW_3D")
    busy = "Lee is editing Cube"

    def at_view(*keys):
        def act():
            ui.move(*center(view, 0.3, 0.7))
            for type_, mods in keys:
                ui.key(type_, **mods)
            yield
        return act

    for name, type_, mods in (("G (move)", "G", {}), ("R (rotate)", "R", {}),
                              ("S (scale)", "S", {}), ("Alt+G (clear location)", "G", {"alt": 1}),
                              ("Alt+R (clear rotation)", "R", {"alt": 1}),
                              ("Ctrl+M (mirror)", "M", {"ctrl": 1}),
                              ("X (delete)", "X", {}), ("Delete", "DEL", {}),
                              ("Ctrl+A (Apply menu)", "A", {"ctrl": 1}),
                              ("right-click (object context menu)", "RIGHTMOUSE", {}),
                              ("Ctrl+1 (Subdivision Set)", "ONE", {"ctrl": 1}),
                              ("Tab (Edit Mode)", "TAB", {}),
                              ("Ctrl+Z (Undo)", "Z", {"ctrl": 1}),
                              ("Ctrl+Shift+Z (Redo)", "Z", {"ctrl": 1, "shift": 1})):
        select_only(cube)
        reason = "Undo and Redo wait" if type_ == "Z" else busy
        if type_ == "RIGHTMOUSE":
            def act():
                ui.click(*center(view, 0.3, 0.7), button="RIGHTMOUSE")
                yield
        else:
            act = at_view((type_, mods))
        yield from refused(gate, f"{name} on Cube", act, reason)
        ui.key("ESC")  # closes a menu if one had opened
        yield from pause(0.1)

    select_only(twin)
    yield from refused(gate, "G on Twin (shares Cube's mesh)", at_view(("G", {})), busy)
    yield from refused(gate, "Delete on Twin", at_view(("DEL", {})), busy)
    select_only(lone)
    yield from refused(gate, "Ctrl+Z with only Lone selected", at_view(("Z", {"ctrl": 1})),
                       "Undo and Redo wait")
    select_only(spare)
    yield from allowed(gate, "Delete on Spare (not leased) while Lee edits Cube",
                       at_view(("DEL", {})), lambda: "Spare" not in bpy.data.objects)
    select_only(lone)
    window = bpy.context.window_manager.windows[0]
    yield from allowed(gate, "G on Lone (not leased)", at_view(("G", {})),
                       lambda: running(window, "TRANSFORM_OT_translate"))
    ui.key("ESC")
    yield from pause()

    select_only(cube)
    for where, field, tab in (("the sidebar", sidebar_field, None),
                              ("the Properties editor", props_field, "OBJECT")):
        if tab:
            screen.area("PROPERTIES").spaces.active.context = tab
            yield from pause(0.1)

        def wheel(field=field):
            ui.move(*field)
            yield from pause(0.06)
            ui.key("WHEELUPMOUSE", ctrl=True)

        def typed(field=field):
            ui.click(*field, double=True)
            ui.key("A", ctrl=True)
            ui.type_text("2.5")
            ui.key("RET")
            yield

        def reset(field=field):
            ui.move(*field)
            yield from pause(0.06)
            ui.key("BACK_SPACE")

        yield from refused(gate, f"Ctrl+Wheel on Location in {where}", wheel, busy)
        yield from refused(gate, f"double-click and type a Location in {where}", typed, busy)
        ui.key("ESC")
        yield from refused(gate, f"Backspace (reset) on Location in {where}", reset, busy)

    sidebar = screen.region("VIEW_3D", "UI")
    count = len(gate.refusals)
    ui.click(sidebar.x + sidebar.width - 6, sidebar.y + sidebar.height - 60)  # the tab strip
    yield from pause()
    assert len(gate.refusals) == count, "a click on the sidebar's tabs was refused"
    log("the sidebar's tab strip still takes clicks")

    screen.area("PROPERTIES").spaces.active.context = "MODIFIER"
    yield from pause(0.2)
    region = screen.region("PROPERTIES")

    def clicks():
        for fy in (0.97, 0.93, 0.9, 0.86, 0.82, 0.78):
            for fx in (0.15, 0.4, 0.6, 0.85, 0.95):
                ui.click(*center(region, fx, fy))
                yield from pause(0.03)
                ui.key("ESC")

    yield from refused(gate, "clicks across the Modifiers tab (Add Modifier, the stack)",
                       clicks, busy)
    for name, type_, mods in (("X", "X", {}), ("Delete", "DEL", {}), ("Ctrl+A", "A", {"ctrl": 1}),
                              ("Shift+D", "D", {"shift": 1})):
        def hover_key(type_=type_, mods=mods):
            ui.move(*center(region, 0.5, 0.9))
            yield from pause(0.06)
            ui.key(type_, **mods)

        yield from refused(gate, f"{name} over Cube's modifier", hover_key, busy)
    screen.area("PROPERTIES").spaces.active.context = "OBJECT"

    with screen.override():
        bpy.ops.wm.tool_set_by_id(name="builtin.move")
    yield from pause(0.3)
    view = screen.region("VIEW_3D")
    gizmo = view3d_utils.location_3d_to_region_2d(view, view.data, cube.matrix_world.translation)
    gx, gy = view.x + gizmo.x, view.y + gizmo.y

    def on_gizmo():
        ui.drag(gx, gy, gx + 80, gy + 40)
        yield

    tx, ty = view3d_utils.location_3d_to_region_2d(view, view.data,
                                                   bpy.data.objects["Twin"].location)

    def tweak():  # the Tweak tool selects Twin on the press and moves it on the drag
        with screen.override():
            bpy.ops.wm.tool_set_by_id(name="builtin.select")
        yield from pause(0.2)
        ui.drag(view.x + tx, view.y + ty, view.x + tx + 60, view.y + ty + 30)

    yield from refused(gate, "dragging the Move tool's gizmo", on_gizmo, busy)
    yield from refused(gate, "dragging Twin with the Tweak tool", tweak, busy)
    select_only(cube)
    with screen.override():
        bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
    yield from pause(0.2)

    count = len(gate.refusals)
    with screen.override():
        bpy.ops.object.mode_set(mode="EDIT")  # what the header's mode menu runs
    yield from bc.wait(lambda: cube.mode == "OBJECT", "the gate to leave Edit Mode")
    assert len(gate.refusals) > count and gate.refusals[-1][0] == "object.mode_set"
    ROUTES.append(("Edit Mode from the mode menu or pie",
                   "left at the next tick, before any edit", gate.refusals[-1][1]))
    log("Edit Mode entered by an ungated route was left before anything could change")

    yield from bypasses(gate, host, screen, lee, lease)


def bypasses(gate, host, screen, lee, lease):
    """Routes the gate doesn't cover: each is a recorded bypass and Lee gets a fresh snapshot."""
    sync = mod("sync")
    cube = bpy.data.objects["Cube"]
    cube_id = sync.object_id(cube)

    def detected(what, act, history=False, target=cube_id):
        count, seen = len(gate.bypasses), len(lee.messages)
        generation = sync.generation(cube_id)
        act()
        yield from bc.wait(lambda: len(gate.bypasses) > count, f"the bypass by {what}")
        found = gate.bypasses[-1]
        assert found["owner"] == "Lee" and found["lease_id"] == lease["lease_id"], found
        assert found["history"] == history and (history or target in found["objects"]), found
        yield from bc.wait(lambda: any(m["type"] == "scene.snapshot"
                                       for m in lee.messages[seen:]), "Lee's fresh snapshot")
        assert not host._commands.frozen, "edits stayed stopped after the snapshot went out"
        ROUTES.append((what, "detected after: bypass recorded", found["operator"] or ""))
        log(f"detected after the change: {what}; last operator {found['operator']!r}; Lee got "
            "a fresh scene.snapshot")
        return generation

    def console():
        bpy.data.objects["Cube"].location.x += 1  # the RNA path the sidebar's field sets

    old = yield from detected("obj.location from Python (console, script, add-on)", console)
    receipt = yield from lee.command("object.move", cube_id, {"by": [0.01, 0, 0]}, lease,
                                     generation=old)
    assert receipt["error"]["code"] == "stale_revision", receipt
    receipt = yield from lee.command("object.move", cube_id, {"by": [0.01, 0, 0]}, lease)
    assert receipt["outcome"] == "applied", receipt
    log("Lee's move from before the bypass is stale_revision; from the fresh snapshot, applied")

    def operator():
        with screen.override():
            bpy.ops.object.modifier_add(type="BEVEL")

    yield from detected("an operator the gate doesn't wrap (modifier_add from a menu or "
                        "script)", operator)

    kid_id = sync.object_id(bpy.data.objects["Kid"])

    def remove():
        bpy.data.objects.remove(bpy.data.objects["Kid"])

    yield from detected("deleting Cube's child Kid from Python", remove, target=kid_id)

    def undo():
        bpy.ops.ed.undo()  # what Edit > Undo and Undo History run

    yield from detected("Undo from the Edit menu (bpy.ops.ed.undo)", undo, history=True)


def exclusive_mode(gate, screen, ui, sidebar_field):
    lone = bpy.data.objects["Lone"]
    view = screen.region("VIEW_3D")
    busy = "Lee is editing — wait for Apply"
    select_only(lone)

    def at_view(type_, **mods):
        def act():
            ui.move(*center(view, 0.3, 0.7))
            ui.key(type_, **mods)
            yield
        return act

    for name, type_, mods in (("G", "G", {}), ("Delete", "DEL", {}),
                              ("Shift+A (Add menu)", "A", {"shift": 1}),
                              ("Shift+D (duplicate)", "D", {"shift": 1}),
                              ("Ctrl+Z", "Z", {"ctrl": 1})):
        yield from refused(gate, f"exclusive: {name} on Lone", at_view(type_, **mods), busy)
        ui.key("ESC")

    def wheel():
        ui.move(*sidebar_field)
        yield from pause(0.06)
        ui.key("WHEELUPMOUSE", ctrl=True)

    yield from refused(gate, "exclusive: Ctrl+Wheel on Lone's Location in the sidebar", wheel,
                       busy)
    screen.area("PROPERTIES").spaces.active.context = "SCENE"
    yield from pause(0.2)
    region = screen.region("PROPERTIES")

    def clicks():
        for fy in (0.95, 0.9, 0.85, 0.8, 0.75, 0.7):
            ui.click(*center(region, 0.7, fy), double=True)
            ui.key("ESC")
            yield from pause(0.03)

    yield from refused(gate, "exclusive: clicks in the Scene tab (units)", clicks, busy)
    screen.area("PROPERTIES").spaces.active.context = "OBJECT"


def unlocked(gate, screen, ui, sidebar_field, when, delete=False):
    """Nothing is held: Blender's own tools work again."""
    cube = bpy.data.objects["Cube"]
    view = screen.region("VIEW_3D")
    select_only(cube)
    x = cube.location.x

    def wheel():
        ui.move(*sidebar_field)
        yield from pause(0.06)
        ui.key("WHEELUPMOUSE", ctrl=True)

    yield from allowed(gate, f"Ctrl+Wheel on Cube's Location {when}", wheel,
                       lambda: bpy.data.objects["Cube"].location.x != x)

    def tab():
        ui.move(*center(view, 0.3, 0.7))
        ui.key("TAB")
        yield

    yield from allowed(gate, f"Tab {when}", tab, lambda: bpy.data.objects["Cube"].mode == "EDIT")
    yield from tab()
    yield from pause()
    assert bpy.data.objects["Cube"].mode == "OBJECT"
    if delete:
        lone = bpy.data.objects["Lone"]
        select_only(lone)

        def delete_key():
            ui.move(*center(view, 0.3, 0.7))
            ui.key("DEL")
            yield

        yield from allowed(gate, f"Delete on Lone {when}", delete_key,
                           lambda: "Lone" not in bpy.data.objects)

        def undo():
            ui.key("Z", ctrl=True)
            yield

        yield from allowed(gate, f"Ctrl+Z {when}", undo, lambda: "Lone" in bpy.data.objects)
    if delete:
        props = screen.area("PROPERTIES").spaces.active
        props.context = "MODIFIER"
        yield from pause(0.2)
        count = len(bpy.data.objects["Cube"].modifiers)
        region = screen.region("PROPERTIES")

        def remove():
            ui.move(*center(region, 0.5, 0.9))
            yield from pause(0.06)
            ui.key("X")

        yield from allowed(gate, f"X over Cube's modifier {when}", remove,
                           lambda: len(bpy.data.objects["Cube"].modifiers) == count - 1)
        props.context = "OBJECT"
    cube = bpy.data.objects["Cube"]
    select_only(cube)
    with screen.override():
        bpy.ops.wm.tool_set_by_id(name="builtin.move")
    yield from pause(0.3)
    x = cube.location.copy()
    at = view3d_utils.location_3d_to_region_2d(view, view.data, cube.matrix_world.translation)

    def on_gizmo():
        ui.drag(view.x + at.x, view.y + at.y, view.x + at.x + 80, view.y + at.y + 40)
        yield

    yield from allowed(gate, f"dragging the Move tool's gizmo {when}", on_gizmo,
                       lambda: bpy.data.objects["Cube"].location != x)
    twin = bpy.data.objects["Twin"]
    x = twin.location.copy()
    at = view3d_utils.location_3d_to_region_2d(view, view.data, twin.location)

    def tweak():
        with screen.override():
            bpy.ops.wm.tool_set_by_id(name="builtin.select")
        yield from pause(0.2)
        ui.drag(view.x + at.x, view.y + at.y, view.x + at.x + 60, view.y + at.y + 30)

    yield from allowed(gate, f"dragging Twin with the Tweak tool {when}", tweak,
                       lambda: bpy.data.objects["Twin"].location != x)
    with screen.override():
        bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
    select_only(bpy.data.objects["Cube"])

    def grab():
        ui.move(*center(view, 0.3, 0.7))
        ui.key("G")
        yield

    window = bpy.context.window_manager.windows[0]
    yield from allowed(gate, f"G {when}", grab, lambda: running(window,
                                                                "TRANSFORM_OT_translate"))
    ui.key("ESC")
    yield from pause()


if __name__ == "__main__":
    bc.main(gate_checks)

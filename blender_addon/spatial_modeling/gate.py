"""The host desktop's own edits wait while another participant's lease covers them (#77).

Implements "the host blocks its own desktop edits" in "Leases and presence"
(contracts/README.md) and P3B's rule that Blender checks permission BEFORE a
supported native edit. Viewing, navigation, selection and the table are never
blocked, and while nobody else holds a lease Blender behaves exactly as without
the add-on.

Blender has no hook that runs before an operator or a property change: its
handlers (depsgraph, msgbus, undo) all run after, and built-in operators can't be
replaced or given another poll from Python. So the gate stands in front of the
input that starts an edit, and asks host.blocked() what that edit would change:

1. Shortcuts. SHORTCUTS puts an add-on keymap item on each of Blender's own
   editing keys. Blender tries add-on items first. Gate's poll is false unless
   another participant holds a lease, so the key falls through to Blender's own
   item. Otherwise Gate.invoke() asks: refused, it reports why and returns
   CANCELLED, which consumes the key; allowed, it returns PASS_THROUGH and
   Blender's own item runs. These are G, R, S, the tools' drags, Alt+G/R/S,
   X and Delete, Shift+A, Ctrl+A, the object context menu, Shift+D, Alt+D,
   Ctrl+J, Ctrl+P, Ctrl+0..5, Tab, Ctrl+Z, Ctrl+Shift+Z, and in the Properties
   editor and Outliner their Delete, Apply and Duplicate keys. Custom keymaps
   and other key bindings aren't covered.
2. Pointers. While another participant holds a lease, InputGate, a modal
   operator, runs in every window, so it sees each event before Blender's
   regions do. It consumes the clicks, Ctrl/Alt+wheel and button hotkeys
   (UI_HOTKEYS) that would edit a blocked object in the Properties editor's
   object tabs (DOCUMENT_TABS too, for an exclusive lease), in the 3D View
   sidebar's Item tab (its tabs stay clickable) and on the transform gizmo. It
   lets everything else through, and everything while another modal operator
   (a transform, say) runs in that window. It ends itself when no lease is held.
   While it runs, Blender postpones its autosave, as for any modal operator.
3. Edit Mode entered on a blocked object by a route that isn't gated (the mode
   menu, the pie) is left again at the next timer tick, before anything in Edit
   Mode could change the object's data.

Everything else isn't gated: the header menus, F3 search, the Python console,
scripts, other add-ons, the Outliner's renaming and drag and drop, and edits
already under way when a lease begins. sync.py reports every change it finds
outside a command (on_change); one that touches what another participant's
lease covers, or Undo/Redo while anyone else holds a lease, is a bypass:
STRICT LOCK BYPASSED in the log (with the operator Blender recorded just before, if any), a
warning in Blender, an entry in `bypasses`, and the host stops command writes
until it has re-read the scene and sent every client a fresh scene.snapshot, as
after an unknown outcome. Strict locking did not pass for that route.
"""

import logging
import time
from collections import deque

import bpy
from bpy.app.handlers import persistent
from bpy_extras import view3d_utils
from mathutils import Vector

from . import host
from . import sync as scene_sync

KINDS = (
    ("selected", "Selected", "The selected objects, or those in Edit Mode"),
    ("active", "Selected and active", "The selected objects and the active one"),
    ("object", "Context object", "The object the Properties editor shows"),
    ("ids", "Outliner selection", "The objects selected in the Outliner"),
    ("new", "Nothing existing", "Only adds: only an exclusive lease blocks it"),
    ("history", "Everything", "Undo and Redo: any other participant's lease blocks it"),
)

_OBJECT_MODE = ("Object Mode", "EMPTY", "WINDOW")
_NON_MODAL = ("Object Non-modal", "EMPTY", "WINDOW")
_SCREEN = ("Screen", "EMPTY", "WINDOW")
_PROPERTIES = ("Property Editor", "PROPERTIES", "WINDOW")
_OUTLINER = ("Outliner", "OUTLINER", "WINDOW")


def _key(keymap, tool, kind, type_, value="PRESS", menu=None, **mods):
    return {"keymap": keymap, "tool": tool, "menu": menu, "kind": kind, "type": type_,
            "value": value, "mods": mods}


# Blender 5.2's default editing keys (test: each matches an item of the default keymap).
SHORTCUTS = (
    _key(_OBJECT_MODE, "transform.translate", "selected", "G"),
    _key(_OBJECT_MODE, "transform.rotate", "selected", "R"),
    _key(_OBJECT_MODE, "transform.resize", "selected", "S"),
    _key(_OBJECT_MODE, "transform.translate", "selected", "LEFTMOUSE", "CLICK_DRAG"),
    _key(_OBJECT_MODE, "transform.mirror", "selected", "M", ctrl=True),
    _key(_OBJECT_MODE, "object.location_clear", "selected", "G", alt=True),
    _key(_OBJECT_MODE, "object.rotation_clear", "selected", "R", alt=True),
    _key(_OBJECT_MODE, "object.scale_clear", "selected", "S", alt=True),
    _key(_OBJECT_MODE, "object.delete", "selected", "X"),
    _key(_OBJECT_MODE, "object.delete", "selected", "X", shift=True),
    _key(_OBJECT_MODE, "object.delete", "selected", "DEL"),
    _key(_OBJECT_MODE, "object.delete", "selected", "DEL", shift=True),
    _key(_OBJECT_MODE, "wm.call_menu", "new", "A", menu="VIEW3D_MT_add", shift=True),
    _key(_OBJECT_MODE, "wm.call_menu", "selected", "A", menu="VIEW3D_MT_object_apply", ctrl=True),
    _key(_OBJECT_MODE, "wm.call_menu", "selected", "RIGHTMOUSE",
         menu="VIEW3D_MT_object_context_menu"),
    _key(_OBJECT_MODE, "wm.call_menu", "selected", "APP", menu="VIEW3D_MT_object_context_menu"),
    _key(_OBJECT_MODE, "object.duplicate_move", "new", "D", shift=True),
    _key(_OBJECT_MODE, "object.duplicate_move_linked", "new", "D", alt=True),
    _key(_OBJECT_MODE, "object.join", "active", "J", ctrl=True),
    _key(_OBJECT_MODE, "object.parent_set", "active", "P", ctrl=True),
    *(_key(_OBJECT_MODE, "object.subdivision_set", "selected", n, ctrl=True)
      for n in ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE")),
    _key(_NON_MODAL, "object.mode_set", "active", "TAB"),
    _key(_SCREEN, "ed.undo", "history", "Z", ctrl=True),
    _key(_SCREEN, "ed.redo", "history", "Z", ctrl=True, shift=True),
    _key(_PROPERTIES, "object.modifier_remove", "object", "X"),
    _key(_PROPERTIES, "object.modifier_remove", "object", "DEL"),
    _key(_PROPERTIES, "object.modifier_copy", "object", "D", shift=True),
    _key(_PROPERTIES, "object.modifier_apply", "object", "A", ctrl=True),
    _key(_OUTLINER, "outliner.delete", "ids", "X"),
    _key(_OUTLINER, "outliner.delete", "ids", "DEL"),
    *(_key((f"3D View Tool: {name}", "VIEW_3D", "WINDOW"), op, "selected", "LEFTMOUSE",
           "CLICK_DRAG")
      for name, op in (("Move", "transform.translate"), ("Rotate", "transform.rotate"),
                       ("Scale", "transform.resize"), ("Tweak (fallback)", "transform.translate"))),
)

# Properties editor tabs that edit the object they show; and, for an exclusive
# lease, the document (Unit Scale moves every object; collections decide what's in it).
OBJECT_TABS = frozenset({"OBJECT", "MODIFIER", "DATA", "CONSTRAINT", "PHYSICS", "PARTICLES",
                         "MATERIAL", "SHADERFX", "BONE", "BONE_CONSTRAINT", "TEXTURE"})
DOCUMENT_TABS = frozenset({"SCENE", "COLLECTION"})
# Keys a hovered button acts on: reset, enter/edit, negate, keyframes, keying sets,
# eyedropper, drivers, paste, delete, apply.
UI_HOTKEYS = frozenset({"BACK_SPACE", "DEL", "RET", "NUMPAD_ENTER", "MINUS", "NUMPAD_MINUS",
                        "I", "K", "E", "D", "V", "X", "A"})
TRANSFORM_TOOLS = frozenset({"builtin.move", "builtin.rotate", "builtin.scale",
                             "builtin.transform", "builtin.scale_cage"})
STARTS = frozenset({"PRESS", "DOUBLE_CLICK", "CLICK_DRAG"})
TAB_STRIP = 24  # px (at UI scale 1) at the sidebar's outer edge where its tabs are
OPERATOR_RECENT = 0.5  # s: an operator recorded this long before a bypass is named in the log
MAX_KEPT = 100

log = logging.getLogger(__name__)

refusals = deque(maxlen=MAX_KEPT)  # (what was refused, reason), newest last
bypasses = deque(maxlen=MAX_KEPT)  # {at, objects, owner, lease_id, history, operator}
_pending = []  # bypasses seen by on_change or the Undo handlers, reported by poll()
_keymaps = []  # (keymap, item) added by register()
_active_mode = (None, "OBJECT")  # (session_uid, mode) of the active object at the last poll
_last_op = (None, None, 0.0)  # (pointer, name, monotonic time first seen) of wm.operators[-1]


def _affected(context, kind):
    """(objects, whole) the edit started from this context would change."""
    if kind == "history":
        return [], True
    if kind == "new":
        return [], False
    if kind == "object":
        return [context.object], False
    if kind == "ids":
        ids = getattr(context, "selected_ids", None)
        if ids is not None:
            return [i for i in ids if isinstance(i, bpy.types.Object)], False
        return list(context.selected_objects), False
    objects = list(context.selected_objects)
    if context.mode != "OBJECT":
        objects += list(getattr(context, "objects_in_mode", None) or ())
    if kind == "active":
        objects.append(context.active_object)
    return objects, False


def _refuse(op, reason, what):
    refusals.append((what, reason))
    log.info("refused %s: %s", what, reason)
    op.report({"WARNING"}, reason)


class SPATIAL_MODELING_OT_gate(bpy.types.Operator):
    """Wait while someone else is editing what this would change"""

    bl_idname = "spatial_modeling.gate"
    bl_label = "Check Who Is Editing"
    bl_options = frozenset({"INTERNAL"})

    tool: bpy.props.StringProperty(name="Tool", description="What the key runs in Blender")
    kind: bpy.props.EnumProperty(name="Changes", items=KINDS)

    @classmethod
    def poll(cls, context):
        return host.others_hold_leases()

    def invoke(self, context, event):
        try:
            objects, whole = _affected(context, self.kind)
            found = host.blocked(objects, whole=whole)
        except Exception:  # fail closed: someone else holds a lease
            log.exception("could not check %s", self.tool)
            found = (None, "Someone else is editing; try again in a moment")
        if found is None:
            return {"PASS_THROUGH"}  # Blender's own keymap item runs
        _refuse(self, found[1], self.tool)
        return {"CANCELLED"}

    def execute(self, context):
        return {"PASS_THROUGH"}


def _region_under(window, x, y):
    """(area, region) under window coordinates x, y; overlapping regions before WINDOW."""
    for area in window.screen.areas:
        if not (area.x <= x < area.x + area.width and area.y <= y < area.y + area.height):
            continue
        found = None
        for region in area.regions:
            if region.width > 1 and region.height > 1 and (
                    region.x <= x < region.x + region.width
                    and region.y <= y < region.y + region.height):
                if region.type != "WINDOW":
                    return area, region
                found = region
        return area, found
    return None, None


def _shown_objects(context, space):
    """The object(s) a Properties editor shows: its pinned object or data, else the active one."""
    pin = space.pin_id if space.use_pin_id else None
    if isinstance(pin, bpy.types.Object):
        return [pin]
    if pin is not None:
        return [o for o in context.view_layer.objects if o.data == pin]
    return [context.view_layer.objects.active]


def _on_tabs(region, x):
    width = TAB_STRIP * bpy.context.preferences.system.ui_scale
    if region.alignment == "LEFT":
        return x < region.x + width
    return x >= region.x + region.width - width


def _pivot(context, objects):
    pivot = context.scene.tool_settings.transform_pivot_point
    if pivot == "CURSOR":
        return context.scene.cursor.location
    active = context.view_layer.objects.active
    if pivot == "ACTIVE_ELEMENT" and active is not None and active.select_get():
        return active.matrix_world.translation
    points = [o.matrix_world.translation for o in objects]
    if pivot == "BOUNDING_BOX_CENTER":
        return Vector([(min(p[i] for p in points) + max(p[i] for p in points)) / 2
                       for i in range(3)])
    return sum(points, Vector()) / len(points)


def _on_gizmo(context, area, region, x, y):
    """Is the press on the transform gizmo (roughly: within its size of its center)?"""
    space = area.spaces.active
    if not space.show_gizmo:
        return False
    tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    shown = (space.show_gizmo_tool and tool is not None and tool.idname in TRANSFORM_TOOLS) or (
        space.show_gizmo_object_translate or space.show_gizmo_object_rotate
        or space.show_gizmo_object_scale)
    objects = list(context.selected_objects)
    if not shown or not objects or region.data is None:
        return False
    center = view3d_utils.location_3d_to_region_2d(region, region.data, _pivot(context, objects))
    if center is None:
        return False
    radius = bpy.context.preferences.view.gizmo_size * bpy.context.preferences.system.ui_scale
    return (x - region.x - center.x) ** 2 + (y - region.y - center.y) ** 2 <= radius * radius


def _pointer_edit(context, event):
    """(objects, what) an edit this event would start would change, or None if it starts none."""
    if event.value not in STARTS:
        return None
    pointer = event.type in ("LEFTMOUSE", "RIGHTMOUSE")
    wheel = event.type in ("WHEELUPMOUSE", "WHEELDOWNMOUSE") and (event.ctrl or event.alt)
    key = event.type in UI_HOTKEYS and event.value == "PRESS"
    if not (pointer or wheel or key):
        return None
    x, y = event.mouse_x, event.mouse_y
    area, region = _region_under(context.window, x, y)
    if region is None:
        return None
    if area.type == "PROPERTIES" and region.type == "WINDOW":
        tab = area.spaces.active.context
        if tab in OBJECT_TABS:
            return _shown_objects(context, area.spaces.active), f"the {tab.lower()} properties"
        if tab in DOCUMENT_TABS:
            return [], f"the {tab.lower()} properties"
        return None
    if area.type == "VIEW_3D" and region.type == "UI":
        if region.active_panel_category != "Item" or _on_tabs(region, x):
            return None
        return [*context.selected_objects, context.view_layer.objects.active], "the sidebar"
    if (area.type == "VIEW_3D" and region.type == "WINDOW" and event.type == "LEFTMOUSE"
            and _on_gizmo(context, area, region, x, y)):
        return list(context.selected_objects), "the transform gizmo"
    return None


class SPATIAL_MODELING_OT_input_gate(bpy.types.Operator):
    """Holds back clicks that would edit what someone else is editing"""

    bl_idname = "spatial_modeling.input_gate"
    bl_label = "Wait While Others Edit"
    bl_options = frozenset({"INTERNAL"})

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not host.others_hold_leases():
            return {"CANCELLED", "PASS_THROUGH"}
        running = context.window.modal_operators
        if running and running[0].bl_idname != "SPATIAL_MODELING_OT_input_gate":
            return {"PASS_THROUGH"}  # a drag started after this gate gets its own events
        try:
            edit = _pointer_edit(context, event)
            found = edit and host.blocked(edit[0])
        except Exception:  # fail open: this sees every event; a bypass is still caught after
            log.exception("the input gate failed on %s %s", event.type, event.value)
            return {"PASS_THROUGH"}
        if not found:
            return {"PASS_THROUGH"}
        _refuse(self, found[1], f"{event.type} {event.value} in {edit[1]}")
        return {"RUNNING_MODAL"}  # consumed: nothing behind it sees the event


class SPATIAL_MODELING_OT_notify(bpy.types.Operator):
    """Show a warning in Blender's status bar"""

    bl_idname = "spatial_modeling.notify"
    bl_label = "Spatial Modeling Warning"
    bl_options = frozenset({"INTERNAL"})

    message: bpy.props.StringProperty()

    def execute(self, context):
        self.report({"WARNING"}, self.message)
        return {"FINISHED"}


def _windows():
    wm = bpy.context.window_manager
    return list(wm.windows) if wm is not None else []


def _ensure_input_gates():
    for window in _windows():
        if not any(op.bl_idname == "SPATIAL_MODELING_OT_input_gate"
                   for op in window.modal_operators):
            with bpy.context.temp_override(window=window, screen=window.screen):
                bpy.ops.spatial_modeling.input_gate("INVOKE_DEFAULT")


def _view3d(window):
    for area in window.screen.areas:
        if area.type == "VIEW_3D":
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            return {"window": window, "screen": window.screen, "area": area, "region": region}
    return {"window": window, "screen": window.screen}


def _watch_modes():
    """Leave Edit Mode (or another) entered on a blocked object since the last poll.

    Only an entry seen happening counts: someone already in Edit Mode when a lease
    begins stays there (leaving would write their unfinished edit), and a change
    they make shows up as a bypass when they leave.
    """
    global _active_mode
    active = bpy.context.view_layer.objects.active
    now = (active.session_uid, active.mode) if active is not None else (None, "OBJECT")
    entered = now[1] != "OBJECT" and _active_mode[1] == "OBJECT"
    _active_mode = now
    if not entered or not host.others_hold_leases():
        return
    in_mode = [o for o in bpy.context.view_layer.objects if o.mode != "OBJECT"]
    found = host.blocked(in_mode)
    windows = _windows()
    if found is None or not windows:
        return
    with bpy.context.temp_override(**_view3d(windows[0])):
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.ed.undo_push(message="Back to Object Mode")  # as leaving it with Tab would
    _active_mode = (active.session_uid, active.mode)
    refusals.append(("object.mode_set", found[1]))
    log.info("left %s on %s: %s", now[1], active.name, found[1])
    _notify(f"{found[1]}: back to Object Mode")


def _note_operator():
    global _last_op
    ops = bpy.context.window_manager.operators
    if not len(ops):
        return
    last = ops[-1]
    if last.as_pointer() != _last_op[0]:
        _last_op = (last.as_pointer(), last.bl_idname, time.monotonic())


def _recent_operator():
    """The operator Blender recorded just before, if any (a clue, not proof: scripts and
    many tools record none), as bpy.ops names it."""
    _, name, seen = _last_op
    if not name or time.monotonic() - seen > OPERATOR_RECENT:
        return None
    prefix, _, rest = name.partition("_OT_")
    return f"{prefix.lower()}.{rest}" if rest else name


def _observed(changed, removed, everything):
    """sync.on_change: a flush found changes. Outside a command, are they leased data?"""
    sess = host._session
    if sess is None or sess.committing:
        return  # a command's own write, checked by leases.py before it was applied
    lease = host.blocked_ids([*changed, *removed], whole=everything)
    if lease is not None:
        _pending.append({"session": sess, "ids": [*changed, *removed], "removed": dict(removed),
                         "lease": lease, "history": False})


@persistent
def _on_history(*_args):
    sess = host._session
    if sess is None or sess.committing:
        return  # history.undo / history.redo commands, checked by leases.py
    lease = host.blocked_ids(whole=True)
    if lease is not None:
        _pending.append({"session": sess, "ids": [], "removed": {}, "lease": lease,
                         "history": True})


def _report_bypasses():
    found = [f for f in _pending if f["session"] is host._session]  # not a stopped server's
    _pending.clear()
    if not found:
        return
    lease = found[0]["lease"]
    owner = lease["owner"]["name"]
    ids = list(dict.fromkeys(i for f in found for i in f["ids"]))
    history = any(f["history"] for f in found)
    removed = {k: v for f in found for k, v in f["removed"].items()}
    names = [removed[i] + " (deleted)" if i in removed else getattr(
        scene_sync.find_object(i), "name", None) for i in ids]
    names = [n for n in names if n]
    what = "Undo/Redo" if history else ", ".join(names[:3]) + (" and more" * (len(names) > 3))
    operator = _recent_operator()
    bypasses.append({"at": time.time(), "objects": ids, "owner": owner,
                     "lease_id": lease["lease_id"], "history": history, "operator": operator})
    clue = f" Blender's last recorded operator: {operator}." if operator else ""
    text = (f"STRICT LOCK BYPASSED: {what or 'leased data'} changed in host Blender while "
            f"{owner} holds a {lease['mode']} lease, by a route the gate doesn't cover (a "
            f"script, an add-on, a menu or a tool).{clue} Strict locking did not pass for this "
            "route. Edits stop until every client has the re-read scene.")
    print("Spatial Modeling:", text)
    log.warning(text)
    host.stop_writes(f"{what} changed outside the gate while {owner} is editing")
    _notify(f"Not locked: {what} changed while {owner} is editing. Everyone got the new scene; "
            f"check it with {owner}")


def _notify(text):
    windows = _windows()
    if not windows:
        return
    with bpy.context.temp_override(window=windows[0], screen=windows[0].screen):
        bpy.ops.spatial_modeling.notify(message=text)


def poll():
    """host.py's drain timer: gate pointers, watch modes, report bypasses (before commands)."""
    _note_operator()
    if _pending:
        try:
            _report_bypasses()
        except Exception:
            log.exception("could not report a bypass; stopping edits anyway")
            host.stop_writes("a change outside the gate")
    try:
        _watch_modes()  # also without leases: it must see the moment Edit Mode is entered
        if host.others_hold_leases():
            _ensure_input_gates()
    except Exception:
        log.exception("the gate's poll failed")


CLASSES = (SPATIAL_MODELING_OT_gate, SPATIAL_MODELING_OT_input_gate, SPATIAL_MODELING_OT_notify)
_HANDLERS = ((bpy.app.handlers.undo_post, _on_history), (bpy.app.handlers.redo_post, _on_history))


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    kc = bpy.context.window_manager.keyconfigs.addon  # None in background mode: no keys anyway
    if kc is not None:
        for key in SHORTCUTS:
            name, space_type, region_type = key["keymap"]
            km = kc.keymaps.new(name, space_type=space_type, region_type=region_type)
            kmi = km.keymap_items.new(SPATIAL_MODELING_OT_gate.bl_idname, key["type"],
                                      key["value"], **key["mods"])
            kmi.properties.tool = (f"{key['tool']}({key['menu']})" if key["menu"]
                                   else key["tool"])
            kmi.properties.kind = key["kind"]
            _keymaps.append((km, kmi))
    scene_sync.on_change = _observed
    for handlers, fn in _HANDLERS:
        if fn not in handlers:
            handlers.append(fn)


def unregister():
    for handlers, fn in _HANDLERS:
        if fn in handlers:
            handlers.remove(fn)
    if scene_sync.on_change is _observed:
        scene_sync.on_change = None
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    _pending.clear()
    for cls in reversed(CLASSES):  # ends any InputGate still running
        bpy.utils.unregister_class(cls)

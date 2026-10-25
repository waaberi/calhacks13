"""Pure, bounded membership checks for explicitly enabled Blender native UI.

An executable name or a window title alone never admits a target. Non-GHOST
targets must have an actual owner chain ending at a Blender GHOST window.
Process creation stamps and capture-session pins belong to the input bridge.
"""

import ntpath

MAX_OWNER_DEPTH = 16
GHOST_CLASS = "GHOST_WindowClass"


def _positive_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def resolve_window(hwnd, raw_window, *, blender_pid=None, max_depth=MAX_OWNER_DEPTH):
    """Return a public family identity, or None for an unproven owner chain.

    ``raw_window(handle)`` supplies hwnd, pid, title, window_class, owner_hwnd
    and an optional executable path. A brokered dialog's process need not be
    Blender, but its terminal GHOST owner must be an actual blender.exe process.
    The returned identity deliberately omits executable paths.
    """
    if not _positive_integer(hwnd) or not _positive_integer(max_depth):
        return None
    if blender_pid is not None and not _positive_integer(blender_pid):
        return None
    seen, ghost_pids, target = set(), set(), None
    current = hwnd
    for _ in range(min(max_depth, MAX_OWNER_DEPTH)):
        if current in seen:
            return None
        seen.add(current)
        record = raw_window(current)
        if not isinstance(record, dict) or record.get("hwnd") != current:
            return None
        if not _positive_integer(record.get("pid")):
            return None
        window_class, owner = record.get("window_class"), record.get("owner_hwnd")
        if not isinstance(window_class, str) or not window_class:
            return None
        if not isinstance(owner, int) or isinstance(owner, bool) or owner < 0:
            return None
        parent, menu_owner = record.get("parent_hwnd", 0), record.get("menu_owner_hwnd", 0)
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
               for value in (parent, menu_owner)):
            return None
        if window_class == "#32768" and owner and menu_owner and owner != menu_owner:
            return None
        if target is None:
            target = dict(record)
        next_owner = owner or (menu_owner if window_class == "#32768" else 0) or parent
        if window_class == GHOST_CLASS:
            executable = record.get("executable")
            if not isinstance(executable, str) or ntpath.basename(executable).lower() != "blender.exe":
                return None
            if blender_pid is not None and record["pid"] != blender_pid:
                return None
            ghost_pids.add(record["pid"])
            if len(ghost_pids) != 1:
                return None
            if not next_owner:
                return {
                    "hwnd": target["hwnd"], "pid": target["pid"], "title": target.get("title", ""),
                    "window_class": target["window_class"], "owner_hwnd": target["owner_hwnd"],
                    "parent_hwnd": target.get("parent_hwnd", 0),
                    "menu_owner_hwnd": target.get("menu_owner_hwnd", 0),
                    "blender_hwnd": record["hwnd"], "blender_pid": record["pid"],
                    "kind": "blender" if target["window_class"] == GHOST_CLASS else
                            "popup" if target["window_class"] in ("#32768", "ComboLBox") else "dialog",
                }
        if not next_owner:
            return None
        current = next_owner
    return None

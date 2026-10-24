"""Installed default-keymap matching and real private-background viewport operations.

No injected keys, GUI, host listener, capture, Player or headset are involved.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import traceback
from pathlib import Path

import bpy
from mathutils import Vector

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]


def catalog_entries(path):
    source = path.read_text(encoding="utf-8")
    pattern = (r'new PreviewShortcut\("([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)"'
               r'([^\r\n]*?)\),?\s*$')
    entries = []
    for match in re.finditer(pattern, source, re.MULTILINE):
        ident, label, group, key, extra = match.groups()
        mods = re.findall(r'"(CTRL|SHIFT|ALT)"', extra)
        native_key = {"DECIMAL": "NUMPAD_PERIOD", "DIVIDE": "NUMPAD_SLASH", "ENTER": "RET"}.get(key, key)
        if re.fullmatch(r"NUMPAD[0-9]", native_key):
            native_key = "NUMPAD_" + native_key[-1]
        entries.append({"id": ident, "label": label, "group": group, "key": key,
                        "native_key": native_key, "modifiers": mods})
    assert len(entries) == 31 and len({entry["id"] for entry in entries}) == 31, entries
    return entries


def main(args, report):
    assert bpy.app.background, "Headless gate only"
    profile = args.private_profile.resolve()
    assert profile.is_relative_to(args.output.resolve())
    for name, value in os.environ.items():
        if name.upper().startswith("BLENDER_USER_") or name.upper() in ("TEMP", "TMP", "TMPDIR"):
            assert value and Path(value).resolve().is_relative_to(profile), name
    tempfile.tempdir = str(profile / "temp")
    assert Path(bpy.app.tempdir).resolve().is_relative_to(profile)
    assert Path(tempfile.gettempdir()).resolve().is_relative_to(profile)
    report["isolation"] = {"profile": str(profile), "blender_temp_directory": bpy.app.tempdir,
                           "tempfile_directory": tempfile.gettempdir(), "dont_write_bytecode": sys.dont_write_bytecode,
                           "cad_enabled": False}
    report["identity"] = {"blender": bpy.app.version_string, "process_id": os.getpid()}

    def check(name, okay, details=None, method="native viewport operator", optional=False):
        entry = {"name": name, "method": method, "passed": bool(okay)}
        if details is not None:
            entry["details"] = details
        report["optional_checks" if optional else "checks"].append(entry)
        if optional and not okay:
            report["pending"].append({"name": name, "reason": "Synchronous background panel state did not match expected state",
                                      "details": details})
        return bool(okay)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scripts = Path(bpy.utils.system_resource("SCRIPTS"))
    preset = scripts / "presets/keyconfig/Blender.py"
    data = preset.parent / "keymap_data/blender_default.py"
    panel_operators = scripts / "startup/bl_operators/wm.py"
    catalog = ROOT / "app/Assets/SpatialModeling/Scripts/PreviewShortcutCatalog.cs"
    report["sources"] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (preset, data, panel_operators, catalog)}
    entries = catalog_entries(catalog)
    assert bpy.utils.keyconfig_set(str(preset)), "Installed default preset could not be activated"
    kc = bpy.context.window_manager.keyconfigs.active
    report["keyconfig"] = {"name": kc.name, "keymaps": len(kc.keymaps),
                           "select_mouse": kc.preferences.select_mouse,
                           "spacebar_action": kc.preferences.spacebar_action,
                           "tool_key_mode": kc.preferences.tool_key_mode,
                           "use_region_toggle_pie": kc.preferences.use_region_toggle_pie,
                           "use_v3d_tab_menu": kc.preferences.use_v3d_tab_menu,
                           "use_v3d_shade_ex_pie": kc.preferences.use_v3d_shade_ex_pie}
    # Expected intent is independently specified, while keys/modifiers come from
    # the actual C# source. Matching requires context, operator AND properties.
    expected = {
        "select.all": [("Object Mode", "object.select_all", {"action": "SELECT"}),
                       ("Mesh", "mesh.select_all", {"action": "SELECT"})],
        "select.none": [("Object Mode", "object.select_all", {"action": "DESELECT"}),
                        ("Mesh", "mesh.select_all", {"action": "DESELECT"})],
        "select.invert": [("Object Mode", "object.select_all", {"action": "INVERT"}),
                          ("Mesh", "mesh.select_all", {"action": "INVERT"})],
        "object.duplicate": [("Object Mode", "object.duplicate_move", {})],
        "mode.edit": [("Object Non-modal", "object.mode_set", {"mode": "EDIT", "toggle": True})],
        "transform.move": [("Object Mode", "transform.translate", {}), ("Mesh", "transform.translate", {})],
        "transform.rotate": [("Object Mode", "transform.rotate", {}), ("Mesh", "transform.rotate", {})],
        "transform.scale": [("Object Mode", "transform.resize", {}), ("Mesh", "transform.resize", {})],
        "mesh.extrude": [("Mesh", "view3d.edit_mesh_extrude_move_normal", {})],
        "mesh.inset": [("Mesh", "mesh.inset", {})],
        "mesh.bevel": [("Mesh", "mesh.bevel", {"affect": "EDGES"})],
        "mesh.loop_cut": [("Mesh", "mesh.loopcut_slide", {})],
        "mesh.merge": [("Mesh", "wm.call_menu", {"name": "VIEW3D_MT_edit_mesh_merge"})],
        "object.hide": [("Object Mode", "object.hide_view_set", {"unselected": False})],
        "object.unhide": [("Object Mode", "object.hide_view_clear", {})],
        "view.frame": [("3D View", "view3d.view_selected", {})],
        "view.all": [("3D View", "view3d.view_all", {"center": False})],
        "view.front": [("3D View", "view3d.view_axis", {"type": "FRONT"})],
        "view.right": [("3D View", "view3d.view_axis", {"type": "RIGHT"})],
        "view.top": [("3D View", "view3d.view_axis", {"type": "TOP"})],
        "view.back": [("3D View", "view3d.view_axis", {"type": "BACK"})],
        "view.left": [("3D View", "view3d.view_axis", {"type": "LEFT"})],
        "view.bottom": [("3D View", "view3d.view_axis", {"type": "BOTTOM"})],
        "view.perspective": [("3D View", "view3d.view_persportho", {})],
        "view.camera": [("3D View", "view3d.view_camera", {})],
        "view.local": [("3D View", "view3d.localview", {})],
        "view.shading": [("3D View", "wm.call_menu_pie", {"name": "VIEW3D_MT_shading_pie"})],
        "panel.tools": [("3D View Generic", "wm.context_toggle", {"data_path": "space_data.show_region_toolbar"})],
        "panel.sidebar": [("3D View Generic", "wm.context_toggle", {"data_path": "space_data.show_region_ui"})],
        # These are contextual modal-map matches, not universal editor commands.
        "cancel": [("Transform Modal Map", "CANCEL", {})],
        "confirm": [("Transform Modal Map", "CONFIRM", {})],
    }
    assert set(expected) == {entry["id"] for entry in entries}
    modal_map = kc.keymaps.get("Transform Modal Map")
    report["modal_keymap_items"] = [{"operator": item.propvalue, "key": item.type, "value": item.value,
                                     "any": item.any, "ctrl": item.ctrl, "shift": item.shift,
                                     "alt": item.alt, "oskey": item.oskey}
                                    for item in modal_map.keymap_items if item.type in ("ESC", "RET")] if modal_map else []
    for entry in entries:
        matches = []
        missing = []
        for km_name, operator, properties in expected[entry["id"]]:
            km = kc.keymaps.get(km_name)
            found = []
            if km:
                for item in km.keymap_items:
                    op = item.propvalue if km.is_modal else item.idname
                    modifiers_match = item.any or all(bool(getattr(item, mod.lower())) == (mod in entry["modifiers"])
                                                       for mod in ("CTRL", "SHIFT", "ALT"))
                    if (item.active and op == operator and item.type == entry["native_key"]
                            and item.value == "PRESS" and modifiers_match and (item.any or not item.oskey)
                            and all(getattr(item.properties, key, None) == value for key, value in properties.items())):
                        found.append({"map": km_name, "operator": op, "properties": properties,
                                      "key": item.type, "any_modifier": item.any})
            matches.extend(found)
            if not found:
                missing.append({"map": km_name, "operator": operator, "properties": properties})
        result = {**entry, "matches": matches, "missing": missing, "matched": not missing}
        report["shortcuts"].append(result)
    check("All 31 catalog chords match installed active default keyconfig contexts and intents",
          all(entry["matched"] for entry in report["shortcuts"]),
          [entry for entry in report["shortcuts"] if not entry["matched"]], "installed default keyconfig matching")

    window = bpy.context.window or bpy.context.window_manager.windows[0]
    area = next((area for area in window.screen.areas if area.type == "VIEW_3D"), None)
    region = next((region for region in area.regions if region.type == "WINDOW"), None) if area else None
    if not area or not region or not area.spaces.active.region_3d:
        report["pending"].append("Background factory screen has no VIEW_3D/WINDOW/RegionView3D; navigation operators unverified")
        return
    report["native_operator_context"] = {"previous_area": bpy.context.area.type if bpy.context.area else None,
                                          "override_editor": "VIEW_3D", "region": "WINDOW"}
    bpy.context.preferences.view.smooth_view = 0
    space = area.spaces.active
    view = space.region_3d
    report["viewport_states"] = []

    def snapshot(name):
        state = {"name": name, "view_location": list(view.view_location), "view_distance": view.view_distance,
                 "view_rotation": list(view.view_rotation), "view_perspective": view.view_perspective,
                 "view_back_axis": list(view.view_rotation @ Vector((0, 0, 1))),
                 "local_view": space.local_view is not None, "toolbar": space.show_region_toolbar,
                 "sidebar": space.show_region_ui}
        report["viewport_states"].append(state)
        return state

    def invoke(name, operator, expected_result=frozenset({"FINISHED"}), optional=False, **kwargs):
        if not operator.poll():
            report["pending"].append(f"{name}: native operator poll rejected the private background VIEW_3D/WINDOW context")
            return False
        result = operator(**kwargs)
        return check(name + " returned expected native result", result == expected_result, sorted(result), optional=optional)

    def near(actual, expected, tolerance=1e-5):
        return all(math.isclose(a, b, abs_tol=tolerance) for a, b in zip(actual, expected, strict=True))

    with bpy.context.temp_override(window=window, area=area, region=region):
        axes = {"FRONT": (0, -1, 0), "BACK": (0, 1, 0), "RIGHT": (1, 0, 0),
                "LEFT": (-1, 0, 0), "TOP": (0, 0, 1), "BOTTOM": (0, 0, -1)}
        for axis, expected_back in axes.items():
            if invoke("View " + axis, bpy.ops.view3d.view_axis, type=axis, align_active=False):
                state = snapshot(axis)
                check("View " + axis + " has independent expected world-facing axis",
                      near(state["view_back_axis"], expected_back), {"actual": state["view_back_axis"], "expected": expected_back})
        view.view_perspective = "ORTHO"
        if invoke("Toggle perspective", bpy.ops.view3d.view_persportho):
            check("Ortho toggles to perspective", snapshot("perspective")["view_perspective"] == "PERSP")
        if invoke("Toggle ortho", bpy.ops.view3d.view_persportho):
            check("Perspective toggles to ortho", snapshot("ortho")["view_perspective"] == "ORTHO")
        bpy.ops.mesh.primitive_cube_add(size=2, location=(-2, 0, 0))
        left = bpy.context.object
        bpy.ops.mesh.primitive_cube_add(size=2, location=(4, 0, 0))
        right = bpy.context.object
        view.view_location = (10, 12, 14)
        if invoke("Frame all", bpy.ops.view3d.view_all, center=False):
            state = snapshot("all")
            # Two equal cubes bound X[-3,5], Y/Z[-1,1]; midpoint is (1,0,0).
            check("Frame all centers independent complete scene bounds", near(state["view_location"], (1, 0, 0)), state)
            check("Frame all creates a positive finite view distance", math.isfinite(view.view_distance) and view.view_distance > 0)
        bpy.ops.object.select_all(action="DESELECT")
        right.select_set(True)
        bpy.context.view_layer.objects.active = right
        if invoke("Frame selected", bpy.ops.view3d.view_selected):
            check("Frame selected centers only selected right cube", near(snapshot("selected")["view_location"], (4, 0, 0)))
        if invoke("Enter local view", bpy.ops.view3d.localview, frame_selected=False):
            check("Local view contains selected right cube and excludes left cube",
                  space.local_view is not None and right.local_view_get(space) and not left.local_view_get(space), snapshot("local"))
            if invoke("Leave local view", bpy.ops.view3d.localview, frame_selected=False):
                check("Local view returns to complete scene", space.local_view is None, snapshot("global"))
        # Overlapping panels animate by default. Blender temporarily keeps a
        # hiding region visible until its event-loop timer finishes; background
        # mode does not run that displayed UI loop. Use Blender's supported
        # accessibility preference ONLY inside this private test process so the
        # very same native T/N operators complete synchronously. Never save it
        # or change the product/helper/user's interactive Blender preferences.
        # Blender 5.2.2 rna_space.cc chooses the synchronous update when
        # USER_REDUCE_MOTION is set; installed wm.py returns CANCELLED for
        # non-Undo Screen properties even after a successful native change.
        prefs = bpy.context.preferences.view
        panels = (("Toolbar", "show_region_toolbar"), ("Sidebar", "show_region_ui"))
        original_motion = prefs.use_reduce_motion
        original_panels = {name: getattr(space, name) for _, name in panels}
        report["panel_fixture"] = {"original_reduce_motion": original_motion,
                                   "private_reduce_motion": True, "original_panels": original_panels,
                                   "transitions": [], "preference_saved": False}
        try:
            prefs.use_reduce_motion = True
            check("Private headless fixture disables only panel animation", prefs.use_reduce_motion)
            check("Panel operators use the actual selected native editor space",
                  bpy.context.space_data.as_pointer() == space.as_pointer())
            for label, property_name in panels:
                other = next(name for _, name in panels if name != property_name)
                for initial in (False, True):
                    setattr(space, property_name, initial)
                    check(f"{label} starts {'shown' if initial else 'hidden'}",
                          getattr(space, property_name) is initial)
                    for expected in (not initial, initial):
                        other_before = getattr(space, other)
                        if invoke(f"{label} toggle from {not expected}", bpy.ops.wm.context_toggle,
                                  expected_result={"CANCELLED"}, data_path="space_data." + property_name):
                            actual = getattr(space, property_name)
                            report["panel_fixture"]["transitions"].append(
                                {"panel": label, "before": not expected, "expected": expected, "actual": actual})
                            check(f"{label} native keymap route reaches {expected}", actual is expected,
                                  {"expected": expected, "actual": actual})
                            check(f"{label} leaves the other panel unchanged", getattr(space, other) is other_before)
            check("Both panel routes completed every shown/hidden round trip",
                  len(report["panel_fixture"]["transitions"]) == 8)
        finally:
            # Restore panel state while synchronous updates are still enabled,
            # then restore the preference even if a native assertion failed.
            try:
                for property_name, value in original_panels.items():
                    setattr(space, property_name, value)
                    check(property_name + " restored after private panel test", getattr(space, property_name) is value)
            finally:
                prefs.use_reduce_motion = original_motion
                report["panel_fixture"]["restored_reduce_motion"] = prefs.use_reduce_motion
                check("Original reduce-motion preference restored", prefs.use_reduce_motion is original_motion)
        snapshot("final")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-profile", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    report = {"method": "installed default keyconfig matching + actual native viewport operators; no key injection",
              "checks": [], "optional_checks": [], "shortcuts": [], "pending": [],
              "required_passed": False, "passed": False, "outcome": "failed"}
    try:
        main(args, report)
        report["required_passed"] = all(check["passed"] for check in report["checks"])
        report["outcome"] = "failed" if not report["required_passed"] else "pending" if report["pending"] else "passed"
        report["passed"] = report["outcome"] == "passed"
    except Exception:
        report["error"] = traceback.format_exc()
        raise
    finally:
        (args.output / "navigation-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

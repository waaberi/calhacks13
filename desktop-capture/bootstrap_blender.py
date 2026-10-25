"""Launch-only bootstrap for an isolated Blender Host; never saves a source file."""

import argparse
import os
import sys
from pathlib import Path

import bpy

parser = argparse.ArgumentParser()
parser.add_argument("--addon", type=Path, required=True)
parser.add_argument("--blend", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
if not os.environ.get("BLENDER_USER_RESOURCES"):
    raise RuntimeError("Launcher must provide isolated Blender resources")
bpy.ops.wm.open_mainfile(filepath=str(args.blend.resolve()))
bpy.ops.extensions.package_install_files(
    filepath=str(args.addon.resolve()), repo="user_default", enable_on_install=False
)
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.spatial_modeling")
prefs = bpy.context.preferences.addons["bl_ext.user_default.spatial_modeling"].preferences
if prefs.lan_enabled:
    raise RuntimeError("P1 launcher requires LAN disabled")
print("P1_LAUNCHER_HOST_READY localhost only; source file not saved", flush=True)

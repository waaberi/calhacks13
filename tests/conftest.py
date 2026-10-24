"""Lets tests import the add-on's pure-Python modules (those without bpy) outside Blender."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_addon" / "spatial_modeling"))

"""Run only inside an owned background factory Blender; never saves preferences."""
import importlib.util
import json
import sys
from pathlib import Path

import bpy

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("glass_theme", root / "desktop-capture/glass_blender_theme.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert "--background" in sys.argv and "--factory-startup" in sys.argv
before = (bpy.data.filepath, bpy.data.is_dirty, len(bpy.data.objects))
result = module.apply_private_theme(bpy)
after = (bpy.data.filepath, bpy.data.is_dirty, len(bpy.data.objects))
assert before == after, "Theme must not alter the native document"
assert not bpy.context.preferences.use_preferences_save
assert len(result["applied"]) >= 50, "Expected actual supported native widget colors"
result.update(passed=True, version=bpy.app.version_string, document_unchanged=True,
              roundness_properties=[name for name in result["applied"] if name.endswith(".roundness")])
path = Path(sys.argv[sys.argv.index("--") + 1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(result, indent=2), encoding="utf-8")
print("PRIVATE_GLASS_THEME PASS", len(result["applied"]), "supported properties; no document/preference save")

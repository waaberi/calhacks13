"""Fail on new app-owned UI creation that bypasses the shared rounded theme.

Native Blender, model/room geometry and third-party packages are not app UI.
Run from any directory. This audit complements actual Unity render/hit tests.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "app/Assets/SpatialModeling/Scripts"
violations = []
for path in sorted(SCRIPTS.glob("*.cs")):
    source = path.read_text(encoding="utf-8-sig")
    for line, content in enumerate(source.splitlines(), 1):
        if re.search(r"(?:AddComponent<Image>\s*\(|typeof\(Image\))", content):
            violations.append(f"{path.relative_to(ROOT)}:{line}: use RoundedGlassImage / GlassTheme")
        if "GUI.Button(" in content and path.name != "GlassDesktopStatus.cs":
            violations.append(f"{path.relative_to(ROOT)}:{line}: unthemed desktop button")
    # Text constructors must be connected to the type API in the same factory file.
    if re.search(r"typeof\(Text\)|AddComponent<Text>", source) and "GlassTheme" not in source:
        violations.append(f"{path.relative_to(ROOT)}: text factory bypasses semantic type")
if violations:
    print("\n".join(violations))
    sys.exit(1)
print("GLASS_UI_AUDIT PASS app-owned Image/Text/IMGUI factories use shared theme")

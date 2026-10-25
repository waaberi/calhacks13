"""Run the existing real GUI gate check on isolated ports and user resources.

Only the test process's module defaults change. The implementation files and
the active host on 8765 are untouched. Run with --enable-event-simulate.
"""

import hashlib
import importlib
import json
import os
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
LOCAL_PORT = int(os.environ.get("P3B_LOCAL_PORT", "29765"))
LAN_PORT = int(os.environ.get("P3B_LAN_PORT", "29767"))

# Defaults in the pre-existing harness are bound at definition time. Compile a
# private process-local copy with its source filename preserved for tracebacks.
source_path = HERE / "blender_check.py"
source = source_path.read_text("utf-8")
assert source.count("PORT = 8765\n") == 1
assert source.count("LAN_PORT = lan.PORT\n") == 1
source = source.replace("PORT = 8765\n", f"PORT = {LOCAL_PORT}\n")
source = source.replace("LAN_PORT = lan.PORT\n", f"LAN_PORT = {LAN_PORT}\n")
bc = types.ModuleType("blender_check")
bc.__file__ = str(source_path)
sys.modules[bc.__name__] = bc
exec(compile(source, str(source_path), "exec"), bc.__dict__)  # noqa: S102 - trusted local harness

original_install = bc.install


def isolated_install():
    manifest = {str(p.relative_to(bc.ADDON_DIR)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in bc.ADDON_DIR.rglob("*.py") if "__pycache__" not in p.parts}
    manifest_path = os.environ.get("P3B_SOURCE_MANIFEST")
    if manifest_path:
        Path(manifest_path).write_text(json.dumps(manifest, indent=2), "utf-8")
    original_install()
    package = importlib.import_module(bc.MODULE)
    server = package.host.server
    server.PORT = LOCAL_PORT
    defaults = list(server.Server.__init__.__defaults__)
    assert defaults[1] == 8765, defaults
    defaults[1] = LOCAL_PORT
    server.Server.__init__.__defaults__ = tuple(defaults)
    package.lan.PORT = LAN_PORT
    bc.log(f"P3B isolated test ports: {LOCAL_PORT}/{LAN_PORT}; "
           f"resources={os.environ['BLENDER_USER_RESOURCES']}")


bc.install = isolated_install
import gate_check

original_finish = bc.finish


def recording_finish(code):
    out = os.environ.get("SPATIAL_MODELING_GATE_ROUTES")
    if out:
        Path(out).write_text(json.dumps(gate_check.ROUTES, indent=2), "utf-8")
    original_finish(code)


bc.finish = recording_finish

if __name__ == "__main__":
    bc.main(gate_check.gate_checks)

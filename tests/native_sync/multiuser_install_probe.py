"""Isolated install/native translation proof for the unmodified official Multiuser ZIP."""
import json
import sys
import traceback
from collections import Counter
from pathlib import Path

import addon_utils
import bpy

folder = Path(sys.argv[sys.argv.index("--") + 1])
config = json.loads((folder / "config.json").read_text())
report = {"passed": False, "blender": bpy.app.version_string, "checks": []}
try:
    assert bpy.ops.extensions.package_install_files(filepath=config["zip"], repo="user_default",
                                                   enable_on_install=False) == {"FINISHED"}
    name = "bl_ext.user_default.multi_user"
    addon = addon_utils.enable(name, default_set=True)
    assert addon is not None
    report["checks"].append("official Multiuser0.8.2 installs and enables in Blender5.2.2")
    protocol = addon.bl_types.get_data_translation_protocol()
    report["data_types"] = list(protocol.implementations)
    sys.path.insert(0, str(Path(__file__).parent))
    from native_fixture import build_fixture
    report["fixture"] = build_fixture()
    for image in bpy.data.images:
        if image.get("native_sync_fixture") and not image.filepath:
            image.filepath_raw = str(folder / (image.name + ".png"))
    from replication import porcelain
    from replication.repository import Repository
    repository = Repository(rdp=protocol, username="isolated-probe")
    for scene in bpy.data.scenes:
        scene_id = porcelain.add(repository, scene)
        porcelain.commit(repository, scene_id)
    report["node_count"] = len(repository.graph)
    types = Counter()
    examples = {}

    def inspect(value, path):
        kind = type(value).__module__ + "." + type(value).__qualname__
        types[kind] += 1
        examples.setdefault(kind, path)
        if isinstance(value, dict):
            for key, child in value.items():
                inspect(key, path + ".<key>")
                inspect(child, path + "." + str(key))
        elif isinstance(value, (list, tuple, set)):
            for index, child in enumerate(value):
                inspect(child, f"{path}[{index}]")

    for node in repository.graph.values():
        inspect(node.data, f"{node.data.get('type_id')}:{node.data.get('name')}")
    report["serialized_value_types"] = dict(types)
    report["serialized_value_type_examples"] = examples
    report["checks"].append("original native fixture serializes into actual upstream replication repository")
    report["passed"] = True
except Exception:  # noqa: BLE001 - isolated Blender probe preserves every import/native failure
    report["error"] = traceback.format_exc()
finally:
    (folder / "RESULT.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps(report, default=str), flush=True)
if not report["passed"]:
    raise SystemExit(1)

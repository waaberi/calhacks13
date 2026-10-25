"""Offline upstream Multiuser native-datablock roundtrip; no network transport claim."""
import argparse
import base64
import json
import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

sys.path.insert(0, str(Path(__file__).parent))
from native_fixture import CUBE, IMAGE, build_fixture, edit_topology_fixture
from native_graph import capture_graph, differences

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
parser.add_argument("--zip", required=True)
parser.add_argument("--edit-topology", action="store_true")
parser.add_argument("--phase", choices=("write", "read"), required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
out = Path(args.output)
report = {"passed": False, "network_sync_tested": False, "phase": args.phase}


def encode(item):
    if isinstance(item, bytes):
        return {"__fixture_bytes__": base64.b64encode(item).decode("ascii")}
    if isinstance(item, tuple):
        return {"__fixture_tuple__": [encode(v) for v in item]}
    if isinstance(item, list):
        return [encode(v) for v in item]
    if isinstance(item, dict):
        if all(isinstance(key, str) for key in item):
            return {key: encode(value) for key, value in item.items()}
        return {"__fixture_dict__": [[encode(key), encode(value)] for key, value in item.items()]}
    if item is None or isinstance(item, (str, bool, int, float)):
        return item
    raise TypeError("Fixture graph needs explicit encoding for " + str(type(item)))


def decode(item):
    if isinstance(item, list):
        return [decode(v) for v in item]
    if isinstance(item, dict):
        if set(item) == {"__fixture_bytes__"}:
            return base64.b64decode(item["__fixture_bytes__"], validate=True)
        if set(item) == {"__fixture_dict__"}:
            return {decode(key): decode(value) for key, value in item["__fixture_dict__"]}
        if set(item) == {"__fixture_tuple__"}:
            return tuple(decode(v) for v in item["__fixture_tuple__"])
        return {key: decode(value) for key, value in item.items()}
    return item


def run():
    try:
        assert bpy.ops.extensions.package_install_files(filepath=args.zip, repo="user_default",
            enable_on_install=False) == {"FINISHED"}
        addon = addon_utils.enable("bl_ext.user_default.multi_user", default_set=True)
        assert addon is not None
        cache = out / (args.phase + "-cache")
        cache.mkdir(exist_ok=True)
        addon.utils.get_preferences().cache_directory = str(cache)
        protocol = addon.bl_types.get_data_translation_protocol()
        from replication import porcelain
        from replication.constants import FETCHED
        from replication.objects import Node
        from replication.repository import Repository
        repository = Repository(rdp=protocol, username="native-offline-fixture")
        if args.phase == "write":
            build_fixture()
            if args.edit_topology:
                edit_topology_fixture()
            # Upstream needs a name to extract packed bytes to its cache. Keep
            # the fixture's packed state before registering the native graph.
            bpy.data.images[IMAGE].filepath_raw = str(cache / "fixture-image.png")
            expected = capture_graph()
            (out / "expected-original.json").write_text(json.dumps(expected, indent=2))
            for scene in bpy.data.scenes:
                root = porcelain.add(repository, scene)
                porcelain.commit(repository, root)
            data = [{"uuid": node.uuid, "data": encode(node.data), "owner": node.owner,
                     "dependencies": node.dependencies} for node in repository.graph.values()]
            (out / "repository.json").write_text(json.dumps(data))
            report["node_count"] = len(data)
            report["node_types"] = [node.data.get("type_id") for node in repository.graph.values()]
            report["source_shape_keys_after_dump"] = list(bpy.data.objects[CUBE].data.shape_keys.key_blocks.keys())
            report["source_packed_image_after_dump"] = bpy.data.images[IMAGE].packed_file is not None
            report["passed"] = True
        else:
            bpy.ops.object.select_all(action="SELECT")
            bpy.ops.object.delete(use_global=False)
            for entry in json.loads((out / "repository.json").read_text()):
                repository.do_commit(Node(uuid=entry["uuid"], data=decode(entry["data"]),
                    dependencies=entry["dependencies"], owner=entry["owner"], state=FETCHED))
            for identity in repository.index_sorted:
                node = repository.graph[identity]
                node.instance = repository.rdp.resolve(node.data) or repository.rdp.construct(node.data)
                try:
                    node.instance.uuid = node.uuid
                except AttributeError:
                    pass
            for identity in repository.heads:
                porcelain.apply(repository, identity)
            for node in repository.graph.values():
                if isinstance(node.instance, bpy.types.Scene):
                    bpy.context.window.scene = node.instance
            bpy.context.view_layer.update()
            report["shape_keys_present"] = bpy.data.objects[CUBE].data.shape_keys is not None
            report["custom_point_attribute_present"] = "NativeSync_Attribute" in bpy.data.objects[CUBE].data.attributes
            report["packed_image_present"] = bpy.data.images[IMAGE].packed_file is not None
            actual = capture_graph()
            (out / "actual-original.json").write_text(json.dumps(actual, indent=2))
            report["mismatches"] = differences(json.loads((out / "expected-original.json").read_text()), actual)
            report["passed"] = not report["mismatches"]
    except Exception:  # noqa: BLE001 - retain actual upstream/native failures before process exit
        report["error"] = traceback.format_exc()
    finally:
        (out / (args.phase + "-result.json")).write_text(json.dumps(report, indent=2))
        bpy.ops.wm.quit_blender()


bpy.app.timers.register(run, first_interval=1)

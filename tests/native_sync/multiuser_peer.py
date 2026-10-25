"""Unmodified Multiuser own-peer native propagation experiment, never production."""
import json
import sys
import time
import traceback
from pathlib import Path

import addon_utils
import bpy

folder = Path(sys.argv[sys.argv.index("--") + 1])
side = sys.argv[-1]
config = json.loads((folder / "config.json").read_text())
sys.path.insert(0, str(Path(__file__).parent))
from native_fixture import CUBE, IMAGE, MATERIAL, build_fixture, select_only
from native_graph import capture_graph, differences

assert bpy.ops.extensions.package_install_files(filepath=config["zip"], repo="user_default",
                                               enable_on_install=False) == {"FINISHED"}
addon = addon_utils.enable("bl_ext.user_default.multi_user", default_set=True)
assert addon is not None
from replication.constants import STATE_ACTIVE, STATE_LOBBY
from replication.interface import session

settings = addon.utils.get_preferences()
settings.username = f"isolated-{side}"
settings.connection_timeout = 20000
settings.depsgraph_update_rate = .05
settings.cache_directory = str(folder / (side + "-cache"))
if side == "host":
    build_fixture()
    bpy.data.images[IMAGE].filepath_raw = str(folder / (IMAGE + ".png"))
    (folder / "host-original-graph.json").write_text(json.dumps(capture_graph(), indent=2))
else:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
preset = settings.server_preset[0]
preset.ip, preset.port = "127.0.0.1", config["port"]
preset.use_server_password, preset.server_password = True, config["server_password"]
preset.use_admin_password, preset.admin_password = side == "host", config["admin_password"]
assert bpy.ops.wm.session_join() == {"FINISHED"}
started = time.monotonic()
initialized = False
active = False
edited = False
selected_at = None
host_selected_at = None
host_edited = False


def capture():
    cube = bpy.data.objects.get(CUBE)
    if cube is None:
        return {"cube": False, "state": session.state}
    mesh = cube.data
    return {"cube": True, "state": session.state, "uuid": cube.uuid,
        "vertices": [[round(float(v), 6) for v in point.co] for point in mesh.vertices],
        "polygons": [list(face.vertices) for face in mesh.polygons],
        "uv0": [round(float(v), 6) for v in mesh.uv_layers["NativeSync_UV"].data[0].uv],
        "bevel_width": round(float(cube.modifiers["NativeSync_Bevel"].width), 6),
        "roughness": round(float(bpy.data.materials[MATERIAL].node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value), 6),
        "shape_keys": [key.name for key in mesh.shape_keys.key_blocks] if mesh.shape_keys else [],
        "packed_image": bpy.data.images[IMAGE].packed_file is not None,
        "custom_scalar": cube.get("native_scalar"),
        "nodes": len(session.repository.graph)}


def mutate(reverse=False):
    cube = bpy.data.objects[CUBE]
    select_only(cube)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    cube.data.vertices[7 if reverse else 0].select = True
    bpy.ops.object.mode_set(mode="EDIT")
    assert bpy.ops.transform.translate(value=(0, 0, .2) if reverse else (.125, 0, 0)) == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
    cube.modifiers["NativeSync_Bevel"].width = .13 if reverse else .11
    cube.data.uv_layers["NativeSync_UV"].data[0].uv = (.23, .41) if reverse else (.17, .29)
    bpy.data.materials[MATERIAL].node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = .33 if reverse else .22
    bpy.context.view_layer.update()


def tick():
    global initialized, active, edited, selected_at, host_selected_at, host_edited
    try:
        if time.monotonic() - started > 130:
            raise TimeoutError(f"{side} state {session.state}")
        if side == "host" and session.state == STATE_LOBBY and not initialized:
            assert bpy.ops.wm.session_init(init_method="BLEND") == {"FINISHED"}
            initialized = True
        if session.state == STATE_ACTIVE and not active:
            active = True
            bpy.ops.object.select_all(action="DESELECT")
            bpy.context.view_layer.update()
            (folder / (side + "-initial.json")).write_text(json.dumps(capture(), indent=2))
            graph = capture_graph()
            (folder / (side + "-initial-graph.json")).write_text(json.dumps(graph, indent=2))
            if side == "client":
                original = json.loads((folder / "host-original-graph.json").read_text())
                (folder / "initial-fidelity-differences.json").write_text(json.dumps(differences(original, graph), indent=2))
        if side == "client" and active and not edited:
            if selected_at is None:
                select_only(bpy.data.objects[CUBE])
                selected_at = time.monotonic()
            elif time.monotonic() - selected_at > 1.5:
                mutate()
                edited = True
                (folder / "client-edited.json").write_text(json.dumps(capture(), indent=2))
                bpy.ops.object.select_all(action="DESELECT")
        if side == "host" and active and (folder / "client-edited.json").exists():
            now = capture()
            if (abs(now["uv0"][0] - .17) < 1e-5 and abs(now["bevel_width"] - .11) < 1e-5
                    and abs(now["roughness"] - .22) < 1e-5 and abs(now["vertices"][0][0] + .875) < 1e-5):
                (folder / "host-received.json").write_text(json.dumps(now, indent=2))
                if host_selected_at is None:
                    host_selected_at = time.monotonic()
            if host_selected_at is not None and not host_edited:
                if time.monotonic() - host_selected_at > 1:
                    select_only(bpy.data.objects[CUBE])
                if time.monotonic() - host_selected_at > 2.5:
                    mutate(reverse=True)
                    host_edited = True
                    (folder / "host-edited.json").write_text(json.dumps(capture(), indent=2))
        if side == "client" and edited and (folder / "host-edited.json").exists():
            now = capture()
            if (abs(now["uv0"][0] - .23) < 1e-5 and abs(now["bevel_width"] - .13) < 1e-5
                    and abs(now["roughness"] - .33) < 1e-5 and abs(now["vertices"][7][2] - 1.2) < 1e-5):
                (folder / "client-received.json").write_text(json.dumps(now, indent=2))
                (folder / "finish-peers").touch()
        if (folder / "finish-peers").exists():
            bpy.ops.wm.session_quit()
            bpy.ops.wm.quit_blender()
            return None
        return .05
    except Exception:  # noqa: BLE001 - retain every native experiment failure
        (folder / (side + "-error.txt")).write_text(traceback.format_exc())
        try:
            if session.repository:
                session.disconnect(reason="user")
        finally:
            bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=.1)

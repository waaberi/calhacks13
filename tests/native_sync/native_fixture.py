"""Native Blender fidelity fixture for disposable synchronization peers.

These helpers intentionally use ordinary Blender Edit Mode operators, original
RNA datablocks and native Undo/Redo. They do not flatten evaluated geometry and
never replace the user's running Blender document. The launcher must grant the
SPATIAL_NATIVE_SYNC_TEST=1 capability in its own child process environment.
"""
import os

import bpy

MARKER = "native_sync_fixture"
CUBE = "NativeSync_Cube"
LINKED = "NativeSync_LinkedMesh"
RIG = "NativeSync_Rig"
MATERIAL = "NativeSync_Material"
IMAGE = "NativeSync_PackedImage"
GROUP = "NativeSync_NodeGroup"


def _owned():
    if os.environ.get("SPATIAL_NATIVE_SYNC_TEST") != "1":
        raise RuntimeError("Native fidelity mutation requires an owned disposable test process")


def _tag(value):
    value[MARKER] = True
    return value


def select_only(obj):
    _owned()
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def build_fixture():
    """Create a small self-contained original-data graph in an owned empty peer."""
    _owned()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0
    bpy.ops.mesh.primitive_cube_add(size=2)
    cube = _tag(bpy.context.object)
    cube.name = CUBE
    _tag(cube.data)
    cube.data.name = "NativeSync_QuadMesh"
    cube["native_scalar"] = 0.6
    cube["native_note"] = "original topology and native dependency graph"
    cube.data.uv_layers.active.name = "NativeSync_UV"
    for i, loop in enumerate(cube.data.uv_layers.active.data):
        loop.uv = ((i % 4) * 0.19 + 0.03, (i // 4) * 0.11 + 0.07)
    weight = cube.data.attributes.new("NativeSync_Attribute", "FLOAT", "POINT")
    for i, value in enumerate(weight.data):
        value.value = 0.125 * i
    cube.shape_key_add(name="Basis")
    raised = cube.shape_key_add(name="NativeSync_RaisedCorner")
    raised.data[0].co.z += 0.35
    raised.value = 0.23
    bevel = cube.modifiers.new("NativeSync_Bevel", "BEVEL")
    bevel.width, bevel.segments = 0.075, 3
    linked = _tag(bpy.data.objects.new(LINKED, cube.data))
    bpy.context.collection.objects.link(linked)
    linked.location.x = 3.0

    image = _tag(bpy.data.images.new(IMAGE, width=2, height=2, alpha=True))
    image.pixels = [1, .2, .1, 1, .1, .8, .2, 1, .2, .1, .9, 1, .7, .6, .2, 1]
    image.pack()
    material = _tag(bpy.data.materials.new(MATERIAL))
    material.use_nodes = True
    material.diffuse_color = (.2, .4, .7, 1)
    cube.data.materials.append(material)
    nodes = material.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.37
    texture = nodes.new("ShaderNodeTexImage")
    texture.name = "NativeSync_ImageTexture"
    texture.image = image
    material.node_tree.links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
    noise = nodes.new("ShaderNodeTexNoise")
    noise.name = "NativeSync_Noise"
    noise.inputs["Scale"].default_value = 7.25
    group = _tag(bpy.data.node_groups.new(GROUP, "ShaderNodeTree"))
    group.interface.new_socket(name="Value", in_out="OUTPUT", socket_type="NodeSocketFloat")
    output = group.nodes.new("NodeGroupOutput")
    value = group.nodes.new("ShaderNodeValue")
    value.outputs[0].default_value = .64
    group.links.new(value.outputs[0], output.inputs["Value"])
    instance = nodes.new("ShaderNodeGroup")
    instance.name, instance.node_tree = "NativeSync_GroupInstance", group
    material.node_tree.links.new(instance.outputs["Value"], bsdf.inputs["Metallic"])
    driver = noise.inputs["Scale"].driver_add("default_value").driver
    driver.expression = "native_value * 10"
    variable = driver.variables.new()
    variable.name, variable.type = "native_value", "SINGLE_PROP"
    variable.targets[0].id = cube
    variable.targets[0].data_path = '["native_scalar"]'

    armature = _tag(bpy.data.armatures.new("NativeSync_Armature"))
    rig = _tag(bpy.data.objects.new(RIG, armature))
    bpy.context.collection.objects.link(rig)
    select_only(rig)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.edit_bones.new("NativeSync_Bone")
    bone.head, bone.tail = (0, 0, -1), (0, 0, 1)
    bpy.ops.object.mode_set(mode="OBJECT")
    vertex_group = cube.vertex_groups.new(name="NativeSync_Bone")
    vertex_group.add(list(range(len(cube.data.vertices))), .65, "REPLACE")
    modifier = cube.modifiers.new("NativeSync_ArmatureModifier", "ARMATURE")
    modifier.object = rig
    select_only(cube)
    bpy.context.view_layer.update()
    return cube


def edit_fixture(side):
    """Apply full native operations beyond object-transform request vocabularies."""
    _owned()
    cube = bpy.data.objects[CUBE]
    if not cube.get(MARKER):
        raise RuntimeError("Refusing to edit a non-fixture object")
    select_only(cube)
    cube.active_shape_key_index = 0
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    cube.data.vertices[0 if side == "host" else 6].select = True
    bpy.ops.object.mode_set(mode="EDIT")
    delta = (.125, .05, 0) if side == "host" else (0, -.075, .2)
    assert bpy.ops.transform.translate(value=delta) == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
    if side == "host":
        cube.modifiers["NativeSync_Bevel"].width = .11
        cube.data.uv_layers["NativeSync_UV"].data[0].uv = (.17, .29)
        cube["native_scalar"] = .81
        bpy.data.materials[MATERIAL].node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = .22
    elif side == "client":
        cube.data.shape_keys.key_blocks["NativeSync_RaisedCorner"].value = .48
        cube.modifiers["NativeSync_Bevel"].segments = 5
        bpy.data.node_groups[GROUP].nodes.get("Value").outputs[0].default_value = .31
        rig = bpy.data.objects[RIG]
        rig.pose.bones["NativeSync_Bone"].rotation_mode = "XYZ"
        rig.pose.bones["NativeSync_Bone"].rotation_euler.y = .13
        cube["native_note"] = "edited through ordinary native Client data"
    else:
        raise ValueError("side must be host or client")
    bpy.context.view_layer.update()

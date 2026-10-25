"""Semantic original-datablock graph checks; no evaluated mesh substitution."""
import hashlib

import bpy
from native_fixture import CUBE, GROUP, IMAGE, LINKED, MATERIAL, RIG


def value(item):
    if item is None or isinstance(item, (str, bool, int)):
        return item
    if isinstance(item, dict):
        return {str(key): value(part) for key, part in item.items()}
    if hasattr(item, "to_dict"):
        return value(item.to_dict())
    if isinstance(item, float):
        return round(item, 7)
    if isinstance(item, bpy.types.ID):
        return {"id_type": item.bl_rna.identifier, "name": item.name}
    try:
        return [value(part) for part in item]
    except TypeError:
        return str(item)


def simple_rna(item):
    out = {}
    for prop in item.bl_rna.properties:
        if prop.identifier in {"rna_type", "select"} or prop.is_readonly:
            continue
        if prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            continue
        try:
            out[prop.identifier] = value(getattr(item, prop.identifier))
        except (AttributeError, RuntimeError, TypeError):
            continue
    return out


def drivers(block):
    animation = block.animation_data
    if animation is None:
        return []
    return [{"path": curve.data_path, "index": curve.array_index,
             "expression": curve.driver.expression,
             "variables": [{"name": var.name, "type": var.type,
                "targets": [{"id": value(target.id), "path": target.data_path,
                             "bone": target.bone_target} for target in var.targets]}
                for var in curve.driver.variables]} for curve in animation.drivers]


def node_tree(tree):
    return {"nodes": [{"name": node.name, "type": node.bl_idname,
                       "rna": simple_rna(node),
                       "image": value(getattr(node, "image", None)),
                       "color_ramp": {"interpolation": node.color_ramp.interpolation,
                           "color_mode": node.color_ramp.color_mode,
                           "elements": [{"position": value(element.position), "color": value(element.color)}
                                        for element in node.color_ramp.elements]}
                           if hasattr(node, "color_ramp") else None,
                       "node_tree": value(getattr(node, "node_tree", None)),
                       "inputs": [{"name": socket.name, "id": socket.identifier,
                                   "default": value(getattr(socket, "default_value", None))}
                                  for socket in node.inputs],
                       "outputs": [{"name": socket.name, "id": socket.identifier,
                                    "default": value(getattr(socket, "default_value", None))}
                                   for socket in node.outputs]}
                      for node in sorted(tree.nodes, key=lambda item: item.name)],
            "links": sorted([link.from_node.name, link.from_socket.identifier,
                             link.to_node.name, link.to_socket.identifier] for link in tree.links),
            "drivers": drivers(tree)}


def capture_graph():
    cube, linked = bpy.data.objects[CUBE], bpy.data.objects[LINKED]
    mesh = cube.data
    rig, material = bpy.data.objects[RIG], bpy.data.materials[MATERIAL]
    image = bpy.data.images[IMAGE]
    return {
        "cube": {"name": cube.name, "data": mesh.name, "matrix": value(cube.matrix_world),
                 "custom_scalar": value(cube.get("native_scalar")), "note": cube.get("native_note"),
                 "native_properties": {key: value(prop_value) for key, prop_value in cube.items() if key.startswith("native_")},
                 "modifiers": [{"type": mod.type, "rna": simple_rna(mod), "object": value(getattr(mod, "object", None))}
                               for mod in cube.modifiers],
                 "vertex_groups": [group.name for group in cube.vertex_groups]},
        "mesh": {"vertices": [value(vertex.co) for vertex in mesh.vertices],
                 "edges": [list(edge.vertices) for edge in mesh.edges],
                 "faces": [list(face.vertices) for face in mesh.polygons],
                 "material_indices": [face.material_index for face in mesh.polygons],
                 "uv_layers": {layer.name: [value(loop.uv) for loop in layer.data]
                               for layer in mesh.uv_layers},
                 "attributes": {attr.name: {"type": attr.data_type, "domain": attr.domain,
                      "values": [value(getattr(item, "value", None)) for item in attr.data]}
                      for attr in mesh.attributes if attr.name.startswith("NativeSync")},
                 "materials": [mat.name for mat in mesh.materials],
                 "weights": [[[group.group, value(group.weight)] for group in vertex.groups]
                             for vertex in mesh.vertices]},
        "shape_keys": [{"name": key.name, "value": value(key.value),
                        "relative": key.relative_key.name, "coordinates": [value(p.co) for p in key.data]}
                       for key in (mesh.shape_keys.key_blocks if mesh.shape_keys is not None else [])],
        "linked_mesh": {"same_datablock": linked.data == mesh, "data": linked.data.name,
                        "matrix": value(linked.matrix_world)},
        "material": {"name": material.name, "color": value(material.diffuse_color),
                     "tree": node_tree(material.node_tree)},
        "node_group": node_tree(bpy.data.node_groups[GROUP]),
        "image": {"size": list(image.size), "pixels": value(image.pixels[:]),
                  "packed": image.packed_file is not None,
                  "packed_sha256": hashlib.sha256(image.packed_file.data).hexdigest()
                      if image.packed_file is not None else None},
        "rig": {"data": rig.data.name,
                "bones": [{"name": bone.name, "head": value(bone.head_local),
                           "tail": value(bone.tail_local), "matrix": value(bone.matrix_local)}
                          for bone in rig.data.bones],
                "pose": [{"name": bone.name, "location": value(bone.location),
                          "rotation_mode": bone.rotation_mode, "rotation": value(bone.rotation_euler),
                          "quaternion": value(bone.rotation_quaternion), "scale": value(bone.scale)}
                         for bone in rig.pose.bones]},
    }


def assert_original_data(graph, original_topology=True):
    if original_topology:
        assert len(graph["mesh"]["vertices"]) == 8
        assert len(graph["mesh"]["faces"]) == 6 and all(len(face) == 4 for face in graph["mesh"]["faces"])
        assert len(graph["mesh"]["uv_layers"]["NativeSync_UV"]) == 24
    else:
        assert len(graph["mesh"]["vertices"]) > 8
        assert len(graph["mesh"]["faces"]) > 6
        assert all(len(key["coordinates"]) == len(graph["mesh"]["vertices"]) for key in graph["shape_keys"])
    assert graph["linked_mesh"]["same_datablock"]
    assert [entry["name"] for entry in graph["shape_keys"]] == ["Basis", "NativeSync_RaisedCorner"]
    assert [entry["type"] for entry in graph["cube"]["modifiers"]] == ["BEVEL", "ARMATURE"]
    assert graph["image"]["packed"] and len(graph["image"]["pixels"]) == 16
    assert len(graph["material"]["tree"]["drivers"]) == 1
    assert len(graph["rig"]["bones"]) == len(graph["rig"]["pose"]) == 1


def differences(expected, actual, path=""):
    """Bounded useful mismatch paths for cross-process synchronization diagnostics."""
    if type(expected) is not type(actual):
        return [path + ": type differs"]
    if isinstance(expected, dict):
        out = [path + "." + key + ": missing/extra" for key in expected.keys() ^ actual.keys()]
        for key in expected.keys() & actual.keys():
            out.extend(differences(expected[key], actual[key], path + "." + key))
            if len(out) >= 30:
                break
        return out[:30]
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [path + ": length differs"]
        out = []
        for i, (before, after) in enumerate(zip(expected, actual, strict=True)):
            out.extend(differences(before, after, path + f"[{i}]"))
            if len(out) >= 30:
                break
        return out[:30]
    return [] if expected == actual else [path + ": " + repr(expected) + " != " + repr(actual)]

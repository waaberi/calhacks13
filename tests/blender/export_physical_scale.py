"""Run in background Blender: export real metre/mm/cm fixtures and world-space oracles."""
import hashlib
import json
import sys
from pathlib import Path

import bpy

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo / 'blender_addon'))
from spatial_modeling import scene as export


def identity(name):
    return hashlib.md5(name.encode(), usedforsecurity=False).hexdigest()


cases = []
for unit in (1.0, 0.001, 0.01):
    scene = bpy.data.scenes.new(f'Physical scale {unit}')
    bpy.context.window.scene = scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = unit
    scene.unit_settings.length_unit = 'MILLIMETERS' if unit == .001 else 'METERS'
    parent = bpy.data.objects.new('Assembly', None)
    scene.collection.objects.link(parent)
    parent.location = (.3 / unit, -.2 / unit, .1 / unit)
    parent.rotation_euler = (.2, .1, .4)
    parent.scale = (1.5,) * 3
    records, expected = [], []
    for name, sizes, parented in [('20mm part', (.02, .03, .04), False),
                                  ('1m assembly part', (1.0, .6, .4), True)]:
        mesh = bpy.data.meshes.new(name)
        vertices = [tuple(sign[i] * sizes[i] / unit / 2 for i in range(3))
                    for sign in [(-1,-1,-1), (1,-1,-1), (1,1,-1), (-1,1,-1),
                                 (-1,-1,1), (1,-1,1), (1,1,1), (-1,1,1)]]
        mesh.from_pydata(vertices, [], [(0,3,2,1), (4,5,6,7), (0,1,5,4),
                                        (1,2,6,5), (2,3,7,6), (3,0,4,7)])
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        if parented:
            obj.parent = parent
            obj.location = (.15 / unit, .05 / unit, .1 / unit)
            obj.rotation_euler = (.1, -.2, .3)
            obj.scale = (.7, 1.2, -.4)
            modifier = obj.modifiers.new('Evaluated subdivision', 'SUBSURF')
            modifier.subdivision_type = 'SIMPLE'
            modifier.levels = 1
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    for obj in scene.objects:
        record = export.record(obj, identity(obj.name), identity(obj.parent.name) if obj.parent else None,
                               bpy.context.view_layer, graph, unit)
        mesh = export.evaluated_mesh(obj, graph, unit)
        record.update(generation=0, mesh=mesh.wire() if mesh else None)
        records.append(record)
        if obj.type == 'MESH':
            evaluated = obj.evaluated_get(graph)
            native = evaluated.to_mesh()
            world = [list((evaluated.matrix_world @ v.co) * unit) for v in native.vertices]
            evaluated.to_mesh_clear()
            expected.append({'name': obj.name, 'world_vertices_metres': world})
    cases.append({'payload': {'document': {'id': identity(str(unit)), 'open_epoch': '2'*32,
                  'name': scene.name, 'revision': 0, 'dirty': False,
                  'units': {'system': 'METRIC', 'length_unit': scene.unit_settings.length_unit,
                            'rotation_unit': 'DEGREES', 'scale_length': unit}},
                  'objects': records}, 'expected': expected})
target = repo / 'tests/fixtures/physical-scale.json'
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({'blender_version': bpy.app.version_string, 'cases': cases}, indent=2) + '\n',
                  encoding='utf-8')
print(f'PHYSICAL_SCALE_EXPORTED {len(cases)} unit cases from real Blender; {target}', flush=True)

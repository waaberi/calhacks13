"""Factory-only solid/plane tools plus exact finishing history and refusals."""

import json
import sys
import traceback
import uuid
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_modeling_extended_gate as gate

tools, editor = gate.tools, gate.editor
REPORT, OUTPUT = gate.REPORT, gate.OUTPUT
apply, check, make, active, clean, history = gate.apply, gate.check, gate.make, gate.active, gate.clean, gate.history


def mesh_state(obj):
    bm = bmesh.from_edit_mesh(obj.data).copy() if obj.data.is_editmode else bmesh.new()
    if not obj.data.is_editmode:
        bm.from_mesh(obj.data)
    try:
        for values in (bm.verts, bm.edges, bm.faces):
            values.index_update()
        return {'vertices': [tuple(v.co) for v in bm.verts],
                'edges': [(tuple(v.index for v in e.verts), e.seam, e.smooth) for e in bm.edges],
                'faces': [(tuple(v.index for v in f.verts), f.material_index, f.smooth) for f in bm.faces],
                'uv': [(name, [(tuple(l[layer].uv), l[layer].pin_uv) for f in bm.faces for l in f.loops])
                       for name in list(bm.loops.layers.uv.keys()) for layer in [bm.loops.layers.uv[name]]]}
    finally:
        bm.free()


def run():
    bpy.context.preferences.edit.use_global_undo = True
    for unit in (1, .001):
        clean()
        bpy.context.scene.unit_settings.scale_length = unit
        for solver in ('EXACT', 'FLOAT', 'MANIFOLD'):
            obj = make()
            operand = make(name='Private Boolean operand')
            operand.location.x = .05 / unit
            operand.scale = (.8, .8, 2)
            operand_id = gate.Sync.object_id(operand)
            active(obj)
            bpy.context.view_layer.update()
            obj = history(obj, 'Native Boolean ' + solver,
                lambda obj=obj, operand_id=operand_id, solver=solver: apply(obj, 'modifier.boolean',
                    {'operand_id': operand_id, 'operation': 'DIFFERENCE', 'solver': solver}),
                lambda o: [(m.type, m.operation, m.solver, m.object.get('spatial_modeling_id')) for m in o.modifiers])
            evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            try:
                bm = bmesh.new()
                bm.from_mesh(mesh)
                volume = abs(bm.calc_volume()) * unit ** 3
                bm.free()
                check('Boolean actual reduced volume ' + solver, 0 < volume < .008 - 1e-6)
            finally:
                evaluated.to_mesh_clear()

        obj = make()
        active(obj, 'EDIT')
        obj = history(obj, 'Flatten native plane', lambda obj=obj: apply(obj, 'mesh.flatten',
                      {'normal': [0, 0, 1], 'plane_point_m': [0, 0, .02]}, 'vertex', [0, 1, 2]), mesh_state)
        bm = bmesh.from_edit_mesh(obj.data)
        check('flatten exact world plane', all(abs(v.co.z * unit - .02) < 1e-6 for v in list(bm.verts)[:3]))
        before = mesh_state(obj)
        try:
            apply(obj, 'mesh.flatten', {'normal': [0, 0, 0]}, 'vertex', [0])
            raise AssertionError('zero plane normal admitted')
        except ValueError:
            check('invalid plane refused before native write', mesh_state(obj) == before)

        obj = make()
        # A single native quad becomes a closed slab.
        obj.data.clear_geometry()
        obj.data.from_pydata([(-.1 / unit, -.1 / unit, 0), (.1 / unit, -.1 / unit, 0),
                              (.1 / unit, .1 / unit, 0), (-.1 / unit, .1 / unit, 0)], [], [(0, 1, 2, 3)])
        active(obj, 'EDIT')
        obj = history(obj, 'Selected solidify', lambda obj=obj: apply(obj, 'mesh.solidify',
                      {'thickness_m': .02}, 'face', [0]), mesh_state)
        bm = bmesh.from_edit_mesh(obj.data)
        check('solidify creates closed native slab', len(bm.faces) == 6 and all(len(e.link_faces) == 2 for e in bm.edges))
        check('solidify native metric volume', abs(abs(bm.calc_volume()) * unit ** 3 - .0008) < 1e-7)

        obj = make()
        obj.data.vertices[0].co.x *= 1.3
        active(obj, 'EDIT')
        obj = history(obj, 'Native symmetrize', lambda obj=obj: apply(obj, 'mesh.symmetrize',
                      {'direction': '-X'}, 'vertex', list(range(8))), mesh_state)
        coords = [v.co.copy() * unit for v in bmesh.from_edit_mesh(obj.data).verts]
        check('native symmetry pairs exist', all(any((Vector((-v.x, v.y, v.z)) - q).length < 1e-6 for q in coords) for v in coords))

        # History across the initial finishing families uses the same one-step caller.
        obj = make()
        obj.data.uv_layers.new(name='UVMap')
        active(obj, 'EDIT')
        history(obj, 'UV pin native history', lambda obj=obj: apply(obj, 'uv.pin', {'pinned': True}, 'face', [0]), mesh_state)
        obj = make()
        history(obj, 'Material native history', lambda obj=obj: apply(obj, 'material.principled',
                {'base_colour': [.2, .3, .4, 1], 'roughness': .2}),
                lambda o: [(m.name, tuple(m.diffuse_color), m.roughness) for m in o.data.materials])
        obj = make()
        collection = 'Private history ' + uuid.uuid4().hex[:8]
        history(obj, 'Collection native history', lambda obj=obj, collection=collection: apply(obj, 'collection.create', {'name': collection}),
                lambda _: sorted(c.name for c in bpy.data.collections))
        obj = make()
        def group_chain(obj=obj):
            apply(obj, 'vertex_group.create', {'name': 'Weighted'})
            return apply(obj, 'weights.assign', {'name': 'Weighted', 'weight': .7}, 'vertex', [0, 1])
        history(obj, 'Group and weights single chain', group_chain,
                lambda o: ([(g.name, g.lock_weight) for g in o.vertex_groups],
                           [[(g.group, g.weight) for g in v.groups] for v in o.data.vertices]))
        data = bpy.data.curves.new('Private curve history', 'CURVE')
        obj = bpy.data.objects.new('Private curve history', data)
        bpy.context.scene.collection.objects.link(obj)
        gate.Sync.object_id(obj)
        active(obj)
        history(obj, 'Curve native history', lambda obj=obj: apply(obj, 'curve.spline_add',
                {'kind': 'BEZIER', 'points_m': [[0, 0, 0], [.1, .2, 0], [.2, 0, 0]]}),
                lambda o: [(s.type, [tuple(p.co) for p in s.bezier_points]) for s in o.data.splines])

        obj = make()
        other = bpy.data.objects.new('Shared data sentinel', obj.data)
        bpy.context.scene.collection.objects.link(other)
        before = mesh_state(obj)
        try:
            apply(obj, 'vertex_group.create', {'name': 'Refused'})
            raise AssertionError('shared mesh admitted')
        except ValueError:
            check('shared mesh refused unchanged', mesh_state(obj) == before and not obj.vertex_groups)
        bpy.data.objects.remove(other, do_unlink=True)
        try:
            apply(obj, 'camera.settings', {'clip_start_m': 1})
            raise AssertionError('wrong native data type admitted')
        except ValueError:
            check('wrong native family refused unchanged', mesh_state(obj) == before)
        extra = tools.ExtraBackup([{'tool': 'vertex_group.create', 'target': gate.Sync.object_id(obj)}], editor)
        original_scene = bpy.context.scene
        isolated_scene = bpy.data.scenes.new('Private wrong document')
        bpy.context.window.scene = isolated_scene
        try:
            extra.restore()
            raise AssertionError('cross-document rollback admitted')
        except ValueError:
            check('cross-document metadata rollback refused', not obj.vertex_groups)
        finally:
            bpy.context.window.scene = original_scene
            bpy.data.scenes.remove(isolated_scene)
            extra.close()
        # Renamed collections and a newly reused name must roll back exactly.
        name = 'Private collection collision ' + uuid.uuid4().hex[:8]
        apply(obj, 'collection.create', {'name': name})
        steps = [{'tool': 'collection.rename', 'target': gate.Sync.object_id(obj)},
                 {'tool': 'collection.create', 'target': gate.Sync.object_id(obj)}]
        extra, baseline = tools.ExtraBackup(steps, editor), gate.voice_sequence.Backup([obj])
        apply(obj, 'collection.rename', {'name': name, 'new_name': name + ' changed'})
        apply(obj, 'collection.create', {'name': name})
        baseline.restore()
        extra.restore()
        baseline.close(restored=True)
        extra.close(restored=True)
        check('collection reused-name rollback exact', bpy.data.collections.get(name) is not None
              and bpy.data.collections.get(name + ' changed') is None)
        # A disabled collection can temporarily remove its members from the view layer.
        obj = make()
        collection = bpy.data.collections.new('Private disabled collection ' + uuid.uuid4().hex[:8])
        bpy.context.scene.collection.children.link(collection)
        collection.objects.link(obj)
        bpy.context.scene.collection.objects.unlink(obj)
        bpy.context.view_layer.update()
        active(obj)
        identity = gate.Sync.object_id(obj)
        steps = [{'tool': 'collection.visibility', 'target': identity}]
        extra, baseline = tools.ExtraBackup(steps, editor), gate.voice_sequence.Backup([obj])
        apply(obj, 'collection.visibility', {'name': collection.name, 'viewport': False})
        baseline.restore()
        extra.restore()
        baseline.close(restored=True)
        extra.close(restored=True)
        obj = gate.Sync.find_object(identity)
        check('disabled collection rollback restores active native target', not collection.hide_viewport
              and bpy.context.view_layer.objects.active == obj and obj.select_get())
    offered = tools.OPERATIONS - gate.catalog.BASE_OPERATIONS - gate.catalog.RIG_SCENE_OPERATIONS
    check('all new solid and plane tools exercised', offered <= set(REPORT['tools']))
    REPORT['passed'] = True


try:
    run()
except Exception:
    REPORT['error'] = traceback.format_exc()
    raise
finally:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(REPORT, indent=2), encoding='utf-8')
print(json.dumps({'passed': REPORT['passed'], 'checks': len(REPORT['checks']), 'tools': len(set(REPORT['tools']))}), flush=True)

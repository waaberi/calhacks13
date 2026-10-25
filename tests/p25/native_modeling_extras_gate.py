"""Factory-process native finishing checks. Never opens an existing document."""

import json
import os
import sys
import traceback
import uuid
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'blender_addon'))
sys.dont_write_bytecode = True
from spatial_modeling import edits, host, voice_sequence
from spatial_modeling import modeling_extras as tools
from spatial_modeling import tool_catalog_extras as catalog

OUTPUT = Path(sys.argv[sys.argv.index('--output') + 1])
REPORT = {'passed': False, 'physical_acceptance': False, 'blender': bpy.app.version_string,
          'checks': [], 'tools': []}


class Sync:
    @staticmethod
    def object_id(obj):
        if not obj.get('spatial_modeling_id'):
            obj['spatial_modeling_id'] = uuid.uuid4().hex
        return obj['spatial_modeling_id']

    @staticmethod
    def find_object(identity):
        return next((o for o in bpy.context.scene.objects if o.get('spatial_modeling_id') == identity), None)


editor = edits.Editor(Sync, host.undoable)


def check(name, value=True):
    assert value, name
    REPORT['checks'].append(name)


def fresh(kind='mesh', edit=False, triangles=False):
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    if kind == 'curve':
        data = bpy.data.curves.new('Owned curve', 'CURVE')
        data.dimensions = '3D'
    else:
        data = bpy.data.meshes.new('Owned mesh')
        data.from_pydata([(-.1, -.1, 0), (0, -.1, 0), (.1, -.1, 0),
                          (-.1, .1, 0), (0, .1, 0), (.1, .1, 0)], [],
                         [(0, 1, 4, 3), (1, 2, 5, 4)])
        data.uv_layers.new(name='UVMap')
        for loop in data.loops:
            data.uv_layers.active.data[loop.index].uv = data.vertices[loop.vertex_index].co.xy
        if triangles:
            bm = bmesh.new()
            bm.from_mesh(data)
            bmesh.ops.triangulate(bm, faces=list(bm.faces))
            bm.to_mesh(data)
            bm.free()
    obj = bpy.data.objects.new('Owned target', data)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    Sync.object_id(obj)
    if edit:
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.object.mode_set(mode='EDIT')
    return obj


def apply(obj, tool, params=None, component='object', indices=None):
    result = tools.apply_step(editor, obj, tool, params or {},
                              {'component': component, 'indices': indices or []})
    REPORT['tools'].append(tool)
    check(tool + ' final target', result['selection']['id'] == Sync.object_id(obj))
    return result


def weights(obj):
    if obj.data.is_editmode:
        bm = bmesh.from_edit_mesh(obj.data)
        layer = bm.verts.layers.deform.active
        return [dict(v[layer]) if layer else {} for v in bm.verts]
    return [{g.group: g.weight for g in v.groups} for v in obj.data.vertices]


def run():
    bpy.context.preferences.edit.use_global_undo = True
    check('private native profiles', all(os.environ.get(k) for k in
          ('BLENDER_USER_CONFIG', 'BLENDER_USER_SCRIPTS', 'BLENDER_USER_DATAFILES', 'TEMP', 'TMP')))
    for unit in (1, .001):
        bpy.context.scene.unit_settings.scale_length = unit
        obj = fresh(edit=True)
        result = apply(obj, 'uv.select_island', component='face', indices=[0])
        check('exact UV continuity expands both faces', result['selection']['indices'] == [0, 1])
        before_uv = tools.context_fingerprint()
        apply(obj, 'uv.pin', {'pinned': True}, 'face', [0])
        check('UV pin changes opaque native freshness', tools.context_fingerprint() != before_uv)
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        check('pins selected face only', all(l[uv].pin_uv for l in bm.faces[0].loops)
              and not any(l[uv].pin_uv for l in bm.faces[1].loops))
        apply(obj, 'uv.pin', {'pinned': False}, 'face', [0])
        original_sync = bpy.context.scene.tool_settings.use_uv_select_sync
        for name in ('uv.pack', 'uv.weld', 'uv.average_islands_scale'):
            apply(obj, name, component='face', indices=[0, 1])
        check('UV sync setting restored', bpy.context.scene.tool_settings.use_uv_select_sync == original_sync)
        bpy.ops.object.mode_set(mode='OBJECT')
        original = [tuple(loop.uv) for loop in obj.data.uv_layers.active.data]
        apply(obj, 'uv.layer_copy', {'name': 'Independent UV'})
        check('UV layer copy exact', [tuple(l.uv) for l in obj.data.uv_layers.active.data] == original)
        apply(obj, 'uv.layer_activate', {'name': 'UVMap'})
        check('UV layer activation', obj.data.uv_layers.active.name == 'UVMap')

        obj = fresh()
        apply(obj, 'vertex_group.create', {'name': 'A'})
        apply(obj, 'vertex_group.create', {'name': 'B'})
        apply(obj, 'weights.assign', {'name': 'A', 'weight': .25}, 'vertex', [0, 1])
        apply(obj, 'weights.assign', {'name': 'B', 'weight': .25}, 'vertex', [0, 1])
        apply(obj, 'weights.normalize', component='vertex', indices=[0, 1])
        check('weights normalized', abs(sum(weights(obj)[0].values()) - 1) < 1e-6)
        apply(obj, 'weights.smooth', {'name': 'A', 'factor': .5, 'iterations': 2}, 'vertex', [0, 1])
        check('smoothing changes native weights', weights(obj)[0][0] != .5)
        apply(obj, 'vertex_group.lock', {'name': 'A', 'locked': True})
        before = weights(obj)
        try:
            apply(obj, 'weights.assign', {'name': 'A', 'weight': 1}, 'vertex', [0])
            raise AssertionError('locked group admitted')
        except ValueError:
            check('locked group refused without mutation', before == weights(obj))
        apply(obj, 'vertex_group.lock', {'name': 'A', 'locked': False})
        bpy.ops.object.mode_set(mode='EDIT')
        apply(obj, 'weights.assign', {'name': 'A', 'weight': .75}, 'vertex', [2])
        check('Edit mode native weights', abs(weights(obj)[2][0] - .75) < 1e-6)
        apply(obj, 'weights.remove', {'name': 'A'}, 'vertex', [2])
        check('Edit mode weight remove', 0 not in weights(obj)[2])
        bpy.ops.object.mode_set(mode='OBJECT')
        apply(obj, 'vertex_group.rename', {'name': 'A', 'new_name': 'Renamed'})
        apply(obj, 'vertex_group.remove', {'name': 'Renamed'})
        check('native group removal keeps other group', [g.name for g in obj.vertex_groups] == ['B'])

        obj = fresh()
        original = bpy.data.materials.new('Original shared source')
        original.use_nodes = True
        original.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = (.1, .2, .3, 1)
        obj.data.materials.append(original)
        apply(obj, 'material.principled', {'roughness': .2, 'metallic': .8, 'emission_strength': 3, 'transmission': .3})
        check('shader freshness is serializable', len(tools.context_fingerprint()) == 64)
        check('material isolated from original', obj.active_material != original)
        check('unchanged shader values preserved', tuple(obj.active_material.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value) == tuple(original.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value))
        check('native shader parameter', abs(obj.active_material.node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value - .2) < 1e-6)
        apply(obj, 'material.slot_remove', {'index': 0})
        check('native material slot removal', len(obj.data.materials) == 0)

        obj = fresh()
        name = 'Owned collection ' + uuid.uuid4().hex[:8]
        apply(obj, 'collection.create', {'name': name})
        apply(obj, 'object.collection_link', {'name': name})
        renamed = name + ' renamed'
        apply(obj, 'collection.rename', {'name': name, 'new_name': renamed})
        apply(obj, 'collection.visibility', {'name': renamed, 'render': False})
        check('collection visibility native state', bpy.data.collections[renamed].hide_render)
        apply(obj, 'object.collection_unlink', {'name': renamed})
        check('collection unlink preserves original scene link', len(obj.users_collection) == 1)

        obj = fresh('curve')
        for kind in ('POLY', 'NURBS', 'BEZIER'):
            apply(obj, 'curve.spline_add', {'kind': kind, 'points_m': [[0, 0, 0], [.1, .2, 0], [.2, 0, 0]]})
        apply(obj, 'curve.point_set', {'spline': 2, 'point': 1, 'position_m': [.1, .3, 0], 'radius': .5, 'tilt': .2})
        check('curve local metric coordinates', (obj.data.splines[2].bezier_points[1].co * unit - Vector((.1, .3, 0))).length < 1e-6)
        apply(obj, 'curve.settings', {'bevel_depth_m': .002, 'bevel_resolution': 2, 'extrude_m': .001, 'fill_caps': True, 'resolution': 8})
        check('curve metric bevel', abs(obj.data.bevel_depth * unit - .002) < 1e-6)
        apply(obj, 'curve.spline_remove', {'spline': 0})
        check('curve spline deletion', len(obj.data.splines) == 2)

        obj = fresh(edit=True)
        apply(obj, 'mesh.poke', {'offset_m': .01}, 'face', [0])
        check('poke real new triangles', len(bmesh.from_edit_mesh(obj.data).faces) == 5)
        obj = fresh(edit=True, triangles=True)
        result = apply(obj, 'mesh.tris_to_quads', component='face', indices=[0, 1, 2, 3])
        check('triangles join to actual quads', len(bmesh.from_edit_mesh(obj.data).faces) == 2)
        apply(obj, 'mesh.smooth_vertices', {'preserve_boundary': False}, 'vertex', [0, 1])
        # A grid gives the inverse subdivision operator meaningful topology.
        bpy.ops.object.mode_set(mode='OBJECT')
        mesh = obj.data
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=4, y_segments=4, size=.1)
        bm.to_mesh(mesh)
        bm.free()
        bpy.ops.object.mode_set(mode='EDIT')
        count = len(bmesh.from_edit_mesh(mesh).verts)
        apply(obj, 'mesh.unsubdivide', {'iterations': 1}, 'vertex', list(range(count)))
        check('inverse subdivision changes native topology', len(bmesh.from_edit_mesh(mesh).verts) < count)

        obj = fresh(edit=True)
        surface_data = bpy.data.meshes.new('Projection surface')
        surface_data.from_pydata([(-2, -2, .1 / unit), (2, -2, .1 / unit), (2, 2, .1 / unit), (-2, 2, .1 / unit)], [], [(0, 1, 2, 3)])
        surface = bpy.data.objects.new('Owned surface', surface_data)
        bpy.context.scene.collection.objects.link(surface)
        surface_id = Sync.object_id(surface)
        bpy.context.view_layer.update()
        apply(obj, 'mesh.project_surface', {'surface_id': surface_id, 'max_distance_m': 1, 'normal_offset_m': .02}, 'vertex', [0, 1])
        check('retopology world metric projection', all(abs(v.co.z * unit - .12) < 1e-6 for v in list(bmesh.from_edit_mesh(obj.data).verts)[:2]))

    # Mixed-operation rollback uses exactly the public integration hooks.
    obj = fresh()
    obj.vertex_groups.new(name='Keep')
    obj.vertex_groups['Keep'].add([0], .25, 'REPLACE')
    identity = Sync.object_id(obj)
    before_groups = [(g.name, g.lock_weight) for g in obj.vertex_groups]
    before_weights = weights(obj)
    before_collections = sorted(c.name for c in bpy.data.collections)
    before_membership = tuple(obj.users_collection)
    steps = [{'tool': name, 'target': identity} for name in
             ('vertex_group.rename', 'weights.assign', 'material.principled', 'collection.create', 'object.collection_link')]
    extra = tools.ExtraBackup(steps, editor)
    baseline = voice_sequence.Backup([obj])
    apply(obj, 'vertex_group.rename', {'name': 'Keep', 'new_name': 'Changed'})
    apply(obj, 'weights.assign', {'name': 'Changed', 'weight': 1}, 'vertex', [0, 1])
    apply(obj, 'material.principled', {'base_colour': [1, 0, 0, 1]})
    collection = 'Rollback collection ' + uuid.uuid4().hex[:8]
    apply(obj, 'collection.create', {'name': collection})
    apply(obj, 'object.collection_link', {'name': collection})
    baseline.restore()
    extra.restore()
    baseline.close(restored=True)
    extra.close(restored=True)
    obj = Sync.find_object(identity)
    check('atomic group definitions rollback', [(g.name, g.lock_weight) for g in obj.vertex_groups] == before_groups)
    check('atomic native weights rollback', weights(obj) == before_weights)
    check('atomic new collections removed', sorted(c.name for c in bpy.data.collections) == before_collections)
    check('atomic membership rollback', tuple(obj.users_collection) == before_membership)
    check('atomic new material removed', len(obj.data.materials) == 0)

    # The shared history wrapper owns exactly one step for an extras operation.
    bpy.ops.ed.undo_push(message='Extras baseline')
    before = weights(obj)
    host.undoable('Whole extras edit')(lambda: apply(obj, 'weights.assign', {'name': 'Keep', 'weight': .8}, 'vertex', [0, 1]))()
    after = weights(obj)
    with __import__('spatial_modeling.modeling_tools', fromlist=['native_context']).native_context(obj):
        check('native extras Undo finished', bpy.ops.ed.undo() == {'FINISHED'})
    obj = Sync.find_object(identity)
    check('one native Undo restores weights', weights(obj) == before)
    with __import__('spatial_modeling.modeling_tools', fromlist=['native_context']).native_context(obj):
        check('native extras Redo finished', bpy.ops.ed.redo() == {'FINISHED'})
    obj = Sync.find_object(identity)
    check('one native Redo restores weights', weights(obj) == after)
    check('every base finishing tool exercised', set(REPORT['tools']) == catalog.BASE_OPERATIONS)
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

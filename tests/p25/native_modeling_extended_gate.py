"""Disposable native pose, history, animation, finishing and metadata checks."""

import json
import os
import sys
import traceback
import uuid
from pathlib import Path

import bmesh
import bpy
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'blender_addon'))
sys.dont_write_bytecode = True
from spatial_modeling import edits, host, modeling_tools, voice_sequence
from spatial_modeling import modeling_extras as tools
from spatial_modeling import tool_catalog_extras as catalog

OUTPUT = Path(sys.argv[sys.argv.index('--output') + 1])
REPORT = {'passed': False, 'physical_acceptance': False, 'checks': [], 'tools': [], 'blender': bpy.app.version_string}


class Sync:
    @staticmethod
    def object_id(obj):
        if not obj.get('spatial_modeling_id'):
            obj['spatial_modeling_id'] = uuid.uuid4().hex
        return obj['spatial_modeling_id']

    stage_object_id = object_id

    @staticmethod
    def find_object(identity):
        return next((o for o in bpy.context.scene.objects if o.get('spatial_modeling_id') == identity), None)


editor = edits.Editor(Sync, host.undoable)


def check(name, condition=True):
    assert condition, name
    REPORT['checks'].append(name)


def active(obj, mode='OBJECT'):
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for item in bpy.context.scene.objects:
        item.select_set(item == obj)
    bpy.context.view_layer.objects.active = obj
    if mode != 'OBJECT':
        bpy.ops.object.mode_set(mode=mode)


def clean():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for item in list(bpy.data.objects):
        bpy.data.objects.remove(item, do_unlink=True)


def make(kind='MESH', name='Private target'):
    if kind == 'MESH':
        data = bpy.data.meshes.new(name)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=.2 / bpy.context.scene.unit_settings.scale_length)
        bm.to_mesh(data)
        bm.free()
    elif kind == 'ARMATURE':
        data = bpy.data.armatures.new(name)
    elif kind == 'CAMERA':
        data = bpy.data.cameras.new(name)
    elif kind == 'LIGHT':
        data = bpy.data.lights.new(name, 'POINT')
    elif kind == 'FONT':
        data = bpy.data.curves.new(name, 'FONT')
    else:
        data = None
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    Sync.object_id(obj)
    active(obj)
    if kind == 'ARMATURE':
        bpy.ops.object.mode_set(mode='EDIT')
        unit = bpy.context.scene.unit_settings.scale_length
        root = data.edit_bones.new('Root')
        root.head, root.tail = (0, 0, 0), (0, .1 / unit, 0)
        tip = data.edit_bones.new('Tip')
        tip.head, tip.tail = root.tail, (0, .2 / unit, 0)
        tip.parent = root
        tip.use_connect = True
        bpy.ops.object.mode_set(mode='OBJECT')
        for bone in obj.pose.bones:
            bone.rotation_mode = 'QUATERNION'
    return obj


def apply(obj, tool, params=None, component='object', indices=None):
    result = tools.apply_step(editor, obj, tool, params or {}, {'component': component, 'indices': indices or []})
    REPORT['tools'].append(tool)
    check(tool + ' native selection', result['selection']['id'] == Sync.object_id(obj))
    return result


def history(obj, label, operation, observe):
    identity = Sync.object_id(obj)
    bpy.ops.ed.undo_push(message='Private ' + label + ' baseline')
    before = observe(obj)
    host.undoable(label)(operation)()
    obj = Sync.find_object(identity)
    after = observe(obj)
    check(label + ' actual native change', before != after)
    with modeling_tools.native_context(obj):
        check(label + ' Undo finished', bpy.ops.ed.undo() == {'FINISHED'})
    obj = Sync.find_object(identity)
    check(label + ' one Undo exact', observe(obj) == before)
    with modeling_tools.native_context(obj):
        check(label + ' Redo finished', bpy.ops.ed.redo() == {'FINISHED'})
    obj = Sync.find_object(identity)
    check(label + ' one Redo exact', observe(obj) == after)
    return obj


def key_state(obj):
    action = obj.animation_data.action if obj.animation_data else None
    return [] if action is None else [(c.data_path, c.array_index, [(tuple(k.co), k.interpolation) for k in c.keyframe_points])
                                      for c in tools._action_curves(action)]


def run():
    bpy.context.preferences.edit.use_global_undo = True
    check('private factory profiles', all(os.environ.get(key) for key in
          ('BLENDER_USER_CONFIG', 'BLENDER_USER_SCRIPTS', 'BLENDER_USER_DATAFILES', 'TEMP', 'TMP')))
    for index in range(257):
        bpy.context.scene.collection.objects.link(bpy.data.objects.new('Untouched bound regression ' + str(index), None))
    unused = tools.ExtraBackup([{'tool': 'object.translate', 'target': 'unused'}], editor)
    unused.restore()
    unused.close(restored=True)
    check('base recipes retain scenes above 256 objects', unused.noop)
    clean()
    class AtomicSync:
        @staticmethod
        def object_id(obj):
            raise AssertionError('Atomic identity lookup must not flush')

        @staticmethod
        def stage_object_id(obj):
            obj['spatial_modeling_id'] = 'staged-only'
            return 'staged-only'
    class AtomicEditor:
        sync = AtomicSync
    check('new recipe identities do not publish', tools._identity(AtomicEditor(), {}) == 'staged-only')
    for unit in (1, .001):
        clean()
        bpy.context.scene.unit_settings.scale_length = unit
        rig = make('ARMATURE')
        active(rig, 'POSE')
        before = tools.context_fingerprint()
        rig.pose.bones['Tip'].select = not rig.pose.bones['Tip'].select
        check('bone selection changes freshness', tools.context_fingerprint() != before)
        angle = Quaternion((0, 0, 1), .4)
        rig = history(rig, 'FK pose', lambda rig=rig, angle=angle: apply(rig, 'rig.pose_transform',
                      {'bone': 'Root', 'location_m': [.01, 0, 0], 'rotation': list(angle), 'scale': [1.1, 1, 1]}),
                      lambda o: (tuple(o.pose.bones['Root'].location), tuple(o.pose.bones['Root'].rotation_quaternion), tuple(o.pose.bones['Root'].scale)))
        active(rig, 'POSE')
        apply(rig, 'rig.pose_reset', {'bone': 'Root'})
        locked_location = tuple(rig.pose.bones['Root'].location)
        rig.pose.bones['Root'].lock_location = (True, False, False)
        try:
            apply(rig, 'rig.pose_transform', {'bone': 'Root', 'location_m': [.03, 0, 0]})
            raise AssertionError('locked pose channel admitted')
        except ValueError:
            check('locked native pose channel refused', tuple(rig.pose.bones['Root'].location) == locked_location)
        rig.pose.bones['Root'].lock_location = (False, False, False)
        check('FK reset native channels', tuple(rig.pose.bones['Root'].location) == (0, 0, 0)
              and tuple(rig.pose.bones['Root'].scale) == (1, 1, 1))
        digest = tools.context_fingerprint()
        rig.pose.bones['Root'].location.x += .01 / unit
        check('pose channels change freshness without geometry', tools.context_fingerprint() != digest)
        apply(rig, 'rig.pose_reset', {'bone': 'Root'})

        target = make('EMPTY', 'Private IK target')
        target.location = (.06 / unit, .15 / unit, 0)
        active(rig)
        target_id = Sync.object_id(target)
        rig = history(rig, 'IK add', lambda rig=rig, target_id=target_id: apply(rig, 'rig.ik_add', {'bone': 'Tip', 'target_id': target_id, 'chain_count': 2}),
                      lambda o: [(b.name, c.type, c.chain_count, c.influence, c.target.get('spatial_modeling_id'))
                                 for b in o.pose.bones for c in b.constraints])
        check('IK actual evaluated endpoint', (rig.pose.bones['Tip'].tail * unit - Vector((.06, .15, 0))).length < .002)
        check('IK native freshness is serializable', len(tools.context_fingerprint()) == 64)
        apply(rig, 'rig.ik_update', {'bone': 'Tip', 'influence': .5, 'chain_count': 1})
        check('IK native parameter update', rig.pose.bones['Tip'].constraints[0].chain_count == 1)
        # Exact rollback of changed owned constraints and pose channels.
        identity = Sync.object_id(rig)
        before = tools._pose_state(rig, True)
        steps = [{'tool': 'rig.ik_update', 'target': identity}]
        extra, baseline = tools.ExtraBackup(steps, editor), voice_sequence.Backup([rig])
        apply(rig, 'rig.ik_update', {'bone': 'Tip', 'influence': .1})
        baseline.restore()
        extra.restore()
        baseline.close(restored=True)
        extra.close(restored=True)
        rig = Sync.find_object(identity)
        check('owned IK exact rollback', tools._pose_state(rig, True) == before)
        apply(rig, 'rig.ik_remove', {'bone': 'Tip'})
        check('owned IK removed', not any(b.constraints for b in rig.pose.bones))
        rig.pose.bones['Tip'].constraints.new('COPY_LOCATION')
        try:
            apply(rig, 'rig.ik_add', {'bone': 'Tip', 'target_id': target_id})
            raise AssertionError('foreign constraint admitted')
        except ValueError:
            check('foreign constraint refused without removal', rig.pose.bones['Tip'].constraints[0].type == 'COPY_LOCATION')
        for constraint in list(rig.pose.bones['Tip'].constraints):
            rig.pose.bones['Tip'].constraints.remove(constraint)

        mesh = make()
        group = mesh.vertex_groups.new(name='Root')
        group.add(list(range(len(mesh.data.vertices))), 1, 'REPLACE')
        apply(mesh, 'rig.bind_armature', {'rig_id': Sync.object_id(rig)})
        rig.pose.bones['Root'].location.x = .03 / unit
        bpy.context.view_layer.update()
        evaluated = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
        try:
            check('bound native skin actually deforms', abs(evaluated.vertices[0].co.x - mesh.data.vertices[0].co.x - .03 / unit) < 1e-4)
        finally:
            mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
        apply(mesh, 'rig.unbind_armature')
        check('owned skin unbound', not any(m.type == 'ARMATURE' for m in mesh.modifiers))

        active(rig, 'POSE')
        rig = history(rig, 'Pose keyframe', lambda rig=rig: apply(rig, 'animation.pose_keyframe',
                      {'bone': 'Root', 'channel': 'location', 'frame': 4}), key_state)
        active(rig, 'POSE')
        apply(rig, 'animation.pose_keyframe_delete', {'bone': 'Root', 'channel': 'location', 'frame': 4})
        check('pose keyframe deleted', not any(c.keyframe_points for c in tools._action_curves(rig.animation_data.action)))

        obj = make()
        obj.keyframe_insert(data_path='location', frame=1)
        obj.location.x = .1 / unit
        obj.keyframe_insert(data_path='location', frame=10)
        original_action = obj.animation_data.action
        apply(obj, 'animation.interpolation', {'channel': 'location', 'interpolation': 'CONSTANT'})
        check('original action remains intact', all(k.interpolation == 'BEZIER' for c in tools._action_curves(original_action) for k in c.keyframe_points))
        obj = history(obj, 'Action interpolation', lambda obj=obj: apply(obj, 'animation.interpolation',
                      {'channel': 'location', 'interpolation': 'LINEAR', 'handle_type': 'VECTOR'}), key_state)
        # Shared object/data plus action metadata restores the original pointer and values.
        identity = Sync.object_id(obj)
        before_action, before_keys = obj.animation_data.action, key_state(obj)
        steps = [{'tool': 'animation.interpolation', 'target': identity}, {'tool': 'animation.frame_range', 'target': identity}]
        extra, baseline = tools.ExtraBackup(steps, editor), voice_sequence.Backup([obj])
        frame = (bpy.context.scene.frame_start, bpy.context.scene.frame_end, bpy.context.scene.render.fps)
        apply(obj, 'animation.interpolation', {'channel': 'location', 'interpolation': 'CONSTANT'})
        apply(obj, 'animation.frame_range', {'start': 4, 'end': 40, 'fps': 48})
        baseline.restore()
        extra.restore()
        baseline.close(restored=True)
        extra.close(restored=True)
        obj = Sync.find_object(identity)
        check('original action pointer and keys restored', obj.animation_data.action == before_action and key_state(obj) == before_keys)
        check('native timeline rollback', (bpy.context.scene.frame_start, bpy.context.scene.frame_end, bpy.context.scene.render.fps) == frame)
        range_start = bpy.context.scene.frame_start + 1
        obj = history(obj, 'Timeline range', lambda obj=obj, range_start=range_start: apply(obj, 'animation.frame_range', {'start': range_start, 'end': 33, 'fps': 50}),
                      lambda _: (bpy.context.scene.frame_start, bpy.context.scene.frame_end, bpy.context.scene.render.fps))

        for kind, tool, params, observe in (
            ('CAMERA', 'camera.settings', {'lens_mm': 70, 'ortho_scale_m': .4, 'clip_start_m': .01, 'clip_end_m': 100}, lambda o: (o.data.lens, o.data.ortho_scale)),
            ('LIGHT', 'light.settings', {'energy': 250, 'colour': [.1, .2, .3], 'radius_m': .02}, lambda o: (o.data.energy, tuple(o.data.color))),
            ('FONT', 'text.settings', {'body': 'Native VR text', 'size_m': .04, 'extrude_m': .002, 'bevel_depth_m': .001, 'align_x': 'CENTER'}, lambda o: (o.data.body, o.data.size, o.data.extrude))):
            obj = make(kind)
            obj = history(obj, tool, lambda obj=obj, tool=tool, params=params: apply(obj, tool, params), observe)
            if kind == 'FONT':
                check('text native metric size', abs(obj.data.size * unit - .04) < 1e-6)
                evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
                try:
                    check('text produces real native geometry', len(evaluated.vertices) > 0)
                finally:
                    obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()

        for kind, params in (('SIMPLE_DEFORM', {'method': 'TWIST', 'axis': 'Z', 'angle': .4}),
                             ('CAST', {'factor': .3}), ('DISPLACE', {'amount_m': .01}), ('EDGE_SPLIT', {'angle': .1})):
            obj = make()
            obj = history(obj, 'Deform ' + kind, lambda obj=obj, kind=kind, params=params: apply(obj, 'modifier.add_deform', {'kind': kind, **params}),
                          lambda o: [(m.name, m.type) for m in o.modifiers])
            check('real deform modifier exists', obj.modifiers[-1].type == kind)
        obj = make()
        obj.modifiers.new('Bevel', 'BEVEL')
        obj = history(obj, 'Configure modifier', lambda obj=obj: apply(obj, 'modifier.configure',
                      {'name': 'Bevel', 'width_m': .01, 'segments': 3, 'profile': .7}),
                      lambda o: (o.modifiers['Bevel'].width, o.modifiers['Bevel'].segments, o.modifiers['Bevel'].profile))
        check('modifier native metric width', abs(obj.modifiers['Bevel'].width * unit - .01) < 1e-6)
        try:
            apply(obj, 'modifier.configure', {'name': 'Bevel', 'ratio': .5})
            raise AssertionError('wrong modifier parameter admitted')
        except ValueError:
            check('wrong modifier property refused', obj.modifiers['Bevel'].segments == 3)
        obj = make()
        active(obj, 'EDIT')
        apply(obj, 'mesh.sculpt_mask', {'value': .7}, 'vertex', [0, 1])
        bm = bmesh.from_edit_mesh(obj.data)
        check('sculpt mask native attribute', abs(bm.verts[0][bm.verts.layers.float['.sculpt_mask']] - .7) < 1e-6)
        apply(obj, 'mesh.face_set', {'value': 4}, 'face', [0])
        bm = bmesh.from_edit_mesh(obj.data)
        check('face set native attribute', bm.faces[0][bm.faces.layers.int['.sculpt_face_set']] == 4)
        check('sculpt native freshness is serializable', len(tools.context_fingerprint()) == 64)

    check('all extended rig and scene tools executed', set(REPORT['tools']) == catalog.RIG_SCENE_OPERATIONS)
    REPORT['passed'] = True


def main():
    try:
        run()
    except Exception:
        REPORT['error'] = traceback.format_exc()
        raise
    finally:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(REPORT, indent=2), encoding='utf-8')
    print(json.dumps({'passed': REPORT['passed'], 'checks': len(REPORT['checks']), 'tools': len(set(REPORT['tools']))}), flush=True)


if __name__ == '__main__':
    main()

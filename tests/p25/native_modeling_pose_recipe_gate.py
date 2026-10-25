"""Production typed-voice Pose recipes in a disposable factory Blender only.

Uses the selected source tree's Voice -> Commands -> Editor route. Provider
output is fixed typed data; no microphone, Gemini request or listener is used.
"""

import argparse
import copy
import json
import os
import sys
import traceback
import uuid
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

parser = argparse.ArgumentParser()
parser.add_argument('--source-root', type=Path, required=True)
parser.add_argument('--source-commit', required=True)
parser.add_argument('--output', type=Path, required=True)
ARGS = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
sys.path.insert(0, str(ARGS.source_root / 'blender_addon'))
sys.dont_write_bytecode = True
from spatial_modeling import (
    commands,
    document,
    edits,
    host,
    leases,
    modeling_extras,
    modeling_recipe,
    modeling_tools,
    protocol,
    session,
    sync,
    voice_ops,
)

REPORT = {'passed': False, 'physical_acceptance': False, 'live_gemini_api': False,
          'blender': bpy.app.version_string, 'source_root': str(ARGS.source_root),
          'source_commit': ARGS.source_commit, 'checks': [], 'receipts': []}


def check(name, condition=True):
    assert condition, name
    REPORT['checks'].append(name)


def run():
    check('private factory process profiles', all(os.environ.get(key) for key in
          ('BLENDER_USER_CONFIG', 'BLENDER_USER_SCRIPTS', 'BLENDER_USER_DATAFILES', 'TEMP', 'TMP')))
    bpy.utils.keyconfig_init()
    from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active
    VIEW3D_PT_tools_active.register_ensure()
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.preferences.filepaths.temporary_directory = os.environ['TEMP']
    # The default Camera and Light deliberately remain to exercise full-scene
    # freshness, while the existing factory Cube is a prior-work sentinel.
    sentinel = bpy.context.active_object
    sentinel.location.x = .123
    data = bpy.data.armatures.new('Private production pose rig')
    rig = bpy.data.objects.new('Private production pose rig', data)
    bpy.context.scene.collection.objects.link(rig)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    root = data.edit_bones.new('Root')
    root.head, root.tail = (0, 0, 0), (0, .1, 0)
    tip = data.edit_bones.new('Tip')
    tip.head, tip.tail, tip.parent, tip.use_connect = root.tail, (0, .2, 0), root, True
    bpy.ops.object.mode_set(mode='OBJECT')
    for bone in rig.pose.bones:
        bone.rotation_mode = 'QUATERNION'
    doc = document.Document()
    sess = session.Session(sync.describe, sync.snapshot, uuid.uuid4().hex)
    sync.register()
    sync.start(doc, sess)
    sync.flush()
    rid, sentinel_id = sync.object_id(rig), sync.object_id(sentinel)
    voice = voice_ops.Voice(sync)
    editor = edits.Editor(sync, host.undoable, document=doc, voice=voice)
    lses = leases.Leases(sess, editor)
    cmds = commands.Commands(sess, editor, leases=lses)
    host._session, host._leases, host._commands = sess, lses, cmds

    class Connection:
        can_edit = True

        def __init__(self):
            self.sent = []

        def send(self, *messages):
            self.sent.extend(messages)

    conn = Connection()
    actor = {'actor_id': uuid.uuid4().hex, 'name': 'Private Pose recipe gate', 'role': 'vr'}
    sess.participants[conn] = actor
    sess.store.join(actor)
    area = next(a for a in bpy.context.window.screen.areas if a.type == 'VIEW_3D')
    override = {'window': bpy.context.window, 'area': area,
                'region': next(r for r in area.regions if r.type == 'WINDOW')}

    def target():
        return sync.find_object(rid)

    def state():
        current = target()
        current.update_tag(refresh={'OBJECT', 'DATA'})
        bpy.context.view_layer.update()
        action = current.animation_data.action if current.animation_data else None
        return {'bones': [(b.name, list(b.location), list(b.rotation_quaternion), list(b.scale),
                           b.select, [list(row) for row in b.matrix]) for b in current.pose.bones],
                'active_bone': current.data.bones.active.name if current.data.bones.active else None,
                'keys': [] if action is None else [(c.data_path, c.array_index,
                           [(list(k.co), k.interpolation) for k in c.keyframe_points])
                          for c in modeling_extras._action_curves(action)],
                'actions': sorted(a.name for a in bpy.data.actions),
                'sentinel': list(sync.find_object(sentinel_id).location), 'mode': bpy.context.mode}

    def command(op, arguments=None, expected='applied'):
        lease = lses.grant(actor['actor_id'], 'exclusive')
        try:
            native = sess.document()
            payload = {'session_id': sess.session_id, 'host_epoch': sess.host_epoch,
                       'document_id': native['id'], 'open_epoch': native['open_epoch'],
                       'actor_id': actor['actor_id'], 'base_revision': sync.flush(),
                       'source': 'voice', 'op': op, 'args': arguments or {}, 'lease': lease['lease_id']}
            if op == 'voice.run':
                payload['target'] = {'id': rid, 'generation': sync.generation(rid)}
            immediate = cmds.command(protocol.message('command', payload), conn)
            result = immediate or conn.sent[-1]
            assert result['type'] == 'result', result
            receipt = result['payload']
            assert receipt['outcome'] == expected, receipt
            REPORT['receipts'].append({'op': op, 'outcome': receipt['outcome'],
                                       'selection': receipt.get('selection'), 'error': receipt.get('error')})
            return receipt
        finally:
            lses.end(lease['lease_id'], actor['actor_id'])

    def step(sid, tool, params):
        return {'id': sid, 'tool': tool, 'params': params, 'selection': 'captured', 'target': 'selected'}

    def prepare(steps, decision='run'):
        before = state()
        context = modeling_recipe.capture_context(sync)
        context.pop('model', None)
        context['selection'] = copy.deepcopy(context.get('native_selection', {}))
        context['selection']['objects'] = [{'id': rid, 'generation': sync.generation(rid)}]
        response = voice.on_resolve(protocol.message('voice.resolve', {
            'text': 'Pose the selected rig and insert a keyframe', 'confidence': 1,
            'composition': True, 'recipe': {'decision': 'propose', 'steps': steps},
            'context': context}), conn)
        result = response['payload']
        assert response['type'] == 'voice.candidates' and result['decision'] == decision, result
        check('whole Pose recipe preflight leaves native state unchanged', state() == before)
        if decision == 'run':
            assert result['candidates'][0]['requires_confirmation'] is True
        else:
            assert result['candidates'] == []
        return result

    def execute(plan, expected='applied'):
        return command('voice.run', {'resolution': plan['resolution'], 'choice': 1}, expected)

    try:
        with bpy.context.temp_override(**override):
            bpy.ops.object.mode_set(mode='POSE')
            bpy.ops.wm.tool_set_by_id(name='builtin.move')
            for bone in target().pose.bones:
                bone.select = bone.name == 'Root'
            target().data.bones.active = target().data.bones['Root']
            sync.flush()
            bpy.ops.ed.undo_push(message='Private native Pose initial state')
            initial = state()

            def prior_work():
                target().pose.bones['Root'].location = (.007, 0, 0)
                bpy.context.view_layer.update()
            host.undoable('Private prior native Pose edit')(prior_work)()
            sync.flush()
            before = state()
            check('prior native pose work exists', before != initial)
            q = list(Quaternion((0, 0, 1), .35))
            recipe = [step('move_root', 'rig.pose_transform', {'bone': 'Root', 'location_m': [.02, 0, 0]}),
                      step('key_root', 'animation.pose_keyframe', {'bone': 'Root', 'channel': 'location', 'frame': 10}),
                      step('rotate_tip', 'rig.pose_transform', {'bone': 'Tip', 'rotation': q})]
            plan = prepare(recipe)
            sent_start, original_apply = len(conn.sent), modeling_tools.apply_step
            kernels = []

            def traced(*args, **kwargs):
                result = original_apply(*args, **kwargs)
                kernels.append(args[2])
                assert not [m for m in conn.sent[sent_start:] if m['type'] == 'scene.update'], 'Published partial Pose recipe'
                return result
            modeling_tools.apply_step = traced
            try:
                receipt = execute(plan)
            finally:
                modeling_tools.apply_step = original_apply
            after = state()
            check('actual Voice Commands Editor Pose kernels execute in order', kernels == [s['tool'] for s in recipe])
            check('Pose recipe changes native channels and inserts actual keys',
                  (target().pose.bones['Root'].location - Vector((.02, 0, 0))).length < 1e-7
                  and abs(target().pose.bones['Tip'].rotation_quaternion.dot(Quaternion(q))) > .99999 and len(after['keys']) == 3)
            check('Pose receipt selects actual final target and stays in Pose mode', receipt['selection']['id'] == rid and bpy.context.mode == 'POSE')
            command('history.undo')
            check('one production Undo exactly restores pose and keys preserving prior work', state() == before)
            command('history.undo')
            check('previous native history remains separately undoable', state() == initial)
            command('history.redo')
            check('previous native history remains separately redoable', state() == before)
            command('history.redo')
            check('one production Redo exactly restores whole Pose recipe', state() == after)

            # A locked final step refuses the complete request during review.
            target().pose.bones['Tip'].lock_rotation = (True, False, False)
            locked_before = state()
            refused = prepare(recipe, 'reject')
            check('locked channel refuses entire valid-prefix Pose request', 'locked' in refused['reason'].lower() and state() == locked_before)
            target().pose.bones['Tip'].lock_rotation = (False, False, False)

            # A native lock change after review is a freshness failure even
            # though it does not advance the streamed geometry revision.
            plan = prepare(recipe)
            revision = sync.flush()
            target().pose.bones['Tip'].lock_rotation = (True, False, False)
            assert sync.flush() == revision
            refused = execute(plan, 'rejected')
            check('Pose lock change invalidates reviewed plan without geometry revision', refused['error']['code'] == 'stale_revision')
            target().pose.bones['Tip'].lock_rotation = (False, False, False)

            # Force a late native failure after channel and Action changes.
            failing = [step('move_root', 'rig.pose_transform', {'bone': 'Root', 'location_m': [.06, 0, 0]}),
                       step('key_root', 'animation.pose_keyframe', {'bone': 'Root', 'channel': 'location', 'frame': 22}),
                       step('rotate_tip', 'rig.pose_transform', {'bone': 'Tip', 'rotation': list(Quaternion((0, 0, 1), .8))})]
            plan, rollback_before = prepare(failing), state()
            sent_start, original_apply = len(conn.sent), modeling_tools.apply_step
            calls = []

            def fail_late(*args, **kwargs):
                calls.append(args[2])
                if len(calls) == 3:
                    raise ValueError('Private injected final Pose kernel failure')
                return original_apply(*args, **kwargs)
            modeling_tools.apply_step = fail_late
            try:
                refused = execute(plan, 'rejected')
            finally:
                modeling_tools.apply_step = original_apply
            check('late Pose failure rolls back channels actions keys selection and native Pose mode',
                  refused['error']['code'] == 'failed' and len(calls) == 3 and state() == rollback_before)
            check('rejected Pose recipe publishes no valid prefix',
                  not [m for m in conn.sent[sent_start:] if m['type'] == 'scene.update'])
            check('prior unrelated native object retained', list(sync.find_object(sentinel_id).location) == list(Vector((.123, 0, 0))))
            REPORT['passed'] = True
    finally:
        sync.unregister()


def entry():
    try:
        run()
    except Exception:  # noqa: BLE001 - always preserve factory-process failure evidence
        REPORT['error'] = traceback.format_exc()
        traceback.print_exc()
    finally:
        ARGS.output.parent.mkdir(parents=True, exist_ok=True)
        ARGS.output.write_text(json.dumps(REPORT, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': REPORT['passed'], 'checks': len(REPORT['checks'])}), flush=True)
        bpy.ops.wm.quit_blender()


if bpy.app.background:
    entry()
else:
    bpy.app.timers.register(entry, first_interval=1.0)

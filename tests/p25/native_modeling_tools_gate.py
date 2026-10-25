"""Factory-only native modeling checks, with private files and no runtime input."""

import json
import sys
import traceback
import uuid
from pathlib import Path

import bmesh
import bpy
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender_addon"))
from spatial_modeling import edits, host
from spatial_modeling import modeling_mesh as kernels
from spatial_modeling import modeling_tools as tools

OUT = Path(sys.argv[sys.argv.index('--output')+1]) if '--output' in sys.argv else ROOT/'acceptance/native-modeling.json'
REPORT = {"blender": bpy.app.version_string, "checks": [], "passed": False, "physical_acceptance": False}


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


def fresh(component='face', scale=1):
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for item in list(bpy.data.objects):
        bpy.data.objects.remove(item, do_unlink=True)
    mesh = bpy.data.meshes.new('Private mesh')
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=.2/scale)
    uv = bm.loops.layers.uv.new('UVMap')
    for face in bm.faces:
        for loop in face.loops:
            loop[uv].uv = (loop.vert.co.x, loop.vert.co.y)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new('Private mesh', mesh)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    obj['spatial_modeling_id'] = uuid.uuid4().hex
    bpy.context.scene.unit_settings.scale_length = scale
    bpy.context.tool_settings.mesh_select_mode = tuple(c == component for c in ('vertex','edge','face'))
    bpy.ops.object.mode_set(mode='EDIT')
    return obj


def counts(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    return len(bm.verts), len(bm.edges), len(bm.faces)


def run():
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.preferences.filepaths.temporary_directory = str(OUT.parent)
    cases = [
        ('mesh.extrude', 'face', [0], {'translation_m':[0,0,.02]}),
        ('mesh.extrude', 'face', [0], {'translation_m':[0,0,0],'individual':True,'normal_distance_m':.02}),
        ('mesh.extrude', 'face', list(range(6)), {'translation_m':[0,0,0],'individual':True,'normal_distance_m':.02}),
        ('mesh.inset', 'face', [0], {'thickness_m':.01}),
        ('mesh.inset', 'face', [0,1], {'thickness_m':.01,'individual':True}),
        ('mesh.bevel', 'edge', [0], {'width_m':.01,'segments':3}),
        ('mesh.bevel', 'vertex', [0], {'width_m':.01,'segments':2,'vertices':True}),
        ('mesh.bevel', 'face', [0], {'width_m':.01,'segments':2,'vertices':False}),
        ('mesh.loop_cut', 'edge', [0], {'cuts':2,'slide':.2}),
        ('mesh.merge', 'vertex', [0,1], {'variant':'CENTER'}),
        ('mesh.merge', 'vertex', [0,1], {'variant':'LAST'}),
        ('mesh.dissolve', 'edge', [0], {}),
        ('mesh.delete', 'face', [0], {'domain':'ONLY_FACE'}),
        ('mesh.subdivide', 'edge', [0,1], {'cuts':2}),
        ('mesh.triangulate', 'face', [0], {}),
        ('mesh.split_edges', 'edge', [0], {}),
        ('mesh.recalculate_normals', 'face', [0], {}),
        ('mesh.flip_normals', 'face', [0], {}),
        ('mesh.face_smooth', 'face', [0], {'smooth':True}),
        ('mesh.edge_seam', 'edge', [0], {'seam':True}),
        ('mesh.edge_properties', 'edge', [0], {'sharp':True,'crease':.7,'bevel_weight':.3}),
        ('mesh.select_region', 'face', [0], {'region':'BOUNDARY'}),
        ('mesh.bisect', 'face', list(range(6)), {'plane_point_m':[0,0,0], 'plane_normal':[1,0,0]}),
        ('mesh.spin', 'edge', [0], {'center_m':[0,0,0], 'axis':[0,0,1], 'angle':.4,'steps':3}),
    ]
    for unit in (1, .001):
        for tool, component, indices, params in cases:
            obj = fresh(component, unit)
            before = counts(obj)
            result = tools.apply_step(editor,obj,tool,params,{'component':component,'indices':indices})
            after = counts(obj)
            bm = bmesh.from_edit_mesh(obj.data)
            assert bm.loops.layers.uv.get('UVMap') is not None, tool
            assert all('id' in value for value in result['outputs'].values()), (tool,result)
            if tool == 'mesh.extrude':
                assert all(len(e.link_faces) == 2 for e in bm.edges), 'extrusion must retain a manifold closed cube'
            if tool == 'mesh.loop_cut':
                assert after[0] == 16 and after[2] == 14, after
                assert result['selection']['indices'], result
            REPORT['checks'].append({'tool':tool,'unit':unit,'before':before,'after':after})
        obj=fresh('vertex',unit)
        bm=bmesh.from_edit_mesh(obj.data); kernels.index(bm)
        before=[v.co.copy() for v in bm.verts]
        tools.apply_step(editor,obj,'mesh.translate',{'translation_m':[.01,0,0],
            'proportional_radius_m':.3,'proportional_falloff':'SMOOTH','connected':True},
            {'component':'vertex','indices':[0]})
        bm=bmesh.from_edit_mesh(obj.data); kernels.index(bm)
        assert (bm.verts[0].co-before[0]-Vector((.01/unit,0,0))).length < 1e-5
        assert any((bm.verts[i].co-before[i]).length > 1e-5 for i in range(1,len(before)))
        REPORT['checks'].append({'tool':'native_proportional_translate','unit':unit})
        obj=fresh('vertex',unit)
        bm=bmesh.from_edit_mesh(obj.data); kernels.index(bm); before=bm.verts[0].co.copy()
        tools.apply_step(editor,obj,'mesh.translate',{'translation_m':[.012,.017,0],
            'constraint_axis':[True,False,False],'snap_increment_m':.01}, {'component':'vertex','indices':[0]})
        bm=bmesh.from_edit_mesh(obj.data); kernels.index(bm)
        assert abs(bm.verts[0].co.y-before.y)<1e-5
        REPORT['checks'].append({'tool':'axis_grid_snap','unit':unit})
        for behavior, extra in [
            ('axis_grid', {'constraint_axis':[True,False,False],'snap_increment_m':.01}),
            ('surface_target', {'snap_point_m':[.3,.2,.1]}),
            ('proportional', {'proportional_radius_m':.4,'connected':True}),
        ]:
            obj=fresh('face',unit)
            bm=bmesh.from_edit_mesh(obj.data);kernels.index(bm)
            original=[v.co.copy() for v in bm.verts]
            center=bm.faces[0].calc_center_median().copy()*unit
            result=tools.apply_step(editor,obj,'mesh.extrude',{'translation_m':[.013,.017,0],**extra},
                {'component':'face','indices':[0]})
            bm=bmesh.from_edit_mesh(obj.data);kernels.index(bm)
            cap=bm.faces[result['selection']['indices'][0]].calc_center_median()*unit
            if behavior=='axis_grid':assert (cap-center-Vector((.01,0,0))).length<2e-6
            elif behavior=='surface_target':assert (cap-Vector((.3,.2,.1))).length<2e-6
            else:assert any((bm.verts[i].co-original[i]).length*unit>1e-6 for i in range(8))
            REPORT['checks'].append({'tool':'extrude_native_'+behavior,'unit':unit})
        obj=fresh('vertex',unit)
        bm=bmesh.from_edit_mesh(obj.data); kernels.index(bm); before=bm.verts[0].co.copy()
        turn=Quaternion(Vector((1,2,3)).normalized(),.4)
        preset=bpy.context.scene.transform_orientation_slots[0].type
        tools.apply_step(editor,obj,'mesh.rotate',{'rotation':list(turn),'pivot_m':[0,0,0]}, {'component':'vertex','indices':[0]})
        bm=bmesh.from_edit_mesh(obj.data); kernels.index(bm)
        assert (bm.verts[0].co-turn@before).length*unit<2e-6
        assert bpy.context.scene.transform_orientation_slots[0].type==preset
        REPORT['checks'].append({'tool':'arbitrary_world_rotation_native_frame_restored','unit':unit})
        bpy.ops.object.mode_set(mode='OBJECT')
        obj.rotation_euler=(.3,.2,.1);bpy.context.view_layer.update()
        tools.apply_step(editor,obj,'object.translate',{'translation_m':[0,0,0],
            'snap_point_m':[1,2,3],'snap_normal':[0,1,0],'snap_align_rotation':True}, {'component':'object','indices':[]})
        assert (obj.matrix_world.translation*unit-Vector((1,2,3))).length<2e-6
        assert ((obj.matrix_world.to_3x3()@Vector((0,0,1))).normalized()-Vector((0,1,0))).length<2e-6
        REPORT['checks'].append({'tool':'native_face_snap_alignment','unit':unit})
        twin=obj.copy();twin.data=obj.data.copy();twin['spatial_modeling_id']=uuid.uuid4().hex
        bpy.context.collection.objects.link(twin);twin.select_set(True)
        twin.location.x+=.2/unit;bpy.context.view_layer.update()
        first,second=obj.matrix_world.translation.copy(),twin.matrix_world.translation.copy()
        ids=[obj['spatial_modeling_id'],twin['spatial_modeling_id']]
        tools.apply_live(editor,{'tool':'object.translate','targets':ids,'selection':{'component':'object','indices':[]}},
            {'per_target':{ids[0]:{'translation_m':[.02,0,0],'pivot_m':[0,0,0]},
                           ids[1]:{'translation_m':[0,.03,0],'pivot_m':[0,0,0]}}})
        assert (obj.matrix_world.translation-first-Vector((.02/unit,0,0))).length*unit<2e-6
        assert (twin.matrix_world.translation-second-Vector((0,.03/unit,0))).length*unit<2e-6
        assert obj.select_get() and twin.select_get()
        REPORT['checks'].append({'tool':'multiobject_per_target_changes_once_preserve_native_selection','unit':unit})
    REPORT['passed']=True


def main():
    OUT.parent.mkdir(parents=True,exist_ok=True)
    try:
        run()
    except Exception:
        REPORT['error']=traceback.format_exc()
        raise
    finally:
        OUT.write_text(json.dumps(REPORT,indent=2),encoding='utf-8')
    print(json.dumps(REPORT),flush=True)


if __name__=='__main__':
    main()

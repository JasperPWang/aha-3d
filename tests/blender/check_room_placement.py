"""Actual evaluated Blender collision/support/physics regressions and saved fixture."""
import argparse
import json
from pathlib import Path
import sys
import unittest

import bpy
import numpy as np
from mathutils import Matrix
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from aha3d.blender.placement_check import check, discover, inside
from aha3d.placement.config import normalize
from aha3d.placement.report import write_report


def root(name,role='prop',support=None):
    obj=bpy.data.objects.new(name,None); bpy.context.scene.collection.objects.link(obj)
    obj['instance_id']=name; obj['semantic_class']=role
    if support: obj['support_id']=support
    return obj


def box(name,loc,size,parent=None):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc)
    obj=bpy.context.object; obj.name=name; obj.scale=size
    if parent: obj.parent=parent
    return obj


def fixture():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    floor=root('floor','floor');box('floor slab',(0,0,-.1),(10,10,.2),floor)
    table=root('table','table', 'floor')
    box('tabletop',(0,0,1),(2,2,.1),table)
    for x in (-.85,.85):
        for y in (-.85,.85): box('leg',(x,y,.475),(.1,.1,.95),table)
    chair=root('chair','prop','floor');box('seat under table',(0,0,.35),(.6,.6,.7),chair)
    cube=root('supported','prop','table');box('supported cube',(0,0,1.15),(.2,.2,.2),cube)
    bpy.context.scene.frame_set(1);bpy.context.view_layer.update()


class Checks(unittest.TestCase):
    def setUp(self): fixture()
    def test_rotated_beveled_baseboard_containment(self):
        # A ray can re-hit the same bevel triangle because BVH coordinates are
        # float32. This outside point used to be reported 27.6 mm inside.
        from aha3d.blender.roomkit import box as room_box
        bpy.ops.wm.read_factory_settings(use_empty=True)
        ob=room_box('Baseboard',(3.415,1.,.06),(.065,4.6,.10),edge=.004)
        rotation=Matrix(((.8331258114970213,-.5530835219181907,0,0),
                         (.5530835219181907,.8331258114970213,0,0),
                         (0,0,1,0),(0,0,0,1)))
        bpy.context.view_layer.update(); ob.matrix_world=rotation@ob.matrix_world
        objects,_=discover(bpy.context.scene,normalize({'physics':'off'}),[])
        part=objects[0]['parts'][0]
        outside=np.array([1.8962686039495742,3.2094800581489844,.05999999865889549])
        self.assertFalse(inside(part,outside))
        center=np.array(rotation)[:3,:3]@np.array([3.415,1.,.06])
        self.assertTrue(inside(part,center))
    def test_valid_contacts_and_table_cavity(self):
        report=check({'physics':'off'})
        self.assertFalse([i for i in report['issues'] if i['code'] in ('penetration','surface_overlap','support_gap')],report['issues'])
        self.assertEqual(next(o for o in report['objects'] if o['id']=='supported')['support']['target'],'table')
    def test_floating_and_wall_penetration(self):
        bpy.data.objects['supported'].location.z=.2
        wall=root('wall','wall');box('wall slab',(3,0,1),(.2,3,2),wall)
        wrong=root('bad-cabinet','prop','floor');box('cabinet',(3,0,.5),(.5,.5,1),wrong)
        report=check({'physics':'off'})
        self.assertTrue(any(i['code']=='support_gap' and 'supported' in i['objects'] for i in report['issues']))
        self.assertTrue(any(i['code']=='penetration' and 'wall' in i['objects'] for i in report['issues']),report['issues'])
    def test_containment_without_triangle_crossing(self):
        outer=root('solid','prop');box('solid block',(3,0,1),(2,2,2),outer)
        inner=root('embedded','prop');box('embedded block',(3,0,1),(.2,.2,.2),inner)
        report=check({'physics':'off'})
        self.assertTrue(any(i['code']=='penetration' and set(i['objects'])=={'solid','embedded'} for i in report['issues']))
    def test_duplicate_ids_and_bad_overrides_fail(self):
        with self.assertRaises(ValueError):check({'physics':'off','objects':{'typo':{'fixed':True}}})
        bpy.data.objects['supported']['instance_id']='chair'
        with self.assertRaises(ValueError):check({'physics':'off'})
    def test_hidden_and_collection_instance(self):
        hidden=root('hidden');box('hidden cube',(0,0,1),(.5,.5,.5),hidden);hidden.hide_render=True
        coll=bpy.data.collections.new('instance geometry')
        cube=box('instance cube',(0,0,0),(.2,.2,.2))
        for c in list(cube.users_collection):c.objects.unlink(cube)
        coll.objects.link(cube)
        inst=bpy.data.objects.new('instanced',None);bpy.context.scene.collection.objects.link(inst)
        inst.instance_type='COLLECTION';inst.instance_collection=coll;inst.location=(3,2,.1)
        inst['instance_id']='instanced';inst['semantic_class']='prop'
        report=check({'physics':'off'})
        self.assertNotIn('hidden',{o['id'] for o in report['objects']})
        row=next(o for o in report['objects'] if o['id']=='instanced')
        self.assertAlmostEqual(row['min'][0],2.9,places=5)
    def test_physics_stable_and_dropping(self):
        bpy.data.objects['supported'].location.z=.2
        bpy.context.view_layer.update();scene=bpy.context.scene;before={o.name:o.matrix_world.copy() for o in scene.objects}
        report=check({'simulation_seconds':1.})
        self.assertEqual(report['coverage']['physics']['status'],'completed',report['coverage']['physics'])
        self.assertTrue(any(i['code']=='unstable' and i['objects']==['supported'] for i in report['issues']),report['issues'])
        self.assertFalse(any(i['code']=='unstable' and i['objects']==['chair'] for i in report['issues']),report['issues'])
        self.assertEqual(scene,bpy.context.scene)
        for name,matrix in before.items():self.assertEqual(matrix,bpy.data.objects[name].matrix_world)
    def test_architectural_seams_keep_furniture_obstacles(self):
        wall=root('wall','wall');box('wall slab',(3,0,1),(.2,3,2),wall)
        box('Wall molding',(3,0,1),(.3,1,1))
        obj=root('bad-furniture');box('penetrating',(3,0,1),(.5,.5,.5),obj)
        report=check({'physics':'off'})
        self.assertFalse(any(i['code']=='penetration' and set(i['objects'])=={'wall','object:Wall molding'} for i in report['issues']))
        self.assertTrue(any(i['code']=='penetration' and 'bad-furniture' in i['objects'] for i in report['issues']))
    def test_overhanging_center_of_mass_tips(self):
        o=bpy.data.objects['supported'];o.location=(1.1,0,0)
        body=bpy.data.objects['supported cube'];body.scale=(.8,.4,.4);body.location.z=1.25
        report=check({'simulation_seconds':2.})
        self.assertTrue(any(i['code']=='unstable' and i['objects']==['supported'] for i in report['issues']),report['issues'])
    def test_baked_person_is_excluded_from_room_collisions(self):
        person=root('Person_001_Placement')
        body=box('Person_001_Body',(0,0,.8),(1,1,1.6),person);body['person_id']=1
        report=check({'physics':'off'})
        self.assertEqual(next(o for o in report['objects'] if o['id']==person['instance_id'])['role'],'person')
        self.assertFalse(any(i['code']=='penetration' and 'Person_001_Placement' in i['objects'] for i in report['issues']))
    def test_open_surface_is_not_certified(self):
        obj=root('open');bpy.ops.mesh.primitive_plane_add(size=1,location=(3,0,1));bpy.context.object.parent=obj
        report=check({'physics':'off'})
        self.assertTrue(any(i['code']=='open_geometry' for i in report['issues']))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    out=p.parse_args(sys.argv[sys.argv.index('--')+1:]).out;out.mkdir(parents=True,exist_ok=True)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    (out/'tests.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,failures=[str(t) for t,_ in result.failures],errors=[str(t) for t,_ in result.errors]),indent=2))
    if not result.wasSuccessful():raise RuntimeError('Placement regression failed')
    fixture();bpy.data.objects['supported'].location.z=.2
    wall=root('wall','wall');box('wall slab',(3,0,1),(.2,3,2),wall)
    wrong=root('bad-cabinet','prop','floor');box('cabinet',(3,0,.5),(.5,.5,1),wrong)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'fixture.blend'))

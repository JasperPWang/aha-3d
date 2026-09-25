"""Shared placement and transform-only preflight; no rendering or inference."""
import argparse
import json
import math
from pathlib import Path
import sys
import unittest
import bpy
from mathutils import Vector, Matrix
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'src'))
from aha3d.blender.roomkit import cabinet, place_root, place_asset, configure_render
from aha3d.blender.orientation import (tag_orientation, facing_report,
    scene_facing_report, world_front)
from aha3d.orientation import authored_orientation


def make(name, metadata=True):
    o=bpy.data.objects.new(name,None);bpy.context.scene.collection.objects.link(o)
    o['instance_id']=name;o['semantic_class']='chair'
    if metadata:tag_orientation(o,authored_orientation('seating',evidence='Synthetic -Y facing root'))
    return o


class Checks(unittest.TestCase):
    def setUp(self):bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_missing_metadata_and_intent_are_not_passes(self):
        make('unknown',False);make('no-target')
        r=scene_facing_report(bpy.context.scene)
        self.assertEqual({x['instance_id']:x['status'] for x in r['issues']},
                         {'unknown':'unverified','no-target':'no_target'})

    def test_reversed_cabinet_and_post_parenting(self):
        parent=make('room',False);parent['semantic_class']='room'
        parent.location=(3,4,0);parent.rotation_euler.z=.8;parent.scale=(1.3,)*3
        o,controls=cabinet('test',layout={'columns':[{'sections':[{'front':'double_door'}]}]})
        o.parent=parent;bpy.context.view_layer.update()
        before=[c.matrix_local.copy() for c in controls];origin=o.matrix_world.translation.copy()
        place_root(o,facing_direction=(-1,0,0))
        self.assertLess((world_front(o)-Vector((-1,0,0))).length,1e-5)
        self.assertLess((o.matrix_world.translation-origin).length,1e-5)
        for c,m in zip(controls,before):
            self.assertLess(max(abs(c.matrix_local[i][j]-m[i][j]) for i in range(4) for j in range(4)),1e-5)
        o.rotation_euler.z+=math.pi
        r=scene_facing_report(bpy.context.scene)
        issue=next(i for i in r['issues'] if i['instance_id']==o['instance_id'])
        self.assertEqual(issue['status'],'fail');self.assertGreater(issue['error_degrees'],179.9)

    def test_source_skew_translation_and_reopen(self):
        o=make('skew');d=(math.cos(.37),math.sin(.37),0)
        place_root(o,location=(1,2,.4),facing_direction=d)
        o.location.x+=5;bpy.context.view_layer.update()
        self.assertEqual(facing_report(o)['status'],'pass')
        file=OUT/'skew.blend';bpy.ops.wm.save_as_mainfile(filepath=str(file))
        bpy.ops.wm.open_mainfile(filepath=str(file));o=bpy.data.objects['skew']
        self.assertLess((world_front(o)-Vector(d)).length,1e-5)
        self.assertEqual(facing_report(o)['status'],'pass')

    def test_bad_request_does_not_mutate_root(self):
        o=make('test');place_root(o,facing_direction=(1,0,0))
        before=o.matrix_world.copy();relation=o['facing_target_json']
        for kwargs in [dict(facing_direction=(0,0,0)),dict(facing_target=(2,3,0),facing_direction=(1,0,0)),
                       dict(facing_target=(2,3,0)),dict(facing_direction=(1,0,1))]:
            with self.assertRaises(ValueError):place_root(o,location=(2,3,0),**kwargs)
            self.assertEqual(o.matrix_world,before);self.assertEqual(o['facing_target_json'],relation)

    def test_registered_and_generated_entry(self):
        tap=place_asset('faucet-simple-v1/faucet-simple-gooseneck',location=(1,2,1),
                        facing_direction=(-1,0,0),project_root=R)
        self.assertLess((world_front(tap)-Vector((-1,0,0))).length,1e-5)
        r=scene_facing_report(bpy.context.scene)
        self.assertEqual(r['checked'],1);self.assertEqual(r['counts']['pass'],1)
        for layout in [None,{'columns':[{'sections':[{'front':'double_door'}]}]}]:
            o,controls=cabinet('cab',location=(3,2,0),layout=layout,facing_target=(2,2,0))
            self.assertEqual(facing_report(o)['status'],'pass')
            self.assertTrue(all(c.get('roomkit_open_property') for c in controls))
        count=len(bpy.data.objects)
        with self.assertRaises(ValueError):cabinet('invalid',facing_target=(0,0,0))
        self.assertEqual(len(bpy.data.objects),count)

    def test_render_configuration_emits_exceptions_without_changing_signature(self):
        o=make('test');place_root(o,facing_direction=(1,0,0));o.rotation_euler.z+=math.pi
        first=configure_render(bpy.context.scene)
        report=json.loads(bpy.context.scene['facing_preflight_json'])
        self.assertEqual(report['issues'][0]['status'],'fail')
        second=configure_render(bpy.context.scene)
        self.assertEqual(first,second)  # Timings must not invalidate render receipts.

    def test_malformed_relation_does_not_abort_other_checks(self):
        bad=make('bad');bad['facing_target_json']='not json'
        good=make('good');place_root(good,facing_direction=(1,0,0))
        report=scene_facing_report(bpy.context.scene)
        self.assertEqual(report['counts']['invalid'],1);self.assertEqual(report['counts']['pass'],1)

    def test_target_lookup_uses_requested_scene(self):
        scene=bpy.context.scene;o=make('chair');target=make('target',False);target.location=(1,0,0)
        place_root(o,facing_target=target)
        other=bpy.data.scenes.new('other');bpy.context.window.scene=other
        self.assertEqual(scene_facing_report(scene)['counts']['pass'],1)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    OUT=p.parse_args(sys.argv[sys.argv.index('--')+1:]).out;OUT.mkdir(parents=True,exist_ok=True)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    (OUT/'results.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,
        failures=[str(t) for t,_ in result.failures],errors=[str(t) for t,_ in result.errors]),indent=2))
    if not result.wasSuccessful():raise RuntimeError('Facing preflight checks failed')

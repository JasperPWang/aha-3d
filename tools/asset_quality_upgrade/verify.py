"""Verify every registered model through real independent import and reopen.

Run in background Blender. This checks geometry, identity and
independent native cabinet controls; it makes no physics or photorealism claim.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    import bpy
    from aha3d.blender.roomkit import place_asset, cabinet_controls, set_open
    from aha3d.blender.semantics import descendants
    from aha3d.blender.variants import apply_variant, _bounds
    from integrate import assert_portable, digest, write
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.out.mkdir(parents=True, exist_ok=True)
    entries = [e for e in json.loads((ROOT/'assets/index.json').read_text())['entries'] if e['kind']=='collection']
    report = {'schema_version':1,'job_id':os.environ.get('INDOOR_RUN_ID'), 'blender':bpy.app.version_string,
              'registry_sha256':digest(ROOT/'assets/registry.json'),'models':[], 'physics':'not tested'}
    for index, card in enumerate(entries):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        first = place_asset(card['id'],instance_id='quality-first',project_root=ROOT)
        second = place_asset(card['id'],location=(3,0,0),rotation=37,instance_id='quality-second',project_root=ROOT)
        tree1, tree2 = set(descendants(first)), set(descendants(second))
        assert not tree1 & tree2, card['id']
        assert first['asset_id']==second['asset_id']==card['id']
        initial = _bounds(first)
        before = tuple(float(x) for x in first.matrix_world.translation)
        joints = []
        if card.get('articulation'):
            controls1, controls2 = cabinet_controls(first), cabinet_controls(second)
            assert controls1 and controls2 and not set(controls1) & set(controls2)
            def evaluated_matrices(objects):
                graph=bpy.context.evaluated_depsgraph_get()
                return {o.name:tuple(x for row in o.evaluated_get(graph).matrix_world for x in row)
                        for o in objects if o.type=='MESH'}
            closed_first,closed_second=evaluated_matrices(tree1),evaluated_matrices(tree2)
            set_open(first,.7)
            bpy.context.scene.frame_set(bpy.context.scene.frame_current)
            opened_first,opened_second=evaluated_matrices(tree1),evaluated_matrices(tree2)
            assert any(max(abs(a-b) for a,b in zip(closed_first[n],opened_first[n]))>1e-4
                       for n in closed_first),'First cabinet drivers did not move geometry'
            assert opened_second==closed_second,'First cabinet moved the second cabinet'
            for control in controls2:
                prop = control.get('roomkit_open_property','Open')
                assert abs(control[prop]) < 1e-7, card['id']
            joints = [c.get('joint_id',c.name) for c in controls1]
            set_open(first,0)
            bpy.context.scene.frame_set(bpy.context.scene.frame_current)
            restored=evaluated_matrices(tree1)
            assert all(max(abs(a-b) for a,b in zip(closed_first[n],restored[n]))<1e-6 for n in closed_first)
        else:
            replacement = apply_variant({'schema_version':1,'models':[{'selector':{'instance_ids':['quality-first']},
                'asset_id':card['id'],'fit':'native'}]},project_root=ROOT)
            assert len(replacement['models'])==1
            assert tuple(float(x) for x in first.matrix_world.translation)==before
            assert _bounds(first)==initial,card['id']
        assert_portable()
        save = args.out/(card['id'].replace('/','__')+'.blend')
        bpy.context.preferences.filepaths.save_version=0
        bpy.ops.wm.save_as_mainfile(filepath=str(save))
        bpy.ops.wm.open_mainfile(filepath=str(save))
        slots = {o.get('instance_id'):o for o in bpy.context.scene.objects if o.get('instance_id')}
        assert set(slots)=={'quality-first','quality-second'},card['id']
        assert slots['quality-first']['asset_id']==card['id']
        assert_portable()
        report['models'].append({'asset_id':card['id'],'status':'passed','independent_instances':2,
             'registered_replacement':'passed' if not card.get('articulation') else 'native control independence checked',
             'reopen':'passed','joints':joints})
        write(args.out/'report.json',report)
        save.unlink()  # Validation fixture; no permanent duplicate asset inventory.
        print('VERIFIED',index+1,len(entries),card['id'],flush=True)
    report['status']='passed';write(args.out/'report.json',report)


if __name__=='__main__':
    main()

"""Refresh explicitly identified static scene assets from the current registry.

No name-based object classification is performed. Use --audit to list eligible
and protected semantic slots; use --out to save the refreshed scene separately.
Legacy loose parts still require an explicit reviewed semantic migration.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))


def inspect_scene(asset_ids):
    from aha3d.blender.semantics import roots
    from aha3d.blender.variants import plan_variant
    import bpy
    from integrate import slot_signature
    cards={e['id']:e for e in json.loads((ROOT/'assets/index.json').read_text())['entries']}
    eligible, skipped, unidentified = [], [], []
    for root in roots():
        identity = root.get('asset_id')
        if identity not in asset_ids:
            unidentified.append({'instance_id':root['instance_id'],'asset_id':identity,
                                 'semantic_class':root.get('semantic_class')})
            continue
        op = {'selector':{'instance_ids':[root['instance_id']]},'asset_id':identity,'fit':'native'}
        try:
            if abs(root.get('variant_uniform_scale',1.0)-1.0)>1e-8:
                raise ValueError('Scene uses a fitted geometry scale; preserve/review that fit before refresh')
            if any(slot.link=='OBJECT' for obj in root.children_recursive for slot in obj.material_slots):
                raise ValueError('Scene-local object material overrides require review before refresh')
            expected_signature=cards[identity].get('quality_review',{}).get('source_signature')
            if expected_signature and slot_signature(root)!=expected_signature:
                raise ValueError('Scene geometry or materials differ from the original library; review local edits or an already-current asset')
            source_shape=cards[identity].get('quality_review',{}).get('source_geometry')
            if source_shape:
                meshes=[o for o in root.children_recursive if o.type=='MESH']
                counts={'parts':len(meshes),'vertices':sum(len(o.data.vertices) for o in meshes)}
                expected={k:source_shape[k] for k in counts}
                current={k:cards[identity][k] for k in counts}
                if counts==current and current!=expected:
                    skipped.append({'instance_id':root['instance_id'],'asset_id':identity,
                                    'reason':'Geometry counts already match the current asset; review before replacing again.'})
                    continue
                if counts!=expected:
                    raise ValueError('Scene-local geometry differs from the original registered asset; review additions and edits before replacement')
            plan_variant({'schema_version':1,'models':[op]},ROOT)
        except (ValueError, KeyError) as error:
            skipped.append({'instance_id':root['instance_id'],'asset_id':identity,'reason':str(error)})
        else:
            eligible.append(op)
    legacy = [{'collection':c.name,'import_key':c.get('roomkit_import_key')}
              for c in bpy.data.collections if c.get('roomkit_import_key')]
    return {'eligible':eligible,'skipped':skipped,'other_semantic_roots':unidentified,
            'legacy_collection_imports':legacy,
            'limitations':'Loose objects and legacy collection imports require explicit semantic migration; no automatic name guessing.'}


def main():
    import bpy
    from aha3d.blender.variants import apply_variant
    from aha3d.blender.semantics import export_semantics
    from integrate import digest, write
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--audit',action='store_true')
    parser.add_argument('--asset-id',action='append',default=[])
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if not args.audit and not args.out:parser.error('--out is required unless --audit is selected')
    if args.out and (args.out.resolve()==args.source.resolve() or args.out.exists()):
        parser.error('Choose a distinct, unused scene output')
    entries=json.loads((ROOT/'assets/index.json').read_text())['entries']
    asset_ids=set(args.asset_id) if args.asset_id else {e['id'] for e in entries
        if e['kind']=='collection' and e.get('quality_review',{}).get('status')=='upgraded'}
    known={e['id'] for e in entries if e['kind']=='collection'}
    if asset_ids-known:parser.error('Unregistered requested asset: '+str(sorted(asset_ids-known)))
    bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()))
    result=inspect_scene(asset_ids)
    result.update(source=str(args.source.resolve()),source_sha256=digest(args.source),
                  registry_sha256=digest(ROOT/'assets/registry.json'),job_id=os.environ.get('INDOOR_RUN_ID'))
    if not args.audit and result['eligible']:
        result['replacement']=apply_variant({'schema_version':1,'models':result['eligible']},ROOT)
        args.out.parent.mkdir(parents=True,exist_ok=True)
        bpy.context.preferences.filepaths.save_version=0
        bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve()))
        export_semantics(args.out.with_suffix('.semantics.json'))
        result.update(output=str(args.out.resolve()),output_sha256=digest(args.out),status='refreshed')
    else:
        result['status']='audited' if args.audit else 'no_eligible_assets'
    write(args.report,result)
    print(json.dumps({'status':result['status'],'eligible':len(result['eligible']),
                      'protected':len(result['skipped']),'report':str(args.report)}))


if __name__=='__main__':main()

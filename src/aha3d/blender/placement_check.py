"""Batch placement diagnosis on evaluated saved geometry; never saves the source."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from aha3d.placement.config import normalize
from aha3d.placement.report import write_report

STRUCTURE={'floor','wall','ceiling','structure'}
ARCHITECTURAL={'beam','timber','mullion','molding','moulding','wainscot','backsplash','jamb','sill','gable','roof','baseboard','architrave','worktop','hood'}


def issue(issues, severity, code, objects, message, action, **evidence):
    issues.append(dict(severity=severity, code=code, objects=objects, message=message,
                       next_action=action, evidence=evidence))


def ancestry(obj):
    while obj:
        yield obj
        obj = obj.parent


def geometry_parts(vertices, faces):
    """Split connected mesh islands; preserves table-leg and shelf cavities."""
    parents = list(range(len(vertices)))
    def find(x):
        while parents[x] != x:
            parents[x] = parents[parents[x]]; x = parents[x]
        return x
    for f in faces:
        for v in f[1:]:
            parents[find(int(v))] = find(int(f[0]))
    groups = {}
    for f in faces:
        groups.setdefault(find(int(f[0])), []).append(f)
    result = []
    for fs in groups.values():
        ids = sorted({int(i) for f in fs for i in f}); mapping = {i:j for j,i in enumerate(ids)}
        vv = vertices[ids]; ff = np.array([[mapping[int(i)] for i in f] for f in fs], dtype=int)
        edges = Counter(tuple(sorted((int(a),int(b)))) for f in ff for a,b in zip(f,np.roll(f,-1)))
        closed = bool(edges) and all(n == 2 for n in edges.values())
        result.append(dict(v=vv, f=ff, tree=BVHTree.FromPolygons(vv.tolist(),ff.tolist(),all_triangles=True),
                           lo=vv.min(0), hi=vv.max(0), closed=closed))
    return result


def discover(scene, config, issues):
    scene.frame_set(config['frame'] if config['frame'] is not None else scene.frame_current)
    bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
    scale = scene.unit_settings.scale_length
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Invalid scene unit scale')
    allowed = set()
    def visit(layer):
        if layer.exclude or layer.collection.hide_render:
            return
        allowed.update(o.name for o in layer.collection.objects)
        for c in layer.children: visit(c)
    visit(bpy.context.view_layer.layer_collection)
    groups = {}; excluded = []; used = set()
    for inst in dg.object_instances:
        obj = inst.object; original = obj.original
        anchor = inst.parent.original if inst.is_instance and inst.parent else original
        if anchor.name not in allowed or any(o.hide_render for o in ancestry(anchor)) or original.hide_render:
            continue
        if obj.type not in {'MESH','CURVE','SURFACE','FONT','META'}:
            continue
        chain = list(ancestry(anchor))
        root = next((o for o in chain if o.get('instance_id')), chain[-1])
        semantic = bool(root.get('instance_id'))
        oid = str(root.get('instance_id') or 'object:'+root.name)
        override_keys = [k for k in (oid,root.name) if k in config['objects']]
        if len(set(override_keys)) > 1:
            raise ValueError('Conflicting ID and name overrides for '+oid)
        override = config['objects'].get(override_keys[0],{}) if override_keys else {}
        used.update(override_keys)
        if override.get('exclude_reason'):
            excluded.append(dict(object=oid, reason=override['exclude_reason'])); continue
        if oid in groups and groups[oid]['root'] != root:
            raise ValueError('Duplicate instance_id: '+oid)
        if oid not in groups:
            words = re.split(r'[^a-z]+', str(root.get('semantic_class','')).lower())
            surface = str(original.get('surface_role',''))
            role = 'furniture'
            for candidate in ('floor','wall','ceiling','structure','cover','person','fixture','prop'):
                if candidate in words or surface.startswith(candidate): role = candidate; break
            inferred_role = False
            if not semantic and role == 'furniture':
                for candidate in ('floor','wall','ceiling'):
                    if candidate in re.split(r'[^a-z]+',root.name.lower()):
                        role = candidate; inferred_role = True; break
            if not semantic and role=='furniture' and (ARCHITECTURAL & set(re.split(r'[^a-z]+',root.name.lower())) or ('window' in root.name.lower() and any(w in root.name.lower() for w in ('frame','rail','glass','pane')))):
                role='structure'; inferred_role=True
            if set(words)&{'rug','carpet'}:role='cover'
            if set(words)&{'person','human','body','actor'} or 'person_id' in original or any(o.type=='ARMATURE' or 'person_id' in o for o in chain) or any(m.type=='ARMATURE' for m in original.modifiers): role='person'
            animated = any(o.animation_data or o.constraints for o in chain) or bool(original.data and getattr(original.data,'shape_keys',None))
            groups[oid] = dict(id=oid, name=root.name, root=root, grouping='semantic_root' if semantic else 'legacy_parent_hierarchy',
                role=override.get('role',role), role_inferred=inferred_role, parts=[], animated=bool(animated),
                fixed=override.get('fixed', bool(root.get('placement_fixed',False))),
                support_id=override.get('support',root.get('support_id')), override=override,
                asset_id=root.get('asset_id'), meshes=[])
        groups[oid]['animated'] |= any(o.animation_data or o.constraints for o in chain) or bool(getattr(original.data,'shape_keys',None))
        if 'person_id' in original: groups[oid]['role']='person'
        mesh = obj.to_mesh()
        try:
            if not mesh or not mesh.vertices: continue
            mesh.calc_loop_triangles()
            v = np.array([p.co[:] for p in mesh.vertices],float)
            m = np.asarray(inst.matrix_world)
            v = (v@m[:3,:3].T+m[:3,3])*scale
            f = np.array([t.vertices[:] for t in mesh.loop_triangles],int)
            if not len(f): continue
            if not np.isfinite(v).all(): raise ValueError('Nonfinite geometry: '+obj.name)
            groups[oid]['parts'].extend(geometry_parts(v,f))
            groups[oid]['meshes'].append(original.name)
        finally:
            obj.to_mesh_clear()
    if set(config['objects'])-used:
        raise ValueError('Object overrides match no visible root: '+', '.join(sorted(set(config['objects'])-used)))
    objects = []
    for oid,o in sorted(groups.items()):
        if not o['parts']: continue
        v = np.concatenate([p['v'] for p in o['parts']]); o.update(lo=v.min(0),hi=v.max(0), number=len(objects)+1)
        objects.append(o)
    legacy = [o['id'] for o in objects if o['grouping']!='semantic_root' and o['role'] not in STRUCTURE|{'person'}]
    if legacy:
        issue(issues,'unverified','legacy_grouping',legacy,'Used existing parent hierarchies; complete furniture identities are unverified.',
              'Review numbered inventory. Tag complete furniture roots with instance_id/semantic_class when grouping is wrong.')
    if not objects:
        issue(issues,'unverified','empty_scene',[],'No visible evaluated geometry was found.','Open the intended saved scene/view layer.')
    open_ids = [o['id'] for o in objects if any(not p['closed'] for p in o['parts'])]
    if open_ids:
        issue(issues,'unverified','open_geometry',open_ids,'Some components are not closed two-manifold surfaces; inside/outside tests are unavailable for them.',
              'Review surface-overlap warnings; use closed collision geometry for volume certification.')
    return objects, dict(structural_name_hints=[o['id'] for o in objects if o['role_inferred']],frame=scene.frame_current,unit_scale_m=scale, excluded=excluded,
                         visible_meshes=sum(len(o['meshes']) for o in objects))


def inside(part, point):
    """Two-ray parity on closed components, independent of face winding."""
    if not part['closed'] or np.any(point<=part['lo']) or np.any(point>=part['hi']): return False
    votes=[]
    for direction in (Vector((.8123,.3317,.4781)).normalized(),Vector((-.293,.873,.397)).normalized()):
        origin=Vector(point); faces=set()
        for _ in range(128):
            loc,normal,index,distance=part['tree'].ray_cast(origin,direction)
            if loc is None: break
            # Float32 BVH roundoff can re-hit the same bevel triangle after
            # advancing the origin. A straight ray crosses each triangle at
            # most once; repeated hits must not flip containment parity.
            faces.add(index); origin=loc+direction*1e-6
        else: return False
        votes.append(len(faces)%2==1)
    return all(votes)


def samples(part, budget):
    v=part['v']; centers=v[part['f']].mean(1)
    pts=np.concatenate((v,centers))
    if len(pts)>budget: pts=pts[np.linspace(0,len(pts)-1,budget,dtype=int)]
    return pts


def collision_checks(objects, config, issues):
    count=0; overlapping=0; tol=config['penetration_m']
    for ai,a in enumerate(objects):
        if a['role']=='person': continue
        for b in objects[ai+1:]:
            if b['role']=='person' or {a['role'],b['role']} <= STRUCTURE: continue
            if np.min(np.minimum(a['hi'],b['hi'])-np.maximum(a['lo'],b['lo'])) <= tol: continue
            count+=1; depth=0.; crossing=False; witness=None
            for pa in a['parts']:
                for pb in b['parts']:
                    if np.min(np.minimum(pa['hi'],pb['hi'])-np.maximum(pa['lo'],pb['lo'])) <= tol: continue
                    pairs=pa['tree'].overlap(pb['tree']); crossing |= bool(pairs)
                    for src,dst in ((pa,pb),(pb,pa)):
                        pts=samples(src,config['max_samples'])
                        pts=pts[np.all((pts>dst['lo'])&(pts<dst['hi']),axis=1)]
                        for p in pts:
                            nearest=dst['tree'].find_nearest(Vector(p))
                            if nearest[0] is not None and nearest[3]>tol and inside(dst,p):
                                if nearest[3]>depth: depth=float(nearest[3]); witness=p.tolist()
            if depth>tol:
                overlapping+=1
                cover=next((o for o in (a,b) if o['role']=='cover' and o['hi'][2]-o['lo'][2]<=.08),None)
                soft_contact=cover is not None and depth<=config['support_gap_m']
                issue(issues,'warning' if soft_contact else 'error','soft_cover_contact' if soft_contact else 'penetration',[a['id'],b['id']],f'Interior geometry sample is {depth:.4f} m inside the other object.'+(' Thin floor-cover contact may represent compression; review it.' if soft_contact else ''),
                      'Inspect this pair in the report and source views; correct the offending complete root or geometry and rerun.',
                      sampled_interior_depth_m=depth,witness_m=witness)
            elif crossing:
                issue(issues,'warning','surface_overlap',[a['id'],b['id']],'Triangle surfaces intersect; sampling did not establish penetration beyond tolerance.',
                      'Review whether this is intended contact, an open mesh, or a thin crossing; do not resolve from bounds alone.')
    return dict(candidate_pairs=count,penetrating_pairs=overlapping,method='component BVH surface overlap plus sampled two-ray containment',
                max_samples_per_component=config['max_samples'],penetration_tolerance_m=tol)


def support_checks(objects, config, issues):
    lookup={o['id']:o for o in objects}; names={o['name']:o for o in objects}
    for o in objects:
        sid=o['support_id']; declared=bool(sid)
        if sid and sid not in lookup and sid not in names:
            issue(issues,'unverified','missing_support',[o['id']],f'Declared support {sid!r} is absent.', 'Correct support_id or include the support geometry.')
            o['support']=dict(status='missing',declared=sid); continue
        target=lookup.get(sid,names.get(sid)) if sid else None
        if o['role'] in STRUCTURE|{'person','fixture'} or o['fixed']:
            o['support']=dict(status='not_applicable',reason='structure/person/declared fixed'); continue
        if target is o:
            issue(issues,'unverified','invalid_support',[o['id']], 'Object declares itself as its support.', 'Correct the support relationship.')
            o['support']=dict(status='missing'); continue
        if target and target['role'] in ('wall','ceiling'):
            # Mounting forces cannot be recovered from a gravity drop.
            o['fixed']=True
            issue(issues,'unverified','attachment',[o['id'],target['id']], 'Declared wall/ceiling attachment is held fixed; mounting contact is not certified.',
                  'Review mounting distance and source view; collision checks still apply.')
            o['support']=dict(status='attachment_unverified',target=target['id']); continue
        points=np.concatenate([p['v'] for p in o['parts']]); low=o['lo'][2]
        bottom=points[points[:,2]<=low+config['support_gap_m']]
        if len(bottom)>96: bottom=bottom[np.linspace(0,len(bottom)-1,96,dtype=int)]
        candidates=[target] if target else [v for v in objects if v is not o and v['role'] not in ('person','wall','ceiling') and v['lo'][2]<low+config['support_gap_m']]
        hits=[]
        # Cast from just below each low surface sample. Penetration is handled separately.
        for p in bottom:
            best=None
            for other in candidates:
                for part in other['parts']:
                    if np.any(p[:2]<part['lo'][:2]-1e-5) or np.any(p[:2]>part['hi'][:2]+1e-5): continue
                    origin=Vector((p[0],p[1],p[2]+config['support_gap_m']))
                    loc,normal,index,dist=part['tree'].ray_cast(origin,Vector((0,0,-1)))
                    if loc is not None and abs(normal.z)>.3:
                        gap=float(p[2]-loc.z)
                        if gap>=-config['support_gap_m'] and (best is None or gap<best[0]): best=(gap,other['id'])
            if best: hits.append(best)
        near=[h for h in hits if abs(h[0])<=config['support_gap_m']]
        if near:
            support=Counter(h[1] for h in near).most_common(1)[0][0]
            o['support']=dict(status='contact_observed',target=support,declared=declared,
                              sample_contact_fraction=len(near)/max(len(bottom),1),gap_m=min(h[0] for h in near))
        elif hits:
            gap,support=min(hits)
            o['support']=dict(status='gap',target=support,declared=declared,gap_m=gap)
            issue(issues,'error' if declared else 'warning','support_gap',[o['id'],support],f'Nearest sampled support is {gap:.4f} m below the object.',
                  'Check the intended support in source views; adjust the complete root or declare its actual mounting relationship.')
        else:
            o['support']=dict(status='unknown',declared=declared)
            issue(issues,'unverified','support_unknown',[o['id']], 'No support surface was found below sampled bottom geometry.',
                  'Check missing room geometry, shelf containment or wall mounting; supply support_id when known.')
    return dict(method='downward rays from evaluated bottom vertices',gap_tolerance_m=config['support_gap_m'])


def public_object(o):
    parts=[]
    for p in o['parts']:
        v=p['v']
        # Preserve extremal points for diagrams without embedding full meshes.
        ids=set()
        for direction in ((x,y,z) for x in (-1,0,1) for y in (-1,0,1) for z in (-1,0,1) if (x,y,z)!=(0,0,0)):
            ids.add(int(np.argmax(v@np.array(direction))))
        parts.append(v[sorted(ids)].tolist())
    return {k:o[k] for k in ('id','name','number','grouping','role','role_inferred','animated','fixed','asset_id','meshes','support') } | dict(min=o['lo'].tolist(),max=o['hi'].tolist(),projection_parts=parts)


def check(config=None):
    config=normalize(config); start=time.monotonic(); source_scene=bpy.context.scene
    issues=[]; objects,coverage=discover(source_scene,config,issues)
    print(f'PLACEMENT_DISCOVERY objects={len(objects)} seconds={time.monotonic()-start:.2f}',flush=True)
    coverage['collisions']=collision_checks(objects,config,issues)
    print(f'PLACEMENT_COLLISIONS seconds={time.monotonic()-start:.2f}',flush=True)
    coverage['support']=support_checks(objects,config,issues)
    print(f'PLACEMENT_SUPPORT seconds={time.monotonic()-start:.2f}',flush=True)
    from aha3d.blender.orientation import scene_facing_report
    facing=scene_facing_report(source_scene)
    for row in facing['issues']:
        issue(issues,'error' if row['status']=='fail' else 'unverified','facing',[str(row.get('instance_id') or row.get('object','unknown'))],
              str(row.get('reason') or row), 'Use the existing facing contract and source-view evidence; rerun after correcting the complete root.')
    coverage['facing']=facing
    animated=[o['id'] for o in objects if o['animated'] or o['role']=='person']
    if animated:
        issue(issues,'unverified','animated_scope',animated,'Placement check covers one evaluated frame; animated bodies are excluded from static-room collision checks.',
              'Use the existing full-clip body checks and requested articulation sweep review.')
    from aha3d.placement.physics import simulate
    try:
        coverage['physics']=simulate(objects,config,issues,issue)
    except Exception as exc:
        coverage['physics']=dict(status='failed',error=str(exc))
        issue(issues,'unverified','physics_failed',[],str(exc), 'Inspect the Blender log and geometry proxies; stability was not verified.')
    coverage['source_views']='Existing Pi3X layout review remains required; not regenerated by this room-only check'
    coverage['articulation']='No automatic door/drawer sweep or navigation certification'
    issues.sort(key=lambda i: ({'error':0,'warning':1,'unverified':2}[i['severity']], 0 if any(not o.startswith('object:') for o in i['objects']) else 1, i['code']))
    return dict(schema_version=1,tool='indoor.check-placement',config=config,objects=[public_object(o) for o in objects],issues=issues,
                coverage=coverage,seconds=time.monotonic()-start,blender_version=bpy.app.version_string,
                limits=['A clean diagnostic does not accept source fidelity, metric calibration, or final delivery.',
                        'Sampled containment can miss thin crossings; unresolved triangle intersections remain warnings.',
                        'Internal intersections within one semantic root and structural wall/floor seams are not assessed.',
                        'Support rays establish sampled contact, not a full contact patch or load-bearing capacity.',
                        'Short rigid-body simulation uses inferred uniform density and friction; movement diagnoses a candidate issue, not its cause.',
                        'No continuous collision, human contact repair, automatic placement edits, or source-scene save.'])


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--out',type=Path,required=True); parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]); args.out.mkdir(parents=True,exist_ok=False)
    source=Path(bpy.data.filepath)
    if not source.is_file(): raise ValueError('Open a saved .blend source')
    report=check(json.loads(args.config.read_text())); report['source']=str(source)
    write_report(args.out,report)
    print('PLACEMENT_CHECK '+json.dumps(report['summary']))


if __name__=='__main__': main()

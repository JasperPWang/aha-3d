"""Opt-in tabletop support discovery and registered swap assets (in memory only)."""
import re
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

CATALOG = [
    ('ceramic-vase-v1/vase-rounded-ceramic', 'Rounded ceramic vase', 'centerpiece', 1.4),
    ('tabletop-plants-v1/plant-compact-fern', 'Compact fern', 'centerpiece', .8),
    ('tabletop-plants-v1/flowers-pink-hydrangea-bowl', 'Pink hydrangea', 'centerpiece', .7),
    ('additional-444547-45-v1/additional-45-tall-porcelain-vase', 'Porcelain vase', 'accent', .5),
    ('additional-444547-44-v1/additional-44-silver-serving-platter', 'Silver platter', 'place-setting', .35),
    ('additional-444547-44-v1/additional-44-stylized-stemmed-vessel', 'Stemmed vessel', 'accent', .25),
]


def support_surface(obj):
    """Accept a connected convex horizontal top, including rotated and round slabs."""
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh=evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        points=np.asarray([evaluated.matrix_world @ v.co for v in mesh.vertices])
        if not len(points):return None
        lo,hi=points.min(0),points.max(0)
        if hi[2]-lo[2]<.004:return None
        if min((hi-lo)[:2])<.35:return None
        triangles=points[np.asarray([list(t.vertices) for t in mesh.loop_triangles])]
        normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        mask=(normals[:,2]>1e-9)&(np.ptp(triangles[:,:,2],axis=1)<.001)&(abs(triangles[:,:,2].mean(1)-hi[2])<.003)
        tops=triangles[mask]
        if not len(tops):return None
        from mathutils.geometry import convex_hull_2d
        xy=np.unique(np.round(tops[:,:,:2].reshape(-1,2),6),axis=0)
        hull=[xy[i].tolist() for i in convex_hull_2d([Vector(p) for p in xy])]
        area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(hull,hull[1:]+hull[:1]))/2
        if area<0:hull.reverse();area=-area
        if area<.08 or abs(normals[mask,2].sum()/2-area)>max(.005,area*.03):return None
        return dict(min=[float(lo[0]),float(lo[1]),float(max(lo[2],hi[2]-.08))],max=hi.tolist(),footprint=hull,area=float(area),
                    measurement='Evaluated horizontal top triangles cover their convex footprint within 3 percent')
    finally:evaluated.to_mesh_clear()


def prepare(scene):
    """Measure a convex horizontal top under an explicit semantic table root."""
    supports = []
    for root in list(scene.objects):
        if not root.get('instance_id') or not re.search(r'\btable(?:s)?\b', str(root.get('semantic_class', ''))):
            continue
        candidates = []
        for obj in [root, *root.children_recursive]:
            if obj.type != 'MESH' or obj.hide_render:
                continue
            support = support_surface(obj)
            if support:
                candidates.append((support['area'], obj.name, support))
        if candidates:
            largest=max(c[0] for c in candidates)
            _, name, surface = max((c for c in candidates if c[0]>=largest*.5), key=lambda x:(x[2]['max'][2],x[0]))
            root['browser_movable'] = False
            supports.append(dict(surface, id=root['instance_id'], mesh=name,
                                 source_ids=[o['instance_id'] for o in scene.objects
                                             if o.get('support_id') == root['instance_id'] and o.get('instance_id')]))
    if not supports:
        raise ValueError('--tabletop requires a semantic table with a measurable convex horizontal top')
    # Complete semantic props can rest on the slab or on another source prop.
    # Check the lower footprint, so a plant's overhanging leaves do not erase
    # the support relationship of its pot. Keep stacked books/props in one scope.
    props=[]
    for root in list(scene.objects):
        if not root.get('instance_id') or not re.search(r'decor|tabletop',str(root.get('semantic_class',''))):continue
        points=np.asarray([o.matrix_world @ Vector(p) for o in [root,*root.children_recursive]
                           if o.type=='MESH' and not o.hide_render for p in o.bound_box])
        if not len(points):continue
        lo,hi=points.min(0),points.max(0);base=points[points[:,2]<=lo[2]+max(.01,(hi[2]-lo[2])*.15)]
        props.append((root,lo,hi,base))
    def on_surface(s,base):
        hull=s['footprint']
        return all(all(((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]))/np.hypot(b[0]-a[0],b[1]-a[1])>=-.005
                       for a,b in zip(hull,hull[1:]+hull[:1])) for p in base)
    for _ in range(len(props)+1):
        changed=False
        for root,lo,hi,base in props:
            if root.get('support_id'):continue
            matches=[]
            for support in supports:
                if not on_surface(support,base):continue
                direct=abs(lo[2]-support['max'][2])<.035
                stacked=any(other.get('support_id')==support['id'] and abs(lo[2]-ohi[2])<.035
                            and all(olo[i]-.005<=base[:,i].mean()<=ohi[i]+.005 for i in (0,1))
                            for other,olo,ohi,_ in props if other!=root)
                if direct or stacked:matches.append(support)
            if len(matches)==1:
                root['support_id']=matches[0]['id'];matches[0]['source_ids'].append(root['instance_id']);changed=True
        if not changed:break
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'src'))
    from aha3d.blender.roomkit import place_asset
    templates = []
    project = Path(__file__).resolve().parents[2]
    asset_index = json.loads((project/'assets/index.json').read_text())
    for index, (asset_id, label, category, mass) in enumerate(CATALOG):
        identity = 'browser-template-'+str(index)
        place_asset(asset_id, instance_id=identity, project_root=Path(__file__).resolve().parents[2])
        card = next(item for item in asset_index['entries'] if item['id'] == asset_id)
        templates.append({'id': identity, 'asset_id': asset_id, 'label': label, 'category': category, 'mass': mass,
                          'library_sha256': card['library_sha256'], 'orientation': card.get('orientation')})
    bpy.context.view_layer.update()
    floors=[dict(surface,mesh=o.name) for o in scene.objects if o.type=='MESH' and not o.hide_render and re.search(r'\bfloor\b',o.name,re.I) for surface in [support_surface(o)] if surface]
    return {'schema_version': 1, 'seed': 'dining-28', 'scope': 'tabletop', 'supports': supports, 'templates': templates, 'floors': floors}


def finish(payload, spec):
    """Separate reusable asset geometry and normalize it about its bounds center."""
    templates = spec['templates']
    library_ids = {t['id'] for t in templates}
    source_ids = {i for s in spec['supports'] for i in s['source_ids']}
    for identity in sorted(source_ids):
        obj = next(o for o in payload['objects'] if o['instance_id'] == identity)
        templates.append({'id': identity, 'asset_id': obj.get('asset_id') or 'source-scene/'+identity,
                          'label': identity.replace('_', ' '), 'category': 'accent' if 'candlestick' in identity.lower() else 'centerpiece', 'mass': 1.5,
                          'source_sha256': payload['source_sha256']})
    for template in templates:
        parts = [m for m in payload['meshes'] if m['owner'] == template['id']]
        if not parts or any(p['joint'] for p in parts):
            raise ValueError('Tabletop assets must contain static geometry: '+template['id'])
        world = []
        for part in parts:
            p = np.asarray(part['positions']).reshape(-1, 3)
            m = np.asarray(part['matrix']).reshape(4, 4).T
            world.append(p @ m[:3, :3].T + m[:3, 3])
        world = np.concatenate(world)
        lo, hi = world.min(axis=0), world.max(axis=0)
        center = (lo+hi)/2
        template['size'] = (hi-lo).tolist()
        template['source_center'] = center.tolist()
        # A heavy base with light stems/petals is a better authored mass proxy
        # than assigning flower-tip vertices the same density as the vessel.
        lower = world[world[:, 2] <= lo[2]+(hi[2]-lo[2])*.25]
        com = (lower.min(axis=0)+lower.max(axis=0))/2 if len(lower) else center
        com[2] = lo[2]+(hi[2]-lo[2])*.18
        template['center_of_mass'] = (com-center).tolist()
        template['meshes'] = []
        for part in parts:
            m = np.asarray(part['matrix']).reshape(4, 4).T.copy()
            m[:3, 3] -= center
            template['meshes'].append({**part, 'matrix': m.T.reshape(-1).tolist()})
        # Bounded-complexity convex proxy from extremal visual vertices;
        # curved surfaces are approximate and vessels have no hollow interior.
        import bmesh
        bm = bmesh.new()
        # Quantization removes duplicated export triangle corners before the hull.
        points = np.unique(np.round(world-center, 5), axis=0)
        directions = [np.array([x, y, z], dtype=float) for x in (-1, 0, 1)
                      for y in (-1, 0, 1) for z in (-1, 0, 1) if x or y or z]
        directions += [np.array([np.cos(a), np.sin(a), -1000.])
                       for a in np.linspace(0, np.pi*2, 12, endpoint=False)]
        indices = sorted({int(np.argmax(points @ direction)) for direction in directions})
        for index in indices:
            bm.verts.new(points[index])
        bmesh.ops.convex_hull(bm, input=list(bm.verts), use_existing_faces=False)
        # cannon-es requires one polygon per plane; triangulated coplanar
        # faces create unstable contact clipping even with a correct hull.
        bm.normal_update()
        bmesh.ops.dissolve_limit(bm, angle_limit=.001, verts=list(bm.verts), edges=list(bm.edges))
        bm.normal_update()
        faces = list(bm.faces)
        used = list({v for face in faces for v in face.verts})
        ids = {v: i for i, v in enumerate(used)}
        template['hull'] = {'vertices': [list(v.co) for v in used],
                            'faces': [[ids[v] for v in face.verts] for face in faces]}
        bm.free()
    payload['meshes'] = [m for m in payload['meshes'] if m['owner'] not in library_ids]
    payload['objects'] = [o for o in payload['objects'] if o['instance_id'] not in library_ids]
    for support in spec['supports']:
        support['obstacles']=[]
        for part in payload['meshes']:
            if part['name']==support['mesh'] or part['owner'] in source_ids or any(o['instance_id']==part['owner'] and str(o.get('semantic_class','')).startswith('animation/') for o in payload['objects']) or part.get('cutaway') or part.get('joint'):continue
            p=np.asarray(part['positions']).reshape(-1,3);m=np.asarray(part['matrix']).reshape(4,4).T;p=p@m[:3,:3].T+m[:3,3]
            lo,hi=p.min(0),p.max(0)
            if lo[2]<support['max'][2]+.4 and hi[2]>support['max'][2]+.008 and all(hi[i]>support['min'][i] and lo[i]<support['max'][i] for i in (0,1)):
                support['obstacles'].append(dict(min=lo.tolist(),max=hi.tolist(),name=part['name']))
    payload['tabletop'] = spec
    payload['description'] = 'Tabletop objects use rigid-body gravity and convex collision proxies. Furniture edits and human playback are independent; browser changes stay in this page.'

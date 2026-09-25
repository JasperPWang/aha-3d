"""Canonical chair slots and conservative component/swept-motion proxies."""
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

import bpy
import numpy as np
from chair_geometry import forward_table_distance

def prepare(scene):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
    from aha3d.blender.roomkit import place_asset
    from aha3d.blender.orientation import get_orientation
    from aha3d.assets import resolve_item
    project = Path(__file__).resolve().parents[2]
    catalog_bytes = (project/'assets/index.json').read_bytes()
    index = json.loads(catalog_bytes)
    entries = {e['id']: e for e in index['entries']}
    roots = [o for o in scene.objects if str(o.get('semantic_class', '')).endswith('/chairs')]
    if not roots:
        raise ValueError('--chairs requires complete semantic chair roots')
    slots = []
    for root in roots:
        orientation = get_orientation(root, require_trusted=True)
        matrix = np.array(root.matrix_world, copy=True)
        if orientation['front_axis'] != '-Y' or orientation['up_axis'] != 'Z' or orientation['origin'] != 'floor_center':
            raise ValueError('Chair slots need reviewed canonical -Y/Z floor-center frames: ' + root.name)
        lengths = np.linalg.norm(matrix[:3,:3],axis=0)
        if min(lengths)<=0 or not np.isfinite(lengths).all():
            raise ValueError('Chair slot must have finite positive scale: '+root.name)
        # Remove only root scale from the canonical measurement frame. The
        # evaluated source meshes retain all authored nonuniform dimensions;
        # replacement assets still use their native, unscaled geometry.
        matrix[:3,:3] /= lengths
        if not np.allclose(matrix[:3,:3].T @ matrix[:3,:3],np.eye(3),atol=1e-5) or not np.allclose(matrix[2,:3],[0,0,1],atol=1e-5) or np.linalg.det(matrix[:3,:3])<0:
            raise ValueError('Chair slots must be upright without reflection or shear: '+root.name)
        root['browser_movable'] = True
        entry = entries.get(root.get('asset_id'), {})
        slots.append({'id': root['instance_id'], 'original_asset_id': root.get('asset_id'),
                      'seating_type': entry.get('seating_type') or root.get('browser_seating_type'), 'source_model_id': entry.get('family_id') or root.get('browser_source_model_id'),
                      'replacement_group_id': entry.get('family_id') or root.get('browser_source_model_id') or root['instance_id'],
                      'original_scale': lengths.tolist(),
                      'original_uniform_scale': float(lengths[0]) if np.allclose(lengths,lengths[0],atol=1e-5) else None, 'matrix': matrix.tolist(),
                      'position': matrix[:3, 3].tolist(), 'yaw': float(np.arctan2(matrix[1, 0], matrix[0, 0])),
                      'orientation': orientation, 'facing_intent': json.loads(root['facing_target_json']) if root.get('facing_target_json') else
                      {'direction': (-matrix[:3,1]).tolist(), 'origin': 'Retained heading of trusted source asset'}})
    templates = []
    candidates = sorted((c for c in index['entries'] if c.get('kind')=='collection' and c.get('status')=='registered'
                         and str(c.get('category','')).endswith('/chairs') and c.get('orientation',{}).get('status') in ('authored','reviewed')
                         and all(c.get('orientation',{}).get(k)==v for k,v in {'front_axis':'-Y','up_axis':'Z','origin':'floor_center'}.items())), key=lambda c:c['id'])
    used_ids = {o.get('instance_id') for o in scene.objects}
    for i, entry in enumerate(candidates):
        asset = entry['id']
        card = resolve_item(asset, root=project, expected_kind='collection')
        label = card['datablock'].replace('RK Chair - ', '').replace('Additional 44 | ', '').replace('Additional 45 | ', '')
        identity = 'chair-template-' + str(i)
        while identity in used_ids:
            identity += '-'
        used_ids.add(identity)
        place_asset(asset, instance_id=identity, project_root=project)
        templates.append({'id': identity, 'asset_id': asset, 'label': label,
                          'seating_type': entry.get('seating_type'), 'model_id': entry['family_id'],
                          'library_sha256': card['library_sha256'],
                          'library': str(card['library']), 'orientation': card['orientation']})
    bpy.context.view_layer.update()
    return {'schema_version': 2, 'slots': slots, 'templates': templates,
            'asset_catalog_sha256': hashlib.sha256(catalog_bytes).hexdigest(),
            'policy': {'version': 'source-relative-v2', 'width_ratio': 1.20, 'depth_ratio': 1.35,
                       'replacement': 'Same source model shares one alternative asset of the same declared seating type; original model excluded',
                       'height_ratio': 1.50, 'seat_height_relative_tolerance': .18,
                       'translation_footprint_ratio': 0, 'rear_clearance_depth_ratio': .50, 'collision_margin_m': .003,
                       'scale': 'native', 'scope': 'Fixed seat count and heading; preserve current XY anchors; interactive dragging allowed'},
            'limitations': ['Component bounds are conservative collision proxies, not mesh contact certification.',
                            'Human envelopes cover every saved animation frame, not continuous inter-frame motion.',
                            'Rear clearance covers static fixtures and other chairs, not a simulated seated interaction.']}


def world_points(mesh):
    m = np.asarray(mesh['matrix']).reshape(4, 4).T
    return np.asarray(mesh['positions']).reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]


def box(points, **extra):
    return {'min': points.min(axis=0).tolist(), 'max': points.max(axis=0).tolist(), **extra}


def normalize(parts, transform):
    inverse = np.linalg.inv(transform)
    normalized, proxies = [], []
    for part in parts:
        m = inverse @ np.asarray(part['matrix']).reshape(4, 4).T
        copy = {**part, 'matrix': m.T.ravel().tolist()}
        normalized.append(copy)
        proxies.append(box(world_points(copy), name=part['name']))
    points = np.concatenate([world_points(p) for p in normalized])
    bounds = box(points)
    # Names nominate authored parts; callers inspect these exact measurements.
    seats = [p for p in proxies if re.search(r'\bseat\b|\bcushion\b', p['name'], re.I)
             and not re.search(r'back|welt|frame|rail', p['name'], re.I)]
    if not seats:
        return normalized, proxies, {**bounds, 'dimensions_m': (points.max(0)-points.min(0)).tolist(), 'seat': None}
    seat = max(seats, key=lambda p: p['max'][2])
    arms = [p for p in proxies if re.search(r'\barm(?:rest)?\b', p['name'], re.I)]
    return normalized, proxies, {**bounds, 'dimensions_m': (points.max(0)-points.min(0)).tolist(),
        'seat': {'height_m': seat['max'][2], 'width_m': seat['max'][0]-seat['min'][0],
                 'depth_m': seat['max'][1]-seat['min'][1], 'part': seat['name']},
        'arm_height_m': max((p['max'][2] for p in arms), default=None),
        'frame': {'front': '-Y', 'up': 'Z', 'origin': 'floor_center'},
        'measurement': 'Evaluated geometry in canonical asset coordinates; authored scene metres'}


def finish(payload, spec):
    templates, slots = spec['templates'], spec['slots']
    template_ids = {t['id'] for t in templates}
    chair_ids = {s['id'] for s in slots}
    for template in templates:
        parts = [m for m in payload['meshes'] if m['owner'] == template['id']]
        template['meshes'], template['proxies'], template['specification'] = normalize(parts, np.eye(4))
        if hashlib.sha256(Path(template['library']).read_bytes()).hexdigest() != template['library_sha256']:
            raise ValueError('Chair library changed during export: '+template['asset_id'])
        template.pop('library')
    for slot in slots:
        parts = [m for m in payload['meshes'] if m['owner'] == slot['id']]
        _, slot['original_proxies'], slot['original_specification'] = normalize(parts, np.asarray(slot.pop('matrix')))
        if slot['original_specification']['seat'] is None:
            raise ValueError('Chair slot requires an identifiable seat surface: '+slot['id'])
        measured=slot['original_specification'];w,d,h=measured['dimensions_m'];seat_h=measured['seat']['height_m'];policy=spec['policy']
        slot['limits'] = {'max_translation_m':min(w,d)*policy['translation_footprint_ratio'],
                          'max_width_m':w*policy['width_ratio'],'max_depth_m':d*policy['depth_ratio'],'max_height_m':h*policy['height_ratio'],
                          'seat_height_range_m':[seat_h*(1-policy['seat_height_relative_tolerance']),seat_h*(1+policy['seat_height_relative_tolerance'])],
                          'rear_clearance_m':d*policy['rear_clearance_depth_ratio'],'collision_margin_m':policy['collision_margin_m'],
                          'derived_from':'Source canonical geometry; shared source-relative-v2 policy; no automatic translation'}
        # Group membership does not mean the table physically supports the chair.
        tables = [o for o in payload['objects'] if re.search(r'\btables?\b', o['semantic_class'] or '', re.I)]
        nearby=[]
        for table in tables:
            points=np.concatenate([world_points(m) for m in payload['meshes'] if m['owner']==table['instance_id']])
            distance=forward_table_distance(points,slot['position'],slot['yaw'])
            if distance is not None and distance<=np.linalg.norm(points.max(0)[:2]-points.min(0)[:2])+d:
                nearby.append((distance,table['instance_id']))
        slot['table_id']=min(nearby)[1] if nearby else None
    payload['meshes'] = [m for m in payload['meshes'] if m['owner'] not in template_ids]
    payload['objects'] = [o for o in payload['objects'] if o['instance_id'] not in template_ids]
    # Read the support elevation from the source geometry. A multi-level room
    # needs separate navigation layers and is deliberately rejected for now.
    elevations = [s['position'][2] for s in slots]
    if max(elevations)-min(elevations) > .02:
        raise ValueError('Chair slots on multiple floor levels need separate navigation layers')
    floor_z = float(np.median(elevations))
    floors = []
    for mesh in payload['meshes']:
        if mesh.get('surface') not in ('floor', 'floor_finish') and not re.search(r'\bfloor\b', mesh['name'], re.I):
            continue
        points = world_points(mesh)
        bounds = box(points, name=mesh['name'])
        if abs(bounds['max'][2]-floor_z) > .04:
            continue
        faces = np.asarray([i for g in mesh['groups'] for i in g['indices']]).reshape(-1, 3)
        triangles = points[faces]
        normals = np.cross(triangles[:,1]-triangles[:,0], triangles[:,2]-triangles[:,0])
        top = (normals[:,2]>1e-8) & (np.ptp(triangles[:,:,2],axis=1)<.003) & (abs(triangles[:,:,2].mean(1)-floor_z)<=.04)
        if np.any(top):
            floors.append({**bounds, 'triangles_xy':triangles[top,:,:2].tolist()})
    if not floors:
        raise ValueError('Chair slots require identifiable floor geometry at their support height')
    used_ids = {o['instance_id'] for o in payload['objects']}
    def identity(base):
        while base in used_ids:
            base += '-'
        used_ids.add(base)
        return base
    spec['floor_support'] = {'id': identity('roomkit-floor-support'), 'height_m': floor_z,
                             'surfaces': floors, 'measurement': 'Source chair anchors checked against floor geometry'}
    groups = {t: identity('roomkit-seating:'+str(t)) for t in sorted({s['table_id'] for s in slots}, key=str)}
    for slot in slots:
        slot['group_id'] = groups[slot['table_id']]
    spec['motion_envelopes'] = []
    animation = payload.get('animation')
    if animation:
        for actor in animation['actors']:
            frames = np.frombuffer(base64.b64decode(actor['positions_base64']), dtype='<f4').reshape(animation['frames'], -1, 3)
            mesh = next(m for m in payload['meshes'] if m['name']==actor['mesh_name'])
            faces = np.asarray([i for g in mesh['groups'] for i in g['indices']]).reshape(-1, 3)
            for frame, vertices in enumerate(frames):
                triangles = vertices[faces]; low = triangles[:,:,2].min(1); high = triangles[:,:,2].max(1)
                for z in np.arange(np.floor(vertices[:,2].min()/.12)*.12, vertices[:,2].max(), .12):
                    points = triangles[(low <= z+.12) & (high >= z)].reshape(-1,3)
                    if not len(points):
                        continue
                    b = box(points, owner=actor['owner'], frame=frame+animation['start_frame'])
                    b['min'][2], b['max'][2] = float(z), float(z+.12)
                    spec['motion_envelopes'].append(b)
    spec['animation_frames_checked'] = animation['frames'] if animation else 0
    # Keep each native door's entire sampled opening envelope, irrespective of current slider value.
    from mathutils import Matrix, Quaternion, Vector
    joint_proxies = []
    for joint in payload['joints']:
        a, b = joint['closed'], joint['open']
        qa = Quaternion((a['quaternion'][3], *a['quaternion'][:3])); qb = Quaternion((b['quaternion'][3], *b['quaternion'][:3]))
        for amount in np.linspace(0, 1, 21):
            parent = np.asarray(Matrix.LocRotScale(Vector(a['position']).lerp(Vector(b['position']), float(amount)), qa.slerp(qb,float(amount)), Vector(a['scale'])))
            for mesh in payload['meshes']:
                if mesh['joint'] != joint['id']:
                    continue
                p = world_points(mesh) @ parent[:3,:3].T + parent[:3,3]
                joint_proxies.append(box(p, owner=joint['owner'], joint=joint['id']))
    spec['joint_envelopes'] = joint_proxies
    payload['chairs'] = spec

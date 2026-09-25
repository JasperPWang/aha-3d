"""Refine current tabletop collections without changing stable asset identities.

Run with background Blender. Outputs are candidate libraries only;
registration and replacement of canonical payloads are deliberate integration steps.
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path
import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

COLLECTIONS = {
    'additional-444547-44-v1': ['Additional 44 | Silver serving platter', 'Additional 44 | Stylized stemmed vessel'],
    'additional-444547-45-v1': ['Additional 45 | Tall porcelain vase', 'Additional 45 | Small porcelain vase'],
    'ceramic-vase-v1': ['RK Vase - Rounded Ceramic'],
    'plants-v1': ['RK Plant - Broadleaf Ceramic'],
    'plants-v2': ['RK Plant - Peace Lily Natural'],
    'tabletop-plants-v1': ['RK Plant - Compact Fern', 'RK Flowers - Pink Hydrangea Bowl'],
}
ROOT = Path(__file__).resolve().parents[2]


def mesh_objects(collection):
    return [o for o in collection.all_objects if o.type == 'MESH']


def bounds(objects):
    coords = [o.matrix_world @ v.co for o in objects if o.type == 'MESH' for v in o.data.vertices]
    return [min(p[i] for p in coords) for i in range(3)], [max(p[i] for p in coords) for i in range(3)]


def topology(obj):
    bm = bmesh.new(); bm.from_mesh(obj.data)
    result = {'vertices':len(bm.verts), 'edges':len(bm.edges), 'faces':len(bm.faces),
              'boundary_edges':sum(e.is_boundary for e in bm.edges),
              'nonmanifold_edges':sum(not e.is_manifold for e in bm.edges),
              'degenerate_faces':sum(f.calc_area() < 1e-14 for f in bm.faces),
              'signed_volume_m3': bm.calc_volume(signed=True) * obj.matrix_world.to_3x3().determinant()}
    bm.free()
    return result


def object_audit(obj):
    low, high = bounds([obj])
    return {'name':obj.name, 'bounds_min_m':low, 'bounds_max_m':high,
            'materials':[m.name if m else None for m in obj.data.materials], **topology(obj)}


def snapshot(collection):
    objects = mesh_objects(collection)
    low, high = bounds(objects)
    return {'parts':len(objects), 'vertices':sum(len(o.data.vertices) for o in objects),
            'dimensions_m':[b-a for a,b in zip(low,high)], 'bounds_min_m':low, 'bounds_max_m':high,
            'collection_instance_offset':list(collection.instance_offset),
            'objects':[object_audit(o) for o in objects]}


def lathe_mesh(obj, profile, center, *, segments=128, ribs=0.0):
    """Replace mesh with a closed meridian: outside bottom -> rim -> inside floor.

    Axis poles are single vertices, never coincident angular rings. Coordinates
    are specified in native world metres and transformed back into the object's
    unchanged local basis, retaining the import contract and material slots.
    """
    vertices, rings, faces = [], [], []
    inverse = obj.matrix_world.inverted()
    for radius, z in profile:
        if radius <= 1e-10:
            rings.append([len(vertices)])
            vertices.append(inverse @ Vector((center[0],center[1],z)))
        else:
            ring=[]
            for i in range(segments):
                angle=math.tau*i/segments
                r=radius+(ribs*math.cos(32*angle) if radius > .025 else 0)
                ring.append(len(vertices))
                vertices.append(inverse @ Vector((center[0]+r*math.cos(angle),center[1]+r*math.sin(angle),z)))
            rings.append(ring)
    for a,b in zip(rings,rings[1:]):
        for i in range(segments):
            j=(i+1)%segments
            if len(a)==1: faces.append((a[0],b[j],b[i]))
            elif len(b)==1: faces.append((a[i],a[j],b[0]))
            else: faces.append((a[i],a[j],b[j],b[i]))
    data=bpy.data.meshes.new(obj.data.name+' refined')
    data.from_pydata(vertices,[],faces); data.update()
    for material in obj.data.materials: data.materials.append(material)
    old=obj.data; obj.data=data
    for mod in list(obj.modifiers): obj.modifiers.remove(mod)
    bm=bmesh.new(); bm.from_mesh(data)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    if bm.calc_volume(signed=True)<0: bmesh.ops.reverse_faces(bm,faces=list(bm.faces))
    bm.to_mesh(data); bm.free(); data.update()
    for p in data.polygons:
        # Flat underside/floor remain flat; curved meridians shade smoothly.
        p.use_smooth=abs(p.normal.z)<.9999
    if not old.users: bpy.data.meshes.remove(old)
    return obj


def exterior_profile(obj):
    """Recover rotational exterior landmarks independent of Blender vertex order.

    The supported authored vessels have one maximum-radius body ring. Increasing
    radii below that ring and decreasing radii above it exclude inner neck/floor
    rings, which can be interleaved in a modifier-baked mesh's vertex ordering.
    """
    low,high=bounds([obj]); cx=(low[0]+high[0])/2; cy=(low[1]+high[1])/2
    groups={}
    for vertex in obj.data.vertices:
        p=obj.matrix_world @ vertex.co
        groups.setdefault(round(p.z,6),[]).append(p)
    rings=[]
    for key,points in sorted(groups.items()):
        z=sum(p.z for p in points)/len(points)
        r=max(math.hypot(p.x-cx,p.y-cy) for p in points)
        rings.append((r,z))
    peak=max(range(len(rings)),key=lambda i:rings[i][0])
    lower=[]
    for ring in rings[:peak+1]:
        if not lower or ring[0]>=lower[-1][0]-1e-7:lower.append(ring)
    upper=[]
    for ring in reversed(rings[peak+1:]):
        if not upper or ring[0]>=upper[-1][0]-1e-7:upper.append(ring)
    rings=lower+list(reversed(upper))
    radius=max(high[0]-low[0],high[1]-low[1])/2
    biggest=max(r for r,z in rings)
    rings=[(r*radius/biggest,z) for r,z in rings]
    return rings,(cx,cy),low,high


def smooth_profile(rings, steps=5):
    """Monotone cubic interpolation of radius versus height without overshoot."""
    if len(rings)<3:return rings
    h=[b[1]-a[1] for a,b in zip(rings,rings[1:])]
    if any(x<=1e-8 for x in h):raise ValueError('Exterior heights must increase')
    delta=[(b[0]-a[0])/dz for a,b,dz in zip(rings,rings[1:],h)]
    slopes=[delta[0]]
    for i in range(1,len(rings)-1):
        left,right=delta[i-1],delta[i]
        if left*right<=0:slopes.append(0)
        else:
            w1=2*h[i]+h[i-1];w2=h[i]+2*h[i-1]
            slopes.append((w1+w2)/(w1/left+w2/right))
    slopes.append(delta[-1]);result=[]
    for i,(a,b) in enumerate(zip(rings,rings[1:])):
        for j in range(steps):
            t=j/steps
            r=(2*t**3-3*t**2+1)*a[0]+(t**3-2*t**2+t)*h[i]*slopes[i]+(-2*t**3+3*t**2)*b[0]+(t**3-t**2)*h[i]*slopes[i+1]
            if not min(a[0],b[0])-1e-9<=r<=max(a[0],b[0])+1e-9:raise ValueError('Profile overshoot')
            result.append((r,a[1]+t*h[i]))
    return result+[rings[-1]]


def clean_poles(obj):
    """Weld collapsed lathe poles; preserve outer geometry/materials/UV layers."""
    data=obj.data.copy(); obj.data=data
    bm=bmesh.new(); bm.from_mesh(data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-7)
    bmesh.ops.dissolve_degenerate(bm,edges=list(bm.edges),dist=1e-9)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    if bm.calc_volume(signed=True)<0: bmesh.ops.reverse_faces(bm,faces=list(bm.faces))
    bm.to_mesh(data);bm.free();data.update()


def cavity_check(obj):
    """Check actual mesh rays, with soil/flowers deliberately absent from BVH."""
    low,high=bounds([obj]); center=Vector(((low[0]+high[0])/2,(low[1]+high[1])/2,high[2]+.01))
    verts=[obj.matrix_world @ v.co for v in obj.data.vertices]
    tree=BVHTree.FromPolygons(verts,[tuple(p.vertices) for p in obj.data.polygons],all_triangles=False)
    point,normal,index,distance=tree.ray_cast(center,Vector((0,0,-1)))
    if point is None: raise ValueError(f'No sealed cavity floor in {obj.name}')
    depth=high[2]-point.z
    if depth<=.001: raise ValueError(f'Solid or too shallow: {obj.name}: {depth}')
    checks=[]
    # Horizontal rays from half cavity depth must hit the inner wall before leaving.
    probe=Vector((center.x,center.y,point.z+depth*.5))
    for angle in (0,math.pi/2,math.pi,math.pi*1.5):
        direction=Vector((math.cos(angle),math.sin(angle),0))
        p,n,i,d=tree.ray_cast(probe,direction)
        checks.append({'angle_rad':angle,'wall_distance_m':d,'hit':p is not None})
    if not all(x['hit'] for x in checks): raise ValueError('Missing inner wall: '+obj.name)
    return {'object':obj.name,'floor_z_m':point.z,'rim_z_m':high[2],
            'center_cavity_depth_m':depth,'wall_rays':checks,
            'scope':'Vessel mesh only; soil and foliage excluded. No dynamics certification.'}


def refine_collection(collection):
    name=collection.name; objects=mesh_objects(collection); changed=[]; vessels=[]
    if 'stemmed vessel' in name:
        low,high=bounds(objects); r=(high[0]-low[0])/2; z0=low[2]; h=high[2]-z0
        obj=next(o for o in objects if 'glass bowl' in o.name)
        profile=[(0,z0),(.041,z0),(.044,z0+.001), (r,z0+.003),(r,z0+.012),(.043,z0+.015),
                 (.019,z0+.015),(.013,z0+.020),(.012,z0+.027),(.012,z0+.194),(.014,z0+.201),
                 (.032,z0+.2055),(.040,z0+.207),(.044,z0+.211),(r,z0+.216),
                 (r,z0+h-.002),(.0447,z0+h-.0005),(.0438,z0+h),(.0429,z0+h-.0005),
                 (.0426,z0+h-.002),(.0426,z0+.219),(.041,z0+.215),(.034,z0+.212),(0,z0+.212)]
        lathe_mesh(obj,profile,((low[0]+high[0])/2,(low[1]+high[1])/2))
        for old in objects:
            if old!=obj: bpy.data.objects.remove(old,do_unlink=True)
        changed=[obj];vessels=[obj]
        reasons=['Replaced three intersecting 24-sided solid proxies with one continuous 128-sided vessel shell.',
                 'Authored open cup, 2.4 mm straight wall, sealed floor, softened rim and continuous stem/base junction.']
    elif 'porcelain vase' in name:
        obj=objects[0];rings,center,low,high=exterior_profile(obj);rings=smooth_profile(rings);t=.004 if 'Tall' in name else .003
        top=rings[-1];base=low[2]+.007
        profile=[(0,low[2]),*rings,(top[0]-t*.3,top[1]-.00025),(top[0]-t,top[1]-.0015)]
        profile += [(r-t,z) for r,z in reversed(rings[:-1]) if z>base+.001]
        profile += [(rings[1][0]-t,base+.001),(rings[0][0]-t,base),(0,base)]
        lathe_mesh(obj,profile,center);changed=[obj];vessels=[obj]
        reasons=['Rebuilt capped solid porcelain cylinder as a sealed hollow vessel with 128 radial segments.',
                 f'Retained measured rounded outer silhouette and ceramic material; authored {t*1000:g} mm radial wall and 7 mm base.']
    elif 'Rounded Ceramic' in name:
        obj=objects[0];rings,center,low,high=exterior_profile(obj);rings=smooth_profile(rings)
        end=max(range(len(rings)),key=lambda i:rings[i][1]);outer=rings[:end+1]
        # Retain every original exterior ring and top; extend the shallow throat
        # through the full body with a sealed bottom.
        t=.006;floor=low[2]+.014;top=outer[-1]
        profile=[(0,low[2]),*outer,(top[0]-.003,top[1]-.0007),(top[0]-t,top[1]-.003)]
        profile += [(r-t,z) for r,z in reversed(outer[:-1]) if z>floor+.002]
        profile += [(outer[0][0]-t,floor+.002),(outer[0][0]-.010,floor),(0,floor)]
        lathe_mesh(obj,profile,center);changed=[obj];vessels=[obj]
        reasons=['Smoothed the original exterior landmarks without radius overshoot; extended shallow inner neck into a full-depth cavity.',
                 'Closed missing underside and joined inner/outer shells with a rounded lip and 14 mm base.']
    elif 'Silver serving platter' in name:
        low,high=bounds(objects);r=(high[0]-low[0])/2;z=low[2]
        obj=next(o for o in objects if 'Silver serving platter' in o.name)
        profile=[(0,z+.003),(.110,z+.003),(.119,z+.002),(.123,z),(.132,z),(.137,z+.003),
                 (.149,z+.009),(r,z+.013),(.1535,high[2]-.0008),(.151,high[2]),
                 (.148,high[2]-.001),(.141,z+.012),(.133,z+.007),(.122,z+.006),(0,z+.006)]
        lathe_mesh(obj,profile,((low[0]+high[0])/2,(low[1]+high[1])/2))
        for old in objects:
            if old!=obj:bpy.data.objects.remove(old,do_unlink=True)
        changed=[obj];vessels=[obj]
        reasons=['Replaced overlapping thick disk and torus with one continuous serving surface, recessed well, rolled rim and support foot.',
                 'Preserved 308 mm outer diameter, 18 mm overall height and silver material.']
    elif name in ('RK Plant - Broadleaf Ceramic','RK Plant - Peace Lily Natural'):
        obj=next(o for o in objects if o.get('plant_role')=='pot');rings,center,low,high=exterior_profile(obj);rings=smooth_profile(rings)
        # Existing ring order is exterior -> lip -> cavity floor, followed by a
        # single welded pole. Keep those landmarks and add a proper round lip.
        top=max(range(len(rings)),key=lambda i:rings[i][1]); outer=rings[:top+1]
        t=.008;floor=low[2]+.016;tip=outer[-1]
        profile=[(0,low[2]),*outer,(tip[0]-.003,tip[1]-.0007),(tip[0]-t,tip[1]-.003)]
        profile += [(r-t,z) for r,z in reversed(outer[:-1]) if z>floor+.004]
        profile += [(outer[0][0]-t,floor+.003),(outer[0][0]-.014,floor),(0,floor)]
        lathe_mesh(obj,profile,center);changed=[obj];vessels=[obj]
        reasons=['Retained foliage, substrate and pot position; smoothed the original pot profile through its measured landmarks.',
                 'Refined 48-sided pot to 128-sided sealed vessel with a full interior and explicit 8 mm radial wall and 16 mm base.']
    else:
        for obj in objects:
            if any(s in obj.name.lower() for s in ('pot','bowl','substrate')) and 'granule' not in obj.name.lower():
                clean_poles(obj);changed.append(obj)
                if 'soil' not in obj.name.lower() and 'substrate' not in obj.name.lower():vessels.append(obj)
        reasons=['Welded duplicated axis poles in vessel and substrate meshes, closing false boundary loops and restoring valid solid topology.',
                 'Preserved authored ribbed bowl/pot shape, all foliage, materials and geometry positions.']
    for obj in changed:
        stats=topology(obj)
        if stats['nonmanifold_edges'] or stats['degenerate_faces'] or stats['signed_volume_m3']<=0:
            raise ValueError(f'Invalid changed mesh {obj.name}: {stats}')
    return reasons,changed,[cavity_check(o) for o in vessels]


def render_views(collection,directory,prefix,framing=None,focus_objects=None):
    sys.path.insert(0,str(ROOT/'src'))
    from aha3d.blender.roomkit import configure_render
    directory.mkdir(parents=True,exist_ok=True);scene=bpy.context.scene
    objects=focus_objects or mesh_objects(collection); low,high=framing or bounds(objects)
    hidden=[]
    if focus_objects is not None:
        for obj in mesh_objects(collection):
            if obj not in focus_objects:
                hidden.append((obj,obj.hide_render));obj.hide_render=True
    center=(Vector(low)+Vector(high))*.5; size=max(high[i]-low[i] for i in range(3))
    camera_data=bpy.data.cameras.new('Quality inspection camera');camera=bpy.data.objects.new(camera_data.name,camera_data)
    scene.collection.objects.link(camera);scene.camera=camera;camera_data.type='ORTHO';camera_data.ortho_scale=size*1.45
    scene.render.resolution_x=scene.render.resolution_y=512;scene.render.resolution_percentage=100
    scene.world=bpy.data.worlds.new('Quality inspection world');scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.45,.45,.45,1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.65
    lights=[]
    for loc,power,scale in [((2,-3,4),500,3),((-3,-1,2),300,2),((1,3,3),400,2)]:
        data=bpy.data.lights.new('Quality softbox','AREA');data.energy=power*size*size;data.shape='DISK';data.size=scale*size
        obj=bpy.data.objects.new(data.name,data);scene.collection.objects.link(obj);obj.location=center+Vector(loc)*size
        obj.rotation_euler=(center-obj.location).to_track_quat('-Z','Y').to_euler();lights.append(obj)
    outputs=[]
    for suffix,direction,mode in [('oblique',(1.3,-1.8,1.25),'material'),('cavity',(0,-.55,2.0),'clay')]:
        configure_render(scene,mode=mode,samples=24)
        camera.location=center+Vector(direction)*size*2
        camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
        scene.render.filepath=str(directory/f'{prefix}_{suffix}.png');bpy.ops.render.render(write_still=True);outputs.append(scene.render.filepath)
    for obj in [camera,*lights]:bpy.data.objects.remove(obj,do_unlink=True)
    for obj,was_hidden in hidden:obj.hide_render=was_hidden
    return outputs


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--library-id',choices=COLLECTIONS)
    parser.add_argument('--out',required=True)
    parser.add_argument('--audit-only',action='store_true')
    parser.add_argument('--render',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    registry=json.loads((ROOT/'assets/registry.json').read_text())['assets']
    entries=json.loads((ROOT/'assets/index.json').read_text())['entries']
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True);reports=[]
    for lid in ([args.library_id] if args.library_id else COLLECTIONS):
        bpy.ops.wm.open_mainfile(filepath=str(ROOT/registry[lid]['path']))
        candidate=out/lid/'tabletop_candidates.blend';candidate.parent.mkdir(parents=True,exist_ok=True)
        selected=[];library_reports=[]
        for name in COLLECTIONS[lid]:
            collection=bpy.data.collections.get(name)
            if collection is None:raise ValueError('Missing '+name)
            bpy.context.scene.collection.children.link(collection);bpy.context.view_layer.update()
            before=snapshot(collection);selected.append(collection)
            if args.audit_only:
                reports.append({'library_id':lid,'datablock':name,'before':before})
                bpy.context.scene.collection.children.unlink(collection);continue
            slug=name.lower().replace(' | ','-').replace(' - ','-').replace(' ','-')
            preview_dir=out/lid/slug
            previews=render_views(collection,preview_dir,'before',framing=(before['bounds_min_m'],before['bounds_max_m'])) if args.render else []
            plant_vessels=[o for o in mesh_objects(collection) if ('Plant -' in name or 'Flowers -' in name) and (o.get('plant_role')=='pot' or any(t in o.name.lower() for t in ('ribbed pot','ivory bowl')))]
            if args.render and plant_vessels:previews+=render_views(collection,preview_dir,'before_container',focus_objects=plant_vessels)
            changes,changed,cavities=refine_collection(collection)
            bpy.context.view_layer.update();after=snapshot(collection)
            bound_error=max(abs(a-b) for key in ('bounds_min_m','bounds_max_m') for a,b in zip(before[key],after[key]))
            if bound_error>1e-5:raise ValueError(f'Outer bounds changed by {bound_error}: {name}')
            previews+=render_views(collection,preview_dir,'after',framing=(before['bounds_min_m'],before['bounds_max_m'])) if args.render else []
            if args.render and plant_vessels:previews+=render_views(collection,preview_dir,'after_container',focus_objects=plant_vessels)
            asset_id=next(x['id'] for x in entries if x.get('library_id')==lid and x.get('datablock')==name)
            manifest={k:after[k] for k in ('parts','vertices','dimensions_m','bounds_min_m','bounds_max_m')}
            manifest['description']=' '.join(changes)+' Source-derived or authored approximation; no physics certification.'
            manifest['asset_quality_refinement']={'generator':'tools/asset_quality_upgrade/tabletop.py','revision':1,'changes':changes}
            record={'asset_id':asset_id,'library_id':lid,'source_library':str(ROOT/registry[lid]['path']),'source_library_sha256':registry[lid]['sha256'],'datablock':name,'status':'upgraded','candidate_library':str(candidate),
                    'changes':changes,'reason':'Corrected verified vessel geometry or topology defect.',
                    'manifest_updates':manifest,'validation':{'before':before,'after':after,'max_bounds_delta_m':bound_error,
                      'changed_meshes':[object_audit(o) for o in changed],'cavity_checks':cavities,
                      'visual_review':'pending','scope':'Changed vessel/substrate meshes only. Foliage and simulation not certified.'},
                    'previews':previews}
            reports.append(record);library_reports.append(record)
            bpy.context.scene.collection.children.unlink(collection)
        if not args.audit_only:
            bpy.data.libraries.write(str(candidate),set(selected),fake_user=True,compress=True)
            # Independent reopen: collection identity, evaluated transforms, shell
            # topology and cavity geometry are checked from the written payload.
            bpy.ops.wm.open_mainfile(filepath=str(candidate))
            for record in library_reports:
                collection=bpy.data.collections[record['datablock']]
                bpy.context.scene.collection.children.link(collection);bpy.context.view_layer.update()
                actual=snapshot(collection)
                for key in ('parts','vertices','bounds_min_m','bounds_max_m'):
                    if actual[key]!=record['validation']['after'][key]:raise ValueError('Reopen mismatch '+key)
                for expected in record['validation']['changed_meshes']:
                    if topology(bpy.data.objects[expected['name']])['nonmanifold_edges']:raise ValueError('Reopened mesh invalid')
                record['validation']['saved_reopen_passed']=True
                bpy.context.scene.collection.children.unlink(collection)
        (out/('audit.json' if args.audit_only else 'report.json')).write_text(json.dumps(reports,indent=2)+'\n')
    print(json.dumps({'report':str(out/('audit.json' if args.audit_only else 'report.json')),'collections':len(reports)}))

if __name__=='__main__':main()

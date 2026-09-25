"""Bounded Bullet drop/stack checks for current registered tabletop vessels.

Uses convex hulls for everyday exterior contact. It intentionally does not test
objects entering cavities, liquid containment, calibrated mass or every pose.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))

VESSELS=[
    'additional-444547-44-v1/additional-44-silver-serving-platter',
    'additional-444547-44-v1/additional-44-stylized-stemmed-vessel',
    'additional-444547-45-v1/additional-45-small-porcelain-vase',
    'additional-444547-45-v1/additional-45-tall-porcelain-vase',
    'ceramic-vase-v1/vase-rounded-ceramic',
]


def rigid(obj,kind='ACTIVE',shape='CONVEX_HULL'):
    import bpy
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True);bpy.context.view_layer.objects.active=obj
    bpy.ops.rigidbody.object_add()
    body=obj.rigid_body;body.type=kind;body.collision_shape=shape
    body.use_margin=True;body.collision_margin=.0005
    body.friction=.6;body.restitution=.02;body.mass=.25
    body.linear_damping=.1;body.angular_damping=.2


def geometry(identity,height,tilt=0):
    import bpy
    from mathutils import Matrix,Vector
    from aha3d.blender.roomkit import place_asset
    root=place_asset(identity,project_root=ROOT)
    bpy.context.view_layer.update()
    objects=[o for o in root.children_recursive if o.type=='MESH']
    verts,faces,mats,slots=[],[],[],[]
    for obj in objects:
        offset=len(verts)
        verts.extend(obj.matrix_world@v.co for v in obj.data.vertices)
        lookup=[]
        for mat in obj.data.materials:
            if mat not in mats:mats.append(mat)
            lookup.append(mats.index(mat))
        for poly in obj.data.polygons:
            faces.append([offset+i for i in poly.vertices])
            slots.append(lookup[poly.material_index] if lookup else 0)
    mesh=bpy.data.meshes.new('Rigid vessel surface');mesh.from_pydata(verts,[],faces);mesh.update()
    for material in mats:mesh.materials.append(material)
    for poly,slot in zip(mesh.polygons,slots):poly.material_index=slot;poly.use_smooth=True
    for child in list(root.children_recursive):bpy.data.objects.remove(child,do_unlink=True)
    bpy.data.objects.remove(root,do_unlink=True)
    obj=bpy.data.objects.new('Rigid vessel',mesh);bpy.context.scene.collection.objects.link(obj)
    obj.location.z=height;obj.rotation_euler.x=tilt
    rigid(obj)
    return obj


def bounds(obj):
    import bpy
    from mathutils import Vector
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    points=[evaluated.matrix_world@Vector(corner) for corner in evaluated.bound_box]
    return [min(p[i] for p in points) for i in range(3)],[max(p[i] for p in points) for i in range(3)]


def world():
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene=bpy.context.scene;scene.render.fps=24;scene.frame_end=240
    bpy.ops.mesh.primitive_cube_add(size=1,location=(0,0,-.05))
    floor=bpy.context.object;floor.name='Support plane';floor.dimensions=(3,3,.1)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    rigid(floor,'PASSIVE','BOX')
    rb=scene.rigidbody_world;rb.substeps_per_frame=10;rb.solver_iterations=30
    rb.point_cache.frame_start=1;rb.point_cache.frame_end=240
    return scene


def simulate(objects):
    import bpy
    samples=[]
    for frame in range(1,241):
        bpy.context.scene.frame_set(frame)
        samples.append([bounds(obj) for obj in objects])
    for index,obj in enumerate(objects):
        last=[sample[index] for sample in samples[-24:]]
        assert all(math.isfinite(x) for row in last for bound in row for x in bound),obj.name
        assert min(row[0][2] for row in last)>-.004,(obj.name,'floor penetration',last[-1])
        motion=max(max(row[k][j] for row in last)-min(row[k][j] for row in last)
                   for k in range(2) for j in range(3))
        assert motion<.003,(obj.name,'not settled',motion)
        assert max(abs(last[-1][k][j]) for k in range(2) for j in range(2))<1.4,'fell off support'
    return {'frames':240,'duration_seconds':10,'final_bounds':samples[-1],
            'last_second_max_bounds_motion_m':[max(max(row[i][k][j] for row in samples[-24:])-
                 min(row[i][k][j] for row in samples[-24:])
                 for k in range(2) for j in range(3)) for i in range(len(objects))]}


def main():
    import bpy
    from integrate import digest,write
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.out.mkdir(parents=True,exist_ok=True)
    report={'schema_version':1,'blender':bpy.app.version_string,'job_id':os.environ.get('INDOOR_RUN_ID'),
            'registry_sha256':digest(ROOT/'assets/registry.json'),'collision_shape':'CONVEX_HULL',
            'mass_kg_assumed':.25,'collision_margin_m':.0005,'drops':[],
            'scope':'Five vessels dropped 0.25 m with 5 degree initial tilt; two-platter exterior stacking. No cavity insertion, liquid, fracture or arbitrary interaction certification.'}
    for identity in VESSELS:
        world();obj=geometry(identity,.25,math.radians(5))
        result=simulate([obj]);result['asset_id']=identity;report['drops'].append(result)
        assert -.004<result['final_bounds'][0][0][2]<.006,('did not settle on floor',identity,result['final_bounds'])
        write(args.out/'report.json',report)
    scene=world();lower=geometry(VESSELS[0],.03);upper=geometry(VESSELS[0],.23)
    report['platter_stack']=simulate([lower,upper])
    lower_bounds,upper_bounds=report['platter_stack']['final_bounds']
    assert -.004<lower_bounds[0][2]<.006,('lower platter did not settle on floor',lower_bounds)
    gap=upper_bounds[0][2]-lower_bounds[1][2]
    assert -.004<gap<.008,('platter stacking gap',gap)
    report['platter_stack']['support_gap_m']=gap
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str((args.out/'platter_stack.blend').resolve()))
    report['status']='passed';write(args.out/'report.json',report)
    print(json.dumps({'status':'passed','drop_cases':len(VESSELS),'stack_cases':1}))


if __name__=='__main__':main()

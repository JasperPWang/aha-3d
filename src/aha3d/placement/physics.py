"""Disposable Blender/Bullet gravity test with verified convex component shapes."""
import hashlib
import math


def convex_properties(part, cache):
    import bmesh
    import numpy as np
    key=hashlib.sha256(part['v'].tobytes()+part['f'].tobytes()).hexdigest()
    if key in cache: return cache[key]
    if not part['closed'] or len(part['v'])>20000:
        return None
    v=part['v']; f=part['f']; origin=v.mean(0); q=v-origin
    signed=np.einsum('ij,ij->i',q[f[:,0]],np.cross(q[f[:,1]],q[f[:,2]]))/6
    volume=abs(float(signed.sum()))
    if volume<1e-10: return None
    center=origin+(signed[:,None]*(q[f[:,0]]+q[f[:,1]]+q[f[:,2]])/4).sum(0)/signed.sum()
    bm=bmesh.new()
    try:
        for point in q: bm.verts.new(point)
        bmesh.ops.convex_hull(bm,input=list(bm.verts),use_existing_faces=False)
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        convex_volume=abs(bm.calc_volume(signed=True))
    finally: bm.free()
    # A loose hull is unsuitable for testing chairs under tables or shelf cavities.
    if convex_volume<1e-10 or not .98<=volume/convex_volume<=1.02: return None
    cache[key]=(volume,center); return cache[key]


def simulate(objects,config,issues,issue):
    import bpy
    import numpy as np
    if config['physics']=='off':
        return dict(status='disabled',tested=0,reason='Explicit physics=off')
    original=bpy.context.window.scene; cache={}; eligible=[]; skipped=[]
    for o in objects:
        if o['fixed'] or o['role'] in ('floor','wall','ceiling','structure','cover','fixture','person'): continue
        reason=None
        if o['animated']: reason='Animated/constrained root or deformed body'
        elif o['support']['status'] in ('unknown','missing'): reason='Support or mounting intent unresolved'
        elif o['grouping']!='semantic_root': reason='Complete rigid object grouping unverified'
        props=[]
        if reason is None:
            props=[convex_properties(p,cache) for p in o['parts']]
            if any(p is None for p in props): reason='Concave, open, degenerate or oversized component; no faithful convex compound available'
        if reason is None and len(eligible)>=config['max_simulated_objects']: reason='Configured simulation object budget reached'
        if reason:
            skipped.append(dict(object=o['id'],reason=reason)); continue
        total=sum(p[0] for p in props)
        center=sum(p[0]*p[1] for p in props)/total
        eligible.append((o,center))
    if skipped:
        issue(issues,'unverified','physics_skipped',[p['object'] for p in skipped],
              f'{len(skipped)} movable objects could not be stability-tested safely.',
              'Inspect per-object reasons in coverage.physics.skipped; provide complete roots/supports or convex component collision geometry.',skipped=skipped)
    if not eligible: return dict(status='no_eligible_objects',tested=0,skipped=skipped)
    sim=bpy.data.scenes.new('Placement diagnostic physics'); bpy.context.window.scene=sim
    sim.render.fps=60; sim.frame_start=1; sim.frame_end=1+math.ceil(config['simulation_seconds']*60)
    sim.gravity=(0,0,-9.81); made=[]; meshes=[]
    def add(name,v,f,kind,shape):
        mesh=bpy.data.meshes.new(name); meshes.append(mesh); mesh.from_pydata(v,[],f); mesh.update()
        obj=bpy.data.objects.new(name,mesh); made.append(obj); sim.collection.objects.link(obj)
        bpy.context.view_layer.objects.active=obj; obj.select_set(True)
        bpy.ops.rigidbody.object_add(); obj.rigid_body.type=kind; obj.rigid_body.collision_shape=shape
        obj.rigid_body.use_margin=True; obj.rigid_body.collision_margin=.001
        obj.rigid_body.friction=.5; obj.rigid_body.restitution=0
        obj.select_set(False)
        return obj
    dynamic={}; eligible_ids={o['id'] for o,c in eligible}
    try:
        for o in objects:
            if o['id'] in eligible_ids or o['role']=='person': continue
            for idx,p in enumerate(o['parts']):
                add(o['id']+str(idx),p['v'].tolist(),p['f'].tolist(),'PASSIVE','MESH')
        for o,center in eligible:
            parent=add(o['id'],[],[],'ACTIVE','COMPOUND'); parent.location=center
            parent.rigid_body.mass=o['override'].get('mass_kg',1.)
            parent.rigid_body.use_deactivation=False
            for idx,p in enumerate(o['parts']):
                child=add(o['id']+str(idx),(p['v']-center).tolist(),p['f'].tolist(),'ACTIVE','CONVEX_HULL')
                child.parent=parent
            dynamic[o['id']]=parent
        bpy.context.view_layer.update()
        sim.rigidbody_world.substeps_per_frame=4; sim.rigidbody_world.solver_iterations=20
        sim.rigidbody_world.point_cache.frame_start=1; sim.rigidbody_world.point_cache.frame_end=sim.frame_end
        first={}; maximum={oid:0. for oid in dynamic}; penultimate={}
        for frame in range(1,sim.frame_end+1):
            sim.frame_set(frame); dg=bpy.context.evaluated_depsgraph_get()
            for oid,obj in dynamic.items():
                matrix=obj.evaluated_get(dg).matrix_world.copy()
                if frame==1: first[oid]=matrix
                maximum[oid]=max(maximum[oid],(matrix.translation-first[oid].translation).length)
                if frame==sim.frame_end-1: penultimate[oid]=matrix
        rows=[]
        for oid,obj in dynamic.items():
            matrix=obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
            delta=(matrix.translation-first[oid].translation).length
            angle=math.degrees(first[oid].to_quaternion().rotation_difference(matrix.to_quaternion()).angle)
            speed=(matrix.translation-penultimate[oid].translation).length*60
            row=dict(object=oid,final_displacement_m=delta,maximum_displacement_m=maximum[oid],rotation_degrees=angle,final_speed_m_s=speed)
            rows.append(row)
            if maximum[oid]>config['movement_m'] or angle>config['rotation_degrees']:
                issue(issues,'warning','unstable',[oid],f'Gravity test moved the object {maximum[oid]:.4f} m; final rotation {angle:.2f} degrees.',
                      'Inspect support, initial penetration, mounting and mass assumptions before editing; this test never changes the source.',**row)
            elif speed>.01:
                issue(issues,'unverified','not_settled',[oid],'The short simulation ended while this object was still moving.',
                      'Increase simulation_seconds or inspect the support and collision proxy.',**row)
        return dict(status='completed',tested=len(rows),seconds=config['simulation_seconds'],fps=60,substeps=4,
                    solver_iterations=20,friction=.5,mass_model='1 kg per object unless overridden; uniform component-volume center of mass',
                    shape='compound of closed components with volume within 2% of convex hull; other geometry static triangle meshes',
                    skipped=skipped,objects=rows)
    finally:
        bpy.context.window.scene=original
        bpy.data.scenes.remove(sim)
        for o in made:
            if o.name in bpy.data.objects: bpy.data.objects.remove(o,do_unlink=True)
        for mesh in meshes:
            if mesh.users==0: bpy.data.meshes.remove(mesh)

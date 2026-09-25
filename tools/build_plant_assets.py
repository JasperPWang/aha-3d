"""Audit authored plants and create a complete editable broad-leaf plant asset.

Run background Blender. Input scenes/libraries are read-only.
Stages: audit, build, export. Inspect the build before exporting a library version.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'src/aha3d').is_dir())
sys.path.insert(0, str(ROOT / 'src'))
from aha3d.blender.roomkit import box, area_light
from aha3d.blender.semantics import tag_root, tag_surface
from aha3d.blender.orientation import tag_orientation
from aha3d.blender.stage import gpu

ASSET_NAME = 'RK Plant - Broadleaf Ceramic'
ITEM_ID = 'plants-v1/plant-broadleaf-ceramic'
SOURCES = [
    {'id': 'g0025-orchid', 'blend': 'scenes/living_room_kitchen_g0025/blender/walkthrough_cabinet_animation/living_room_kitchen_operable_cabinets.blend',
     'prefixes': ['Orchid bowl', 'Orchid broad leaf', 'Orchid stem', 'Simplified orchid petal'],
     'anchor': [3.82,4.24,.523], 'leaf_prefix': 'Orchid broad leaf',
     'diagnosis_from_builder': 'Leaves exist as seven ellipsoids; stems and petals are separate ungrouped parts.'},
    {'id': 'g0064-planter', 'blend': 'scenes/living_room_piano_g0064/blender/room_source.blend',
     'prefixes': ['Planter', 'Plant stem', 'Plant leaf'],
     'anchor': [3.8,.01,1.47], 'leaf_prefix': 'Plant leaf', 'select_near_x': 3.8,
     'diagnosis_from_builder': 'Two shelf plants have nine ellipsoid leaves each; leaf material is the shared upholstery material.'},
    {'id': 'g0070-flower-vase', 'blend': 'scenes/minimal_living_g0070/blender/fresh_white_20260909/pi3x_white_supported.blend',
     'prefixes': ['Vase', 'Flower stem', 'Flower mass'],
     'anchor': [.40,4.08,.65], 'leaf_prefix': 'Leaf',
     'diagnosis_from_builder': 'Vase arrangement contains seventeen stems and small flower masses; no leaves were authored.'},
]


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + '\n')


def material(name, color, roughness=.65):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*color, 1)
    node = mat.node_tree.nodes.get('Principled BSDF')
    node.inputs['Base Color'].default_value = (*color, 1)
    node.inputs['Roughness'].default_value = roughness
    return mat


def bounds(objects):
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for obj in objects:
        if obj.type not in {'MESH', 'CURVE', 'SURFACE'}:
            continue
        evaluated = obj.evaluated_get(dg)
        mesh = evaluated.to_mesh()
        pts.extend(evaluated.matrix_world @ v.co for v in mesh.vertices)
        evaluated.to_mesh_clear()
    if not pts:
        raise ValueError('No geometry')
    return (Vector([min(p[k] for p in pts) for k in range(3)]),
            Vector([max(p[k] for p in pts) for k in range(3)]))


def copy_evaluated(source, destination_scene, transform):
    dg = bpy.context.evaluated_depsgraph_get()
    evaluated = source.evaluated_get(dg)
    mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=dg)
    obj = bpy.data.objects.new(source.name, mesh)
    destination_scene.collection.objects.link(obj)
    obj.matrix_world = transform @ evaluated.matrix_world
    return obj


def studio(scene, objects, output, samples=32, resolution=1000, closeups=None):
    """Preserve geometry/materials; build only a separate inspection studio."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    gpu(scene)
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.exposure = 0
    scene.render.resolution_x = scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False
    scene.world = bpy.data.worlds.new('Plant studio world')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.45,.45,.45,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = .5
    low, high = bounds(objects)
    center = (low+high)/2
    extent = max(high-low)
    ground = material('Plant studio sand', (.29,.30,.28), .9)
    box('Plant studio ground', (0,0,low.z-.008), (extent*20,extent*20,.014), ground, edge=0)
    for label, offset, power in [('Key',(2,-3,4),230), ('Fill',(-3,-1,2),150), ('Rim',(1,3,4),200)]:
        area_light('Plant studio '+label, tuple(center+Vector(offset)*extent), tuple(center), power*extent**2, extent*2)
    camera_data = bpy.data.cameras.new('Plant inspection camera')
    camera = bpy.data.objects.new('Plant inspection camera', camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = 'ORTHO'
    camera_data.clip_start = .001
    camera_data.clip_end = 100
    clay = material('Plant geometry clay', (.56,.58,.57), .75)
    captures = []
    views = [('whole_material',center,Vector((1.1,-1.8,1.05))*extent,extent*1.4,False),
             ('whole_clay',center,Vector((1.1,-1.8,1.05))*extent,extent*1.4,True),
             ('top_material',center,Vector((0,0,3))*extent,extent*1.35,False)]
    for label, point, scale in closeups or []:
        views.append((label+'_material',Vector(point),Vector((.5,-.9,1.1))*scale,scale,False))
        views.append((label+'_clay',Vector(point),Vector((.5,-.9,1.1))*scale,scale,True))
    for label,target,offset,scale,use_clay in views:
        camera.location = target+offset
        camera.rotation_euler = (target-camera.location).to_track_quat('-Z','Y').to_euler()
        camera_data.ortho_scale = scale
        scene.view_layers[0].material_override = clay if use_clay else None
        scene.render.filepath = str(output/(label+'.png'))
        bpy.context.view_layer.update()
        bpy.ops.render.render(write_still=True)
        captures.append(scene.render.filepath)
    scene.view_layers[0].material_override = None
    return captures


def audit_sources(args):
    out = args.out/'before'
    out.mkdir(parents=True, exist_ok=True)
    reports = []
    for item in SOURCES:
        path = ROOT/item['blend']
        source_hash = digest(path)
        bpy.ops.wm.open_mainfile(filepath=str(path))
        bpy.context.scene.frame_set(1)
        bpy.context.view_layer.update()
        matches = [o for o in bpy.context.scene.objects if o.type in {'MESH','CURVE'}
                   and any(o.name.startswith(prefix) for prefix in item['prefixes'])]
        selected = []
        records = []
        for obj in matches:
            low,high = bounds([obj])
            include = 'select_near_x' not in item or abs((low.x+high.x)/2-item['select_near_x']) < .7
            records.append({'name':obj.name,'type':obj.type,'parent':obj.parent.name if obj.parent else None,
                            'hide_render':obj.hide_render,'hide_viewport':obj.hide_viewport,
                            'visible_in_current_view_layer':obj.visible_get(),
                            'materials':[m.name if m else None for m in obj.data.materials],
                            'bounds_min':list(low),'bounds_max':list(high),'selected':include})
            if include:
                selected.append(obj)
        if not selected:
            raise ValueError('Missing expected source plant: '+item['id'])
        stage = bpy.data.scenes.new('Plant source inspection '+item['id'])
        transform = Matrix.Translation(-Vector(item['anchor']))
        copied = [copy_evaluated(o,stage,transform) for o in selected]
        bpy.context.window.scene = stage
        bpy.context.view_layer.update()
        row = dict(item)
        row.update(source_sha256=source_hash, source_objects=records,
                   selected_parts=len(selected), selected_leaves=sum(o.name.startswith(item['leaf_prefix']) for o in selected),
                   all_matching_leaf_objects=sum(o.name.startswith(item['leaf_prefix']) for o in matches),
                   images=studio(stage,copied,out/item['id'],args.samples,args.resolution),
                   visual_review='pending', source_unchanged=digest(path)==source_hash)
        reports.append(row)
        write_json(args.out/'source_audit.json',reports)
        print(json.dumps({'source_audit':item['id'],'parts':row['selected_parts'],'leaves':row['selected_leaves']}),flush=True)
    return reports


def build_candidate(args):
    source_path=ROOT/SOURCES[0]['blend']
    source_hash=digest(source_path)
    library_path=ROOT/'assets/roomkit/v1/roomkit_furniture_materials.blend'
    material_hash=digest(library_path)
    bpy.ops.wm.open_mainfile(filepath=str(source_path))
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    source_pot=bpy.data.objects['Orchid bowl']
    stage=bpy.data.scenes.new('Broadleaf plant candidate')
    scale=Matrix.Diagonal((.55,.55,1.15,1.))
    pot=copy_evaluated(source_pot,stage,scale@Matrix.Translation(-Vector(SOURCES[0]['anchor'])))
    pot.name='Broadleaf ceramic pot'
    transform=pot.matrix_world.copy()
    for vertex in pot.data.vertices:
        vertex.co=transform@vertex.co
    pot.matrix_world=Matrix.Identity(4)
    # The source lathe has an uncapped lower ring and coincident inner-center
    # vertices. Close the physical base while retaining the adapted bowl profile.
    bm=bmesh.new();bm.from_mesh(pot.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
    lowest=min(v.co.z for v in bm.verts)
    lower_edges=[e for e in bm.edges if e.is_boundary and all(abs(v.co.z-lowest)<1e-5 for v in e.verts)]
    if lower_edges:
        bmesh.ops.holes_fill(bm,edges=lower_edges,sides=0)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    remaining_boundary=sum(e.is_boundary for e in bm.edges)
    if remaining_boundary:
        raise ValueError('Adapted pot remains open at {} boundary edges'.format(remaining_boundary))
    bm.to_mesh(pot.data);bm.free();pot.data.update()
    material_names=['RK | Deep green orchid leaves','RK | Charcoal ceramic bowl']
    with bpy.data.libraries.load(str(library_path),link=False) as (source,dest):
        if not all(name in source.materials for name in material_names):
            raise ValueError('Required reusable leaf/pot materials missing')
        dest.materials=material_names
    leaf_source,pot_mat=dest.materials
    bpy.context.window.scene=stage
    root=bpy.data.objects.new(ASSET_NAME+' | semantic root',None)
    stage.collection.objects.link(root)
    tag_root(root,'decor/plants',instance_id='plant-broadleaf-ceramic',asset_id=ITEM_ID)
    tag_orientation(root,{'schema_version':1,'front_axis':'-Y','up_axis':'Z','symmetry':'none',
        'origin':'floor_center','semantic_front':'generic','status':'authored',
        'evidence':'tools/build_plant_assets.py: lower presentation foliage toward -Y, balanced XY extents and physical pot base at Z0; final preview review recorded separately'})
    root['plant_seed']=args.seed
    root['plant_type']='Broad-leaf tropical ornamental; authored approximate plant, no botanical species claim'
    root['plant_generator_version']=1
    root['pot_center_local']=[0.,0.,0.]
    root['source_pot']='scene/g0025/orchid-planter: Orchid bowl; XY scale0.55, Z scale1.15; base repaired'
    pot.parent=root;pot.data.materials.clear();pot.data.materials.append(pot_mat)
    pot['plant_role']='pot';tag_surface(pot,'pot_ceramic')
    soil_mat=material('Plant potting soil',(.045,.024,.012),.98)
    nodes=soil_mat.node_tree.nodes;links=soil_mat.node_tree.links
    noise=nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=90
    bump=nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.32;bump.inputs['Distance'].default_value=.003
    links.new(noise.outputs['Fac'],bump.inputs['Height']);links.new(bump.outputs['Normal'],nodes.get('Principled BSDF').inputs['Normal'])
    stem_mat=material('Plant green petioles',(.07,.15,.025),.56)
    vein_mat=material('Plant subtle leaf veins',(.10,.21,.045),.5)
    leaf_mats=[]
    for index,factor in enumerate((.8,1.,1.18)):
        mat=leaf_source.copy();mat.name='Broadleaf foliage tone '+str(index)
        for node in mat.node_tree.nodes:
            if node.type=='VALTORGB':
                for element in node.color_ramp.elements:
                    element.color=tuple(min(.7,c*factor) for c in element.color[:3])+(1.,)
        bsdf=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        bsdf.inputs['Roughness'].default_value=.46
        leaf_mats.append(mat)
    soil_z=.195
    bpy.ops.mesh.primitive_cylinder_add(vertices=64,radius=.145,depth=.025,location=(0,0,soil_z-.0125))
    soil=bpy.context.object;soil.name='Broadleaf visible soil';soil.parent=root
    soil.data.materials.append(soil_mat);soil['plant_role']='soil';tag_surface(soil,'soil')
    rng=random.Random(args.seed)
    attachments=[]
    leaf_centers=[]

    def curve_parts(name,paths,radius,mat,role):
        data=bpy.data.curves.new(name,'CURVE');data.dimensions='3D'
        data.bevel_depth=radius;data.bevel_resolution=2;data.resolution_u=1
        data.use_fill_caps=True
        for points in paths:
            spline=data.splines.new('POLY');spline.points.add(len(points)-1)
            for j,(vertex,point) in enumerate(zip(spline.points,points)):
                vertex.co=(*point,1.);vertex.radius=1-.45*j/max(1,len(points)-1)
        obj=bpy.data.objects.new(name,data);stage.collection.objects.link(obj)
        obj.parent=root;data.materials.append(mat);obj['plant_role']=role
        tag_surface(obj,'plant_stem' if role=='petiole' else 'plant_vein')
        return obj

    for pair in range(10):
        angle=-math.pi/2+pair*math.pi/10+rng.uniform(-.045,.045)
        length=.31-.010*pair+rng.uniform(-.018,.018)
        width=.128-.004*pair+rng.uniform(-.009,.009)
        radial=.070+rng.uniform(0,.035)
        leaf_z=.37+.028*pair
        rise=.035+rng.uniform(0,.020)
        droop=.075-.003*pair
        phase=rng.uniform(0,2*math.pi)
        for opposite in range(2):
            leaf_id='leaf-{:02d}'.format(pair*2+opposite+1)
            a=angle+math.pi*opposite
            direction=Vector((math.cos(a),math.sin(a),0))
            sideways=Vector((-math.sin(a),math.cos(a),0))
            base=direction*radial+Vector((0,0,leaf_z+.045*opposite))
            root_point=direction*.026+Vector((0,0,soil_z-.010))
            control=direction*.036+Vector((0,0,(soil_z+base.z)*.56))
            petiole_points=[(1-t)**2*root_point+2*(1-t)*t*control+t*t*base for t in [i/18 for i in range(19)]]
            petiole=curve_parts('Broadleaf '+leaf_id+' petiole',[petiole_points],.0038,stem_mat,'petiole')
            petiole['leaf_id']=leaf_id
            def surface(s,u):
                center=base+direction*(length*s)+Vector((0,0,rise*math.sin(math.pi*s)-droop*s*s))
                half_width=width/2*math.sin(math.pi*s)**.72*(.52+.48*s**.28)
                flutter=.0035*math.sin(3*math.pi*s+phase)*u*u*math.sin(math.pi*s)
                fold=-.014*u*u*math.sin(math.pi*s)
                return center+sideways*(half_width*u)+Vector((0,0,fold+flutter))
            nlong,nwide=24,11
            verts=[surface(0,0)]
            for i in range(1,nlong):
                for j in range(nwide):
                    verts.append(surface(i/nlong,-1+2*j/(nwide-1)))
            end=len(verts);verts.append(surface(1,0))
            faces=[]
            for j in range(nwide-1):faces.append((0,1+j,2+j))
            for i in range(nlong-2):
                for j in range(nwide-1):
                    k=1+i*nwide+j;faces.append((k,k+nwide,k+nwide+1,k+1))
            last=1+(nlong-2)*nwide
            for j in range(nwide-1):faces.append((last+j,end,last+j+1))
            mesh=bpy.data.meshes.new('Broadleaf '+leaf_id+' shaped mesh');mesh.from_pydata(verts,[],faces);mesh.update()
            leaf=bpy.data.objects.new('Broadleaf '+leaf_id+' blade',mesh);stage.collection.objects.link(leaf)
            leaf.parent=root;mesh.materials.append(leaf_mats[(pair+opposite)%3])
            for polygon in mesh.polygons:polygon.use_smooth=True
            thick=leaf.modifiers.new('Real leaf thickness','SOLIDIFY');thick.thickness=.0007;thick.offset=0
            leaf['plant_role']='leaf';leaf['leaf_id']=leaf_id
            leaf['blade_base_local']=list(base);leaf['petiole_object']=petiole.name
            leaf['blade_length_m']=length;leaf['blade_width_m']=width
            tag_surface(leaf,'plant_leaf')
            main=[surface(i/30,0)+Vector((0,0,.00065)) for i in range(31)]
            rib=curve_parts('Broadleaf '+leaf_id+' midrib',[main],.00085,vein_mat,'midrib');rib['leaf_id']=leaf_id
            paths=[]
            for index in range(1,8):
                s=.09+index*.095
                for sign in (-1,1):
                    paths.append([surface(s+.070*t,sign*.90*t)+Vector((0,0,.00048)) for t in [j/8 for j in range(9)]])
            veins=curve_parts('Broadleaf '+leaf_id+' side veins',paths,.00028,vein_mat,'veins');veins['leaf_id']=leaf_id
            gap=(verts[0]-petiole_points[-1]).length
            attachments.append({'leaf_id':leaf_id,'blade':leaf.name,'petiole':petiole.name,
                'blade_vertex_base':list(verts[0]),'petiole_end':list(petiole_points[-1]),
                'petiole_soil_start':list(root_point),'base_gap_m':gap,'blade_vertices':len(verts)})
            leaf_centers.append(surface(.5,0))
    root['plant_leaf_count']=len(attachments)
    root['leaf_attachments_json']=json.dumps(attachments)
    bpy.context.view_layer.update()
    plant_objects=list(root.children_recursive)
    low,high=bounds(plant_objects)
    pot_low,pot_high=bounds([pot]);soil_low,soil_high=bounds([soil])
    xy_center=(low+high)/2
    if abs(pot_low.z)>2e-5 or max(abs(xy_center.x),abs(xy_center.y))>2e-5:
        raise ValueError('Physical pot support or balanced XY origin failed')
    if max(a['base_gap_m'] for a in attachments)>1e-7:
        raise ValueError('Detached petiole/leaf junction')
    if any(Vector(a['petiole_soil_start']).xy.length>.145 or not soil_low.z<=a['petiole_soil_start'][2]<=soil_high.z for a in attachments):
        raise ValueError('Stem root does not enter the soil volume')
    # Save a compact asset-authoring scene, not an in-memory copy of the room.
    for other in list(bpy.data.scenes):
        if other!=stage:bpy.data.scenes.remove(other)
    keep={root,*plant_objects}
    for obj in list(bpy.data.objects):
        if obj not in keep:bpy.data.objects.remove(obj,do_unlink=True)
    bpy.data.orphans_purge(do_recursive=True)
    stage.frame_start=stage.frame_end=1
    candidate=args.out/'candidate';candidate.mkdir(parents=True,exist_ok=True)
    scene_path=candidate/'plant_source.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(scene_path))
    report={'schema_version':1,'item_id':ITEM_ID,'name':ASSET_NAME,'seed':args.seed,
        'source_scene':str(source_path),'source_sha256':source_hash,
        'material_library':str(library_path),'material_library_sha256':material_hash,
        'source_pot':'Orchid bowl','source_pot_scale':[.55,.55,1.15],
        'pot_adaptations':['Merged coincident inner-center vertices','Filled bottom boundary ring','Kept adapted source bowl profile'],
        'pot_boundary_edges':remaining_boundary,'pot_base_z':pot_low.z,
        'geometry_bounds_min':list(low),'geometry_bounds_max':list(high),'dimensions_m':list(high-low),
        'xy_bounds_center':list(xy_center)[:2],'root_origin':'physical pot base center at (0,0,0); paired XY leaf extents avoid foliage-origin drift',
        'leaf_count':len(attachments),'attachments':attachments,'soil_bounds_min':list(soil_low),'soil_bounds_max':list(soil_high),
        'source_scene_saved':str(scene_path),'candidate_sha256':digest(scene_path),
        'orientation':json.loads(root['asset_orientation_json']),
        'visual_review':'pending','limitations':['Authored approximate ornamental plant; no botanical species or reference reconstruction claim','No general leaf-leaf collision guarantee; overlapping foliage is part of the intended silhouette']}
    report['images']=studio(stage,plant_objects,candidate,args.samples,args.resolution,
        [('leaf_closeup',leaf_centers[0],.30),('pot_closeup',(0,-.025,.18),.43)])
    report['source_unchanged']=digest(source_path)==source_hash
    report['material_library_unchanged']=digest(library_path)==material_hash
    write_json(args.out/'build_report.json',report)
    write_json(candidate/'export_selection.json',{'source_frame':1,'register_materials':False,'material_prefix':'NO_BULK_MATERIAL_EXPORT',
        'furniture':[{'root':root.name,'name':ASSET_NAME,'catalog':'Plants','orientation':report['orientation'],
         'description':'Complete broad-leaf potted plant with twenty shaped leaves, attached petioles, veins, visible soil and ceramic pot; seed '+str(args.seed)}]})
    print(json.dumps({'build':'complete; visual review pending','leaf_count':len(attachments),'dimensions_m':report['dimensions_m']}),flush=True)


def export_candidate(args):
    report=json.loads((args.out/'build_report.json').read_text())
    source=Path(report['source_scene_saved'])
    if digest(source)!=report['candidate_sha256']:
        raise ValueError('Candidate source changed after validation')
    if digest(Path(report['source_scene']))!=report['source_sha256']:
        raise ValueError('Original pot source changed after candidate validation')
    if digest(Path(report['material_library']))!=report['material_library_sha256']:
        raise ValueError('Original material library changed after candidate validation')
    bpy.ops.wm.open_mainfile(filepath=str(source))
    source_root=bpy.data.objects[ASSET_NAME+' | semantic root']
    root_properties={k:source_root[k] for k in source_root.keys()}
    part_properties={o.name:{k:o[k] for k in o.keys()} for o in source_root.children_recursive}
    export_script=ROOT/'.agents/skills/blender-roomkit/scripts/export_assets.py'
    spec=importlib.util.spec_from_file_location('plant_static_exporter',export_script)
    exporter=importlib.util.module_from_spec(spec);spec.loader.exec_module(exporter)
    old_argv=sys.argv
    try:
        sys.argv=[str(export_script),'--','--config',str(args.out/'candidate/export_selection.json'),'--out',str(args.library_out)]
        exporter.main()
    finally:
        sys.argv=old_argv
    library=args.library_out/'roomkit_furniture_materials.blend'
    manifest_path=args.library_out/'manifest.json'
    manifest=json.loads(manifest_path.read_text())
    item=manifest['furniture'][0]
    # The verified static exporter bakes geometry. Enrich only this new plant
    # collection with the authoring metadata before the final native write.
    exported=bpy.data.collections[ASSET_NAME]
    exported_root=next(o for o in exported.all_objects if o.type=='EMPTY' and o.parent is None)
    for key,value in root_properties.items():
        if key not in {'asset_orientation_json','asset_front_axis','asset_up_axis','asset_origin'}:
            exported_root[key]=value
    exported['semantic_class']='decor/plants'
    exported['plant_seed']=report['seed']
    for obj in exported.all_objects:
        stem,suffix=obj.name.rsplit('.',1) if '.' in obj.name else (obj.name,'')
        source_name=obj.name if obj.name in part_properties else stem if suffix.isdigit() else obj.name
        if source_name not in part_properties:
            if obj.type=='MESH':raise ValueError('Cannot bind exported metadata to source part '+obj.name)
            continue
        for key,value in part_properties[source_name].items():obj[key]=value
        obj['source_part_name']=source_name
        if obj.get('petiole_object'):
            obj['source_petiole_name']=obj['petiole_object']
            del obj['petiole_object']
            obj['petiole_leaf_id']=obj['leaf_id']
    exported_attachments=json.loads(exported_root['leaf_attachments_json'])
    for attachment in exported_attachments:
        for key in ('blade','petiole'):attachment['source_'+key+'_name']=attachment.pop(key)
    exported_root['leaf_attachments_json']=json.dumps(exported_attachments)
    exported_root['plant_attachment_contract']='Resolve leaf_id with plant_role=leaf/petiole among one owning semantic root descendants; source object names are provenance only'
    exported_materials={m for o in exported.all_objects if o.type=='MESH' for m in o.data.materials if m}
    bpy.data.libraries.write(str(library),{exported,*exported_materials},path_remap='RELATIVE',fake_user=True,compress=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with bpy.data.libraries.load(str(library),link=False) as (src,dst):dst.collections=[ASSET_NAME]
    collection=dst.collections[0];bpy.context.scene.collection.children.link(collection)
    bpy.context.view_layer.update()
    objects=list(collection.all_objects)
    roots=[o for o in objects if o.get('semantic_class')=='decor/plants']
    if len(roots)!=1 or roots[0].get('plant_leaf_count')!=20:
        raise ValueError('Reopened semantic root or seed metadata missing')
    if any(not o.get('surface_role') or not o.get('plant_role') for o in objects if o.type=='MESH'):
        raise ValueError('Reopened material role or plant part metadata missing')
    reopened_attachment_distances=[]
    for attachment in json.loads(roots[0]['leaf_attachments_json']):
        matches={role:[o for o in objects if o.get('leaf_id')==attachment['leaf_id'] and o.get('plant_role')==role] for role in ('leaf','petiole')}
        if any(len(group)!=1 for group in matches.values()):raise ValueError('Reopened stable attachment identifiers lost')
        blade,petiole=matches['leaf'][0],matches['petiole'][0]
        if blade.get('petiole_leaf_id')!=petiole['leaf_id'] or 'petiole_object' in blade:
            raise ValueError('Reopened attachment identifier contract lost')
        base=Vector(blade['blade_base_local'])
        found,point,normal,index=petiole.closest_point_on_mesh(petiole.matrix_world.inverted()@base)
        distance=((petiole.matrix_world@point)-base).length
        if not found or distance>.004:raise ValueError('Baked petiole does not touch authored blade base')
        reopened_attachment_distances.append(distance)
    blades=[o for o in objects if 'leaf-' in o.name and ' blade' in o.name]
    petioles=[o for o in objects if 'leaf-' in o.name and ' petiole' in o.name]
    pots=[o for o in objects if o.name.startswith('Broadleaf ceramic pot')]
    if len(blades)!=20 or len(petioles)!=20 or len(pots)!=1:
        raise ValueError('Export lost complete plant parts')
    low,high=bounds(objects);pot_low,pot_high=bounds(pots)
    if abs(pot_low.z)>2e-5 or max(abs((low+high)[i]/2) for i in range(2))>2e-5:
        raise ValueError('Export/reopen changed pot support or XY center')
    if any(o.library for o in objects):raise ValueError('Linked object dependency retained')
    if any(m and any(n.type=='TEX_IMAGE' and n.image and not n.image.packed_file for n in m.node_tree.nodes) for o in objects if o.type=='MESH' for m in o.data.materials):
        raise ValueError('Unpacked image dependency')
    baked_vertices=sum(len(o.data.vertices) for o in objects if o.type=='MESH')
    validation={'status':'passed','library':str(library),'library_sha256':digest(library),
        'candidate_sha256':report['candidate_sha256'],'leaf_count':len(blades),'petiole_count':len(petioles),
        'parts':sum(o.type=='MESH' for o in objects),'baked_vertices':baked_vertices,
        'dimensions_m':list(high-low),'pot_base_z':pot_low.z,
        'xy_recenter_from_source_m':[item['bounds_min_m'][i]-report['geometry_bounds_min'][i] for i in range(2)],
        'complete_editable_mesh_parts':True,'linked_object_dependencies':False,
        'semantic_root_and_all_part_roles_preserved':True,
        'attachment_contract':'per-owning-root leaf_id + plant_role; names are source provenance only',
        'reopened_leaf_base_to_petiole_surface_max_m':max(reopened_attachment_distances),
        'native_reopen_validation':'raw library appended in factory scene, full leaf/petiole/pot counts and physical support checked',
        'source_scene_unchanged':digest(Path(report['source_scene']))==report['source_sha256'],
        'material_library_unchanged':digest(Path(report['material_library']))==report['material_library_sha256']}
    validation['images']=studio(bpy.context.scene,objects,args.out/'reopened',args.samples,args.resolution)
    validation['candidate_unchanged']=digest(source)==report['candidate_sha256']
    validation['source_scene_unchanged']=digest(Path(report['source_scene']))==report['source_sha256']
    validation['material_library_unchanged']=digest(Path(report['material_library']))==report['material_library_sha256']
    if not all(validation[key] for key in ('candidate_unchanged','source_scene_unchanged','material_library_unchanged')):
        raise ValueError('Input candidate/source/material hash changed during export validation')
    manifest['furniture'][0]['semantic_class']='decor/plants'
    manifest['furniture'][0]['category']='decor/plants'
    manifest['furniture'][0]['generator']={'script':'tools/build_plant_assets.py','seed':report['seed'],'leaf_count':20}
    manifest['furniture'][0]['provenance']='provenance.json'
    write_json(manifest_path,manifest)
    write_json(args.library_out/'provenance.json',{'item_id':ITEM_ID,'source_scene':report['source_scene'],
        'source_sha256':report['source_sha256'],'candidate_sha256':report['candidate_sha256'],
        'material_library':report['material_library'],'material_library_sha256':report['material_library_sha256'],
        'seed':report['seed'],'pot_adaptations':report['pot_adaptations'],'source_pot_scale':report['source_pot_scale'],
        'orientation':report['orientation'],'leaf_count':report['leaf_count'],'leaf_attachment_max_gap_m':max(a['base_gap_m'] for a in report['attachments']),
        'physical_pot_base_z':validation['pot_base_z'],'xy_recenter_from_source_m':validation['xy_recenter_from_source_m'],
        'validation_report':str(args.out/'export_validation.json'),'source_unchanged':validation['source_scene_unchanged'],
        'limitations':report['limitations']})
    write_json(args.out/'export_validation.json',validation)
    print(json.dumps({'export':'passed','item_id':ITEM_ID,'library':str(library),'vertices':baked_vertices}),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',required=True,choices=['audit','build','export'])
    parser.add_argument('--out',type=Path,default=ROOT/'runs/plant_quality/20260910')
    parser.add_argument('--library-out',type=Path,default=ROOT/'assets/plants/v1')
    parser.add_argument('--seed',type=int,default=20260910)
    parser.add_argument('--samples',type=int,default=32)
    parser.add_argument('--resolution',type=int,default=1000)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    args.out=args.out.resolve();args.library_out=args.library_out.resolve()
    args.out.mkdir(parents=True,exist_ok=True)
    {'audit':audit_sources,'build':build_candidate,'export':export_candidate}[args.stage](args)


if __name__=='__main__':
    main()

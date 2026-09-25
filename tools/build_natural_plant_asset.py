"""Author and export a peace-lily-inspired plant in background Blender.

Preserves plants/v1 and source rooms. The build stage saves an editable candidate
before rendering. The export stage uses the verified static RoomKit exporter,
preserves per-part semantic metadata and checks evaluated geometry/materials.
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
from mathutils import Matrix, Quaternion, Vector

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'src/aha3d').is_dir())
sys.path.insert(0, str(ROOT/'src'))
from aha3d.blender.semantics import tag_root, tag_surface
from aha3d.blender.orientation import tag_orientation


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


shared = module(ROOT/'tools/build_plant_assets.py', 'existing_plant_inspection_helpers')
bounds, digest, write_json = shared.bounds, shared.digest, shared.write_json
ASSET_NAME = 'RK Plant - Peace Lily Natural'
ITEM_ID = 'plants-v2/plant-peace-lily-natural'
SOURCE_LIBRARY = ROOT/'assets/plants/v1/roomkit_furniture_materials.blend'
REFERENCE = 'https://gardeningsolutions.ifas.ufl.edu/mastergardener/resources/plantid/flowers-and-foliage/spathiphyllum/'


def shader_math(nodes, links, operation, left, right=0.):
    node = nodes.new('ShaderNodeMath'); node.operation = operation
    for index, value in enumerate((left, right)):
        if hasattr(value, 'node'): links.new(value, node.inputs[index])
        else: node.inputs[index].default_value = value
    return node.outputs[0]


def foliage_material(age, tone):
    """UV-aligned curved veins and restrained transmission, without vein tubes."""
    mat = bpy.data.materials.new('Natural leaf '+age+' '+str(tone))
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Roughness'].default_value = .43
    bsdf.inputs['IOR'].default_value = 1.42
    bsdf.inputs['Coat Weight'].default_value = .035
    bsdf.inputs['Coat Roughness'].default_value = .45
    uv = nodes.new('ShaderNodeTexCoord')
    separate = nodes.new('ShaderNodeSeparateXYZ'); links.new(uv.outputs['UV'], separate.inputs[0])
    # U is transverse [0,1], V is blade length [0,1].
    transverse = shader_math(nodes, links, 'SUBTRACT', shader_math(nodes, links, 'MULTIPLY', separate.outputs['X'], 2), 1)
    across = shader_math(nodes, links, 'ABSOLUTE', transverse)
    curvature = shader_math(nodes, links, 'MULTIPLY', shader_math(nodes, links, 'MULTIPLY', across, across), .28)
    branches = shader_math(nodes, links, 'SUBTRACT', shader_math(nodes, links, 'MULTIPLY', separate.outputs['Y'], 14), shader_math(nodes, links, 'ADD', shader_math(nodes, links, 'MULTIPLY', across, .62), curvature))
    fractional = shader_math(nodes, links, 'FRACT', branches)
    distance = shader_math(nodes, links, 'MINIMUM', fractional, shader_math(nodes, links, 'SUBTRACT', 1, fractional))
    vein = shader_math(nodes, links, 'LESS_THAN', distance, .023)
    central = shader_math(nodes, links, 'LESS_THAN', across, .018)
    vein_mask = shader_math(nodes, links, 'MAXIMUM', shader_math(nodes, links, 'MULTIPLY', vein, .40), central)
    noise = nodes.new('ShaderNodeTexNoise'); noise.noise_dimensions = '3D'
    links.new(uv.outputs['UV'], noise.inputs['Vector'])
    noise.inputs['Scale'].default_value = 5.5; noise.inputs['Detail'].default_value = 3.
    base = (.045,.12,.022) if age == 'young' else (.019,.062,.010)
    factor = (1 + tone*.055)
    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = .15
    ramp.color_ramp.elements[0].color = (*(x*factor*.74 for x in base),1)
    ramp.color_ramp.elements[1].position = .85
    ramp.color_ramp.elements[1].color = (*(x*factor*1.22 for x in base),1)
    links.new(noise.outputs['Fac'], ramp.inputs[0])
    tint = nodes.new('ShaderNodeMixRGB'); tint.blend_type = 'MIX'
    links.new(shader_math(nodes, links, 'MULTIPLY', vein_mask, .11), tint.inputs[0])
    links.new(ramp.outputs['Color'], tint.inputs[1]); tint.inputs[2].default_value = (.074,.13,.028,1)
    links.new(tint.outputs[0], bsdf.inputs['Base Color'])
    rough = shader_math(nodes, links, 'ADD', shader_math(nodes, links, 'MULTIPLY', noise.outputs['Fac'], .11), .36)
    links.new(rough, bsdf.inputs['Roughness'])
    fine = nodes.new('ShaderNodeTexNoise'); links.new(uv.outputs['UV'], fine.inputs['Vector'])
    fine.inputs['Scale'].default_value = 145.; fine.inputs['Detail'].default_value = 2.
    bump = nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = .23; bump.inputs['Distance'].default_value = .00035
    links.new(shader_math(nodes, links, 'ADD', shader_math(nodes, links, 'MULTIPLY', fine.outputs['Fac'], .24), vein_mask), bump.inputs['Height'])
    links.new(bump.outputs[0], bsdf.inputs['Normal'])
    translucent = nodes.new('ShaderNodeBsdfTranslucent')
    links.new(ramp.outputs[0], translucent.inputs['Color']); links.new(bump.outputs[0], translucent.inputs['Normal'])
    mix = nodes.new('ShaderNodeMixShader'); mix.inputs[0].default_value = .10 if age == 'young' else .065
    links.new(bsdf.outputs[0], mix.inputs[1]); links.new(translucent.outputs[0], mix.inputs[2]); links.new(mix.outputs[0], output.inputs[0])
    mat.diffuse_color = (*base,1)
    return mat


def mesh_part(name, vertices, faces, root, material, role, part_id, uv=None):
    mesh = bpy.data.meshes.new(name+' mesh'); mesh.from_pydata(vertices,[],faces); mesh.update()
    obj = bpy.data.objects.new(name,mesh); bpy.context.scene.collection.objects.link(obj); obj.parent = root
    mesh.materials.append(material)
    for polygon in mesh.polygons: polygon.use_smooth = True
    if uv:
        layer = mesh.uv_layers.new(name='Leaf UV')
        for polygon in mesh.polygons:
            for loop in polygon.loop_indices: layer.data[loop].uv = uv[mesh.loops[loop].vertex_index]
    obj['plant_role'] = role; obj['plant_part_id'] = part_id
    tag_surface(obj, 'plant_leaf' if role == 'leaf' else 'plant_stem' if role in {'petiole','sheath'} else role)
    return obj


def material_signature(mat):
    if not mat or not mat.use_nodes: return None
    nodes = []
    for node in mat.node_tree.nodes:
        values = []
        for socket in node.inputs:
            if not hasattr(socket, 'default_value'): continue
            value = socket.default_value
            if not isinstance(value,(str,float,int,bool)):
                try: value = list(value)
                except TypeError: continue
            values.append((socket.identifier,value))
        properties = {key:getattr(node,key) for key in ('operation','blend_type','noise_dimensions','distribution','interpolation') if hasattr(node,key)}
        if hasattr(node,'color_ramp'):
            properties['ramp'] = [(e.position,list(e.color)) for e in node.color_ramp.elements]
        nodes.append((node.name,node.bl_idname,values,properties))
    links = sorted((l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier) for l in mat.node_tree.links)
    return hashlib.sha256(json.dumps((sorted(nodes),links),sort_keys=True).encode()).hexdigest()


def evaluated_snapshot(obj):
    dg = bpy.context.evaluated_depsgraph_get(); evaluated = obj.evaluated_get(dg); mesh = evaluated.to_mesh()
    data = {'vertices':[list(evaluated.matrix_world@v.co) for v in mesh.vertices],
            'faces':[(list(p.vertices),p.material_index,p.use_smooth) for p in mesh.polygons],
            'uvs':[[list(x.uv) for x in layer.data] for layer in mesh.uv_layers],
            'materials':[material_signature(m) for m in mesh.materials]}
    evaluated.to_mesh_clear()
    return data


def build(args):
    if (args.out/'build_report.json').exists() or (args.out/'candidate/plant_source.blend').exists():
        raise ValueError('Choose a new candidate output directory; preserve previous review evidence')
    source_hash = digest(SOURCE_LIBRARY)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with bpy.data.libraries.load(str(SOURCE_LIBRARY),link=False) as (src,dst): dst.collections = ['RK Plant - Broadleaf Ceramic']
    source_collection = dst.collections[0]; bpy.context.scene.collection.children.link(source_collection)
    bpy.context.view_layer.update()
    source_parts = {role:next(o for o in source_collection.all_objects if o.get('plant_role')==role) for role in ('pot','soil')}
    # Reuse exact complete pot and soil meshes/materials; no change to accepted v1.
    retained = []
    for role,old in source_parts.items():
        obj = old.copy(); obj.data = old.data.copy(); obj.parent = None; obj.matrix_world = old.matrix_world.copy()
        obj.name = 'Natural plant '+role; bpy.context.scene.collection.objects.link(obj); retained.append(obj)
    source_pot_geometry = evaluated_snapshot(source_parts['pot'])
    for obj in list(source_collection.all_objects): bpy.data.objects.remove(obj,do_unlink=True)
    bpy.data.collections.remove(source_collection)
    root = bpy.data.objects.new(ASSET_NAME+' | semantic root',None); bpy.context.scene.collection.objects.link(root)
    tag_root(root,'decor/plants',instance_id='plant-peace-lily-natural',asset_id=ITEM_ID)
    root['plant_seed'] = args.seed; root['plant_leaf_count'] = args.leaf_count
    root['plant_generator_revision'] = 2
    root['plant_attachment_contract'] = 'Resolve leaf_id and plant_role=leaf/petiole within one owning semantic root; object names are provenance only'
    root['plant_type'] = 'Peace-lily-inspired approximate foliage; no botanical cultivar reconstruction claim'
    pot,soil = retained
    for obj,role in ((pot,'pot'),(soil,'soil')):
        obj.parent = root; obj['plant_part_id'] = role; tag_surface(obj,'pot_ceramic' if role=='pot' else 'soil')
    # Source physical pot center is intentionally retained until the complete
    # asymmetric candidate is measured and normalized to floor bounds center.
    rng = random.Random(args.seed)
    leaf_mats = {(age,tone):foliage_material(age,tone) for age in ('mature','young') for tone in (-1,0,1)}
    stem_mat = shared.material('Natural tapered petioles',(.054,.12,.023),.60)
    sheath_mat = shared.material('Natural basal sheaths',(.067,.095,.025),.77)
    granule_mat = shared.material('Potting soil granules',(.028,.015,.007),.95)
    crowns = [Vector((-.037,-.027,.183)),Vector((.033,-.020,.182)),Vector((-.019,.037,.184)),Vector((.038,.038,.184))]
    mature_count = round(args.leaf_count*.44); young_count = max(3,round(args.leaf_count*.15))
    mid_count = args.leaf_count-mature_count-young_count
    ages = ['mature']*mature_count + ['mid']*mid_count + ['young']*young_count
    leaves = []; attachments = []; centers = []; pose_adjustments = []
    for index,age in enumerate(ages):
        leaf_id = 'leaf-{:02d}'.format(index+1); crown_id = (index*3+index//4)%4
        crown = crowns[crown_id]+Vector((rng.uniform(-.012,.012),rng.uniform(-.012,.012),0))
        # Golden-angle sequence with independent crown positions and large jitter;
        # no equal-angle rows, mirrored counterparts or forced extent pairs.
        angle = -math.pi/2 + index*2.3999632297 + rng.uniform(-.38,.38)
        direction = Vector((math.cos(angle),math.sin(angle),0)); sideways = Vector((-math.sin(angle),math.cos(angle),0))
        if age == 'mature':
            length = rng.uniform(.255,.322); width = rng.uniform(.090,.128)
            base_z = rng.uniform(.395,.49); radial = rng.uniform(.067,.115)
            initial = rng.uniform(.28,.72); final = rng.uniform(-1.22,-.72); fold = rng.uniform(.10,.19)
        elif age == 'mid':
            length = rng.uniform(.225,.29); width = rng.uniform(.073,.112)
            base_z = rng.uniform(.405,.50); radial = rng.uniform(.031,.069)
            initial = rng.uniform(.89,1.27); final = rng.uniform(-.52,.04); fold = rng.uniform(.12,.23)
        else:
            length = rng.uniform(.19,.255); width = rng.uniform(.037,.060)
            base_z = rng.uniform(.395,.46); radial = rng.uniform(.008,.026)
            initial = rng.uniform(1.22,1.43); final = rng.uniform(.55,1.13); fold = rng.uniform(.35,.62)
        # Reviewed default-seed grooming, based on the saved candidate's blade
        # BVH intersections. Keep earlier candidate evidence and do not claim
        # these bounded pose edits solve collision clearance for arbitrary seeds.
        if args.seed == 20260911 and args.leaf_count == 27:
            height_offsets = {5:-.045,12:.080,15:.075,21:.065,22:.085}
            if index in height_offsets:
                offset=height_offsets[index];base_z+=offset
                pose_adjustments.append({'leaf_id':leaf_id,'base_height_delta_m':offset})
            if index == 24:
                base_z+=.095;initial=1.46;final=1.33;length*=.88;width*=.82
                pose_adjustments.append({'leaf_id':leaf_id,'base_height_delta_m':.095,'young_blade':'narrower, shorter and more upright'})
            if index == 26:
                base_z=.535;angle=math.radians(45);initial=1.48;final=1.30;length*=.80;width*=.67;radial=.012
                pose_adjustments.append({'leaf_id':leaf_id,'base_height_m':.535,'azimuth_degrees':45,'young_blade':'small upright inner leaf routed away from mid leaves14/19'})
            direction=Vector((math.cos(angle),math.sin(angle),0));sideways=Vector((-math.sin(angle),math.cos(angle),0))
        base = Vector((crown.x,crown.y,base_z))+direction*radial
        start = crown; control1 = crown+Vector((0,0,(base_z-crown.z)*.42))
        control2 = base-direction*.022-Vector((0,0,(base_z-crown.z)*.20))
        path = []
        for j in range(33):
            t = j/32; path.append((1-t)**3*start+3*(1-t)**2*t*control1+3*(1-t)*t*t*control2+t**3*base)
        vertices=[]; faces=[]; frames=[]
        for j,point in enumerate(path):
            tangent = (path[min(j+1,32)]-path[max(j-1,0)]).normalized()
            axis = tangent.cross(direction).normalized()
            if axis.length<.5: axis = sideways
            normal = tangent.cross(axis).normalized(); t=j/32
            radius = (.0043*(1-t)**.64+.00105)*(1+.10*math.sin(math.pi*t))
            frames.append((axis,normal))
            for k in range(12):
                a=2*math.pi*k/12; vertices.append(point+axis*(radius*math.cos(a))+normal*(radius*.79*math.sin(a)))
        for j in range(32):
            for k in range(12): a=j*12+k; b=j*12+(k+1)%12; faces.append((a,b,b+12,a+12))
        faces.extend([tuple(reversed(range(12))),tuple(32*12+k for k in range(12))])
        petiole = mesh_part('Natural '+leaf_id+' petiole',vertices,faces,root,stem_mat,'petiole',leaf_id+'-petiole')
        petiole['leaf_id']=leaf_id; petiole['crown_id']=crown_id
        # Slight open sheath embraces the lower petiole rather than a uniform rod.
        sheath_verts=[]; sheath_faces=[]
        for j in range(11):
            t=j/10; p=path[round(t*9)]; a,b=frames[round(t*9)]; radius=.0075*(1-t)+.0045*t
            for k in range(9):
                phi=-2.48+4.96*k/8; sheath_verts.append(p+a*(math.cos(phi)*radius)+b*(math.sin(phi)*radius*.85))
        for j in range(10):
            for k in range(8): a=j*9+k; sheath_faces.append((a,a+1,a+10,a+9))
        sheath=mesh_part('Natural '+leaf_id+' sheath',sheath_verts,sheath_faces,root,sheath_mat,'sheath',leaf_id+'-sheath')
        sheath['leaf_id']=leaf_id; solid=sheath.modifiers.new('Fine sheath wall','SOLIDIFY');solid.thickness=.00045
        # Numerically integrate a changing inclination to obtain an arched
        # midline. Young inner leaves remain upright and tightly folded.
        nlong,nwide=48,17; centerline=[base]; tangents=[]
        bend = rng.uniform(-.027,.027); twist = rng.uniform(-.43,.43); phase = rng.uniform(0,6.28)
        for j in range(nlong+1):
            s=j/nlong; inclination=initial+(final-initial)*s**1.28
            tangent=direction*math.cos(inclination)+Vector((0,0,math.sin(inclination)))+sideways*(bend/length*math.pi*math.cos(math.pi*s))
            tangents.append(tangent.normalized())
            if j: centerline.append(centerline[-1]+(tangents[j-1]+tangents[j]).normalized()*(length/nlong))
        asym = rng.uniform(-.12,.12); wave = rng.uniform(.0008,.0025)
        def surface(j,u):
            s=j/nlong; tangent=tangents[j]
            across=Quaternion(tangent,twist*math.sin(math.pi*s*.8))@sideways
            normal=tangent.cross(across).normalized()
            half=width*.5*math.sin(math.pi*s)**.83*(.73+.27*s**.35)
            half*=1+asym*u+.032*math.sin(5*math.pi*s+phase)*u
            cup=-fold*width*abs(u)**1.6*math.sin(math.pi*s)
            margin=wave*math.sin(9*math.pi*s+phase)*abs(u)**4*math.sin(math.pi*s)
            ribs=.00038*math.sin(2*math.pi*(14*s-.62*abs(u)-.28*u*u))*abs(u)*math.sin(math.pi*s)
            return centerline[j]+across*(half*u)+normal*(cup+margin+ribs)
        verts=[surface(0,0)]; uvs=[(.5,0)]
        for j in range(1,nlong):
            for k in range(nwide): verts.append(surface(j,-1+2*k/(nwide-1))); uvs.append((k/(nwide-1),j/nlong))
        end=len(verts);verts.append(surface(nlong,0));uvs.append((.5,1))
        faces=[(0,1+k,2+k) for k in range(nwide-1)]
        for j in range(nlong-2):
            for k in range(nwide-1): a=1+j*nwide+k;faces.append((a,a+nwide,a+nwide+1,a+1))
        last=1+(nlong-2)*nwide
        faces.extend((last+k,end,last+k+1) for k in range(nwide-1))
        leaf=mesh_part('Natural '+leaf_id+' blade',verts,faces,root,leaf_mats[('young' if age=='young' else 'mature',rng.choice((-1,0,1)))],'leaf',leaf_id+'-blade',uvs)
        leaf['leaf_id']=leaf_id;leaf['petiole_leaf_id']=leaf_id;leaf['crown_id']=crown_id;leaf['leaf_age']=age
        solid=leaf.modifiers.new('Thin leaf tissue','SOLIDIFY');solid.thickness=.00028;solid.offset=0
        leaf['blade_length_m']=length;leaf['blade_width_m']=width;leaf['blade_base_local']=list(base)
        attachments.append({'leaf_id':leaf_id,'crown_id':crown_id,'age':age,'blade_base':list(base),'soil_start':list(start),'gap_m':(verts[0]-path[-1]).length,'length_m':length,'width_m':width,'azimuth_rad':angle,'twist_rad':twist})
        leaves.append(leaf);centers.append(centerline[nlong//2])
    # Sparse embedded granules break the flat soil disk without floating scatter.
    vertices=[];faces=[]
    for i in range(110):
        radius=.136*math.sqrt(rng.random());a=rng.random()*2*math.pi
        p=Vector((radius*math.cos(a),radius*math.sin(a),.1945));r=rng.uniform(.001,.0031);first=len(vertices)
        vertices.extend(p+Vector(v)*r for v in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,.65),(0,0,-.5)])
        faces.extend(tuple(first+k for k in face) for face in [(0,2,4),(2,1,4),(1,3,4),(3,0,4),(2,0,5),(1,2,5),(3,1,5),(0,3,5)])
    mesh_part('Natural soil granules',vertices,faces,root,granule_mat,'soil_granules','soil-granules')
    bpy.context.view_layer.update()
    plant_objects=list(root.children_recursive);low,high=bounds(plant_objects)
    # A bounded horizontal scale applies to foliage only if this random seed
    # exceeds the room-sized footprint. It never introduces mirror pairs.
    foliage_scale=min(1.,.84/max(high.x-low.x,high.y-low.y))
    if foliage_scale<1:
        for obj in plant_objects:
            if obj.get('plant_role') in {'leaf','petiole','sheath'}:
                for v in obj.data.vertices:v.co.x*=foliage_scale;v.co.y*=foliage_scale
        for a in attachments:
            for field in ('blade_base','soil_start'):
                a[field][0]*=foliage_scale;a[field][1]*=foliage_scale
        for p in centers:p.x*=foliage_scale;p.y*=foliage_scale
        bpy.context.view_layer.update();low,high=bounds(plant_objects)
    recenter=Vector(((low.x+high.x)/2,(low.y+high.y)/2,0))
    if recenter.xy.length>.085:raise ValueError('Foliage centroid too eccentric for this pot-sized asset')
    for obj in plant_objects:obj.location-=recenter
    for a,leaf in zip(attachments,leaves):
        a['blade_base']=list(Vector(a['blade_base'])-recenter);a['soil_start']=list(Vector(a['soil_start'])-recenter)
        leaf['blade_base_local']=a['blade_base']
    for p in centers:p-=recenter
    root['pot_center_local']=list(-recenter);root['leaf_attachments_json']=json.dumps(attachments)
    tag_orientation(root,{'schema_version':1,'front_axis':'-Y','up_axis':'Z','symmetry':'none','origin':'floor_center','semantic_front':'generic','status':'authored','evidence':'tools/build_natural_plant_asset.py: low outward presentation leaves begin toward -Y; exact evaluated bounds centered after asymmetric clump authoring, physical pot center offset reported separately'})
    bpy.context.view_layer.update();low,high=bounds(plant_objects);pot_low,pot_high=bounds([pot]);soil_low,soil_high=bounds([soil])
    if abs(pot_low.z)>1e-6 or max(high.x-low.x,high.y-low.y)>.8501 or high.z>.81:raise ValueError('Candidate footprint/height/support limit exceeded')
    if max(a['gap_m'] for a in attachments)>1e-7:raise ValueError('Detached blade base')
    if any(not soil_low.z<a['soil_start'][2]<soil_high.z for a in attachments):raise ValueError('Petiole base outside soil')
    # Ensure exact pot shape and material were retained despite origin translation.
    now=evaluated_snapshot(pot)
    max_pot_delta=max((Vector(v)+recenter-Vector(w)).length for v,w in zip(now['vertices'],source_pot_geometry['vertices']))
    if max_pot_delta>1e-6 or now['faces']!=source_pot_geometry['faces'] or now['materials']!=source_pot_geometry['materials']:raise ValueError('Reused pot geometry or material changed')
    candidate=args.out/'candidate';candidate.mkdir(parents=True,exist_ok=True)
    bpy.data.orphans_purge(do_recursive=True)
    scene_path=candidate/'plant_source.blend';bpy.ops.wm.save_as_mainfile(filepath=str(scene_path))
    report={'schema_version':1,'item_id':ITEM_ID,'name':ASSET_NAME,'seed':args.seed,'leaf_count':args.leaf_count,'age_counts':{'mature':mature_count,'mid':mid_count,'young':young_count},'basal_crowns':4,
        'source_library':str(SOURCE_LIBRARY),'source_library_sha256':source_hash,'source_candidate':str(scene_path),'candidate_sha256':digest(scene_path),
        'dimensions_m':list(high-low),'bounds_min':list(low),'bounds_max':list(high),'pot_center_local':list(-recenter),'origin_recenter_from_physical_pot_m':list(recenter),'foliage_xy_scale':foliage_scale,'pot_base_z':pot_low.z,'exact_pot_preservation_max_delta_m':max_pot_delta,
        'attachments':attachments,'generator_revision':2,'reviewed_default_pose_adjustments':pose_adjustments,'orientation':json.loads(root['asset_orientation_json']),'reference':REFERENCE,'visual_review':'pending','limitations':['Peace-lily-inspired procedural approximation, not an identified cultivar or scanned plant','Leaf overlaps are not generally collision-free; crown and sheath intersections are intentional attachments','Origin is whole geometry floor center; physical pot center may be a few centimetres eccentric']}
    report['images']=shared.studio(bpy.context.scene,plant_objects,candidate,args.samples,args.resolution,[('leaf_detail',centers[1],.28),('crown_detail',Vector((0,0,.255))-recenter,.30)])
    if digest(SOURCE_LIBRARY)!=source_hash:raise ValueError('Accepted v1 source changed')
    report['source_unchanged']=True;write_json(args.out/'build_report.json',report)
    write_json(candidate/'export_selection.json',{'source_frame':1,'register_materials':False,'material_prefix':'NO_BULK_MATERIAL_EXPORT','furniture':[{'root':root.name,'name':ASSET_NAME,'catalog':'Plants','orientation':report['orientation'],'description':'Peace-lily-inspired irregular clump with '+str(args.leaf_count)+' curved thin leaves, tapered petioles, sheathed bases, UV-aligned fine veins, soil and unchanged ceramic pot; seed '+str(args.seed)}]})
    print(json.dumps({'build':'passed; visual review pending','dimensions_m':report['dimensions_m'],'leaves':args.leaf_count,'pot_center_local':report['pot_center_local']}),flush=True)


def export(args):
    report=json.loads((args.out/'build_report.json').read_text());source=Path(report['source_candidate'])
    if digest(source)!=report['candidate_sha256'] or digest(SOURCE_LIBRARY)!=report['source_library_sha256']:raise ValueError('Candidate/source changed before export')
    bpy.ops.wm.open_mainfile(filepath=str(source));root=bpy.data.objects[ASSET_NAME+' | semantic root']
    bpy.context.view_layer.update()
    root_props={key:root[key] for key in root.keys()}
    source_parts={o.name:({key:o[key] for key in o.keys()},evaluated_snapshot(o)) for o in root.children_recursive if o.type=='MESH'}
    expected={props['plant_part_id']:snapshot for props,snapshot in source_parts.values()}
    exporter=module(ROOT/'.agents/skills/blender-roomkit/scripts/export_assets.py','verified_natural_plant_exporter')
    previous=sys.argv
    try:
        sys.argv=['export_assets.py','--','--config',str(args.out/'candidate/export_selection.json'),'--out',str(args.library_out)];exporter.main()
    finally:sys.argv=previous
    library=args.library_out/'roomkit_furniture_materials.blend';manifest_path=args.library_out/'manifest.json'
    manifest=json.loads(manifest_path.read_text());collection=bpy.data.collections[ASSET_NAME]
    placement_root=next(o for o in collection.all_objects if o.type=='EMPTY' and o.parent is None)
    for key,value in root_props.items():
        if not key.startswith('asset_'):placement_root[key]=value
    placement_root['asset_id']=ITEM_ID
    for obj in collection.all_objects:
        if obj.type!='MESH':continue
        name=obj.name
        if name not in source_parts and name.rsplit('.',1)[-1].isdigit():name=name.rsplit('.',1)[0]
        if name not in source_parts:raise ValueError('Exported part source cannot be identified')
        for key,value in source_parts[name][0].items():obj[key]=value
        obj['source_part_name']=name
    materials={m for o in collection.all_objects if o.type=='MESH' for m in o.data.materials if m}
    bpy.data.libraries.write(str(library),{collection,*materials},path_remap='RELATIVE',fake_user=True,compress=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with bpy.data.libraries.load(str(library),link=False) as (src,dst):dst.collections=[ASSET_NAME]
    collection=dst.collections[0];bpy.context.scene.collection.children.link(collection);bpy.context.view_layer.update()
    root=next(o for o in collection.all_objects if o.get('semantic_class')=='decor/plants')
    objects=[o for o in collection.all_objects if o.type=='MESH'];max_delta=0.;geometry_summary=[]
    if len(objects)!=len(expected):raise ValueError('Export lost plant geometry parts')
    for obj in objects:
        if not obj.get('surface_role') or not obj.get('plant_role'):raise ValueError('Part role missing after reopen')
        actual=evaluated_snapshot(obj);before=expected[obj['plant_part_id']]
        if len(actual['vertices'])!=len(before['vertices']) or actual['faces']!=before['faces'] or actual['uvs']!=before['uvs'] or actual['materials']!=before['materials']:raise ValueError('Export changed evaluated topology, UVs or material graphs: '+obj.name)
        delta=max((Vector(a)-Vector(b)).length for a,b in zip(actual['vertices'],before['vertices']));max_delta=max(max_delta,delta)
        if delta>2e-6:raise ValueError('Export changed evaluated geometry positions')
        geometry_summary.append({'part_id':obj['plant_part_id'],'vertices':len(actual['vertices']),'max_coordinate_delta_m':delta,'material_graph_sha256':actual['materials']})
    gaps=[]
    for a in json.loads(root['leaf_attachments_json']):
        groups={role:[o for o in objects if o.get('leaf_id')==a['leaf_id'] and o.get('plant_role')==role] for role in ('leaf','petiole')}
        if any(len(v)!=1 for v in groups.values()):raise ValueError('Non-unique attachment IDs within plant')
        leaf,petiole=groups['leaf'][0],groups['petiole'][0]
        if leaf.get('petiole_leaf_id')!=petiole['leaf_id']:raise ValueError('Attachment metadata changed')
        point=Vector(leaf['blade_base_local']);found,near,normal,index=petiole.closest_point_on_mesh(petiole.matrix_world.inverted()@point)
        distance=(petiole.matrix_world@near-point).length
        if not found or distance>.002:raise ValueError('Leaf/petiole detached after export')
        gaps.append(distance)
    low,high=bounds(objects);pots=[o for o in objects if o.get('plant_role')=='pot'];pot_low,pot_high=bounds(pots)
    if abs(pot_low.z)>1e-6:raise ValueError('Pot support changed after export')
    if any(o.library for o in objects):raise ValueError('External object dependency')
    images=shared.studio(bpy.context.scene,objects,args.out/'reopened',args.samples,args.resolution)
    if digest(source)!=report['candidate_sha256'] or digest(SOURCE_LIBRARY)!=report['source_library_sha256']:raise ValueError('Candidate/source changed during export')
    validation={'status':'passed','item_id':ITEM_ID,'library':str(library),'library_sha256':digest(library),'candidate_sha256':report['candidate_sha256'],'source_library_sha256':report['source_library_sha256'],
        'leaf_count':report['leaf_count'],'parts':len(objects),'vertices':sum(len(o.data.vertices) for o in objects),'dimensions_m':list(high-low),'pot_base_z':pot_low.z,'physical_pot_center_local':list((pot_low+pot_high)/2)[:2]+[0.],
        'export_coordinate_max_delta_m':max_delta,'topology_uv_material_graphs_preserved':True,'part_checks':geometry_summary,'reopened_attachment_max_gap_m':max(gaps),'source_and_candidate_unchanged':True,'images':images}
    manifest['furniture'][0].update(semantic_class='decor/plants',category='decor/plants',provenance='provenance.json',generator={'script':'tools/build_natural_plant_asset.py','seed':report['seed'],'leaf_count':report['leaf_count']})
    write_json(manifest_path,manifest);write_json(args.out/'export_validation.json',validation)
    write_json(args.library_out/'provenance.json',{'item_id':ITEM_ID,'source_library':str(SOURCE_LIBRARY),'source_library_sha256':report['source_library_sha256'],'candidate_sha256':report['candidate_sha256'],'library_sha256':validation['library_sha256'],'seed':report['seed'],'leaf_count':report['leaf_count'],'morphology_reference':REFERENCE,'same_pot_as':'plants-v1/plant-broadleaf-ceramic','pot_center_local':report['pot_center_local'],'origin_recenter_from_physical_pot_m':report['origin_recenter_from_physical_pot_m'],'orientation':report['orientation'],'geometry_and_materials_preserved':True,'validation_report':str(args.out/'export_validation.json'),'limitations':report['limitations']})
    print(json.dumps({'export':'passed','library':str(library),'vertices':validation['vertices'],'coordinate_max_delta_m':max_delta}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',required=True,choices=['build','export'])
    parser.add_argument('--out',type=Path,default=ROOT/'runs/plant_realism/20260911')
    parser.add_argument('--library-out',type=Path,default=ROOT/'assets/plants/v2')
    parser.add_argument('--seed',type=int,default=20260911)
    parser.add_argument('--leaf-count',type=int,default=27)
    parser.add_argument('--samples',type=int,default=48);parser.add_argument('--resolution',type=int,default=1200)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if not 20<=args.leaf_count<=36:raise ValueError('leaf-count must be in [20,36]')
    args.out=args.out.resolve();args.library_out=args.library_out.resolve();args.out.mkdir(parents=True,exist_ok=True)
    {'build':build,'export':export}[args.stage](args)


if __name__=='__main__':main()

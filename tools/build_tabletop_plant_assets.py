"""Author two editable tabletop botanicals for reviewed RoomKit export.

Run with background Blender. These seeded ornamental models are authored geometry,
not scans or exact botanical specimens. The output is a candidate, not a registry
promotion. Export/reopen/placement and visual review are separate required steps.
"""
import argparse
import json
import math
from pathlib import Path
import random
import sys

import bpy
from mathutils import Vector

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'src/aha3d').is_dir())
sys.path.insert(0, str(ROOT / 'src'))
from aha3d.blender.roomkit import configure_render
from aha3d.blender.orientation import tag_orientation


def material(name, color, roughness=.6):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = roughness
    return mat


def mesh(name, vertices, faces, materials, root, indices=None):
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = root
    for mat in materials:
        data.materials.append(mat)
    for i, face in enumerate(data.polygons):
        face.use_smooth = True
        if indices is not None:
            face.material_index = indices[i]
    return obj


def lathe(name, profile, mat, root, ribs=0):
    vertices, faces = [], []
    n = 96
    for radius, height in profile:
        for i in range(n):
            angle = i * math.tau / n
            r = radius + (ribs * .00065 * math.cos(angle * 32) if radius > .025 else 0)
            vertices.append((r * math.cos(angle), r * math.sin(angle), height))
    for j in range(len(profile) - 1):
        for i in range(n):
            k = j * n + i
            faces.append((k, j*n+(i+1)%n, (j+1)*n+(i+1)%n, k+n))
    return mesh(name, vertices, faces, [mat], root)


def stem(name, points, radius, mat, root):
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = '3D'
    curve.bevel_depth = radius
    curve.bevel_resolution = 1
    spline = curve.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for p, xyz in zip(spline.points, points):
        p.co = (*xyz, 1)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = root
    curve.materials.append(mat)
    return obj


def blade_geometry(vertices, faces, start, end, width, bend, normal):
    """Thin curved blade, attached at start; used for leaflets and broad leaves."""
    a, b, n = Vector(start), Vector(end), Vector(normal).normalized()
    axis = (b-a).normalized()
    across = axis.cross(n).normalized()
    offset = len(vertices)
    nl, nw = 8, 4
    for i in range(nl+1):
        t = i/nl
        center = a.lerp(b, t) + n * (bend * math.sin(math.pi*t))
        span = width * max(.025, math.sin(math.pi*t)**.85)
        for j in range(nw+1):
            u = 2*j/nw-1
            vertices.append(tuple(center + across*(span*u) + n*(width*.16*u*u*math.sin(math.pi*t))))
    for i in range(nl):
        for j in range(nw):
            k = offset+i*(nw+1)+j
            faces.append((k, k+1, k+nw+2, k+nw+1))


def botanical_root(name):
    root = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(root)
    root['semantic_class'] = 'decor/plants'
    root['instance_id'] = name
    tag_orientation(root, dict(schema_version=1, front_axis='-Y', up_axis='Z',
        origin='mount_center', symmetry='none', semantic_front='generic',
        status='authored', evidence='Generator authors upright ornamental foliage with presentation toward -Y; pot mounting center at XY0, bottomZ0.'))
    return root


def build_fern(rng, greens, stalk, soil, pot):
    root = botanical_root('RK Plant - Compact Fern')
    lathe('Fern charcoal ribbed pot', [(0,0),(.045,0),(.051,.006),(.065,.09),
        (.066,.111),(.062,.116),(.057,.112),(.056,.020),(0,.020)], pot, root, ribs=1)
    lathe('Fern visible potting soil', [(0,.106),(.057,.106),(.057,.102),(0,.102)], soil, root)
    for i in range(21):
        angle = i * 2.399963 + rng.uniform(-.16,.16)
        direction = Vector((math.cos(angle), math.sin(angle), 0))
        side = Vector((-direction.y, direction.x, 0))
        reach = rng.uniform(.115,.19) if i < 16 else rng.uniform(.055,.10)
        height = rng.uniform(.095,.145) if i < 16 else rng.uniform(.13,.18)
        base = direction * rng.uniform(.003,.019)
        def center(t):
            return base + direction*(reach*t) + Vector((0,0,.103+height*math.sin(t*2.15)-.015*t*t))
        stem('Fern connected rachis', [center(j/24) for j in range(25)], .0008, stalk, root)
        vertices, faces = [], []
        for j in range(1,13):
            t = .12 + j*.063
            length = .040 * math.sin(math.pi*t)**.85 * rng.uniform(.83,1.13)
            for sign in [-1,1]:
                start = center(t + (.009 if sign == 1 else 0))
                tip = start + sign*side*length + direction*(length*.30) + Vector((0,0,-length*.20))
                blade_geometry(vertices, faces, start, tip, length*.19, .004, (0,0,1))
        blade_geometry(vertices, faces, center(.90), center(1.07), .007, .002, (0,0,1))
        obj = mesh('Fern pinnate frond %02d'%i, vertices, faces, [greens[i%len(greens)]], root)
        obj['plant_role'] = 'connected_leaflets'
        mod = obj.modifiers.new('Thin leaflet tissue', 'SOLIDIFY')
        mod.thickness = .00012
    return root


def build_flowers(rng, greens, stalk, soil, pot, pinks):
    root = botanical_root('RK Flowers - Pink Hydrangea Bowl')
    lathe('Hydrangea low ivory bowl', [(0,0),(.054,0),(.071,.012),(.087,.055),
        (.090,.096),(.086,.103),(.080,.100),(.077,.037),(.043,.012),(0,.012)], pot, root, ribs=1)
    lathe('Hydrangea arrangement substrate', [(0,.087),(.077,.087),(.077,.08),(0,.08)], soil, root)
    clusters = [((0,.025,.224),.070), ((-.057,.004,.200),.065),
                ((.058,.006,.197),.063), ((-.024,-.048,.178),.063), ((.042,-.048,.169),.058)]
    for idx, (xyz, radius) in enumerate(clusters):
        center = Vector(xyz)
        stem('Hydrangea supported flower stem', [(0,0,.025), (xyz[0]*.55,xyz[1]*.55,.123), xyz], .0025, stalk, root)
        branches = bpy.data.curves.new('Hydrangea flower pedicels', 'CURVE')
        branches.dimensions = '3D'
        branches.bevel_depth = .00045
        branches.bevel_resolution = 0
        branch_obj = bpy.data.objects.new(branches.name, branches)
        bpy.context.scene.collection.objects.link(branch_obj)
        branch_obj.parent = root
        branches.materials.append(stalk)
        vertices, faces, indices = [], [], []
        for k in range(78):
            z = .99 - 1.30*(k+.5)/78
            phi = k*2.399963 + rng.uniform(-.14,.14)
            normal = Vector((math.sqrt(1-z*z)*math.cos(phi), math.sqrt(1-z*z)*math.sin(phi), z))
            origin = center + normal * radius * rng.uniform(.92,1.04)
            branch = branches.splines.new('POLY')
            branch.points.add(1)
            branch.points[0].co = (*center, 1)
            branch.points[1].co = (*origin, 1)
            u = normal.cross(Vector((0,1,0))).normalized()
            v = normal.cross(u).normalized()
            phase = rng.uniform(0,math.tau)
            size = rng.uniform(.009,.013)
            for petal in range(4):
                a = phase+petal*math.pi/2
                direction = u*math.cos(a)+v*math.sin(a)
                before = len(faces)
                blade_geometry(vertices, faces, origin, origin+direction*size,
                               size*.53, -.002, normal)
                indices.extend([rng.randrange(len(pinks))]*(len(faces)-before))
        obj = mesh('Hydrangea four-petal florets %02d'%idx, vertices, faces, pinks, root, indices)
        obj['plant_role'] = 'flower_petals'
        mod = obj.modifiers.new('Thin petal tissue','SOLIDIFY')
        mod.thickness = .00016
    for i in range(8):
        a = i*2.4
        start = Vector((0,0,.105))
        end = Vector((.118*math.cos(a), .118*math.sin(a), .123+rng.uniform(-.018,.02)))
        vertices, faces = [], []
        blade_geometry(vertices, faces, start, end, .026, .017, (0,0,1))
        mesh('Hydrangea basal leaf', vertices, faces, [greens[i%len(greens)]], root)
        stem('Hydrangea leaf midrib',[start,start.lerp(end,.5)+Vector((0,0,.017)),end],.00055,stalk,root)
    return root


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--seed', type=int, default=20260912)
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.out.mkdir(parents=True, exist_ok=False)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    rng = random.Random(args.seed)
    greens = [material('Tabletop foliage %d'%i,c,.50) for i,c in enumerate([
        (.031,.105,.014),(.052,.16,.018),(.021,.074,.008),(.081,.18,.028)])]
    stalk = material('Tabletop green petioles',(.062,.12,.017),.65)
    soil = material('Dark potting substrate',(.023,.013,.007),.92)
    charcoal = material('Ribbed charcoal stoneware',(.073,.080,.074),.78)
    ivory = material('Fluted ivory ceramic bowl',(.68,.63,.52),.39)
    pinks = [material('Hydrangea petal tone %d'%i,c,.68) for i,c in enumerate([
        (.39,.024,.10),(.62,.068,.19),(.74,.15,.29),(.51,.041,.14),(.84,.24,.35)])]
    roots = [build_fern(rng,greens,stalk,soil,charcoal),build_flowers(rng,greens,stalk,soil,ivory,pinks)]
    bpy.context.view_layer.update()
    s = bpy.context.scene
    s.unit_settings.system='METRIC'
    s['generator_seed']=args.seed
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out/'candidates.blend'))
    config = dict(source_frame=1, material_prefix='__NO_SEPARATE_PALETTE__',register_materials=False, furniture=[])
    for root, desc in zip(roots, [
        'Compact tabletop fern:21 irregular arched fronds with thin attached leaflets, visible soil and ribbed charcoal pot.',
        'Pink hydrangea arrangement:five flower heads with390 four-petal florets, basal leaves and a low ivory ceramic bowl.']):
        config['furniture'].append(dict(root=root.name,name=root.name,catalog='Decor/Plants',description=desc))
    (args.out/'selection.json').write_text(json.dumps(config,indent=2))
    # Matched neutral stage; roots are moved only in this separate preview copy.
    roots[0].location.x=-.25
    roots[1].location.x=.25
    from aha3d.blender.roomkit import box
    ground = material('Preview warm gray',(.25,.24,.21),.85)
    box('Preview support',(0,0,-.018),(2,2,.036),ground,edge=0)
    for name,xyz,power,size in [('Key',(1,-1,2),100,2),('Fill',(-1,-.5,1),60,2),('Rim',(0,1,1.2),90,1.5)]:
        data=bpy.data.lights.new(name,'AREA');data.energy=power;data.shape='DISK';data.size=size
        obj=bpy.data.objects.new(name,data);s.collection.objects.link(obj);obj.location=xyz;obj.rotation_euler=(Vector((0,0,.13))-obj.location).to_track_quat('-Z','Y').to_euler()
    data=bpy.data.cameras.new('Plant comparison camera');cam=bpy.data.objects.new(data.name,data);s.collection.objects.link(cam);s.camera=cam;data.type='ORTHO';data.ortho_scale=.99
    s.render.resolution_x=1440;s.render.resolution_y=840;s.render.resolution_percentage=100
    for name,xyz,target in [('front',(0,-1,.57),(0,0,.14)),('side',(1,-.65,.47),(0,0,.15)),('top',(0,-.08,1),(0,0,.10)),('low',(0,-1,.14),(0,0,.13))]:
        cam.location=xyz;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
        configure_render(s,'material',samples=48);s.render.filepath=str(args.out/(name+'.png'));bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out/'preview_scene.blend'))


if __name__ == '__main__':
    main()

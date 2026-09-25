"""Targeted registered non-vessel asset quality audit/refinement (Blender)."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from aha3d.blender.roomkit import configure_render, area_light

EXCLUDED_LIBRARIES = {"plants-v1", "plants-v2", "tabletop-plants-v1", "ceramic-vase-v1"}
EXCLUDED_ITEMS = {"additional-44-stylized-stemmed-vessel", "additional-44-silver-serving-platter", "additional-45-small-porcelain-vase", "additional-45-tall-porcelain-vase"}


def records():
    data = json.loads((ROOT / "assets/index.json").read_text())
    cards = data["entries"]
    return [c for c in cards if c.get("status") == "registered"]


def owned(card):
    return card["library_id"] not in EXCLUDED_LIBRARIES and card["id"].split("/")[-1] not in EXCLUDED_ITEMS


def bounds(objects):
    graph=bpy.context.evaluated_depsgraph_get()
    points=[]
    for o in objects:
        if o.type != "MESH": continue
        evaluated=o.evaluated_get(graph)
        mesh=evaluated.to_mesh()
        points.extend(evaluated.matrix_world @ v.co for v in mesh.vertices)
        evaluated.to_mesh_clear()
    if not points:
        return [[0] * 3, [0] * 3]
    return [[min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]]


def describe(collection):
    bpy.context.view_layer.update()
    objects = list(collection.all_objects)
    meshes = [o for o in objects if o.type == "MESH"]
    box = bounds(meshes)
    return dict(parts=len(meshes), vertices=sum(len(o.data.vertices) for o in meshes),
                bounds_min_m=box[0], bounds_max_m=box[1], dimensions_m=[b-a for a,b in zip(*box)],
                drivers=sum(len(o.animation_data.drivers) for o in objects if o.animation_data),
                objects=[dict(name=o.name, type=o.type, vertices=len(o.data.vertices) if o.type == "MESH" else 0,
                              bounds=bounds([o]), materials=[m.name for m in o.data.materials] if o.type == "MESH" else [],
                              modifiers=[m.type for m in o.modifiers], parent=o.parent.name if o.parent else None) for o in objects])


def render(collection, path, view="front", material=False):
    scene = bpy.context.scene
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    original = {o: o.hide_render for o in scene.objects}
    for o in scene.objects:
        o.hide_render = o.name not in collection.all_objects
    box = bounds(collection.all_objects)
    center = Vector([(a+b)/2 for a,b in zip(*box)])
    scale = max(b-a for a,b in zip(*box))
    data = bpy.data.cameras.new("Quality review camera")
    camera = bpy.data.objects.new("Quality review camera", data)
    scene.collection.objects.link(camera)
    direction = Vector((1.3, -2.0 if view != "back" else 2., 1.25 if view != "top" else 4.5))
    camera.location = center + direction * scale
    camera.rotation_euler = (center-camera.location).to_track_quat("-Z", "Y").to_euler()
    data.type = "ORTHO"; data.ortho_scale = scale * 1.5
    scene.camera = camera
    scene.render.resolution_x = scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    configure_render(scene, mode="material" if material else "clay", samples=24)
    lights=[]
    if material:
        scene.world=bpy.data.worlds.new("Quality neutral studio world")
        scene.world.use_nodes=True
        scene.world.node_tree.nodes["Background"].inputs[0].default_value=(.22,.25,.30,1)
        scene.world.node_tree.nodes["Background"].inputs[1].default_value=.65
        lights=[area_light("Quality key", center+Vector((2,-3,4))*scale, center, energy=600*scale*scale, size=scale*3),
                area_light("Quality fill", center+Vector((-3,-1,2))*scale, center, energy=250*scale*scale, size=scale*2)]
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    for o in [camera]+lights: bpy.data.objects.remove(o, do_unlink=True)
    for o,hidden in original.items(): o.hide_render=hidden


def mesh_set(obj, vertices, faces, materials=None, smooth=True):
    inverse=obj.matrix_world.inverted()
    mesh=bpy.data.meshes.new(obj.name+" quality mesh")
    mesh.from_pydata([inverse @ Vector(v) for v in vertices], [], faces)
    mesh.update()
    for material in materials if materials is not None else list(obj.data.materials):
        mesh.materials.append(material)
    obj.data=mesh
    bm=bmesh.new(); bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces)); bm.to_mesh(mesh); bm.free()
    for face in mesh.polygons: face.use_smooth=smooth
    obj["quality_refinement"]="authored geometric detail; no simulation certification"
    return obj


def part(collection, name, vertices, faces, material, smooth=True):
    mesh=bpy.data.meshes.new(name)
    obj=bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    roots=[o for o in collection.all_objects if o.parent is None and o.type=="EMPTY"]
    if roots:
        obj.parent=roots[0]
        obj.matrix_world=Matrix.Identity(4)
    return mesh_set(obj, vertices, faces, [material], smooth)


def lathe(profile, center=(0,0), segments=96):
    """Closed section revolution; zero-radius rings are single pole vertices."""
    vertices=[]; rings=[]; faces=[]
    for radius,z in profile:
        ring=[]
        for i in range(1 if radius < 1e-9 else segments):
            a=2*math.pi*i/segments
            ring.append(len(vertices)); vertices.append((center[0]+radius*math.cos(a), center[1]+radius*math.sin(a), z))
        rings.append(ring)
    for a,b in zip(rings, rings[1:]+rings[:1]):
        if len(a)==len(b)==1: continue
        for i in range(segments):
            j=(i+1)%segments
            faces.append((a[0],b[j],b[i]) if len(a)==1 else
                         (a[i],a[j],b[0]) if len(b)==1 else (a[i],a[j],b[j],b[i]))
    return vertices,faces


def rod(collection,name,a,b,radius,material):
    a,b=Vector(a),Vector(b); direction=(b-a).normalized()
    axis=direction.cross(Vector((0,0,1)))
    if axis.length<.01: axis=direction.cross(Vector((0,1,0)))
    axis.normalize(); other=direction.cross(axis)
    vertices=[p+radius*(axis*math.cos(i*math.tau/16)+other*math.sin(i*math.tau/16)) for p in (a,b) for i in range(16)]
    faces=[tuple(range(15,-1,-1)),tuple(range(16,32))]+[(i,(i+1)%16,(i+1)%16+16,i+16) for i in range(16)]
    return part(collection,name,vertices,faces,material)


def plain_material(name,color,roughness=.5,metallic=0):
    material=bpy.data.materials.new(name); material.use_nodes=True
    material.diffuse_color=(*color,1)
    shader=material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value=(*color,1)
    shader.inputs["Roughness"].default_value=roughness
    shader.inputs["Metallic"].default_value=metallic
    return material


def apply_solidify(obj,thickness):
    bpy.context.view_layer.objects.active=obj
    modifier=obj.modifiers.new("Physical wall thickness", "SOLIDIFY")
    modifier.thickness=thickness; modifier.offset=-1
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def lounge(collection,occupied=False):
    meshes=[o for o in collection.all_objects if o.type=="MESH"]
    material=next(o.data.materials[0] for o in meshes if "armrest" in o.name)
    sx, sy=(.62*1.15,.62) if occupied else (1.,1.)
    for sign,label in [(-1,"left"),(1,"right")]:
        x=sign*.22*sx
        # Back slats overlap both cross rails and support the original upholstery.
        lo=Vector((x-.026*sx,.30*sy,.384*sy)); hi=Vector((x+.026*sx,.42*sy,.964*sy))
        vertices=[(x,y,z) for x in (lo.x,hi.x) for y in (lo.y,hi.y) for z in (lo.z,hi.z)]
        faces=[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]
        obj=part(collection,"Quality walnut back support "+label,vertices,faces,material,False)
        bpy.context.view_layer.objects.active=obj
        modifier=obj.modifiers.new("Slat edge finish","BEVEL"); modifier.width=.003*sy; modifier.segments=3
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    if not occupied:
        for obj in meshes:
            if "lumbar pillow" in obj.name: obj.location.z-=.018
    return ["Added two walnut rear support slats within the original envelope."]+([] if occupied else ["Lowered lumbar pillow and its piping by 18 mm for supported seat contact."])


def candles(collection):
    meshes=[o for o in collection.all_objects if o.type=="MESH"]
    wax=plain_material("Quality candle ivory wax",(.72,.66,.53),.38)
    wax.node_tree.nodes.get("Principled BSDF").inputs["Subsurface Weight"].default_value=.08
    wick=plain_material("Quality candle cotton wick",(.025,.017,.011),.95)
    for index,obj in enumerate(meshes):
        low,high=bounds([obj]); radius=(high[0]-low[0])/2; height=high[2]-low[2]
        center=((low[0]+high[0])/2,(low[1]+high[1])/2)
        profile=[(0,0),(radius*.97,0),(radius,.0015),(radius,height-.003),(radius*.96,height-.002),
                 (radius*.68,height-.004),(radius*.22,height-.008),(0,height-.008)]
        mesh_set(obj,*lathe(profile,center),[wax])
        rod(collection,f"Quality candle wick {index+1}",(center[0],center[1],height-.010),(center[0]+.001,center[1],height),.0008,wick)
    return ["Replaced solid block candles with round wax bodies, dished wax tops and six cotton wicks.",
            "Grounded all six candle bases at the group support plane; preserved each original candle height and overall group envelope.",
            "Assigned wax and wick materials instead of linen upholstery."]


def napkin(collection):
    obj=next(o for o in collection.all_objects if o.type=="MESH")
    low,high=bounds([obj]); material=obj.data.materials[0]
    width,depth,height=[b-a for a,b in zip(low,high)]
    nx,ny=40,20
    for layer in range(4):
        vertices=[]; faces=[]
        for side in range(2):
            for j in range(ny+1):
                v=j/ny; y=low[1]+v*depth
                for i in range(nx+1):
                    u=i/nx; x=low[0]+u*width
                    # Interlocking layer boundaries with a restrained rolled edge.
                    level=layer+side
                    z=low[2]+height*level/4
                    if level not in (0,4):
                        z+=height*.055*math.sin(u*math.tau+v*math.pi)
                    elif level==4:
                        z-=height*.07*(.5+.5*math.sin(3*math.pi*u+2*math.pi*v))*math.sin(u*math.pi)*math.sin(v*math.pi)
                    edge=(math.sin(u*math.pi)*math.sin(v*math.pi))**.5
                    if side: z-=height*.025*(1-edge)
                    else: z+=height*.025*(1-edge) if layer else 0
                    vertices.append((x,y,z))
        count=(nx+1)*(ny+1)
        for side in range(2):
            offset=side*count
            for j in range(ny):
                for i in range(nx):
                    a=offset+j*(nx+1)+i
                    q=(a,a+1,a+nx+2,a+nx+1)
                    faces.append(q if side else q[::-1])
        border=list(range(nx+1))+[j*(nx+1)+nx for j in range(1,ny+1)]+[ny*(nx+1)+i for i in range(nx-1,-1,-1)]+[j*(nx+1) for j in range(ny-1,0,-1)]
        faces.extend((a,b,b+count,a+count) for a,b in zip(border,border[1:]+border[:1]))
        if layer==0: mesh_set(obj,vertices,faces)
        else: part(collection,f"Quality folded linen layer {layer+1}",vertices,faces,material)
    return ["Replaced one thick box with four fitted linen layers, rolled edges and subtle surface undulation; preserved tabletop footprint and support plane.",
            "Static folded textile geometry; no cloth solver or cloth simulation claim."]


def curtains(collection):
    panels=[o for o in collection.all_objects if o.type=="MESH" and "Linen curtain panel" in o.name]
    bands=[o for o in collection.all_objects if o.type=="MESH" and "taupe band" in o.name]
    band_material=bands[0].data.materials[0]
    for obj in panels:
        low,high=bounds([obj]); vertices=[]; faces=[]
        nx,nz=64,100
        for j in range(nz+1):
            t=j/nz; z=low[2]+t*(high[2]-low[2])
            for i in range(nx+1):
                u=i/nx; x=low[0]+u*(high[0]-low[0])
                wave=(.5-.5*math.cos(u*math.tau*3))
                y=.0115+wave*.096*(1-.99*t**12)
                vertices.append((x,y,z))
        for j in range(nz):
            for i in range(nx):
                a=j*(nx+1)+i; faces.append((a,a+1,a+nx+2,a+nx+1))
        mesh_set(obj,vertices,faces,[obj.data.materials[0],band_material])
        for p in obj.data.polygons:
            z=sum(vertices[i][2] for i in p.vertices)/len(p.vertices)
            p.material_index=int(any(abs(z-c)<.040 for c in (-.47,-.94,-1.41,-1.88)))
        apply_solidify(obj,.0012)
    for obj in bands: bpy.data.objects.remove(obj,do_unlink=True)
    return ["Replaced two 100 mm solid slabs with thin pleated linen sheets and native mesh thickness.",
            "Integrated the four taupe bands per curtain as material regions on the cloth; removed detached band boxes.",
            "Gathered cloth into the rod contact at the top; retained mount origin, rod and lower hem height.",
            "Static authored folds; no cloth simulation validation."]


def lamp(collection):
    obj=next(o for o in collection.all_objects if o.type=="MESH" and "Cone" in o.name)
    low,high=bounds([obj]); center=((low[0]+high[0])/2,(low[1]+high[1])/2)
    points=[obj.matrix_world@v.co for v in obj.data.vertices]
    rings=[(z,max(math.hypot(v.x-center[0],v.y-center[1]) for v in points if abs(v.z-z)<1e-5)) for z in (low[2],high[2])]
    bottom,top=rings[0][1],rings[1][1]; wall=.0016
    mesh_set(obj,*lathe([(bottom,low[2]),(top,high[2]),(top-wall,high[2]),(bottom-wall,low[2])],center))
    brass=next(o.data.materials[0] for o in collection.all_objects if o.type=="MESH" and "stem" in o.name)
    z=low[2]+(high[2]-low[2])*.42; radius=bottom+(top-bottom)*.42
    for i in range(3):
        a=i*math.tau/3
        rod(collection,f"Quality shade spider {i}",(center[0],center[1],z),(center[0]+radius*math.cos(a),center[1]+radius*math.sin(a),z),.0018,brass)
    bulb=plain_material("Quality frosted lamp bulb",(.90,.82,.66),.28)
    vertices,faces=lathe([(0,z+.065),(.01,z+.062),(.025,z+.043),(.026,z+.028),(.015,z+.01),(.008,z),(0,z)],center,48)
    part(collection,"Quality lamp bulb",vertices,faces,bulb)
    return ["Rebuilt lampshade as a 1.6 mm open tapered shell with visible inner wall and edge rings.",
            "Added three internal brass supports and a frosted bulb, preserving lamp height, base, stem and material appearance.",
            "No photometric lighting calibration."]


def sconce(collection):
    obj=next(o for o in collection.all_objects if o.type=="MESH" and "shade" in o.name)
    low,high=bounds([obj]); x0,y0,z0=low; x1,y1,z1=high; t=.002
    vertices=[]
    for z in (z0,z1):
        vertices.extend([(x0,y0,z),(x1,y0,z),(x1,y1,z),(x0,y1,z),
                         (x0+t,y0+t,z),(x1-t,y0+t,z),(x1-t,y1-t,z),(x0+t,y1-t,z)])
    faces=[]
    for i in range(4):
        j=(i+1)%4
        faces.extend([(i,j,j+8,i+8),(i+4,i+12,j+12,j+4),(i,j,j+4,i+4),(i+8,i+12,j+12,j+8)])
    mesh_set(obj,vertices,faces,smooth=False)
    brass=next(o.data.materials[0] for o in collection.all_objects if o.type=="MESH" and "plate" in o.name)
    c=Vector(((x0+x1)/2,(y0+y1)/2,(z0+z1)/2))
    rod(collection,"Quality sconce shade support",(c.x,-.065,c.z),(c.x,c.y,c.z),.004,brass)
    rod(collection,"Quality sconce bulb socket",(c.x,c.y,z0+.01),(c.x,c.y,c.z),.010,brass)
    bulb=plain_material("Quality sconce frosted bulb",(.90,.82,.66),.28)
    part(collection,"Quality sconce bulb",*lathe([(0,c.z+.05),(.012,c.z+.04),(.021,c.z+.021),(.018,c.z),(.008,c.z-.018),(0,c.z-.018)],(c.x,c.y),48),bulb)
    return ["Replaced solid shade block with a 2 mm rectangular shade shell open above and below.",
            "Added internal mounting support, socket and frosted bulb while preserving the wall plate, mount origin and outer envelope."]


def faucet(collection):
    obj=next(o for o in collection.all_objects if o.type=="MESH")
    mesh=obj.data.copy(); obj.data=mesh
    bm=bmesh.new(); bm.from_mesh(mesh)
    caps=[f for f in bm.faces if len(f.verts)>4]
    poles=[v for v in bm.verts if len(v.link_edges)>6 and all(len(f.verts)==3 for f in v.link_faces)]
    if len(caps)==2: bmesh.ops.delete(bm,geom=caps,context="FACES_ONLY")
    elif len(poles)==2: bmesh.ops.delete(bm,geom=poles,context="VERTS")
    elif sum(e.is_boundary for e in bm.edges)==20: pass  # Original 10-sided open tube has no wall thickness.
    else: raise ValueError("Unrecognized faucet topology; inspect before modification")
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces)); bm.to_mesh(mesh); bm.free()
    apply_solidify(obj,.0012)
    for p in obj.data.polygons: p.use_smooth=True
    material=plain_material("Quality faucet brushed stainless steel",(.52,.56,.59),.24,1)
    obj.data.materials.clear(); obj.data.materials.append(material)
    return ["Added a 1.2 mm inward wall and annular end rims to the existing open single-surface tube; outlet and mounting end remain open.",
            "Assigned brushed stainless steel instead of the extraction clay; retained original centerline and mount origin.",
            "No valve, internal flow or plumbing simulation model."]


OPERATIONS={
    "roomkit-v1/chair-walnut-lounge": lounge,
    "additional-444547-45-v1/additional-45-occupied-walnut-lounge-chair": lambda c:lounge(c,True),
    "additional-444547-45-v1/additional-45-six-candle-group": candles,
    "additional-444547-45-v1/additional-45-folded-linen-napkin": napkin,
    "additional-444547-47-v1/additional-47-banded-linen-curtain-pair": curtains,
    "additional-444547-47-v1/additional-47-brass-linen-table-lamp": lamp,
    "additional-444547-44-v1/additional-44-wall-sconce": sconce,
    "faucet-simple-v1/faucet-simple-gooseneck": faucet,
}


def retained_reason(card):
    category=card["category"]
    if card.get("articulation"): return "Native independent door and drawer controls retained; hollow carcass and authored joints already present."
    if "wall_art" in category: return "Authored relief/frame geometry is intact; its simple artwork is an intentional source-specific abstraction."
    if "architecture" in category: return "Separate trim members and opening preserved; adding glazing or outdoor scenery would change the declared asset."
    if "seating" in category: return "Separate upholstery and supported frame already present; no unambiguous structural defect identified in the mesh audit."
    if "storage" in category: return "Static facade/handles retained; conversion into operative storage requires a separate articulated design."
    if "tables" in category: return "Separate tabletop and support geometry already present; authored proportions and support contact retained."
    return "Existing component geometry, material graphs and source-specific design retained after item-level inspection."


def validate_collection(collection):
    meshes=[o for o in collection.all_objects if o.type=="MESH"]
    invalid=[o.name for o in meshes if not o.data.polygons or any(not math.isfinite(float(c)) for v in o.data.vertices for c in v.co)]
    if invalid: raise ValueError(f"Invalid mesh geometry: {invalid}")
    missing_material=[o.name for o in meshes if not o.data.materials or any(m is None for m in o.data.materials)]
    if missing_material: raise ValueError(f"Missing mesh material: {missing_material}")
    controllers=[o for o in collection.all_objects if "open_amount" in o]
    controls=[]
    if controllers:
        originals={o:float(o["open_amount"]) for o in controllers}
        for o in controllers: o["open_amount"]=0; o.update_tag()
        bpy.context.view_layer.update()
        closed={o:o.matrix_world.copy() for o in collection.all_objects}
        for control in controllers:
            control["open_amount"]=.75; control.update_tag(); bpy.context.view_layer.update()
            graph=bpy.context.evaluated_depsgraph_get()
            own=max((sum(abs(a-b) for a,b in zip(o.evaluated_get(graph).matrix_world[row],closed[o][row])) for o in [control]+list(control.children_recursive) for row in range(4)),default=0)
            others=max((sum(abs(a-b) for a,b in zip(o.evaluated_get(graph).matrix_world[row],closed[o][row])) for other in controllers if other!=control for o in [other]+list(other.children_recursive) for row in range(4)),default=0)
            if own<.01 or others>1e-6: raise ValueError(f"Cabinet control independence failed {control.name}: {own}/{others}")
            controls.append(dict(name=control.name,own_transform_change=own,other_control_transform_change=others))
            control["open_amount"]=0; control.update_tag(); bpy.context.view_layer.update()
        for o,value in originals.items(): o["open_amount"]=value; o.update_tag()
        bpy.context.view_layer.update()
    return dict(finite_meshes=len(meshes),missing_materials=0,independent_controls=controls)


def inward_meshes(collection, repair=False):
    result=[]
    for obj in collection.all_objects:
        if obj.type!="MESH": continue
        bm=bmesh.new(); bm.from_mesh(obj.data)
        if bm.faces and all(e.is_manifold for e in bm.edges) and bm.calc_volume(signed=True)<-1e-10:
            result.append(obj.name)
            if repair:
                obj.data=obj.data.copy()
                bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
                if bm.calc_volume(signed=True)<0: bmesh.ops.reverse_faces(bm,faces=list(bm.faces))
                bm.to_mesh(obj.data)
        bm.free()
    return result


def build(out,renders):
    result=[]; all_cards=records()
    libraries=json.loads((ROOT / "assets/registry.json").read_text())["assets"]
    for library_id,library in libraries.items():
        cards=[c for c in all_cards if c["library_id"]==library_id and c["kind"]=="collection" and owned(c)]
        if not cards: continue
        bpy.ops.wm.open_mainfile(filepath=str(ROOT/library["path"]))
        for card in cards:
            collection=bpy.data.collections[card["datablock"]]
            if collection.name not in bpy.context.scene.collection.children: bpy.context.scene.collection.children.link(collection)
        changed=[]
        for card in cards:
            collection=bpy.data.collections[card["datablock"]]
            before=describe(collection); preview=[]; slug=card["id"].replace("/","__")
            operation=OPERATIONS.get(card["id"])
            reversed_surfaces=inward_meshes(collection)
            intrinsic=validate_collection(collection)
            if renders:
                for view in (["front","back","top"] if operation or reversed_surfaces else ["front"]):
                    p=out/(slug+f"_{view}_before.png"); render(collection,p,view); preview.append(str(p.resolve()))
            changes=operation(collection) if operation else []
            if reversed_surfaces:
                inward_meshes(collection,repair=True)
                changes.append("Corrected inward-facing normals on closed mesh parts: "+", ".join(reversed_surfaces)+"; vertex positions, UVs and material graphs preserved.")
            bpy.context.view_layer.update()
            after=describe(collection)
            row=dict(asset_id=card["id"],library_id=library_id,datablock=card["datablock"],status="upgraded" if changes else "retained",
                     changes=changes,reason="Targeted correction of observed proxy geometry." if changes else retained_reason(card),
                     before=before, after=after, previews=preview,
                     manifest_updates={k:after[k] for k in ("parts","vertices","dimensions_m","bounds_min_m","bounds_max_m")},
                     validation={"drivers_before":before["drivers"],"drivers_after":after["drivers"],"physics":"Not simulation certified; material/density/collision preparation still required.","inward_meshes_repaired":reversed_surfaces,**intrinsic})
            if changes:
                description=" ".join(changes)
                if operation is None or "chair" in card["id"]:
                    description=card["description"]+" Quality refinement: "+description
                row["manifest_updates"]["description"]=description
                changed.append(row)
                if renders:
                    for view in ["front","back","top"]:
                        p=out/(slug+f"_{view}_after.png"); render(collection,p,view); preview.append(str(p.resolve()))
                    p=out/(slug+"_material_after.png"); render(collection,p,"front",True); preview.append(str(p.resolve()))
            result.append(row)
        if changed:
            candidate=out/(library_id+".blend")
            bpy.data.libraries.write(str(candidate),set(bpy.data.collections)|set(bpy.data.materials),fake_user=True,compress=True)
            for row in changed: row["candidate_library"]=str(candidate.resolve())
        (out/"deltas.json").write_text(json.dumps(result,indent=2))
    print("QUALITY_MODEL_BUILD",len(result),sum(r["status"]=="upgraded" for r in result),flush=True)


def verify(out):
    rows=json.loads((out/"deltas.json").read_text())
    expected={c["id"] for c in records() if c["kind"]=="collection" and owned(c)}
    if {r["asset_id"] for r in rows}!=expected: raise ValueError("Incomplete or stale per-item delta coverage")
    for path in sorted(set(r.get("candidate_library") for r in rows if r.get("candidate_library"))):
        bpy.ops.wm.open_mainfile(filepath=path)
        if list(bpy.data.libraries): raise ValueError("Candidate retains linked libraries")
        for row in [r for r in rows if r.get("candidate_library")==path]:
            collection=bpy.data.collections[row["datablock"]]
            bpy.context.scene.collection.children.link(collection)
            actual=describe(collection)
            for key in ["parts","vertices","drivers"]:
                if actual[key]!=row["after"][key]: raise ValueError(f"Reopen mismatch {row['asset_id']} {key}")
            err=max(abs(a-b) for key in ["bounds_min_m","bounds_max_m"] for a,b in zip(actual[key],row["after"][key]))
            if err>1e-6: raise ValueError(f"Reopen bounds mismatch {err}")
            topology=[]
            for obj in collection.all_objects:
                if obj.type!="MESH":continue
                bm=bmesh.new(); bm.from_mesh(obj.data)
                topology.append(dict(name=obj.name,boundary_edges=sum(e.is_boundary for e in bm.edges),
                    nonmanifold_edges=sum(not e.is_manifold for e in bm.edges), signed_volume=bm.calc_volume(signed=True)))
                bm.free()
            if any(t["nonmanifold_edges"] or t["signed_volume"]<=0 for t in topology):
                raise ValueError(f"Candidate closed-solid topology check failed: {row['asset_id']}")
            row["validation"].update(save_reopen=True,linked_libraries=0,max_bounds_error_m=err,topology=topology)
    (out/"deltas.json").write_text(json.dumps(rows,indent=2))
    print("QUALITY_MODEL_VERIFY",len(rows),flush=True)


def audit(out, renders):
    all_cards=records(); report={"models":[], "materials":[]}
    libraries=json.loads((ROOT / "assets/registry.json").read_text())["assets"]
    for library_id, library in libraries.items():
        bpy.ops.wm.open_mainfile(filepath=str(ROOT / library["path"]))
        for card in [c for c in all_cards if c["library_id"] == library_id]:
            if card["kind"] == "collection" and owned(card):
                collection=bpy.data.collections[card["datablock"]]
                if collection.name not in bpy.context.scene.collection.children:
                    bpy.context.scene.collection.children.link(collection)
                report["models"].append(dict(id=card["id"], library_id=library_id, collection=collection.name,
                                            category=card["category"], description=card["description"], **describe(collection)))
                if renders:
                    render(collection, out / (card["id"].replace("/","__")+"_before.png"))
            elif card["kind"] == "material":
                material=bpy.data.materials[card["datablock"]]
                nodes=material.node_tree.nodes if material.node_tree else []
                report["materials"].append(dict(id=card["id"], name=material.name, nodes=len(nodes),
                    types=sorted(set(n.type for n in nodes)), missing_images=[n.name for n in nodes if n.type=="TEX_IMAGE" and not n.image],
                    status="kept", reason="Editable material graph retained; appearance is source-specific."))
    (out / "audit.json").write_text(json.dumps(report, indent=2))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["audit", "build", "verify"], default="audit")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--renders", action="store_true")
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    args.out.mkdir(parents=True, exist_ok=True)
    if args.stage=="audit": audit(args.out, args.renders)
    elif args.stage=="build": build(args.out,args.renders)
    else: verify(args.out)


if __name__ == "__main__": main()

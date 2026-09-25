"""Background Blender matched views. Run with a saved authored scene open."""
import argparse
import hashlib
import json
import sys
import struct
import zlib
import time
from pathlib import Path
import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector
sys.path.insert(0,str(Path(__file__).resolve().parent))
from config import validate, reference_layers
from overlay import composite_xray, write_report


def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def save_rgb(path, pixels):
    """Write exact uint8 source RGB without Blender color-management conversion."""
    h,w,_=pixels.shape
    def chunk(kind,data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    data=b''.join(b'\0'+row.tobytes() for row in pixels)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(data))+chunk(b'IEND',b''))


def color(mesh,rgb):
    rgb=np.asarray(rgb,dtype=float)
    if rgb.ndim==1:rgb=np.broadcast_to(rgb,(len(mesh.vertices),3))
    linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    attr=mesh.color_attributes.new(name='Source RGB',type='FLOAT_COLOR',domain='POINT')
    attr.data.foreach_set('color',np.column_stack([linear,np.ones(len(linear))]).ravel())
    mesh.color_attributes.active_color=attr


def clipped(mesh,crop):
    if not len(mesh.vertices):return
    xyz=np.empty(len(mesh.vertices)*3,dtype=np.float32);mesh.vertices.foreach_get('co',xyz);xyz=xyz.reshape(-1,3)
    bounds=np.asarray(crop)
    if np.all(xyz.min(0)>=bounds[:,0]) and np.all(xyz.max(0)<=bounds[:,1]):return
    bm=bmesh.new();bm.from_mesh(mesh)
    for axis,(lo,hi) in enumerate(crop):
        for value,sign in ((lo,-1),(hi,1)):
            normal=[0.,0.,0.];normal[axis]=sign;point=[0.,0.,0.];point[axis]=value
            bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-6,plane_co=point,plane_no=normal,clear_outer=True)
    bm.to_mesh(mesh);bm.free();mesh.update()


def collection(name):
    c=bpy.data.collections.new(name);bpy.context.scene.collection.children.link(c);return c


def triangle_mesh(name,vertices,faces):
    """Bulk RNA transfer avoids millions of temporary Python coordinate lists."""
    mesh=bpy.data.meshes.new(name)
    mesh.vertices.add(len(vertices));mesh.vertices.foreach_set('co',np.asarray(vertices,dtype=np.float32).ravel())
    mesh.loops.add(faces.size);mesh.loops.foreach_set('vertex_index',np.asarray(faces,dtype=np.int32).ravel())
    mesh.polygons.add(len(faces));mesh.polygons.foreach_set('loop_start',np.arange(len(faces),dtype=np.int32)*3)
    mesh.polygons.foreach_set('loop_total',np.full(len(faces),3,dtype=np.int32));mesh.update(calc_edges=True)
    return mesh


def feature_edges(mesh,col,name,width,angle):
    bm=bmesh.new();bm.from_mesh(mesh);bm.normal_update()
    segments=[]
    for e in bm.edges:
        if len(e.link_faces)==2 and e.calc_face_angle(0)<angle:continue
        segments.append([tuple(v.co) for v in e.verts])
    bm.free()
    # The old per-segment Curve splines + object.convert rebuilt the dependency
    # graph for every part. Construct the same uncapped four-sided line tubes in
    # bulk; Workbench rasterizes them directly, including hidden X-ray edges.
    points=np.asarray(segments,dtype=np.float32).reshape(-1,2,3)
    direction=points[:,1]-points[:,0];length=np.linalg.norm(direction,axis=1)
    valid=length>1e-12;points=points[valid];direction=direction[valid]/length[valid,None]
    up=np.array([0.,0.,1.],dtype=np.float32)-direction[:,2,None]*direction
    norm=np.linalg.norm(up,axis=1);vertical=norm<1e-6
    up[vertical]=[0.,-1.,0.];norm[vertical]=1.
    up/=norm[:,None];side=np.cross(direction,up)
    ring=np.stack([up,side,-up,-side],axis=1)*(width/2)
    vertices=(points[:,:,None,:]+ring[:,None,:,:]).reshape(-1,3)
    faces=(np.arange(len(points),dtype=np.int32)[:,None,None]*8+
           np.array([[0,4,7,3],[1,5,4,0],[2,6,5,1],[3,7,6,2]],dtype=np.int32)).reshape(-1,4)
    result=bpy.data.meshes.new(name)
    result.vertices.add(len(vertices));result.vertices.foreach_set('co',vertices.ravel())
    result.loops.add(faces.size);result.loops.foreach_set('vertex_index',faces.ravel())
    result.polygons.add(len(faces));result.polygons.foreach_set('loop_start',np.arange(len(faces),dtype=np.int32)*4)
    result.polygons.foreach_set('loop_total',np.full(len(faces),4,dtype=np.int32));result.update(calc_edges=True)
    obj=bpy.data.objects.new(name,result);col.objects.link(obj);color(result,[1,.24,.035]);return obj


def eligible_sources(scene,cfg):
    render_members=set()
    def collect(c):
        if c.exclude or c.collection.hide_render:return
        render_members.update(c.collection.objects)
        for child in c.children:collect(child)
    collect(bpy.context.view_layer.layer_collection)
    # Match the evaluated-geometry exporter: beveled curves and text are visible
    # surfaces too. Dropping them makes source-fit evidence misrepresent the room.
    renderable = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}
    return [o for o in scene.objects if o.type in renderable and o in render_members and not o.hide_render and o.name not in cfg.get('exclude_objects',[])]


class ModelViewCache:
    """Reuse only this invocation's frozen evaluated geometry, never old reviews."""
    def __init__(self):
        self.entries={};self.bounds={};self.meshes=set()

    def add(self,source,base,crop,model,edges,width,angle):
        identity=base.as_pointer()
        if identity not in self.bounds:
            xyz=np.empty(len(base.vertices)*3,dtype=np.float32)
            base.vertices.foreach_get('co',xyz);xyz=xyz.reshape(-1,3)
            self.bounds[identity]=(xyz.min(0),xyz.max(0)) if len(xyz) else None
        bounds=self.bounds[identity];box=np.asarray(crop)
        inside=bounds is None or (np.all(bounds[0]>=box[:,0]) and np.all(bounds[1]<=box[:,1]))
        # Different cameras/crops can share an entirely unclipped mesh. A crop
        # crossing the object must retain its exact planes, including cut edges.
        key=(identity,None if inside else tuple(map(tuple,crop)),width,angle)
        reused=key in self.entries
        if reused:
            mesh,edge_mesh=self.entries[key]
            edge=bpy.data.objects.new(source+' edges',edge_mesh);edges.objects.link(edge)
        else:
            mesh=base.copy();clipped(mesh,crop);color(mesh,[.78,.78,.78])
            edge=feature_edges(mesh,edges,source+' edges',width,angle)
            self.entries[key]=(mesh,edge.data);self.meshes.update((mesh,edge.data))
        obj=bpy.data.objects.new(source,mesh);model.objects.link(obj)
        return reused


def main():
    p=argparse.ArgumentParser();p.add_argument('--reference',required=True);p.add_argument('--cameras',required=True);p.add_argument('--inputs',required=True);p.add_argument('--config',required=True);p.add_argument('--out',required=True)
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
    cfg=json.loads(Path(a.config).read_text());cams=json.loads(Path(a.cameras).read_text())
    with np.load(a.reference) as archive:ref={key:archive[key] for key in archive.files}
    manifest=json.loads(Path(a.reference).with_name('manifest.json').read_text())
    if digest(a.reference) != manifest['layers_sha256']:
        raise ValueError('Reference bytes differ from manifest')
    if digest(a.cameras)!=manifest['cameras_sha256'] or digest(a.inputs)!=manifest['inputs_sha256']:
        raise ValueError('Reference provenance does not match supplied cameras/inputs')
    transform=validate(cfg,ref['world_transform'],cams['world_transform']);scene=bpy.context.scene
    # Diagnose the authored room before adding/clipping any reference geometry.
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
    from aha3d.blender.placement_check import check as check_placement
    from aha3d.placement.report import write_report as write_placement_report
    placement_dir=out/'placement';placement_dir.mkdir()
    placement_report=check_placement({'frame':cfg.get('model_frame',1)})
    write_placement_report(placement_dir,placement_report)
    print('PLACEMENT_CHECK '+json.dumps(placement_report['summary']))
    source_blend=bpy.data.filepath;original=list(scene.objects)
    sources=eligible_sources(scene,cfg)
    scene.frame_set(cfg.get('model_frame',1));dg=bpy.context.evaluated_depsgraph_get();base=[]
    for source in sources:
        mesh=bpy.data.meshes.new_from_object(source.evaluated_get(dg));mesh.transform(Matrix(transform.tolist())@source.matrix_world);base.append((source.name,mesh))
    for o in original:o.hide_render=True;o.hide_set(True)
    for marker in scene.timeline_markers:marker.camera=None
    scene.render.engine='BLENDER_WORKBENCH';scene.view_settings.view_transform='Standard';scene.view_settings.look='None';scene.view_settings.exposure=0;scene.view_settings.gamma=1
    if scene.world is None:scene.world=bpy.data.worlds.new('Inspection world')
    shade=scene.display.shading;shade.color_type='VERTEX';shade.show_shadows=False;shade.show_cavity=False;shade.show_specular_highlight=False;shade.background_type='WORLD';scene.world.color=(.07,.07,.07)
    scene.display.render_aa='16';scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
    scene.render.image_settings.color_mode='RGBA';scene.render.image_settings.color_depth='8';scene.render.film_transparent=False
    inp=np.load(a.inputs);input_frames=inp['frame_indices'].tolist();rgb=inp['rgb']
    hybrid = manifest.get('geometry_representation',{}).get('method') == 'tsdf-context'
    if hybrid and not all(key in ref for key in ('display_vertices','display_colors','display_faces','display_face_layer','display_face_role','context_point_indices')):
        raise ValueError('Hybrid reference is missing embedded display geometry')
    layers=['static','person','glass','mirror','geometry_invalid','semantic_unknown','context','context_points']
    shown = reference_layers(cfg, hybrid)
    geometry = {key:ref['display_'+key] if hybrid else ref[key] for key in ('vertices','colors','faces','face_layer')}
    face_layers=geometry['face_layer'];groups=[];metadata={'config':cfg,'world_transform':ref['world_transform'].tolist(),'source_scene':source_blend,'source_scene_sha256':digest(source_blend),'reference_sha256':digest(a.reference),'cameras_sha256':digest(a.cameras),'coordinate_policy':'One explicit basis and identical crop/camera per row; no independent fit','placement_report':'placement/report.json','coverage':'Missing surfaces unknown, not free space. Glass and mirror geometry unresolved.','geometry_method':manifest.get('geometry_representation',{}).get('method','grid'),'reference_layers':shown,'measurement_policy':manifest.get('measurement_policy'),'views':{}}
    views=dict(cfg['views'])
    metadata['overlay_modes']={
        'overlay_xray':'Default layout review: separate transparent edge pass alpha-composited over reference; no reference depth occlusion',
        'overlay_depth':'Depth review: opaque reference and model edges share the depth test',
        'overlay':'Compatibility alias of overlay_depth',
    }
    metadata['report']='report.html'
    metadata['default_layout_overlay']='overlay_xray'
    for frame in cfg.get('source_frames',[]):
        record=next((r for r in cams['frames'] if r['source_frame']==frame),None)
        if record is None or frame not in input_frames:raise ValueError(f'Native source frame missing: {frame}')
        views[f'source_{frame:06d}']={'source_record':record,'crop_xyz_m':cfg.get('source_crop_xyz_m',[[-1000,1000]]*3)}
    model_cache=ModelViewCache()
    for name,view in views.items():
        view_started=time.perf_counter()
        if not cfg.get('retain_view_geometry',True):
            for col in groups:
                for obj in list(col.objects):
                    data=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
                    if isinstance(data,bpy.types.Mesh) and data.users==0 and data not in model_cache.meshes:bpy.data.meshes.remove(data)
                bpy.data.collections.remove(col)
            groups=[]
        for col in groups:col.hide_render=True;col.hide_viewport=True
        model=collection(name+' / model clay');edges=collection(name+' / model edges');refs={x:collection(name+' / Pi3X '+x) for x in layers};groups += [model,edges,*refs.values()]
        model_started=time.perf_counter();cache_hits=0
        for source,base_mesh in base:
            cache_hits+=model_cache.add(source,base_mesh,view['crop_xyz_m'],model,edges,cfg.get('edge_width_m',.012),np.deg2rad(cfg.get('edge_angle_degrees',25)))
        model_seconds=time.perf_counter()-model_started
        reference_started=time.perf_counter()
        bad=np.flatnonzero(ref['finite'] & ~ref['geometry_valid'])
        stride=max(1,int(np.ceil(len(bad)/cfg.get('invalid_point_limit',10000))))
        points=ref['vertices'][bad[::stride]];radius=cfg.get('invalid_point_radius_m',.012)
        if len(points):
            vv=(points[:,None,:]+np.array([[0,0,radius],[radius,0,0],[0,radius,0],[-radius,-radius,-radius]])[None,:,:]).reshape(-1,3)
            ff=(np.arange(len(points))[:,None,None]*4+np.array([[0,1,2],[0,2,3],[0,3,1],[1,3,2]])[None,:,:]).reshape(-1,3)
            mm=bpy.data.meshes.new('Rejected finite samples');mm.from_pydata(vv.tolist(),[],ff.tolist());color(mm,[.9,.12,.7]);clipped(mm,view['crop_xyz_m']);oo=bpy.data.objects.new('Rejected finite samples (display subsample)',mm);refs['geometry_invalid'].objects.link(oo)
            oo['sampling_stride']=stride;oo['total_rejected_finite_samples']=len(bad)
        if hybrid:
            available=ref['context_point_indices']
            limit=int(cfg.get('context_point_limit',20000))
            if limit <= 0: raise ValueError('context_point_limit must be positive')
            stride=max(1,int(np.ceil(len(available)/limit)))
            selected=available[::stride];points=ref['vertices'][selected];radius=cfg.get('context_point_radius_m',.008)
            if len(points):
                vv=(points[:,None,:]+np.array([[0,0,radius],[radius,0,0],[0,radius,0],[-radius,-radius,-radius]])[None,:,:]).reshape(-1,3)
                ff=(np.arange(len(points))[:,None,None]*4+np.array([[0,1,2],[0,2,3],[0,3,1],[1,3,2]])[None,:,:]).reshape(-1,3)
                mm=triangle_mesh('Source context points without triangles',vv,ff)
                color(mm,np.repeat(ref['colors'][selected]/255.,4,axis=0));clipped(mm,view['crop_xyz_m'])
                oo=bpy.data.objects.new('Pi3X context points (display subsample)',mm);refs['context_points'].objects.link(oo)
                oo['sampling_stride']=stride;oo['total_context_points']=len(available)
                oo['meaning']='Uncertain reference points without reliable triangle support; not measurements'
        for index,layer in enumerate(layers):
            if hybrid:
                select = face_layers == index
                if layer == 'static': select &= ref['display_face_role'] == 0
                elif layer == 'context': select = (face_layers == 0) & (ref['display_face_role'] == 1)
                elif layer in ('geometry_invalid','context_points'): continue
            else:
                select = face_layers == index
            faces=geometry['faces'][select]
            if len(faces)==0:continue
            used,inverse=np.unique(faces,return_inverse=True);mesh=triangle_mesh(layer,geometry['vertices'][used],inverse.reshape(-1,3));color(mesh,geometry['colors'][used]/255.)
            clipped(mesh,view['crop_xyz_m']);obj=bpy.data.objects.new('Pi3X '+layer,mesh);refs[layer].objects.link(obj)
            obj['meaning']='Semantic prediction only; geometry validity and completeness are separate'
        reference_seconds=time.perf_counter()-reference_started
        data=bpy.data.cameras.new(name);cam=bpy.data.objects.new(name,data);scene.collection.objects.link(cam);scene.camera=cam;data.clip_end=2000
        if 'source_record' in view:
            rec=view['source_record'];k=np.asarray(rec['intrinsics']);w,h=cams['processed_size_wh'];ratio=k[0,0]/k[1,1]
            scene.render.pixel_aspect_x=max(1.,1./ratio);scene.render.pixel_aspect_y=max(1.,ratio)
            data.type='PERSP';data.sensor_fit='HORIZONTAL';data.sensor_width=36;data.lens=k[0,0]*36/w;data.shift_x=(w/2-k[0,2])/w;data.shift_y=(k[1,2]-h/2)*ratio/w
            cam.matrix_world=Matrix((np.asarray(rec['c2w'])@np.diag([1,-1,-1,1])).tolist());scene.render.resolution_x=w;scene.render.resolution_y=h
            pixels=rgb[input_frames.index(rec['source_frame'])];save_rgb(out/(name+'_source.png'),pixels);im=bpy.data.images.load(str(out/(name+'_source.png')))
            im.use_fake_user=True;im.pack()
        else:
            scene.render.pixel_aspect_x=scene.render.pixel_aspect_y=1;scene.render.resolution_x=scene.render.resolution_y=cfg.get('resolution',900)
            data.type='ORTHO';data.ortho_scale=view['ortho_scale'];cam.location=view['location'];cam.rotation_euler=(Vector(view['target'])-cam.location).to_track_quat('-Z','Y').to_euler()
            if 'rotation_euler' in view:cam.rotation_euler=view['rotation_euler']
        bpy.context.view_layer.update()
        metadata['views'][name]={'camera_matrix_world':np.asarray(cam.matrix_world).tolist(),'settings':view,'outputs':[]}
        preparation_seconds=time.perf_counter()-view_started
        for mode in ('reference','model','overlay','uncertainty'):
            model.hide_render=mode!='model';edges.hide_render=mode!='overlay'
            for layer,col in refs.items():
                col.hide_render=(layer not in shown if mode in ('reference','overlay') else (layer not in cfg.get('uncertainty_layers',['glass','mirror','semantic_unknown','context','context_points']) if mode=='uncertainty' else True))
            shade.light='STUDIO' if mode=='model' else 'FLAT'
            scene.render.filepath=str(out/f'{name}_{mode}.png');bpy.ops.render.render(write_still=True);metadata['views'][name]['outputs'].append(scene.render.filepath)
        depth_path=out/f'{name}_overlay_depth.png'
        depth_path.write_bytes((out/f'{name}_overlay.png').read_bytes())
        # A separate transparent pass prevents reference surfaces (including
        # uncertain context) from hiding authored edges. Keep identical geometry,
        # camera and crop; never offset geometry to force an edge into view.
        model.hide_render=True;edges.hide_render=False
        for col in refs.values():col.hide_render=True
        scene.render.film_transparent=True;shade.light='FLAT'
        edge_path=out/f'{name}_edges.png';scene.render.filepath=str(edge_path)
        try:
            bpy.ops.render.render(write_still=True)
        finally:
            scene.render.film_transparent=False
        xray_path=out/f'{name}_overlay_xray.png'
        composite_xray(out/f'{name}_reference.png',edge_path,xray_path,scene)
        metadata['views'][name]['outputs'].extend(map(str,[depth_path,edge_path,xray_path]))
        model.hide_render=True;edges.hide_render=False
        for layer,col in refs.items():col.hide_render=layer not in shown
        timing=dict(preparation_seconds=preparation_seconds,model_seconds=model_seconds,
                    reference_seconds=reference_seconds,render_and_composite_seconds=time.perf_counter()-view_started-preparation_seconds,
                    model_cache_hits=cache_hits,model_objects=len(base))
        metadata['views'][name]['timing']=timing
        print('INSPECTION_TIMING '+json.dumps(dict(view=name,**timing)),flush=True)
    # Last view is visible on reopen; every layer remains independently toggleable.
    for col in groups:col.hide_viewport=col.hide_render
    (out/'inspection.json').write_text(json.dumps(metadata,indent=2));write_report(out,metadata)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'inspection.blend'))

if __name__=='__main__':main()

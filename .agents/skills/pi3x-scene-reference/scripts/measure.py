"""Export configurable dimensioned views and source-linked measurement records."""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import re
import textwrap
import numpy as np
from PIL import Image,ImageDraw
from drawing import Sheet,font

def write_json(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def require(condition,message):
    if not condition:raise ValueError(message)
def validate_config(spec):
    require(isinstance(spec,dict),'Config must be an object')
    for key in ['landmarks','measurements']:require(isinstance(spec.get(key,[]),list),key+' must be a list')
    all_ids=set();point_ids=set()
    for group in ['landmarks','measurements']:
        for item in spec.get(group,[]):
            identifier=item.get('id','')
            require(isinstance(identifier,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,23}',identifier),'Use short alphanumeric IDs')
            require(identifier not in all_ids,'Duplicate ID: '+identifier);all_ids.add(identifier)
            require(isinstance(item.get('label'),str) and bool(item['label'].strip()),'Every item needs a label')
            if group=='landmarks':
                point_ids.add(identifier);uv=item.get('pixel_uv')
                require(type(item.get('source_frame')) is int and item['source_frame']>=0,'source_frame must be a nonnegative integer')
                require(isinstance(uv,list) and len(uv)==2 and all(type(v) is int for v in uv),'pixel_uv must contain two integers')
    for m in spec.get('measurements',[]):
        require(m.get('kind') in ['horizontal_distance','distance_3d','median_height','vertical_distance'],'Unknown measurement kind')
        pts=m.get('points',[]);require(isinstance(pts,list) and len(pts)>0 and all(p in point_ids for p in pts),'Unknown/empty measurement endpoints')
        if m['kind']!='median_height':require(len(pts)==2 and pts[0]!=pts[1],'Distance measurements require two distinct points')
    for line in spec.get('polylines',[]):require(len(line)>=2 and all(p in point_ids for p in line),'Invalid polyline')

def value_for(kind,points):
    if kind=='horizontal_distance':return float(np.linalg.norm(points[0,:2]-points[1,:2]))
    if kind=='distance_3d':return float(np.linalg.norm(points[0]-points[1]))
    if kind=='median_height':return float(np.median(points[:,2]))
    if kind=='vertical_distance':return float(abs(points[0,2]-points[1,2]))
    raise ValueError(kind)

def load_reference(source,spec,cameras_path=None):
    validate_config(spec)
    manifest=json.loads((source/'inputs.json').read_text());camera=json.loads(Path(cameras_path or source/'cameras.json').read_text())
    transform=np.array(camera['world_transform'],dtype=float)
    require(transform.shape==(4,4) and np.isfinite(transform).all(),'Invalid world transform')
    require(np.allclose(transform[:3,:3]@transform[:3,:3].T,np.eye(3),atol=1e-4) and np.linalg.det(transform[:3,:3])>0.999,'World transform must be a rigid proper rotation/translation; scale is separate')
    ids=manifest['frame_indices'];times=manifest['timestamps_seconds'];size=manifest['processed_size_wh']
    require(len(ids)==len(times)==len(camera['frames']) and len(ids)>0 and len(set(ids))==len(ids),'Frame/camera counts or IDs disagree')
    require(np.isfinite(times).all() and np.all(np.diff(times)>0),'Nonmonotonic timestamps')
    floor=spec.get('floor_reference')
    if not floor and 'floor_alignment' in camera and 'plane_normal_raw' in camera['floor_alignment']:
        floor='Automatic floor hypothesis from reconstruction; physical height unverified'
    require(floor or not any(m['kind']=='median_height' for m in spec.get('measurements',[])),
            'Height requires floor_reference or an exported floor hypothesis; camera-up alone is insufficient')
    threshold=float(spec.get('confidence_min',0.5));patch_limit=float(spec.get('patch_span_max_m',0.12))
    require(0<threshold<1 and math.isfinite(patch_limit) and patch_limit>0,'Invalid endpoint quality thresholds')
    marks=[]
    with np.load(source/'predictions.npz',allow_pickle=False) as pred:
        points=pred['points'];confidence=pred['conf']
        require(points.shape==(len(ids),size[1],size[0],3),'Prediction shape does not match input manifest')
        require(confidence.shape==(*points.shape[:-1],1),'Confidence shape does not match predictions')
        for mark in spec.get('landmarks',[]):
            require(mark['source_frame'] in ids,'Landmark frame not in cached reconstruction: '+str(mark['source_frame']))
            row=ids.index(mark['source_frame']);u,v=mark['pixel_uv'];h,w=points.shape[1:3]
            require(1<=u<w-1 and 1<=v<h-1,'Endpoint requires an in-bounds 3x3 patch: '+mark['id'])
            xyz=points[row,v,u]@transform[:3,:3].T+transform[:3,3]
            patch=points[row,v-1:v+2,u-1:u+2]@transform[:3,:3].T+transform[:3,3]
            quality=float(1/(1+np.exp(-np.clip(confidence[row,v,u,0],-50,50))))
            span=np.ptp(patch.reshape(-1,3),axis=0)
            require(np.isfinite(patch).all() and quality>=threshold and max(span)<=patch_limit,'Unreliable endpoint '+mark['id'])
            marks.append({**mark,'prediction_row':row,'timestamp_seconds':times[row],'xyz_predicted_m':xyz.tolist(),
                          'model_confidence_score':quality,'patch_3x3_span_predicted_m':span.tolist()})
        raw_cameras=pred['camera_poses']
    poses=np.array([f['c2w'] for f in camera['frames']],dtype=float)
    require(np.allclose(poses,transform@raw_cameras,atol=1e-4),'Exported cameras do not match raw poses/world transform')
    require([f['source_frame'] for f in camera['frames']]==ids and np.allclose([f['timestamp_seconds'] for f in camera['frames']],times),'Camera frame/timestamp identity differs from inputs')
    with np.load(source/'reference_samples.npz',allow_pickle=False) as sample:
        cloud=np.array(sample['points'],dtype=float)
        colors=np.array(sample['colors']) if 'colors' in sample.files else None
        if cameras_path is not None:
            require('source_flat_indices' in sample.files,'Alternate cameras require source-linked sample indices')
            indices=sample['source_flat_indices']
            require(indices.shape==(len(cloud),) and np.issubdtype(indices.dtype,np.integer) and
                    np.all((indices>=0)&(indices<points.size//3)),'Invalid sample source indices')
            cloud=points.reshape(-1,3)[indices]@transform[:3,:3].T+transform[:3,3]
    require(colors is None or colors.shape==cloud.shape and np.isfinite(colors).all() and colors.min()>=0 and colors.max()<=255,'Invalid sample RGB colors')
    require(cloud.ndim==2 and cloud.shape[1]==3 and len(cloud)>0 and np.isfinite(cloud).all(),'Invalid reference sample cloud')
    with np.load(source/'inputs.npz',allow_pickle=False) as z:rgb=z['rgb']
    require(rgb.shape==(len(ids),size[1],size[0],3),'RGB shape mismatch')
    by_id={p['id']:p for p in marks};measurements=[]
    for m in spec.get('measurements',[]):
        value=value_for(m['kind'],np.array([by_id[p]['xyz_predicted_m'] for p in m['points']]))
        require(math.isfinite(value),'Nonfinite measurement')
        measurements.append({**m,'value_predicted_m':value,'status':'sample-based estimate; physical accuracy unverified'})
    return manifest,camera,marks,measurements,cloud,rgb,floor,colors

def source_sheets(out,manifest,rgb,marks,selection_method):
    images=[];names=[]
    for frame in sorted({p['source_frame'] for p in marks}):
        frame_marks=[p for p in marks if p['source_frame']==frame];row=manifest['frame_indices'].index(frame)
        for page,start in enumerate(range(0,len(frame_marks),8),1):
            subset=frame_marks[start:start+8];im=Image.new('RGB',(1760,1200),'white');d=ImageDraw.Draw(im)
            d.text((35,25),'Source measurement points',fill='black',font=font(34))
            d.text((35,80),f'Frame {frame} | t={manifest["timestamps_seconds"][row]:g} s | processed-image pixels',fill='black',font=font(23))
            base=Image.fromarray(rgb[row]);factor=min(1300/base.width,830/base.height)
            shape=(round(base.width*factor),round(base.height*factor));base=base.resize(shape,Image.Resampling.NEAREST)
            left,top=35,145;im.paste(base,(left,top));d=ImageDraw.Draw(im)
            for index,p in enumerate(subset):
                u,v=p['pixel_uv'];x,y=left+u*factor,top+v*factor
                dx,dy=p.get('label_offset_px',[35,-25 if index%2==0 else 25])
                tx=np.clip(x+dx*factor,left+85,left+shape[0]-85);ty=np.clip(y+dy*factor,top+25,top+shape[1]-25)
                d.line((x,y,tx,ty),fill='white',width=5);d.line((x,y,tx,ty),fill='black',width=2)
                d.ellipse((x-5,y-5,x+5,y+5),fill='white',outline='black',width=2)
                width=d.textbbox((0,0),p['id'],font=font(22))[2]
                d.rectangle((tx-width/2-4,ty-16,tx+width/2+4,ty+16),fill='white',outline='black')
                d.text((tx-width/2,ty-13),p['id'],fill='black',font=font(22))
                sy=155+index*108;d.text((1370,sy),p['id'],fill='black',font=font(26))
                for j,line in enumerate(textwrap.wrap(p['label'],27)[:2]):d.text((1370,sy+35+j*25),line,fill='black',font=font(20))
            for j,line in enumerate(textwrap.wrap('Selection: '+selection_method,112)[:3]):d.text((35,1030+j*31),line,fill='black',font=font(21))
            name=f'source_{frame:06d}_{page:02d}.png';im.save(out/name);names.append(name);images.append(im)
    return images,names


def display_filter(cloud,cfg,scale):
    """Display-only axis slicing; named measurement XYZ and cameras stay unchanged."""
    ranges=cfg.get('clip_xyz_m',{})
    require(isinstance(ranges,dict) and set(ranges)<=set('xyz'),'clip_xyz_m uses x/y/z intervals')
    keep=np.ones(len(cloud),dtype=bool)
    for axis,bounds in ranges.items():
        bounds=np.asarray(bounds,dtype=float)*scale
        require(bounds.shape==(2,) and np.isfinite(bounds).all() and bounds[1]>bounds[0],'Invalid display clip interval')
        values=cloud[:, 'xyz'.index(axis)];keep &= (values>=bounds[0]) & (values<=bounds[1])
    return keep

def render(out,spec,cloud,marks,measurements,camera,scale,floor,status,colors=None):
    mode=spec.get('color_mode','rgb');require(mode in ('rgb','gray'),'color_mode must be rgb or gray')
    require(mode!='rgb' or colors is not None,'RGB reference requires saved colors; explicitly select gray for a legacy bundle')
    views=spec.get('views',{});all_axes={'top':[0,1],'front':[0,2],'side':[1,2]}
    require(isinstance(views,dict) and set(views)<=set(all_axes),'Views must use top/front/side names')
    grid=float(spec.get('grid_m',0.5));require(math.isfinite(grid) and grid>0,'grid_m must be positive')
    xyz={p['id']:np.array(p['xyz_m']) for p in marks};poses=np.array([f['c2w'] for f in camera['frames']]);poses[:,:3,3]*=scale
    ranges={};groups={}
    for name,axes in all_axes.items():
        cfg=views.get(name,{})
        if 'bounds' in cfg:
            bound=np.asarray(cfg['bounds'],dtype=float)*scale
            require(bound.shape==(2,2) and np.isfinite(bound).all() and np.all(bound[:,1]>bound[:,0]),'Invalid view bounds')
        else:
            lo,hi=np.percentile(cloud[:,axes],[1,99],axis=0)
            support=np.array(list(xyz.values())+[p[:3,3] for p in poses])[:,axes]
            lo=np.minimum(lo,support.min(0));hi=np.maximum(hi,support.max(0))
            if 2 in axes and floor:lo[axes.index(2)]=min(0,lo[axes.index(2)])
            bound=np.stack([np.floor((lo-grid/2)/grid)*grid,np.ceil((hi+grid/2)/grid)*grid],axis=1)
        require(np.max((bound[:,1]-bound[:,0])/grid)<150,'Grid is too dense; increase grid_m')
        ranges[name]=bound
        chosen=cfg.get('measurements')
        if chosen is not None:
            require(isinstance(chosen,list) and all(mid in {m['id'] for m in measurements} for mid in chosen),'Unknown view measurement ID')
            ms=[m for m in measurements if m['id'] in chosen]
        else:ms=[m for m in measurements if (name=='top' and m['kind'] in ['horizontal_distance','distance_3d']) or (name!='top' and m['kind'] in ['median_height','vertical_distance','distance_3d'])]
        require(name!='top' or not any(m['kind'] in ['median_height','vertical_distance'] for m in ms),'Heights are not visible in top projection')
        groups[name]=[ms[i:i+6] for i in range(0,len(ms),6)] or [[]]
    ppm=min(min(1080/(b[0,1]-b[0,0]),1030/(b[1,1]-b[1,0])) for b in ranges.values())
    images=[];names=[];view_records=[]
    for name,axes in all_axes.items():
        cfg=views.get(name,{})
        keep=display_filter(cloud,cfg,scale)
        require(keep.any(),'View filter leaves no observed points: '+name)
        display_cloud=cloud[keep];display_colors=colors[keep] if mode=='rgb' else None
        for page,ms in enumerate(groups[name],1):
            sheet=Sheet(name.upper()+' / metric reference',axes,ranges[name],display_cloud,1,grid=grid,ppm=ppm,status=status,
                        colors=display_colors,floor_label='Z=0: estimated/supplied floor; see measurements.json for provenance.' if floor else 'Z=0 is a coordinate reference, not an established floor. Heights are unavailable.')
            sheet.legend(ms)
            if cfg.get('clip_xyz_m'):
                sheet.d.text((1260,1100),'View filter (predicted m):',fill='black',font=font(17))
                sheet.d.text((1260,1125),str(cfg['clip_xyz_m'])[:48],fill='black',font=font(16))
            for line in spec.get('polylines',[]):sheet.line([xyz[p] for p in line],width=2)
            used=set(p for m in ms for p in m['points'])
            for mark in marks:
                if mark['id'] in used:sheet.point(xyz[mark['id']],mark['id'],offset=tuple(cfg.get('point_label_offsets',{}).get(mark['id'],[15,-20])))
            for j,m in enumerate(ms):
                pts=np.array([xyz[p] for p in m['points']]);offset=float(cfg.get('dimension_offsets',{}).get(m['id'],55+35*(j%3)))
                if m['kind']=='median_height':
                    b=pts.mean(0);b[2]=m['value_m'];a=b.copy();a[2]=0
                elif m['kind']=='vertical_distance':
                    a,b=pts.copy();b[:2]=a[:2]
                else:a,b=pts
                suffix=' (3D)' if m['kind']=='distance_3d' else ''
                sheet.dimension(a,b,f"{m['id']}: ~{m['value_m']:.2f} m{suffix}",offset)
            if name=='top':
                sheet.line(poses[:,:3,3],color=(110,110,110),width=2)
                count=spec.get('camera_labels',5);require(type(count) is int and 0<=count<=20,'camera_labels must be an integer from 0 to 20')
                for i in np.unique(np.linspace(0,len(poses)-1,min(count,len(poses))).round().astype(int)) if count else []:
                    sheet.point(poses[i,:3,3],f"{camera['frames'][i]['timestamp_seconds']:.2f}s",offset=tuple(cfg.get('camera_label_offsets',{}).get(str(camera['frames'][i]['source_frame']),[55,0])))
            filename=f'{name}_{page:02d}.png';sheet.im.save(out/filename);images.append(sheet.im);names.append(filename)
            view_records.append({'file':filename,'axes':axes,'bounds_m':ranges[name].tolist(),'pixels_per_metre':ppm,'grid_m':grid,'measurements':[m['id'] for m in ms],'color_mode':mode,'displayed_points':int(keep.sum()),'clip_xyz_m':cfg.get('clip_xyz_m',{}),'display_filter_changes_measurements':False})
    return images,names,view_records

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True,help='Cached reconstruction directory')
    parser.add_argument('--cameras',type=Path,help='Alternate rigid camera basis, e.g. alignment/cameras.json; reprojects source-linked samples')
    parser.add_argument('--config',type=Path,help='JSON measurement specification; omit for grid-only references')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--known-distance',help='Any measurement ID from the config')
    parser.add_argument('--known-length-m',type=float)
    parser.add_argument('--scale-source',help='Describe the physical measurement or explicitly label an assumed/test length')
    args=parser.parse_args()
    require(bool(args.known_distance)==(args.known_length_m is not None),'Supply both known-distance and known-length-m')
    spec=json.loads(args.config.read_text()) if args.config else {}
    source=args.input.resolve();out=args.output.resolve()
    require(not out.exists(),'Output already exists; use a new directory')
    manifest,camera,marks,measurements,cloud,rgb,floor,colors=load_reference(source,spec,args.cameras)
    scale=1.0;calibration={'status':'uncalibrated Pi3X prediction','factor':1.0,'physical_accuracy_validated':False}
    if args.known_distance:
        require(args.known_length_m>0 and math.isfinite(args.known_length_m),'Known length must be finite and positive')
        require(bool(args.scale_source and args.scale_source.strip()),'Record --scale-source for a physical cue, assumption, or test')
        anchor=next((m for m in measurements if m['id']==args.known_distance),None)
        require(anchor is not None and anchor['value_predicted_m']>0,'Invalid or zero calibration anchor')
        scale=args.known_length_m/anchor['value_predicted_m']
        calibration={'status':'scaled to supplied reference; independent accuracy unverified','factor':scale,
                     'anchor_measurement':args.known_distance,'anchor_length_m':args.known_length_m,
                     'source':args.scale_source,'physical_accuracy_validated':False}
    for mark in marks:mark['xyz_m']=(np.array(mark['xyz_predicted_m'])*scale).tolist()
    for m in measurements:m['value_m']=m['value_predicted_m']*scale
    cloud*=scale;out.mkdir(parents=True,exist_ok=False)
    status='Pi3X predicted scale, not physically calibrated' if not args.known_distance else f'Scale x {scale:.5f}; see calibration source in JSON'
    images,names,view_records=render(out,spec,cloud,marks,measurements,camera,scale,floor,status,colors)
    selection=spec.get('selection_method','No semantic endpoints selected; grid-only reference')
    source_images,source_names=source_sheets(out,manifest,rgb,marks,selection);images+=source_images
    images[0].save(out/'measurement_sheets.pdf',save_all=True,append_images=images[1:],resolution=150)
    write_json(out/'config_snapshot.json',spec)
    export={'schema_version':1,'units':'metres','calibration':calibration,'floor_reference':floor,
            'coordinate_system':{'axes':'inherited aligned world XYZ; Z up','source_world_transform':camera['world_transform'],
                                 'scale_after_source_world_transform':scale},
            'source':{'bundle':str(source),'processed_size_wh':manifest['processed_size_wh'],
                      'config':str(args.config.resolve()) if args.config else None,
                      'cameras_path':str((args.cameras or source/'cameras.json').resolve())},
            'landmark_selection_method':selection,'landmarks':marks,'measurements':measurements,'views':view_records,
            'source_point_images':source_names,'display_precision_m':0.01,'display_precision_is_accuracy':False,
            'unknown_space_is_free_space':False,'source_pixel_ids_are_persistent_tracks':False}
    write_json(out/'measurements.json',export)
    with (out/'measurements.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['id','label','kind','value_m','value_predicted_m','points','scale_factor'])
        for m in measurements:writer.writerow([m['id'],m['label'],m['kind'],m['value_m'],m['value_predicted_m'],';'.join(m['points']),scale])
    with (out/'landmarks.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['id','label','x_m','y_m','z_m','source_frame','time_seconds','pixel_u','pixel_v','quality_score'])
        for p in marks:writer.writerow([p['id'],p['label'],*p['xyz_m'],p['source_frame'],p['timestamp_seconds'],*p['pixel_uv'],p['model_confidence_score']])
    frames=[]
    for frame in camera['frames']:
        pose=np.array(frame['c2w']);pose[:3,3]*=scale;frames.append({**frame,'c2w':pose.tolist()})
    # Keep source alignment and subsequent scaling distinct; camera rotations
    # stay orthonormal rather than multiplying an entire pose matrix by scale.
    camera_export={k:v for k,v in camera.items() if k not in ['frames','world_transform','units']}
    camera_export.update({'units':'metres with scale provenance','source_world_transform':camera['world_transform'],
                          'scale_after_source_world_transform':scale,'calibration':calibration,'frames':frames})
    write_json(out/'cameras.json',camera_export)
    with (out/'camera_positions.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['source_frame','time_seconds','x_m','y_m','z_m'])
        for frame in frames:writer.writerow([frame['source_frame'],frame['timestamp_seconds'],*np.array(frame['c2w'])[:3,3].tolist()])
    rows=['# Scene measurements','',f"Scale: **{calibration['status']}**.",'',
          '| ID | Measurement | Estimate | Source points |','| --- | --- | ---: | --- |']
    rows += [f"| {m['id']} | {m['label'].replace('|','/')} | ~{m['value_m']:.2f} m | {', '.join(m['points'])} |" for m in measurements]
    rows+=['','[Measurement sheets PDF](measurement_sheets.pdf) · [Agent JSON](measurements.json) · [Measurement CSV](measurements.csv) · [Landmark CSV](landmarks.csv) · [Camera times and positions](camera_positions.csv)','',
           'Views: '+ ' · '.join(f'[{n}]({n})' for n in names),'',
           'Source endpoints: '+ (' · '.join(f'[{n}]({n})' for n in source_names) or 'none selected'),'',
           'Distances use the named 3D samples. Horizontal distances use XY; 3D distances use XYZ; heights use Z above the stated floor reference. Diagram arrows are projections of those definitions. Missing surfaces remain unknown.','',
           'Display rounding to 0.01 m is not an accuracy claim. Interior endpoint samples are not certified physical object bounds. See config_snapshot.json for endpoint and view settings.','']
    (out/'MEASUREMENTS.md').write_text('\n'.join(rows))
    reread=json.loads((out/'measurements.json').read_text());by_id={p['id']:np.array(p['xyz_m']) for p in reread['landmarks']}
    for m in reread['measurements']:require(np.isclose(value_for(m['kind'],np.array([by_id[p] for p in m['points']])),m['value_m'],atol=1e-10),'Exported dimension mismatch')
    with (out/'measurements.csv').open() as f:csv_rows=list(csv.DictReader(f))
    require(len(csv_rows)==len(measurements),'CSV row count mismatch')
    for row,m in zip(csv_rows,measurements):require(row['id']==m['id'] and float(row['value_m'])==m['value_m'],'CSV/JSON mismatch')
    for old,new in zip(camera['frames'],frames):
        require(np.allclose(np.array(old['c2w'])[:3,3]*scale,np.array(new['c2w'])[:3,3]),'Camera scale mismatch')
        require(np.allclose(np.array(old['c2w'])[:3,:3],np.array(new['c2w'])[:3,:3]),'Camera rotation changed')
    for n in names+source_names:
        with Image.open(out/n) as im:im.load()
    write_json(out/'validation.json',{'status':'passed','job_id':os.environ.get('INDOOR_RUN_ID'),
        'checks':['input/camera identity and world transform','endpoint quality and bounds','dimensions from exported XYZ',
                  'CSV/JSON equality','camera scaling preserves rotations','all diagram PNGs decode'],
        'visual_review':'required separately','physical_accuracy_validated':False,'model_inference_performed':False})
    print(out)

if __name__=='__main__':main()

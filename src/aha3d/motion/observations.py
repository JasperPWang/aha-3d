"""Review cached SAM full-body/leg predictions without repeating inference."""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from aha3d.io import digest, read, write


def draw_full_body(image, record, names, labels=True, banner=True):
    im = image.copy(); d = ImageDraw.Draw(im); uv = np.asarray(record['keypoints_2d'])
    index = {name:i for i,name in enumerate(names)}
    edges = [('shoulder','elbow'),('elbow','wrist'),('shoulder','hip'),('hip','knee'),('knee','ankle'),
             ('ankle','heel'),('heel','big-toe-tip'),('big-toe-tip','small-toe-tip'),('small-toe-tip','heel')]
    for side,color in [('left','#00e5ff'),('right','#ffad19')]:
        for a,b in edges:
            if side+'-'+a in index and side+'-'+b in index:
                points=uv[[index[side+'-'+a],index[side+'-'+b]]]
                if np.isfinite(points).all():d.line([tuple(x) for x in points],fill=color,width=2)
        for joint in ('hip','knee','ankle','heel','big-toe-tip'):
            if side+'-'+joint not in index:continue
            x,y=uv[index[side+'-'+joint]]
            if 0<=x<im.width and 0<=y<im.height:
                d.ellipse((x-3,y-3,x+3,y+3),fill=color)
                if labels and joint in ('knee','ankle'):d.text((x+4,y-10),side[0].upper()+' '+joint,fill=color,stroke_width=1,stroke_fill='black')
    for joint in ('shoulder','hip'):
        if all(side+'-'+joint in index for side in ('left','right')):
            d.line([tuple(uv[index[side+'-'+joint]]) for side in ('left','right')],fill='white',width=2)
    if banner:
        d.rectangle((0,0,im.width,25),fill='#222222')
        d.text((6,7),f"Frame {record['source_frame']} | SAM full body | cyan LEFT / orange RIGHT",fill='white')
    return im


def paired_crop(source, record, names):
    """Enlarge source and overlay together; preserve aspect and identical crop."""
    from PIL import ImageOps
    box=np.asarray(record['bbox_xyxy'],dtype=float)+[-18,-12,18,12]
    box=np.rint(np.clip(box,[0,0,0,0],[source.width,source.height,source.width,source.height])).astype(int)
    if box[2]<=box[0] or box[3]<=box[1]:raise ValueError('Invalid body crop')
    tile=Image.new('RGB',(672,430),'#eeeeee');d=ImageDraw.Draw(tile)
    d.text((8,8),f"Frame {record['source_frame']} | source / SAM | cyan LEFT, orange RIGHT",fill='black')
    overlay=draw_full_body(source,record,names,labels=False,banner=False)
    for i,im in enumerate((source,overlay)):
        crop=ImageOps.contain(im.crop(tuple(box)),(328,390),Image.Resampling.NEAREST)
        tile.paste(crop,(i*336+(336-crop.width)//2,32+(390-crop.height)//2))
    return tile


def merge_observations(values, person_id=None):
    if not values:raise ValueError('At least one observation bundle required')
    if len(values)>1 and not person_id:raise ValueError('Merging requires an explicitly reviewed person_id; identity is not inferred')
    base=dict(values[0]);frames={}
    fields=('source_sha256','pi3x_inputs_sha256','pi3x_cameras_sha256','processed_size_wh','keypoint_names','coordinate_convention')
    for value in values:
        if value.get('person_id') and person_id and value['person_id']!=person_id:
            raise ValueError('Person identity differs from the reviewed merge identity')
        if any(value[k]!=base[k] for k in fields):raise ValueError('Observation bundles differ in source/camera/keypoint contract')
        model_fields=('model_revision','dinov3_revision','checkpoint_sha256','mhr_sha256','checkpoint_config_sha256')
        if any(value.get(k)!=base.get(k) for k in model_fields):
            raise ValueError('Observation model/weight versions differ; do not attribute mixed estimates to the first model')
        for record in value['frames']:
            key=record['source_frame']
            if key in frames:raise ValueError('Duplicate source frame: do not silently replace cached observations')
            frames[key]=record
    base['frames']=[frames[k] for k in sorted(frames)]
    if person_id:base['person_id']=person_id
    base['identity_note']='Caller-reviewed identity; no automatic identity association'
    return base


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--observations',type=Path,nargs='+',required=True);p.add_argument('--pi3x',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--person-id',help='Explicitly reviewed identity for merging sparse batches')
    a=p.parse_args()
    obs=merge_observations([read(path) for path in a.observations],a.person_id);inp=read(a.pi3x/'inputs.json')
    if obs['source_sha256']!=inp['source_sha256'] or obs['pi3x_inputs_sha256']!=digest(a.pi3x/'inputs.json') or obs['pi3x_cameras_sha256']!=digest(a.pi3x/'cameras.json'):
        raise ValueError('Same-shot original bundle hashes required')
    with np.load(a.pi3x/'inputs.npz') as z:rgb=z['rgb']
    a.out.mkdir(parents=True,exist_ok=False);(a.out/'overlays').mkdir();(a.out/'crops').mkdir()
    records=[];tiles=[];crops=[];names=obs['keypoint_names'];legnames=[side+'-'+joint for side in ('left','right') for joint in ('hip','knee','ankle','heel','big-toe-tip','small-toe-tip')]
    for record in obs['frames']:
        row=inp['frame_indices'].index(record['source_frame']);im=draw_full_body(Image.fromarray(rgb[row]),record,names)
        im.save(a.out/'overlays'/f"{record['source_frame']:06d}.png")
        crop=paired_crop(Image.fromarray(rgb[row]),record,names)
        crop.save(a.out/'crops'/f"{record['source_frame']:06d}.jpg",quality=95);crops.append(crop)
        uv=np.asarray(record['keypoints_2d']);pts=np.asarray(record['keypoints_camera_m']);ids=[names.index(n) for n in legnames]
        inside=np.isfinite(uv[ids]).all(1)&(uv[ids,0]>=0)&(uv[ids,0]<im.width)&(uv[ids,1]>=0)&(uv[ids,1]<im.height)
        records.append(dict(source_frame=record['source_frame'],timestamp_seconds=record['timestamp_seconds'],landmarks_in_frame=dict(zip(legnames,inside.tolist())),reviewed=False,visibility='Not inferred: in-frame does not mean visible',legs={side:dict(thigh_length_camera_m=float(np.linalg.norm(pts[names.index(side+'-knee')]-pts[names.index(side+'-hip')])),shin_length_camera_m=float(np.linalg.norm(pts[names.index(side+'-ankle')]-pts[names.index(side+'-knee')]))) for side in ('left','right')}))
        tiles.append(im.resize((672,378)))
    # Paginate to keep source landmarks readable rather than one enormous thumbnail sheet.
    sheets=[]
    for start in range(0,len(tiles),6):
        chosen=tiles[start:start+6];sheet=Image.new('RGB',(1344,378*((len(chosen)+1)//2)),'white')
        for i,im in enumerate(chosen):sheet.paste(im,((i%2)*672,(i//2)*378))
        name=f'contact_{start//6+1:02d}.jpg';sheet.save(a.out/name,quality=94);sheets.append(name)
        crop_sheet=Image.new('RGB',(1344,430*((len(chosen)+1)//2)),'white')
        for i,crop in enumerate(crops[start:start+6]):crop_sheet.paste(crop,((i%2)*672,(i//2)*430))
        crop_sheet.save(a.out/f'crops_{start//6+1:02d}.jpg',quality=95)
    write(a.out/'observations.json',obs)
    write(a.out/'review.json',dict(status='needs_visual_review',frames=records,contact_sheets=sheets,inputs={str(path):digest(path) for path in a.observations},limits='Single-image estimates; no confidence/occlusion output or ground-contact certification. Adjacent samples must be inspected before temporal use.'))


if __name__=='__main__':main()

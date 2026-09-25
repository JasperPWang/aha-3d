#!/usr/bin/env python3
"""Decode the complete result, audit parameter coverage and create review sheets."""
import argparse,json,importlib.util
from pathlib import Path
import av,numpy as np,torch
from PIL import Image,ImageDraw
p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);a=p.parse_args()
out=a.output.resolve()
spec=importlib.util.spec_from_file_location('gvhmr_run',Path(__file__).with_name('run.py'))
entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
reference=entry.probe_video(out/'0_input_video.mp4')
validation={'normalized_input':reference,'outputs':{},'visual_review':'pending'}
for name in ['1_incam.mp4','2_global.mp4','3_incam_global_horiz.mp4'] + (['4_source_overlay.mp4'] if (out/'4_source_overlay.mp4').exists() else []):
 metadata=entry.probe_video(out/name)
 entry.check_timing(reference,metadata)
 validation['outputs'][name]=metadata
(out/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
pred=torch.load(out/'hmr4d_results.pt',map_location='cpu',weights_only=False)
bbx=torch.load(out/'preprocess/bbx.pt',map_location='cpu',weights_only=False)['bbx_xyxy'].numpy()
frames=[]
with av.open(str(out/'1_incam.mp4')) as container:
 for frame in container.decode(video=0):
  frames.append(frame.to_image())
report={'frames':len(frames),'fps':30,'parameter_groups':{},'visual_review':'pending','accuracy_vs_ground_truth':'not measured','room_alignment':'not performed'}
for group in ['smpl_params_global','smpl_params_incam']:
 params=pred[group];report['parameter_groups'][group]={}
 for name,value in params.items():
  array=value.detach().cpu().numpy()
  assert np.isfinite(array).all(),(group,name)
  assert array.shape[0]==len(frames),(group,name,array.shape,len(frames))
  report['parameter_groups'][group][name]={'shape':list(array.shape),'finite':True}
 translation=params['transl'].numpy()
 step=np.linalg.norm(np.diff(translation,axis=0),axis=-1)
 report['parameter_groups'][group]['root_motion']={'path_length_m':float(step.sum()),'max_step_m':float(step.max()),'median_step_m':float(np.median(step))}
assert len(bbx)==len(frames)
arrays={'fps':np.array(30.0),'frame_times_seconds':np.arange(len(frames),dtype=np.float64)/30}
for group in ['smpl_params_global','smpl_params_incam']:
 for name,value in pred[group].items():
  arrays[group+'__'+name]=value.detach().cpu().numpy()
arrays['K_fullimg']=pred['K_fullimg'].detach().cpu().numpy()
np.savez_compressed(out/'motion_native.npz',**arrays)
review=out/'review';review.mkdir(exist_ok=True)
ids=np.unique(np.round(np.linspace(0,len(frames)-1,48)).astype(int))
for page in range(3):
 sheet=Image.new('RGB',(1024,1560),'white');draw=ImageDraw.Draw(sheet)
 for slot,idx in enumerate(ids[page*16:(page+1)*16]):
  im=frames[idx];box=bbx[idx];cx=(box[0]+box[2])/2;cy=(box[1]+box[3])/2
  w=(box[2]-box[0])*1.3;h=(box[3]-box[1])*1.15
  crop=im.crop((int(max(0,cx-w/2)),int(max(0,cy-h/2)),int(min(im.width,cx+w/2)),int(min(im.height,cy+h/2))))
  crop.thumbnail((256,360));x=slot%4*256;y=slot//4*390
  sheet.paste(crop,(x+(256-crop.width)//2,y+25));draw.text((x+8,y+5),f'frame {idx}, {idx/30:.2f}s',fill='black')
 sheet.save(review/f'body_crops_{page+1}.jpg',quality=92)
report['crop_review_frame_ids']=ids.tolist()
(out/'parameter_validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))

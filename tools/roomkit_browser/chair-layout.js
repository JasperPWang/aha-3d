import {randomFor} from './seeded-layout.js';

export function placedBox(box, position=[0,0,0], yaw=0) {
 const c=Math.cos(yaw),s=Math.sin(yaw),local=box.min.map((v,i)=>(v+box.max[i])/2);
 return {center:[position[0]+c*local[0]-s*local[1],position[1]+s*local[0]+c*local[1],position[2]+local[2]],
  half:box.min.map((v,i)=>(box.max[i]-v)/2),yaw,owner:box.owner,name:box.name};
}
export function overlap(a,b,margin=0) {
 if(Math.abs(a.center[2]-b.center[2])>=a.half[2]+b.half[2]+margin)return false;
 const axes=y=>[[Math.cos(y),Math.sin(y)],[-Math.sin(y),Math.cos(y)]],aa=axes(a.yaw),bb=axes(b.yaw);
 for(const axis of [...aa,...bb]){
  const dot=v=>Math.abs(v[0]*axis[0]+v[1]*axis[1]);
  if(Math.abs((a.center[0]-b.center[0])*axis[0]+(a.center[1]-b.center[1])*axis[1])>=
   a.half[0]*dot(aa[0])+a.half[1]*dot(aa[1])+b.half[0]*dot(bb[0])+b.half[1]*dot(bb[1])+margin)return false;
 }
 return true;
}
export function insideFloor(context,x,y){
 if(context.floorTriangles){
  return context.floorTriangles.some(([a,b,c])=>{
   const cross=(p,q)=>(q[0]-p[0])*(y-p[1])-(q[1]-p[1])*(x-p[0]);
   const d=[cross(a,b),cross(b,c),cross(c,a)];
   return d.every(v=>v>=-1e-8)||d.every(v=>v<=1e-8);
  });
 }
 return !!context.floor&&x>=context.floor[0]&&y>=context.floor[1]&&x<=context.floor[2]&&y<=context.floor[3];
}
export function dimensionsReason(template,slot){
 const spec=template.specification,limits=slot.limits,[w,d,h]=spec.dimensions_m;
 if(w>limits.max_width_m)return 'too wide';
 if(d>limits.max_depth_m)return 'too deep';
 if(h>limits.max_height_m)return 'too tall';
 if(!spec.seat)return 'seat specification unavailable';
 if(spec.seat.height_m<limits.seat_height_range_m[0]||spec.seat.height_m>limits.seat_height_range_m[1])return 'seat height mismatch';
 return null;
}
export function replacementReason(template,slot){
 if(!slot.seating_type||!slot.source_model_id)return 'source chair type unavailable';
 if(!template.seating_type||!template.model_id)return 'candidate chair type unavailable';
 if(template.seating_type!==slot.seating_type)return 'different seating type';
 if(template.asset_id===slot.original_asset_id||template.model_id===slot.source_model_id)return 'original chair model';
 return null;
}
export function candidate(template,slot,position){
 return {id:slot.id,template:template.id,asset_id:template.asset_id,position,yaw:slot.yaw,
  box:placedBox(template.specification,position,slot.yaw),parts:template.proxies.map(b=>placedBox(b,position,slot.yaw)),
  rear:placedBox({min:[template.specification.min[0],template.specification.max[1]+.005,.08],
   max:[template.specification.max[0],template.specification.max[1]+slot.limits.rear_clearance_m,.90]},position,slot.yaw)};
}
export function collisionReason(choice,context,margin=.003){
 for(const obstacle of context.solids){
  if(!overlap(choice.box,obstacle,margin))continue;
  if(choice.parts.some(p=>overlap(p,obstacle,margin)))return 'collision: '+(obstacle.name||obstacle.owner||'room');
 }
 for(const envelope of context.motion){
  if(overlap(choice.box,envelope,margin)&&choice.parts.some(p=>overlap(p,envelope,margin)))return 'human animation clearance';
 }
 for(const obstacle of context.fixtures){if(overlap(choice.rear,obstacle,margin))return 'rear access blocked';}
 if(context.floor){
  const [xmin,ymin,xmax,ymax]=context.floor;
  const b=choice.box,c=Math.abs(Math.cos(b.yaw)),s=Math.abs(Math.sin(b.yaw)),rx=c*b.half[0]+s*b.half[1],ry=s*b.half[0]+c*b.half[1];
  if(b.center[0]-rx<xmin||b.center[0]+rx>xmax||b.center[1]-ry<ymin||b.center[1]+ry>ymax)return 'outside floor';
  for(const x of [-b.half[0],b.half[0]])for(const y of [-b.half[1],b.half[1]]){
   if(!insideFloor(context,b.center[0]+Math.cos(b.yaw)*x-Math.sin(b.yaw)*y,b.center[1]+Math.sin(b.yaw)*x+Math.cos(b.yaw)*y))return 'outside floor surface';
  }
 }
 return null;
}
function compatible(a,b){
 if(overlap(a.rear,b.box)||overlap(b.rear,a.box))return false;
 return !overlap(a.box,b.box)||!a.parts.some(p=>b.parts.some(q=>overlap(p,q,.003)));
}
// Preserve connectivity of the source walkable component at the stated grid
// resolution. Footprints include a navigation radius, not just point reachability.
export function navigationPreserved(context,original,proposed){
 if(!context.floor)return false;
 const [x0,y0,x1,y1]=context.floor,step=.12,radius=.15,nx=Math.ceil((x1-x0)/step),ny=Math.ceil((y1-y0)/step);
 const grid=chairs=>{
  const result=new Uint8Array(nx*ny),obstacles=[...context.navigation,...chairs.map(c=>c.box)];
  for(let y=0;y<ny;y++)for(let x=0;x<nx;x++){
   const px=x0+(x+.5)*step,py=y0+(y+.5)*step;
   if(px<x0+radius||py<y0+radius||px>x1-radius||py>y1-radius)continue;
   if(![[0,0],[-radius,-radius],[-radius,radius],[radius,-radius],[radius,radius]].every(([dx,dy])=>insideFloor(context,px+dx,py+dy)))continue;
   const probe={center:[px,py,context.floorZ+.50],half:[radius,radius,.44],yaw:0};
   if(!obstacles.some(b=>overlap(probe,b)))result[y*nx+x]=1;
  }
  return result;
 };
 const before=grid(original),after=grid(proposed),flood=(mask,start)=>{
  const seen=new Uint8Array(mask.length),queue=[start];seen[start]=1;
  for(let i=0;i<queue.length;i++){
   const p=queue[i],x=p%nx,y=Math.floor(p/nx);
   for(const q of [x>0?p-1:-1,x<nx-1?p+1:-1,y>0?p-nx:-1,y<ny-1?p+nx:-1])if(q>=0&&mask[q]&&!seen[q]){seen[q]=1;queue.push(q);}
  }return {seen,queue};
 };
 let largest=[],visited=new Uint8Array(before.length);
 for(let i=0;i<before.length;i++)if(before[i]&&!visited[i]){const c=flood(before,i);for(const j of c.queue)visited[j]=1;if(c.queue.length>largest.length)largest=c.queue;}
 const kept=largest.filter(i=>after[i]);if(!kept.length)return false;
 const reachable=flood(after,kept[0]).seen;
 return kept.every(i=>reachable[i]);
}
export function planChairs(spec,seed,context){
 const rng=randomFor(seed,'chairs-grouped-v3'),rejections={},choices=[],groups=new Map();
 const reject=(asset,reason)=>{if(!rejections[asset])rejections[asset]={};rejections[asset][reason]=(rejections[asset][reason]||0)+1;};
 for(const slot of spec.slots){
  const group=slot.replacement_group_id||slot.source_model_id||slot.id;
  if(!groups.has(group))groups.set(group,{id:group,seating_type:slot.seating_type,source_model_id:slot.source_model_id,slot_ids:[]});
  groups.get(group).slot_ids.push(slot.id);
  const valid=[];
  for(const template of spec.templates){
   const reason=replacementReason(template,slot)||dimensionsReason(template,slot);if(reason){reject(template.asset_id,reason);continue;}
   // Swapping changes the model, never the user's current placement anchor.
   const choice=candidate(template,slot,[...slot.position]),failure=collisionReason(choice,context,slot.limits.collision_margin_m);
    if(failure)reject(template.asset_id,failure);else valid.push({...choice,rank:rng()});
  }
  valid.sort((a,b)=>a.rank-b.rank);choices.push({slot:slot.id,group,valid});
 }
 // A model must fit every seat in its source group. Never repair a failed
 // group by mixing individually valid models at different seats.
 for(const group of groups.values()){
  const members=choices.filter(c=>c.group===group.id);
  const common=[...new Set(members[0].valid.map(v=>v.asset_id))].filter(asset=>members.every(c=>c.valid.some(v=>v.asset_id===asset)));
  group.compatible_assets=common;
  for(const member of members){
   for(const asset of new Set(member.valid.map(v=>v.asset_id)))if(!common.includes(asset))reject(asset,'does not fit every chair in its source group');
   member.valid=member.valid.filter(v=>common.includes(v.asset_id));
  }
 }
 choices.sort((a,b)=>a.valid.length-b.valid.length);
 const original=spec.slots.map(s=>({box:placedBox(s.original_specification,s.position,s.yaw)}));
 let attempts=0,completeAttempts=0,solution=null;
 function search(index,selected,groupAssets=new Map()){
  if(++attempts>3000||completeAttempts>=20)return false;
  if(index===choices.length){completeAttempts++;if(!navigationPreserved(context,original,selected))return false;solution=selected;return true;}
  const {group,valid}=choices[index];
  for(const option of valid){
   if(groupAssets.has(group)&&groupAssets.get(group)!==option.asset_id)continue;
   if(selected.every(other=>compatible(option,other))&&search(index+1,[...selected,option],new Map([...groupAssets,[group,option.asset_id]])))return true;
  }
  return false;
 }
 search(0,[]);
 return {version:2,scope:'chairs',seed:String(seed),passed:!!solution,attempts,completeAttempts,rejections,
  groups:[...groups.values()].map(g=>({...g,chosen_asset_id:solution?.find(p=>g.slot_ids.includes(p.id))?.asset_id||null})),
  slots:choices.map(c=>({id:c.slot,valid_candidates:c.valid.length})),
  reason:solution?null:choices.some(c=>!c.valid.length)?'No same-type alternative fits every chair in its source group':'No complete arrangement found within the access/search limits',
  placements:solution?solution.sort((a,b)=>a.id.localeCompare(b.id)).map(({id,template,asset_id,position,yaw})=>({id,template,asset_id,position,yaw})):[]};
}

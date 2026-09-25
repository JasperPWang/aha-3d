import * as THREE from 'three';
import {placedBox,planChairs,replacementReason} from './chair-layout.js';

// Upright component boxes retain their actual world yaw. Tilted/sheared parts
// use a conservative world AABB. A rotated room must not acquire solid corners
// simply because its coordinate frame differs from the original demo.
export function meshProxy(mesh,bounds){
 const axes=[0,1,2].map(i=>new THREE.Vector3().setFromMatrixColumn(mesh.matrixWorld,i)),scale=axes.map(v=>v.length());
 if(scale.some(s=>s<1e-8))return placedBox(bounds);
 axes.forEach(v=>v.normalize());
 if(Math.abs(axes[2].z)<1-1e-6||Math.abs(axes[0].z)>1e-6||Math.abs(axes[1].z)>1e-6||Math.abs(axes[0].dot(axes[1]))>1e-6)return placedBox(bounds);
 if(!mesh.geometry.boundingBox)mesh.geometry.computeBoundingBox();const local=mesh.geometry.boundingBox;
 return {center:local.getCenter(new THREE.Vector3()).applyMatrix4(mesh.matrixWorld).toArray(),
  half:local.getSize(new THREE.Vector3()).toArray().map((s,i)=>s*scale[i]/2),yaw:Math.atan2(axes[0].y,axes[0].x),owner:bounds.owner,name:bounds.name};
}

export function createChairs({data,scene,pickables,placements,objectMeshes,materials,onChange}){
 const spec=data.chairs;if(!spec)return null;
 const $=id=>document.getElementById(id),ids=new Set(spec.slots.map(s=>s.id)),templates=new Map(spec.templates.map(t=>[t.id,t]));
 for(const record of data.objects)if(ids.has(record.instance_id))record.movable=true;
 const originals=new Map([...ids].map(id=>[id,{meshes:objectMeshes.get(id).slice(),record:{...data.objects.find(o=>o.instance_id===id)}}]));
 const prototypes=new Map(spec.templates.map(t=>[t.id,t.meshes.map(m=>{
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(m.positions,3));g.setAttribute('normal',new THREE.Float32BufferAttribute(m.normals,3));
  const indices=[];for(const group of m.groups){g.addGroup(indices.length,group.indices.length,group.material);for(const index of group.indices)indices.push(index);}g.setIndex(indices);g.computeBoundingSphere();
  const mesh=new THREE.Mesh(g,materials);mesh.name=m.name;mesh.matrixAutoUpdate=false;mesh.matrix.fromArray(m.matrix);return mesh;
 })]));
 const motion=spec.motion_envelopes.map(b=>placedBox(b));
 let layout={version:1,scope:'chairs',seed:'original',placements:[]},lastReport=null;
 function currentSlots(){
  return spec.slots.map(s=>{
   const anchor=layout.placements.find(p=>p.id===s.id)?.position||s.position,offset=placements.get(s.id).position;
   return {...s,position:[anchor[0]+offset.x,anchor[1]+offset.y,s.position[2]]};
  });
 }
 function context(){
  scene.updateMatrixWorld(true);const solids=[],fixtures=[],navigation=[],floorTriangles=[],floorZ=spec.floor_support.height_m;let floor=null;
  const actorIds=new Set(data.animation?.actors.map(a=>a.owner)||[]);
  for(const mesh of pickables){
   const id=mesh.userData.owner;if(ids.has(id)||actorIds.has(id)||mesh.userData.joint)continue;
   const record=data.objects.find(o=>o.instance_id===id),bounds=new THREE.Box3().setFromObject(mesh),b={min:bounds.min.toArray(),max:bounds.max.toArray(),owner:id,name:mesh.name};
   const support=spec.floor_support.surfaces.find(s=>s.name===mesh.name);
   if(support&&Math.abs(b.max[2]-floorZ)<=.04){
    floor=floor?[Math.min(floor[0],b.min[0]),Math.min(floor[1],b.min[1]),Math.max(floor[2],b.max[0]),Math.max(floor[3],b.max[1])]:[b.min[0],b.min[1],b.max[0],b.max[1]];
    const offset=placements.get(id)?.getWorldPosition(new THREE.Vector3())||new THREE.Vector3();
    floorTriangles.push(...support.triangles_xy.map(t=>t.map(([x,y])=>[x+offset.x,y+offset.y])));continue;
   }
   if(/rug|carpet|fringe/i.test(mesh.name)||record?.semantic_class==='rug')continue;
   if(b.max[2]<floorZ+.04)continue;
   const proxy=meshProxy(mesh,b);solids.push(proxy);
   if(!record?.support_id){fixtures.push(proxy);if(b.min[2]<floorZ+.94&&b.max[2]>floorZ+.06)navigation.push(proxy);}
  }
  for(const b of spec.joint_envelopes){
   const offset=placements.get(b.owner)?.getWorldPosition(new THREE.Vector3()).toArray()||[0,0,0],proxy=placedBox(b,offset);
   solids.push(proxy);fixtures.push(proxy);
  }
  return {solids,fixtures,navigation,motion,floor,floorZ,floorTriangles};
 }
 function replace(id,meshes){
  for(const mesh of objectMeshes.get(id)||[]){mesh.removeFromParent();const index=pickables.indexOf(mesh);if(index>=0)pickables.splice(index,1);}
  const group=placements.get(id);group.position.set(0,0,0);
  for(const mesh of meshes){group.add(mesh);pickables.push(mesh);}objectMeshes.set(id,meshes);
 }
 function apply(plan){
  // All geometry is prepared before touching the live scene. Failed plans do
  // not alter objects, selection, seed, or the previous accepted arrangement.
  const prepared=plan.placements.map(p=>{
   const matrix=new THREE.Matrix4().makeRotationZ(p.yaw);matrix.setPosition(...p.position);
   return {p,meshes:prototypes.get(p.template).map(m=>{const mesh=m.clone();mesh.matrix.premultiply(matrix);const proxy=templates.get(p.template).proxies.find(b=>b.name===m.name);mesh.userData={owner:p.id,chair:true,chairProxy:placedBox(proxy,p.position,p.yaw)};return mesh;})};
  });
  for(const {p,meshes} of prepared){replace(p.id,meshes);const template=templates.get(p.template),record=data.objects.find(o=>o.instance_id===p.id);
   Object.assign(record,{asset_id:template.asset_id,label:template.label,movable:true});}
  layout=JSON.parse(JSON.stringify(plan));onChange?.();
 }
 function reportText(report){
  $('chair-result').textContent=report.passed?`${report.placements.length} chairs replaced in ${report.groups.length} matching group(s) · seed ${report.seed}`:`Layout kept · ${report.reason}`;
  const reasons=Object.entries(report.rejections).map(([asset,counts])=>`${spec.templates.find(t=>t.asset_id===asset)?.label||asset}: ${Object.keys(counts).join('; ')}`);
  $('chair-rejections').textContent=reasons.join('\n')||'All candidates satisfy the individual checks.';
 }
 function regenerate(seed,asset=''){
  const request={...spec,slots:currentSlots(),templates:asset?spec.templates.filter(t=>t.asset_id===asset):spec.templates};
  lastReport=planChairs(request,seed,context());
  if(lastReport.passed){apply(lastReport);$('chair-seed').value=seed;const params=new URLSearchParams(location.hash.slice(1));params.set('chairSeed',seed);if(asset)params.set('chairAsset',asset);else params.delete('chairAsset');history.replaceState(null,'','#'+params);}
  reportText(lastReport);return lastReport;
 }
 function original(){
  for(const [id,source] of originals){replace(id,source.meshes);const record=data.objects.find(o=>o.instance_id===id);for(const key of Object.keys(record))delete record[key];Object.assign(record,source.record);}
  layout={version:1,scope:'chairs',seed:'original',placements:[]};lastReport=null;onChange?.();
  const params=new URLSearchParams(location.hash.slice(1));params.delete('chairSeed');params.delete('chairAsset');history.replaceState(null,'',location.pathname+location.search+(params.size?'#'+params:''));
  $('chair-result').textContent='Original chairs restored';$('chair-rejections').textContent='';
 }
 function inspect(id){
  const slot=spec.slots.find(s=>s.id===id);if(!slot)return null;
  const placement=layout.placements.find(p=>p.id===id),template=placement?templates.get(placement.template):null;
  return {slot_id:id,group_id:slot.group_id,table_id:slot.table_id,supported_by:spec.floor_support.id,
   replacement_group_id:slot.replacement_group_id,seating_type:slot.seating_type,source_model_id:slot.source_model_id,
   replacement_rule:'Same source model uses one alternative asset of the same seating type',
   source_asset_id:slot.original_asset_id,source_uniform_scale:slot.original_uniform_scale,source_scale:slot.original_scale,
   specification:template?.specification||slot.original_specification,limits:slot.limits,
   placement:{...placement,position:currentSlots().find(s=>s.id===id).position,yaw:slot.yaw},seed:layout.seed,
   validation:Math.hypot(placements.get(id).position.x,placements.get(id).position.y)>1e-8?'Manually moved; swap clearance has not been revalidated at this position':placement?'Native size, component collision proxies, all-frame human envelopes, sampled cabinet sweep, rear access and navigation grid passed':'Source arrangement; not a new clearance acceptance'};
 }
 $('chair-controls').hidden=false;$('chair-result').textContent=`Original chairs · ${spec.slots.length} seats · matching groups`;$('chair-asset').append(new Option('Match each original chair group',''));
 for(const t of spec.templates)if(spec.slots.every(s=>!replacementReason(t,s)))$('chair-asset').append(new Option(t.label,t.asset_id));
 $('swap-chairs').onclick=()=>regenerate(String(crypto.getRandomValues(new Uint32Array(1))[0]),$('chair-asset').value);
 $('rebuild-chairs').onclick=()=>regenerate($('chair-seed').value.trim()||'chairs-1',$('chair-asset').value);
 $('original-chairs').onclick=original;$('chair-seed').value='chairs-1';
 const params=new URLSearchParams(location.hash.slice(1));if(params.has('chairSeed')){$('chair-asset').value=params.get('chairAsset')||'';regenerate(params.get('chairSeed'),$('chair-asset').value);}
 return {spec,context,regenerate,original,inspect,has:id=>ids.has(id),get layout(){const slots=currentSlots();return JSON.parse(JSON.stringify({...layout,currentPlacementValidated:layout.seed!=='original'&&[...ids].every(id=>Math.hypot(placements.get(id).position.x,placements.get(id).position.y)<1e-8),anchors:slots.map(s=>({id:s.id,position:s.position,yaw:s.yaw})),placements:layout.placements.map(p=>({...p,position:slots.find(s=>s.id===p.id).position}))}));},get lastReport(){return lastReport;}};
}

import * as THREE from 'three';
import * as CANNON from 'cannon-es';
import {generateLayout} from './seeded-layout.js';
import {createSupportBody} from './support-physics.js';
import {createMeshBody} from './mesh-physics.js';
import {containsCircle} from './support-geometry.js';

export function createTabletop({data,scene,pickables,placements,objectMeshes,materials,onChange,status}) {
 const spec=data.tabletop;if(!spec)return null;
 const physicsHz=120, stepTime=1/physicsHz, maxSubsteps=4;
 const world=new CANNON.World({gravity:new CANNON.Vec3(0,0,-9.81),allowSleep:true});
 world.broadphase=new CANNON.SAPBroadphase(world);world.solver.iterations=20;
 world.defaultContactMaterial.friction=.5;world.defaultContactMaterial.restitution=.12;
 world.defaultContactMaterial.contactEquationStiffness=1e7;
 const entries=new Map(), templates=new Map(spec.templates.map(t=>[t.id,t]));
 const sourceIds=new Set(spec.supports.flatMap(s=>s.source_ids));
 const originalMeshes=pickables.filter(m=>sourceIds.has(m.userData.owner));
 const originalRecords=data.objects.filter(o=>sourceIds.has(o.instance_id));
 const prototypeMeshes=new Map(), statics=[];
 let paused=spec.start_paused===true, held=null, layout=null, steps=0, contactCount=0, requestId=0;
 window.addEventListener('keydown',e=>{if(e.key==='Escape')requestId++;});
 function makeMesh(m) {
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(m.positions,3));
  g.setAttribute('normal',new THREE.Float32BufferAttribute(m.normals,3));
  const indices=[];for(const group of m.groups){g.addGroup(indices.length,group.indices.length,group.material);for(const i of group.indices)indices.push(i);}
  g.setIndex(indices);g.computeBoundingSphere();
  const mesh=new THREE.Mesh(g,materials);mesh.matrixAutoUpdate=false;mesh.matrix.fromArray(m.matrix);mesh.name=m.name;
  return mesh;
 }
 for(const t of spec.templates)if(t.meshes)prototypeMeshes.set(t.id,t.meshes.map(makeMesh));
 const pendingModels=new Map();
 async function loadTemplate(id){
  if(prototypeMeshes.has(id))return;
  if(pendingModels.has(id))return pendingModels.get(id);
  const task=(async()=>{const response=await fetch(templates.get(id).meshes_url);if(!response.ok)throw Error('Model download failed ('+response.status+')');
   const meshes=JSON.parse(await new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).text());
   prototypeMeshes.set(id,meshes.map(makeMesh));})();pendingModels.set(id,task);
  try{await task;}finally{pendingModels.delete(id);}
 }
 const shapeFor=t=>new CANNON.ConvexPolyhedron({vertices:t.hull.vertices.map(v=>new CANNON.Vec3(...v)),faces:t.hull.faces});
 scene.updateMatrixWorld(true);
 // Transformed convex proxies per solid mesh retain table legs and chair gaps. Roof,
 // actors and thin decorative carpet details are outside this solver.
 function rebuildStatics(){
 for(const s of statics)world.removeBody(s.body);statics.length=0;scene.updateMatrixWorld(true);
 for(const mesh of pickables) {
  if(spec.supports.some(s=>s.footprint&&s.mesh===mesh.name)||mesh.userData.tabletop||sourceIds.has(mesh.userData.owner)||mesh.userData.cutaway||mesh.userData.joint||data.animation?.actors.some(a=>a.mesh_name===mesh.name))continue;
  if(/rug|carpet|fringe|flower|petal|leaf/i.test(mesh.name))continue;
  const box=new THREE.Box3().setFromObject(mesh),size=box.getSize(new THREE.Vector3());
  if(Math.min(size.x,size.y,size.z)<.004)continue;
  const proxy=mesh.userData.chairProxy,offset=placements.get(mesh.userData.owner)?.getWorldPosition(new THREE.Vector3())||new THREE.Vector3();
  const center=proxy?new THREE.Vector3(...proxy.center).add(offset):box.getCenter(new THREE.Vector3());
  if(proxy)size.set(...proxy.half.map(v=>v*2));
  const body=proxy?new CANNON.Body({mass:0,shape:new CANNON.Box(new CANNON.Vec3(size.x/2,size.y/2,size.z/2)),position:new CANNON.Vec3(...center)}):createMeshBody(mesh);
  if(!body)continue;
  center.set(...body.position.toArray());
  if(proxy)body.quaternion.setFromAxisAngle(new CANNON.Vec3(0,0,1),proxy.yaw);
  world.addBody(body);statics.push({body,mesh,center:center.clone(),origin:placements.get(mesh.userData.owner)?.getWorldPosition(new THREE.Vector3())||new THREE.Vector3()});
 }
 for(const s of spec.supports){
  if(!s.footprint)continue;
  const body=createSupportBody(s);world.addBody(body);
  statics.push({body,mesh:{userData:{}},center:new THREE.Vector3(...body.position.toArray()),origin:new THREE.Vector3()});
 }
 for(const e of entries.values())e.body.wakeUp();
 }
 rebuildStatics();
 function syncStatics() {
  for(const s of statics) {
   // Ordinary furniture placement remains translation-only.
   const delta=s.mesh.userData.owner?placements.get(s.mesh.userData.owner)?.getWorldPosition(new THREE.Vector3()):null;
   const next=s.center.clone().add(delta||new THREE.Vector3()).sub(s.origin);
   if(s.body.position.distanceTo(new CANNON.Vec3(...next))>1e-6){s.body.position.set(...next);s.body.aabbNeedsUpdate=true;for(const e of entries.values())e.body.wakeUp();}
  }
 }
 function syncVisual(e){const offset=e.body.quaternion.vmult(e.com);e.group.position.set(e.body.position.x-offset.x,e.body.position.y-offset.y,e.body.position.z-offset.z);e.group.quaternion.copy(e.body.quaternion);}
 function add(record) {
  const t=templates.get(record.template),group=new THREE.Group();scene.add(group);
  group.name=record.id;
  const meshes=prototypeMeshes.get(t.id).map(m=>{const mesh=m.clone();mesh.userData={owner:record.id,tabletop:true};group.add(mesh);pickables.push(mesh);return mesh;});
  placements.set(record.id,group);objectMeshes.set(record.id,meshes);
  data.objects.push({instance_id:record.id,semantic_class:`tabletop/${t.category}`,asset_id:t.asset_id,support_id:record.support,movable:true,label:t.label});
  const body=new CANNON.Body({mass:t.mass,position:new CANNON.Vec3(...record.position),linearDamping:.15,angularDamping:.25,sleepSpeedLimit:.12,sleepTimeLimit:.8});
  const com=new CANNON.Vec3(...(t.center_of_mass||[0,0,0]));
  if(t.collision?.kind==='sphere'){
   body.addShape(new CANNON.Sphere(t.collision.radius),com.negate());body.angularDamping=.05;
  }else if(t.collision?.kind==='box'){
   body.addShape(new CANNON.Box(new CANNON.Vec3(...t.collision.half)),com.negate());
  }else if(t.collision?.kind==='basket'||t.collision?.kind==='cup'){
   // Separate tier bottoms and rim segments leave the container interior open.
   for(const tier of t.collision.tiers){
    const rotation=new CANNON.Quaternion();rotation.setFromAxisAngle(new CANNON.Vec3(1,0,0),Math.PI/2);
    const thickness=tier.thickness??.008,bottom=tier.bottom??tier.z-.038,height=tier.height??.038,x=tier.x??0,y=tier.y??0;
    const baseRadius=tier.baseRadius??tier.radius,wallBottom=tier.wallBottom??bottom;
    body.addShape(new CANNON.Cylinder(baseRadius,baseRadius,thickness,12),new CANNON.Vec3(x-com.x,y-com.y,bottom+thickness/2-com.z),rotation);
    for(let i=0;i<12;i++){
     const angle=i*Math.PI*2/12,q=new CANNON.Quaternion();q.setFromAxisAngle(new CANNON.Vec3(0,0,1),angle+Math.PI/2);
     body.addShape(new CANNON.Box(new CANNON.Vec3(Math.PI*tier.radius/12+.002,.004,height/2)),new CANNON.Vec3(x+Math.cos(angle)*tier.radius-com.x,y+Math.sin(angle)*tier.radius-com.y,wallBottom+height/2-com.z),q);
    }
   }
   const post=t.collision.post;if(post){const q=new CANNON.Quaternion();q.setFromAxisAngle(new CANNON.Vec3(1,0,0),Math.PI/2);body.addShape(new CANNON.Cylinder(post.radius,post.radius,post.top-post.bottom,12),new CANNON.Vec3(post.x-com.x,post.y-com.y,(post.bottom+post.top)/2-com.z),q);}
   const handle=t.collision.handle;if(handle)for(let i=0;i<12;i++){const angle=handle.start+(handle.end-handle.start)*i/11;body.addShape(new CANNON.Sphere(handle.tube),new CANNON.Vec3(handle.x+handle.radius*Math.cos(angle)-com.x,handle.y-com.y,handle.z+handle.radius*Math.sin(angle)-com.z));}
  }else body.addShape(shapeFor(t),com.negate());
  body.quaternion.setFromAxisAngle(new CANNON.Vec3(0,0,1),record.yaw||0);
  body.position.vadd(body.quaternion.vmult(com),body.position);world.addBody(body);
  const e={id:record.id,body,group,template:t,record,com};entries.set(e.id,e);syncVisual(e);
 }
 function clear(){
  if(held)release(true);
  for(const e of entries.values()) {
   world.removeBody(e.body);scene.remove(e.group);placements.delete(e.id);objectMeshes.delete(e.id);
   for(let i=pickables.length-1;i>=0;i--)if(pickables[i].userData.owner===e.id)pickables.splice(i,1);
   const i=data.objects.findIndex(o=>o.instance_id===e.id);if(i>=0)data.objects.splice(i,1);
  }
  entries.clear();world.accumulator=0;
 }
 // Replace original browser representations with equivalent centered physics
 // instances; the exported source records and the .blend are untouched on disk.
 for(const m of originalMeshes){m.visible=false;const i=pickables.indexOf(m);if(i>=0)pickables.splice(i,1);}
 for(const o of originalRecords){data.objects.splice(data.objects.indexOf(o),1);placements.get(o.instance_id)?.removeFromParent();}
 function apply(next){clear();layout=next;for(const record of next.placements)add(record);onChange?.();status(`Seed ${next.seed} · ${entries.size} tabletop objects`);}
 function original(){requestId++;apply({version:1,scope:'tabletop',seed:'original',placements:originalRecords.map(o=>({id:o.instance_id,template:o.instance_id,support:o.support_id,position:templates.get(o.instance_id).source_center.slice(),yaw:0}))});}
 function regenerate(seed){
  const token=++requestId,next=generateLayout(spec,seed),missing=[...new Set(next.placements.map(p=>p.template))].filter(id=>!prototypeMeshes.has(id));
  if(!missing.length){apply(next);return true;}
  status('Loading tabletop models… · Escape to cancel');
  return Promise.all(missing.map(loadTemplate)).then(()=>{if(token!==requestId)return false;apply(next);return true;}).catch(error=>{if(token===requestId)status(error.message+' · click Swap to retry');return false;});
 }
 function reset(){requestId++;apply(JSON.parse(JSON.stringify(layout)));}
 async function replace(id, templateId){
  const entry=entries.get(id), template=templates.get(templateId);
  if(!entry||!template||held)return false;
  const token=++requestId;
  try { await loadTemplate(templateId); } catch(error) { status(error.message); return false; }
  if(token!==requestId||held||!entries.has(id))return false;
  const next=entries.get(id),bottom=next.group.position.z-next.template.size[2]/2;
  let supportId=next.record.support;const seen=new Set();
  while(!spec.supports.some(s=>s.id===supportId)&&!seen.has(supportId)){seen.add(supportId);supportId=originalRecords.find(o=>o.instance_id===supportId)?.support_id;}
  const support=spec.supports.find(s=>s.id===supportId),position=next.group.position.toArray();
  position[2]=bottom+template.size[2]/2+.005;
  if(support){
   const radius=Math.hypot(template.size[0],template.size[1])/2+.015,candidates=[[position[0],position[1]]];
   for(let x=support.min[0]+radius;x<=support.max[0]-radius;x+=.06)for(let y=support.min[1]+radius;y<=support.max[1]-radius;y+=.06)candidates.push([x,y]);
   candidates.sort((a,b)=>Math.hypot(a[0]-position[0],a[1]-position[1])-Math.hypot(b[0]-position[0],b[1]-position[1]));
   const fit=candidates.find(([x,y])=>containsCircle(support,x,y,radius)&&
    !support.obstacles?.some(b=>Math.hypot(x-Math.max(b.min[0],Math.min(x,b.max[0])),y-Math.max(b.min[1],Math.min(y,b.max[1])))<radius)&&
    ![...entries.values()].some(e=>e.id!==id&&e.group.position.z+e.template.size[2]/2>support.max[2]&&Math.hypot(x-e.group.position.x,y-e.group.position.y)<radius+Math.hypot(e.template.size[0],e.template.size[1])/2+.01));
   if(!fit){status('No clear tabletop position for this asset');return false;}
   position[0]=fit[0];position[1]=fit[1];position[2]=support.max[2]+template.size[2]/2+.01;
  }
  world.removeBody(next.body);scene.remove(next.group);placements.delete(id);objectMeshes.delete(id);entries.delete(id);
  for(let i=pickables.length-1;i>=0;i--)if(pickables[i].userData.owner===id)pickables.splice(i,1);
  data.objects.splice(data.objects.findIndex(o=>o.instance_id===id),1);
  add({...next.record,support:support?.id||next.record.support,template:templateId,position,yaw:0});
  layout.placements=layout.placements.map(p=>p.id===id?{...p,support:support?.id||p.support,template:templateId,position,yaw:0}:p);
  onChange?.();status(template.label);return true;
 }
 function arrangeOffsets(offsets){
  if(held)return false;
  for(const e of entries.values()){
   const original=originalRecords.find(o=>o.instance_id===e.id);if(!original)continue;
   const delta=new THREE.Vector3(...(offsets[e.id]||[0,0,0]));
   let parent=original.support_id;const visited=new Set();
   while(parent&&!visited.has(parent)){visited.add(parent);delta.add(new THREE.Vector3(...(offsets[parent]||[0,0,0])));parent=originalRecords.find(o=>o.instance_id===parent)?.support_id;}
   const source=templates.get(e.id),position=source.source_center.map((v,i)=>v+delta.getComponent(i));
   position[2]+=(e.template.size[2]-source.size[2])/2;
   e.body.position.set(...position);e.body.position.vadd(e.com,e.body.position);e.body.quaternion.set(0,0,0,1);
   e.body.velocity.setZero();e.body.angularVelocity.setZero();e.body.wakeUp();e.body.aabbNeedsUpdate=true;syncVisual(e);
  }
  return true;
 }
 function begin(id){
  requestId++;
  const e=entries.get(id);if(!e||paused)return false;
  held={entry:e,position:e.body.position.clone(),quaternion:e.body.quaternion.clone(),target:e.body.position.clone()};
  const anchor=new CANNON.Body({mass:0,type:CANNON.Body.KINEMATIC,collisionFilterGroup:0,position:e.body.position.clone()});
  const constraint=new CANNON.PointToPointConstraint(e.body,new CANNON.Vec3(),anchor,new CANNON.Vec3(),e.body.mass*100);
  world.addBody(anchor);world.addConstraint(constraint);held.anchor=anchor;held.constraint=constraint;
  e.body.wakeUp();return true;
 }
 function move(id,position){if(held?.entry.id===id){held.target.set(...position);held.target.vadd(held.entry.body.quaternion.vmult(held.entry.com),held.target);}}
 function release(cancel=false){
  if(!held)return;const {entry:e,position,quaternion}=held;
  world.removeConstraint(held.constraint);world.removeBody(held.anchor);
  if(cancel){e.body.position.copy(position);e.body.quaternion.copy(quaternion);}
  // Throw-enabled scenes retain bounded grab velocity; other scenes drop at rest.
  if(spec.throw_on_release&&!cancel){e.body.velocity.copy(held.anchor.velocity);const speed=e.body.velocity.length();if(speed>4)e.body.velocity.scale(4/speed,e.body.velocity);}
  else e.body.velocity.setZero();
  e.body.angularVelocity.setZero();e.body.wakeUp();e.body.aabbNeedsUpdate=true;syncVisual(e);held=null;
 }
 function advance(count){
  for(let i=0;i<count;i++){
   if(held){const b=held.anchor;held.target.vsub(b.position,b.velocity);const speed=b.velocity.length();b.velocity.scale(speed>0?Math.min(4,speed*physicsHz)/speed:0,b.velocity);}
   world.step(stepTime);steps++;contactCount+=world.contacts.length;
  }
  for(const e of entries.values())syncVisual(e);
 }
 let accumulator=0;
 function tick(dt){if(paused)return;syncStatics();if(!held&&[...entries.values()].every(e=>e.body.sleepState===CANNON.Body.SLEEPING)){accumulator=0;return;}accumulator=Math.min(accumulator+Math.max(0,dt),maxSubsteps*stepTime);const n=Math.min(maxSubsteps,Math.floor(accumulator/stepTime));accumulator-=n*stepTime;advance(n);}
 function nudge(){for(const e of entries.values())e.body.applyImpulse(new CANNON.Vec3(e.body.mass*.6,e.body.mass*.1,e.body.mass*.18),new CANNON.Vec3(0,0,.1));}
 function focus(camera,controls){const s=spec.supports[0],cx=(s.min[0]+s.max[0])/2,cy=(s.min[1]+s.max[1])/2,z=s.max[2],length=Math.max(s.max[0]-s.min[0],s.max[1]-s.min[1]);controls.target.set(cx,cy,z+.12);camera.position.set(cx+length*.45,cy-length*.85,z+length*1.15);camera.fov=50;camera.updateProjectionMatrix();controls.update();}
 original();
 return {entries,spec,world,stepTime,regenerate,original,reset,replace,arrangeOffsets,begin,move,release,tick,nudge,focus,advance,rebuildStatics,
  has:id=>entries.has(id),get layout(){return JSON.parse(JSON.stringify(layout));},get paused(){return paused;},set paused(value){paused=value;accumulator=0;},
  get steps(){return steps;},get contacts(){return contactCount;},
  snapshot:()=>[...entries.values()].map(e=>({id:e.id,asset:e.template.asset_id,position:e.group.position.toArray(),quaternion:e.body.quaternion.toArray(),velocity:e.body.velocity.length(),sleep:e.body.sleepState}))};
}

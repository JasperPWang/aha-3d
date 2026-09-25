import * as THREE from 'three';
import {createMeshBody} from './mesh-physics.js';
import {completeFixtureLights} from './fixture-lights.js';
import {repairTabletopGeometry} from './basket-geometry.js';
import {readFile,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';

function points(record){
 const matrix=new THREE.Matrix4().fromArray(record.matrix),result=[];
 for(let i=0;i<record.positions.length;i+=3)result.push(new THREE.Vector3(...record.positions.slice(i,i+3)).applyMatrix4(matrix));
 return result;
}
function bounds(records){return new THREE.Box3().setFromPoints(records.flatMap(points));}

// Reuse an evaluated scene and registered template export without reopening or
// modifying the Blender source. Support meshes are explicit caller choices.
export function prepareTabletop(data,library,supportMeshes){
 repairTabletopGeometry(data,supportMeshes);
 // Legacy exports group small countertop vessels as furniture. Recognize only
 // complete, named jar assemblies on an explicitly selected support surface.
 const supportOwners=new Set(data.meshes.filter(m=>supportMeshes.includes(m.name)).map(m=>m.owner));
 for(const object of data.objects){
  if(object.semantic_class!=='furniture'||object.movable===false||!supportOwners.has(object.support_id))continue;
  const parts=data.meshes.filter(m=>m.owner===object.instance_id);
  if(!parts.length||parts.some(m=>m.joint)||!parts.every(m=>/\bjar\b/i.test(m.name)))continue;
  const size=bounds(parts).getSize(new THREE.Vector3());
  if(Math.min(size.x,size.y,size.z)>.02&&Math.max(size.x,size.y,size.z)<.5)object.semantic_class='props/jar';
 }
 // Preserve each existing fruit mesh and its world transform, but give it a
 // separate semantic owner so the solver and picking can address it directly.
 for(const basket of data.objects.filter(o=>o.semantic_class==='props/fruit-basket')){
  const groups=new Map();
  for(const mesh of data.meshes.filter(m=>m.owner===basket.instance_id&&/apple|orange|pear|lemon|lime|peach/i.test(m.name))){
   if(!groups.has(mesh.name))groups.set(mesh.name,[]);groups.get(mesh.name).push(mesh);
  }
  let index=0;
  for(const meshes of groups.values()){
   const id=basket.instance_id+':fruit:'+(++index);
   for(const mesh of meshes)mesh.owner=id;
   data.objects.push({instance_id:id,label:'Apple '+index,semantic_class:'props/fruit',asset_id:'source-scene/'+id,support_id:basket.instance_id,movable:true});
  }
 }
 const sources=new Set();const supports=[];
 for(const name of supportMeshes){
  const mesh=data.meshes.find(m=>m.name===name);if(!mesh)throw Error('Unknown support: '+name);
  const box=bounds([mesh]),sourceIds=new Set();
  for(const object of data.objects)if(object.support_id===mesh.owner&&object.semantic_class?.startsWith('props/'))sourceIds.add(object.instance_id);
  let changed=true;while(changed){changed=false;for(const o of data.objects)if(sourceIds.has(o.support_id)&&!sourceIds.has(o.instance_id)){sourceIds.add(o.instance_id);changed=true;}}
  for(const id of sourceIds)sources.add(id);
  const min=box.min.toArray(),max=box.max.toArray();min[2]=Math.max(min[2],max[2]-.08);
  supports.push({id:mesh.owner,mesh:name,min,max,footprint:[[min[0],min[1]],[max[0],min[1]],[max[0],max[1]],[min[0],max[1]]],source_ids:[...sourceIds]});
  data.objects.find(o=>o.instance_id===mesh.owner).movable=false;
 }
 const templates=[];
 for(const id of sources){
  const parts=data.meshes.filter(m=>m.owner===id);if(!parts.length||parts.some(m=>m.joint))throw Error('Incomplete source prop: '+id);
  const vertices=parts.flatMap(points),box=new THREE.Box3().setFromPoints(vertices),center=box.getCenter(new THREE.Vector3());
  const object=data.objects.find(o=>o.instance_id===id);
  const geometry=new THREE.BufferGeometry().setFromPoints(vertices),mesh=new THREE.Mesh(geometry);mesh.updateMatrixWorld();
  const proxy=createMeshBody(mesh,{preserveBase:object.semantic_class==='props/jar'});geometry.dispose();if(!proxy)throw Error('No solid prop hull: '+id);
  const shape=proxy.shapes[0],offset=new THREE.Vector3(...proxy.position.toArray()).sub(center),size=box.getSize(new THREE.Vector3()).toArray();
  const template={id,asset_id:'source-scene/'+id,label:object.label||id.replaceAll('_',' '),category:'accent',mass:.6,size,source_center:center.toArray(),center_of_mass:[0,0,-size[2]*.25],
   hull:{vertices:shape.vertices.map(v=>[v.x+offset.x,v.y+offset.y,v.z+offset.z]),faces:shape.faces},
   meshes:parts.map(part=>{const matrix=new THREE.Matrix4().fromArray(part.matrix);matrix.elements[12]-=center.x;matrix.elements[13]-=center.y;matrix.elements[14]-=center.z;return {...part,matrix:matrix.toArray()};})};
  if(object.semantic_class==='props/fruit'){
   template.mass=.16;template.category='fruit';template.center_of_mass=[0,0,0];template.collision={kind:'sphere',radius:Math.max(...size)/2};
  }
  if(object.semantic_class==='props/tray')template.collision={kind:'box',half:size.map(v=>v/2)};
  if(object.semantic_class==='props/fruit-basket'||object.semantic_class==='props/cup'){
   const collision=object.browser_collision;
   if(!collision)throw Error('Basket requires complete base and wall geometry');
   template.collision={...collision,tiers:collision.tiers.map(t=>({...t,x:t.x-center.x,y:t.y-center.y,z:t.z-center.z,bottom:t.bottom-center.z,...(t.wallBottom!==undefined?{wallBottom:t.wallBottom-center.z}:{})}))};
   if(collision.post)template.collision.post={...collision.post,x:collision.post.x-center.x,y:collision.post.y-center.y,bottom:collision.post.bottom-center.z,top:collision.post.top-center.z};
   if(collision.handle)template.collision.handle={...collision.handle,x:collision.handle.x-center.x,y:collision.handle.y-center.y,z:collision.handle.z-center.z};
   template.mass=collision.kind==='cup'?.18:.65;
   if(collision.kind==='cup')template.center_of_mass=[collision.tiers[0].x-center.x+.004,collision.tiers[0].y-center.y,-size[2]*.25];
  }
  templates.push(template);
 }
 const offset=data.materials.length;data.materials.push(...structuredClone(library.materials));
 for(const original of library.tabletop.templates.filter(t=>t.id.startsWith('browser-template-'))){
  const template=structuredClone(original);if(!template.meshes)throw Error('Library export must contain geometry');
  for(const mesh of template.meshes)for(const group of mesh.groups)group.material+=offset;
  templates.push(template);
 }
 for(const support of supports){support.obstacles=[];for(const mesh of data.meshes){
  if(mesh.name===support.mesh||sources.has(mesh.owner)||mesh.cutaway||mesh.joint)continue;
  const box=bounds([mesh]);if(box.min.z<support.max[2]+.4&&box.max.z>support.max[2]+.008&&[0,1].every(i=>box.max.getComponent(i)>support.min[i]&&box.min.getComponent(i)<support.max[i]))support.obstacles.push({name:mesh.name,min:box.min.toArray(),max:box.max.toArray()});
 }}
 data.tabletop={schema_version:1,seed:'featured-tabletop',scope:'tabletop',supports,templates,start_paused:true,throw_on_release:true};
 data.quick_actions.interactions=true;
 completeFixtureLights(data);
 // Structural roots may contain several separate downlights. Bind each emitter
 // explicitly so a click on one does not switch the entire ceiling.
 const expanded=[];
 for(const light of data.lighting.lights){
  const owner=data.objects.find(o=>o.instance_id===light.owner);
  if(light.lamp&&!light.owner&&!light.emitter_meshes?.length)continue;
  if(light.lamp&&owner?.semantic_class?.startsWith('structure/')&&light.emitter_meshes.length>1){
   for(const [index,name] of light.emitter_meshes.entries()){
    const mesh=data.meshes.find(m=>m.name===name),center=bounds([mesh]).getCenter(new THREE.Vector3());
    expanded.push({...light,id:light.id+'-'+index,label:'Downlight '+(index+1),name:'Downlight '+(index+1),position:center.toArray(),energy:light.energy/light.emitter_meshes.length,emitter_meshes:[name]});
   }
  }else expanded.push(light);
 }
 data.lighting.lights=expanded;data.lighting.max_lights=Math.max(12,expanded.filter(l=>l.lamp).length+2);
 return data;
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
 const [source,library,output,...supports]=process.argv.slice(2);
 if(!supports.length)throw Error('Usage: prepare-tabletop.mjs scene.json library-scene.json output.json support-mesh ...');
 const data=prepareTabletop(JSON.parse(await readFile(source,'utf8')),JSON.parse(await readFile(library,'utf8')),supports);
 await writeFile(output,JSON.stringify(data),{flag:'wx'});
 console.log(JSON.stringify({props:data.tabletop.supports.flatMap(s=>s.source_ids),library:data.tabletop.templates.filter(t=>t.id.startsWith('browser-template-')).map(t=>t.asset_id),lights:data.lighting.lights.length}));
}

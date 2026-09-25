import * as THREE from 'three';

function bounds(parts){
 const box=new THREE.Box3();
 for(const p of parts){const m=new THREE.Matrix4().fromArray(p.matrix);for(let i=0;i<p.positions.length;i+=3)box.expandByPoint(new THREE.Vector3(...p.positions.slice(i,i+3)).applyMatrix4(m));}
 return box;
}
function translate(parts,delta){for(const p of parts)for(let i=0;i<3;i++)p.matrix[12+i]+=delta[i];}

/** Complete legacy ring-only baskets before exporting their physical templates.
 * Basket geometry and collision use the same tier dimensions; inputs stay on disk.
 */
export function repairTabletopGeometry(data,supportMeshes){
 const owned=id=>data.meshes.filter(m=>m.owner===id);
 for(const basket of data.objects.filter(o=>o.semantic_class==='props/fruit-basket')){
  if(basket.browser_collision)continue;
  const parts=owned(basket.instance_id),rings=parts.filter(m=>/basket rim/i.test(m.name));
  if(!rings.length)continue;
  const box=bounds(rings),center=box.getCenter(new THREE.Vector3()),material=rings[0].groups[0].material;
  const support=data.meshes.find(m=>supportMeshes.includes(m.name)&&m.owner===basket.support_id);
  if(!support)throw Error('Basket requires a measured tabletop');
  const surface=bounds([support]);
  const tiers=[];
  for(const ring of rings){const b=bounds([ring]),c=b.getCenter(new THREE.Vector3());if(!tiers.some(t=>Math.abs(t.z-c.z)<.01))tiers.push({z:c.z,radius:Math.min(b.max.x-b.min.x,b.max.y-b.min.y)/2-.004});}
  tiers.sort((a,b)=>a.z-b.z);
  const height=.05,thickness=.008,base=surface.max.z+.002;
  const dz=base+height-tiers[0].z;
  for(const tier of tiers){tier.bottom=tier.z+dz-height;tier.z+=dz;tier.height=height;tier.thickness=thickness;}
  // Separate the basket footprint from sibling trays without changing the table.
  let cy=center.y;
  for(const tray of data.objects.filter(o=>o.support_id===basket.support_id&&o.semantic_class==='props/tray')){
   const b=bounds(owned(tray.instance_id)),r=tiers[0].radius+.008;
   if(center.x+r>b.min.x&&center.x-r<b.max.x&&cy+r>b.min.y&&cy-r<b.max.y)cy=b.min.y-r-.04;
  }
  if(cy-tiers[0].radius<surface.min.y)throw Error('No clear basket placement on support');
  const cx=center.x,added=[];
  function add(name,g,position,quaternion=new THREE.Quaternion()){
   const matrix=new THREE.Matrix4().compose(new THREE.Vector3(...position),quaternion,new THREE.Vector3(1,1,1));
   added.push({name,owner:basket.instance_id,positions:Array.from(g.attributes.position.array),normals:Array.from(g.attributes.normal.array),matrix:matrix.toArray(),groups:[{material,indices:g.index?Array.from(g.index.array):Array.from({length:g.attributes.position.count},(_,i)=>i)}]});g.dispose();
  }
  const upright=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),Math.PI/2);
  for(const [i,t] of tiers.entries()){
   add(`Basket tier ${i+1} solid base`,new THREE.CylinderGeometry(t.radius,t.radius,thickness,48),[cx,cy,t.bottom+thickness/2],upright);
   for(const z of [t.bottom+thickness,t.z])add(`Basket tier ${i+1} rim`,new THREE.TorusGeometry(t.radius,.004,8,64),[cx,cy,z]);
   for(let j=0;j<40;j++){const angle=j*Math.PI*2/40;add(`Basket tier ${i+1} upright ${j+1}`,new THREE.CylinderGeometry(.0025,.0025,height-thickness,6),[cx+t.radius*Math.cos(angle),cy+t.radius*Math.sin(angle),t.bottom+(height+thickness)/2],upright);}
  }
  const top=tiers.at(-1).z+.025,post={radius:.007,bottom:base,top};
  add('Basket central support',new THREE.CylinderGeometry(post.radius,post.radius,top-base,12),[cx,cy,(base+top)/2],upright);
  add('Basket carry handle',new THREE.TorusGeometry(.025,.004,8,32),[cx,cy,top+.022],upright);
  // Preserve every fruit as a separate mesh, with nonintersecting packing per tier.
  const fruits=parts.filter(m=>/apple|orange|pear|lemon|lime|peach/i.test(m.name)),groups=new Map();
  for(const fruit of fruits){if(!groups.has(fruit.name))groups.set(fruit.name,[]);groups.get(fruit.name).push(fruit);}
  const byTier=tiers.map(()=>[]);
  for(const meshes of groups.values()){const b=bounds(meshes),c=b.getCenter(new THREE.Vector3());let index=0;for(let i=1;i<tiers.length;i++)if(Math.abs(c.z-(tiers[i].z-dz))<Math.abs(c.z-(tiers[index].z-dz)))index=i;byTier[index].push({meshes,box:b,center:c});}
  for(const [i,items] of byTier.entries()){
   const tier=tiers[i],orbit=tier.radius*.60,maxRadius=Math.min(tier.radius-orbit-.012,orbit*Math.sin(Math.PI/items.length)-.004);
   for(const [j,item] of items.entries()){
    const size=item.box.getSize(new THREE.Vector3()),scale=Math.min(1,maxRadius/(Math.max(size.x,size.y,size.z)/2)),angle=j*Math.PI*2/items.length;
    const next=new THREE.Vector3(cx+orbit*Math.cos(angle),cy+orbit*Math.sin(angle),tier.bottom+thickness+size.z*scale/2+.002);
    const transform=new THREE.Matrix4().makeTranslation(...next).multiply(new THREE.Matrix4().makeScale(scale,scale,scale)).multiply(new THREE.Matrix4().makeTranslation(...item.center.clone().negate()));
    for(const mesh of item.meshes)mesh.matrix=transform.clone().multiply(new THREE.Matrix4().fromArray(mesh.matrix)).toArray();
   }
  }
  data.meshes=data.meshes.filter(m=>!rings.includes(m));data.meshes.push(...added);
  basket.browser_collision={kind:'basket',tiers:tiers.map(t=>({...t,x:cx,y:cy})),post:{...post,x:cx,y:cy}};
 }
 // Rest vessels on the actual tray top, not on its mid-plane.
 for(const tray of data.objects.filter(o=>o.semantic_class==='props/tray')){
  const top=bounds(owned(tray.instance_id)).max.z;
  for(const child of data.objects.filter(o=>o.support_id===tray.instance_id)){
   const parts=owned(child.instance_id),b=bounds(parts);
   if(child.semantic_class!=='props/bowl'){translate(parts,[0,0,top+.002-b.min.z]);continue;}
   const c=b.getCenter(new THREE.Vector3()),z=top+.002,material=parts[0].groups[0].material;
   // Closed ceramic cross-section: flat foot, inner floor, tapered walls and open mouth.
   const profile=[[0,0],[.032,0],[.038,.003],[.04,.008],[.047,.073],[.048,.077],[.047,.08],[.044,.08],[.043,.077],[.036,.013],[.033,.01],[0,.01]];
   const cup=new THREE.LatheGeometry(profile.map(p=>new THREE.Vector2(...p)),64);cup.rotateX(Math.PI/2);
   const handle=new THREE.TorusGeometry(.023,.0055,12,24,Math.PI);handle.rotateZ(-Math.PI/2);handle.rotateX(Math.PI/2);handle.translate(.044,0,.044);
   function record(name,g){const mesh={name,owner:child.instance_id,positions:Array.from(g.attributes.position.array),normals:Array.from(g.attributes.normal.array),matrix:new THREE.Matrix4().makeTranslation(c.x,c.y,z).toArray(),groups:[{material,indices:Array.from(g.index.array)}]};g.dispose();return mesh;}
   data.meshes=data.meshes.filter(m=>!parts.includes(m));data.meshes.push(record('Tea cup ceramic shell '+child.instance_id,cup),record('Tea cup handle '+child.instance_id,handle));
   child.label='Tea cup '+child.instance_id.replace(/.*_/,'');child.semantic_class='props/cup';
   child.browser_collision={kind:'cup',tiers:[{x:c.x,y:c.y,z:z+.08,bottom:z,wallBottom:z+.008,radius:.044,baseRadius:.032,height:.072,thickness:.008}],handle:{x:c.x+.044,y:c.y,z:z+.044,radius:.023,tube:.0055,start:-Math.PI/2,end:Math.PI/2}};
  }
 }
 return data;
}

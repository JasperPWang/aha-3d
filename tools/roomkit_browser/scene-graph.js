import * as THREE from 'three';
import {containsCircle} from './support-geometry.js';

// Semantic ownership is deliberately separate from Three.js parenting and from
// transient physical contact. Geometry bounds give actual world layout even when
// a legacy Blender root is at (0,0,0) and all placement is baked into its meshes.
export function createSceneGraph({data,scene,pickables,bounds,tabletop,chairs,joints,onSelect}) {
 const $=id=>document.getElementById(id), rows=new Map(), expanded=new Set();
 let selected=null, signature='', lastUpdate=-Infinity, current=null;
 const rounded=v=>Number(v.toFixed(4)), vector=v=>v.toArray().map(rounded);
 const label=o=>o.label||o.instance_id.replaceAll('_',' ');
 const geometry=pickables.filter(m=>!m.userData.owner);
 const geometryBounds=new THREE.Box3();for(const mesh of geometry)geometryBounds.union(new THREE.Box3().setFromObject(mesh));
 const boxRecord=box=>box.isEmpty()?null:{center_m:vector(box.getCenter(new THREE.Vector3())),size_m:vector(box.getSize(new THREE.Vector3())),min_m:vector(box.min),max_m:vector(box.max)};
 function objectNode(o){
  const box=bounds(o.instance_id),entry=tabletop?.entries.get(o.instance_id),support=tabletop?.spec.supports.find(s=>s.id===o.support_id);
  const node={id:o.instance_id,label:label(o),kind:'object',category:o.semantic_class||'unclassified',parent_id:o.support_id||'scene',asset_id:o.asset_id||null,layout:boxRecord(box),movable:o.movable!==false};
  const seating=chairs?.inspect(o.instance_id);if(seating){node.seating=seating;node.parent_id=seating.group_id;}
  const seatingGroup=chairs?.spec.slots.find(s=>s.table_id===o.instance_id);if(seatingGroup)node.parent_id=seatingGroup.group_id;
  if(support){
   const gap=box.min.z-support.max[2],inside=[box.min.x,box.max.x].every(x=>[box.min.y,box.max.y].every(y=>containsCircle(support,x,y,-.01)));
   node.support={assigned_id:support.id,height_above_table_m:rounded(gap),inside_table_footprint:inside,
    spatial_state:!inside?'outside table footprint':gap>.04?'above tabletop':gap<-.04?'below tabletop':'at tabletop height',
    interpretation:'Spatial bounds relative to assigned support; not a contact or visibility certificate'};
  }else if(o.support_id)node.support={assigned_id:o.support_id};
  const slab=tabletop?.spec.supports.find(s=>s.id===o.instance_id);if(slab)node.tabletop_height_m=rounded(slab.max[2]);
  if(entry)node.physics={type:'dynamic',paused:tabletop.paused,sleeping:entry.body.sleepState===2,mass_kg:entry.body.mass,
   quaternion_xyzw:entry.body.quaternion.toArray().map(rounded),velocity_m_s:entry.body.velocity.toArray().map(rounded)};
  return node;
 }
 function snapshot(){
  scene.updateMatrixWorld(true);
  const objects=data.objects.map(objectNode),nodes=[{id:'scene',label:data.title||'Scene',kind:'scene',parent_id:null},
   {id:'room-geometry',label:'Room geometry',kind:'static_geometry',parent_id:'scene',mesh_count:geometry.length,visible_mesh_count:geometry.filter(m=>m.visible).length,layout:boxRecord(geometryBounds),members:geometry.map(m=>m.name)},...objects];
  if(chairs){nodes.push({id:chairs.spec.floor_support.id,label:'Floor support',kind:'support',parent_id:'room-geometry',height_m:chairs.spec.floor_support.height_m});for(const [id,slot] of new Map(chairs.spec.slots.map(s=>[s.group_id,s])))nodes.push({id,label:slot.table_id?'Seating · '+label(data.objects.find(o=>o.instance_id===slot.table_id)):'Seating',kind:'group',parent_id:'scene'});}
  for(const joint of joints.values())nodes.push({id:'joint:'+joint.id,label:joint.label,kind:'joint',parent_id:joint.owner,joint_type:joint.type,opening:rounded(joint.value)});
  return {schema_version:1,source:data.source,source_sha256:data.source_sha256,coordinate_system:{up:'Z',units:'scene metres',position:'World geometry bounds center',dimensions:'World axis-aligned bounds; not calibrated measurements'},
   seed:tabletop?.layout.seed??null,swap_scope:tabletop?'tabletop':null,initial_seed_layout:tabletop?.layout??null,
   chair_layout:chairs?.layout??null,chair_swap_report:chairs?.lastReport??null,
   animation_frame:data.animation?Number($('timeline').value)+data.animation.start_frame:null,nodes,
   edges:[...nodes.filter(n=>n.parent_id).map(n=>({from:n.parent_id,to:n.id,relation:n.kind==='joint'?'has_joint':objects.find(o=>o.id===n.id)?.support?'assigned_support':'contains'})),
    ...(chairs?.spec.slots.flatMap(s=>[{from:chairs.spec.floor_support.id,to:s.id,relation:'supports'},...(s.table_id?[{from:s.id,to:s.table_id,relation:'faces'}]:[])])||[])]};
 }
 function rebuild(nodes){
  rows.clear();$('scene-tree').replaceChildren();
  const byParent=new Map();for(const n of nodes){if(n.id==='scene')continue;const key=n.parent_id||'scene';if(!byParent.has(key))byParent.set(key,[]);byParent.get(key).push(n);}
  const supports=new Set(tabletop?.spec.supports.map(s=>s.id)||[]);
  const priority=n=>n.kind==='static_geometry'?-3:n.kind==='group'?-2:supports.has(n.id)?-1:0;
  for(const siblings of byParent.values())siblings.sort((a,b)=>priority(a)-priority(b)||a.label.localeCompare(b.label));
  const append=(parent,list)=>{
   for(const node of byParent.get(parent)||[]){
    const li=document.createElement('li'),row=document.createElement('div');row.className='graph-row';li.append(row);
    const children=byParent.get(node.id)||[],toggle=document.createElement('button');toggle.className='graph-toggle';toggle.type='button';
    if(children.length){toggle.textContent=expanded.has(node.id)?'▾':'▸';toggle.setAttribute('aria-label','Expand '+node.label);toggle.setAttribute('aria-expanded',String(expanded.has(node.id)));}
    else{toggle.textContent='·';toggle.disabled=true;toggle.setAttribute('aria-hidden','true');}
    row.append(toggle);
    const button=document.createElement('button');button.type='button';button.className='graph-node';button.dataset.nodeId=node.id;
    const name=document.createElement('span');name.textContent=node.label;const meta=document.createElement('small');button.append(name,meta);row.append(button);
    button.onclick=()=>{if(node.kind==='object')onSelect(node.id);else {onSelect(node.kind==='joint'?node.parent_id:null);setSelection(node.id);}};
    rows.set(node.id,{button,meta});
    if(children.length){const nested=document.createElement('ul');nested.hidden=!expanded.has(node.id);toggle.onclick=()=>{const open=nested.hidden;nested.hidden=!open;toggle.textContent=open?'▾':'▸';toggle.setAttribute('aria-expanded',String(open));if(open)expanded.add(node.id);else expanded.delete(node.id);};append(node.id,nested);li.append(nested);}
    list.append(li);
   }
  };
  append('scene',$('scene-tree'));
 }
 function refresh(force=false){
  current=snapshot();
  const next=current.nodes.map(n=>n.id+'>'+n.parent_id+'>'+n.asset_id+'>'+n.label).join('|');
  if(next!==signature){signature=next;for(const s of tabletop?.spec.supports||[])expanded.add(s.id);for(const s of chairs?.spec.slots||[])expanded.add(s.group_id);rebuild(current.nodes);}
  for(const node of current.nodes){const row=rows.get(node.id);if(!row)continue;
   row.button.setAttribute('aria-pressed',String(node.id===selected));
   const value=node.kind==='joint'?`${node.joint_type} · ${Math.round(node.opening*100)}% open`:node.kind==='static_geometry'?`${node.mesh_count} static mesh parts`:node.layout?`XYZ ${node.layout.center_m.map(n=>n.toFixed(2)).join(', ')} m`:(node.category||'');
   if(row.meta.textContent!==value)row.meta.textContent=value;
  }
  $('graph-summary').textContent=`${data.objects.length} objects · ${joints.size} joints`+(tabletop?` · table seed ${current.seed}`:'')+(chairs?` · chair seed ${current.chair_layout.seed}`:'');
  const node=current.nodes.find(n=>n.id===selected);
  $('layout-title').textContent=node?node.label:'Current scene layout';
  const text=node?JSON.stringify(node,null,2):JSON.stringify({seeds:{tabletop:current.seed,chairs:current.chair_layout?.seed??null},objects:current.nodes.filter(n=>n.kind==='object').map(n=>({id:n.id,parent:n.parent_id,center_m:n.layout?.center_m,size_m:n.layout?.size_m}))},null,2);
  if($('layout-text').textContent!==text)$('layout-text').textContent=text;
  return current;
 }
 function setSelection(id){selected=id;const node=data.objects.find(o=>o.instance_id===id);if(node?.support_id&&!expanded.has(node.support_id)){expanded.add(node.support_id);signature='';}refresh(true);}
 $('download-layout').onclick=()=>{const blob=new Blob([JSON.stringify(snapshot(),null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='roomkit-layout.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 $('graph-swap').hidden=!tabletop;$('graph-swap').onclick=()=>$('swap-all').click();
 for(const [tab,panel,other,otherPanel] of [['graph-tab','graph-panel','controls-tab','controls-panel'],['controls-tab','controls-panel','graph-tab','graph-panel']]){
  $(tab).onclick=()=>{$(panel).hidden=false;$(otherPanel).hidden=true;$(tab).setAttribute('aria-selected','true');$(other).setAttribute('aria-selected','false');refresh(true);};
 }
 refresh(true);
 return {snapshot,refresh,setSelection,get selected(){return selected;},tick(now){if(now-lastUpdate>=200&&!$('graph-panel').hidden){lastUpdate=now;refresh();}}};
}

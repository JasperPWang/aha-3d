import {createInteraction} from './interaction.js';
import {createSurfaceMaterial} from './material-surface.js';
import * as THREE from 'three';
import {createAnimationStream} from './streaming.js';
import {createSceneGraph} from './scene-graph.js';
import {createTabletop} from './tabletop.js';
import {createLighting} from './lighting.js';
import {createMaterials} from './materials.js';
import {createSelectionBox} from './selection-box.js';
import {createChairs} from './chairs.js';
import {lockStructure} from './movement-policy.js';
import {obstacleBounds} from './collision-proxies.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {createRenderer} from './renderer.js';

try {
const data=window.ROOMKIT_SCENE, $=id=>document.getElementById(id);
lockStructure(data);
const stage=$('stage');
const {renderer,canvas,profile:rendererProfile}=createRenderer(THREE.WebGLRenderer,document.querySelector('canvas'),{
 report:diagnostic=>{window.roomkitRendererDiagnostic=diagnostic;},
});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.setClearColor(0xdbe2e7); renderer.toneMapping=THREE.ACESFilmicToneMapping;
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(42,1,.02,120);camera.up.set(0,0,1);
const controls=new OrbitControls(camera,canvas);controls.enableDamping=true;controls.maxPolarAngle=Math.PI*.49;controls.minDistance=2;controls.maxDistance=30;
const materials=data.materials.map(m=>createSurfaceMaterial({color:new THREE.Color(...m.color),roughness:m.roughness,metalness:m.metalness,emissive:new THREE.Color(...(m.emissive||[0,0,0])),emissiveIntensity:m.emissive_intensity||0,side:THREE.DoubleSide},m.physical));
for(const [i,m] of materials.entries())m.name=data.materials[i].name||'Unnamed material';
const joints=new Map(), pickables=[], objectMeshes=new Map(), placements=new Map();
for(const o of data.objects){const group=new THREE.Group();group.name=o.instance_id;placements.set(o.instance_id,group);}
for(const o of data.objects){
 const seen=new Set([o.instance_id]);let parent=o.support_id;
 while(parent){if(seen.has(parent))throw Error('Cyclic support relationship');seen.add(parent);const record=data.objects.find(x=>x.instance_id===parent);if(!record)throw Error('Unknown support: '+parent);parent=record.support_id;}
 (o.support_id?placements.get(o.support_id):scene).add(placements.get(o.instance_id));
}
const makePose=p=>({p:new THREE.Vector3(...p.position),q:new THREE.Quaternion(...p.quaternion),s:new THREE.Vector3(...p.scale)});
for(const j of data.joints){const group=new THREE.Group();placements.get(j.owner).add(group);joints.set(j.id,{...j,group,a:makePose(j.closed),b:makePose(j.open),value:0,target:0});}
for(const m of data.meshes){
 const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(m.positions,3));if(m.normals)g.setAttribute('normal',new THREE.Float32BufferAttribute(m.normals,3));
 const indices=[];for(const group of m.groups){g.addGroup(indices.length,group.indices.length,group.material);for(const i of group.indices)indices.push(i);}g.setIndex(indices);if(m.material_uv)g.setAttribute('uv',new THREE.Float32BufferAttribute(m.material_uv,2));if(!m.normals)g.computeVertexNormals();g.computeBoundingSphere();
 const mesh=new THREE.Mesh(g,materials);mesh.name=m.name;mesh.matrixAutoUpdate=false;mesh.matrix.fromArray(m.matrix);mesh.userData={owner:m.owner,joint:m.joint,cutaway:m.cutaway,surface:m.surface};
 (m.joint?joints.get(m.joint).group:m.owner?placements.get(m.owner):scene).add(mesh);pickables.push(mesh);
 if(m.owner){if(!objectMeshes.has(m.owner))objectMeshes.set(m.owner,[]);objectMeshes.get(m.owner).push(mesh);}
}
const lighting=createLighting({renderer,scene,data,placements,joints,pickables,materials});
if(rendererProfile!=='standard'){lighting.setQuality('fast');$('lighting-quality').value='fast';}
let tabletop=null, sceneGraph=null, chairs=null, materialLab=null;
let selected=null, highlight=null, mode='orbit', moveMode=true, drag=null;
const settling=new Map();
let playbackTime=0, playing=false, shownFrame=-1;
const actors=(data.animation?.actors||[]).map(a=>({...a,mesh:pickables.find(m=>m.name===a.mesh_name),frames:a.positions_buffer?new Float32Array(a.positions_buffer):a.positions_base64?new Float32Array(Uint8Array.from(atob(a.positions_base64),c=>c.charCodeAt(0)).buffer):null}));
const interaction=createInteraction({data,placements,objectMeshes,scene,lighting});
const stream=data.animation?.actors.some(a=>a.segments)?createAnimationStream(data.animation):null;
let requestedFrame=0, loadingFrame=null, streamError=false;
function applyFrame(frame,values){
 interaction?.apply(frame);
 for(const [i,a] of actors.entries()){
  // Source tracks may enter late or leave before the video ends. Padded vertex
  // buffers retain finite geometry; visibility follows original source timing.
  if(a.active_frame_range)a.mesh.visible=frame>=a.active_frame_range[0]&&frame<a.active_frame_range[1];
  const attr=a.mesh.geometry.attributes.position;attr.array.set(values[i]);attr.needsUpdate=true;a.mesh.geometry.computeVertexNormals();a.mesh.geometry.computeBoundingSphere();a.mesh.geometry.computeBoundingBox();
 }
 shownFrame=frame;
 $('timeline').value=frame;$('time').textContent=`${(frame/data.animation.fps).toFixed(2)} / ${data.animation.duration_seconds.toFixed(2)} s · ${frame+1}/${data.animation.frames}`;
}
function poseFrame(frame){
 if(!data.animation)return true;frame=THREE.MathUtils.clamp(Math.round(frame),0,data.animation.frames-1);requestedFrame=frame;
 if(frame===shownFrame)return true;
 if(stream){
  const cached=stream.peek(frame);if(cached){applyFrame(frame,cached);if(playing)stream.prefetch(frame);return true;}
  if(frame===0){applyFrame(0,actors.map(a=>data.meshes.find(m=>m.name===a.mesh_name).positions));return true;}
  if(loadingFrame!==frame&&!streamError){loadingFrame=frame;$('time').textContent='Loading animation…';
   stream.frame(frame).then(values=>{if(requestedFrame===frame){applyFrame(frame,values);if(playing)stream.prefetch(frame);}}).catch(error=>{if(requestedFrame===frame){streamError=true;playing=false;$('play').textContent='Retry';$('time').textContent=error.message+' · press Retry';}}).finally(()=>{if(loadingFrame===frame)loadingFrame=null;});}
  return false;
 }
 applyFrame(frame,actors.map(a=>a.frames.subarray(frame*a.vertex_count*3,(frame+1)*a.vertex_count*3)));return true;
}
if(data.capability_note){$('capability-note').hidden=false;$('capability-note').textContent=data.capability_note;}
if(data.title){document.querySelector('h1').textContent=data.title;document.title=data.title;}
if(data.description)document.querySelector('footer').textContent=data.description;
if(data.animation){
 $('playback').hidden=false;$('timeline').max=data.animation.frames-1;
 $('motion-note').textContent=data.animation.description;
 $('play').onclick=()=>{streamError=false;const range=interaction?.range||[0,data.animation.frames];if(playbackTime>=range[1]/data.animation.fps||playbackTime<range[0]/data.animation.fps)playbackTime=range[0]/data.animation.fps;playing=!playing;$('play').textContent=playing?'Pause':'Play';};
 $('restart').onclick=()=>{streamError=false;playing=false;playbackTime=(interaction?.range[0]||0)/data.animation.fps;poseFrame(Math.round(playbackTime*data.animation.fps));$('play').textContent='Play';};
 $('timeline').oninput=()=>{streamError=false;playing=false;playbackTime=Number($('timeline').value)/data.animation.fps;poseFrame(Number($('timeline').value));$('play').textContent='Play';};
 poseFrame(0);
 document.querySelector('h1').textContent=data.title;document.title=data.title;
 document.querySelector('footer').textContent=data.description;
}
const cutaways=pickables.filter(m=>m.userData.cutaway);
if(cutaways.length){$('cutaway').hidden=false;$('cutaway').onclick=()=>{const hide=$('cutaway').getAttribute('aria-pressed')!=='true';$('cutaway').setAttribute('aria-pressed',String(hide));for(const mesh of cutaways)mesh.visible=!hide;};$('cutaway').click();}
const status=text=>{$('status').textContent=text;};
const readable=id=>id.replaceAll('_',' ').replaceAll('-',' ');
for(const o of data.objects){const option=document.createElement('option');option.value=o.instance_id;option.textContent=readable(o.instance_id);$('objects').append(option);}
function select(id){
 selected=id;materialLab?.refresh();sceneGraph?.setSelection(id);$('objects').value=id||'';$('details').replaceChildren();$('joints').replaceChildren();
 const o=data.objects.find(x=>x.instance_id===id);if(!o)return;
 const dl=document.createElement('dl');for(const [label,value] of [['Object',o.instance_id],['Category',o.semantic_class],['Asset',o.asset_id],['Supported by',o.support_id]]){if(value){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;dl.append(dt,dd);}}$('details').append(dl);
 const owned=[...joints.values()].filter(j=>j.owner===id);
 if(owned.length){const h=document.createElement('h3');h.textContent='Doors & drawers';$('joints').append(h);}
 for(const j of owned){const row=document.createElement('div');row.className='joint';const button=document.createElement('button');button.dataset.joint=j.id;button.textContent=`${j.type==='hinge'?'Door':'Drawer'} · ${j.label}`;button.setAttribute('aria-pressed',j.target>0?'true':'false');button.onclick=()=>toggle(j);
 const input=document.createElement('input');input.type='range';input.min=0;input.max=100;input.value=Math.round(j.value*100);input.setAttribute('aria-label',`${j.label} opening percentage`);input.oninput=()=>{j.target=j.value=Number(input.value)/100;updatePose(j);button.setAttribute('aria-pressed',j.target>0?'true':'false');};row.append(button,input);$('joints').append(row);j.input=input;j.button=button;}
 if(!owned.length){const p=document.createElement('p');p.className='muted';p.textContent=tabletop?.has(id)?'Hold to lift · release to drop under gravity':o.movable===false?'Fixed object · source placement retained':'Hold to lift · drag to move · release to place';$('joints').append(p);}
 const position=document.createElement('p');position.id='position';position.className='muted';$('details').append(position);showPosition();
}
function showPosition(){const el=$('position');if(el&&selected){const p=bounds(selected).getCenter(new THREE.Vector3());el.textContent=`World center: X ${p.x.toFixed(2)} · Y ${p.y.toFixed(2)} · Z ${p.z.toFixed(2)} m`;}}
function bounds(id){const box=new THREE.Box3();for(const mesh of objectMeshes.get(id)||[])box.union(new THREE.Box3().setFromObject(mesh));return box;}
function moveObject(id, next){
 const group=placements.get(id),record=data.objects.find(o=>o.instance_id===id);
 scene.updateMatrixWorld(true);
 if(record.support_id&&(!tabletop||tabletop.paused)){
  const support=bounds(record.support_id),object=bounds(id),delta=next.clone().sub(group.position);
  // A conservative world-axis footprint bound, not a contact or collision solver.
  for(const axis of ['x','y']){const lo=support.min[axis]-object.min[axis],hi=support.max[axis]-object.max[axis];delta[axis]=lo<=hi?THREE.MathUtils.clamp(delta[axis],lo,hi):0;}
  next=group.position.clone().add(delta);
 }
 next.z=group.position.z;group.position.copy(next);scene.updateMatrixWorld(true);showPosition();
}
// Swept axis-aligned boxes prevent tunnelling even for large pointer jumps.
// Test at the resting height: the visual lift must not let furniture jump walls.
function constrain(box, delta, obstacles){
 const result=delta.clone();result.z=0;
 for(const axis of ['x','y']){
  const other=axis==='x'?'y':'x';let d=result[axis];
  for(const obstacle of obstacles){
   if(box.max.z<=obstacle.min.z+.015||box.min.z>=obstacle.max.z-.015||box.max[other]<=obstacle.min[other]+.002||box.min[other]>=obstacle.max[other]-.002)continue;
   // Existing source overlaps may escape, but must not deepen along this axis.
   if(box.max[axis]>obstacle.min[axis]+.002&&box.min[axis]<obstacle.max[axis]-.002){const left=box.max[axis]-obstacle.min[axis],right=obstacle.max[axis]-box.min[axis];if((left<right&&d>0)||(right<left&&d<0))d=0;}
   if(d>0&&box.max[axis]<=obstacle.min[axis]+.002)d=Math.min(d,Math.max(0,obstacle.min[axis]-box.max[axis]-.002));
   if(d<0&&box.min[axis]>=obstacle.max[axis]-.002)d=Math.max(d,Math.min(0,obstacle.max[axis]-box.min[axis]+.002));
  }
  result[axis]=d;box.min[axis]+=d;box.max[axis]+=d;
 }
 return result;
}
function walkableCover(mesh, box, restingBox){
 const record=data.objects.find(o=>o.instance_id===mesh.userData.owner);
 const label=[mesh.name,record?.semantic_class,mesh.userData.surface].filter(Boolean).join(' ').replaceAll('_',' ');
 const identified=/\b(rug|carpet|floor finish|floor covering)\b/i.test(label);
 // Only thin covers at the dragged object's support height are passable.
 // A hanging carpet or a tall object with "rug" in its name stays solid.
 return identified&&box.max.z-box.min.z<=.08&&Math.abs(box.max.z-restingBox.min.z)<=.08;
}
function dragObstacles(id, restingBox){
 const family=new Set([id]);let changed=true;
 while(changed){changed=false;for(const o of data.objects)if(family.has(o.support_id)&&!family.has(o.instance_id)){family.add(o.instance_id);changed=true;}}
 const support=data.objects.find(o=>o.instance_id===id)?.support_id;
 return pickables.filter(m=>m.visible&&!family.has(m.userData.owner)&&(!support||m.userData.owner!==support)&&!actors.some(a=>a.mesh===m)).flatMap(m=>obstacleBounds(m).map(box=>({mesh:m,box}))).filter(({mesh,box})=>!walkableCover(mesh,box,restingBox)).map(({box})=>box);
}
function finishDrag(cancel=false){
 if(!drag)return;const d=drag;drag=null;
 if(d.physical){tabletop.release(cancel);}
 else if(cancel){placements.get(d.id).position.copy(d.origin);settling.delete(d.id);}
 else settling.set(d.id,d.origin.z);
 down=null;controls.enabled=true;canvas.style.cursor='grab';
 if(canvas.hasPointerCapture(d.pointerId))canvas.releasePointerCapture(d.pointerId);
 scene.updateMatrixWorld(true);showPosition();
}
$('move').setAttribute('aria-pressed','true');
$('move').onclick=()=>{finishDrag();moveMode=!moveMode;$('move').setAttribute('aria-pressed',String(moveMode));$('hint').textContent=moveMode?'Hold to lift · drag to move · release to place · bounding-box limits · Esc cancels':'Drag to orbit · scroll to zoom · click doors to open';};
$('hint').textContent='Hold to lift · drag to move · release to place · bounding-box limits · Esc cancels';
$('reset-layout').onclick=()=>{finishDrag();settling.clear();for(const [id,group] of placements)if(!tabletop?.has(id))group.position.set(0,0,0);chairs?.original();tabletop?.reset();scene.updateMatrixWorld(true);showPosition();status('Layout reset');};
document.addEventListener('keydown',e=>{if(e.key==='Escape')finishDrag(true);});
window.addEventListener('blur',()=>finishDrag(true));
function toggle(j){j.target=j.target>.5?0:1;status(`${j.target?'Opening':'Closing'} ${readable(j.owner)} · ${j.label}`);if(j.button)j.button.setAttribute('aria-pressed',j.target>0?'true':'false');}
function updatePose(j){j.group.position.lerpVectors(j.a.p,j.b.p,j.value);j.group.quaternion.slerpQuaternions(j.a.q,j.b.q,j.value);j.group.scale.lerpVectors(j.a.s,j.b.s,j.value);}
function setView(next){mode=next;controls.enableRotate=mode==='orbit';const v=data.views?.[mode];controls.target.fromArray(v?.target||[0,.8,.65]);camera.position.fromArray(v?.position||(mode==='plan'?[0,.8,14]:[6.9,-11.8,7.7]));camera.fov=v?.fov||42;const distance=camera.position.distanceTo(controls.target);controls.maxDistance=Math.max(30,distance*3);camera.far=Math.max(120,distance*6);camera.updateProjectionMatrix();controls.update();$('orbit').setAttribute('aria-pressed',String(mode==='orbit'));$('plan').setAttribute('aria-pressed',String(mode==='plan'));}
$('orbit').onclick=()=>setView('orbit');$('plan').onclick=()=>setView('plan');$('home').onclick=()=>setView(mode);
$('objects').onchange=()=>select($('objects').value);
for(const [id,value] of [['open-all',1],['close-all',0]])$(id).onclick=()=>{for(const j of joints.values()){j.target=value;if(j.button)j.button.setAttribute('aria-pressed',String(!!value));}status(value?'Opening all doors and drawers':'Closing all doors and drawers');};
const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();let down=null;
function pick(e){const r=canvas.getBoundingClientRect();pointer.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);raycaster.setFromCamera(pointer,camera);return raycaster.intersectObjects(pickables.filter(m=>m.visible),false)[0];}
canvas.addEventListener('pointerdown',e=>{
 if(!moveMode||e.button!==0||drag)return;const hit=pick(e),id=hit?.object.userData.owner;if(!id||hit.object.userData.joint)return;
 if(tabletop?.has(id)&&tabletop.paused){select(id);status('Resume physics to lift objects');return;}
 if(data.objects.find(o=>o.instance_id===id)?.movable===false){select(id);status('This fixed object keeps its source placement');return;}
 e.stopImmediatePropagation();e.preventDefault();select(id);controls.enabled=false;down=null;
 const origin=placements.get(id).position.clone();origin.z=settling.get(id)??origin.z;settling.delete(id);
 const physical=tabletop?.begin(id)||false;
 drag={id,origin,physical,target:origin.clone(),point:hit.point.clone(),plane:new THREE.Plane(new THREE.Vector3(0,0,1),-hit.point.z),pointerId:e.pointerId,start:performance.now(),active:false};canvas.setPointerCapture(e.pointerId);
},true);
canvas.addEventListener('pointermove',e=>{
 if(!drag||e.pointerId!==drag.pointerId)return;e.stopImmediatePropagation();if(!drag.active)return;pick(e);const point=new THREE.Vector3();if(raycaster.ray.intersectPlane(drag.plane,point)){const group=placements.get(drag.id),next=drag.origin.clone().add(point.sub(drag.point));if(drag.physical){drag.target.x=next.x;drag.target.y=next.y;status('Release to drop · Esc returns the object');return;}const box=bounds(drag.id);box.translate(new THREE.Vector3(0,0,drag.origin.z-group.position.z));const delta=constrain(box,next.clone().sub(group.position),dragObstacles(drag.id,box));moveObject(drag.id,group.position.clone().add(delta));status('Dragging with bounding-box limits · release to place');}
},true);
canvas.addEventListener('pointerup',e=>{if(drag&&e.pointerId===drag.pointerId){e.stopImmediatePropagation();finishDrag();}},true);
canvas.addEventListener('pointercancel',()=>finishDrag(true),true);
canvas.addEventListener('lostpointercapture',()=>finishDrag(true));
canvas.addEventListener('pointerdown',e=>{down={x:e.clientX,y:e.clientY,button:e.button};});
canvas.addEventListener('pointerup',e=>{if(!down||down.button!==0||Math.hypot(e.clientX-down.x,e.clientY-down.y)>5){down=null;return;}down=null;const hit=pick(e);if(!hit)return;select(hit.object.userData.owner);const j=joints.get(hit.object.userData.joint);if(j)toggle(j);});
canvas.addEventListener('pointercancel',()=>{down=null;});
canvas.addEventListener('pointermove',e=>{const hit=pick(e);canvas.style.cursor=hit?.object.userData.joint?'pointer':hit?.object.userData.owner?'crosshair':'grab';});
new ResizeObserver(()=>{const w=stage.clientWidth,h=stage.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}).observe(stage);
setView('orbit');$('counts').textContent=`${data.objects.length} objects · ${data.joints.length} independent joints`;

if(data.tabletop){
 const refresh=()=>{lighting.refresh();$('counts').textContent=`${data.objects.length} objects · ${data.joints.length} independent joints`;select(null);$('objects').replaceChildren(new Option('Choose in the scene or here',''));for(const o of data.objects)$('objects').append(new Option(o.label||readable(o.instance_id),o.instance_id));};
 tabletop=createTabletop({data,scene,pickables,placements,objectMeshes,materials,onChange:refresh,status});
 $('tabletop').hidden=false;$('table-view').hidden=false;$('seed').value=data.tabletop.seed;
 const seedFromURL=new URLSearchParams(location.hash.slice(1)).get('seed');
 if(seedFromURL!==null){$('seed').value=seedFromURL;tabletop.regenerate(seedFromURL);}
 const useSeed=async seed=>{finishDrag(true);if(!await tabletop.regenerate(seed))return;$('seed').value=seed;const params=new URLSearchParams(location.hash.slice(1));params.set('seed',seed);history.replaceState(null,'','#'+params);};
 $('swap-all').onclick=()=>useSeed(String(crypto.getRandomValues(new Uint32Array(1))[0]));
 $('apply-seed').onclick=()=>useSeed($('seed').value.trim()||data.tabletop.seed);
 $('seed').onkeydown=e=>{if(e.key==='Enter')$('apply-seed').click();};
 $('original-table').onclick=()=>{finishDrag(true);tabletop.original();const params=new URLSearchParams(location.hash.slice(1));params.delete('seed');history.replaceState(null,'',location.pathname+location.search+(params.size?'#'+params:''));status('Original tabletop restored');};
 $('reset-table').onclick=()=>{finishDrag(true);tabletop.reset();status('Current seed restored');};
 $('physics-pause').onclick=()=>{tabletop.paused=!tabletop.paused;$('physics-pause').textContent=tabletop.paused?'Resume physics':'Pause physics';$('physics-pause').setAttribute('aria-pressed',String(tabletop.paused));};
 $('nudge-table').onclick=()=>{tabletop.nudge();status(tabletop.paused?'Nudge queued · resume physics to see it':'Tabletop objects nudged');};
 $('table-view').onclick=()=>{mode='orbit';controls.enableRotate=true;tabletop.focus(camera,controls);$('orbit').setAttribute('aria-pressed','true');$('plan').setAttribute('aria-pressed','false');};
 $('hint').textContent='Hold a tabletop object to lift · drag and release to drop · scroll to zoom';
 $('table-view').click();
}

chairs=createChairs({data,scene,pickables,placements,objectMeshes,materials,onChange:()=>{lighting.refresh();tabletop?.rebuildStatics();select(selected);}});
sceneGraph=createSceneGraph({data,scene,pickables,bounds,tabletop,chairs,joints,onSelect:select});
select(data.tabletop?.supports[0]?.id||null);
let previous=performance.now();
function animate(now){const elapsed=(now-previous)/1000,dt=Math.min(elapsed,.05);previous=now;
 if(playing&&data.animation){const end=(interaction?.range[1]||data.animation.frames)/data.animation.fps;const next=Math.min(end,playbackTime+elapsed);if(poseFrame(Math.min(Math.ceil(end*data.animation.fps)-1,Math.floor(next*data.animation.fps))))playbackTime=next;if(playbackTime>=end){playing=false;$('play').textContent='Play';}}
 if(drag){if(now-drag.start>=160)drag.active=true;if(drag.active){if(drag.physical){drag.target.z=drag.origin.z+.25;tabletop.move(drag.id,drag.target.toArray());}else{const p=placements.get(drag.id).position;p.z=THREE.MathUtils.damp(p.z,drag.origin.z+.14,18,elapsed);}canvas.style.cursor='grabbing';}}
 for(const [id,z] of settling){const p=placements.get(id).position;p.z=THREE.MathUtils.damp(p.z,z,22,elapsed);if(Math.abs(p.z-z)<.001){p.z=z;settling.delete(id);if(chairs?.has(id))tabletop?.rebuildStatics();}}
 for(const j of joints.values()){const step=dt*1.35;j.value+=Math.sign(j.target-j.value)*Math.min(Math.abs(j.target-j.value),step);updatePose(j);if(j.input&&document.activeElement!==j.input)j.input.value=Math.round(j.value*100);}
 tabletop?.tick(dt);
 controls.update();scene.updateMatrixWorld(true);sceneGraph.tick(now);
 if(highlight){scene.remove(highlight);highlight.geometry.dispose();highlight.material.dispose();highlight=null;}
 if(selected && data.show_selection_bounds===true){highlight=createSelectionBox(objectMeshes.get(selected)||[],tabletop?.has(selected)?placements.get(selected):null);if(highlight){highlight.userData.selectionId=selected;scene.add(highlight);}}
 renderer.render(scene,camera);requestAnimationFrame(animate);
}
requestAnimationFrame(animate);
// Read-only inspection hooks for interaction QA; clicks and controls remain the input path.
materialLab=createMaterials({data,pickables,objectMeshes,actors,getSelected:()=>selected,status});
window.roomkitQA={controls,interaction,materialLab,lighting,async seek(frame){playing=false;playbackTime=frame/data.animation.fps;requestedFrame=frame;if(stream){const values=await stream.frame(frame);if(requestedFrame===frame)applyFrame(frame,values);}else poseFrame(frame);},chairs,sceneGraph,tabletop,walkableCover,dragObstacles,bounds,constrain,get dragging(){return drag?.active??false;},joints,scene,camera,renderer,pickables,placements,actors,get shownFrame(){return shownFrame;},get playing(){return playing;},get selected(){return selected;},get mode(){return mode;},ready:true};
} catch(error){document.getElementById('error').textContent='The 3D view could not start: '+error.message;console.error(error);}

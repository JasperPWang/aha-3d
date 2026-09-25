import * as THREE from 'three';

// A prescribed object track shares the mesh animation clock, including seeks.
// Furniture motion here is kinematic playback, not a dynamics simulation.
export function createInteraction({data,placements,objectMeshes,scene,lighting}) {
 const spec=data.interaction;
 if(!spec)return null;
 if(!data.animation)throw Error('Interaction tracks need an animation timeline');
 const tracks=spec.object_tracks||[];
 for(const track of tracks){
  if(!placements.has(track.owner)||track.translations.length!==data.animation.frames)throw Error('Invalid object interaction track');
  if(track.translations.some(p=>p.length!==3||p.some(x=>!Number.isFinite(x))))throw Error('Nonfinite object track');
  if(track.quaternions&&(track.quaternions.length!==data.animation.frames||track.quaternions.some(q=>q.length!==4||q.some(x=>!Number.isFinite(x))||Math.abs(Math.hypot(...q)-1)>.001)))throw Error('Invalid rigid rotation track');
 }
 const lightTracks=spec.light_tracks||[];
 for(const t of lightTracks)if(!lighting?.lights.some(l=>l.userData.lamp&&l.userData.owner===t.owner)||t.values.length!==data.animation.frames||t.values.some(v=>!Number.isFinite(v)||v<0||v>1))throw Error('Invalid lamp state track');
 const panel=document.getElementById('playback');
 document.querySelector('.sidebar-tabs').after(panel);
 panel.querySelector('h2').textContent='Interaction sequence';
 const label=document.createElement('p');label.className='muted';label.id='interaction-phase';panel.append(label);
 let lastFrame=0,updateDirections=()=>{},updateRoots=()=>{},updateSupport=()=>{};
 let variant=spec.default_variant,range=[0,data.animation.frames];
 function setVariant(owner){
  if(!spec.variants?.some(v=>v.owner===owner))throw Error('Unknown motion stage');
  variant=owner;
  for(const v of spec.variants){
   if(placements.has(v.owner))placements.get(v.owner).visible=v.owner===owner;
   for(const m of objectMeshes.get(v.owner)||[])m.visible=v.owner===owner;
  }
  const select=document.getElementById('interaction-stage');if(select)select.value=owner;updateDirections(lastFrame);updateRoots(lastFrame);updateSupport(lastFrame);
 }
 if(spec.variants){
  const select=document.createElement('select');select.id='interaction-stage';select.setAttribute('aria-label','Motion artifact');
  for(const v of spec.variants){const o=document.createElement('option');o.value=v.owner;o.textContent=v.label;select.append(o);}
  select.onchange=()=>setVariant(select.value);panel.append(select);setVariant(variant||spec.variants[0].owner);
  const phases=document.createElement('select');phases.id='interaction-step';phases.setAttribute('aria-label','Plan step');
  const all=document.createElement('option');all.value='-1';all.textContent=`All ${spec.phases.length} steps · 0–${data.animation.frames/data.animation.fps} s`;phases.append(all);
  spec.phases.forEach((p,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`Step ${i+1} · ${p.start_frame/data.animation.fps}–${p.end_frame/data.animation.fps} s · ${p.label}`;phases.append(o);});
  phases.onchange=()=>{const p=spec.phases[Number(phases.value)];range=p?[p.start_frame,p.end_frame]:[0,data.animation.frames];window.roomkitQA?.seek(range[0]);};panel.append(phases);
  const note=document.createElement('p');note.className='muted';note.textContent=spec.provenance;panel.append(note);
 }

 if(spec.baseline_owner&&!spec.variants){
  const originals=objectMeshes.get(spec.baseline_owner)||[];
  originals.forEach(m=>{m.visible=false;});
  const button=document.createElement('button');button.id='interaction-baseline';button.textContent='Show before refinement';button.setAttribute('aria-pressed','false');
  button.onclick=()=>{const show=button.getAttribute('aria-pressed')!=='true';originals.forEach(m=>{m.visible=show;});button.setAttribute('aria-pressed',String(show));button.textContent=show?'Hide before refinement':'Show before refinement';};
  panel.append(button);
 }
 const target=new THREE.Mesh(new THREE.SphereGeometry(.018,12,8),new THREE.MeshBasicMaterial({color:0xffb547}));target.name='Planned hand contact';scene.add(target);
 if(spec.hand_orientation_goal){
  const actual=new THREE.ArrowHelper(new THREE.Vector3(0,0,-1),new THREE.Vector3(),.16,0x15a8ba,.035,.018);
  const desired=new THREE.ArrowHelper(new THREE.Vector3(0,0,-1),new THREE.Vector3(),.16,0xffb547,.035,.018);
  actual.name='Measured mesh palm normal';desired.name='Requested palm normal';scene.add(actual,desired);
  // These diagnostic arrows must remain legible when they point into the chair.
  for(const arrow of [actual,desired])for(const part of [arrow.line,arrow.cone]){part.material.depthTest=false;part.material.depthWrite=false;part.renderOrder=10;}
  const row=document.createElement('label'),toggle=document.createElement('input');toggle.type='checkbox';toggle.checked=true;toggle.id='interaction-directions';
  row.append(toggle,document.createTextNode('Palm arrows: cyan actual / gold requested'));panel.append(row);
  const info=document.createElement('p');info.id='interaction-hand-angle';info.className='muted';panel.append(info);
  updateDirections=frame=>{
   const track=spec.hand_direction_tracks?.[variant];const on=!!track&&!!spec.hand_contact_mask?.[frame];
   actual.visible=desired.visible=on&&toggle.checked;
   if(!on){info.textContent='';return;}
   actual.position.fromArray(track.palm_centers[frame]);desired.position.copy(actual.position);desired.position.y+=.045;
   actual.setDirection(new THREE.Vector3(...track.mesh_normal[frame]).normalize());desired.setDirection(new THREE.Vector3(...spec.hand_orientation_goal.palm_normal_room).normalize());
   const dot=new THREE.Vector3(...track.mesh_normal[frame]).dot(new THREE.Vector3(...spec.hand_orientation_goal.palm_normal_room));
   info.textContent=`Mesh palm normal: ${(Math.acos(Math.max(-1,Math.min(1,dot)))*180/Math.PI).toFixed(1)}° from requested down direction`;
  };
  toggle.onchange=()=>updateDirections(lastFrame);
 }
 if(spec.root_coupling){
  const root=spec.root_coupling,z=root.floor_height+.035;
  const on=spec.hand_contact_mask,ids=on.flatMap((yes,i)=>yes?[i]:[]);
  const makeLine=(points,color)=>{const m=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color,depthTest:false,depthWrite:false}));m.renderOrder=11;scene.add(m);return m;};
  const planned=makeLine(ids.map(i=>new THREE.Vector3(...root.goal_xy[i],z)),0xffb547);
  const paths=new Map(Object.entries(root.tracks).map(([name,track])=>[name,makeLine(ids.map(i=>new THREE.Vector3(track[i][0],track[i][1],z+.003)),0x15a8ba)]));
  const marker=new THREE.Mesh(new THREE.SphereGeometry(.025,12,8),new THREE.MeshBasicMaterial({color:0x15a8ba,depthTest:false}));marker.renderOrder=12;scene.add(marker);
  const span=makeLine([new THREE.Vector3(),new THREE.Vector3()],0x15a8ba);span.name='Root to moving grasp (floor projection)';
  const row=document.createElement('label'),toggle=document.createElement('input');toggle.type='checkbox';toggle.checked=true;toggle.id='interaction-root-path';
  row.append(toggle,document.createTextNode('Pull root path on floor: cyan actual / gold planned'));panel.append(row);
  const info=document.createElement('p');info.id='interaction-root-error';info.className='muted';panel.append(info);
  updateRoots=frame=>{
   const track=root.tracks[variant],visible=toggle.checked&&!!on[frame];planned.visible=visible;
   for(const [name,path] of paths)path.visible=visible&&name===variant;
   marker.visible=span.visible=visible&&!!track;
   if(!track||!on[frame]){info.textContent='';return;}
   const [x,y]=track[frame],goal=root.goal_xy[frame],hand=spec.hand_targets[frame];marker.position.set(x,y,z);
   const pos=span.geometry.attributes.position;pos.setXYZ(0,x,y,z);pos.setXYZ(1,hand[0],hand[1],z);pos.needsUpdate=true;span.geometry.computeBoundingSphere();
   info.textContent=`Root path error: ${(100*Math.hypot(x-goal[0],y-goal[1])).toFixed(2)} cm; line links root to moving grasp`;
  };
  toggle.onchange=()=>updateRoots(lastFrame);
 }
 if(spec.foot_support){
  const row=document.createElement('p');row.id='interaction-foot-support';row.setAttribute('role','status');panel.append(row);
  for(const v of Object.values(spec.foot_support))if(v.gaps_m.length!==data.animation.frames||v.gaps_m.some(pair=>pair.length!==2||pair.some(x=>!Number.isFinite(x))))throw Error('Invalid all-frame foot support diagnostics');
  updateSupport=frame=>{
   const record=spec.foot_support[variant];if(!record){row.textContent='';return;}
   const [left,right]=record.gaps_m[frame],gap=Math.min(left,right);
   const state=gap>.02?'NO FOOT SUPPORT':gap<-.005?'FLOOR PENETRATION':'Support present';
   row.textContent=`Foot / authored floor gap: L ${(left*100).toFixed(1)} cm · R ${(right*100).toFixed(1)} cm · ${state}`;
   row.style.color=gap>.02||gap<-.005?'#ffad91':'#b9e5cc';
  };
 }
 function apply(frame){
  lastFrame=frame;updateDirections(frame);updateRoots(frame);updateSupport(frame);
  for(const track of tracks){const placement=placements.get(track.owner);placement.position.fromArray(track.translations[frame]);if(track.quaternions)placement.quaternion.fromArray(track.quaternions[frame]);}
  for(const track of lightTracks)lighting.setLampLevel(track.owner,track.values[frame]);
  const phase=spec.phases.find(p=>frame>=p.start_frame&&frame<p.end_frame);
  label.textContent=phase?`Step ${spec.phases.indexOf(phase)+1}/${spec.phases.length} · ${phase.start_frame/data.animation.fps}–${phase.end_frame/data.animation.fps} s · ${phase.label} · local time ${((frame-phase.start_frame)/data.animation.fps).toFixed(2)} s`:'';
  target.visible=!!spec.hand_contact_mask?.[frame];
  if(target.visible)target.position.fromArray(spec.hand_targets[frame]);
 }
 return {apply,tracks,setVariant,get variant(){return variant;},get range(){return range;}};
}

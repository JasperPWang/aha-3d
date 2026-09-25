import * as THREE from 'three';

export function createDemoInteractions(api,data){
 if(!api?.ready||!data.quick_actions?.interactions)return;
 const $=id=>document.getElementById(id),panel=$('editor-panel');if(!panel)return;
 const style=document.createElement('style');style.textContent=`
 #demo-physics{flex-shrink:0;border-bottom:1px solid #d6dccf;padding:0 0 10px}
 #demo-physics label{display:flex;align-items:center;gap:8px;font-size:12px;color:#29342a}
 #demo-physics input{accent-color:#39543d;width:16px;height:16px;margin:0}
 #demo-physics button,#replace-prop{font-size:11px;padding:7px;width:100%;margin-top:8px;border-radius:5px}
 #prop-replacements{margin-top:12px;border-top:1px solid #d6dccf;padding-top:10px}
 #fixture-switches label{display:flex;align-items:center;gap:7px;margin:8px 0;font-size:11px}
 @media(max-width:680px){#editor-panel{grid-template-rows:auto minmax(0,1fr)}#demo-physics{grid-column:1/-1;display:flex;justify-content:space-between;align-items:center;padding:0 0 6px}#demo-physics button{width:auto;margin:0}#editor-panel .finish-card{grid-row:2}}
 `;document.head.append(style);
 if(api.tabletop){
  const table=api.tabletop,section=document.createElement('section');section.id='demo-physics';
  section.innerHTML='<label><input id="enable-physics" type="checkbox">Enable physics</label><button id="physics-nudge" type="button">Nudge objects</button><button id="reset-scene" type="button">Reset scene</button>';
  panel.prepend(section);
  const enabled=$('enable-physics'),nudge=$('physics-nudge');
  const syncPhysics=()=>{enabled.checked=!table.paused;nudge.disabled=table.paused;};
  const initialView={position:new THREE.Vector3(...(data.views?.orbit?.position||api.camera.position.toArray())),target:new THREE.Vector3(...(data.views?.orbit?.target||api.controls.target.toArray())),fov:data.views?.orbit?.fov||api.camera.fov},initialQuality=api.lighting.quality;
  $('reset-scene').onclick=()=>{
   // Cancel any active pointer constraint through the shared layout control.
   table.paused=true;
   for(const id of api.placements.keys())api.materialLab.reset(id);
   $('reset-layout').click();table.original();
   for(const joint of api.joints.values()){joint.value=joint.target=0;joint.group.position.copy(joint.a.p);joint.group.quaternion.copy(joint.a.q);joint.group.scale.copy(joint.a.s);if(joint.input)joint.input.value=0;if(joint.button)joint.button.setAttribute('aria-pressed','false');}
   api.lighting.lamps(true);api.lighting.setQuality(initialQuality);$('lighting-quality').value=initialQuality;syncLights();
   if(data.animation)api.seek(0);
   $('orbit').click();api.camera.position.copy(initialView.position);api.camera.fov=initialView.fov;api.controls.target.copy(initialView.target);api.camera.lookAt(initialView.target);api.camera.updateProjectionMatrix();api.controls.update();
   const params=new URLSearchParams(location.hash.slice(1));params.delete('seed');history.replaceState(null,'',location.pathname+location.search+(params.size?'#'+params:''));
   table.rebuildStatics();table.paused=table.spec.start_paused===true;index=0;syncPhysics();syncObjects();$('quick-state').textContent='Original scene';
  };
  enabled.onchange=()=>{if(api.dragging){enabled.checked=!table.paused;return;}table.release();table.paused=!enabled.checked;syncPhysics();};
  nudge.onclick=()=>{if(!table.paused)table.nudge();};syncPhysics();
  const replacement=document.createElement('section');replacement.id='prop-replacements';
  replacement.innerHTML='<label for="prop-object">Tabletop object</label><select id="prop-object"></select><label for="prop-asset">Asset library</label><select id="prop-asset"></select><button id="replace-prop" type="button">Replace object</button>';
  $('layout-card').insertBefore(replacement,$('layout-card').querySelector('details'));
  const object=$('prop-object'),asset=$('prop-asset'),replace=$('replace-prop');
  for(const template of table.spec.templates.filter(t=>t.id.startsWith('browser-template-')))asset.append(new Option(template.label,template.id));
  function syncObjects(){const current=table.has(api.selected)?api.selected:object.value;object.replaceChildren();for(const e of table.entries.values())object.append(new Option(e.template.label,e.id));if(table.has(current))object.value=current;replace.disabled=!object.value||!asset.value;}
  object.onchange=()=>{$('objects').value=object.value;$('objects').dispatchEvent(new Event('change'));};
  $('objects').addEventListener('change',syncObjects);
  new MutationObserver(syncObjects).observe($('material-slot'),{childList:true});
  replace.onclick=async()=>{if(api.dragging)return;replace.disabled=true;const id=object.value;try{if(await table.replace(id,asset.value)){$('objects').value=id;$('objects').dispatchEvent(new Event('change'));}}finally{syncObjects();}};
  let index=0;const layouts=data.quick_actions.layouts||[];
  if(layouts.length)$('quick-layout').onclick=()=>{if(api.dragging)return;index=(index+1)%layouts.length;table.arrangeOffsets(layouts[index].positions);$('quick-state').textContent=layouts[index].label;$('table-view').click();};
  $('quick-restore').onclick=()=>{if(api.dragging)return;table.original();index=0;syncObjects();$('quick-state').textContent='Original tabletop';};
  syncObjects();
 }
 const fixtureList=document.createElement('details');fixtureList.id='fixture-switches';fixtureList.innerHTML='<summary>Individual lights</summary>';$('layout-card').append(fixtureList);
 const lights=api.lighting.lights.filter(l=>l.userData.lamp),switches=new Map();
 for(const light of lights){const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=light.intensity>0;input.dataset.fixture=light.userData.id;label.append(input,document.createTextNode(light.userData.label||light.name.replace(/ emitters$/,'').replaceAll('_',' ')));fixtureList.append(label);switches.set(light.userData.id,input);input.onchange=()=>api.lighting.setFixtureLevel(light.userData.id,input.checked?1:0);}
 const syncLights=()=>{for(const light of lights)switches.get(light.userData.id).checked=light.intensity>0;};$('lamps').addEventListener('click',syncLights);
 const canvas=api.renderer.domElement,stage=$('stage'),raycaster=new THREE.Raycaster();let down;
 const pick=e=>{const r=canvas.getBoundingClientRect();raycaster.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),api.camera);return raycaster.intersectObjects(api.pickables.filter(m=>m.visible),false)[0];};
 stage.addEventListener('pointerdown',e=>{if(e.target!==canvas||e.button!==0)return;const hit=pick(e);down=hit?{x:e.clientX,y:e.clientY,id:api.lighting.fixtureForMesh(hit.object),time:performance.now()}:null;},true);
 stage.addEventListener('pointerup',e=>{const start=down;down=null;if(e.target!==canvas||!start?.id||api.dragging||performance.now()-start.time>300||Math.hypot(e.clientX-start.x,e.clientY-start.y)>5)return;const light=lights.find(l=>l.userData.id===start.id);api.lighting.setFixtureLevel(start.id,light.intensity>0?0:1);syncLights();},true);
 stage.addEventListener('pointercancel',()=>{down=null;},true);
}

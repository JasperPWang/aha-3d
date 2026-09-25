import {castsSurfaceShadow} from './material-surface.js';
import * as THREE from 'three';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';

export function createLighting({renderer,scene,data,placements,joints,pickables,materials}){
 const $=id=>document.getElementById(id), config=data.lighting||{}, lampLights=[], emissionMaterials=[];
 const hasDaylight=(config.lights||[]).some(l=>!l.lamp&&l.energy>0);
 const exposure=config.exposure??(hasDaylight?.85:1),lampScale=config.lamp_scale??(hasDaylight?.65:1);
 renderer.toneMappingExposure=exposure;
 const envScene=new RoomEnvironment(), pmrem=new THREE.PMREMGenerator(renderer);
 const environment=pmrem.fromScene(envScene,.04);scene.environment=environment.texture;
 scene.environmentRotation.x=Math.PI/2;scene.environmentIntensity=.45;
 envScene.dispose();pmrem.dispose();
 const ambient=new THREE.HemisphereLight(0xdceaff,0x777064,config.probe?.coefficients?.length===9?(hasDaylight?.08:.25):.65);
 ambient.position.set(0,0,1);scene.add(ambient);
 const box=new THREE.Box3();for(const mesh of pickables)box.expandByObject(mesh);
 const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());
 const radius=Math.max(size.x,size.y,size.z,2);
 // Authored window light already supplies daylight; keep the generic key as
 // softer fill instead of stacking a second full-strength primary light.
 const key=new THREE.DirectionalLight(0xfff4df,config.key_intensity??(hasDaylight?.8:1.5));
 key.position.copy(center).add(new THREE.Vector3(-.45,-.6,1).multiplyScalar(radius));
 key.target.position.copy(center);scene.add(key,key.target);
 key.shadow.camera.left=key.shadow.camera.bottom=-radius*.65;
 key.shadow.camera.right=key.shadow.camera.top=radius*.65;
 key.shadow.camera.near=.1;key.shadow.camera.far=radius*4;
 key.shadow.normalBias=.025;key.shadow.bias=-.00015;key.shadow.mapSize.set(1024,1024);
 let probe=null,lightmap=null;
 if(config.probe?.coefficients?.length===9){
  const sh=new THREE.SphericalHarmonics3();sh.fromArray(config.probe.coefficients.flat());probe=new THREE.LightProbe(sh,1);scene.add(probe);
 }
 if(config.lightmap){
  const m=config.lightmap,bytes=Uint8Array.from(atob(m.rgb_float16_base64),c=>c.charCodeAt(0));
  const rgb=new Uint16Array(bytes.buffer),rgba=new Uint16Array(m.width*m.height*4);
  if(rgb.length!==m.width*m.height*3)throw Error('Invalid baked lightmap dimensions');
  for(let i=0;i<m.width*m.height;i++){rgba[i*4]=rgb[i*3];rgba[i*4+1]=rgb[i*3+1];rgba[i*4+2]=rgb[i*3+2];rgba[i*4+3]=0x3c00;}
  lightmap=new THREE.DataTexture(rgba,m.width,m.height,THREE.RGBAFormat,THREE.HalfFloatType);
  lightmap.colorSpace=THREE.LinearSRGBColorSpace;lightmap.channel=1;
  lightmap.minFilter=lightmap.magFilter=THREE.LinearFilter;lightmap.needsUpdate=true;
 }
 // Prevent a second diffuse IBL contribution when a baked probe is present.
 // Static atlas materials receive their baked bounce instead of the room probe.
 function tune(material,baked=false){
  if(!probe&&!baked)return;
  material.onBeforeCompile=shader=>{
   shader.fragmentShader=shader.fragmentShader.replace('#include <lights_fragment_maps>',THREE.ShaderChunk.lights_fragment_maps.replace('iblIrradiance += getIBLIrradiance( geometryNormal );',''));
   if(baked)shader.fragmentShader=shader.fragmentShader.replace('#include <lights_fragment_begin>',THREE.ShaderChunk.lights_fragment_begin.replace('irradiance += getLightProbeIrradiance( lightProbe, geometryNormal );',''));
  };
  material.customProgramCacheKey=()=>baked?'roomkit-atlas-v1':'roomkit-probe-v1';material.needsUpdate=true;
 }
 for(const material of materials)tune(material);
 const bakedMaterials=new Map(),atlasMaterials=new Set();
 for(const [index,record] of data.meshes.entries()){
  const mesh=pickables[index];if(!mesh)continue;mesh.castShadow=castsSurfaceShadow(mesh);mesh.receiveShadow=true;
  if(lightmap&&record.lightmap_uv){
   mesh.geometry.setAttribute('uv1',new THREE.Float32BufferAttribute(record.lightmap_uv,2));
   // Only used material slots need atlas variants; preserve group slot indices.
   mesh.material=materials.map((m,i)=>{
    if(!record.groups.some(g=>g.material===i))return m;
    if(!bakedMaterials.has(i)){const clone=m.clone();clone.lightMap=lightmap;clone.lightMapIntensity=config.lightmap.intensity||Math.PI;tune(clone,true);bakedMaterials.set(i,clone);atlasMaterials.add(clone);}
    return bakedMaterials.get(i);
   });
  }
 }
 const records=[...(config.lights||[])];
 // Bound fragment shader cost. Prioritize recognizable fixtures, then daylight.
 records.sort((a,b)=>Number(b.lamp)-Number(a.lamp)||b.energy-a.energy);
 const active=records.filter(r=>r.energy>0).slice(0,config.max_lights||12);
 const lights=[];
 for(const record of active){
  const color=new THREE.Color(...record.color), energy=Math.max(0,record.energy);
  let light;
  if(record.type==='SUN')light=new THREE.DirectionalLight(color,Math.min(energy,3));
  else if(record.type==='SPOT'||record.type==='AREA'){
   light=new THREE.SpotLight(color,Math.min(energy*.3,90),Math.max(6,radius*1.5),record.angle||Math.PI*.38,record.penumbra??.65,2);
  }else light=new THREE.PointLight(color,Math.min(energy*.8,45),Math.max(5,radius),2);
  if(record.lamp)light.intensity*=lampScale;
  light.name=record.name;light.userData={...record,baseIntensity:light.intensity};light.position.fromArray(record.position);
  const parent=record.joint?joints.get(record.joint)?.group:placements.get(record.owner);
  (parent||scene).add(light);
  if(light.target){light.target.position.copy(light.position).add(new THREE.Vector3(...(record.direction||[0,0,-1])));(parent||scene).add(light.target);}
  light.shadow.mapSize.set(512,512);light.shadow.camera.near=.05;light.shadow.camera.far=Math.max(8,radius*2);light.shadow.normalBias=.02;light.shadow.bias=-.0001;
  lights.push(light);if(record.lamp)lampLights.push(light);
  for(const name of record.emitter_meshes||[]){
   for(const mesh of pickables.filter(m=>m.name===name)){
    // A simplified solid shade cannot transmit light as real cloth/glass does.
    mesh.castShadow=false;mesh.userData.browserEmitter=true;
    mesh.material=(Array.isArray(mesh.material)?mesh.material:[mesh.material]).map(mat=>{
     const clone=mat.clone();tune(clone,!!clone.lightMap);if(clone.lightMap)atlasMaterials.add(clone);
     clone.emissive.copy(color);clone.emissiveIntensity=.65;
     emissionMaterials.push({material:clone,intensity:clone.emissiveIntensity,owner:record.owner,fixture:record.id});return clone;
    });
   }
  }
 }
 const lampsButton=$('lamps');lampsButton.hidden=lampLights.length===0;
 let lampsOn=true,quality='balanced',indirectOn=true;
 function lamps(on){lampsOn=!!on;for(const light of lampLights)light.intensity=lampsOn?light.userData.baseIntensity:0;for(const entry of emissionMaterials)entry.material.emissiveIntensity=lampsOn?entry.intensity:0;lampsButton.setAttribute('aria-pressed',String(lampsOn));lampsButton.textContent=lampsOn?'Lamps on':'Lamps off';}
 function setLampLevel(owner,level){
  if(!Number.isFinite(level)||level<0||level>1)throw Error('Lamp level must be between zero and one');
  const owned=lampLights.filter(l=>l.userData.owner===owner);if(!owned.length)throw Error('Unknown lamp owner: '+owner);
  for(const light of owned)light.intensity=light.userData.baseIntensity*level;
  for(const entry of emissionMaterials)if(entry.owner===owner)entry.material.emissiveIntensity=entry.intensity*level;
  lampsOn=lampLights.some(l=>l.intensity>0);lampsButton.setAttribute('aria-pressed',String(lampsOn));lampsButton.textContent=lampsOn?'Lamps on':'Lamps off';
 }
 lampsButton.onclick=()=>lamps(!lampsOn);
 function setFixtureLevel(id,level){
  if(!Number.isFinite(level)||level<0||level>1)throw Error('Invalid fixture level');
  const light=lampLights.find(l=>l.userData.id===id);if(!light)return false;
  light.intensity=light.userData.baseIntensity*level;
  for(const entry of emissionMaterials)if(entry.fixture===id)entry.material.emissiveIntensity=entry.intensity*level;
  lampsOn=lampLights.some(l=>l.intensity>0);lampsButton.setAttribute('aria-pressed',String(lampsOn));lampsButton.textContent=lampsOn?'Lamps on':'Lamps off';
  return true;
 }
 function fixtureForMesh(mesh){
  const explicit=lampLights.find(l=>l.userData.emitter_meshes?.includes(mesh.name));if(explicit)return explicit.userData.id;
  const owner=data.objects.find(o=>o.instance_id===mesh.userData.owner);
  if(!owner||owner.semantic_class?.startsWith('structure/'))return null;
  return lampLights.find(l=>l.userData.owner===mesh.userData.owner)?.userData.id||null;
 }
 function setQuality(value){
  quality=value;const shadows=value!=='fast';renderer.shadowMap.enabled=shadows;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.setPixelRatio(Math.min(devicePixelRatio,value==='fast'?1:value==='high'?2:1.5));key.castShadow=shadows;
  // Point-light shadows cost six views each; reserve them for at most two lamps.
  let budget=value==='high'?2:1;
  for(const light of lights){light.castShadow=shadows&&light.userData.lamp&&budget-->0;}
  scene.traverse(o=>{if(o.isMesh){o.receiveShadow=true;o.castShadow=castsSurfaceShadow(o);for(const m of Array.isArray(o.material)?o.material:[o.material])if(m)m.needsUpdate=true;}});
  renderer.shadowMap.needsUpdate=true;
 }
 $('lighting-quality').onchange=e=>setQuality(e.target.value);
 $('indirect').hidden=!probe&&!lightmap;
 $('indirect').onclick=()=>{indirectOn=!indirectOn;if(probe)probe.intensity=indirectOn?1:0;for(const m of atlasMaterials)m.lightMapIntensity=indirectOn?(config.lightmap.intensity||Math.PI):0;$('indirect').setAttribute('aria-pressed',String(indirectOn));};
 $('lighting-note').textContent=`${lampLights.length} lamp${lampLights.length===1?'':'s'} · ${lightmap?'Baked room lighting':'Environment lighting'}${records.length>active.length?' · limited lights for performance':''}`;
 setQuality('balanced');lamps(true);
 return {lights,key,probe,lightmap,lamps,setLampLevel,setFixtureLevel,fixtureForMesh,setQuality,get lampsOn(){return lampsOn;},get quality(){return quality;},get indirectOn(){return indirectOn;},
  refresh(){for(const mesh of pickables){mesh.receiveShadow=true;mesh.castShadow=castsSurfaceShadow(mesh);}},
  report(){return {lamps:lampLights.length,native:active.filter(r=>r.provenance==='native Blender light').length,inferred:active.filter(r=>r.provenance!=='native Blender light').length,omitted:records.length-active.length,lightmap:!!lightmap,probe:!!probe,quality,lampsOn,exposure,lampScale,keyIntensity:key.intensity};}};
}

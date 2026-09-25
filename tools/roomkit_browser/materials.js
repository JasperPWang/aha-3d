import * as THREE from 'three';
import {cloneSurfaceMaterial,castsSurfaceShadow} from './material-surface.js';
import {PRESETS,generate,recipe} from './material-generator.js';

/** Face projection in object axes, scaled to metres; leaves authored lightmap UVs alone. */
export function projectMaterialUV(mesh){
  const g=mesh.geometry.index?mesh.geometry.toNonIndexed():mesh.geometry.clone();
  mesh.updateWorldMatrix(true,false);
  const p=g.attributes.position,uv=new Float32Array(p.count*2),scale=new THREE.Vector3().setFromMatrixScale(mesh.matrixWorld);
  const a=new THREE.Vector3(),b=new THREE.Vector3(),c=new THREE.Vector3(),n=new THREE.Vector3();
  for(let i=0;i<p.count;i+=3){
    a.fromBufferAttribute(p,i);b.fromBufferAttribute(p,i+1);c.fromBufferAttribute(p,i+2);n.crossVectors(b.sub(a),c.sub(a));
    const [x,y,z]=[Math.abs(n.x),Math.abs(n.y),Math.abs(n.z)];
    const axes=x>=y&&x>=z?[1,2]:y>=z?[0,2]:[0,1];
    for(let j=0;j<3;j++){a.fromBufferAttribute(p,i+j).multiply(scale);uv[(i+j)*2]=a.getComponent(axes[0]);uv[(i+j)*2+1]=a.getComponent(axes[1]);}
  }
  g.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));return g;
}
function texture(bytes,tile,color=false){
  const t=new THREE.DataTexture(bytes,tile.size,tile.size,THREE.RGBAFormat);
  t.colorSpace=color?THREE.SRGBColorSpace:THREE.NoColorSpace;
  t.wrapS=t.wrapT=THREE.RepeatWrapping;t.magFilter=THREE.LinearFilter;t.minFilter=THREE.LinearMipmapLinearFilter;t.generateMipmaps=true;
  t.repeat.setScalar(1/tile.recipe.tileSize);t.rotation=tile.recipe.rotation*Math.PI/180;t.needsUpdate=true;return t;
}
function mapsFor(tile){return {map:texture(tile.baseColor,tile,true),roughnessMap:texture(tile.orm,tile),normalMap:texture(tile.normal,tile)};}
const mapUsers=new WeakMap();
function withMaps(original,tile,maps){
  mapUsers.set(maps,(mapUsers.get(maps)||0)+1);
  const m=cloneSurfaceMaterial(original,tile.recipe);
  // Three Material.clone does not copy custom shader hooks (the GI path uses them).
  m.onBeforeCompile=original.onBeforeCompile;m.customProgramCacheKey=original.customProgramCacheKey;
  m.onBeforeRender=(...args)=>{original.onBeforeRender?.(...args);m.lightMapIntensity=original.lightMapIntensity;};
  Object.assign(m,maps);m.metalnessMap=maps.roughnessMap;m.roughness=m.metalness=1;
  m.color.setRGB(1,1,1);m.normalScale.set(1,1);m.name=original.name;m.userData={...original.userData,procedural:tile.recipe};m.needsUpdate=true;return m;
}
function disposeMaps(maps){
  const users=(mapUsers.get(maps)||0)-1;mapUsers.set(maps,users);
  if(users===0)for(const t of Object.values(maps))t.dispose();
}

export function createMaterials({data,pickables,objectMeshes,actors,getSelected,status}){
  const $=id=>document.getElementById(id),states=new Map(),animated=new Set(actors.map(a=>a.mesh));
  const presets=$('material-preset'),slot=$('material-slot');
  for(const [id,p] of Object.entries(PRESETS))presets.append(new Option(p.label,id));
  function prune(){for(const [mesh,state] of states)if(!pickables.includes(mesh)){mesh.material=state.material;mesh.geometry=state.geometry;mesh.castShadow=state.castShadow;release(state);states.delete(mesh);}}
  function originals(mesh){return states.get(mesh)?.material??mesh.material;}
  const array=m=>Array.isArray(m)?m:[m];
  function eligible(mesh){return !animated.has(mesh)&&!mesh.userData.browserEmitter;}
  function refresh(){
    prune();const id=getSelected(),prior=slot.value;slot.replaceChildren();
    const names=new Set();for(const mesh of objectMeshes.get(id)||[])if(eligible(mesh))for(const g of mesh.geometry.groups.length?mesh.geometry.groups:[{materialIndex:0}]){
      const m=array(originals(mesh))[g.materialIndex];if(m)names.add(m.name||'Unnamed material');
    }
    for(const name of names)slot.append(new Option(name,name));
    if(names.size>1)slot.append(new Option('All material slots','*'));
    if([...slot.options].some(o=>o.value===prior))slot.value=prior;
    $('material-target').textContent=id?`Selected: ${id.replaceAll('_',' ')}`:'Select an object in the scene graph or scene.';
    $('material-apply').disabled=!names.size;$('material-reset').disabled=!(objectMeshes.get(id)||[]).some(m=>states.has(m));
  }
  function values(){return recipe({preset:presets.value,seed:$('material-seed').value,color:$('material-color').value,tileSize:Number($('material-size').value),rotation:Number($('material-rotation').value),roughness:Number($('material-roughness').value),relief:Number($('material-relief').value)/1000,transmission:Number($('material-transmission').value),ior:Number($('material-ior').value),thickness:Number($('material-thickness').value)/1000,clearcoat:Number($('material-clearcoat').value),clearcoatRoughness:Number($('material-coat-roughness').value)});}
  let preview=null;
  function updatePreview(){
    try{preview=generate(values(),256);const c=$('material-preview'),ctx=c.getContext('2d');c.width=c.height=preview.size;ctx.putImageData(new ImageData(new Uint8ClampedArray(preview.baseColor),preview.size,preview.size),0,0);
      $('material-description').textContent=`${PRESETS[preview.recipe.preset].label} · ${preview.recipe.tileSize} m repeat · ${(preview.recipe.relief*1000).toFixed(2)} mm relief${preview.recipe.transmission>0?' · light transmission':preview.recipe.clearcoat>0?' · glazed finish':''}`;
    }catch(e){status(e.message);preview=null;}
  }
  function defaults(){const p=PRESETS[presets.value];$('material-color').value=p.light;$('material-roughness').value=p.roughness;$('material-relief').value=p.relief*1000;$('material-transmission').value=p.transmission??0;$('material-ior').value=p.ior??1.5;$('material-thickness').value=(p.thickness??.006)*1000;$('material-clearcoat').value=p.clearcoat??0;$('material-coat-roughness').value=p.clearcoatRoughness??.1;$('material-glass-fields').hidden=p.family!=='glass';$('material-coat-fields').hidden=p.family!=='ceramic';updatePreview();}
  function release(state){for(const {material,maps} of state.overrides.values()){material.dispose();disposeMaps(maps);}if(state.geometry!==state.projected)state.projected?.dispose();}
  function apply(input=values(),target=getSelected(),materialName=slot.value){
    const tile=generate(input),meshes=(objectMeshes.get(target)||[]).filter(eligible);let count=0,sharedMaps=null;
    for(const mesh of meshes){
      const original=array(originals(mesh)),used=new Set((mesh.geometry.groups.length?mesh.geometry.groups:[{materialIndex:0}]).map(g=>g.materialIndex));
      const indices=[...used].filter(i=>original[i]&&(materialName==='*'||(original[i].name||'Unnamed material')===materialName));
      if(!indices.length)continue;
      if(!states.has(mesh)){
        const geometry=mesh.geometry,projected=geometry.attributes.uv?geometry:projectMaterialUV(mesh);
        states.set(mesh,{material:mesh.material,geometry,projected,castShadow:mesh.castShadow,overrides:new Map()});mesh.geometry=projected;mesh.material=original.slice();
      }
      const state=states.get(mesh);
      for(const i of indices){
        const previous=state.overrides.get(i);if(previous){previous.material.dispose();disposeMaps(previous.maps);}
        const maps=sharedMaps??=mapsFor(tile),material=withMaps(original[i],tile,maps);mesh.material[i]=material;state.overrides.set(i,{material,maps});count++;
      }
      mesh.castShadow=castsSurfaceShadow(mesh);
    }
    refresh();status(count?`${PRESETS[tile.recipe.preset].label} applied to ${count} surface${count===1?'':'s'}.`:'Select a static object and material slot first.');return count;
  }
  function reset(target=getSelected()){
    for(const mesh of objectMeshes.get(target)||[]){const state=states.get(mesh);if(!state)continue;mesh.material=state.material;mesh.geometry=state.geometry;mesh.castShadow=state.castShadow;release(state);states.delete(mesh);}
    refresh();status('Original materials restored');
  }
  function download(){const blob=new Blob([JSON.stringify(values(),null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='material-recipe.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  presets.onchange=defaults;
  for(const id of ['material-seed','material-color','material-size','material-rotation','material-roughness','material-relief','material-transmission','material-ior','material-thickness','material-clearcoat','material-coat-roughness'])$(id).onchange=updatePreview;
  $('material-apply').onclick=()=>{try{apply();}catch(e){status(e.message);}};
  $('material-reset').onclick=()=>reset();$('material-download').onclick=()=>{try{download();}catch(e){status(e.message);}};
  $('material-random').onclick=()=>{$('material-seed').value=String(crypto.getRandomValues(new Uint32Array(1))[0]);updatePreview();};
  // Generated materials imported from Blender retain their recipe automatically.
  const imported=new Map();
  for(const mesh of pickables){if(!eligible(mesh))continue;const used=new Set(mesh.geometry.groups.map(g=>g.materialIndex));
    let changed=false;const next=array(mesh.material).slice();
    for(const i of used){const r=data.materials[i]?.procedural;if(!r)continue;
      const key=JSON.stringify(recipe(r));
      if(!imported.has(key)){const tile=generate(r);imported.set(key,{tile,maps:mapsFor(tile)});}
      const {tile,maps}=imported.get(key);next[i]=withMaps(next[i],tile,maps);changed=true;
    }
    if(changed){if(!mesh.geometry.attributes.uv)mesh.geometry=projectMaterialUV(mesh);mesh.material=next;mesh.castShadow=castsSurfaceShadow(mesh);}
  }
  defaults();refresh();return {apply,reset,refresh,recipe:values,get overrideCount(){return states.size;}};
}

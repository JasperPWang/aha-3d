import * as THREE from 'three';

/** Shared scalar surface settings for imported scenes and generated recipes. */
export function surfaceOptions(source={}){
  return {transmission:source.transmission??0,ior:source.ior??1.5,thickness:source.thickness??.006,
    clearcoat:source.clearcoat??0,clearcoatRoughness:source.clearcoatRoughness??.1};
}
export function createSurfaceMaterial(parameters={},surface={}){
  const p=surfaceOptions(surface);
  return p.transmission>0||p.clearcoat>0?new THREE.MeshPhysicalMaterial({...parameters,...p}):new THREE.MeshStandardMaterial(parameters);
}
export function cloneSurfaceMaterial(original,surface){
  const p=surfaceOptions(surface),m=createSurfaceMaterial({},p);
  // Physical.copy expects another Physical material. Copy common Standard fields
  // explicitly, then restore the PHYSICAL shader define and the new surface layer.
  THREE.MeshStandardMaterial.prototype.copy.call(m,original);
  if(m.isMeshPhysicalMaterial){m.defines={STANDARD:'',PHYSICAL:''};Object.assign(m,p);}
  m.onBeforeCompile=original.onBeforeCompile;m.customProgramCacheKey=original.customProgramCacheKey;
  return m;
}
/** Ordinary shadow maps cannot transmit glass. Keep opaque slots casting. */
export function castsSurfaceShadow(mesh){
  if(mesh.userData.browserEmitter)return false;
  const materials=Array.isArray(mesh.material)?mesh.material:[mesh.material];
  const used=mesh.geometry.groups.length?mesh.geometry.groups.map(g=>g.materialIndex):[0];
  return used.some(i=>materials[i]&&(materials[i].transmission??0)<.5);
}

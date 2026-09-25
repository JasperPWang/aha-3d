import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {createSurfaceMaterial,cloneSurfaceMaterial,castsSurfaceShadow} from './material-surface.js';
import {recipe} from './material-generator.js';

test('physical surfaces preserve Standard properties and GI hooks without copying the wrong shader define',()=>{
 const source=new THREE.MeshStandardMaterial({roughness:.8,side:THREE.DoubleSide});source.name='original';
 source.lightMap=new THREE.Texture();source.lightMapIntensity=.7;source.normalScale.set(.3,.4);
 const hook=()=>{},cache=()=> 'custom-gi';source.onBeforeCompile=hook;source.customProgramCacheKey=cache;
 const glass=cloneSurfaceMaterial(source,recipe({preset:'glass_clear',ior:1.6,thickness:.007}));
 assert.ok(glass.isMeshPhysicalMaterial);assert.ok('PHYSICAL' in glass.defines);assert.equal(glass.transmission,1);assert.equal(glass.ior,1.6);assert.equal(glass.thickness,.007);
 assert.equal(glass.opacity,1);assert.equal(glass.transparent,false);assert.equal(glass.lightMap,source.lightMap);assert.equal(glass.lightMapIntensity,.7);assert.equal(glass.onBeforeCompile,hook);assert.equal(glass.customProgramCacheKey,cache);assert.deepEqual(glass.normalScale,source.normalScale);
 const porcelain=cloneSurfaceMaterial(glass,recipe({preset:'porcelain'}));assert.equal(porcelain.transmission,0);assert.equal(porcelain.clearcoat,1);
 const wood=cloneSurfaceMaterial(porcelain,recipe({preset:'oak'}));assert.ok(!wood.isMeshPhysicalMaterial);assert.ok(!('PHYSICAL' in wood.defines));assert.equal(source.roughness,.8);
});
test('only fully transmissive meshes skip ordinary opaque shadows',()=>{
 const geometry=new THREE.BoxGeometry(),glass=createSurfaceMaterial({},recipe({preset:'glass_clear'})),paint=createSurfaceMaterial({},recipe({preset:'wall_paint'}));
 const mesh=new THREE.Mesh(geometry,[glass,glass,glass,glass,glass,glass]);assert.equal(castsSurfaceShadow(mesh),false);
 mesh.material[3]=paint;assert.equal(castsSurfaceShadow(mesh),true);mesh.userData.browserEmitter=true;assert.equal(castsSurfaceShadow(mesh),false);
 geometry.dispose();glass.dispose();paint.dispose();
});

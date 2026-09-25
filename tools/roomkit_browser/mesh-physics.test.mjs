import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import * as CANNON from 'cannon-es';
import {createMeshBody} from './mesh-physics.js';
test('rotated zero-thickness decoration does not become a solid obstacle',()=>{
 const mesh=new THREE.Mesh(new THREE.PlaneGeometry(4,3));mesh.rotation.set(Math.PI/2,0,Math.PI/4);mesh.updateMatrixWorld(true);
 assert.equal(createMeshBody(mesh),null);
});
for(const reflected of [false,true])test(`rotated wall leaves adjacent floor clear (reflected=${reflected})`,()=>{
 const mesh=new THREE.Mesh(new THREE.BoxGeometry(4,.1,1));
 mesh.rotation.z=Math.PI/4;mesh.position.set(0,0,.5);mesh.scale.x=reflected?-1:1;mesh.updateMatrixWorld(true);
 const world=new CANNON.World({gravity:new CANNON.Vec3(0,0,-9.81)});
 world.addBody(createMeshBody(mesh));
 world.addBody(new CANNON.Body({mass:0,shape:new CANNON.Plane()}));
 const drop=(x,y)=>{const body=new CANNON.Body({mass:1,shape:new CANNON.Box(new CANNON.Vec3(.05,.05,.05)),position:new CANNON.Vec3(x,y,1.5)});world.addBody(body);return body;};
 const clear=drop(.9,-.9),supported=drop(0,0);
 for(let i=0;i<900;i++)world.step(1/120);
 assert.ok(Math.abs(clear.position.z-.05)<.005,`clear floor: ${clear.position.z}`);
 assert.ok(Math.abs(supported.position.z-1.05)<.005,`wall top: ${supported.position.z}`);
});
test('tapered solid does not support props in empty bounding-box corners',()=>{
 const mesh=new THREE.Mesh(new THREE.CylinderGeometry(.1,1,1,16));
 mesh.rotation.x=Math.PI/2;mesh.position.z=.5;mesh.updateMatrixWorld(true);
 const world=new CANNON.World({gravity:new CANNON.Vec3(0,0,-9.81)});
 world.addBody(createMeshBody(mesh));world.addBody(new CANNON.Body({mass:0,shape:new CANNON.Plane()}));
 const prop=new CANNON.Body({mass:1,shape:new CANNON.Box(new CANNON.Vec3(.04,.04,.04)),position:new CANNON.Vec3(.8,.8,1.5)});world.addBody(prop);
 for(let i=0;i<900;i++)world.step(1/120);
 assert.ok(Math.abs(prop.position.z-.04)<.005,`floor beside tapered base: ${prop.position.z}`);
});

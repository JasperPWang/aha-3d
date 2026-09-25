import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {selectionBounds,createSelectionBox} from './selection-box.js';
test('table selection follows authored yaw and stays tight after translation',()=>{
 const group=new THREE.Group();group.position.set(5,-3,.2);
 const top=new THREE.Mesh(new THREE.BoxGeometry(2,1,.1));top.rotation.z=-.48;top.position.z=.75;group.add(top);group.updateMatrixWorld(true);
 const result=selectionBounds([top]),size=result.box.getSize(new THREE.Vector3());
 assert.ok(size.distanceTo(new THREE.Vector3(2,1,.1))<1e-6);
 const line=createSelectionBox([top]),p=line.geometry.attributes.position,a=new THREE.Vector3().fromBufferAttribute(p,0),b=new THREE.Vector3().fromBufferAttribute(p,1);
 assert.ok(b.sub(a).normalize().distanceTo(new THREE.Vector3(Math.cos(-.48),Math.sin(-.48),0))<1e-6);
 const center=result.box.getCenter(new THREE.Vector3()).applyMatrix4(result.matrix);assert.ok(center.distanceTo(new THREE.Vector3(5,-3,.95))<1e-6);
});
test('compound cabinet box encloses its parts in one authored frame',()=>{
 const group=new THREE.Group();group.rotation.z=.6;group.position.set(-2,4,0);
 const main=new THREE.Mesh(new THREE.BoxGeometry(2,.5,.7));main.position.z=.45;group.add(main);
 const foot=new THREE.Mesh(new THREE.BoxGeometry(.1,.1,.2));foot.position.set(.8,.15,.1);group.add(foot);group.updateMatrixWorld(true);
 const result=selectionBounds([foot,main]),size=result.box.getSize(new THREE.Vector3());assert.ok(size.distanceTo(new THREE.Vector3(2,.5,.8))<1e-6);
 for(const mesh of [foot,main])for(let i=0;i<mesh.geometry.attributes.position.count;i++){
  const p=new THREE.Vector3().fromBufferAttribute(mesh.geometry.attributes.position,i).applyMatrix4(mesh.matrixWorld).applyMatrix4(result.matrix.clone().invert());
  assert.ok(result.box.clone().expandByScalar(1e-6).containsPoint(p));
 }
});
test('tumbling props use their live rigid-body frame',()=>{
 const group=new THREE.Group();group.rotation.set(.6,.3,-.8);const mesh=new THREE.Mesh(new THREE.BoxGeometry(.2,.3,.4));group.add(mesh);group.updateMatrixWorld(true);
 const b=selectionBounds([mesh],group);assert.ok(b.box.getSize(new THREE.Vector3()).distanceTo(new THREE.Vector3(.2,.3,.4))<1e-6);
});

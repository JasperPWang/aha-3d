import * as THREE from 'three';
import {obstacleBounds} from './collision-proxies.js';
import assert from 'node:assert/strict';
const wall=new THREE.Mesh(new THREE.BoxGeometry(8,.1,.4));wall.rotation.z=Math.PI/4;wall.position.set(0,3,.2);wall.updateMatrixWorld(true);
const free=new THREE.Box3(new THREE.Vector3(-.25,.25,0),new THREE.Vector3(.25,.75,.4));
assert.ok(new THREE.Box3().setFromObject(wall).intersectsBox(free),'Original world box falsely fills empty space');
assert.ok(obstacleBounds(wall).every(b=>!b.intersectsBox(free)),'Segmented bounds free empty floor');
const actual=new THREE.Box3(new THREE.Vector3(-.1,2.9,0),new THREE.Vector3(.1,3.1,.4));
assert.ok(obstacleBounds(wall).some(b=>b.intersectsBox(actual)),'Actual wall stays solid');
for(let x=-4;x<=4;x+=.05){const p=new THREE.Vector3(x,0,0).applyMatrix4(wall.matrixWorld);assert.ok(obstacleBounds(wall).some(b=>b.containsPoint(p)),'Wall extent stays covered');}
const before=obstacleBounds(wall);wall.position.x+=5;wall.updateMatrixWorld(true);const after=obstacleBounds(wall);assert.notEqual(before,after);assert.ok(after.every((b,i)=>Math.abs(b.min.x-before[i].min.x-5)<1e-8),'Moving object refreshes its collision bounds');
console.log('PASS: false diagonal obstruction cleared, real wall covered, moved obstacle bounds refreshed');

wall.geometry=new THREE.BoxGeometry(.2,.1,.4);const replaced=obstacleBounds(wall);assert.notEqual(replaced,after);assert.ok(replaced.length<after.length,'Replacement geometry refreshes proxy shapes');

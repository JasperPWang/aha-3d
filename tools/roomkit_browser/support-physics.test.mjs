import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as CANNON from 'cannon-es';
import {createSupportBody} from './support-physics.js';
for(const [x,y,z] of [[0,0,.7],[4,-3,-.5725],[-8,5,2.1]])test('Convex table support remains valid at '+[x,y,z],()=>{
 const s={min:[x-1,y-1,z-.06],max:[x+1,y+1,z],footprint:[[x,y-1],[x+1,y],[x,y+1],[x-1,y]]};
 const world=new CANNON.World({gravity:new CANNON.Vec3(0,0,-9.81)});world.solver.iterations=20;
 const support=createSupportBody(s),body=new CANNON.Body({mass:.1,shape:new CANNON.Box(new CANNON.Vec3(.04,.04,.04)),position:new CANNON.Vec3(x,y,z+.3)});world.addBody(support);world.addBody(body);
 for(let i=0;i<720;i++)world.step(1/120);
 body.updateAABB();assert.ok(Math.abs(body.aabb.lowerBound.z-z)<.005,JSON.stringify(body.position));assert.ok(body.velocity.length()<.01);
});

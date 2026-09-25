import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as C from 'cannon-es';
import {ActiveBodyBroadphase,installPerformanceBudget} from './performance-budget.js';
const box=(mass,x,y,z)=>new C.Body({mass,position:new C.Vec3(x,y,z),shape:new C.Box(new C.Vec3(.1,.1,.1))});
const pairs=(b,w)=>{const a=[],c=[];b.collisionPairs(w,a,c);return a.map((v,i)=>[v.id,c[i].id].sort((a,b)=>a-b).join(':')).sort();};
test('same overlapping pairs as exhaustive AABB broadphase, including masks, sleepers and moved statics',()=>{
 const w=new C.World(),actual=new ActiveBodyBroadphase(),reference=new C.NaiveBroadphase();reference.useBoundingBoxes=true;
 for(let i=0;i<80;i++){const b=box(i%3?1:0,(i%5)*.12,(i%4)*.1,(i%7)*.08);if(i%4===0)b.sleep();if(i%9===0)b.collisionFilterMask=0;w.addBody(b);}
 assert.deepEqual(pairs(actual,w),pairs(reference,w));
 w.bodies[0].position.set(.2,.2,.2);w.bodies[0].aabbNeedsUpdate=true;w.bodies[4].wakeUp();w.removeBody(w.bodies[6]);w.addBody(box(1,.1,.1,.1));
 assert.deepEqual(pairs(actual,w),pairs(reference,w));
 const bounds=new C.AABB({lowerBound:new C.Vec3(0,0,0),upperBound:new C.Vec3(.3,.3,.3)});
 assert.deepEqual(actual.aabbQuery(w,bounds).map(b=>b.id),reference.aabbQuery(w,bounds).map(b=>b.id));
});
test('static-heavy room avoids quadratic pair enumeration and skips sleeping pairs',()=>{
 const w=new C.World();for(let i=0;i<2000;i++)w.addBody(box(0,i,0,0));for(let i=0;i<8;i++)w.addBody(box(1,i,0,.15));
 const broad=new ActiveBodyBroadphase();pairs(broad,w);assert.equal(broad.lastChecks,16028);
 for(const b of w.bodies)if(b.mass)b.sleep();pairs(broad,w);assert.equal(broad.lastChecks,0);
});
test('stacked props settle on thin support without tunneling',()=>{
 const w=new C.World({gravity:new C.Vec3(0,0,-9.81),allowSleep:true});w.broadphase=new C.SAPBroadphase(w);installPerformanceBudget({tabletop:{world:w}});
 w.addBody(new C.Body({mass:0,shape:new C.Box(new C.Vec3(2,2,.004))}));
 const props=[box(1,0,0,.4),box(1,0,0,.65),box(1,0,0,.9)];for(const b of props)w.addBody(b);
 for(let i=0;i<1200;i++)w.step(1/120);
 for(let i=0;i<props.length;i++){assert(Math.abs(props[i].position.z-(.104+.2*i))<.025);assert(props[i].velocity.length()<.02);}
});

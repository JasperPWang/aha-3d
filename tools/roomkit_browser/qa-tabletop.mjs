import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {containsCircle} from './support-geometry.js';
import {generateLayout} from './seeded-layout.js';
const [html,out]=process.argv.slice(2),errors=[];
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:960}});
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(resolve(html)).href,{timeout:120000});
 await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});
 assert.equal(await page.locator('#error').textContent(),'');
 await page.click('#controls-tab');
 const spec=await page.evaluate(()=>{const s=roomkitQA.tabletop.spec;return {...s,templates:s.templates.map(({meshes,hull,...t})=>t)};});
 for(let seed=0;seed<200;seed++){
  const a=generateLayout(spec,String(seed));assert.deepEqual(a,generateLayout(spec,String(seed)));
  assert.ok(a.placements.length>0,'At least one complete object fits every tested seed');
  for(const p of a.placements){
   const t=spec.templates.find(t=>t.id===p.template),s=spec.supports.find(s=>s.id===p.support),r=Math.hypot(t.size[0],t.size[1])/2;
   assert.ok(containsCircle(s,p.position[0],p.position[1],r));
   assert.ok(p.position[0]-r>s.min[0]&&p.position[0]+r<s.max[0]);
   assert.ok(p.position[1]-r>s.min[1]&&p.position[1]+r<s.max[1]);
   for(const q of a.placements)if(p!==q&&p.support===q.support){const u=spec.templates.find(t=>t.id===q.template);assert.ok(Math.hypot(p.position[0]-q.position[0],p.position[1]-q.position[1])>r+Math.hypot(u.size[0],u.size[1])/2);}
  }
 }
 const original=await page.evaluate(()=>roomkitQA.tabletop.layout);
 const originalSettled=await page.evaluate(()=>{roomkitQA.tabletop.advance(720);return roomkitQA.tabletop.snapshot().map(o=>{const e=roomkitQA.tabletop.entries.get(o.id);e.body.updateAABB();return {...o,convexBottom:e.body.aabb.lowerBound.z};});});
 for(const o of originalSettled){
  assert.ok([...o.position,...o.quaternion,o.convexBottom,o.velocity].every(Number.isFinite));
  assert.ok(o.velocity<.1,'Original bodies settle: '+JSON.stringify(o));
  const support=spec.supports.find(s=>s.id===original.placements.find(p=>p.id===o.id).support);
  assert.ok(o.convexBottom>=support.max[2]-.025,'Original object keeps table support: '+JSON.stringify(o));
 }
 const originalUpright=originalSettled.every(o=>Math.hypot(o.quaternion[0],o.quaternion[1])<.14);
 console.log('200 seeds passed');await page.screenshot({timeout:120000,path:resolve(out,'tabletop-original.png')});
 await page.click('#physics-pause');
 await page.fill('#seed','dining-28');await page.click('#apply-seed');
 const initial=await page.evaluate(()=>({layout:roomkitQA.tabletop.layout,snapshot:roomkitQA.tabletop.snapshot(),bodies:roomkitQA.tabletop.world.bodies.length}));
 assert.ok(new Set(initial.snapshot.map(s=>s.asset)).size>=2,'Seed changes object types');
 const settled=await page.evaluate(()=>{const t=roomkitQA.tabletop,start=performance.now();t.advance(720);return {objects:t.snapshot().map(o=>{const e=t.entries.get(o.id);e.body.updateAABB();return {...o,convexBottom:e.body.aabb.lowerBound.z};}),contacts:t.contacts,solverMilliseconds:performance.now()-start};});
 console.log('Settled',JSON.stringify(settled));assert.ok(settled.contacts>0);
 for(const o of settled.objects){
  assert.ok(o.position.every(Number.isFinite));assert.ok(o.velocity<.15,'Bodies settle: '+JSON.stringify(o));
  const support=spec.supports.find(s=>s.id===initial.layout.placements.find(p=>p.id===o.id).support);
  assert.ok(o.convexBottom>=support.max[2]-.025,'No tabletop tunnelling: '+JSON.stringify({id:o.id,bottom:o.convexBottom,top:support.max[2]}));
 }
 await page.screenshot({timeout:120000,path:resolve(out,'tabletop-seeded.png')});
 await page.click('#nudge-table');
 const nudged=await page.evaluate(()=>{roomkitQA.tabletop.advance(120);return roomkitQA.tabletop.snapshot();});
 assert.ok(nudged.some((o,i)=>Math.hypot(o.position[0]-settled.objects[i].position[0],o.position[1]-settled.objects[i].position[1])>.015),'Nudge creates physical motion');
 await page.click('#reset-table');
 assert.deepEqual(await page.evaluate(()=>roomkitQA.tabletop.snapshot().map(x=>x.position)),initial.snapshot.map(x=>x.position));
 await page.click('#swap-all');const randomLayout=await page.evaluate(()=>roomkitQA.tabletop.layout);assert.notDeepEqual(randomLayout,initial.layout);
 await page.fill('#seed','dining-28');await page.click('#apply-seed');
 assert.deepEqual(await page.evaluate(()=>roomkitQA.tabletop.layout),initial.layout);
 for(let i=0;i<12;i++)await page.click('#apply-seed');
 assert.equal(await page.evaluate(()=>roomkitQA.tabletop.world.bodies.length),initial.bodies,'Swaps remove old collision bodies');
 assert.equal(await page.evaluate(()=>roomkitQA.pickables.filter(m=>m.userData.tabletop).length),await page.evaluate(()=>[...roomkitQA.tabletop.entries.values()].reduce((n,e)=>n+e.group.children.length,0)),'No stale pickable meshes');
 const frozen=await page.evaluate(()=>roomkitQA.tabletop.snapshot());await page.waitForTimeout(400);assert.deepEqual(await page.evaluate(()=>roomkitQA.tabletop.snapshot()),frozen,'Pause stops physics');
 await page.evaluate(()=>roomkitQA.tabletop.advance(720));await page.click('#physics-pause');await page.click('#table-view');await page.waitForTimeout(700);
 // Real canvas pick, lift, drag, release. Choose a visible generated object.
 const targets=await page.evaluate(()=>{const q=roomkitQA,r=q.renderer.domElement.getBoundingClientRect();q.scene.updateMatrixWorld(true);q.camera.updateMatrixWorld(true);return [...q.tabletop.entries.values()].flatMap(e=>e.group.children.map(m=>{const p=m.geometry.boundingSphere.center.clone().applyMatrix4(m.matrixWorld).project(q.camera);return {id:e.id,x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2};}));});
 let target,heldStart;
 for(const p of targets){
  if(p.x<90||p.x>1100||p.y<100||p.y>850)continue;
  heldStart=await page.evaluate(id=>roomkitQA.tabletop.entries.get(id).body.position.toArray(),p.id);
  await page.mouse.move(p.x,p.y);await page.mouse.down();
  await page.waitForFunction(id=>roomkitQA.dragging&&roomkitQA.selected===id,p.id,{timeout:5000}).catch(()=>{});
  if(await page.evaluate(id=>roomkitQA.dragging&&roomkitQA.selected===id,p.id)){target=p;break;}await page.mouse.up();
 }
 assert.ok(target,'Canvas pointer selects a physical object');
 await page.waitForFunction(({id,z})=>roomkitQA.tabletop.entries.get(id).body.position.z>z+.1,{id:target.id,z:heldStart[2]},{timeout:30000});
 await page.screenshot({timeout:120000,path:resolve(out,'tabletop-held.png')});
 await page.mouse.move(target.x+20,target.y+8,{steps:8});await page.mouse.up();
 await page.waitForFunction(({id,z})=>{const b=roomkitQA.tabletop.entries.get(id).body;return b.velocity.length()<.1&&b.position.z<z+.08;},{id:target.id,z:heldStart[2]},{timeout:30000});
 const released=await page.evaluate(id=>roomkitQA.tabletop.entries.get(id).body.position.toArray(),target.id);
 assert.ok(released[2]<heldStart[2]+.08,'Released object falls back');
 // Drop a body just beyond the table edge and run the same solver to the floor.
 await page.click('#physics-pause');
 const floorDrop=await page.evaluate(()=>{
  const q=roomkitQA,t=q.tabletop,e=[...t.entries.values()].find(e=>e.template.size[2]<.25)||[...t.entries.values()][0];
  const radius=Math.hypot(e.template.size[0],e.template.size[1])/2+.08;
  const inside=(s,x,y)=>s.footprint.every((a,i)=>{const b=s.footprint[(i+1)%s.footprint.length];return ((b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0]))/Math.hypot(b[0]-a[0],b[1]-a[1])>=radius;});
  let target;
  for(const floor of t.spec.floors||[]){
   for(let x=floor.min[0]+radius;x<floor.max[0]-radius&&!target;x+=.3)for(let y=floor.min[1]+radius;y<floor.max[1]-radius&&!target;y+=.3){
    if(!inside(floor,x,y))continue;
    const blocked=t.world.bodies.some(b=>{if(b===e.body)return false;b.updateAABB();const a=b.aabb;return a.upperBound.z>floor.max[2]+.04&&a.lowerBound.z<floor.max[2]+1&&x+radius>a.lowerBound.x&&x-radius<a.upperBound.x&&y+radius>a.lowerBound.y&&y-radius<a.upperBound.y;});
    if(!blocked)target={x,y,z:floor.max[2],mesh:floor.mesh};
   }
   if(target)break;
  }
  if(!target)throw Error('No verified free source floor patch for drop test');
  e.body.position.set(target.x,target.y,target.z+.65);e.body.velocity.setZero();e.body.wakeUp();e.body.aabbNeedsUpdate=true;t.advance(1200);
  q.scene.updateMatrixWorld(true);return {position:e.body.position.toArray(),bottom:q.bounds(e.id).min.z,speed:e.body.velocity.length(),floor:target};
 });
 assert.ok(Math.abs(floorDrop.bottom-floorDrop.floor.z)<.035,'Object falls onto the actual source floor');
 assert.ok(floorDrop.speed<.15);
 // A controlled pair collision verifies momentum transfer between two props.
 const collisionSeed=Array.from({length:200},(_,i)=>String(i)).find(seed=>spec.templates.some(t=>t.library_sha256&&generateLayout(spec,seed).placements.filter(p=>p.template===t.id).length>=2));
 assert.ok(collisionSeed,'At least one tested layout supplies two copies of a fitting registered prop');
 await page.fill('#seed',collisionSeed);await page.click('#apply-seed');
 const collision=await page.evaluate(()=>{
  const t=roomkitQA.tabletop,entries=[...t.entries.values()],template=t.spec.templates.find(t=>t.library_sha256&&entries.filter(e=>e.template.id===t.id).length>=2),pair=entries.filter(e=>e.template.id===template?.id).slice(0,2);
  if(pair.length!==2)throw Error('Collision seed must supply two matching registered props');
  for(const e of t.entries.values())if(!pair.includes(e)){e.body.position.set(20,20,30);e.body.sleep();}
  // Same exported convex bodies, isolated above scene geometry; source floor and
  // support contacts are independently tested above. Zero gravity isolates impulse transfer.
  t.world.gravity.set(0,0,0);
  const width=(pair[0].template.size[0]+pair[1].template.size[0])/2+.03;
  for(let i=0;i<2;i++){const e=pair[i];e.body.position.set(i*width,0,30);e.body.quaternion.set(0,0,0,1);e.body.velocity.setZero();e.body.wakeUp();e.body.aabbNeedsUpdate=true;}
  let hits=0,peakSpeed=0;pair[0].body.addEventListener('collide',event=>{if(event.body===pair[1].body)hits++;});
  pair[0].body.velocity.x=1.5;
  for(let i=0;i<120;i++){t.advance(1);peakSpeed=Math.max(peakSpeed,Math.abs(pair[1].body.velocity.x));}
  t.world.gravity.set(0,0,-9.81);return {hits,peakSpeed};
 });
 console.log('Pair collision',JSON.stringify(collision));assert.ok(collision.hits>0&&collision.peakSpeed>.05,'Prop collision transfers momentum: '+JSON.stringify(collision));
 await page.click('#original-table');assert.deepEqual(await page.evaluate(()=>roomkitQA.tabletop.layout),original);
 await page.click('#reset-layout');assert.deepEqual(await page.evaluate(()=>roomkitQA.tabletop.layout),original);
 await page.fill('#seed','dining-28');await page.click('#apply-seed');await page.click('#table-view');
 await page.evaluate(()=>document.querySelector('aside').scrollTop=0);await page.screenshot({timeout:120000,path:resolve(out,'tabletop-final.png')});
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({timeout:120000,path:resolve(out,'tabletop-mobile.png'),fullPage:true});
 assert.deepEqual(errors,[]);
 await writeFile(resolve(out,'tabletop-validation.json'),JSON.stringify({passed:true,engine:'cannon-es 0.20.0',seedsChecked:200,seed:initial.layout.seed,generatedObjects:initial.snapshot.length,contacts:settled.contacts,solverMillisecondsForSixSeconds:settled.solverMilliseconds,originalUpright,originalSettled,originalSupported:true,seedReproducible:true,repeatSwaps:12,pause:true,pointerLiftDrop:true,originalRestored:true,floorDrop,collision,errors},null,2));
 console.log('Tabletop physics and seeded swap validation passed');
}finally{await browser.close();}

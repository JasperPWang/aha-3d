import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
const [url,out]=process.argv.slice(2);await mkdir(out,{recursive:true});
const report={url,errors:[]},browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1100,height:760}});page.on('pageerror',e=>report.errors.push(e.message));
 await page.goto(url,{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>document.getElementById('reset-scene'),null,{timeout:120000});
 await page.evaluate(()=>{const q=roomkitQA;window.draw=q.renderer.render.bind(q.renderer);q.renderer.render=()=>{};});
 const snapshot=()=>page.evaluate(()=>roomkitQA.tabletop.snapshot());
 report.initial=await snapshot();
 report.geometry=await page.evaluate(()=>{
  const q=roomkitQA,box=id=>{const b=q.bounds(id);return {min:b.min.toArray(),max:b.max.toArray()};};
  return {basket:box('fruit_basket'),tray:box('serving_tray'),bowls:['bowl_1','bowl_2','bowl_3'].map(box),basketMeshes:q.pickables.filter(m=>m.userData.owner==='fruit_basket').map(m=>m.name),tiers:q.tabletop.entries.get('fruit_basket').template.collision.tiers};
 });
 assert(report.geometry.basket.max[1]<report.geometry.tray.min[1]-.02);
 assert(report.geometry.bowls.every(b=>b.min[2]>=report.geometry.tray.max[2]));
 assert(report.geometry.basketMeshes.some(n=>n.includes('central support')));
 assert.equal(report.geometry.basketMeshes.filter(n=>n.includes('solid base')).length,2);
 await page.evaluate(()=>{document.getElementById('table-view').click();draw(roomkitQA.scene,roomkitQA.camera);});await page.screenshot({path:out+'/initial.png'});
 await page.check('#enable-physics');await page.evaluate(()=>{roomkitQA.tabletop.paused=true;roomkitQA.tabletop.advance(1200);});
 report.settled=await snapshot();
 const basket=report.settled.find(e=>e.id==='fruit_basket');
 for(const fruit of report.settled.filter(e=>e.id.includes(':fruit:'))){const initial=report.initial.find(e=>e.id===fruit.id);assert(Math.abs(fruit.position[2]-initial.position[2])<.025,fruit.id+' left its tier');assert(Math.hypot(fruit.position[0]-basket.position[0],fruit.position[1]-basket.position[1])<.18);assert(fruit.velocity<.1);}
 assert(Math.hypot(...basket.position.map((x,i)=>x-report.initial.find(e=>e.id==='fruit_basket').position[i]))<.015);
 await page.evaluate(()=>draw(roomkitQA.scene,roomkitQA.camera));await page.screenshot({path:out+'/settled.png'});
 await page.evaluate(()=>{const q=roomkitQA,c=q.tabletop.entries.get('fruit_basket').group.position;q.controls.minDistance=.1;q.controls.target.copy(c);q.camera.position.set(c.x-.5,c.y+.8,c.z+.38);q.camera.fov=40;q.camera.updateProjectionMatrix();q.controls.update();draw(q.scene,q.camera);});await page.screenshot({path:out+'/basket-closeup.png'});
 await page.evaluate(()=>{roomkitQA.controls.minDistance=2;});
 // Change geometry, materials, doors, furniture and lights, then reset them together.
 await page.click('#reset-scene');assert.deepEqual(await snapshot(),report.initial);
 await page.selectOption('#prop-object','bowl_1');await page.selectOption('#prop-asset','browser-template-3');await page.click('#replace-prop');await page.waitForFunction(()=>roomkitQA.tabletop.entries.get('bowl_1').template.id==='browser-template-3');
 await page.evaluate(()=>{const q=roomkitQA;q.placements.get('dining_chair_0').position.x+=.2;document.getElementById('objects').value='kitchen_island';document.getElementById('objects').dispatchEvent(new Event('change'));document.getElementById('material-apply').click();document.getElementById('open-all').click();q.lighting.lamps(false);});
 assert(await page.evaluate(()=>roomkitQA.materialLab.overrideCount>0));
 await page.check('#enable-physics');await page.click('#physics-nudge');await page.click('#reset-scene');
 assert.deepEqual(await snapshot(),report.initial);
 assert(await page.evaluate(()=>{const q=roomkitQA;return q.tabletop.paused&&q.materialLab.overrideCount===0&&q.placements.get('dining_chair_0').position.length()===0&&[...q.joints.values()].every(j=>j.value===0&&j.target===0)&&q.lighting.lights.filter(l=>l.userData.lamp).every(l=>l.intensity>0);}));
 report.reset=true;
 // A replacement vase can be picked up, carried off the island and dropped.
 await page.selectOption('#prop-object','bowl_1');await page.selectOption('#prop-asset','browser-template-3');await page.click('#replace-prop');await page.waitForFunction(()=>roomkitQA.tabletop.entries.get('bowl_1').template.id==='browser-template-3');
 await page.check('#enable-physics');
 const points=await page.evaluate(()=>{const q=roomkitQA,c=q.tabletop.entries.get('bowl_1').group.position.clone();ROOMKIT_SCENE.views.orbit={position:[c.x,c.y+3,3.5],target:[c.x,c.y,1],fov:55};document.getElementById('orbit').click();q.camera.updateMatrixWorld(true);const r=q.renderer.domElement.getBoundingClientRect(),project=v=>{const p=v.project(q.camera);return {x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2};};return {from:project(c.clone()),to:project(c.clone().setY(2.2))};});
 await page.mouse.move(points.from.x,points.from.y);await page.mouse.down();await page.waitForTimeout(250);assert.equal(await page.evaluate(()=>roomkitQA.selected),'bowl_1');assert(await page.evaluate(()=>roomkitQA.dragging));
 await page.mouse.move(points.to.x,points.to.y,{steps:15});await page.waitForTimeout(600);await page.mouse.up();await page.evaluate(()=>{roomkitQA.tabletop.paused=true;roomkitQA.tabletop.advance(900);});
 report.vaseDrop=(await snapshot()).find(e=>e.id==='bowl_1');assert(report.vaseDrop.position[1]>1.8);assert(report.vaseDrop.position[2]<.6);assert(report.vaseDrop.position[2]>-.1);
 await page.click('#reset-scene');assert.deepEqual(await snapshot(),report.initial);
 // Pointer movement of ordinary furniture uses support bounds only with physics off.
 async function dragChair(enabled){
  await page.click('#reset-scene');if(enabled)await page.check('#enable-physics');
  const p=await page.evaluate(()=>{const q=roomkitQA,b=q.bounds('dining_chair_0'),c=b.getCenter(q.camera.position.clone());ROOMKIT_SCENE.views.orbit={position:[c.x,c.y,c.z+5],target:c.toArray(),fov:55};document.getElementById('orbit').click();q.controls.maxPolarAngle=Math.PI/2;q.camera.updateMatrixWorld(true);const r=q.renderer.domElement.getBoundingClientRect(),project=v=>{v.project(q.camera);return {x:r.left+(v.x+1)*r.width/2,y:r.top+(1-v.y)*r.height/2};};return {...project(c.clone()),to:project(c.clone().setY(2.35))};});
  await page.mouse.move(p.x,p.y);await page.mouse.down();await page.waitForTimeout(250);assert.equal(await page.evaluate(()=>roomkitQA.selected),'dining_chair_0');
  await page.mouse.move(p.to.x,p.to.y,{steps:15});await page.waitForTimeout(200);await page.mouse.up();await page.waitForTimeout(300);
  return page.evaluate(()=>{const q=roomkitQA,b=q.bounds('dining_chair_0'),r=q.bounds('rug');return {min:b.min.toArray(),max:b.max.toArray(),rugMin:r.min.toArray(),rugMax:r.max.toArray()};});
 }
 report.chairPaused=await dragChair(false);report.chairEnabled=await dragChair(true);
 assert(report.chairPaused.min[1]>=report.chairPaused.rugMin[1]-.005);
 assert(report.chairEnabled.min[1]<report.chairEnabled.rugMin[1]-.05);
 await page.click('#reset-scene');await page.setViewportSize({width:390,height:620});await page.evaluate(()=>draw(roomkitQA.scene,roomkitQA.camera));await page.screenshot({path:out+'/mobile.png'});
 assert(await page.locator('#reset-scene').isVisible());assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(report.errors,[]);
 report.passed=true;console.log('PASS basket retention, clear placement, reset, vase fall and support-boundary dragging');
}finally{await writeFile(out+'/validation.json',JSON.stringify(report,null,2));await browser.close();}

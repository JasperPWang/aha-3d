import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {writeFile,mkdir} from 'node:fs/promises';
const [url,out]=process.argv.slice(2);await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const checks={url,errors:[]};
try{
 const page=await browser.newPage({viewport:{width:1060,height:700}});page.on('pageerror',e=>checks.errors.push(e.message));
 await page.goto(url,{waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>document.querySelector('#enable-physics'),null,{timeout:120000});
 await page.evaluate(()=>{const q=roomkitQA;window.draw=q.renderer.render.bind(q.renderer);q.renderer.render=()=>{};});
 assert.equal(await page.isChecked('#enable-physics'),false);
 assert.equal(await page.evaluate(()=>roomkitQA.tabletop.paused),true);
 assert.equal(await page.evaluate(()=>document.querySelector('#editor-panel').firstElementChild.id),'demo-physics');
 checks.initial=await page.evaluate(()=>roomkitQA.tabletop.snapshot());assert.equal(checks.initial.length,19);
 checks.fruits=checks.initial.filter(e=>e.id.includes(':fruit:'));assert.equal(checks.fruits.length,14);
 assert(await page.evaluate(()=>new Set([...roomkitQA.tabletop.entries.values()].map(e=>e.body)).size===19));
 assert(await page.evaluate(()=>roomkitQA.tabletop.entries.get('fruit_basket').body.shapes.length>2));
 await page.click('#quick-layout');checks.layout=await page.evaluate(()=>roomkitQA.tabletop.snapshot());assert.notDeepEqual(checks.layout,checks.initial);
 await page.click('#quick-restore');assert.deepEqual(await page.evaluate(()=>roomkitQA.tabletop.snapshot()),checks.initial);
 await page.selectOption('#prop-object','bowl_1');await page.selectOption('#prop-asset','browser-template-3');await page.click('#replace-prop');
 await page.waitForFunction(()=>roomkitQA.tabletop.entries.get('bowl_1').template.id==='browser-template-3');
 checks.replaced=await page.evaluate(()=>roomkitQA.tabletop.snapshot());assert.equal(checks.replaced.length,19);
 assert(checks.replaced.find(x=>x.id==='bowl_1').asset.includes('porcelain-vase'));
 assert.deepEqual(checks.replaced.filter(x=>x.id!=='bowl_1'),checks.initial.filter(x=>x.id!=='bowl_1'));
 checks.library=[];
 for(const template of await page.locator('#prop-asset option').evaluateAll(options=>options.map(o=>o.value))){
  await page.click('#quick-restore');await page.selectOption('#prop-object','fruit_basket');await page.selectOption('#prop-asset',template);await page.click('#replace-prop');
  await page.waitForFunction(id=>roomkitQA.tabletop.entries.get('fruit_basket').template.id===id,template);
  checks.library.push(await page.evaluate(()=>roomkitQA.tabletop.snapshot().find(e=>e.id==='fruit_basket').asset));
 }
 await page.click('#quick-restore');await page.check('#enable-physics');
 assert.equal(await page.evaluate(()=>roomkitQA.tabletop.paused),false);
 await page.click('#physics-nudge');checks.nudge=await page.evaluate(()=>roomkitQA.tabletop.snapshot());assert(checks.nudge.some(x=>x.velocity>.01));
 await page.uncheck('#enable-physics');await page.click('#quick-restore');await page.check('#enable-physics');
 // Real pointer hold and release across the table edge, then solver contacts.
 const dropId='fruit_basket:fruit:10';
 const point=await page.evaluate(id=>{const q=roomkitQA,e=q.tabletop.entries.get(id),c=e.group.position.clone();ROOMKIT_SCENE.views.orbit={position:[c.x,c.y+3,3.2],target:[c.x,c.y,1],fov:55};document.getElementById('orbit').click();q.scene.updateMatrixWorld(true);q.camera.updateMatrixWorld(true);const p=c.project(q.camera),r=q.renderer.domElement.getBoundingClientRect();return {x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2};},dropId);
 await page.mouse.move(point.x,point.y);await page.mouse.down();await page.waitForTimeout(250);
 assert.equal(await page.evaluate(()=>roomkitQA.selected),dropId);assert(await page.evaluate(()=>roomkitQA.dragging));
 await page.mouse.move(point.x+190,point.y+70,{steps:12});await page.waitForTimeout(350);await page.mouse.up();
 await page.evaluate(()=>{roomkitQA.tabletop.paused=true;roomkitQA.tabletop.advance(600);});
 checks.drop=await page.evaluate(()=>roomkitQA.tabletop.snapshot());console.log('drop',checks.drop);
 const dropped=checks.drop.find(x=>x.id===dropId);assert(dropped.position[2]<checks.initial.find(x=>x.id===dropId).position[2]-.2);
 assert(checks.drop.filter(e=>e.id.includes(':fruit:')&&e.id!==dropId).some(e=>e.position[2]>.9));
 assert(checks.drop.every(e=>e.position[2]>-1&&e.velocity<5));
 assert(dropped.position.every(Number.isFinite));assert(dropped.position[2]>-1);
 await page.click('#quick-restore');
 // Each fixture changes only its own light and its emitter materials.
 checks.fixtures=await page.evaluate(()=>roomkitQA.lighting.lights.filter(l=>l.userData.lamp).map(l=>({id:l.userData.id,intensity:l.intensity})));
 await page.locator('#fixture-switches summary').click();
 for(const fixture of checks.fixtures){
  await page.uncheck(`[data-fixture="${fixture.id}"]`);
  const state=await page.evaluate(()=>roomkitQA.lighting.lights.filter(l=>l.userData.lamp).map(l=>({id:l.userData.id,intensity:l.intensity})));
  assert.equal(state.find(l=>l.id===fixture.id).intensity,0);
  assert.deepEqual(state.filter(l=>l.id!==fixture.id),checks.fixtures.filter(l=>l.id!==fixture.id));
  await page.check(`[data-fixture="${fixture.id}"]`);
 }
 // Direct fixture hit uses the same state as its individual checkbox.
 const target=await page.evaluate(()=>{const q=roomkitQA,l=q.lighting.lights.find(l=>l.userData.owner==='living_lamp_0'),m=q.pickables.find(m=>l.userData.emitter_meshes.includes(m.name));q.scene.updateMatrixWorld(true);m.geometry.computeBoundingBox();const c=m.geometry.boundingBox.getCenter(q.camera.position.clone()).applyMatrix4(m.matrixWorld);ROOMKIT_SCENE.views.orbit={position:[c.x,c.y+2.3,c.z+.25],target:c.toArray(),fov:45};document.getElementById('orbit').click();q.camera.updateMatrixWorld(true);const p=c.project(q.camera),r=q.renderer.domElement.getBoundingClientRect();return {id:l.userData.id,x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2};});
 await page.mouse.click(target.x,target.y);assert.equal(await page.isChecked(`[data-fixture="${target.id}"]`),false);await page.mouse.click(target.x,target.y);assert.equal(await page.isChecked(`[data-fixture="${target.id}"]`),true);
 checks.directLampClick=true;
 await page.click('#lamps');assert(await page.evaluate(()=>roomkitQA.lighting.lights.filter(l=>l.userData.lamp).every(l=>l.intensity===0)));await page.click('#lamps');
 await page.evaluate(()=>{document.getElementById('open-all').click();});await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===1));checks.joints=await page.evaluate(()=>roomkitQA.joints.size);
 await page.evaluate(()=>{document.getElementById('close-all').click();});await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===0));
 await page.evaluate(()=>{document.getElementById('table-view').click();document.getElementById('editor-panel').scrollTop=0;draw(roomkitQA.scene,roomkitQA.camera);});
 await page.screenshot({path:out+'/desktop.png',timeout:120000});
 checks.pixels=await page.evaluate(()=>{const q=roomkitQA,gl=q.renderer.getContext(),pixel=new Uint8Array(4),colors=new Set();for(let x=100;x<gl.drawingBufferWidth;x+=90)for(let y=60;y<gl.drawingBufferHeight;y+=70){gl.readPixels(x,y,1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);colors.add([...pixel].join(','));}return colors.size;});assert(checks.pixels>8);
 await page.setViewportSize({width:390,height:620});await page.waitForTimeout(200);await page.evaluate(()=>draw(roomkitQA.scene,roomkitQA.camera));await page.screenshot({path:out+'/mobile.png',timeout:120000});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert(await page.locator('#enable-physics').isVisible());
 assert.deepEqual(checks.errors,[]);checks.passed=true;await writeFile(out+'/validation.json',JSON.stringify(checks,null,2));console.log('PASS physics, replacements, individual lamps, doors, responsive layout and rendered pixels');
}finally{await browser.close();}

import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html,out]=process.argv.slice(2);
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:1440,height:960}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto(pathToFileURL(resolve(html)).href,{timeout:120000});await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});await page.click('#plan');await page.waitForTimeout(500);
 const sweep=await page.evaluate(()=>{
  const q=roomkitQA;q.pickables[0].geometry.computeBoundingBox();const v=q.camera.position.clone(),b=q.pickables[0].geometry.boundingBox.clone();b.min.set(0,0,0);b.max.set(1,1,1);const o=b.clone();o.min.set(2,-1,0);o.max.set(3,3,2);
  const forward=q.constrain(b.clone(),v.set(100,.4,0),[o]).toArray();
  const reverseBox=b.clone();reverseBox.translate(v.set(4,0,0));const reverse=q.constrain(reverseBox,v.set(-100,0,0),[o]).toArray();
  const floor=b.clone();floor.min.set(-100,-100,-.2);floor.max.set(100,100,0);const ground=q.constrain(b.clone(),v.set(2,0,0),[floor]).toArray();return {forward,reverse,ground};
 });
 assert.ok(sweep.forward[0]>.99&&sweep.forward[0]<1);assert.equal(sweep.forward[1],.4);assert.ok(sweep.reverse[0]<-.99&&sweep.reverse[0]>-1);assert.equal(sweep.ground[0],2);
 const id='lounge-chair-a';
 const targets=await page.evaluate(id=>{const q=roomkitQA,r=q.renderer.domElement.getBoundingClientRect();return q.pickables.filter(m=>m.userData.owner===id).map(m=>{const p=m.geometry.boundingSphere.center.clone().applyMatrix4(m.matrixWorld).project(q.camera);return {x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2};});},id);
 let target;
 for(const p of targets){await page.mouse.move(p.x,p.y);await page.mouse.down();await page.waitForTimeout(400);if(await page.evaluate(()=>roomkitQA.dragging&&roomkitQA.selected==='lounge-chair-a')){target=p;break;}await page.mouse.up();}
 assert.ok(target,'Actual pointer picks chair');
 assert.ok(await page.evaluate(()=>roomkitQA.placements.get('lounge-chair-a').position.z)>.1,'Held chair lifts');
 await page.screenshot({path:resolve(out,'chair-held.png')});
 await page.mouse.move(target.x-45,target.y+20,{steps:12});await page.mouse.up();await page.waitForFunction(()=>roomkitQA.placements.get('lounge-chair-a').position.z===0,{},{timeout:15000});
 const moved=await page.evaluate(()=>roomkitQA.placements.get('lounge-chair-a').position.toArray());assert.equal(moved[2],0);assert.ok(Math.hypot(...moved)>.01,'Chair drags');
 await page.click('#reset-layout');await page.waitForTimeout(100);
 await page.mouse.move(target.x,target.y);await page.mouse.down();await page.waitForTimeout(300);await page.mouse.move(target.x-20,target.y+20);await page.keyboard.press('Escape');await page.mouse.up();assert.deepEqual(await page.evaluate(()=>roomkitQA.placements.get('lounge-chair-a').position.toArray()),[0,0,0]);
 await page.mouse.click(target.x,target.y);await page.waitForTimeout(300);assert.deepEqual(await page.evaluate(()=>roomkitQA.placements.get('lounge-chair-a').position.toArray()),[0,0,0],'Quick click does not move');
 assert.deepEqual(errors,[]);await writeFile(resolve(out,'grab-validation.json'),JSON.stringify({passed:true,sweep,moved,hold_lifts:true,release_lands:true,escape_restores:true,quick_click_selects:true,errors},null,2));
 console.log('Grab QA passed');
}finally{await browser.close();}

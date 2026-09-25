import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html,out]=process.argv.slice(2);
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:1440,height:960}}),errors=[],requests=[];
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().startsWith('http'))requests.push(r.url());});
try{
 await page.goto(pathToFileURL(resolve(html)).href,{timeout:120000});await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});await page.waitForTimeout(700);
 const info=await page.evaluate(()=>({objects:ROOMKIT_SCENE.objects.length,joints:roomkitQA.joints.size,meshes:roomkitQA.pickables.length,frames:ROOMKIT_SCENE.animation.frames,fps:ROOMKIT_SCENE.animation.fps,duration:ROOMKIT_SCENE.animation.duration_seconds,actors:roomkitQA.actors.length}));
 assert.equal(info.frames,120);assert.equal(info.fps,24);assert.equal(info.duration,5);assert.equal(info.actors,1);assert.equal(info.joints,35);
 assert.equal(await page.locator('#error').textContent(),'');
 // Exercise the actual timeline control for every source frame, comparing all
 // submitted vertex positions to Blender's per-frame world-coordinate hash.
 const hashes=await page.evaluate(async()=>{
  const result=[];
  for(let frame=0;frame<ROOMKIT_SCENE.animation.frames;frame++){
   const slider=document.getElementById('timeline');slider.value=frame;slider.dispatchEvent(new Event('input',{bubbles:true}));
   const actor=roomkitQA.actors[0],array=actor.mesh.geometry.attributes.position.array;
   const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',array.buffer))].map(x=>x.toString(16).padStart(2,'0')).join('');
   const box=actor.mesh.geometry.boundingBox,expected=actor.bounds[frame];
   const boundsMatch=box&&box.min.toArray().every((v,k)=>Math.abs(v-expected[0][k])<1e-6)&&box.max.toArray().every((v,k)=>Math.abs(v-expected[1][k])<1e-6);
   result.push({frame:frame+1,match:hash===actor.checks[frame].sha256,boundsMatch,hash});
  }
  return result;
 });
 assert.ok(hashes.every(x=>x.match),'Every displayed frame matches Blender positions');
 assert.ok(hashes.every(x=>x.boundsMatch),'Selection bounds follow the animated body');
 assert.notEqual(hashes[0].hash,hashes[119].hash,'Motion is not frozen');
 for(const frame of [0,59,119]){
  await page.locator('#timeline').fill(String(frame));await page.waitForTimeout(250);await page.screenshot({path:resolve(out,`human-${frame+1}.png`)});
 }
 await page.click('#restart');const start=Date.now();await page.click('#play');await page.waitForFunction(()=>roomkitQA.shownFrame>0);await page.waitForFunction(()=>!roomkitQA.playing,{},{timeout:12000});
 const elapsed=Date.now()-start;assert.ok(elapsed>=4500&&elapsed<9000,'Playback follows five-second duration');assert.equal(await page.evaluate(()=>roomkitQA.shownFrame),119);
 await page.click('#restart');await page.click('#play');await page.waitForTimeout(500);await page.click('#play');const paused=await page.evaluate(()=>roomkitQA.shownFrame);await page.waitForTimeout(350);assert.equal(await page.evaluate(()=>roomkitQA.shownFrame),paused,'Pause holds pose');
 await page.click('#open-all');await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===1));
 const joints=await page.evaluate(()=>[...roomkitQA.joints.values()].map(j=>({id:j.id,translation:j.a.p.distanceTo(j.group.position),angle:j.a.q.angleTo(j.group.quaternion)})));
 assert.ok(joints.every(j=>j.translation>.05||j.angle>.1),'Every legacy cabinet joint actually moves');
 await page.locator('#timeline').fill('59');await page.screenshot({path:resolve(out,'human-cabinets-open.png')});
 await page.click('#plan');await page.waitForTimeout(300);await page.screenshot({path:resolve(out,'human-plan.png')});
 assert.equal(await page.locator('#cutaway').getAttribute('aria-pressed'),'true');await page.click('#cutaway');assert.ok(await page.evaluate(()=>roomkitQA.pickables.filter(m=>m.userData.cutaway).every(m=>m.visible)));await page.click('#cutaway');
 await page.selectOption('#objects','person-001');assert.match(await page.locator('#joints').textContent(),/Recorded animation/);
 await page.setViewportSize({width:390,height:844});await page.click('#orbit');await page.waitForTimeout(300);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:resolve(out,'human-mobile.png'),fullPage:true});
 assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
 await writeFile(resolve(out,'human-browser-validation.json'),JSON.stringify({passed:true,info,all_frame_hashes:hashes,playback_elapsed_ms:elapsed,pause_holds:true,joints,roof_toggle:true,mobile_no_overflow:true,page_errors:errors,external_requests:requests},null,2));console.log('Human browser QA passed');
}finally{await browser.close();}

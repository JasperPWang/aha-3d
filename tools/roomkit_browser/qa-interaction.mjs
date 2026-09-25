import {chromium} from 'playwright';
import {writeFile,mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';
const [url,out]=process.argv.slice(2);await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 if(new URL(url).pathname.endsWith('/')){
  await page.goto(url,{timeout:120000});await page.waitForFunction(()=>window.reviewQA?.ready,null,{timeout:120000});
  const left=page.frames().find(f=>f.name()==='left')||page.frames()[1];
  const stageFrames=[45,160,290,450];
  for(let step=0;step<4;step++){
   await page.click(`#steps button[data-step="${step}"]`);
   await page.click('#raw-joined');
   await page.evaluate(f=>reviewQA.seek(f),stageFrames[step]);await page.waitForTimeout(300);
   assert.equal(await page.evaluate(()=>document.getElementById('left').contentWindow.roomkitQA.shownFrame),stageFrames[step]);
   assert.equal(await page.evaluate(()=>document.getElementById('right').contentWindow.roomkitQA.shownFrame),stageFrames[step]);
   await page.screenshot({path:resolve(out,`step-${step+1}-raw-joined.png`)});
   await page.click('#before-after');await page.waitForTimeout(150);
   await page.screenshot({path:resolve(out,`step-${step+1}-before-after.png`)});
  }
  await page.click('#steps button[data-step="-1"]');await page.evaluate(()=>reviewQA.seek(92));await page.click('#neck');await page.waitForTimeout(250);
  await page.screenshot({path:resolve(out,'neck-before-after.png')});
  await page.click('#raw-joined');await page.waitForTimeout(200);await page.screenshot({path:resolve(out,'neck-raw-joined.png')});
  await page.click('#before-after');
  let handCloseup=false;
  if(await page.locator('#hand').count()){
   await page.click('#hand');
   for(const frame of [95,160,205]){await page.evaluate(f=>reviewQA.seek(f),frame);await page.waitForTimeout(250);await page.screenshot({path:resolve(out,`hand-${frame}.png`)});}
   if(await page.evaluate(()=>!!document.getElementById('right').contentWindow.ROOMKIT_SCENE.interaction.hand_orientation_goal)){
    assert.ok((await page.locator('#palm-angle').textContent()).includes('Mesh palm normal:'));
    assert.equal(await page.evaluate(()=>document.getElementById('right').contentWindow.roomkitQA.scene.getObjectByName('Measured mesh palm normal').visible),true);
   }
   handCloseup=true;
  }
  await page.click('#orbit');await page.click('#collisions');await page.evaluate(()=>reviewQA.seek(131));await page.waitForTimeout(250);
  await page.screenshot({path:resolve(out,'collision-markers.png')});
  await page.click('#play');await page.waitForTimeout(1200);await page.click('#play');
  const f=await page.evaluate(()=>reviewQA.frame);await page.waitForTimeout(300);assert.equal(await page.evaluate(()=>reviewQA.frame),f);assert.ok(f>131);
  assert.equal(await page.locator('#error').textContent(),'');assert.deepEqual(errors,[]);
  await writeFile(resolve(out,'portal-validation.json'),JSON.stringify({passed:true,four_steps:true,raw_and_joined:true,before_and_after:true,synchronized_seeks:true,pause:true,neck_closeup:true,hand_closeup:handCloseup,page_errors:errors},null,2));
  console.log('Portal checks passed');
 }else{
 await page.goto(url,{timeout:120000});await page.waitForFunction(()=>window.roomkitQA?.ready,null,{timeout:120000});
 assert.equal(await page.locator('#error').textContent(),'');
 const validation=await page.evaluate(async()=>{
  const qa=roomkitQA,info=ROOMKIT_SCENE;const track=info.interaction.object_tracks[0];
  const samples=[];
  for(let f=0;f<info.animation.frames;f++){
   await qa.seek(f);
   const p=qa.placements.get(track.owner).position.toArray();
   if(p.some((v,k)=>Math.abs(v-track.translations[f][k])>1e-7))throw Error('Chair timeline mismatch '+f);
   for(const actor of qa.actors){const a=actor.mesh.geometry.attributes.position.array;if(!Number.isFinite(a[0])||!Number.isFinite(a[a.length-1]))throw Error('Invalid human mesh');}
   if(f%30===0)samples.push({frame:f,chair:p,vertex:qa.actors[0].mesh.geometry.attributes.position.array.slice(0,3)});
  }
  let rootCoupling=null;
  if(info.interaction.root_coupling){
   const r=info.interaction.root_coupling;let maxError=0;
   info.interaction.hand_contact_mask.forEach((on,f)=>{if(on)maxError=Math.max(maxError,Math.hypot(...r.goal_xy[f].map((x,i)=>x-r.tracks['generated-person'][f][i])));});
   if(maxError>1e-5)throw Error('Refined pull root left the coupled trajectory');
   rootCoupling={max_horizontal_error_m:maxError};
  }
  return {frames:info.animation.frames,fps:info.animation.fps,all_frame_object_alignment:true,root_coupling:rootCoupling,samples};
 });
 for(const f of [0,80,110,160,205,270,350,420,479]){
  await page.evaluate(async f=>roomkitQA.seek(f),f);await page.waitForTimeout(150);
  await page.screenshot({path:resolve(out,`frame-${String(f).padStart(3,'0')}.png`)});
 }
 await page.click('#plan');await page.waitForTimeout(200);await page.screenshot({path:resolve(out,'plan.png')});
 await page.click('#orbit');
 const multistage=await page.locator('#interaction-stage').count();
 if(multistage){
  for(const stage of ['raw-segments','before-refinement','generated-person','route-baseline']){
   await page.selectOption('#interaction-stage',stage);
   const visible=await page.evaluate(()=>roomkitQA.actors.filter(a=>a.mesh.visible).map(a=>a.owner));assert.deepEqual(visible,[stage]);
   await page.evaluate(()=>roomkitQA.seek(160));await page.waitForTimeout(100);await page.screenshot({path:resolve(out,stage+'.png')});
  }
  await page.selectOption('#interaction-step','1');await page.waitForFunction(()=>roomkitQA.shownFrame===90);assert.equal(await page.evaluate(()=>roomkitQA.shownFrame),90);
  await page.evaluate(()=>roomkitQA.seek(209));await page.click('#play');await page.waitForFunction(()=>!roomkitQA.playing,null,{timeout:15000});
  assert.equal(await page.evaluate(()=>roomkitQA.shownFrame),209);assert.equal(await page.evaluate(()=>roomkitQA.playing),false);
  await page.selectOption('#interaction-step','-1');
 }else{
 await page.click('#interaction-baseline');
 assert.equal(await page.locator('#interaction-baseline').getAttribute('aria-pressed'),'true');
 await page.evaluate(()=>roomkitQA.seek(160));await page.waitForTimeout(200);await page.screenshot({path:resolve(out,'comparison.png')});
 await page.click('#interaction-baseline');
 }
 await page.click('#restart');await page.click('#play');await page.waitForTimeout(700);await page.click('#play');
 const paused=await page.evaluate(()=>roomkitQA.shownFrame);await page.waitForTimeout(300);assert.equal(await page.evaluate(()=>roomkitQA.shownFrame),paused);
 assert.ok(paused>0);assert.deepEqual(errors,[]);
 await writeFile(resolve(out,'browser-validation.json'),JSON.stringify({...validation,pause_holds:true,stage_comparison:true,page_errors:errors},null,2));
 console.log(JSON.stringify({passed:true,frames:validation.frames,fps:validation.fps}));
 }
}finally{await browser.close();}

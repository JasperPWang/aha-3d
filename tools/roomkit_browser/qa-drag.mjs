import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html,out]=process.argv.slice(2);
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:1440,height:960}}),errors=[];
page.on('pageerror',e=>errors.push(e.message));
const snapshot=()=>page.evaluate(()=>{
 const q=roomkitQA;q.scene.updateMatrixWorld(true);
 return Object.fromEntries(ROOMKIT_SCENE.objects.map(o=>[o.instance_id,{offset:q.placements.get(o.instance_id).position.toArray(),meshes:q.pickables.filter(m=>m.userData.owner===o.instance_id).map(m=>m.matrixWorld.toArray())}]));
});
async function drag(id,dx,dy,cancel=false){
 const targets=await page.evaluate(id=>{const q=roomkitQA,r=q.renderer.domElement.getBoundingClientRect();return q.pickables.filter(m=>m.userData.owner===id).sort((a,b)=>Number(/seat|front|top/i.test(b.name))-Number(/seat|front|top/i.test(a.name))).map(m=>{const p=m.geometry.boundingSphere.center.clone().applyMatrix4(m.matrixWorld).project(q.camera);return {x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2};});},id);
 for(const p of targets){
  await page.mouse.move(p.x,p.y);await page.mouse.down();await page.waitForTimeout(400);
  if(await page.evaluate(()=>roomkitQA.selected)===id){await page.mouse.move(p.x+dx,p.y+dy,{steps:10});if(cancel)await page.keyboard.press('Escape');await page.mouse.up();await page.waitForTimeout(800);return;}
  await page.mouse.up();
 }
 throw Error('No visible drag target for '+id);
}
function movedTogether(before,after,id){
 const a=before[id],b=after[id],delta=b.offset.map((v,i)=>v-a.offset[i]);
 assert.ok(Math.hypot(...delta)>.05,id+' moved');assert.equal(delta[2],0,'Height preserved');
 a.meshes.forEach((m,i)=>m.forEach((v,k)=>assert.ok(Math.abs(b.meshes[i][k]-v-(k===12?delta[0]:k===13?delta[1]:0))<1e-5,id+' whole hierarchy')));
 return delta;
}
try{
 await page.goto(pathToFileURL(resolve(html)).href);await page.waitForFunction(()=>roomkitQA?.ready);await page.waitForTimeout(500);
 const baseline=await snapshot();await drag('chair-1',-75,25);const chair=await snapshot();const chairDelta=movedTogether(baseline,chair,'chair-1');assert.deepEqual(chair['chair-2'],baseline['chair-2']);
 await page.screenshot({path:resolve(out,'chair-dragged.png')});
 await drag('chair-1',40,20,true);const cancelled=await snapshot();assert.deepEqual(cancelled,chair,'Escape restores initial drag pose');
 await page.click('#open-all');await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===1));
 const beforeCab=await snapshot();await drag('cabinet-mixed',65,-10);const cabinet=await snapshot();const cabinetDelta=movedTogether(beforeCab,cabinet,'cabinet-mixed');assert.deepEqual(cabinet['cabinet-default'],beforeCab['cabinet-default']);
 await page.click('#close-all');await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===0));
 const closedCabinet=await snapshot();assert.deepEqual(closedCabinet['cabinet-mixed'].offset,cabinet['cabinet-mixed'].offset,'Closing retains dragged cabinet position');
 const beforeTable=await snapshot();await drag('support-plinth',70,10);const table=await snapshot();const tableDelta=movedTogether(beforeTable,table,'support-plinth');
 beforeTable['tabletop-vase'].meshes.forEach((m,i)=>{for(const k of [12,13,14])assert.ok(Math.abs(table['tabletop-vase'].meshes[i][k]-m[k]-tableDelta[k-12])<1e-5,'Vase follows support');});
 await drag('tabletop-vase',160,0);const supported=await page.evaluate(()=>{
  const q=roomkitQA;function extent(id){const v={min:[Infinity,Infinity,Infinity],max:[-Infinity,-Infinity,-Infinity]};for(const m of q.pickables.filter(m=>m.userData.owner===id)){const a=m.geometry.attributes.position;for(let i=0;i<a.count;i++){const p=m.geometry.boundingSphere.center.clone().fromBufferAttribute(a,i).applyMatrix4(m.matrixWorld).toArray();for(let k=0;k<3;k++){v.min[k]=Math.min(v.min[k],p[k]);v.max[k]=Math.max(v.max[k],p[k]);}}}return v;}return {vase:extent('tabletop-vase'),table:extent('support-plinth')};
 });
 for(const k of [0,1])assert.ok(supported.vase.min[k]>=supported.table.min[k]-1e-5&&supported.vase.max[k]<=supported.table.max[k]+1e-5,'Vase stays within support footprint');
 await page.screenshot({path:resolve(out,'layout-dragged.png')});
 await page.click('#reset-layout');assert.deepEqual(await snapshot(),baseline,'Reset restores all object matrices');
 await page.setViewportSize({width:390,height:844});await page.waitForTimeout(150);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:resolve(out,'drag-mobile.png'),fullPage:true});
 assert.deepEqual(errors,[]);await writeFile(resolve(out,'drag-validation.json'),JSON.stringify({passed:true,chairDelta,cabinetDelta,tableDelta,whole_mesh_hierarchy:true,unrelated_objects_unchanged:true,escape_cancels:true,joints_work_after_move:true,support_follows:true,support_footprint_clamp:true,reset_exact:true,mobile_no_overflow:true,page_errors:errors},null,2));
 console.log('Drag QA passed');
}finally{await browser.close();}

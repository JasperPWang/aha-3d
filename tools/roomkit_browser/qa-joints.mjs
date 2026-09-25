// Exercise every exported cabinet joint through its actual browser controls.
// Usage: node qa-joints.mjs HTML_OR_URL OUTPUT_DIR [MINIMUM_JOINTS]
import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [entry,out,minimum='1']=process.argv.slice(2),errors=[],failed=[];
await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{if(r.status()>=400)failed.push(r.url());});
 await page.goto(/^https?:/.test(entry)?entry:pathToFileURL(resolve(entry)).href,{timeout:120000});
 await page.waitForFunction(()=>window.roomkitQA?.ready,null,{timeout:120000});
 // Control assertions use the real RAF/pose loop without redrawing the room
 // for every DOM event. Capture renders the actual scene at each review pose.
 await page.evaluate(()=>{const q=roomkitQA;q.lighting?.setQuality('fast');window.captureJointFrame=q.renderer.render.bind(q.renderer);q.renderer.render=()=>{};});
 const capture=async name=>{await page.evaluate(()=>{roomkitQA.scene.updateMatrixWorld(true);captureJointFrame(roomkitQA.scene,roomkitQA.camera);});await page.screenshot({path:resolve(out,name),timeout:120000});};
 await page.click('#controls-tab');
 const joints=await page.evaluate(()=>ROOMKIT_SCENE.joints.map(j=>({id:j.id,owner:j.owner})));
 assert.ok(joints.length>=Number(minimum),`Expected at least ${minimum} joints, got ${joints.length}`);
 await page.evaluate(()=>{
  const q=roomkitQA;q.scene.updateMatrixWorld(true);
  window.jointBaseline=Object.fromEntries(q.pickables.map(m=>[m.name,m.matrixWorld.toArray()]));
 });
 const checks=[];
 for(const j of joints){
  console.log('Checking',j.id);
  await page.click('#controls-tab');
  await page.selectOption('#objects',j.owner);
  // Exact attribute matching also supports arbitrary punctuation in joint IDs.
  const index=await page.locator('button[data-joint]').evaluateAll((buttons,id)=>buttons.findIndex(b=>b.dataset.joint===id),j.id);
  assert.ok(index>=0,'Joint button missing: '+j.id);
  await page.locator('button[data-joint]').nth(index).click();
  await page.waitForFunction(id=>roomkitQA.joints.get(id).value===1,j.id,{timeout:30000}).catch(async error=>{console.log(await page.evaluate(id=>({id,value:roomkitQA.joints.get(id).value,target:roomkitQA.joints.get(id).target,error:document.querySelector('#error').textContent}),j.id),errors);throw error;});
  const result=await page.evaluate(id=>{
   const q=roomkitQA;q.scene.updateMatrixWorld(true);
   const changed=[],unexpected=[];
   for(const m of q.pickables){const before=jointBaseline[m.name],after=m.matrixWorld.toArray();
    const delta=Math.max(...after.map((v,i)=>Math.abs(v-before[i])));
    if(m.userData.joint===id){if(delta<=1e-5)throw Error('Door part did not move: '+m.name);changed.push(m.name);}
    else if(delta>1e-5)unexpected.push(m.name);
   }
   if(!changed.length||unexpected.length)throw Error(JSON.stringify({id,changed,unexpected}));
   return {id,movingParts:changed,unrelatedPartsMoved:unexpected};
  },j.id);checks.push(result);
  const input=page.locator('#joints .joint').nth(index).locator('input');
  await input.fill('50');
  assert.equal(await page.evaluate(id=>roomkitQA.joints.get(id).value,j.id),.5);
  await page.click('#graph-tab');await page.click('#close-all');
  await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===0),null,{timeout:120000});
 }
 await page.evaluate(()=>{
  roomkitQA.scene.updateMatrixWorld(true);
  for(const m of roomkitQA.pickables)if(m.matrixWorld.toArray().some((v,i)=>Math.abs(v-jointBaseline[m.name][i])>1e-5))throw Error('Closed pose differs: '+m.name);
 });
 await capture('cabinet-source-view-closed.png');
 // Supplemental kitchen inspection view; the delivered opening view is unchanged.
 await page.evaluate(()=>{
  const points=ROOMKIT_SCENE.joints.map(j=>j.closed.position);
  const lo=[0,1,2].map(i=>Math.min(...points.map(p=>p[i]))),hi=[0,1,2].map(i=>Math.max(...points.map(p=>p[i])));
  const center=lo.map((v,i)=>(v+hi[i])/2),span=Math.max(2,...lo.map((v,i)=>hi[i]-v));
  ROOMKIT_SCENE.views.orbit={position:center.map((v,i)=>v+[-.55,.9,.6][i]*span),target:center,fov:62};
 });
 await page.click('#orbit');
 await page.click('#controls-tab');await page.selectOption('#objects','');
 await capture('cabinet-closed.png');
 await page.click('#graph-tab');await page.click('#open-all');
 await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===1),null,{timeout:120000});
 await capture('cabinet-open.png');
 await page.click('#plan');
 await capture('cabinet-plan-open.png');
 await page.click('#graph-tab');await page.click('#close-all');
 await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===0),null,{timeout:120000});
 await page.setViewportSize({width:390,height:844});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 assert.deepEqual(errors,[]);assert.deepEqual(failed,[]);
 await writeFile(resolve(out,'cabinet-controls.json'),JSON.stringify({passed:true,entry,joints:checks.length,checks,allOpenAndClose:true,partialOpening:true,closedPoseRestored:true,errors,failed},null,2));
 console.log('Every cabinet joint passed:',checks.length);
}finally{await browser.close();}

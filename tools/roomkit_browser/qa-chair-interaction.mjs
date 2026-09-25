import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html,out,fixture]=process.argv.slice(2),errors=[];
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(resolve(html)).href,{timeout:120000});await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});
 if(fixture)await page.evaluate(poses=>{for(const p of poses){const s=roomkitQA.chairs.spec.slots.find(s=>s.id===p.id);roomkitQA.placements.get(p.id).position.set(p.position[0]-s.position[0],p.position[1]-s.position[1],0);}roomkitQA.scene.updateMatrixWorld(true);},JSON.parse(await readFile(fixture,'utf8')).placements);
 const first=await page.evaluate(()=>{const before=roomkitQA.chairs.layout.anchors,r=roomkitQA.chairs.regenerate('interaction');return {before,r,after:roomkitQA.chairs.layout.anchors};});
 assert.ok(first.r.passed,first.r.reason);assert.deepEqual(first.after,first.before);
 await page.click('#plan');
 await page.evaluate(()=>{roomkitQA.scene.updateMatrixWorld(true);roomkitQA.camera.updateMatrixWorld(true);});
 const targets=await page.evaluate(()=>{const q=roomkitQA,r=q.renderer.domElement.getBoundingClientRect();q.scene.updateMatrixWorld(true);return q.pickables.filter(m=>q.chairs.has(m.userData.owner)&&m.visible).map(m=>{const p=m.geometry.boundingSphere.center.clone().applyMatrix4(m.matrixWorld).project(q.camera);return {id:m.userData.owner,x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2};}).filter(p=>p.x>r.left&&p.x<r.right&&p.y>r.top&&p.y<r.bottom);});
 let moved=null;
 for(const target of targets){
  for(const [dx,dy] of [[45,0],[-45,0],[0,45],[0,-45]]){
   await page.mouse.move(target.x,target.y);await page.mouse.down();
   await page.waitForFunction(id=>roomkitQA.dragging&&roomkitQA.selected===id&&roomkitQA.placements.get(id).position.z>.1,target.id,{timeout:5000}).catch(()=>{});
   const held=await page.evaluate(id=>roomkitQA.dragging&&roomkitQA.selected===id&&roomkitQA.placements.get(id).position.z>.1,target.id);
   if(!held){await page.mouse.up();break;}
   const before=await page.evaluate(id=>roomkitQA.chairs.inspect(id).placement.position,target.id);
   await page.mouse.move(target.x+dx,target.y+dy,{steps:10});
   const after=await page.evaluate(id=>roomkitQA.chairs.inspect(id).placement.position,target.id);
   if(Math.hypot(after[0]-before[0],after[1]-before[1])>.005){
    await page.screenshot({timeout:120000,path:resolve(out,'replacement-chair-held.png')});await page.mouse.up();
    await page.waitForFunction(id=>roomkitQA.placements.get(id).position.z===0,target.id,{timeout:15000});
    moved={id:target.id,before,after};break;
   }
   await page.keyboard.press('Escape');await page.mouse.up();
  }
  if(moved)break;
 }
 assert.ok(moved,'A replacement chair must be pickable, lift and actually drag');
 const next=await page.evaluate(()=>{const before=roomkitQA.chairs.layout.anchors,r=roomkitQA.chairs.regenerate('after-manual-drag');return {before,after:roomkitQA.chairs.layout.anchors,passed:r.passed,reason:r.reason};});
 assert.deepEqual(next.after,next.before,'A subsequent swap or rejection retains manually moved anchors');
 // Cancel a real drag after moving; the last accepted manual position remains.
 const cancelTargets=await page.evaluate(id=>{const q=roomkitQA,r=q.renderer.domElement.getBoundingClientRect();q.scene.updateMatrixWorld(true);return q.pickables.filter(m=>m.userData.owner===id).map(m=>{const p=m.geometry.boundingSphere.center.clone().applyMatrix4(m.matrixWorld).project(q.camera);return {x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2};});},moved.id);
 let cancelled=false;
 for(const target of cancelTargets){
  const before=await page.evaluate(()=>roomkitQA.chairs.layout.anchors);
  await page.mouse.move(target.x,target.y);await page.mouse.down();
  await page.waitForFunction(id=>roomkitQA.dragging&&roomkitQA.selected===id,moved.id,{timeout:5000}).catch(()=>{});
  if(await page.evaluate(id=>roomkitQA.dragging&&roomkitQA.selected===id,moved.id)){
   await page.mouse.move(target.x+20,target.y+20,{steps:5});await page.keyboard.press('Escape');await page.mouse.up();
   assert.deepEqual(await page.evaluate(()=>roomkitQA.chairs.layout.anchors),before);cancelled=true;break;
  }
  await page.mouse.up();
 }
 assert.ok(cancelled);assert.deepEqual(errors,[]);
 await page.screenshot({timeout:120000,path:resolve(out,'replacement-chair-moved.png')});
 await writeFile(resolve(out,'chair-interaction-validation.json'),JSON.stringify({passed:true,placementFixture:fixture||null,swapPreservesAnchors:true,holdLifts:true,dragMoves:true,releaseLands:true,escapeRestores:true,manualPlacementSurvivesSwap:true,moved,next,errors},null,2));
 console.log('Replacement chair pointer interaction passed');
}finally{await browser.close();}

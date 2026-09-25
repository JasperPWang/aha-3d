import {chromium} from 'playwright';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const [html,out,...ids]=process.argv.slice(2),errors=[],checks=[];
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1280,height:900}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(html.startsWith('http')?html:pathToFileURL(resolve(html)).href,{timeout:120000});await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});
 await page.evaluate(()=>{ROOMKIT_SCENE.show_selection_bounds=true;roomkitQA.tabletop.paused=true;window.savedFrameRequest=window.requestAnimationFrame;});
 for(const [index,id] of ids.entries()){
  await page.evaluate(id=>{const el=document.getElementById('objects');el.value=id;el.dispatchEvent(new Event('change'));},id);
  await page.waitForFunction(id=>roomkitQA.scene.children.some(o=>o.userData.selectionId===id),id);
  const check=await page.evaluate(id=>{
   const q=roomkitQA,helpers=q.scene.children.filter(o=>o.userData.selectionBox),line=helpers[0],p=line.geometry.attributes.position;
   const mesh=q.pickables.find(m=>m.userData.owner===id),a=mesh.position.clone().fromBufferAttribute(p,0),edge=mesh.position.clone().fromBufferAttribute(p,1).sub(a).normalize();
   const x=mesh.position.clone().setFromMatrixColumn(mesh.matrixWorld,0).normalize(),y=mesh.position.clone().setFromMatrixColumn(mesh.matrixWorld,1).normalize();
   return {id,helperCount:helpers.length,edgeAlignment:Math.max(Math.abs(edge.dot(x)),Math.abs(edge.dot(y))),vertices:p.count,edges:line.geometry.index.count/2};
  },id);
  assert.equal(check.helperCount,1);assert.ok(check.edgeAlignment>.99999,JSON.stringify(check));assert.equal(check.edges,12);checks.push(check);
  // Freeze the camera for a close-up without OrbitControls overriding lookAt.
  await page.evaluate(()=>{window.requestAnimationFrame=()=>0;});await page.waitForTimeout(100);
  await page.evaluate(id=>{const q=roomkitQA,b=q.bounds(id),c=b.getCenter(q.camera.position.clone());q.camera.position.copy(c).add(c.clone().set(1.3,-1.7,1.65));q.camera.lookAt(c);q.renderer.render(q.scene,q.camera);},id);
  await page.screenshot({path:resolve(out,`selection-${index}.png`),timeout:120000});
  await page.evaluate(()=>{window.requestAnimationFrame=window.savedFrameRequest;});
  // Restore the normal loop by reloading between independent selections.
  if(index<ids.length-1){await page.reload({timeout:120000});await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});await page.evaluate(()=>{ROOMKIT_SCENE.show_selection_bounds=true;roomkitQA.tabletop.paused=true;window.savedFrameRequest=window.requestAnimationFrame;});}
 }
 assert.deepEqual(errors,[]);await writeFile(resolve(out,'selection-box-validation.json'),JSON.stringify({passed:true,checks,errors},null,2));console.log('Selection box validation passed',checks);
}finally{await browser.close();}

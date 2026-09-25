import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html,out]=process.argv.slice(2),errors=[];
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(/^https?:/.test(html)?html:pathToFileURL(resolve(html)).href,{timeout:120000});await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});
 assert.equal(await page.locator('#error').textContent(),'');assert.equal(await page.locator('#graph-tab').getAttribute('aria-selected'),'true');
 const initial=await page.evaluate(()=>roomkitQA.sceneGraph.snapshot());
 assert.equal(initial.nodes.filter(n=>n.kind==='object').length,await page.evaluate(()=>ROOMKIT_SCENE.objects.length));
 assert.equal(initial.nodes.filter(n=>n.kind==='joint').length,await page.evaluate(()=>ROOMKIT_SCENE.joints.length));
 assert.ok(initial.nodes.filter(n=>n.kind==='object').every(n=>n.layout?.center_m.every(Number.isFinite)));
 if(initial.animation_frame!==null)assert.ok(Number.isFinite(initial.animation_frame));
 const tableId=await page.evaluate(()=>roomkitQA.tabletop?.spec.supports[0].id);
 if(tableId){
  const table=initial.nodes.find(n=>n.id===tableId);assert.ok(Math.hypot(...table.layout.center_m)>.1,'Source roots at zero must still have their real geometry center');
  const sourceIds=await page.evaluate(()=>roomkitQA.tabletop.spec.supports[0].source_ids);
  for(const id of sourceIds)assert.ok(initial.nodes.some(n=>n.id===id&&n.parent_id===tableId));
  // A seating group can include the table label; select the object's identity.
  await page.locator('.graph-node').evaluateAll((buttons,id)=>buttons.find(b=>b.dataset.nodeId===id).click(),tableId);
  assert.equal(await page.evaluate(()=>roomkitQA.selected),tableId);assert.equal(JSON.parse(await page.locator('#layout-text').textContent()).id,tableId);
  await page.screenshot({timeout:120000,path:resolve(out,'scene-graph-original.png')});
  await page.click('#graph-swap');
  await page.waitForFunction(id=>roomkitQA.sceneGraph.snapshot().seed!=='original',tableId);
  const swapped=await page.evaluate(()=>roomkitQA.sceneGraph.snapshot());
  const props=swapped.nodes.filter(n=>n.kind==='object'&&n.parent_id===tableId);
  assert.ok(props.length>0);assert.equal(props.length,await page.evaluate(id=>roomkitQA.tabletop.layout.placements.filter(p=>p.support===id).length,tableId));assert.ok(swapped.edges.some(e=>e.relation==='assigned_support'&&e.from===tableId));
  const id=props[0].id;await page.locator('.graph-node').evaluateAll((buttons,id)=>buttons.find(b=>b.dataset.nodeId===id).click(),id);
  assert.equal(await page.evaluate(()=>roomkitQA.selected),id);
  // The tree and the canvas share one selection, and live geometry drives text.
  const movement=await page.evaluate(id=>{const q=roomkitQA,e=q.tabletop.entries.get(id),before=q.sceneGraph.snapshot().nodes.find(n=>n.id===id).layout.center_m;q.tabletop.paused=true;e.body.velocity.setZero();e.body.angularVelocity.setZero();e.body.position.x+=.07;e.body.position.z+=.25;e.body.wakeUp();q.tabletop.advance(1);q.sceneGraph.refresh(true);return {before,after:q.sceneGraph.snapshot().nodes.find(n=>n.id===id).layout.center_m};},id);
  assert.ok(movement.after[2]-movement.before[2]>.2,JSON.stringify(movement));
  await page.waitForFunction(id=>JSON.parse(document.getElementById('layout-text').textContent).id===id,id);
  let node=JSON.parse(await page.locator('#layout-text').textContent());assert.equal(node.support.assigned_id,tableId);
  await page.evaluate(id=>{const q=roomkitQA,e=q.tabletop.entries.get(id);q.tabletop.paused=true;e.body.position.set(q.tabletop.spec.supports[0].max[0]+2,q.tabletop.spec.supports[0].max[1]+2,q.tabletop.spec.supports[0].max[2]-.6);e.body.velocity.setZero();q.tabletop.advance(1);q.sceneGraph.refresh(true);},id);
  await page.waitForFunction(()=>JSON.parse(document.getElementById('layout-text').textContent).support?.spatial_state==='outside table footprint');
  node=JSON.parse(await page.locator('#layout-text').textContent());assert.equal(node.parent_id,tableId);assert.ok(node.support.height_above_table_m<-.3,'Assigned support must not conceal a fallen layout');
  await page.screenshot({timeout:120000,path:resolve(out,'scene-graph-fallen.png')});
  await page.click('#graph-swap');await page.waitForFunction(()=>roomkitQA.selected===null,{},{timeout:120000});assert.equal(await page.evaluate(()=>roomkitQA.selected),null,'Removed selection clears');
 }
 const downloadPromise=page.waitForEvent('download');await page.click('#download-layout');const download=await downloadPromise;
 const path=resolve(out,'layout-export.json');await download.saveAs(path);const exported=JSON.parse(await readFile(path,'utf8'));
 assert.equal(exported.schema_version,1);assert.equal(exported.source_sha256,initial.source_sha256);
 assert.equal(exported.nodes.filter(n=>n.kind==='object').length,await page.evaluate(()=>ROOMKIT_SCENE.objects.length));
 // Controls remain usable after the graph panel has been active.
 await page.click('#controls-tab');await page.click('#open-all');await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===1),{},{timeout:30000});
 await page.click('#graph-tab');assert.ok(await page.evaluate(()=>roomkitQA.sceneGraph.snapshot().nodes.filter(n=>n.kind==='joint').every(n=>n.opening===1)));
 await page.click('#controls-tab');await page.click('#close-all');if(tableId)await page.click('#original-table');await page.click('#graph-tab');
 if(tableId)await page.locator('.graph-node').evaluateAll((buttons,id)=>buttons.find(b=>b.dataset.nodeId===id).click(),tableId);
 await page.screenshot({timeout:120000,path:resolve(out,'scene-graph-final.png')});
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({timeout:120000,path:resolve(out,'scene-graph-mobile.png'),fullPage:true});assert.deepEqual(errors,[]);
 await writeFile(resolve(out,'scene-graph-validation.json'),JSON.stringify({passed:true,objectNodes:initial.nodes.filter(n=>n.kind==='object').length,jointNodes:initial.nodes.filter(n=>n.kind==='joint').length,geometryBasedCoordinates:true,assignedSupportSeparateFromLocation:true,livePositions:true,selectionLinked:true,seedSwapRebuildsGraph:!!tableId,jsonDownload:true,mobile:true,errors},null,2));
 console.log('Scene graph and live layout validation passed');
}finally{await browser.close();}

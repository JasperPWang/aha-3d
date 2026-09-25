import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {lockStructure} from './movement-policy.js';
const fixture={objects:[{instance_id:'parent'},{instance_id:'shell',semantic_class:'architecture/room',support_id:'parent',movable:true},{instance_id:'chair',semantic_class:'furniture/seating/chairs',movable:true},{instance_id:'lamp',semantic_class:'lighting/floor_lamps',movable:true},{instance_id:'cover',semantic_class:'rug',movable:true},{instance_id:'legacy',movable:true}],meshes:[{owner:'legacy',surface:'wall'}]};
assert.deepEqual([...lockStructure(fixture)].sort(),['legacy','parent','shell']);
assert.ok(fixture.objects.filter(o=>['chair','lamp','cover'].includes(o.instance_id)).every(o=>o.movable));
const [html,out]=process.argv.slice(2),errors=[];
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:960}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(resolve(html)).href,{timeout:120000});await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});
 await page.click('#plan');await page.waitForTimeout(500);
 const fixed=await page.evaluate(()=>ROOMKIT_SCENE.objects.filter(o=>/^(architecture|structure)(\/|$)|^(floor|wall|ceiling)$/.test(o.semantic_class||'')).map(o=>({id:o.instance_id,movable:o.movable})));
 assert.ok(fixed.length);assert.ok(fixed.every(o=>o.movable===false));
 // Isolate one structural mesh to make an actual pointer hit deterministic.
 const target=await page.evaluate(ids=>{const q=roomkitQA,m=q.pickables.find(m=>ids.includes(m.userData.owner)&&!m.userData.joint&&m.visible);if(!m)return null;
 window.savedVisible=q.pickables.map(m=>m.visible);q.pickables.forEach(x=>x.visible=x===m);q.scene.updateMatrixWorld(true);
 m.geometry.computeBoundingSphere();const p=m.geometry.boundingSphere.center.clone().applyMatrix4(m.matrixWorld).project(q.camera),r=q.renderer.domElement.getBoundingClientRect();
 return {id:m.userData.owner,x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2,before:q.placements.get(m.userData.owner).position.toArray()};},fixed.map(o=>o.id));
 assert.ok(target);await page.mouse.move(target.x,target.y);await page.mouse.down();await page.waitForTimeout(450);
 assert.equal(await page.evaluate(()=>roomkitQA.dragging),false);assert.equal(await page.evaluate(()=>roomkitQA.selected),target.id);
 await page.mouse.move(target.x+50,target.y+30,{steps:8});await page.mouse.up();
 assert.deepEqual(await page.evaluate(id=>roomkitQA.placements.get(id).position.toArray(),target.id),target.before);
 await page.evaluate(()=>{roomkitQA.pickables.forEach((m,i)=>m.visible=savedVisible[i]);});
 const candidates=await page.evaluate(()=>{const q=roomkitQA,r=q.renderer.domElement.getBoundingClientRect(),ids=ROOMKIT_SCENE.objects.filter(o=>o.movable!==false&&/chair|stool|sofa|seating/.test(o.semantic_class||'')).map(o=>o.instance_id);return q.pickables.filter(m=>ids.includes(m.userData.owner)&&m.visible&&!m.userData.joint).map(m=>{m.geometry.computeBoundingSphere();const p=m.geometry.boundingSphere.center.clone().applyMatrix4(m.matrixWorld).project(q.camera);return {id:m.userData.owner,x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2};}).filter(p=>p.x>r.left&&p.x<r.right&&p.y>r.top&&p.y<r.bottom);});
 let furniture=null;
 for(const p of candidates){
  const before=await page.evaluate(id=>roomkitQA.placements.get(id).position.toArray(),p.id);
  await page.mouse.move(p.x,p.y);await page.mouse.down();await page.waitForTimeout(450);
  const held=await page.evaluate(id=>roomkitQA.dragging&&roomkitQA.selected===id&&roomkitQA.placements.get(id).position.z>.1,p.id);
  if(!held){await page.keyboard.press('Escape');await page.mouse.up();continue;}
  await page.mouse.move(p.x+30,p.y+15,{steps:5});await page.keyboard.press('Escape');await page.mouse.up();
  assert.deepEqual(await page.evaluate(id=>roomkitQA.placements.get(id).position.toArray(),p.id),before);
  await page.mouse.move(p.x,p.y);await page.mouse.down();await page.waitForTimeout(450);assert.equal(await page.evaluate(()=>roomkitQA.dragging),true);await page.mouse.up();
  await page.waitForFunction(id=>roomkitQA.placements.get(id).position.z===0,p.id,{timeout:15000});
  furniture={id:p.id,holdLifts:true,escapeRestores:true,releaseLands:true};break;
 }
 assert.ok(furniture,'Furniture remains draggable');
 await page.click('#orbit');await page.screenshot({path:resolve(out,'structure-orbit.png'),timeout:120000});
 assert.deepEqual(errors,[]);await writeFile(resolve(out,'structure-validation.json'),JSON.stringify({passed:true,fixed,pointer:target,furniture,errors},null,2));
 console.log('Structure QA passed');
}finally{await browser.close();}

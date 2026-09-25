import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html,out]=process.argv.slice(2),errors=[];
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:960}});
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(resolve(html)).href,{timeout:120000});await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});
 assert.equal(await page.locator('#error').textContent(),'');
 await page.click('#controls-tab');
 const evidence=await page.evaluate(async()=>{
  const q=roomkitQA,d=ROOMKIT_SCENE;const hashes=[],checks=[];
  for(let f=0;f<(d.animation?.frames||0);f++){
   const t=document.getElementById('timeline');t.value=f;t.dispatchEvent(new Event('input'));
   // digest copies its input before yielding; collect all checks before waiting
   // so software rendering does not redraw the room between every vertex hash.
   for(const a of q.actors){const bytes=a.mesh.geometry.attributes.position.array;checks.push(crypto.subtle.digest('SHA-256',bytes.buffer).then(digest=>{const hash=[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');if(hash!==a.checks[f].sha256)throw Error('Animation differs at '+f);}));}
   hashes.push(f);
  }
  await Promise.all(checks);
  return {objects:d.objects.length,joints:d.joints.length,meshes:d.meshes.length,actors:q.actors.length,checkedFrames:hashes.length,sourceUnchanged:d.validation.source_unchanged};
 });
 assert.ok(evidence.meshes>0);assert.ok(evidence.sourceUnchanged);
 await page.click('#open-all');await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===1),{},{timeout:30000});
 assert.ok(await page.evaluate(()=>[...roomkitQA.joints.values()].every(j=>j.group.position.distanceTo(j.a.p)>.00001||j.group.quaternion.angleTo(j.a.q)>.00001)),'Every discovered joint moves');
 await page.click('#close-all');await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===0),{},{timeout:30000});
 if(evidence.actors){await page.click('#restart');await page.click('#play');await page.waitForFunction(()=>roomkitQA.shownFrame>0,{},{timeout:30000});await page.click('#play');}
 await page.evaluate(()=>document.querySelector('aside').scrollTop=0);await page.screenshot({timeout:120000,path:resolve(out,'orbit.png')});await page.click('#plan');await page.screenshot({timeout:120000,path:resolve(out,'plan.png')});
 await page.setViewportSize({width:390,height:844});await page.waitForTimeout(300);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({timeout:120000,path:resolve(out,'mobile.png'),fullPage:true});assert.deepEqual(errors,[]);
 await writeFile(resolve(out,'validation.json'),JSON.stringify({passed:true,...evidence,errors},null,2));
 console.log('Generic browser validation passed');
}finally{await browser.close();}

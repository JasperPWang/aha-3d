import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html,out]=process.argv.slice(2),errors=[];
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 await page.goto(pathToFileURL(resolve(html)).href,{timeout:120000});
 await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});
 await page.evaluate(()=>{if(roomkitQA.tabletop)roomkitQA.tabletop.paused=true;});
 await page.click('#orbit');
 const report=await page.evaluate(()=>roomkitQA.lighting.report());
 assert.ok(await page.evaluate(()=>!!roomkitQA.scene.environment));
 assert.ok(await page.evaluate(()=>roomkitQA.renderer.shadowMap.enabled&&roomkitQA.lighting.key.castShadow));
 async function pixels(){return page.evaluate(()=>{
  const q=roomkitQA,r=q.renderer;r.render(q.scene,q.camera);const gl=r.getContext(),w=gl.drawingBufferWidth,h=gl.drawingBufferHeight,bytes=new Uint8Array(w*h*4);gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,bytes);
  let hash=2166136261,sum=0;for(let i=0;i<bytes.length;i+=4){sum+=bytes[i]+bytes[i+1]+bytes[i+2];hash=Math.imul(hash^bytes[i],16777619);hash=Math.imul(hash^bytes[i+1],16777619);hash=Math.imul(hash^bytes[i+2],16777619);}return {hash:hash>>>0,mean:sum/(w*h*3)};
 });}
 const on=await pixels();await page.screenshot({path:resolve(out,'lighting-on.png'),timeout:120000});
 if(report.lamps){
  await page.click('#lamps');const off=await pixels();
  assert.notEqual(on.hash,off.hash,'Lamp toggle must change rendered scene pixels');
  assert.ok(await page.evaluate(()=>roomkitQA.lighting.lights.filter(l=>l.userData.lamp).every(l=>l.intensity===0)));
  await page.screenshot({path:resolve(out,'lighting-off.png'),timeout:120000});
  report.pixelComparison={on,off};await page.click('#lamps');
  // Independent transform diagnostic; restore all source placements immediately.
  report.parenting=await page.evaluate(()=>{
   const q=roomkitQA,checked=[];
   for(const light of q.lighting.lights){const p=q.placements.get(light.userData.owner);if(!p||light.userData.joint)continue;
    const before=light.getWorldPosition(light.position.clone());p.position.x+=.123;q.scene.updateMatrixWorld(true);const after=light.getWorldPosition(light.position.clone());p.position.x-=.123;q.scene.updateMatrixWorld(true);
    if(Math.abs(after.x-before.x-.123)>1e-5)throw Error('Lamp did not follow owner');checked.push(light.name);
   }return checked;
  });
 }
 await page.click('#controls-tab');
 if(report.lightmap||report.probe){
  await page.click('#indirect');const off=await pixels();assert.notEqual(on.hash,off.hash,'Indirect toggle must change rendered scene pixels');
  await page.screenshot({path:resolve(out,'lighting-no-indirect.png'),timeout:120000});await page.click('#indirect');
 }
 await page.selectOption('#lighting-quality','fast');assert.equal(await page.evaluate(()=>roomkitQA.renderer.shadowMap.enabled),false);
 await page.selectOption('#lighting-quality','high');assert.equal(await page.evaluate(()=>roomkitQA.lighting.quality),'high');
 await page.selectOption('#lighting-quality','balanced');
 await page.setViewportSize({width:390,height:844});await page.waitForTimeout(250);
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:resolve(out,'lighting-mobile.png'),fullPage:true,timeout:120000});
 assert.deepEqual(errors,[]);
 await writeFile(resolve(out,'lighting-validation.json'),JSON.stringify({passed:true,...report,errors,performance:'Software-rendered correctness check; not a target-device FPS benchmark'},null,2));
 console.log('Lighting validation passed');
}finally{await browser.close();}

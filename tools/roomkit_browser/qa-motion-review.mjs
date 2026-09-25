import {chromium} from 'playwright';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';

const [url,output,expectedPath]=process.argv.slice(2),out=resolve(output);
await mkdir(out,{recursive:true});
const expected=expectedPath?JSON.parse(await readFile(expectedPath,'utf8')):{};
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const errors=[],checks=[];
try{
 const page=await browser.newPage({viewport:{width:1360,height:1050}});
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url);
 const ready=async()=>{
  await page.waitForFunction(()=>document.getElementById('status').textContent.startsWith('Ready')||!document.getElementById('retry').hidden,null,{timeout:120000});
  const status=await page.locator('#status').textContent();assert.ok(status.startsWith('Ready'),status);
 };
 await ready();
 const cases=await page.locator('#case option').evaluateAll(rows=>rows.map(o=>o.value));
 for(const id of cases){
  await page.selectOption('#case',id);await ready();
  const variants=await page.locator('#variant option').evaluateAll(rows=>rows.map(o=>o.value));
  for(const variant of variants){
   if(await page.locator('#variant').inputValue()!==variant){await page.selectOption('#variant',variant);await ready();}
   assert.equal(await page.locator('iframe').count(),1);
   const result=await page.evaluate(async({id,variant,expected})=>{
    const win=document.querySelector('iframe').contentWindow,q=win.roomkitQA,d=win.ROOMKIT_SCENE;
    const key=id+'/'+variant,frames=new Set([0,Math.floor(d.animation.frames/2),d.animation.frames-1]);
    for(const a of q.actors)if(a.active_frame_range)for(const f of [a.active_frame_range[0]-1,a.active_frame_range[0],a.active_frame_range[1]-1,a.active_frame_range[1]])if(f>=0&&f<d.animation.frames)frames.add(f);
    let maxVertexError=0;
    for(const f of frames){
     await q.seek(f);if(q.shownFrame!==f)throw Error('Seek mismatch');
     for(const a of q.actors){
      if(a.active_frame_range&&a.mesh.visible!==(f>=a.active_frame_range[0]&&f<a.active_frame_range[1]))throw Error('Actor visibility mismatch: '+a.owner);
      const array=a.mesh.geometry.attributes.position.array;
      if(!array.every(Number.isFinite))throw Error('Nonfinite rendered geometry');
      for(const sample of expected[key]?.[a.owner]?.[f]||[]){const error=Math.abs(array[sample[0]]-sample[1]);maxVertexError=Math.max(maxVertexError,error);if(error>1e-6)throw Error('Source mesh mismatch');}
     }
    }
    await q.seek(Math.floor(d.animation.frames/2));
    return {id,variant,actors:q.actors.length,frames:[...frames],maxVertexError,canvas:{width:q.renderer.domElement.width,height:q.renderer.domElement.height},error:win.document.getElementById('error').textContent};
   },{id,variant,expected});
   assert.equal(result.error,'');assert.ok(result.canvas.width>0);checks.push(result);
   if(variant===variants[0])await page.screenshot({path:resolve(out,id+'.png'),timeout:120000});
   console.log('Checked',id,variant);
  }
 }
 // G1 keeps all original rigid-link and light tracks, with stage controls.
 const g1=await page.evaluate(async()=>{
  const w=document.querySelector('iframe').contentWindow,q=w.roomkitQA,d=w.ROOMKIT_SCENE;
  if(!d.interaction?.light_tracks?.length)return null;
  const records=[];
  for(const frame of [0,170,d.animation.frames-1]){
   await q.seek(frame);
   for(const t of d.interaction.object_tracks){
    const p=q.placements.get(t.owner);
    if(p.position.toArray().some((v,i)=>Math.abs(v-t.translations[frame][i])>1e-6))throw Error('G1 rigid translation mismatch');
    if(t.quaternions&&p.quaternion.toArray().some((v,i)=>Math.abs(v-t.quaternions[frame][i])>1e-6))throw Error('G1 rigid rotation mismatch');
   }
   records.push({frame,lamps:q.lighting.lights.filter(l=>l.userData.lamp).map(l=>({owner:l.userData.owner,intensity:l.intensity}))});
  }
  const select=w.document.getElementById('interaction-stage');
  for(const option of select.options){select.value=option.value;select.dispatchEvent(new Event('change'));if(q.interaction.variant!==option.value)throw Error('G1 stage switch mismatch');}
  return {records,stages:select.options.length,tracks:d.interaction.object_tracks.length};
 });
 assert.ok(g1?.stages>=4);assert.notDeepEqual(g1.records[0].lamps,g1.records[1].lamps);
 await page.selectOption('#case',cases[0]);await ready();
 await page.evaluate(async()=>{await document.querySelector('iframe').contentWindow.roomkitQA.seek(30);});
 await page.selectOption('#variant','native');await ready();
 assert.equal(await page.evaluate(()=>document.querySelector('iframe').contentWindow.roomkitQA.shownFrame),30);
 const frame=page.frames().find(f=>f.url().includes('demo-fast.html'));
 await frame.click('#play');await page.waitForFunction(()=>document.querySelector('iframe').contentWindow.roomkitQA.shownFrame>30,null,{timeout:30000});await frame.click('#play');
 const canvas=await frame.locator('canvas[data-engine]').boundingBox();
 const before=await frame.evaluate(()=>roomkitQA.camera.position.toArray());
 await page.mouse.move(canvas.x+canvas.width*.5,canvas.y+canvas.height*.5);await page.mouse.down();await page.mouse.move(canvas.x+canvas.width*.65,canvas.y+canvas.height*.55,{steps:8});await page.mouse.up();
 const after=await frame.evaluate(()=>roomkitQA.camera.position.toArray());assert.notDeepEqual(before,after);
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:resolve(out,'mobile.png'),fullPage:true,timeout:120000});
 assert.deepEqual(errors,[]);
 await writeFile(resolve(out,'validation.json'),JSON.stringify({passed:true,environment:'Headless Chromium / SwiftShader; does not prove client GPU behavior',checks,g1,oneIframe:true,variantPreservesFrame:true,playback:true,orbit:true,mobile:true,errors},null,2));
}finally{await browser.close();}

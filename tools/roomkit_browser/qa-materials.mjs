import {chromium} from 'playwright';
import {writeFile,mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html,out]=process.argv.slice(2),errors=[];await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 await page.goto(pathToFileURL(resolve(html)).href,{timeout:120000});await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});
 await page.click('#controls-tab');await page.selectOption('#lighting-quality','fast');
 const target=await page.evaluate(()=>{
  const q=roomkitQA,ids=ROOMKIT_SCENE.objects.filter(o=>/table|cabinet|chair/.test(o.semantic_class)).map(o=>o.instance_id);
  const target=(ids.includes('support-plinth')?'support-plinth':null)||ids.find(id=>q.pickables.some(m=>m.userData.owner===id&&!q.actors.some(a=>a.mesh===m)))||ROOMKIT_SCENE.objects[0].instance_id;
  window.materialQAOriginal=q.pickables.map(m=>({mesh:m,material:m.material,geometry:m.geometry,matrix:Array.from(m.matrix.elements)}));return target;
 });
 await page.selectOption('#objects',target);assert.ok(await page.locator('#material-slot option').count());
 const snapshots=[];
 for(const preset of ['oak','walnut','marble','granite','concrete','steel','brass','copper']){
  await page.selectOption('#material-preset',preset);await page.fill('#material-seed','review-17');await page.fill('#material-size','0.5');
  await page.click('#material-apply');
  await page.waitForFunction(()=>roomkitQA.materialLab.overrideCount>0);
  const check=await page.evaluate(({target,preset})=>{
   const q=roomkitQA,arr=m=>Array.isArray(m)?m:[m],changed=[],maps=new Set();
   for(const original of materialQAOriginal){const m=original.mesh;
    if(JSON.stringify(Array.from(m.matrix.elements))!==JSON.stringify(original.matrix))throw Error('Material edited placement');
    if(m.userData.owner!==target&&m.material!==original.material)throw Error('Shared material leak');
    if(m.material!==original.material)for(const [i,mat] of arr(m.material).entries())if(mat!==arr(original.material)[i]&&mat.userData.procedural){
      if(mat.userData.procedural.preset!==preset||!mat.map||!mat.normalMap||!mat.roughnessMap)throw Error('PBR maps not installed');
      if(mat.userData.procedural.version!==3||mat.map.image.width!==512)throw Error('Upgraded texture resolution/version missing');
      maps.add(mat.map);changed.push(m.name);
    }
   }if(maps.size!==1)throw Error('Applied surfaces must share their texture set');
   return {preset,changed:[...new Set(changed)],overrides:q.materialLab.overrideCount,sharedTextureSets:maps.size,resolution:512};
  },{target,preset});assert.ok(check.changed.length);snapshots.push(check);
  await page.locator('#material-lab').scrollIntoViewIfNeeded();await page.screenshot({path:resolve(out,`material-${preset}.png`),timeout:120000});
 }
 const indirectFollows=await page.evaluate(()=>{
  const q=roomkitQA,changed=[];
  for(const o of materialQAOriginal){const old=Array.isArray(o.material)?o.material:[o.material],current=Array.isArray(o.mesh.material)?o.mesh.material:[o.mesh.material];
   current.forEach((m,i)=>{if(m!==old[i]&&m.lightMap)changed.push([m,old[i]]);});
  }
  if(!changed.length)return 'no baked lightmap on selected surface';
  document.getElementById('indirect').click();q.renderer.render(q.scene,q.camera);
  if(!changed.every(([m,old])=>m.lightMapIntensity===old.lightMapIntensity&&m.lightMapIntensity===0))throw Error('Indirect off did not reach material override');
  document.getElementById('indirect').click();q.renderer.render(q.scene,q.camera);
  if(!changed.every(([m,old])=>m.lightMapIntensity===old.lightMapIntensity&&m.lightMapIntensity>0))throw Error('Indirect on did not reach material override');
  return true;
 });
 // Recipe download preserves exactly the values used to regenerate in Blender.
 const downloaded=page.waitForEvent('download');await page.click('#material-download');const file=await downloaded;await file.saveAs(resolve(out,'material-recipe.json'));
 await page.click('#material-reset');
 assert.ok(await page.evaluate(()=>materialQAOriginal.every(o=>o.mesh.material===o.material&&o.mesh.geometry===o.geometry)));
 const swapRestored=await page.evaluate(async()=>{
  const q=roomkitQA;if(!q.tabletop)return 'no tabletop in this fixture';
  const id=q.tabletop.snapshot()[0]?.id;if(!id)return 'no tabletop object';
  const source=q.pickables.filter(m=>m.userData.owner===id).map(mesh=>({mesh,material:mesh.material,geometry:mesh.geometry}));
  if(!q.materialLab.apply({preset:'brass'},id,'*'))throw Error('No tabletop material applied');
  if(!await q.tabletop.regenerate('material-regression'))throw Error('Tabletop swap was rejected');
  q.tabletop.original();
  if(!source.every(o=>o.mesh.material===o.material&&o.mesh.geometry===o.geometry))throw Error('Cached originals retained material overrides');
  return true;
 });
 // Exclude baked actors and leave their frame buffers intact.
 const actorsProtected=await page.evaluate(()=>{
  const q=roomkitQA;if(!q.actors.length)return 'no actors in this fixture';
  for(const a of q.actors){const material=a.mesh.material; q.materialLab.apply({preset:'oak'},a.mesh.userData.owner,'*');if(a.mesh.material!==material)throw Error('Actor changed');}
  return true;
 });
 await page.setViewportSize({width:390,height:844});await page.locator('#material-lab').scrollIntoViewIfNeeded();
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:resolve(out,'material-mobile.png'),fullPage:true,timeout:120000});
 assert.deepEqual(errors,[]);await writeFile(resolve(out,'materials-validation.json'),JSON.stringify({passed:true,target,snapshots,restoreIdentity:true,placementUnchanged:true,sharedMaterialsIsolated:true,actorsProtected,swapRestored,indirectFollows,mobile:true,errors},null,2));
 console.log('Material browser QA passed');
}finally{await browser.close();}

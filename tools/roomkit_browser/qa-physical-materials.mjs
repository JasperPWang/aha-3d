/** Targeted renderer/controls checks. Use a small fixture or the actual demo. */
import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html,out,mode='demo']=process.argv.slice(2);await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1000,height:800}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 await page.goto(/^https?:/.test(html)?html:pathToFileURL(resolve(html)).href,{timeout:120000});
 const checks=[];
 if(mode==='gallery'){
  for(const family of ['glass','ceramic','wall']){
   await page.evaluate(f=>{document.getElementById('family').value=f;document.getElementById('family').dispatchEvent(new Event('change'));},family);
   await page.waitForFunction(f=>window.materialGalleryQA?.ready&&materialGalleryQA.family===f,family,{timeout:120000});
   await page.evaluate(()=>Promise.all([...document.querySelectorAll('article:not([hidden]) img')].map(i=>i.decode())));
   const result=await page.evaluate(()=>materialGalleryQA);assert.equal(result.recipes.length,family==='wall'?3:4);checks.push(result);
   await page.screenshot({path:resolve(out,'collection-'+family+'.png'),fullPage:true,timeout:120000});
  }
 }else{
  await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});
  const target=await page.evaluate(()=>{
   const q=roomkitQA;q.lighting.setQuality('fast');if(q.tabletop)q.tabletop.paused=true;
   document.getElementById('controls-tab').click();
   const target=ROOMKIT_SCENE.objects.some(o=>o.instance_id==='tabletop-vase')?'tabletop-vase':'test-frame';
   const select=document.getElementById('objects');select.value=target;select.dispatchEvent(new Event('change'));
   if(target==='tabletop-vase')document.getElementById('table-view').click();
   window.physicalOriginal=q.pickables.map(mesh=>({mesh,material:mesh.material,geometry:mesh.geometry,shadow:mesh.castShadow,matrix:Array.from(mesh.matrix.elements)}));
   return target;
  });
  for(const preset of ['glass_clear','glass_frosted','glass_tinted','glass_ribbed','porcelain','celadon','crackle_glaze','porcelain_bluewhite','plaster','wall_paint','limewash']){
   const result=await page.evaluate(({target,preset})=>{
    const q=roomkitQA,$=id=>document.getElementById(id),arr=m=>Array.isArray(m)?m:[m];
    $('material-preset').value=preset;$('material-preset').dispatchEvent(new Event('change'));
    if([...$('material-slot').options].some(o=>o.value==='*'))$('material-slot').value='*';
    if(preset==='glass_clear'){$('material-ior').value='1.6';$('material-thickness').value='8';}
    if(preset==='porcelain'){$('material-clearcoat').value='.85';$('material-coat-roughness').value='.12';}
    $('material-apply').click();
    const recipe=q.materialLab.recipe(),seen=[];
    for(const o of physicalOriginal){
     if(JSON.stringify(o.matrix)!==JSON.stringify(Array.from(o.mesh.matrix.elements)))throw Error('Material changed placement');
     if(o.mesh.userData.owner!==target){if(o.mesh.material!==o.material)throw Error('Material leaked to another object');continue;}
     for(const m of arr(o.mesh.material).filter(m=>m?.userData.procedural?.preset===preset)){
      if(!m.map||!m.normalMap||!m.roughnessMap)throw Error('Missing generated maps');
      if(recipe.transmission>0||recipe.clearcoat>0){
       if(!m.isMeshPhysicalMaterial||!('PHYSICAL' in m.defines))throw Error('Missing physical shader');
       for(const k of ['transmission','ior','thickness','clearcoat','clearcoatRoughness'])if(m[k]!==recipe[k])throw Error('Surface control not applied: '+k);
       if(m.opacity!==1||m.transparent)throw Error('Glass must use transmission, not alpha blending');
      }else if(m.isMeshPhysicalMaterial)throw Error('Opaque wall retains physical layer');
      seen.push(m.name);
     }
    }
    if(!seen.length)throw Error('No material was applied');
    q.lighting.setQuality('balanced');q.lighting.setQuality('fast');
    for(const o of physicalOriginal.filter(o=>o.mesh.userData.owner===target))if(recipe.transmission>.5&&o.mesh.castShadow)throw Error('Lighting reset an opaque glass shadow');
    q.renderer.render(q.scene,q.camera);
    return {preset,recipe,changed:seen.length};
   },{target,preset});checks.push(result);
   if(['glass_clear','porcelain_bluewhite','plaster'].includes(preset))await page.screenshot({path:resolve(out,'physical-'+preset+'.png'),timeout:120000});
  }
  const restored=await page.evaluate(target=>{roomkitQA.materialLab.reset(target);return physicalOriginal.every(o=>o.mesh.material===o.material&&o.mesh.geometry===o.geometry&&o.mesh.castShadow===o.shadow);},target);assert.ok(restored);
  const source=await page.evaluate(()=>{
   const q=roomkitQA,native=q.pickables.find(m=>m.userData.owner==='native-glass');
   if(!native)return 'not in this scene';
   const used=native.geometry.groups.map(g=>g.materialIndex),m=used.map(i=>native.material[i]).find(m=>m?.transmission>0);
   if(!m?.isMeshPhysicalMaterial||Math.abs(m.ior-1.47)>1e-6||m.thickness!==.008)throw Error('Native Blender glass did not survive export');return true;
  });
  const actorsProtected=await page.evaluate(()=>{const q=roomkitQA;for(const a of q.actors){const original=a.mesh.material;q.materialLab.apply({preset:'glass_clear'},a.mesh.userData.owner,'*');if(a.mesh.material!==original)throw Error('Actor was modified');}return q.actors.length;});
  checks.push({restored,source,actorsProtected});
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:resolve(out,'physical-mobile.png'),fullPage:true,timeout:120000});
 }
 assert.deepEqual(errors,[]);await writeFile(resolve(out,'physical-validation.json'),JSON.stringify({passed:true,mode,checks,errors},null,2));console.log('Physical materials passed: '+mode);
}finally{await browser.close();}

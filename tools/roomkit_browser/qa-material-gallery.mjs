import {PRESETS} from './material-generator.js';
import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html,out]=process.argv.slice(2);await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1600,height:1200}}),errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 await page.goto(pathToFileURL(resolve(html)).href);
 const ready=async()=>{await page.waitForFunction(()=>window.materialGalleryQA?.ready,{},{timeout:120000});await page.evaluate(()=>Promise.all([...document.querySelectorAll('article:not([hidden]) img')].map(i=>i.decode())));};
 await ready();
 for(const version of ['3','2','1'])for(const mode of ['pbr','color']){
  await page.selectOption('#version',version);await page.selectOption('#mode',mode);await ready();
  const result=await page.evaluate(()=>materialGalleryQA);assert.equal(result.recipes.length,Object.values(PRESETS).filter(p=>version==='3'?p.since===3:(p.since??1)<=Number(version)).length);assert.ok(result.recipes.every(r=>r.version===Number(version)));checks.push(result);
  await page.screenshot({path:resolve(out,`collection-v${version}-${mode}.png`),fullPage:true});
 }
 await page.selectOption('#version','3');await page.selectOption('#family','new');await page.fill('#seed','alternative-83');await page.locator('#seed').blur();await ready();
 assert.notDeepEqual(await page.evaluate(()=>materialGalleryQA.recipes),checks[0].recipes);
 await page.screenshot({path:resolve(out,'collection-v3-alternative.png'),fullPage:true});
 const download=page.waitForEvent('download');await page.locator('article:not([hidden]) button').first().click();await (await download).saveAs(resolve(out,'glass-recipe.json'));
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:resolve(out,'collection-mobile.png'),fullPage:true});assert.deepEqual(errors,[]);
 await writeFile(resolve(out,'gallery-validation.json'),JSON.stringify({passed:true,checks,mobile:true,download:true,errors},null,2));
 console.log('Material collection QA passed');
}finally{await browser.close();}

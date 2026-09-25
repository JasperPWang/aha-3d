import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';

const [url,outArg]=process.argv.slice(2),out=resolve(outArg),results=[];
await mkdir(out,{recursive:true});
for(const mode of ['default-browser','software-browser','reject-standard','reject-all','disabled-webgl']){
 const args=['--no-sandbox'];
 if(mode==='disabled-webgl')args.push('--disable-webgl');
 else if(mode!=='default-browser')args.push('--use-angle=swiftshader','--enable-unsafe-swiftshader');
 const browser=await chromium.launch({headless:true,args});
 try{
  const page=await browser.newPage({viewport:{width:1200,height:950}});
  if(mode==='reject-standard'||mode==='reject-all')await page.addInitScript(mode=>{
   const original=HTMLCanvasElement.prototype.getContext;
   HTMLCanvasElement.prototype.getContext=function(type,options){
    if(type==='webgl2'&&!window.top.__qaAllowContext&&(mode==='reject-all'||options?.antialias)){
     this.dispatchEvent(new WebGLContextEvent('webglcontextcreationerror',{statusMessage:'Deliberate QA context rejection: '+mode}));return null;
    }
    return original.call(this,type,options);
   };
  },mode);
  await page.goto(url+'#clip32');
  const settled=()=>page.waitForFunction(()=>document.getElementById('status').textContent.startsWith('Ready')||!document.getElementById('retry').hidden,null,{timeout:120000});
  await settled();
  const report=await page.evaluate(()=>({status:document.getElementById('status').textContent,diagnostic:document.querySelector('iframe').contentWindow.roomkitRendererDiagnostic,details:document.getElementById('diagnostic-text').textContent}));
  if(mode==='reject-all'||mode==='disabled-webgl'){
   assert.equal(report.diagnostic.status,'failed');assert.equal(report.diagnostic.attempts.length,3);
   assert.ok(!report.status.startsWith('Ready'));assert.ok(report.details.includes('attempts'));
   if(mode==='reject-all'){
    await page.evaluate(()=>window.__qaAllowContext=true);await page.click('#retry');await settled();
    assert.ok((await page.locator('#status').textContent()).startsWith('Ready'));report.retryRecovered=true;
   }
  }else if(mode==='default-browser'){
   // Record the real host outcome; do not turn a disabled default driver into
   // a pass using software flags or claim it represents the user's browser.
   report.defaultBrowserReady=report.diagnostic.status==='ready';
  }else{
   assert.equal(report.diagnostic.status,'ready');
   if(mode==='reject-standard')assert.equal(report.diagnostic.profile,'compatible');
   await page.evaluate(async()=>{await document.querySelector('iframe').contentWindow.roomkitQA.seek(90);});
   const state=await page.evaluate(()=>{const w=document.querySelector('iframe').contentWindow,q=w.roomkitQA;return {frame:q.shownFrame,actors:q.actors.length,attributes:q.renderer.getContext().getContextAttributes(),quality:q.lighting.quality};});
   assert.equal(state.frame,90);assert.equal(state.actors,3);
   if(mode==='reject-standard'){assert.equal(state.attributes.antialias,false);assert.equal(state.attributes.preserveDrawingBuffer,false);assert.equal(state.quality,'fast');}
   report.renderState=state;
  }
  await page.screenshot({path:resolve(out,mode+'.png'),timeout:120000});
  results.push({mode,...report});console.log(mode,report.diagnostic.status,report.diagnostic.profile||'');
 }finally{await browser.close();}
}
await writeFile(resolve(out,'validation.json'),JSON.stringify({passed:true,scope:'Host-browser tests and explicitly simulated context rejection; client failure remains unconfirmed',results},null,2));

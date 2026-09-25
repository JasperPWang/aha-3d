import {chromium} from 'playwright';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:http';
import {gunzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
import {readFile,writeFile,stat} from 'node:fs/promises';
import {resolve,dirname,basename,extname} from 'node:path';
import assert from 'node:assert/strict';
const [html,out]=process.argv.slice(2),root=dirname(resolve(html)),requests=[],errors=[];
let failSegments=false,failProps=false;
const server=createServer(async(req,res)=>{try{const p=resolve(root,'.'+decodeURIComponent(req.url));if(!p.startsWith(root+'/'))throw Error('Path');
 if((failSegments&&p.endsWith('.bin.gz'))||(failProps&&p.endsWith('.props.json.gz'))){res.writeHead(503);res.end();return;}
 const bytes=await readFile(p);res.setHeader('Content-Type',extname(p)==='.js'?'text/javascript':extname(p)==='.html'?'text/html':'application/octet-stream');res.end(bytes);
 }catch{res.writeHead(404);res.end();}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:960}});page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 const start=Date.now();await page.goto(`http://127.0.0.1:${server.address().port}/${basename(html)}`);await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});
 const readyMs=Date.now()-start,initialRequests=[...requests];assert.equal(initialRequests.filter(x=>x.endsWith('.bin.gz')||x.endsWith('.props.json.gz')).length,0);
 await page.screenshot({timeout:120000,path:resolve(out,'fast-orbit.png')});await page.click('#plan');await page.screenshot({timeout:120000,path:resolve(out,'fast-plan.png')});await page.click('#controls-tab');
 const timing=await page.evaluate(()=>({frames:ROOMKIT_SCENE.animation?.frames||0,fps:ROOMKIT_SCENE.animation?.fps||0}));
 if(timing.frames>1){
  failSegments=true;await page.locator('#timeline').evaluate((t)=>{t.value=1;t.dispatchEvent(new Event('input'));});await page.waitForFunction(()=>document.getElementById('play').textContent==='Retry');
  failSegments=false;await page.click('#play');await page.waitForFunction(()=>roomkitQA.shownFrame>0);await page.click('#play');
 }
 const hasLazyProps=await page.evaluate(()=>ROOMKIT_SCENE.tabletop?.templates.some(t=>t.meshes_url));
 if(hasLazyProps){failProps=true;const result=await page.evaluate(async()=>{const q=roomkitQA,before=q.tabletop.layout;const applied=await q.tabletop.regenerate('stream-test');return {before,after:q.tabletop.layout,applied};});assert.equal(result.applied,false);assert.deepEqual(result.after,result.before);failProps=false;}
 const evidence=await page.evaluate(async()=>{const d=ROOMKIT_SCENE,q=roomkitQA;let checked=0;
  for(const f of d.animation?[...new Set([0,1,Math.min(d.animation.frames-1,Math.round(d.animation.fps*2)),Math.floor(d.animation.frames/2),d.animation.frames-1])]:[]){await q.seek(f);for(const a of q.actors){const array=a.mesh.geometry.attributes.position.array;const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',array))].map(x=>x.toString(16).padStart(2,'0')).join('');if(hash!==a.checks[f].sha256)throw Error('Frame mismatch '+f);}checked++;}
  return {checkedFrames:checked,actors:q.actors.length};});
 assert.equal(await page.locator('#error').textContent(),'');assert.deepEqual(errors,[]);
 const manifest=JSON.parse(await readFile(html+'.json','utf8'));const scene=JSON.parse(gunzipSync(await readFile(resolve(root,manifest.initial_files[0]))));let verifiedFrames=0;for(const actor of scene.animation?.actors||[]){for(const segment of actor.segments){const bytes=gunzipSync(await readFile(resolve(root,segment.url)));for(let i=0;i<segment.frames;i++){const stride=actor.vertex_count*12;assert.equal(createHash('sha256').update(bytes.subarray(i*stride,(i+1)*stride)).digest('hex'),actor.checks[segment.start+i].sha256);verifiedFrames++;}}}let initialBytes=(await stat(html)).size;for(const p of manifest.initial_files)initialBytes+=(await stat(resolve(root,p))).size;
 await writeFile(resolve(out,'streaming-validation.json'),JSON.stringify({passed:true,readyMs,initialBytes,verifiedFrames,initialRequests,animationRequests:requests.filter(x=>x.endsWith('.bin.gz')).length,...evidence,errors},null,2));
 await page.close();
 await promisify(execFile)('node',[fileURLToPath(new URL('./qa-scene-graph.mjs',import.meta.url)),`http://127.0.0.1:${server.address().port}/${basename(html)}`,out],{maxBuffer:1024*1024});
 console.log(JSON.stringify({passed:true,readyMs,initialBytes,...evidence}));
}finally{await browser.close();await new Promise(r=>server.close(r));}

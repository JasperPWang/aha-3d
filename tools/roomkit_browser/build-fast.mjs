import {writeFile,mkdir,readFile} from 'node:fs/promises';
import {dirname,basename,join} from 'node:path';
import {createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
export async function buildFast(data,template,viewerCode,output,sourceDir=dirname(output)){
 const folder=join(dirname(output),basename(output,'.html')+'-assets');await mkdir(folder,{recursive:false});
 const files=[];
 async function asset(bytes,suffix){
  const name=createHash('sha256').update(bytes).digest('hex')+'.'+suffix;
  await writeFile(join(folder,name),bytes);const url=basename(folder)+'/'+name;files.push(url);return url;
 }
 const scene=structuredClone(data);
 for(const actor of scene.animation?.actors||[]){
  if(actor.positions_file&&basename(actor.positions_file)!==actor.positions_file)throw Error('Actor sidecar must be adjacent to scene JSON');
  const bytes=actor.positions_file?await readFile(join(sourceDir,actor.positions_file)):Buffer.from(actor.positions_base64,'base64');delete actor.positions_base64;delete actor.positions_file;
  const stride=actor.vertex_count*12,step=Math.max(1,Math.round(scene.animation.fps*2));
  if(bytes.length!==scene.animation.frames*stride)throw Error('Animation byte count mismatch');
  actor.segments=[];
  for(let start=0;start<scene.animation.frames;start+=step){const frames=Math.min(step,scene.animation.frames-start);
   actor.segments.push({start,frames,url:await asset(gzipSync(bytes.subarray(start*stride,(start+frames)*stride)), 'bin.gz')});}
 }
 const sourceProps=new Set(scene.tabletop?.supports.flatMap(s=>s.source_ids)||[]);
 for(const template of scene.tabletop?.templates||[]){if(sourceProps.has(template.id))continue;
  template.meshes_url=await asset(gzipSync(Buffer.from(JSON.stringify(template.meshes))),'props.json.gz');delete template.meshes;
 }
 const sceneUrl=await asset(gzipSync(Buffer.from(JSON.stringify(scene))),'json.gz');
 const viewerUrl=await asset(Buffer.from(viewerCode),'js');
 const boot=`(async()=>{try{if(location.protocol==='file:')throw Error('Open this fast demo through HTTP, or use the single-file offline demo.');const response=await fetch(${JSON.stringify(sceneUrl)});if(!response.ok)throw Error('Scene download failed ('+response.status+')');window.ROOMKIT_SCENE=JSON.parse(await new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).text());const script=document.createElement('script');script.src=${JSON.stringify(viewerUrl)};script.onerror=()=>{document.getElementById('error').textContent='Viewer download failed. Reload to retry.';};document.body.append(script);}catch(e){document.getElementById('error').textContent=e.message;}})();`;
 await writeFile(output,template.replace('/*SCENE_DATA*/','').replace('/*VIEWER_CODE*/',()=>boot),{flag:'wx'});
 const manifest={schema_version:1,entry:basename(output),files,initial_files:[sceneUrl,viewerUrl],segment_seconds:2,lossless:true};
 await writeFile(output+'.json',JSON.stringify(manifest,null,2),{flag:'wx'});
}

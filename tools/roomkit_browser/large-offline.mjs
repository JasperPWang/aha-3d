// Write actors separately so no intermediate string contains the whole clip.
import {open,readFile} from 'node:fs/promises';
import {basename,join} from 'node:path';
import {gzipSync} from 'node:zlib';
export async function writeLargeOffline(data,template,viewerCode,sourceDir,output){
 const marker='<script>/*SCENE_DATA*/</script>';
 if(!template.includes(marker))throw Error('Missing scene-data marker');
 const [before,after]=template.split(marker);
 const safe=JSON.stringify(data).replaceAll('<','\\u003c');
 const file=await open(output,'wx');
 try{
  await file.writeFile(before+'<script>window.ROOMKIT_SCENE='+safe+';</script>');
  for(const [i,actor] of data.animation.actors.entries()){
   if(!actor.positions_file)continue;
   if(basename(actor.positions_file)!==actor.positions_file)throw Error('Actor sidecar must be adjacent to scene JSON');
   const bytes=await readFile(join(sourceDir,actor.positions_file));
   if(bytes.length!==data.animation.frames*actor.vertex_count*12)throw Error('Invalid actor sidecar size');
   const packed=gzipSync(bytes,{level:6}).toString('base64');
   await file.writeFile(`<script type="application/octet-stream" id="roomkit-actor-${i}">`);
   await file.writeFile(packed);await file.writeFile('</script>');
  }
  const boot=`(async()=>{try{for(const [i,actor] of window.ROOMKIT_SCENE.animation.actors.entries()){const element=document.getElementById('roomkit-actor-'+i);if(!element)continue;const encoded=element.textContent;element.remove();const binary=atob(encoded),bytes=new Uint8Array(binary.length);for(let j=0;j<binary.length;j++)bytes[j]=binary.charCodeAt(j);actor.positions_buffer=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();if(actor.positions_buffer.byteLength!==window.ROOMKIT_SCENE.animation.frames*actor.vertex_count*12)throw Error('Invalid offline actor size');delete actor.positions_file;}${viewerCode}}catch(e){document.getElementById('error').textContent='Scene loading failed: '+e.message;console.error(e);}})();`;
  await file.writeFile(after.replace('/*VIEWER_CODE*/',()=>boot.replaceAll('</script','<\\/script')));
 }finally{await file.close();}
}

import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {gunzipSync} from 'node:zlib';
import {writeLargeOffline} from './large-offline.mjs';
import {buildFast} from './build-fast.mjs';
const template='<html><body><p id="error"></p><script>/*SCENE_DATA*/</script><script>/*VIEWER_CODE*/</script></body></html>';
test('binary sidecars preserve bytes in fast segments and separate offline actor blocks',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'roomkit-large-'));
 try{
  const bytes=Buffer.from(new Float32Array([1,2,3,4,5,6]).buffer);await writeFile(join(dir,'actor.f32'),bytes);
  const data={animation:{frames:2,fps:1,actors:[{mesh_name:'person',vertex_count:1,positions_file:'actor.f32'}]}};
  await buildFast(data,template,'',join(dir,'fast.html'),dir);
  const manifest=JSON.parse(await readFile(join(dir,'fast.html.json'),'utf8'));
  const scene=JSON.parse(gunzipSync(await readFile(join(dir,manifest.initial_files[0]))));
  assert.equal(scene.animation.actors[0].positions_file,undefined);
  assert.deepEqual(gunzipSync(await readFile(join(dir,scene.animation.actors[0].segments[0].url))),bytes);
  await writeLargeOffline(data,template,'',dir,join(dir,'offline.html'));
  const html=await readFile(join(dir,'offline.html'),'utf8');
  const encoded=html.match(/id="roomkit-actor-0">([^<]+)<\/script>/)[1];
  assert.deepEqual(gunzipSync(Buffer.from(encoded,'base64')),bytes);
  const invalid={animation:{...data.animation,frames:3}};
  await assert.rejects(writeLargeOffline(invalid,template,'',dir,join(dir,'bad.html')),/size/);
  const unsafe={animation:{frames:2,actors:[{vertex_count:1,positions_file:'../actor.f32'}]}};
  await assert.rejects(writeLargeOffline(unsafe,template,'',dir,join(dir,'unsafe.html')),/adjacent/);
 }finally{await rm(dir,{recursive:true,force:true});}
});

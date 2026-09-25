import test from 'node:test';
import assert from 'node:assert/strict';
import {gzipSync} from 'node:zlib';
import {createAnimationStream} from './streaming.js';
test('cached animation frames are synchronous; failures retry and segments evict',async()=>{
 const original=globalThis.fetch,counts=new Map();let fail=true;
 globalThis.fetch=async url=>{counts.set(url,(counts.get(url)||0)+1);if(url==='0'&&fail)return new Response('',{status:503});
  return new Response(gzipSync(Buffer.from(new Float32Array([Number(url),2,3]).buffer)));};
 try{
  const stream=createAnimationStream({actors:[{mesh_name:'person',vertex_count:1,segments:Array.from({length:5},(_,i)=>({start:i,frames:1,url:String(i)}))}]});
  assert.equal(stream.peek(0),null);await assert.rejects(stream.frame(0),/503/);fail=false;
  await Promise.all([stream.frame(0),stream.frame(0)]);assert.equal(counts.get('0'),2);
  assert.deepEqual([...stream.peek(0)[0]],[0,2,3]);
  for(let i=1;i<5;i++)await stream.frame(i);
  assert.equal(stream.peek(0),null);assert.deepEqual([...stream.peek(4)[0]],[4,2,3]);
 }finally{globalThis.fetch=original;}
});

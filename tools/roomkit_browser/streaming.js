// Lossless animation segments. Keep first-frame geometry usable without network I/O.
export function createAnimationStream(animation) {
 const caches=new Map(), pending=new Map();
 async function load(actor,index){
  const key=actor.mesh_name+':'+index;
  if(caches.has(key)){const value=caches.get(key);caches.delete(key);caches.set(key,value);return value;}
  if(pending.has(key))return pending.get(key);
  const segment=actor.segments[index];
  const task=(async()=>{
   const response=await fetch(segment.url);if(!response.ok)throw Error('Animation download failed ('+response.status+')');
   const bytes=await new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
   if(bytes.byteLength!==segment.frames*actor.vertex_count*12)throw Error('Invalid animation segment');
   const value=new Float32Array(bytes);caches.set(key,value);
   while(caches.size>Math.max(3,animation.actors.length*3))caches.delete(caches.keys().next().value);
   return value;
  })();pending.set(key,task);
  try{return await task;}finally{pending.delete(key);}
 }
 function indexFor(actor,frame){return actor.segments.findIndex(s=>frame>=s.start&&frame<s.start+s.frames);}
 async function frame(frame){return Promise.all(animation.actors.map(async actor=>{
  const index=indexFor(actor,frame);if(index<0)throw Error('Frame outside animation');
  const segment=actor.segments[index],values=await load(actor,index),offset=(frame-segment.start)*actor.vertex_count*3;
  return values.subarray(offset,offset+actor.vertex_count*3);
 }));}
 function prefetch(frame){for(const actor of animation.actors){const next=indexFor(actor,frame)+1;if(next<actor.segments.length)load(actor,next).catch(()=>{});}}
 function peek(frame){
  const values=[];
  for(const actor of animation.actors){const index=indexFor(actor,frame),segment=actor.segments[index],bytes=caches.get(actor.mesh_name+':'+index);if(!bytes)return null;
   const offset=(frame-segment.start)*actor.vertex_count*3;values.push(bytes.subarray(offset,offset+actor.vertex_count*3));}
  return values;
 }
 return {frame,prefetch,peek};
}

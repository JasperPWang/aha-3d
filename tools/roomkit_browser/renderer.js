// Try independent canvases: a failed context must not contaminate a retry.
// No WebGL1 fallback: the maintained Three.js renderer requires WebGL2.
export function createRenderer(Renderer, initialCanvas, {report=()=>{}}={}) {
 const attempts=[],profiles=[
  {name:'standard',antialias:true,preserveDrawingBuffer:true,powerPreference:'default'},
  {name:'compatible',antialias:false,preserveDrawingBuffer:false,powerPreference:'default'},
  {name:'low-power',antialias:false,preserveDrawingBuffer:false,powerPreference:'low-power'},
 ];
 let canvas=initialCanvas;
 for(const profile of profiles){
  const {name,...options}=profile;
  const record={profile:name,options,status:'starting',messages:[]};attempts.push(record);
  const listener=e=>record.messages.push(e.statusMessage||'Context creation was rejected without a status message');
  canvas.addEventListener('webglcontextcreationerror',listener);
  let gl;
  try{
   gl=canvas.getContext('webgl2',{...options,alpha:false,depth:true,stencil:false,failIfMajorPerformanceCaveat:false});
   if(!gl)throw Error('Browser returned no WebGL2 context');
   const renderer=new Renderer({canvas,context:gl,...options});
   record.status='created';record.attributes=gl.getContextAttributes();
   report({status:'ready',profile:name,attempts});
   return {renderer,canvas,profile:name};
  }catch(error){
   record.status='failed';record.error=error.message;
   gl?.getExtension('WEBGL_lose_context')?.loseContext();
   report({status:'trying',attempts});
  }finally{canvas.removeEventListener('webglcontextcreationerror',listener);}
  if(profile!==profiles.at(-1)){
   const next=canvas.cloneNode(false);canvas.replaceWith(next);canvas=next;
  }
 }
 const diagnostic={status:'failed',attempts};report(diagnostic);
 const reason=attempts.flatMap(a=>a.messages).at(-1)||attempts.at(-1).error;
 throw Error('WebGL2 context creation failed for standard and reduced-resource settings. '+reason);
}

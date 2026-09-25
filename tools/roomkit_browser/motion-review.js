const $=id=>document.getElementById(id);
let cases=[],current=null,iframe=null,serial=0,lastCase=null;
const options=(element,rows)=>element.replaceChildren(...rows.map(row=>{
 const option=document.createElement('option');option.value=row.id;option.textContent=row.title||row.label;return option;
}));
function release(){
 if(!iframe)return;
 // Explicitly release the old canvas before starting another scene. Removing
 // the iframe also stops its animation loop and drops its decoded motion cache.
 try{const q=iframe.contentWindow.roomkitQA;q?.renderer.dispose();q?.renderer.forceContextLoss();}catch{}
 iframe.remove();iframe=null;
}
async function load(){
 const token=++serial,entry=current,variant=entry.variants.find(v=>v.id===$('variant').value);
 let previous=null;
 try{const q=iframe?.contentWindow.roomkitQA;if(lastCase===entry.id&&q?.ready)previous={frame:q.shownFrame,position:q.camera.position.toArray(),target:q.controls.target.toArray()};}catch{}
 release();lastCase=entry.id;
 $('status').textContent='Loading '+variant.label+'…';$('retry').hidden=true;
 $('diagnostics').hidden=true;
 $('direct').href=variant.url;history.replaceState(null,'','#'+entry.id);
 const frame=document.createElement('iframe');frame.title=entry.title+' · '+variant.label;frame.src=variant.url;iframe=frame;$('viewer').append(frame);
 const deadline=performance.now()+120000;
 try{
  while(token===serial){
   const win=frame.contentWindow,err=win.document.getElementById('error')?.textContent;
   if(err)throw Error(err);
   if(win.roomkitQA?.ready){
    const q=win.roomkitQA;
    win.document.getElementById('controls-tab')?.click();
    if(previous){q.camera.position.fromArray(previous.position);q.controls.target.fromArray(previous.target);q.controls.update();await q.seek(Math.min(previous.frame,win.ROOMKIT_SCENE.animation.frames-1));}
    if(token!==serial)return;
    $('status').textContent='Ready · '+entry.title+' · '+variant.label;return;
   }
   if(performance.now()>deadline)throw Error('Loading timed out. Retry, or open this viewer alone.');
   await new Promise(resolve=>setTimeout(resolve,100));
  }
 }catch(error){if(token===serial){
  $('status').textContent=error.message;$('retry').hidden=false;
  const diagnostic={error:error.message,embedded:window.top!==window,renderer:frame.contentWindow.roomkitRendererDiagnostic||null};
  $('diagnostic-text').textContent=JSON.stringify(diagnostic,null,2);$('diagnostics').hidden=false;$('diagnostics').open=true;
 }}
}
function select(){
 current=cases.find(c=>c.id===$('case').value);options($('variant'),current.variants);
 $('note').textContent=current.note;$('source').pause();
 $('source-panel').hidden=!current.source_video;
 $('video-link').hidden=!current.source_video;
 $('video-label').textContent=current.video_label||'Source video';
 $('video-note').textContent=current.video_note||'Independent playback; use the same timestamp when comparing.';
 if(current.source_video)$('source').src=current.source_video;else{$('source').removeAttribute('src');$('source').load();}
 load();
}
try{
 const response=await fetch('manifest.json');if(!response.ok)throw Error('Scene list download failed ('+response.status+')');
 ({cases}=await response.json());options($('case'),cases);
 const id=decodeURIComponent(location.hash.slice(1));if(cases.some(c=>c.id===id))$('case').value=id;
 $('case').onchange=select;$('variant').onchange=load;$('retry').onclick=load;
 $('copy-diagnostic').onclick=async()=>{try{await navigator.clipboard.writeText($('diagnostic-text').textContent);$('copy-diagnostic').textContent='Copied';}catch{$('copy-diagnostic').textContent='Select and copy the diagnostic text above';}};
 addEventListener('pagehide',()=>{serial++;release();});select();
}catch(error){$('status').textContent=error.message;}

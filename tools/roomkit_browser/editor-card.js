import {PRESETS, generate} from './material-generator.js';

/** Compact, opt-in editor. Move existing controls rather than running a second viewer. */
export function createEditorCard(api, data) {
  const config=data.quick_actions?.editor_card;
  if(!api?.ready || !config)return;
  const $=id=>document.getElementById(id), main=document.querySelector('main');
  document.documentElement.classList.add('roomkit-editor');
  const style=document.createElement('style');
  style.textContent=`
    .roomkit-editor main,.roomkit-editor.article-embed main,.roomkit-editor.article-embed main.inspector-open{display:grid;grid-template-columns:228px minmax(0,1fr);grid-template-rows:minmax(0,1fr);min-height:0;overflow:hidden}
    .roomkit-editor #stage,.roomkit-editor.article-embed #stage{grid-column:2;grid-row:1;min-height:0;height:auto}
    .roomkit-editor main>aside{display:none!important}
    .roomkit-editor #toolbar>button[aria-controls="embed-inspector"]{display:none}
    #editor-panel{grid-column:1;grid-row:1;min-width:0;min-height:0;overflow:auto;padding:12px;background:#eef0e8;border-right:1px solid #d6dccf;display:flex;flex-direction:column;gap:10px}
    #editor-panel .finish-card{flex-shrink:0;background:#fffef9;border:1px solid #d6dccf;border-radius:9px;padding:13px 12px;box-shadow:0 4px 14px #263a2408;min-width:0}
    #editor-panel h2{font:20px Georgia,serif;letter-spacing:0;color:#29342a;margin:0 0 9px}
    #editor-panel .card-intro{font:11px/1.5 system-ui,sans-serif;color:#6a7567;margin:0 0 10px}
    #editor-panel label{font-size:10px;font-weight:550;color:#687462;display:block}
    #editor-panel select{width:100%;min-width:0;padding:7px 8px;border:1px solid #d1d8ca;border-radius:5px;background:#f6f7f0;color:#39543d;font-size:11px;margin:4px 0 9px;height:33px;text-overflow:ellipsis}
    #editor-panel .finish-swatches{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin:8px 0}
    #editor-panel .finish-swatch{position:relative;display:block;justify-self:center;width:36px;height:36px;padding:2px;border:2px solid transparent;border-radius:50%;background:#fffef9;transition:transform .15s,border-color .15s;isolation:isolate}
    #editor-panel .finish-swatch canvas{display:block;width:100%;height:100%;border-radius:50%;box-shadow:inset 0 0 0 1px #0001}
    #editor-panel .finish-swatch:after{content:'';position:absolute;inset:4px;border-radius:50%;background:radial-gradient(circle at 32% 24%,#ffffff36,transparent 60%,#00000012);pointer-events:none}
    #editor-panel .finish-swatch:hover:not(:disabled){transform:translateY(-2px)}
    #editor-panel .finish-swatch[aria-pressed=true]{border-color:#39543d}
    #editor-panel .swatch-check{display:none;position:absolute;right:-2px;bottom:-2px;z-index:1;width:14px;height:14px;border:2px solid #fffef9;border-radius:50%;background:#39543d;color:white;font:8px/10px Arial;text-align:center}
    #editor-panel .finish-swatch[aria-pressed=true] .swatch-check{display:block}
    #editor-panel button:focus-visible{outline:2px solid #719e87;outline-offset:3px}
    #editor-panel #finish-caption{font-size:10px;line-height:1.5;color:#61705b;margin:6px 0;min-height:15px}
    #editor-panel #material-reset{font-size:10px;padding:5px 0;background:transparent;border:0;text-decoration:underline;text-underline-offset:3px;color:#52684c}
    #editor-panel details{margin:9px 0 0;padding:0;border:0;border-top:1px solid #e3e6dc;border-radius:0}
    #editor-panel summary{padding:9px 0 0;font-size:10px;color:#687462;font-weight:500}
    #editor-panel details[open]>summary{margin-bottom:10px}
    #editor-panel #material-lab{border:0;margin:0;padding:0}
    #editor-panel #material-lab>h2,#editor-panel #material-lab>label[for="material-slot"],#editor-panel #material-target,#editor-panel label[for="material-preset"]:not(.card-label){display:none}
    #editor-panel .material-preview-row{display:flex;gap:8px;align-items:center;margin:8px 0}
    #editor-panel #material-preview{width:54px;height:54px;flex:0 0 54px}
    #editor-panel #material-lab .actions{display:block;margin:8px 0}
    #editor-panel #material-apply,#editor-panel #material-download{font-size:10px;padding:7px;width:100%}
    #editor-panel #material-lab p,#editor-panel #lighting-controls p{font-size:10px}
    #editor-panel .material-fields{grid-template-columns:1fr;gap:6px}
    #editor-panel #scene-actions{position:static;display:flex;gap:7px;padding:0;border:0;border-radius:0;background:transparent;box-shadow:none;align-items:stretch}
    #editor-panel #scene-actions button{font-size:10px;padding:8px 7px;border-radius:5px;min-height:32px}
    #editor-panel #quick-layout{order:-5;flex:0 0 100%;font-size:11px;background:#39543d}
    #editor-panel #quick-restore{order:-4;flex:0 0 100%;background:#f6f7f0;color:#39543d}
    #editor-panel #quick-doors,#editor-panel #lamps{flex:1;white-space:normal;background:#f6f7f0;color:#39543d;border:1px solid #d1d8ca}
    #editor-panel #lamps[aria-pressed=true]{background:#e5eddf}
    #editor-panel #quick-state{order:-3;flex:0 0 100%;font-size:10px;margin:0;color:#687462}
    #editor-panel .action-note{font-size:10px;line-height:1.5;margin:2px 0 0;color:#687462}
    #editor-panel #lighting-controls h2{font:13px system-ui,sans-serif;margin-top:10px}
    #editor-panel #status{font-size:10px;line-height:1.5;margin:8px 0 0}
    #editor-panel #reset-layout{font-size:10px;width:100%;padding:7px}
    #editor-panel #scene-tree{max-height:240px}
    #editor-panel .card-label{font-size:10px;line-height:12px}
    #editor-panel select{height:29px;margin:3px 0 7px;padding:5px 7px}
    #editor-panel .finish-state{display:flex;align-items:center;justify-content:space-between;gap:5px;margin-top:6px}
    #editor-panel .finish-state #finish-caption{margin:0}
    #editor-panel #material-reset{flex-shrink:0;padding:3px 0}
    #editor-panel #all-finishes{margin-top:3px}
    #editor-panel #scene-actions #quick-state{order:-4;flex:1;align-self:center;margin:0;font-size:10px}
    #editor-panel #scene-actions #quick-restore{order:-3;flex:0 0 auto;min-height:22px;padding:3px 4px;border:0;background:transparent;text-decoration:underline;text-underline-offset:3px}
    #editor-panel #scene-actions{display:grid;grid-template-columns:1fr 1fr}
    #editor-panel #scene-actions #quick-layout{grid-column:1 / -1}
    #editor-panel #scene-actions #quick-state{order:-4}
    #editor-panel #scene-actions #quick-restore{order:-3}
    #editor-panel #scene-actions .action-note{display:none}
    #editor-panel #status:empty{display:none}
    @media(max-width:680px){
      .roomkit-editor main,.roomkit-editor.article-embed main,.roomkit-editor.article-embed main.inspector-open{height:100dvh;grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(230px,1fr) minmax(0,250px)}
      .roomkit-editor:not(.article-embed) main{height:calc(100dvh - 66px)}
      .roomkit-editor #stage,.roomkit-editor.article-embed #stage{grid-column:1;grid-row:1}
      #editor-panel{grid-column:1;grid-row:2;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);grid-template-rows:minmax(0,1fr);padding:8px;gap:8px;border-right:0;border-top:1px solid #d6dccf;overflow:hidden}
      #editor-panel .finish-card{padding:10px 9px;overflow:auto;min-height:0}
      #editor-panel h2{font-size:17px}
      #editor-panel .finish-swatches{gap:4px}
      #editor-panel .finish-swatch{width:30px;height:30px}
      #editor-panel .card-intro{font-size:10px;margin-bottom:8px}
    }
    @media(prefers-reduced-motion:reduce){#editor-panel .finish-swatch{transition:none}}
  `;
  document.head.append(style);
  const panel=document.createElement('section');panel.id='editor-panel';panel.setAttribute('aria-label','Scene interactions');main.prepend(panel);
  const finishes=document.createElement('section');finishes.className='finish-card';finishes.id='finish-card';panel.append(finishes);
  finishes.innerHTML='<h2>Materials</h2><p class="card-intro">Click a finish to apply it.</p>';
  function field(parent,id,label){const el=$(id),tag=document.createElement('label');tag.htmlFor=id;tag.textContent=label;tag.className='card-label';parent.append(tag,el);return el;}
  const objects=field(finishes,'objects','Object'),slot=field(finishes,'material-slot','Surface');
  const swatches=document.createElement('div');swatches.className='finish-swatches';swatches.setAttribute('role','group');swatches.setAttribute('aria-label','Quick material finishes');finishes.append(swatches);
  const preset=$('material-preset');
  const featured=config.presets || ['marble','travertine','terrazzo','walnut','oak','linen','leather','porcelain'];
  for(const key of featured){
    if(!PRESETS[key])continue;
    const button=document.createElement('button');button.type='button';button.className='finish-swatch';button.dataset.finish=key;button.title=PRESETS[key].label;button.setAttribute('aria-label',PRESETS[key].label);button.setAttribute('aria-pressed','false');
    const canvas=document.createElement('canvas');canvas.width=canvas.height=64;canvas.setAttribute('aria-hidden','true');
    const tile=generate({preset:key,seed:'card-preview'},64);canvas.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(tile.baseColor),64,64),0,0);
    const check=document.createElement('span');check.className='swatch-check';check.setAttribute('aria-hidden','true');check.textContent='✓';button.append(canvas,check);swatches.append(button);
    button.onclick=()=>{preset.value=key;preset.dispatchEvent(new Event('change',{bubbles:true}));};
  }
  const all=document.createElement('details');all.id='all-finishes';all.innerHTML=`<summary>All ${Object.keys(PRESETS).length} finishes</summary>`;finishes.append(all);field(all,'material-preset','Material');
  const caption=document.createElement('p');caption.id='finish-caption';caption.setAttribute('role','status');caption.setAttribute('aria-live','polite');const finishState=document.createElement('div');finishState.className='finish-state';finishes.append(finishState);finishState.append(caption,$('material-reset'));$('material-reset').textContent='Restore';$('material-reset').setAttribute('aria-label','Restore original materials');
  const advanced=document.createElement('details');advanced.innerHTML='<summary>Adjust finish</summary>';finishes.append(advanced);advanced.append($('material-lab'));
  const layout=document.createElement('section');layout.className='finish-card';layout.id='layout-card';layout.innerHTML='<h2>Tabletop layout</h2>';panel.append(layout);layout.append($('scene-actions'));
  const settings=document.createElement('details');settings.innerHTML='<summary>Scene details</summary>';layout.append(settings);settings.append($('lighting-controls'),$('reset-layout'),$('scene-inspector'));
  layout.append($('status'));
  $('quick-restore').textContent='Restore';$('quick-restore').setAttribute('aria-label','Restore original tabletop');
  $('hint').hidden=false;$('hint').textContent='Drag to look around · hold objects to move them';
  settings.addEventListener('toggle',()=>{$('graph-panel').hidden=!settings.open;if(settings.open)api.sceneGraph.refresh(true);});


  function sync(){
    const id=objects.value, active=[];
    for(const mesh of api.pickables){if(mesh.userData.owner!==id)continue;
      for(const group of mesh.geometry.groups){const material=mesh.material[group.materialIndex];if(material&&(slot.value==='*'||material.name===slot.value))active.push(material.userData.procedural?.preset || null);}
    }
    const current=active.length&&active.every(p=>p===active[0])?active[0]:null;
    caption.textContent=current?PRESETS[current]?.label || 'Current finish':id?'Click a swatch to apply':'Select an object in the room';
    for(const button of swatches.children){button.disabled=$('material-apply').disabled;button.setAttribute('aria-pressed',String(button.dataset.finish===current));}
    preset.disabled=$('material-apply').disabled;
    if(current&&PRESETS[current]&&preset.value!==current){preset.value=current;preset.onchange?.();}
  }
  // The native handler prepares color and surface defaults before this listener applies them.
  preset.addEventListener('change',()=>{$('material-apply').click();sync();});
  $('material-apply').addEventListener('click',sync);
  $('material-reset').addEventListener('click',sync);
  slot.addEventListener('change',sync);
  new MutationObserver(sync).observe(slot,{childList:true});
  if(config.default_object && data.objects.some(o=>o.instance_id===config.default_object)){
    objects.value=config.default_object;objects.dispatchEvent(new Event('change',{bubbles:true}));
    if([...slot.options].some(o=>o.value===config.default_surface))slot.value=config.default_surface;
  }
  sync();
}

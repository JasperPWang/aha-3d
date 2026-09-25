/** Scene-advertised shortcuts; delegates doors and lighting to the existing controls. */
export function createQuickActions(api, data) {
  if (!api?.ready || !data.quick_actions) return;
  const $ = id => document.getElementById(id), config = data.quick_actions;
  const style = document.createElement('style');
  style.textContent = `
    #scene-actions{position:absolute;bottom:12px;left:12px;right:12px;display:flex;align-items:center;flex-wrap:wrap;gap:7px;padding:11px 13px;border:1px solid #d4ddd2;border-radius:12px;background:#fffefaf5;box-shadow:0 4px 24px #23352b18;z-index:3}
    #scene-actions button{font-size:12px;padding:9px 12px;white-space:nowrap}
    #scene-actions .primary{background:#315e4b;color:white;border-color:#315e4b}
    #scene-actions .action-note{font-size:11px;color:#647369;flex-basis:100%;margin:0}
    #scene-actions #quick-state{margin-left:auto;font-size:11px;color:#516356}
    #scene-actions button:focus-visible{outline:3px solid #719e87;outline-offset:2px}
    #scene-actions #lamps{background:#eaf0e9;color:#315e4b}
    #scene-actions #lamps[aria-pressed=false]{background:white;color:#687670}
    @media(max-width:540px){#scene-actions{bottom:8px;left:8px;right:8px;padding:9px;gap:6px}#scene-actions button{font-size:11px;padding:9px}#scene-actions #quick-state{margin-left:0}#scene-actions .action-note{font-size:10px}}
  `;
  document.head.append(style);
  const bar = document.createElement('nav');bar.id='scene-actions';bar.setAttribute('aria-label','Try the scene');
  const button = (id,label,action,primary=false) => {
    const el=document.createElement('button');el.id=id;el.type='button';el.textContent=label;
    if(primary)el.className='primary';el.onclick=action;bar.append(el);return el;
  };
  const announce = text => {state.textContent=text;};
  if(api.joints.size){
    const doors=button('quick-doors','Open all doors',()=>{
      const open=[...api.joints.values()].every(j=>j.target===0);
      $(open?'open-all':'close-all').click();
      announce(open?'Doors opening':'Doors closing');
    },true);
    // Also track direct door clicks and controls in the full inspector.
    let previous='';
    const sync=()=>{
      const next=[...api.joints.values()].some(j=>j.target>0)?'Close all doors':'Open all doors';
      if(next!==previous){doors.textContent=next;previous=next;}
      requestAnimationFrame(sync);
    };sync();
  }
  const layouts=config.layouts || [];
  function focusTable(){
    if(!config.layout_view)return;
    const original=data.views.orbit;
    try{data.views.orbit=config.layout_view;$('orbit').click();}finally{data.views.orbit=original;}
  }
  if(config.layout_view){$('table-view').hidden=false;$('table-view').onclick=focusTable;}

  let index=0;
  function layout(i){
    if(api.dragging){announce('Release the object first');return;}
    const variant=layouts[i];if(!variant)return;
    for(const [id,position] of Object.entries(variant.positions)) api.placements.get(id).position.fromArray(position);
    api.scene.updateMatrixWorld(true);index=i;focusTable();announce(variant.label);
  }
  if(layouts.length>1){
    button('quick-layout','Change tabletop layout',()=>layout((index+1)%layouts.length),true);
    button('quick-restore','Restore tabletop',()=>layout(0));
    $('reset-layout').addEventListener('click',()=>{index=0;announce(layouts[0].label);});
  } else if(api.tabletop){
    button('quick-layout','Change tabletop layout',()=>$('swap-all').click(),true);
    button('quick-restore','Restore tabletop',()=>$('original-table').click());
  }
  const lamps=$('lamps');
  if(!lamps.hidden){
    bar.append(lamps);
    lamps.title='Switch ceiling fixtures and table lamps together';
  }
  const state=document.createElement('span');state.id='quick-state';state.setAttribute('role','status');state.setAttribute('aria-live','polite');state.textContent=layouts[0]?.label || 'Try a one-click change';bar.append(state);
  const note=document.createElement('p');note.className='action-note';note.textContent='Drag to look around · hold objects to move them';bar.append(note);
  $('hint').hidden=true;$('stage').append(bar);
}

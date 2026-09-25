"""Portable, interactive object-outline report with no network dependencies."""
import base64
import json
from pathlib import Path


def write_report(out, report, inspection):
    payload = dict(report)
    payload['backgrounds'] = {}
    for name in report['views']:
        backgrounds = {}
        for mode in ('reference', 'source', 'model'):
            path = Path(inspection) / f'{name}_{mode}.png'
            if path.exists():
                backgrounds[mode] = 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
        payload['backgrounds'][name] = backgrounds
    data = json.dumps(payload).replace('<', '\\u003c')
    document = r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Object outlines: color and selection</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#1d2228;color:#ecf1f7;font:15px system-ui}
header{padding:20px 24px 12px}h1{margin:0 0 8px;font-size:26px}p{margin:8px 0;color:#c4ced9;line-height:1.5}
.layout{display:grid;grid-template-columns:270px minmax(0,1fr);gap:20px;padding:12px 24px 24px}
aside{min-width:0}.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:end;margin-bottom:14px}
label{display:block}select,input[type=search],button{font:inherit;color:inherit;background:#303945;border:1px solid #566375;border-radius:6px;padding:7px}
select{max-width:100%}label>span{display:block;font-size:12px;color:#bcc7d5;margin-bottom:4px}
button{cursor:pointer}button:hover,button[aria-pressed=true]{background:#45536b;border-color:#a6c6ff}
input[type=search]{width:100%;margin:10px 0}#objects{max-height:68vh;overflow:auto;display:flex;flex-direction:column;gap:5px}
.object{text-align:left;display:flex;gap:8px;align-items:center;overflow-wrap:anywhere}.swatch{width:14px;height:14px;flex:0 0 14px;border-radius:3px;border:1px solid #fff8}
small{display:block;color:#aebbc9;font-size:11px}.stage{background:#34383f;position:relative;border-radius:8px;overflow:hidden}
svg{display:block;width:100%;height:auto;max-height:78vh}path{cursor:pointer;pointer-events:stroke;vector-effect:non-scaling-stroke}
#selection{font-weight:600;margin-bottom:10px}#crop{font-size:12px;overflow-wrap:anywhere}details{margin-top:12px}details p{font-size:13px}
.hint{font-size:12px}a{color:#a6c6ff}@media(max-width:750px){.layout{grid-template-columns:1fr;padding:12px}header{padding:16px 12px}aside{order:2}#objects{max-height:35vh}svg{max-height:none}}
</style>
<header><h1>Object outlines: color and selection</h1>
<p>Each authored object keeps one color across views. Select a furniture item to isolate its external silhouette. Other geometry cannot hide these X-ray outlines.</p></header>
<div class="layout"><aside>
<label><span>Objects to show</span><select id="category"><option value="furniture">Furniture</option><option value="structure">Architecture / built-ins</option><option value="other">Other tagged objects</option><option value="unknown">Ungrouped components</option><option value="all">All objects</option></select></label>
<input id="search" type="search" aria-label="Find an object" placeholder="Find an object or ID">
<button id="clear">Clear selection</button><p id="count" class="hint"></p><div id="objects"></div>
</aside><main>
<div class="controls">
<label><span>View</span><select id="view"></select></label>
<label><span>Background</span><select id="background"><option value="reference">Pi3X reference mesh</option><option value="source">Original source RGB</option><option value="model">Authored clay model</option></select></label>
<label><input id="solo" type="checkbox" checked> Solo selection</label>
<label><input id="tint" type="checkbox"> Tint silhouettes</label>
<label><span>Tint opacity</span><input id="opacity" aria-label="Tint opacity" type="range" min="0" max="0.5" step="0.05" value="0.15"></label>
</div>
<div id="selection" role="status" aria-live="polite"></div>
<div class="stage"><svg id="viewer" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Colored object silhouettes"><image id="base"/><g id="outlines"></g></svg></div>
<p id="crop"></p><p class="hint">Click a colored outline or an object in the list. Escape clears the selection. Similar colors are disambiguated by names and IDs.</p>
<details><summary>What these outlines mean</summary>
<p>Parts sharing an authored instance ID are grouped as one object. Untagged components remain explicitly ungrouped. Colors are model identities, not automatic detections in the reference video.</p>
<p>These are independent per-object silhouettes with a one-pixel contour simplification. Internal mesh edges and enclosed holes are omitted; tiny disconnected regions can disappear. Tint fills the silhouette, not a physically transparent material. Cropped or off-screen geometry is still absent.</p>
<p>Keep the depth comparison for occlusion and depth review. This report changes no model geometry, scale, cameras or original source timing. A visible outline is not evidence of a correct reconstruction.</p>
</details></main></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('data').textContent), $=id=>document.getElementById(id);
const ns='http://www.w3.org/2000/svg'; let selected=null;
for(const name of Object.keys(data.views)){const option=document.createElement('option');option.value=option.textContent=name;$('view').append(option);}
function category(o){return o.semantic_class.startsWith('furniture/')?'furniture':o.semantic_class.startsWith('structure/')?'structure':o.grouping==='ungrouped component'?'unknown':'other';}
function eligible(o){const group=$('category').value,query=$('search').value.toLowerCase();return(group==='all'||category(o)===group)&&(o.name+' '+o.id).toLowerCase().includes(query);}
function choose(id){selected=id;render();}
function render(){
 const name=$('view').value,view=data.views[name],[w,h]=view.size,bgs=data.backgrounds[name];
 const sourceOption=$('background').querySelector('[value=source]');sourceOption.disabled=!bgs.source;
 if(!bgs[$('background').value])$('background').value='reference';
 $('viewer').setAttribute('viewBox',`0 0 ${w} ${h}`);$('base').setAttribute('width',w);$('base').setAttribute('height',h);$('base').setAttribute('href',bgs[$('background').value]);
 $('outlines').replaceChildren();$('objects').replaceChildren();
 const list=data.objects.filter(eligible),chosen=data.objects.find(o=>o.id===selected);
 $('count').textContent=`${list.length} authored objects in this list`;
 $('selection').textContent=chosen?`${chosen.name} · ${chosen.id}${view.objects[chosen.id].paths.length?'':' — no retained contour in this view'}`:'Colored external silhouettes · select an object to focus';
 for(const o of list){
  const button=document.createElement('button');button.className='object';button.dataset.id=o.id;button.setAttribute('aria-pressed',String(selected===o.id));
  const swatch=document.createElement('span');swatch.className='swatch';swatch.style.background=`rgb(${o.color.join(',')})`;
  const label=document.createElement('span');label.textContent=o.name;const detail=document.createElement('small');detail.textContent=o.id;label.append(detail);button.append(swatch,label);button.onclick=()=>choose(o.id);$('objects').append(button);
 }
 // Paint selected outlines last, so their full shape stays legible.
 const shown=list.filter(o=>!selected||!$('solo').checked||o.id===selected).sort((a,b)=>(a.id===selected)-(b.id===selected));
 for(const o of shown){
  const paths=view.objects[o.id].paths;if(!paths.length)continue;
  const group=document.createElementNS(ns,'g');group.dataset.id=o.id;group.dataset.color=o.color.join(',');group.setAttribute('opacity',selected&&selected!==o.id?'.15':'1');
  for(const points of paths){
   const path=document.createElementNS(ns,'path');path.setAttribute('d','M'+points.map(p=>p.join(',')).join('L')+'Z');
   const color=`rgb(${o.color.join(',')})`;path.setAttribute('stroke',color);path.setAttribute('stroke-width',selected===o.id?'3':'1.5');path.setAttribute('stroke-linejoin','round');
   path.setAttribute('fill',$('tint').checked?color:'none');path.setAttribute('fill-opacity',$('opacity').value);path.onclick=()=>choose(o.id);
   const title=document.createElementNS(ns,'title');title.textContent=o.name+' · '+o.id;path.append(title);group.append(path);
  }$('outlines').append(group);
 }
 $('crop').textContent='Common crop XYZ: '+JSON.stringify(view.settings.crop_xyz_m)+' · input scale retained';
 window.objectOutlineState={view:name,selected,visibleIds:shown.filter(o=>view.objects[o.id].paths.length).map(o=>o.id)};
}
for(const id of ['view','background','solo','tint','opacity'])$(id).addEventListener('input',render);
for(const id of ['category','search'])$(id).addEventListener('input',()=>{selected=null;render();});
$('clear').onclick=()=>choose(null);document.addEventListener('keydown',e=>{if(e.key==='Escape')choose(null);});render();
</script></html>'''
    (Path(out) / 'report.html').write_text(document.replace('__DATA__', data))

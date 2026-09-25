import {createSurfaceMaterial} from './material-surface.js';
import * as THREE from 'three';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js';
import {PRESETS,generate,recipe} from './material-generator.js';

const $=id=>document.getElementById(id),renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
renderer.setSize(520,420);renderer.setPixelRatio(1);renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=.9;
const scene=new THREE.Scene();scene.background=new THREE.Color('#e3e1dd');
const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment(),environment=pmrem.fromScene(room,.04);scene.environment=environment.texture;scene.environmentIntensity=.65;room.dispose();pmrem.dispose();
const camera=new THREE.PerspectiveCamera(35,520/420,.1,20);camera.position.set(.9,.8,4.1);camera.lookAt(0,0,0);
const key=new THREE.DirectionalLight(0xfff5e8,1.3);key.position.set(-3,4,4);scene.add(key);
const fill=new THREE.DirectionalLight(0xdde8ff,.35);fill.position.set(3,1,2);scene.add(fill);
const slab=new THREE.Mesh(new RoundedBoxGeometry(2.2,1.85,.18,3,.045));scene.add(slab);
const sphere=new THREE.Mesh(new THREE.SphereGeometry(.48,64,40));sphere.position.set(.51,-.36,.51);scene.add(sphere);
// Put one complete tile on the slab face; the sphere displays normal/specular response.
const descriptions={travertine:'Layered limestone · open pores · honed finish',terrazzo:'Warm binder · multicolored mineral chips',linen:'Interlaced threads · subtle slubs · matte fibers',leather:'Fine pebbled grain · soft creases · satin finish',glass_clear:'Clear transmission · gentle surface variation',glass_frosted:'Frosted transmission · fine etched surface',glass_tinted:'Green tint · transmission through glass',glass_ribbed:'Fluted surface · refracted background',porcelain:'Ivory body · polished clear glaze',celadon:'Soft green glaze · subtle ceramic body',crackle_glaze:'Fine glaze cracks · reflective coating',porcelain_bluewhite:'Cobalt floral pattern · clear glaze',plaster:'Lime plaster · trowel marks and pores',wall_paint:'Matte paint · fine surface texture',limewash:'Mineral clouds · soft brushed finish',oak:'Growth rings · open pores · medullary rays',walnut:'Flowing grain · fine pores · small knots',marble:'Layered veins · mineral clouds · fine fractures',granite:'Quartz & feldspar grains · mica inclusions',concrete:'Cement mottling · aggregate · scattered pores',steel:'Fine brushing · interrupted scratches',brass:'Machining grain · subtle finish variation',copper:'Fine scratches · mottled copper tones'};
const backdrop=new THREE.Group();
for(let y=0;y<6;y++)for(let x=0;x<7;x++){
 const tile=new THREE.Mesh(new THREE.PlaneGeometry(.36,.36),new THREE.MeshBasicMaterial({color:(x+y)%2?'#536d78':'#ece4d4'}));
 tile.position.set((x-3)*.36,(y-2.5)*.36,-.25);backdrop.add(tile);
}scene.add(backdrop);
const cards=[];
for(const [preset,p] of Object.entries(PRESETS)){
 const card=document.createElement('article');card.innerHTML=`<img alt="${p.label} material swatch"><div class="caption"><h2>${p.label}</h2><p>${descriptions[preset]}</p><button type="button">Save recipe</button></div>`;
 $('grid').append(card);const entry={preset,card,img:card.querySelector('img'),recipe:null};cards.push(entry);
 card.querySelector('button').onclick=()=>{if(!entry.recipe)return;const url=URL.createObjectURL(new Blob([JSON.stringify(entry.recipe,null,2)+'\n'],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=preset+'-recipe.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
}
function texture(bytes,tile,color=false){const t=new THREE.DataTexture(bytes,tile.size,tile.size,THREE.RGBAFormat);t.colorSpace=color?THREE.SRGBColorSpace:THREE.NoColorSpace;t.wrapS=t.wrapT=THREE.RepeatWrapping;t.generateMipmaps=true;t.minFilter=THREE.LinearMipmapLinearFilter;t.needsUpdate=true;return t;}
let revision=0;
async function render(){
 const run=++revision;window.materialGalleryQA={ready:false};$('status').textContent='Generating materials…';
 const seed=$('seed').value,version=Number($('version').value),size=Number($('resolution').value),mode=$('mode').value,family=$('family').value,start=performance.now();
 for(const card of cards){
  const p=PRESETS[card.preset];card.card.hidden=(p.since??1)>version||(family==='new'?p.since!==3:family!=='all'&&p.family!==family);
  if(card.card.hidden){card.recipe=null;continue;}
  await new Promise(resolve=>requestAnimationFrame(resolve));if(run!==revision)return;
  const tile=generate({preset:card.preset,seed,version},size);card.recipe=tile.recipe;
  if(mode==='color'){
   const c=document.createElement('canvas');c.width=c.height=size;const ctx=c.getContext('2d'),rgba=new Uint8ClampedArray(tile.baseColor.length);
   for(let y=0;y<size;y++)rgba.set(tile.baseColor.subarray(y*size*4,(y+1)*size*4),(size-1-y)*size*4);
   ctx.putImageData(new ImageData(rgba,size,size),0,0);card.img.src=c.toDataURL();
  }else{
   const map=texture(tile.baseColor,tile,true),orm=texture(tile.orm,tile),normal=texture(tile.normal,tile);
   const m=createSurfaceMaterial({map,roughnessMap:orm,metalnessMap:orm,normalMap:normal,roughness:1,metalness:1},tile.recipe);backdrop.visible=tile.recipe.transmission>0;slab.material=sphere.material=m;
   renderer.render(scene,camera);card.img.src=renderer.domElement.toDataURL();m.dispose();map.dispose();orm.dispose();normal.dispose();
  }
 }
 const generationMs=Math.round(performance.now()-start);$('status').textContent=`${version===3?'Full collection':version===2?'Upgraded originals':'Original'} · ${size} px · seed ${seed}`;
 window.materialGalleryQA={ready:true,version,seed,size,mode,family,generationMs,recipes:cards.map(c=>c.recipe).filter(Boolean)};
}
for(const id of ['seed','version','resolution','mode','family'])$(id).onchange=render;
$('version').onchange=()=>{if(Number($('version').value)<3)$('family').value='all';render();};
$('family').onchange=()=>{if(['new','glass','ceramic','wall'].includes($('family').value))$('version').value='3';render();};
$('random').onclick=()=>{$('seed').value=String(crypto.getRandomValues(new Uint32Array(1))[0]);render();};
render();

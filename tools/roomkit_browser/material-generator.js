/** Portable, deterministic PBR tiles. No DOM, renderer or external assets. */
export const PRESETS = Object.freeze({
  oak: {label:'Natural oak', family:'wood', dark:'#70502e', light:'#cda571', roughness:.48, metalness:0, relief:.0007},
  walnut: {label:'Walnut', family:'wood', dark:'#342019', light:'#866045', roughness:.4, metalness:0, relief:.0006},
  marble: {label:'Veined marble', family:'marble', dark:'#64686c', light:'#eeeae2', roughness:.24, metalness:0, relief:.0002},
  granite: {label:'Granite', family:'granite', dark:'#43464a', light:'#c2b9aa', roughness:.48, metalness:0, relief:.001},
  concrete: {label:'Concrete', family:'concrete', dark:'#77766f', light:'#b6b2a7', roughness:.82, metalness:0, relief:.0015},
  travertine: {label:'Honed travertine', family:'travertine', since:3, dark:'#95816a', light:'#dfceb1', roughness:.58, metalness:0, relief:.00065},
  terrazzo: {label:'Warm terrazzo', family:'terrazzo', since:3, dark:'#777469', light:'#e8dfcc', roughness:.32, metalness:0, relief:.00012},
  linen: {label:'Woven linen', family:'linen', since:3, dark:'#9a8e79', light:'#e5dac4', roughness:.92, metalness:0, relief:.0007},
  leather: {label:'Saddle leather', family:'leather', since:3, dark:'#42281b', light:'#ac7549', roughness:.48, metalness:0, relief:.0003},
  steel: {label:'Brushed steel', family:'metal', dark:'#7c8790', light:'#c4cdd2', roughness:.3, metalness:1, relief:.00015},
  brass: {label:'Brushed brass', family:'metal', dark:'#937139', light:'#e0bf70', roughness:.3, metalness:1, relief:.00015},
  copper: {label:'Brushed copper', family:'metal', dark:'#8f4933', light:'#df9974', roughness:.32, metalness:1, relief:.00015},
  glass_clear: {label:'Clear glass', family:'glass', since:3, dark:'#e8edee', light:'#f8fcff', roughness:.025, metalness:0, relief:.000005, transmission:1, ior:1.5, thickness:.006},
  glass_frosted: {label:'Frosted glass', family:'glass', since:3, dark:'#dfe7e5', light:'#f2f7f4', roughness:.38, metalness:0, relief:.00008, transmission:1, ior:1.5, thickness:.006},
  glass_tinted: {label:'Green tinted glass', family:'glass', since:3, dark:'#a2beb4', light:'#c1dfcf', roughness:.04, metalness:0, relief:.000006, transmission:1, ior:1.5, thickness:.008},
  glass_ribbed: {label:'Ribbed glass', family:'glass', since:3, dark:'#d4e0e2', light:'#edf6f7', roughness:.08, metalness:0, relief:.003, transmission:1, ior:1.5, thickness:.008},
  porcelain: {label:'White porcelain', family:'ceramic', since:3, dark:'#d9d5cc', light:'#f5f2e9', roughness:.24, metalness:0, relief:.00004, clearcoat:1, clearcoatRoughness:.07},
  celadon: {label:'Celadon glaze', family:'ceramic', since:3, dark:'#698b7b', light:'#a6c5ad', roughness:.25, metalness:0, relief:.00007, clearcoat:1, clearcoatRoughness:.1},
  crackle_glaze: {label:'Crackle glaze', family:'ceramic', since:3, dark:'#938470', light:'#e6ddc7', roughness:.28, metalness:0, relief:.0002, clearcoat:1, clearcoatRoughness:.13},
  porcelain_bluewhite: {label:'Blue-and-white porcelain', family:'ceramic', since:3, dark:'#1c467f', light:'#f1eee3', roughness:.24, metalness:0, relief:.00004, clearcoat:1, clearcoatRoughness:.07},
  plaster: {label:'Ivory lime plaster', family:'wall', since:3, dark:'#b4ac9c', light:'#e9e2d3', roughness:.88, metalness:0, relief:.0012},
  wall_paint: {label:'Matte wall paint', family:'wall', since:3, dark:'#c4c2bc', light:'#eceae4', roughness:.72, metalness:0, relief:.0002},
  limewash: {label:'Clouded limewash', family:'wall', since:3, dark:'#aca395', light:'#ded4c2', roughness:.86, metalness:0, relief:.0006},
});
const clamp = (x,lo=0,hi=1)=>Math.max(lo,Math.min(hi,x));
const mix=(a,b,t)=>a+(b-a)*t;
const smooth=t=>t*t*t*(t*(t*6-15)+10);
function hash(x,y,seed){
  let h=(Math.imul(x,374761393)^Math.imul(y,668265263)^seed)>>>0;
  h=Math.imul(h^(h>>>13),1274126177);return ((h^(h>>>16))>>>0)/4294967295;
}
function seedHash(seed){let h=2166136261;for(const c of seed)h=Math.imul(h^c.charCodeAt(0),16777619);return h>>>0;}
const mod=(x,n)=>((x%n)+n)%n;
function noise(u,v,nx,ny,seed){
  const x=u*nx,y=v*ny,ix=Math.floor(x),iy=Math.floor(y),tx=smooth(x-ix),ty=smooth(y-iy);
  const h=(a,b)=>hash(mod(a,nx),mod(b,ny),seed);
  return mix(mix(h(ix,iy),h(ix+1,iy),tx),mix(h(ix,iy+1),h(ix+1,iy+1),tx),ty);
}
function fbm(u,v,seed){return noise(u,v,4,4,seed)*.54+noise(u,v,8,8,seed+1)*.27+noise(u,v,16,16,seed+2)*.13+noise(u,v,32,32,seed+3)*.06;}
function number(value,fallback,min,max,key){
  const n=value===undefined?fallback:value;
  if(typeof n!=='number'||!Number.isFinite(n)||n<min||n>max)throw Error(`${key} must be a number in [${min}, ${max}]`);
  return n;
}
export function recipe(input={}){
  if(!input||typeof input!=='object'||Array.isArray(input))throw Error('Material recipe must be an object');
  const version=input.version??3;
  const physical=['transmission','ior','thickness','clearcoat','clearcoatRoughness'];
  const known=['version','preset','seed','tileSize','rotation','roughness','relief','color',...(version===3?physical:[])];
  for(const key of Object.keys(input))if(!known.includes(key))throw Error('Unknown material parameter: '+key);
  if(input.version!==undefined&&![1,2,3].includes(input.version))throw Error('Unsupported material recipe version');
  const preset=input.preset??'oak';
  if(!Object.hasOwn(PRESETS,preset))throw Error('Unknown material preset: '+preset);
  if(version<(PRESETS[preset].since??1))throw Error('Preset requires recipe version 3');
  const p=PRESETS[preset], seed=String(input.seed??'1');
  if(seed.length>100)throw Error('Seed must be at most 100 characters');
  const color=input.color??p.light;
  if(typeof color!=='string'||!/^#[0-9a-f]{6}$/i.test(color))throw Error('Color must be #RRGGBB');
  const result={version,preset,seed,tileSize:number(input.tileSize,1,.05,10,'tileSize'),rotation:number(input.rotation,0,-180,180,'rotation'),roughness:number(input.roughness,p.roughness,version===3?0:.05,1,'roughness'),relief:number(input.relief,p.relief,0,.01,'relief'),color:color.toLowerCase()};
  if(version===3)Object.assign(result,{transmission:number(input.transmission,p.transmission??0,0,1,'transmission'),ior:number(input.ior,p.ior??1.5,1,2.333,'ior'),thickness:number(input.thickness,p.thickness??.006,0,1,'thickness'),clearcoat:number(input.clearcoat,p.clearcoat??0,0,1,'clearcoat'),clearcoatRoughness:number(input.clearcoatRoughness,p.clearcoatRoughness??.1,0,1,'clearcoatRoughness')});
  if(result.transmission>0&&p.metalness>0)throw Error('Transmission requires a nonmetal preset');
  return result;
}
function rgb(hex){return [1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255);}
/** Sampling is periodic in both axes, including the domain warp. */
function legacySampler(input){
  const r=recipe(input),p=PRESETS[r.preset],seed=seedHash(r.seed),base=rgb(r.color),dark=rgb(p.dark),light=rgb(p.light);
  const low=base.map((c,i)=>c*dark[i]/light[i]);
  return (u,v)=>{
    const n=fbm(u,v,seed);let tone,height,rough;
    if(p.family==='wood'){
      const warp=noise(u,v,4,2,seed+10),fibres=noise(u+warp*.025,v,96,4,seed+20);
      const rings=.5+.5*Math.sin(2*Math.PI*(u*18+warp*1.7+noise(u,v,8,2,seed)*.3));
      const pores=Math.pow(1-fibres,7);
      tone=clamp(.32+.54*rings+.22*fibres-.9*pores);height=.4*rings+.4*fibres-.3*pores;rough=r.roughness+.16*pores+.05*(n-.5);
    }else if(p.family==='marble'){
      const wave=Math.abs(Math.sin(2*Math.PI*(2*u+v+1.8*n)));
      const vein=Math.exp(-wave*wave*190);
      tone=clamp(.88+.12*n-.8*vein);height=.5+.05*n-.12*vein;rough=r.roughness+.08*vein;
    }else if(p.family==='granite'){
      const fine=noise(u,v,96,96,seed+20),grain=noise(u,v,48,48,seed+30);
      tone=clamp(.2+.6*grain+.45*fine-.2*n);height=.5*grain+.5*fine;rough=r.roughness+.17*(fine-.5);
    }else if(p.family==='concrete'){
      const fine=noise(u,v,96,96,seed+20),pore=Math.pow(1-fine,9);
      tone=clamp(.3+.65*n+.14*fine-2*pore);height=.4*n+.3*fine-2*pore;rough=r.roughness+.12*(fine-.5);
    }else{
      const brush=noise(u,v,128,2,seed+20),micro=noise(u,v,128,16,seed+30);
      tone=clamp(.68+.22*brush+.08*n);height=.75*brush+.25*micro;rough=r.roughness+.14*(brush-.5);
    }
    return {color:low.map((c,i)=>clamp(mix(c,base[i],tone))),height:clamp(height),roughness:clamp(rough,.05,1),metalness:p.metalness};
  };
}
// Version 1 stays frozen so previously saved recipes retain their exact maps.
const TAU=2*Math.PI;
const ramp=(a,b,x)=>smooth(clamp((x-a)/(b-a)));
const periodicDelta=(x,c)=>mod(x-c+.5,1)-.5;
/** Periodic mineral/aggregate cells. F2-F1 gives an irregular crystal boundary. */
function cells(u,v,nx,ny,seed){
  const x=u*nx,y=v*ny,ix=Math.floor(x),iy=Math.floor(y);
  let first=Infinity,second=Infinity,id=0;
  for(let j=-1;j<=1;j++)for(let i=-1;i<=1;i++){
    const px=ix+i,py=iy+j,h=hash(mod(px,nx),mod(py,ny),seed);
    const dx=px+.18+.64*h-x,dy=py+.18+.64*hash(mod(px,nx),mod(py,ny),seed+1)-y,d=dx*dx+dy*dy;
    if(d<first){second=first;first=d;id=h;}else if(d<second)second=d;
  }
  return {distance:Math.sqrt(first),edge:Math.sqrt(second)-Math.sqrt(first),id};
}

/** Multiscale, seamless reflectance and relief; never includes baked shading. */
export function sampler(input){
  const r=recipe(input);
  if(r.version===1)return legacySampler(r);
  const p=PRESETS[r.preset],seed=seedHash(r.seed),base=rgb(r.color),dark=rgb(p.dark),light=rgb(p.light);
  const low=base.map((c,i)=>c*dark[i]/light[i]);
  const N=(u,v,x,y,k)=>noise(u,v,x,y,seed+k);
  const knots=Array.from({length:2},(_,i)=>({u:hash(i,0,seed+211),v:hash(i,1,seed+211),width:.028+.012*hash(i,2,seed+211)}));
  return (u,v)=>{
    const n=fbm(u,v,seed),micro=N(u,v,192,192,97);
    let tone,height,rough,color;
    if(p.family==='wood'){
      const walnut=r.preset==='walnut';
      let bend=0,knot=0,knotRing=0;
      for(const k of knots){
        const dx=periodicDelta(u,k.u),dy=periodicDelta(v,k.v),d=Math.hypot(dx/k.width,dy/(walnut?.16:.11));
        // Wrapped offsets are extinguished before their discontinuity at half a tile.
        const influence=1-ramp(2,4,d);
        bend+=dx*1.3*Math.exp(-d*d*.2)*influence;
        const mask=1-ramp(.4,1.65,d);
        knot+=mask;knotRing+=mask*(.5+.5*Math.sin(d*26+N(u,v,24,24,12)*2));
      }
      const warp=(N(u,v,3,2,10)-.5)*.09+(N(u,v,8,3,11)-.5)*.014;
      const g=u+warp+bend;
      const phase=g*(walnut?14:19)+N(u,v,5,3,16)*.6;
      const growth=.5+.5*Math.sin(TAU*phase);
      const latewood=Math.pow(growth,walnut?6:10);
      const fibres=N(g,v,180,7,20),fine=N(g,v,230,19,21);
      const pores=ramp(.72,.9,N(g,v,315,70,22))*ramp(.35,.7,N(g,v,37,51,23));
      const rays=walnut?0:ramp(.72,.88,N(g,v,89,220,24));
      const ribbon=N(g,v,28,2,25);
      tone=clamp((walnut?.62:.77)+.21*(ribbon-.5)+.14*(n-.5)-latewood*(walnut?.25:.23)+.10*(fibres-.5)+.035*(fine-.5)-.29*pores+.1*rays-.34*knot-.12*knotRing);
      height=.55-.12*latewood+.055*(fibres-.5)+.04*(fine-.5)-.38*pores-.16*knot+.025*rays;
      rough=r.roughness+.14*pores+.07*latewood+.045*(micro-.5)+.035*(n-.5)-.04*rays;
    }else if(p.family==='marble'){
      const warp=fbm(u+.13,v-.27,seed+33),cloud=N(u,v,9,9,35);
      const flow=3*u+v+3.4*n+.3*cloud;
      const width=.022+.075*N(u,v,7,7,36);
      const ridge=Math.abs(Math.sin(Math.PI*flow));
      const vein=1-ramp(width*.25,width*2.2,ridge);
      const halo=1-ramp(width,width*5.5,ridge);
      const filament=Math.exp(-Math.pow(Math.sin(Math.PI*(7*u-2*v+4*warp+1.7*n))/.065,2));
      const fracture=filament*ramp(.42,.7,cloud);
      const fleck=ramp(.76,.91,micro);
      tone=clamp(.92+.10*(n-.5)+.045*(cloud-.5)-.47*vein-.12*halo-.18*fracture-.06*fleck);
      height=.51+.025*(cloud-.5)-.035*vein-.018*fracture+.015*(micro-.5);
      rough=r.roughness+.045*halo+.045*vein+.025*(micro-.5)+.018*(cloud-.5);
      // Warm mineral traces sit within some primary veins, with no light painted in.
      const mineral=vein*ramp(.52,.76,warp)*.2;
      color=low.map((c,i)=>mix(c,base[i],tone)*(1-mineral*[0,.18,.4][i]));
    }else if(p.family==='granite'){
      const coarse=cells(u+.013*(n-.5)+.005*(N(u,v,61,61,41)-.5),v+.012*(n-.5)+.005*(N(u,v,57,57,42)-.5),48,48,seed+40);
      const small=cells(u,v,119,119,seed+44);
      const mica=ramp(.73,.84,small.id)*(1-ramp(.23,.58,small.distance));
      const edge=1-ramp(.008,.065,coarse.edge);
      const quartz=ramp(.53,.64,coarse.id),feldspar=ramp(.18,.28,coarse.id)*(1-quartz);
      tone=clamp(.2+.46*quartz+.24*feldspar+.15*coarse.id+.11*(micro-.5)+.12*(n-.5)-.5*mica-.06*edge);
      color=low.map((c,i)=>mix(c,base[i],tone)*(1-feldspar*[0,.055,.09][i]));
      height=.49+.11*(coarse.id-.5)+.08*(micro-.5)-.13*mica-.045*edge;
      rough=r.roughness+.15*mica+.07*edge-.075*quartz+.06*(micro-.5);
    }else if(p.family==='concrete'){
      const cement=N(u,v,18,18,50),aggregate=cells(u,v,67,67,seed+51),holes=cells(u,v,38,38,seed+54);
      const pore=(1-ramp(.06,.19,holes.distance))*ramp(.66,.77,holes.id);
      const grit=(1-ramp(.19,.53,aggregate.distance))*ramp(.54,.68,aggregate.id);
      const trowel=N(u+.035*n,v,3,57,58);
      tone=clamp(.61+.27*(n-.5)+.13*(cement-.5)+.065*(micro-.5)+.06*(trowel-.5)-.11*grit-.5*pore);
      height=.54+.13*(cement-.5)+.09*(micro-.5)+.07*(trowel-.5)+.045*grit-.65*pore;
      rough=r.roughness+.1*pore+.07*grit+.07*(micro-.5)+.04*(cement-.5);
    }else if(p.family==='travertine'){
      const band=.5+.5*Math.sin(TAU*(v*13+.24*N(u,v,5,3,301)));
      const pores=cells(u+.012*n,v,78,125,seed+302);
      const pore=(1-ramp(.06,.24,pores.distance))*ramp(.48,.72,pores.id);
      const strata=N(u,v,5,97,304);
      tone=clamp(.84+.15*(band-.5)+.13*(n-.5)+.07*(strata-.5)-.35*pore);
      height=.53+.055*(band-.5)+.04*(micro-.5)-.6*pore;
      rough=r.roughness+.16*pore+.04*(strata-.5);
    }else if(p.family==='terrazzo'){
      const chips=cells(u,v,22,22,seed+311),fine=cells(u,v,73,73,seed+313);
      const chip=ramp(.055,.095,chips.edge)*ramp(.15,.30,chips.id);
      const fleck=ramp(.06,.12,fine.edge)*(1-ramp(.20,.38,fine.distance));
      // Seeded mineral chips vary independently from the warm cement binder.
      const palette=[[.97,.94,.85],[.65,.47,.36],[.32,.38,.36],[.72,.70,.64]];
      const mineral=palette[Math.min(3,Math.floor(chips.id*4))];
      const binder=base.map(c=>c*(.94+.04*(n-.5)));
      color=binder.map((c,i)=>mix(mix(c,mineral[i]*base[i]/light[i],chip),c*.58,fleck*.18));
      height=.5+.012*(micro-.5)-.025*(1-chip);
      rough=r.roughness+.05*(1-chip)+.02*(micro-.5);
    }else if(p.family==='linen'){
      const warp=.5+.5*Math.cos(TAU*(u*96+.10*N(u,v,8,16,321)));
      const weft=.5+.5*Math.cos(TAU*(v*96+.10*N(u,v,16,8,322)));
      const crossing=Math.cos(TAU*u*48)*Math.cos(TAU*v*48);
      const thread=mix(warp,weft,.5+.45*crossing);
      const fibres=N(u,v,192,39,323),slub=N(u,v,29,5,324);
      tone=clamp(.84+.11*(thread-.5)+.10*(n-.5)+.055*(slub-.5)+.04*(fibres-.5));
      height=.25+.55*thread+.045*(fibres-.5)+.035*(slub-.5);
      rough=r.roughness+.045*(fibres-.5)+.03*(1-thread);
    }else if(p.family==='leather'){
      const grain=cells(u+.007*n,v-.006*n,105,105,seed+331);
      const crease=1-ramp(.012,.070,grain.edge);
      const pore=(1-ramp(.03,.09,grain.distance))*ramp(.62,.85,grain.id);
      tone=clamp(.84+.15*(n-.5)+.06*(grain.id-.5)-.16*crease-.12*pore);
      height=.53+.06*(grain.id-.5)-.27*crease-.25*pore+.025*(micro-.5);
      rough=r.roughness+.12*crease+.05*pore+.035*(n-.5);
    }else if(p.family==='glass'){
      const rib=r.preset==='glass_ribbed'?.5+.5*Math.cos(TAU*32*u):0;
      tone=.99+.008*(n-.5)+.001*(micro-.5);
      height=.5+.025*(micro-.5)+.006*(n-.5)+.42*rib;
      rough=r.roughness+(r.preset==='glass_frosted'?.04:.008)*(micro-.5);
    }else if(p.family==='ceramic'){
      const ceramic=N(u,v,87,87,81),cloud=N(u,v,8,8,82);
      const grain=cells(u+.006*n,v-.004*n,18,18,seed+83);
      const crack=r.preset==='crackle_glaze'?1-ramp(.006,.034,grain.edge):0;
      let decoration=0;
      if(r.preset==='porcelain_bluewhite'){
        const x=periodicDelta(u*4,0)/.38,y=periodicDelta(v*4,0)/.38;
        const radius=Math.hypot(x,y),angle=Math.atan2(y,x);
        const petals=.52+.17*Math.cos(6*angle);
        const outline=Math.exp(-Math.pow((radius-petals)/.052,2));
        const center=1-ramp(.09,.18,radius);
        const petalVeins=(1-ramp(.35,.65,radius))*Math.pow(.5+.5*Math.cos(6*angle),12)*ramp(.12,.25,radius);
        const border=Math.exp(-Math.pow(Math.sin(TAU*2*v)/.075,2));
        decoration=clamp(outline+.8*center+.55*petalVeins+.5*border);
      }
      tone=clamp(.95+.07*(n-.5)+.025*(ceramic-.5)+.03*(cloud-.5)-.65*crack-.86*decoration);
      height=.5+.05*(ceramic-.5)+.015*(micro-.5)-.06*crack;
      rough=r.roughness+.03*(ceramic-.5)+.025*crack;
    }else if(p.family==='wall'){
      const trowel=N(u+.025*n,v,5,45,91),fine=N(u,v,150,150,92);
      const pore=ramp(.77,.93,N(u,v,83,83,93));
      const paint=r.preset==='wall_paint',wash=r.preset==='limewash';
      tone=clamp(.88+(wash?.6:paint?.035:.2)*(n-.5)+(paint?.025:.1)*(fine-.5)+(paint?0:.09)*(trowel-.5)-.12*pore);
      height=.5+(paint?.12:.22)*(fine-.5)+(paint?0:.14)*(trowel-.5)-.17*pore;
      rough=r.roughness+.04*(fine-.5)+.04*pore;
    }else{
      const brush=N(u+.0015*N(u,v,8,4,60),v,196,3,61),hair=N(u,v,245,27,62);
      const scratches=ramp(.72,.9,N(u,v,245,9,63))*ramp(.25,.6,N(u,v,21,36,64));
      const polish=N(u,v,12,3,65),mottle=fbm(u,v,seed+70);
      // Slight finish variation; conductive throughout, without pretending to model oxide.
      const aged=r.preset==='steel'?.025:r.preset==='brass'?.09:.13;
      tone=clamp(.86+.075*(brush-.5)+.045*(hair-.5)+.035*(polish-.5)-aged*ramp(.35,.75,mottle)-.07*scratches);
      height=.5+.085*(brush-.5)+.035*(hair-.5)-.075*scratches;
      rough=r.roughness+.08*(brush-.5)+.035*(hair-.5)+.075*scratches+aged*(mottle-.35)+.04*(polish-.5);
    }
    return {color:(color??low.map((c,i)=>mix(c,base[i],tone))).map(c=>clamp(c)),height:clamp(height),roughness:clamp(rough,r.version===3?0:.05,1),metalness:p.metalness};
  };
}
/** RGBA8 base color (sRGB), packed ORM (linear), height and tangent normal. */
export function generate(input={},size=recipe(input).version===1?256:512){
  if(!Number.isInteger(size)||size<32||size>2048||(size&(size-1)))throw Error('Resolution must be a power of two from 32 to 2048');
  const r=recipe(input),sample=sampler(r),baseColor=new Uint8Array(size*size*4),orm=new Uint8Array(baseColor.length),normal=new Uint8Array(baseColor.length),height=new Uint8Array(baseColor.length),heights=new Float32Array(size*size);
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    const i=y*size+x,k=i*4,s=sample(x/size,y/size);heights[i]=s.height;
    baseColor.set([...s.color.map(c=>Math.round(c*255)),255],k);
    orm.set([255,Math.round(s.roughness*255),Math.round(s.metalness*255),255],k);
    const h=Math.round(s.height*255);height.set([h,h,h,255],k);
  }
  const h=(x,y)=>heights[mod(y,size)*size+mod(x,size)];
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    const dx=(h(x+1,y)-h(x-1,y))*r.relief*size/(2*r.tileSize),dy=(h(x,y+1)-h(x,y-1))*r.relief*size/(2*r.tileSize);
    const len=Math.hypot(dx,dy,1);normal.set([Math.round((.5-.5*dx/len)*255),Math.round((.5-.5*dy/len)*255),Math.round((.5+.5/len)*255),255],(y*size+x)*4);
  }
  return {recipe:r,size,baseColor,orm,normal,height};
}

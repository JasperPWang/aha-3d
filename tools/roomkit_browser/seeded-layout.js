import {containsCircle} from './support-geometry.js';
// Pure, versioned generation. A scope owns its slots; adding a future chair scope
// does not consume random numbers from tabletop placement.
export function randomFor(seed, scope='tabletop-v1') {
 let h=2166136261;
 for(const c of `${scope}:${seed}`) {h^=c.charCodeAt(0);h=Math.imul(h,16777619);}
 return ()=>{h+=0x6D2B79F5;let t=h;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return ((t^t>>>14)>>>0)/4294967296;};
}
export function generateLayout(spec, seed) {
 const placements=[];
 for(const support of spec.supports) {
  const rng=randomFor(seed,`tabletop-v1:${support.id}`), placed=[];
  const [xmin,ymin]=support.min,[xmax,ymax,z]=support.max;
  const candidates=spec.templates.filter(t=>Math.hypot(t.size[0],t.size[1])<Math.min(xmax-xmin,ymax-ymin)-.08);
  if(!candidates.length)throw Error('No tabletop variants fit this support');
  const count=5+Math.floor(rng()*5);
  for(let slot=0;slot<count;slot++) {
   const choices=candidates.filter(t=>slot===0?t.category==='centerpiece':t.category!=='centerpiece');
   const template=(choices.length?choices:candidates)[Math.floor(rng()*(choices.length||candidates.length))];
   // Circumscribed footprints protect all yaw angles and the table edge.
   const radius=Math.hypot(template.size[0],template.size[1])/2+.025;
   for(let attempt=0;attempt<100;attempt++) {
    const x=xmin+radius+rng()*(xmax-xmin-2*radius), y=ymin+radius+rng()*(ymax-ymin-2*radius);
    if(!containsCircle(support,x,y,radius))continue;
    if(support.obstacles?.some(b=>Math.hypot(x-Math.max(b.min[0],Math.min(x,b.max[0])),y-Math.max(b.min[1],Math.min(y,b.max[1])))<radius+.01))continue;
    if(placed.some(p=>Math.hypot(x-p.x,y-p.y)<radius+p.radius+.025))continue;
    const p={id:`swap:${support.id}:${slot}`,template:template.id,support:support.id,
     position:[x,y,z+template.size[2]/2+.025],yaw:rng()*Math.PI*2};
    placed.push({x,y,radius});placements.push(p);break;
   }
  }
 }
 return {version:1,scope:'tabletop',seed:String(seed),placements};
}

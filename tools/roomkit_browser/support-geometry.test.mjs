import test from 'node:test';
import assert from 'node:assert/strict';
import {containsCircle} from './support-geometry.js';
import {generateLayout} from './seeded-layout.js';
test('rotated support excludes bounding-box corners and respects a static centerpiece',()=>{
 const support={id:'diamond',min:[-1,-1,0],max:[1,1,.7],footprint:[[0,-1],[1,0],[0,1],[-1,0]],obstacles:[{min:[-.1,-.1,.7],max:[.1,.1,1]}]};
 assert.equal(containsCircle(support,.8,.8),false);assert.equal(containsCircle(support,0,0,.3),true);
 const spec={supports:[support],templates:[{id:'a',category:'accent',size:[.1,.1,.1]}]};
 for(let i=0;i<200;i++){const layout=generateLayout(spec,String(i));assert.ok(layout.placements.length);for(const p of layout.placements){assert.ok(containsCircle(support,...p.position.slice(0,2),Math.SQRT2*.05+.025));assert.ok(Math.hypot(Math.max(0,Math.abs(p.position[0])-.1),Math.max(0,Math.abs(p.position[1])-.1))>.1);}}
});

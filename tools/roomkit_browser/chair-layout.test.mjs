import test from 'node:test';
import assert from 'node:assert/strict';
import {placedBox,overlap,insideFloor,candidate,collisionReason,navigationPreserved,planChairs,replacementReason} from './chair-layout.js';
import {meshProxy} from './chairs.js';
import * as THREE from 'three';

const box=(min,max)=>placedBox({min,max});
test('yaw-aware collision preserves empty space around narrow rotated parts',()=>{
 const beam=placedBox({min:[-1,-.05,0],max:[1,.05,1]},[0,0,0],Math.PI/4);
 assert.ok(overlap(beam,box([.3,.3,.1],[.4,.4,.9])));
 assert.equal(overlap(beam,box([.3,-.4,.1],[.4,-.3,.9])),false);
 assert.equal(overlap(beam,box([0,0,2],[.2,.2,3])),false);
});

test('room component proxies retain yaw and rotated floor corners stay outside',()=>{
 const mesh=new THREE.Mesh(new THREE.BoxGeometry(2,.1,1));mesh.rotation.z=Math.PI/4;mesh.updateMatrixWorld(true);
 const bounds=new THREE.Box3().setFromObject(mesh),proxy=meshProxy(mesh,{min:bounds.min.toArray(),max:bounds.max.toArray()});
 assert.ok(Math.abs(proxy.yaw-Math.PI/4)<1e-6);
 assert.equal(overlap(proxy,box([.3,-.4,-.1],[.4,-.3,.1])),false);
 const context={floor:[-1,-1,1,1],floorTriangles:[[[0,-1],[1,0],[0,1]],[[0,-1],[0,1],[-1,0]]]};
 assert.ok(insideFloor(context,0,0));assert.equal(insideFloor(context,.8,.8),false);
});

test('navigation rejects a blocked doorway and is invariant to world Z',()=>{
 const fixtures=[box([2.9,0,0],[3.1,1.4,2]),box([2.9,2.6,0],[3.1,4,2])];
 const original=[{box:box([.5,.5,0],[1,1,.9])}],plug=[{box:box([2.6,1.4,0],[3.4,2.6,.9])}];
 const context={floor:[0,0,6,4],floorZ:0,navigation:fixtures};
 assert.ok(navigationPreserved(context,original,original));
 assert.equal(navigationPreserved(context,original,plug),false);
 const shift=b=>({...b,center:[b.center[0],b.center[1],b.center[2]-1.35]});
 const lower={...context,floorZ:-1.35,navigation:fixtures.map(shift)};
 const shifted=chairs=>chairs.map(c=>({box:shift(c.box)}));
 assert.ok(navigationPreserved(lower,shifted(original),shifted(original)));
 assert.equal(navigationPreserved(lower,shifted(original),shifted(plug)),false);
});

test('late human motion and one impossible seat prevent whole-set acceptance',()=>{
 const geometry={min:[-.2,-.2,0],max:[.2,.2,.8],dimensions_m:[.4,.4,.8],seat:{height_m:.4}};
 const template={id:'library-chair',asset_id:'chairs/a',model_id:'a',seating_type:'dining',specification:geometry,proxies:[geometry]};
 const limits={max_width_m:.5,max_depth_m:.5,max_height_m:1,seat_height_range_m:[.3,.5],max_translation_m:.1,rear_clearance_m:.2,collision_margin_m:.003};
 const a={id:'a',position:[1,1,0],yaw:0,original_specification:geometry,source_model_id:'source',seating_type:'dining',limits},b={...a,id:'b',position:[3,1,0]};
 const context={solids:[],fixtures:[],motion:[],navigation:[],floor:[0,0,5,4],floorZ:0};
 assert.ok(planChairs({slots:[a,b],templates:[template]},'test',context).passed);
 const late={...box([2.5,.5,0],[3.5,1.5,1.8]),frame:360};
 assert.equal(collisionReason(candidate(template,b,b.position),{...context,motion:[late]}),'human animation clearance');
 const failed=planChairs({slots:[a,b],templates:[template]},'test',{...context,motion:[late]});
 assert.equal(failed.passed,false);assert.deepEqual(failed.placements,[]);
 assert.ok(failed.slots.every(s=>s.valid_candidates===0));
 assert.deepEqual(failed.groups[0].compatible_assets,[]);
});

const geometry={min:[-.2,-.2,0],max:[.2,.2,.8],dimensions_m:[.4,.4,.8],seat:{height_m:.4}};
const limits={max_width_m:.5,max_depth_m:.5,max_height_m:1,seat_height_range_m:[.3,.7],max_translation_m:.1,rear_clearance_m:.2,collision_margin_m:.003};
const slot=(id,position,type='dining')=>({id,position,yaw:0,original_asset_id:'chairs/source-'+type,source_model_id:'source-'+type,seating_type:type,original_specification:geometry,limits});
const template=(id,type='dining')=>({id,asset_id:'chairs/'+id,model_id:id,seating_type:type,specification:geometry,proxies:[geometry]});
const context={solids:[],fixtures:[],motion:[],navigation:[],floor:[0,0,5,4],floorZ:0};

test('every seed keeps source models coherent and seating types separate',()=>{
 const slots=[slot('a',[1,1,0]),slot('b',[3,1,0]),slot('c',[1,3,0],'lounge')];
 const templates=[template('d1'),template('d2'),template('l1','lounge'),template('l2','lounge')];
 for(let i=0;i<12;i++){
  const r=planChairs({slots,templates},i,context);assert.ok(r.passed);
  for(const p of r.placements)assert.deepEqual(p.position,slots.find(s=>s.id===p.id).position,'No automatic chair translation');
  assert.equal(r.placements[0].asset_id,r.placements[1].asset_id);
  for(const p of r.placements)assert.equal(templates.find(t=>t.id===p.template).seating_type,slots.find(s=>s.id===p.id).seating_type);
  assert.deepEqual(planChairs({slots,templates},i,context),r);
 }
});

test('individually feasible seats cannot accept an inconsistent group',()=>{
 const a={...slot('a',[1,1,0]),limits:{...limits,seat_height_range_m:[.3,.5]}};
 const b={...slot('b',[3,1,0]),limits:{...limits,seat_height_range_m:[.5,.7]}};
 const low=template('low'),high={...template('high'),specification:{...geometry,seat:{height_m:.6}}};
 assert.ok(planChairs({slots:[a],templates:[low,high]},0,context).passed);
 assert.ok(planChairs({slots:[b],templates:[low,high]},0,context).passed);
 const r=planChairs({slots:[a,b],templates:[low,high]},0,context);
 assert.equal(r.passed,false);assert.deepEqual(r.placements,[]);assert.deepEqual(r.groups[0].compatible_assets,[]);
});

test('original models, aliases, other seating types and unknown metadata cannot masquerade as alternatives',()=>{
 const source=slot('a',[1,1,0]);
 for(const t of [template('source-dining'),{...template('alias'),model_id:source.source_model_id},template('lounge','lounge'),{...template('unknown'),seating_type:null}]){
  assert.ok(replacementReason(t,source));
  assert.equal(planChairs({slots:[source],templates:[t]},0,context).passed,false);
 }
 assert.ok(replacementReason(template('new'),{...source,seating_type:null}));
});

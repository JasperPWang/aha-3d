import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html,out,placementFixture]=process.argv.slice(2),errors=[];
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(resolve(html)).href,{timeout:120000});await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});
 assert.equal(await page.locator('#error').textContent(),'');
 if(placementFixture){
  const fixture=JSON.parse(await readFile(placementFixture,'utf8'));
  await page.evaluate(poses=>{
   for(const p of poses){const s=roomkitQA.chairs.spec.slots.find(s=>s.id===p.id);if(!s)throw Error('Fixture slot absent');roomkitQA.placements.get(p.id).position.set(p.position[0]-s.position[0],p.position[1]-s.position[1],0);}
   roomkitQA.scene.updateMatrixWorld(true);roomkitQA.tabletop?.rebuildStatics();
  },fixture.placements);
 }
 const anchors=await page.evaluate(()=>roomkitQA.chairs.layout.anchors);
 const report=await page.evaluate(()=>{const q=roomkitQA,t=performance.now(),r=q.chairs.regenerate('chair-validation');return {...r,milliseconds:performance.now()-t};});
 console.log('First chair plan',JSON.stringify(report));
 if(!report.passed){
  // Reject a constrained source arrangement without changing any live object.
  // Successful replacement/drag scenarios can additionally use an explicit
  // user-arranged fixture. This never changes the exported demo's initial pose.
  const unavailable=await page.evaluate(()=>{
   const q=roomkitQA,{slots,templates}=q.chairs.spec;
   if(slots.some(s=>!s.seating_type||!s.source_model_id))throw Error('Missing source type metadata');
   const noModel=slots.some(s=>!templates.some(t=>t.seating_type===s.seating_type&&t.model_id!==s.source_model_id&&t.asset_id!==s.original_asset_id));
   if(!q.chairs.lastReport.groups.some(g=>!g.compatible_assets.length))throw Error('Search budget exhausted despite individual fits');
   const before=JSON.stringify(q.chairs.layout),hash=location.hash,meshes=q.pickables.slice();
   for(let i=0;i<50;i++){
    if(q.chairs.regenerate('chair-seed-'+i).passed)throw Error('Same model counted as a replacement');
    if(before!==JSON.stringify(q.chairs.layout)||hash!==location.hash||meshes.length!==q.pickables.length||meshes.some((m,i)=>m!==q.pickables[i]))throw Error('Unavailable group changed the scene');
   }
   q.sceneGraph.setSelection(slots[0].id);q.sceneGraph.refresh(true);
   return {slots:slots.length,groups:q.chairs.lastReport.groups,frames:q.chairs.spec.animation_frames_checked,noModel};
  });
  await page.click('#swap-chairs');assert.equal(await page.evaluate(()=>roomkitQA.chairs.lastReport.passed),false);
  assert.match(await page.locator('#chair-result').textContent(),/Layout kept/);
  const seating=JSON.parse(await page.locator('#layout-text').textContent()).seating;
  assert.ok(seating.seating_type&&seating.source_model_id&&seating.replacement_group_id);
  await page.screenshot({timeout:120000,path:resolve(out,'chairs-final.png')});
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({timeout:120000,path:resolve(out,'chairs-mobile.png'),fullPage:true});assert.deepEqual(errors,[]);
  await writeFile(resolve(out,'chair-validation.json'),JSON.stringify({passed:true,outcome:unavailable.noModel?'no_same_type_alternative':'no_alternative_at_current_positions',slots:unavailable.slots,groups:unavailable.groups,
   seedsChecked:50,assetsExercised:[],alternativeToSourceAssetExercised:false,allOrNothingRejection:true,originalModelsExcluded:true,
   sourceAnimationFrames:unavailable.frames,mobile:true,errors},null,2));
  console.log('Chair unavailability and scene preservation validated');
 }else{
 assert.ok(report.passed,report.reason);assert.equal(report.placements.length,await page.evaluate(()=>roomkitQA.chairs.spec.slots.length));
 assert.deepEqual(report.placements.map(p=>({id:p.id,position:p.position,yaw:p.yaw})).sort((a,b)=>a.id.localeCompare(b.id)),anchors.sort((a,b)=>a.id.localeCompare(b.id)),'Swap preserves every current anchor');
 await page.screenshot({timeout:120000,path:resolve(out,'chairs-grouped.png')});
 const initial=JSON.stringify(report.placements);
 const repeat=await page.evaluate(()=>roomkitQA.chairs.regenerate('chair-validation'));
 assert.equal(JSON.stringify(repeat.placements),initial,'Seed must reproduce exact assets and placements');
 await page.evaluate(()=>roomkitQA.sceneGraph.setSelection(null));
 assert.equal(JSON.parse(await page.locator('#layout-text').textContent()).seeds.chairs,'chair-validation');
 const negative=await page.evaluate(()=>{
  const q=roomkitQA,before=JSON.stringify(q.chairs.layout),seed=location.hash,meshes=q.pickables.length;
  const template=q.chairs.spec.templates.find(t=>t.id===q.chairs.layout.placements[0].template),width=template.specification.dimensions_m[0];template.specification.dimensions_m[0]=Math.max(...q.chairs.spec.slots.map(s=>s.limits.max_width_m))*3;
  const bad=q.chairs.regenerate('oversize',template.asset_id);template.specification.dimensions_m[0]=width;
  return {passed:bad.passed,reasons:bad.rejections,unchanged:before===JSON.stringify(q.chairs.layout),sameSeed:seed===location.hash,sameMeshes:meshes===q.pickables.length};
 });
 assert.equal(negative.passed,false);assert.ok(negative.unchanged&&negative.sameSeed&&negative.sameMeshes);
 assert.ok(Object.values(negative.reasons).some(r=>r['too wide']));
 await page.screenshot({timeout:120000,path:resolve(out,'chairs-rejected.png')});
 const seeded=await page.evaluate(()=>{
  const q=roomkitQA,assets=new Set(),counts=[],elapsed=performance.now();let distinctFromSource=false;
  for(let i=0;i<50;i++){
   const r=q.chairs.regenerate('chair-seed-'+i);if(!r.passed)throw Error('Seed '+i+' failed: '+r.reason);
   for(const p of r.placements){
    const s=q.chairs.spec.slots.find(s=>s.id===p.id),t=q.chairs.spec.templates.find(t=>t.id===p.template);
    if(t.seating_type!==s.seating_type||t.model_id===s.source_model_id||p.asset_id===s.original_asset_id)throw Error('Type or alternative-model violation');
    assets.add(p.asset_id);distinctFromSource=true;
   }
   for(const g of r.groups)if(new Set(r.placements.filter(p=>g.slot_ids.includes(p.id)).map(p=>p.asset_id)).size!==1)throw Error('Mixed chairs within source group');
   counts.push({objects:ROOMKIT_SCENE.objects.length,meshes:q.pickables.length,bodies:q.tabletop?.world.bodies.length});
   for(const slot of q.chairs.spec.slots){const b=q.bounds(slot.id);if(Math.abs(b.min.z-slot.position[2])>.005)throw Error('Chair not on source floor');}
  }
  return {seeds:50,assets:[...assets],distinctFromSource,counts,milliseconds:performance.now()-elapsed};
 });
 assert.ok(seeded.assets.length>=1,'At least one compatible library asset must be usable');
 assert.deepEqual((await page.evaluate(()=>roomkitQA.chairs.layout.anchors)).sort((a,b)=>a.id.localeCompare(b.id)),anchors,'All seeds preserve the initial current anchors');
 assert.ok(seeded.counts.every(c=>c.objects===seeded.counts[0].objects));
 const chairContact=await page.evaluate(()=>{
  const q=roomkitQA;if(!q.tabletop)return null;
  const choices=q.chairs.layout.placements.map(p=>({p,t:q.chairs.spec.templates.find(t=>t.id===p.template),s:q.chairs.spec.slots.find(s=>s.id===p.id)}));
  choices.sort((a,b)=>Math.abs(b.t.specification.seat.height_m-b.s.original_specification.seat.height_m)-Math.abs(a.t.specification.seat.height_m-a.s.original_specification.seat.height_m));
  const {p,t,s}=choices[0],seat=t.proxies.find(b=>b.name===t.specification.seat.part),x=(seat.min[0]+seat.max[0])/2,y=(seat.min[1]+seat.max[1])/2;
  const z=p.position[2]+seat.max[2],body=q.tabletop.world.bodies[0],Body=body.constructor,Vec3=body.position.constructor;
  const Box=q.tabletop.world.bodies.find(b=>b.mass===0&&b.shapes[0]?.halfExtents).shapes[0].constructor;
  const probe=new Body({mass:.1,shape:new Box(new Vec3(.02,.02,.02)),position:new Vec3(p.position[0]+Math.cos(p.yaw)*x-Math.sin(p.yaw)*y,p.position[1]+Math.sin(p.yaw)*x+Math.cos(p.yaw)*y,z+.09)});
  q.tabletop.world.addBody(probe);
  try{q.tabletop.advance(240);return {expectedSeatHeight:z,actualProbeBottom:probe.position.z-.02,sourceSeatHeight:p.position[2]+s.original_specification.seat.height_m};}
  finally{q.tabletop.world.removeBody(probe);}
 });
 if(chairContact)assert.ok(Math.abs(chairContact.actualProbeBottom-chairContact.expectedSeatHeight)<.006,'Physics must use the replacement chair seat: '+JSON.stringify(chairContact));
 const linked=await page.evaluate(()=>{
  const q=roomkitQA,id=q.chairs.spec.slots[0].id;q.sceneGraph.setSelection(id);q.sceneGraph.refresh(true);
  const graph=q.sceneGraph.snapshot(),node=graph.nodes.find(n=>n.id===id);
  if(new Set(graph.nodes.map(n=>n.id)).size!==graph.nodes.length)throw Error('Duplicate graph identities');
  return {node,floor:q.chairs.spec.floor_support.id,edges:graph.edges.filter(e=>e.to===id||e.from===id),frames:q.chairs.spec.animation_frames_checked};
 });
 assert.ok(linked.node.seating.specification.seat);assert.equal(linked.node.seating.supported_by,linked.floor);
 assert.ok(linked.edges.some(e=>e.from===linked.floor&&e.relation==='supports'));if(linked.node.seating.table_id)assert.ok(linked.edges.some(e=>e.relation==='faces'));
 // Live furniture changes must be read at swap time, including atomic failure.
 const blocked=await page.evaluate(()=>{
  const q=roomkitQA,slot=q.chairs.spec.slots[0],obstacle=q.pickables.find(m=>m.userData.owner&&!q.chairs.has(m.userData.owner)&&!m.userData.tabletop&&!m.userData.joint);
  if(!obstacle)throw Error('Cross-scene fixture needs a movable obstacle for the live-context check');
  const saved={matrix:obstacle.matrix.clone(),auto:obstacle.matrixAutoUpdate,cutaway:obstacle.userData.cutaway,owner:obstacle.userData.owner};
  obstacle.geometry.computeBoundingBox();const b=obstacle.geometry.boundingBox,c=b.getCenter(obstacle.position.clone()),d=b.getSize(obstacle.position.clone());
  const world=obstacle.matrixWorld.clone().makeScale(4/Math.max(d.x,.01),4/Math.max(d.y,.01),3/Math.max(d.z,.01));
  const center=c.clone().applyMatrix4(world);world.setPosition(slot.position[0]-center.x,slot.position[1]-center.y,slot.position[2]+1.5-center.z);
  obstacle.parent.updateWorldMatrix(true,false);obstacle.matrix.copy(obstacle.parent.matrixWorld.clone().invert().multiply(world));obstacle.matrixAutoUpdate=false;obstacle.userData.cutaway=false;obstacle.userData.owner='qa-blocker';
  const before=JSON.stringify(q.chairs.layout),hash=location.hash;
  try{const r=q.chairs.regenerate('live-blocker');return {passed:r.passed,reasons:r.rejections,unchanged:before===JSON.stringify(q.chairs.layout)&&hash===location.hash};}
  finally{obstacle.matrix.copy(saved.matrix);obstacle.matrixAutoUpdate=saved.auto;obstacle.userData.cutaway=saved.cutaway;obstacle.userData.owner=saved.owner;}
 });
 assert.equal(blocked.passed,false);assert.ok(blocked.unchanged);assert.ok(Object.values(blocked.reasons).some(r=>Object.keys(r).some(k=>k.startsWith('collision:'))));
 assert.equal(linked.frames,await page.evaluate(()=>ROOMKIT_SCENE.animation?.frames||0));
 // Exercise actual style choice, swap, restore and independent tabletop seed controls.
 await page.locator('#chair-controls details').evaluate(e=>e.open=true);
 const style=await page.evaluate(()=>{for(const template of roomkitQA.chairs.spec.templates)if(roomkitQA.chairs.regenerate('style-check',template.asset_id).passed)return template.asset_id;return null;});
 if(style){await page.selectOption('#chair-asset',style);await page.click('#swap-chairs');assert.ok(await page.evaluate(()=>roomkitQA.chairs.lastReport.passed));}
 await page.screenshot({timeout:120000,path:resolve(out,'chairs-single-style.png')});
 const chairSeed=await page.evaluate(()=>roomkitQA.chairs.layout.seed);
 const hasTabletop=await page.evaluate(()=>!!roomkitQA.tabletop);
 if(hasTabletop){await page.click('#graph-swap');assert.equal(await page.evaluate(()=>new URLSearchParams(location.hash.slice(1)).get('chairSeed')),chairSeed);}
 const tabletopSeed=await page.evaluate(()=>roomkitQA.tabletop?.layout.seed);
 await page.click('#original-chairs');assert.equal(await page.evaluate(()=>roomkitQA.tabletop?.layout.seed),tabletopSeed);
 assert.equal(await page.evaluate(()=>roomkitQA.chairs.layout.seed),'original');
 await page.selectOption('#chair-asset','');await page.click('#swap-chairs');
 await page.locator('#chair-controls details').evaluate(e=>e.open=false);
 await page.screenshot({timeout:120000,path:resolve(out,'chairs-final.png')});
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({timeout:120000,path:resolve(out,'chairs-mobile.png'),fullPage:true});assert.deepEqual(errors,[]);
 await writeFile(resolve(out,'chair-validation.json'),JSON.stringify({passed:true,outcome:'replaced',placementFixture:placementFixture||null,slots:report.placements.length,groups:report.groups,seedReproducible:true,currentAnchorsPreserved:true,
  sameModelGroupsPreserved:true,seatingTypesPreserved:true,originalModelsExcluded:true,
  seedsChecked:seeded.seeds,assetsExercised:seeded.assets,alternativeToSourceAssetExercised:seeded.distinctFromSource,allOrNothingRejection:true,liveObstacleRejection:true,sourceFloorAnchors:true,sourceAnimationFrames:linked.frames,
  typedGraphRelations:true,replacementChairContact:chairContact,independentScopeSeeds:true,mobile:true,firstPlanMilliseconds:report.milliseconds,seedSweepMilliseconds:seeded.milliseconds,errors},null,2));
 console.log('Chair swap validation passed');
 }
}finally{await browser.close();}

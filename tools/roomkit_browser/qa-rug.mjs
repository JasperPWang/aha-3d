import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html,out]=process.argv.slice(2);
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage();await page.goto(pathToFileURL(resolve(html)).href,{timeout:120000});await page.waitForFunction(()=>window.roomkitQA?.ready,{},{timeout:120000});
 const report=await page.evaluate(()=>{
  const q=roomkitQA;q.scene.updateMatrixWorld(true);const chair=q.bounds('lounge-chair-a');
  const covers=q.pickables.filter(m=>/\brug\b/i.test(m.name));
  const boxes=covers.map(m=>{m.geometry.computeBoundingBox();return m.geometry.boundingBox.clone().applyMatrix4(m.matrixWorld);});
  const passable=boxes.map((b,i)=>q.walkableCover(covers[i],b,chair));
  const main=covers.findIndex(m=>m.name==='Large bound area rug'),rug=boxes[main];
  const probe=chair.clone();probe.min.set(rug.min.x-.5,rug.min.y+.2,chair.min.z);probe.max.set(rug.min.x-.1,rug.min.y+.6,chair.min.z+.6);
  const delta=q.camera.position.clone().set(1,0,0);
  const blockedBefore=q.constrain(probe.clone(),delta,[rug]).x;
  const after=q.constrain(probe.clone(),delta,q.walkableCover(covers[main],rug,probe)?[]:[rug]).x;
  const wall=rug.clone();wall.max.z=probe.max.z+1;
  const wallBlocks=q.constrain(probe.clone(),delta,[wall]).x<1;
  const raised=rug.clone();raised.translate(delta.clone().set(0,0,1));
  const obstacles=q.dragObstacles('lounge-chair-a',chair);
  return {count:covers.length,allPassable:passable.every(Boolean),blockedBefore,after,wallBlocks,tallRugSolid:!q.walkableCover(covers[main],wall,probe),raisedRugSolid:!q.walkableCover(covers[main],raised,probe),rugRemoved:!obstacles.some(b=>b.equals(rug))};
 });
 assert.ok(report.count>0);assert.ok(report.allPassable);assert.ok(report.blockedBefore<1);assert.equal(report.after,1);assert.ok(report.wallBlocks&&report.tallRugSolid&&report.raisedRugSolid&&report.rugRemoved);
 await writeFile(resolve(out,'rug-validation.json'),JSON.stringify({passed:true,...report},null,2));console.log('Rug regression passed');
}finally{await browser.close();}

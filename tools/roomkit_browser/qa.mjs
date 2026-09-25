import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [html, out]=process.argv.slice(2);
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:1440,height:960}});
const errors=[],requests=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('request',r=>{if(r.url().startsWith('http'))requests.push(r.url());});
try {
 await page.goto(pathToFileURL(resolve(html)).href);
 await page.waitForFunction(()=>window.roomkitQA?.ready);
 await page.waitForTimeout(800);
 assert.equal(await page.locator('#error').textContent(),'');
 const initial=await page.evaluate(()=>({objects:ROOMKIT_SCENE.objects.length,joints:roomkitQA.joints.size,meshes:roomkitQA.pickables.length}));
 assert.equal(initial.objects,8);assert.equal(initial.joints,10);
 await page.screenshot({path:resolve(out,'closed.png')});
 // Actual canvas click on a visible moving panel, not direct state mutation.
 const targets=await page.evaluate(()=>{
   const q=roomkitQA,r=q.renderer.domElement.getBoundingClientRect();
   return q.pickables.filter(m=>m.userData.joint && /door left|drawer.*front/i.test(m.name)).map(m=>{
     const p=m.geometry.boundingSphere.center.clone().applyMatrix4(m.matrixWorld).project(q.camera);
     return {id:m.userData.joint,x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2};
   });
 });
 let clicked=null;
 for(const p of targets){await page.mouse.click(p.x,p.y);await page.waitForTimeout(100);const opened=await page.evaluate(id=>roomkitQA.joints.get(id).target,p.id);if(opened===1){clicked=p.id;break;}}
 assert.ok(clicked,'Canvas click must open a real moving panel');
 await page.waitForFunction(id=>roomkitQA.joints.get(id).value===1,clicked);
 assert.equal(await page.evaluate(()=>[...roomkitQA.joints.values()].filter(j=>j.value>0).length),1,'Other joints remain closed');
 await page.screenshot({path:resolve(out,'clicked.png')});
 await page.click('#close-all');await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===0));
 await page.selectOption('#objects','cabinet-mixed');
 const slider=page.locator('#joints input').first();await slider.focus();await slider.press('Home');await slider.press('ArrowRight');
 assert.ok(await page.evaluate(()=>[...roomkitQA.joints.values()].some(j=>j.value>0 && j.value<1)),'Keyboard slider produces intermediate pose');
 await page.click('#open-all');await page.waitForFunction(()=>[...roomkitQA.joints.values()].every(j=>j.value===1));
 await page.screenshot({path:resolve(out,'open.png')});
 // Every drawer and hinge has actual evaluated movement in the browser.
 const movements=await page.evaluate(()=>[...roomkitQA.joints.values()].map(j=>({id:j.id,type:j.type,translation:j.a.p.distanceTo(j.group.position),angle:j.a.q.angleTo(j.group.quaternion)})));
 assert.ok(movements.every(j=>j.type==='slider'?j.translation>.1:j.angle>.5));
 await page.selectOption('#objects','chair-1');assert.match(await page.locator('#details').textContent(),/chair-1/);
 assert.equal(await page.locator('#joints input').count(),0);
 await page.click('#plan');assert.equal(await page.evaluate(()=>roomkitQA.mode),'plan');await page.waitForTimeout(300);
 await page.screenshot({path:resolve(out,'plan.png')});
 await page.setViewportSize({width:390,height:844});await page.click('#orbit');await page.waitForTimeout(300);
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No horizontal mobile overflow');
 await page.screenshot({path:resolve(out,'mobile.png'),fullPage:true});
 assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
 await writeFile(resolve(out,'browser-validation.json'),JSON.stringify({passed:true,initial,canvas_clicked_joint:clicked,independent_click:true,keyboard_slider:true,all_joints_move:movements,mobile_no_horizontal_overflow:true,external_requests:requests,page_errors:errors},null,2));
 console.log('Browser validation passed');
} finally {await browser.close();}

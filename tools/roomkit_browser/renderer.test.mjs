import test from 'node:test';
import assert from 'node:assert/strict';
import {createRenderer} from './renderer.js';

function fixture(accept){
 const calls=[],canvases=[],context={getContextAttributes:()=>({antialias:false}),getExtension:()=>({loseContext(){}})};
 function canvas(){const c={listener:null,addEventListener(t,l){this.listener=l;},removeEventListener(){this.listener=null;},getContext(type,options){calls.push({canvas:c,type,options});if(accept(options))return context;this.listener?.({statusMessage:'Test driver rejected context'});return null;},cloneNode:canvas,replaceWith(){}};canvases.push(c);return c;}
 return {canvas:canvas(),calls,canvases};
}
test('falls back on a fresh canvas, removing expensive context attributes',()=>{
 const f=fixture(o=>!o.antialias&&!o.preserveDrawingBuffer),reports=[];
 class Renderer{constructor(options){this.options=options;}}
 const result=createRenderer(Renderer,f.canvas,{report:r=>reports.push(structuredClone(r))});
 assert.equal(result.profile,'compatible');assert.equal(f.calls.length,2);
 assert.notEqual(f.calls[0].canvas,f.calls[1].canvas);assert.equal(result.renderer.options.context.getContextAttributes().antialias,false);
 assert.equal(reports.at(-1).status,'ready');
});
test('total failure preserves real creation-event reasons and never reports ready',()=>{
 const f=fixture(()=>false),reports=[];
 assert.throws(()=>createRenderer(class{},f.canvas,{report:r=>reports.push(structuredClone(r))}),/Test driver rejected context/);
 assert.equal(f.calls.length,3);assert.equal(reports.at(-1).status,'failed');assert.ok(reports.every(r=>r.status!=='ready'));
});
test('successful standard context needs only one allocation',()=>{
 const f=fixture(()=>true);assert.equal(createRenderer(class{},f.canvas).profile,'standard');assert.equal(f.calls.length,1);
});

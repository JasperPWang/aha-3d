import {Broadphase, Body} from 'cannon-es';

// Room demos contain many static mesh parts and only a few moving props.
// Never enumerate static/static or sleeping/sleeping pairs. Exact world AABBs
// limit narrowphase work to each moving body's local region, without clipping
// the area in which users can drop objects or changing collision geometry.
export class ActiveBodyBroadphase extends Broadphase {
 constructor(){super();this.useBoundingBoxes=true;this.lastChecks=0;}
 collisionPairs(world,pairs1,pairs2){
  const active=[],inactive=[];
  for(const body of world.bodies){
   if(body.aabbNeedsUpdate)body.updateAABB();
   ((body.type&Body.STATIC)||body.sleepState===Body.SLEEPING?inactive:active).push(body);
  }
  this.lastChecks=0;
  const check=(a,b)=>{
   this.lastChecks++;
   if(this.needBroadphaseCollision(a,b)&&a.aabb.overlaps(b.aabb)){pairs1.push(a);pairs2.push(b);}
  };
  for(let i=0;i<active.length;i++){
   for(let j=i+1;j<active.length;j++)check(active[i],active[j]);
   for(const body of inactive)check(active[i],body);
  }
 }
 aabbQuery(world,aabb,result=[]){
  for(const body of world.bodies){if(body.aabbNeedsUpdate)body.updateAABB();if(body.aabb.overlaps(aabb))result.push(body);}
  return result;
 }
}

export function installPerformanceBudget(qa){
 const world=qa.tabletop?.world;if(!world)return;
 const previous=world.broadphase;
 // SAP registers listeners with the world; detach them when replacing it.
 if(previous._addBodyHandler)world.removeEventListener('addBody',previous._addBodyHandler);
 if(previous._removeBodyHandler)world.removeEventListener('removeBody',previous._removeBodyHandler);
 world.broadphase=new ActiveBodyBroadphase();world.broadphase.setWorld(world);
 world.solver.iterations=10;
}

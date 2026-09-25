import * as CANNON from 'cannon-es';

export function createSupportBody(s) {
 const n=s.footprint.length,center=new CANNON.Vec3(s.footprint.reduce((sum,p)=>sum+p[0],0)/n,s.footprint.reduce((sum,p)=>sum+p[1],0)/n,(s.min[2]+s.max[2])/2);
 // Convex collision vertices must surround their local origin. World-space
 // vertices with a zero body origin break contacts for below-zero tables.
 const vertices=[...s.footprint.map(p=>new CANNON.Vec3(p[0]-center.x,p[1]-center.y,s.min[2]-center.z)),...s.footprint.map(p=>new CANNON.Vec3(p[0]-center.x,p[1]-center.y,s.max[2]-center.z))];
 const faces=[Array.from({length:n},(_,i)=>n-1-i),Array.from({length:n},(_,i)=>n+i)];
 for(let i=0;i<n;i++){const j=(i+1)%n;faces.push([i,j,j+n,i+n]);}
 return new CANNON.Body({mass:0,position:center,shape:new CANNON.ConvexPolyhedron({vertices,faces})});
}

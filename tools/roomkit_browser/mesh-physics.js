import * as THREE from 'three';
import * as CANNON from 'cannon-es';
import {ConvexHull} from 'three/addons/math/ConvexHull.js';

// A bounded convex proxy from actual mesh extremes, transformed into world
// space. Unlike an enclosing box it retains tapered lamp bases and rotation.
export function createMeshBody(mesh,{preserveBase=false}={}) {
 mesh.geometry.computeBoundingBox();
 const box=mesh.geometry.boundingBox,size=box.getSize(new THREE.Vector3());
 // A rotated zero-thickness pane has a large world AABB but no solid volume.
 if(Math.min(size.x,size.y,size.z)<1e-7||Math.abs(mesh.matrixWorld.determinant())<1e-12)return null;
 const center=box.getCenter(new THREE.Vector3()).applyMatrix4(mesh.matrixWorld);
 const points=[],position=mesh.geometry.attributes.position;
 for(const x of [-1,0,1])for(const y of [-1,0,1])for(const z of [-1,0,1]){
  if(!x&&!y&&!z)continue;
  let best=-Infinity,index=0;
  for(let i=0;i<position.count;i++){const score=x*position.getX(i)+y*position.getY(i)+z*position.getZ(i);if(score>best){best=score;index=i;}}
  const p=new THREE.Vector3().fromBufferAttribute(position,index).applyMatrix4(mesh.matrixWorld);
  if(!points.some(q=>p.distanceToSquared(q)<1e-16))points.push(p);
 }
 // Equal-height vertices otherwise tie for the downward extreme, leaving only
 // one point from a flat vessel base and making it balance on a sloping proxy.
 if(preserveBase){
  for(let direction=0;direction<12;direction++){
   const angle=direction*Math.PI/6;let best=-Infinity,index=-1;
   for(let i=0;i<position.count;i++){
    if(position.getZ(i)>box.min.z+1e-6)continue;
    const score=Math.cos(angle)*position.getX(i)+Math.sin(angle)*position.getY(i);
    if(score>best){best=score;index=i;}
   }
   if(index<0)continue;
   const p=new THREE.Vector3().fromBufferAttribute(position,index).applyMatrix4(mesh.matrixWorld);
   if(!points.some(q=>p.distanceToSquared(q)<1e-16))points.push(p);
  }
 }
 if(points.length<4)return null;
 const hull=new ConvexHull().setFromPoints(points),vertices=[],faces=[],indices=new Map(),planes=[];
 // Recenter inside the sampled hull, including asymmetric tapered parts.
 center.set(0,0,0);for(const p of points)center.add(p);center.divideScalar(points.length);
 for(const face of hull.faces){const indicesForFace=[];let edge=face.edge;do{
  const p=edge.head().point;if(!indices.has(p)){indices.set(p,vertices.length);vertices.push(new CANNON.Vec3(p.x-center.x,p.y-center.y,p.z-center.z));}
  indicesForFace.push(indices.get(p));edge=edge.next;
 }while(edge!==face.edge);
  let plane=planes.find(p=>p.normal.dot(face.normal)>1-1e-7&&Math.abs(p.constant-face.constant)<1e-6);
  if(!plane){plane={normal:face.normal.clone(),constant:face.constant,indices:new Set()};planes.push(plane);}
  for(const i of indicesForFace)plane.indices.add(i);
 }
 // Merge coplanar hull triangles; their internal edges destabilize resting
 // contacts in Cannon's convex clipping solver.
 for(const plane of planes){
  const ids=[...plane.indices],origin=new THREE.Vector3();for(const i of ids)origin.add(new THREE.Vector3(...vertices[i].toArray()));origin.divideScalar(ids.length);
  const u=new THREE.Vector3(...vertices[ids[0]].toArray()).sub(origin).normalize(),v=new THREE.Vector3().crossVectors(plane.normal,u);
  const angle=i=>{const p=new THREE.Vector3(...vertices[i].toArray()).sub(origin);return Math.atan2(p.dot(v),p.dot(u));};
  ids.sort((a,b)=>angle(a)-angle(b));faces.push(ids);
 }
 const volume=faces.reduce((sum,f)=>sum+f.slice(1,-1).reduce((s,i,j)=>s+vertices[f[0]].dot(vertices[i].cross(vertices[f[j+2]]))/6,0),0);
 if(!Number.isFinite(volume)||volume<1e-12)return null;
 return new CANNON.Body({mass:0,position:new CANNON.Vec3(...center),shape:new CANNON.ConvexPolyhedron({vertices,faces})});
}

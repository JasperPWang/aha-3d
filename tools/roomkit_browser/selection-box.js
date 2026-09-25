import * as THREE from 'three';

// Furniture records have translation-only browser groups. Recover the authored
// frame from their largest component; physical props supply their rigid frame.
export function selectionBounds(meshes, rigidFrame=null) {
 if(!meshes.length)return null;
 let reference=rigidFrame,best=-1;
 if(!reference)for(const mesh of meshes){
  if(!mesh.geometry.boundingBox)mesh.geometry.computeBoundingBox();
  const size=mesh.geometry.boundingBox.getSize(new THREE.Vector3());
  const volume=size.x*size.y*size.z*Math.abs(mesh.matrixWorld.determinant());
  if(volume>best){reference=mesh;best=volume;}
 }
 const position=new THREE.Vector3(),rotation=new THREE.Quaternion(),scale=new THREE.Vector3();
 reference.matrixWorld.decompose(position,rotation,scale);
 const matrix=new THREE.Matrix4().compose(position,rotation,new THREE.Vector3(1,1,1));
 const inverse=matrix.clone().invert(),box=new THREE.Box3(),point=new THREE.Vector3();
 for(const mesh of meshes){
  const transform=new THREE.Matrix4().multiplyMatrices(inverse,mesh.matrixWorld),vertices=mesh.geometry.attributes.position;
  for(let i=0;i<vertices.count;i++)box.expandByPoint(point.fromBufferAttribute(vertices,i).applyMatrix4(transform));
 }
 return {box,matrix};
}

export function createSelectionBox(meshes,rigidFrame=null) {
 const bounds=selectionBounds(meshes,rigidFrame);if(!bounds)return null;
 const {box,matrix}=bounds,points=[];
 for(const z of [box.min.z,box.max.z])for(const y of [box.min.y,box.max.y])for(const x of [box.min.x,box.max.x])points.push(new THREE.Vector3(x,y,z).applyMatrix4(matrix));
 const geometry=new THREE.BufferGeometry().setFromPoints(points);
 geometry.setIndex([0,1,1,3,3,2,2,0,4,5,5,7,7,6,6,4,0,4,1,5,2,6,3,7]);
 const helper=new THREE.LineSegments(geometry,new THREE.LineBasicMaterial({color:0x148298,toneMapped:false}));
 helper.userData.selectionBox=true;return helper;
}

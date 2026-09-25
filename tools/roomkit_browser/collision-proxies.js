import * as THREE from 'three';

// Cover the entire local mesh bounds with small boxes before rotating them.
// A single world AABB around a diagonal wall can otherwise fill empty room space.
// Every slice remains conservative; this never removes obstacle geometry.
// Actor/deforming meshes are excluded by the caller; static geometry can be replaced.
const cache = new WeakMap();
export function obstacleBounds(mesh) {
  const cached = cache.get(mesh);
  if (cached && cached.geometry === mesh.geometry && cached.matrix.equals(mesh.matrixWorld)) return cached.boxes;
  if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
  const local = mesh.geometry.boundingBox, matrix = mesh.matrixWorld.elements;
  let boxes = [local.clone()];
  for (const [index, axis] of ['x', 'y', 'z'].entries()) {
    const extent = local.max[axis] - local.min[axis];
    const dx = Math.abs(matrix[index * 4] * extent);
    const dy = Math.abs(matrix[index * 4 + 1] * extent);
    // Axis-aligned edges already have tight world bounds; split diagonal edges.
    if (Math.min(dx, dy) < 0.025) continue;
    const count = Math.ceil(Math.hypot(dx, dy) / 0.2);
    if (count < 2) continue;
    boxes = boxes.flatMap(box => Array.from({length: count}, (_, i) => {
      const slice = box.clone();
      slice.min[axis] = local.min[axis] + extent * i / count;
      slice.max[axis] = local.min[axis] + extent * (i + 1) / count;
      return slice;
    }));
  }
  boxes.forEach(box => box.applyMatrix4(mesh.matrixWorld));
  cache.set(mesh, {geometry: mesh.geometry, matrix: mesh.matrixWorld.clone(), boxes});
  return boxes;
}

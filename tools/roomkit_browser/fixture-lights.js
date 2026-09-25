/** Complete legacy exported fixture records without changing saved scene geometry. */
export function completeFixtureLights(data) {
  if (!data.lighting) return;
  const fixture = /lamp|chandelier|sconce|pendant|lantern|downlight|ceiling (?:light|practical)|fixture\/lighting|furniture\/lighting/i;
  const daylight = /daylight|window|softbox|fill|bounce|sun|sky/i;
  const objects = new Map(data.objects.map(o => [o.instance_id, o]));
  const lights = data.lighting.lights;
  for (const light of lights) {
    if (fixture.test(light.name) && !daylight.test(light.name)) light.lamp = true;
  }
  const groups = new Map();
  for (const mesh of data.meshes) {
    if (lights.some(light => light.lamp && light.emitter_meshes?.includes(mesh.name))) continue;
    const owner = objects.get(mesh.owner);
    if (!owner || !fixture.test(`${owner.instance_id} ${owner.semantic_class} ${mesh.name}`)) continue;
    const emits = mesh.groups.some(g => {
      const material = data.materials[g.material];
      return material.emissive_intensity > 0 && material.emissive?.some(c => c > 0);
    });
    if (!emits) continue;
    const key = `${mesh.owner}/${mesh.joint || ''}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(mesh);
  }
  for (const meshes of groups.values()) {
    // Existing explicit bindings win. Rebuilding is idempotent.
    const names = meshes.map(m => m.name), owner = meshes[0].owner, joint = meshes[0].joint;
    let light = lights.find(l => l.lamp && l.owner === owner && l.joint === joint);
    if (!light) light = lights.find(l => l.lamp && l.emitter_meshes?.some(n => names.includes(n)));
    if (!light) {
      const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
      for (const mesh of meshes) {
        const a = mesh.matrix, p = mesh.positions;
        for (let i = 0; i < p.length; i += 3) for (let k = 0; k < 3; k++) {
          const v = a[k]*p[i] + a[k+4]*p[i+1] + a[k+8]*p[i+2] + a[k+12];
          min[k] = Math.min(min[k], v); max[k] = Math.max(max[k], v);
        }
      }
      const position = min.map((v,i) => (v+max[i])/2);
      light = {id:`emitter-${owner}-${joint || 'fixed'}`, name:`${owner} emitters`,
        type:'POINT', position, direction:[0,0,-1], owner, joint,
        color:[1,.78,.48], energy:12, lamp:true,
        provenance:'inferred from authored emissive fixture surfaces', emitter_meshes:[]};
      lights.push(light);
    }
    light.emitter_meshes = [...new Set([...(light.emitter_meshes || []), ...names])];
  }
}

// Architectural roots stay fixed even when older exports defaulted to movable.
export function lockStructure(data){
 const structural = value => /^(architecture|structure)(\/|$)|^(walls?|floors?|ceilings?|roofs?|windows?|doors?|stairs?|columns?|beams?)(\/|$)/i.test(value || '');
 const fixed = new Set(data.objects.filter(o=>structural(o.semantic_class)).map(o=>o.instance_id));
 for(const mesh of data.meshes){
  if(mesh.owner && structural(mesh.surface))fixed.add(mesh.owner);
 }
 // Moving a support also moves its children, so lock all structural ancestors.
 const objects = new Map(data.objects.map(o=>[o.instance_id,o]));
 for(const id of [...fixed]){
  let object=objects.get(id);const seen=new Set();
  while(object&&!seen.has(object.instance_id)){
   seen.add(object.instance_id);fixed.add(object.instance_id);
   object=objects.get(object.support_id);
  }
 }
 for(const id of fixed)if(objects.has(id))objects.get(id).movable=false;
 return fixed;
}

import test from 'node:test';
import assert from 'node:assert/strict';
import {PRESETS,recipe,generate,sampler} from './material-generator.js';
import {projectMaterialUV} from './materials.js';
import * as THREE from 'three';

test('recipes reproduce all PBR maps; seeds change patterns',()=>{
  for(const preset of Object.keys(PRESETS)){
    const a=generate({preset,seed:'example'},32),b=generate(a.recipe,32),c=generate({preset,seed:'other'},32);
    for(const key of ['baseColor','orm','normal','height'])assert.deepEqual(a[key],b[key]);
    assert.notDeepEqual(PRESETS[preset].family==='glass'?a.height:a.baseColor,PRESETS[preset].family==='glass'?c.height:c.baseColor,preset);
    assert.equal(a.orm[2],PRESETS[preset].metalness*255);
    assert.ok(new Set(a.orm.filter((_,i)=>i%4===1)).size>1);
  }
});
test('all channels tile continuously across both axes',()=>{
  for(const version of [1,2,3])for(const preset of Object.keys(PRESETS).filter(k=>(PRESETS[k].since??1)<=version)){
    const s=sampler({preset,version});
    for(const [u,v] of [[0,.37],[.63,0],[.233,.781],[-.6,-.33]]){
      for(const t of [s(u+1,v),s(u,v+1)]){
        const a=s(u,v);for(const key of ['height','roughness','metalness'])assert.ok(Math.abs(a[key]-t[key])<1e-10,preset+' '+key);
        a.color.forEach((x,i)=>assert.ok(Math.abs(x-t.color[i])<1e-10));
      }
    }
  }
});
test('scale and relief control physical normals without altering palette',()=>{
  const a=generate({relief:.003,tileSize:.1},32),b=generate({relief:0,tileSize:.1},32),c=generate({relief:.003,tileSize:2},32);
  assert.deepEqual(a.baseColor,b.baseColor);assert.notDeepEqual(a.normal,b.normal);assert.notDeepEqual(a.normal,c.normal);
  for(let i=0;i<b.normal.length;i+=4)assert.deepEqual([...b.normal.slice(i,i+4)],[128,128,255,255]);
});
test('bad recipes and unbounded allocations fail explicitly',()=>{
  for(const r of [{version:4},{preset:'missing'},{tileSize:0},{roughness:NaN},{relief:99},{color:'white'},{bogus:1},{rotation:Infinity}])assert.throws(()=>recipe(r));
  for(const size of [0,31,65,4096,NaN])assert.throws(()=>generate({},size));
});
test('UV generation preserves original geometry, groups and lightmap UVs',()=>{
  const g=new THREE.BoxGeometry(2,3,4);g.setAttribute('uv1',g.attributes.uv.clone());g.deleteAttribute('uv');
  const m=new THREE.Mesh(g);m.scale.set(2,1,1);m.updateMatrix();const p=projectMaterialUV(m);
  assert.equal(g.attributes.uv,undefined);assert.ok(p.attributes.uv);assert.ok(p.attributes.uv1);assert.equal(p.groups.length,g.groups.length);
  assert.equal(Math.max(...p.attributes.uv.array),2);
  const parent=new THREE.Group();parent.scale.y=2;parent.add(m);const scaled=projectMaterialUV(m);assert.equal(Math.max(...scaled.attributes.uv.array),3);scaled.dispose();p.dispose();g.dispose();
});

test('PNG bundle round-trips every channel with the correct vertical orientation',async()=>{
  const {mkdtemp,writeFile,readFile,rm}=await import('node:fs/promises');
  const {tmpdir}=await import('node:os');const {join}=await import('node:path');
  const {fileURLToPath}=await import('node:url');const {spawnSync}=await import('node:child_process');const {inflateSync}=await import('node:zlib');
  const root=await mkdtemp(join(tmpdir(),'roomkit-pbr-test-'));
  try{
    const input=join(root,'recipe.json'),out=join(root,'bundle'),r={preset:'marble',seed:'png',tileSize:.7};
    await writeFile(input,JSON.stringify(r));
    const command=[fileURLToPath(new URL('./material-cli.mjs',import.meta.url)),input,out,'32'];
    const result=spawnSync(process.execPath,command,{encoding:'utf8'});assert.equal(result.status,0,result.stderr);
    const tile=generate(r,32);
    for(const key of ['baseColor','orm','normal','height']){
      const png=await readFile(join(out,key+'.png'));assert.deepEqual([...png.subarray(0,8)],[137,80,78,71,13,10,26,10]);
      const parts=[];for(let at=8;at<png.length;){const n=png.readUInt32BE(at);if(png.toString('ascii',at+4,at+8)==='IDAT')parts.push(png.subarray(at+8,at+8+n));at+=n+12;}
      const rows=inflateSync(Buffer.concat(parts));
      for(let y=0;y<32;y++){assert.equal(rows[y*129],0);assert.deepEqual([...rows.subarray(y*129+1,(y+1)*129)],[...tile[key].slice((31-y)*128,(32-y)*128)]);}
    }
    assert.notEqual(spawnSync(process.execPath,command).status,0,'Existing bundles must not be overwritten');
  }finally{await rm(root,{recursive:true,force:true});}
});

// Digests captured from the shipped v1 generator at e4adf3e, before the upgrade.
test('saved version 1 recipes reproduce the shipped maps byte for byte',async()=>{
  const {createHash}=await import('node:crypto');
  const hashes={
    "oak": "922f89ab04263c5fd2cfb38b2e76f184c0b87b80b9784cecaae077a06ec787c9",
    "walnut": "a1351a0d2741a2e1ca4e06a767a4b39e67cbfeda2f5c693f996da0399e287f69",
    "marble": "6f02bb3a033503b966b86be1107578bb7d8514188e5252933d981dab7d5ebc6f",
    "granite": "e029c1bad3192cc9272236f64fa33a47c9b956dae6ddf0237c7c061a1b658927",
    "concrete": "765ed6fc6d37301faefd12afd6d10e59c6d46841744dec89067a0a8136ab2285",
    "steel": "ae9e45a971c27171d92a8930314fcf307a1934517af18ff976b4b33da7007c6b",
    "brass": "b73f433480569fff4b400464808fea836451a729ede9b86b5a6b21adb816842d",
    "copper": "fe1eb5bacf38aea959a2feff24b44da06d522dc5aeb6692f33cb44f43caf8a7c"
};
  for(const [preset,expected] of Object.entries(hashes)){
    const tile=generate({preset,version:1,seed:'compatibility'},32),h=createHash('sha256');
    for(const k of ['baseColor','orm','normal','height'])h.update(tile[k]);
    assert.equal(h.digest('hex'),expected,preset);
    assert.notDeepEqual(tile.baseColor,generate({...tile.recipe,version:2},32).baseColor);
  }
  assert.equal(recipe({}).version,3);assert.equal(recipe({version:1}).version,1);
});

test('version 2 tiles stay unchanged when physical surfaces are introduced',async()=>{
 const {createHash}=await import('node:crypto');
 const hashes={
  "oak": "d8c7d35938aeb8f23c7155c21627d8397168e54c8820e512a89c89aa92af6faf",
  "walnut": "4e6c54bf4d24a51c6d12e70768c35c55893e643e44288f48a4f9dec25314ac6d",
  "marble": "63b5d4f48a8a8c24ab81045f73e4d182e6ce906d7a185cddc047f5d57ab06f78",
  "granite": "345a324b606a1e19968e43f8040e0fb7475abca9d082a3a113ed8fc0ab5beac5",
  "concrete": "1400a7af58ac8b6fa8f797fe20f737e3c4f2f01b33785787f5101d863774108b",
  "steel": "20195c7cf667b1e12a80b6e47c8801692fbe567bb0cd1e63ff92374106591910",
  "brass": "3d0171e9caae672b97bdcc4514f4de38f0b76d06ed72e7f5cc1b6533c45a7682",
  "copper": "ab65cc128328d2f33801ced2aba7d0cae2712438f84bba6e92feb47cfab7b927"
};
 for(const [preset,expected] of Object.entries(hashes)){
  const tile=generate({version:2,preset,seed:'compatibility'},32),h=createHash('sha256');
  for(const key of ['baseColor','orm','normal','height']){h.update(tile[key]);assert.deepEqual(tile[key],generate({version:3,preset,seed:'compatibility'},32)[key]);}
  assert.equal(h.digest('hex'),expected,preset);assert.equal(tile.recipe.transmission,undefined);
 }
});

test('physical recipes validate their scalar layers and reject unsupported legacy presets',()=>{
 for(const input of [{preset:'glass_clear',version:2},{version:1,clearcoat:1},{preset:'steel',transmission:1},{ior:0},{ior:2.4},{transmission:NaN},{clearcoat:-1},{clearcoatRoughness:2},{thickness:-.01},{thickness:Infinity}])assert.throws(()=>recipe(input));
 const a=generate({preset:'porcelain'},32),b=generate({...a.recipe,clearcoat:.4,ior:1.8},32);
 assert.deepEqual(a.baseColor,b.baseColor);assert.equal(b.recipe.clearcoat,.4);assert.equal(recipe({preset:'glass_clear'}).transmission,1);
});

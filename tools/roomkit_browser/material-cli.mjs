#!/usr/bin/env node
/** Generate a portable texture bundle; PNG encoder uses only Node built-ins. */
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {deflateSync} from 'node:zlib';
import {generate} from './material-generator.js';
const [input,out,size='512']=process.argv.slice(2);
if(!input||!out)throw Error('Usage: node material-cli.mjs recipe.json NEW_OUTPUT_DIR [resolution]');
const tile=generate(JSON.parse(await readFile(input,'utf8')),Number(size));
const crcTable=Array.from({length:256},(_,c)=>{for(let k=0;k<8;k++)c=(c&1)?0xedb88320^(c>>>1):c>>>1;return c>>>0;});
function chunk(type,data){const name=Buffer.from(type),body=Buffer.concat([name,data]),result=Buffer.alloc(body.length+8);result.writeUInt32BE(data.length);body.copy(result,4);let c=0xffffffff;for(const b of body)c=crcTable[(c^b)&255]^(c>>>8);result.writeUInt32BE((c^0xffffffff)>>>0,body.length+4);return result;}
function png(rgba,n){
  const header=Buffer.alloc(13);header.writeUInt32BE(n);header.writeUInt32BE(n,4);header[8]=8;header[9]=6;
  // PNG top row is v=1; both Three DataTexture and Blender use v=0 at bottom.
  const rows=Buffer.alloc(n*(n*4+1));for(let y=0;y<n;y++)Buffer.from(rgba.buffer,rgba.byteOffset+(n-1-y)*n*4,n*4).copy(rows,y*(n*4+1)+1);
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('IDAT',deflateSync(rows)),chunk('IEND',Buffer.alloc(0))]);
}
const directory=resolve(out);await mkdir(directory,{recursive:false});
for(const key of ['baseColor','orm','normal','height'])await writeFile(join(directory,key+'.png'),png(tile[key],tile.size));
await writeFile(join(directory,'material.json'),JSON.stringify({schema_version:1,generator:`roomkit-pbr-v${tile.recipe.version}`,recipe:tile.recipe,resolution:tile.size,maps:{baseColor:'baseColor.png',orm:'orm.png',normal:'normal.png',height:'height.png'},color_spaces:{baseColor:'sRGB',orm:'linear',normal:'linear',height:'linear'},normal_convention:'OpenGL +Y',orm_channels:'R=1 (unoccluded), G=roughness, B=metalness'},null,2)+'\n');
console.log(directory);

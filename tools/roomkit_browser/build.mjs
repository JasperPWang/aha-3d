import {build} from 'esbuild';
import {completeFixtureLights} from './fixture-lights.js';
import {buildFast} from './build-fast.mjs';
import {writeLargeOffline} from './large-offline.mjs';
import {dirname} from 'node:path';
import {readFile, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {gzipSync} from 'node:zlib';
const base = fileURLToPath(new URL('.', import.meta.url));
const [dataPath, output] = process.argv.slice(2);
if (!dataPath || !output) throw Error('Usage: node build.mjs scene.json demo.html');
const result = await build({stdin:{contents:"import './viewer.js'; import {createQuickActions} from './quick-actions.js'; import {createEditorCard} from './editor-card.js'; import {createDemoInteractions} from './demo-interactions.js'; createQuickActions(window.roomkitQA, window.ROOMKIT_SCENE); createEditorCard(window.roomkitQA, window.ROOMKIT_SCENE); createDemoInteractions(window.roomkitQA, window.ROOMKIT_SCENE); import {installPerformanceBudget} from './performance-budget.js'; installPerformanceBudget(window.roomkitQA);",resolveDir:base,sourcefile:'viewer-entry.js'},bundle:true,write:false,minify:true,format:'iife',legalComments:'inline'});
const data = JSON.parse(await readFile(dataPath,'utf8'));
completeFixtureLights(data);
const external=data.animation?.actors.some(a=>a.positions_file);
const safe = JSON.stringify(data).replaceAll('<','\\u003c');
let dataCode=`window.ROOMKIT_SCENE=${safe};`, viewerCode=result.outputFiles[0].text;
if(data.animation&&!external){
 const compressed=gzipSync(Buffer.from(safe),{level:6}).toString('base64');
 dataCode=`window.ROOMKIT_PACKED="${compressed}";`;
 viewerCode=`(async()=>{try{const raw=Uint8Array.from(atob(window.ROOMKIT_PACKED),c=>c.charCodeAt(0));window.ROOMKIT_SCENE=JSON.parse(await new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip'))).text());delete window.ROOMKIT_PACKED;${viewerCode}}catch(e){document.getElementById('error').textContent='Scene loading failed: '+e.message;console.error(e);}})();`;
}
const notices=await Promise.all(['three','cannon-es'].map(name=>readFile(base+'node_modules/'+name+'/LICENSE','utf8')));
viewerCode+='\n/* Bundled dependency licenses\n'+notices.join('\n\n').replaceAll('*/','* /')+'\n*/';
await buildFast(data,await readFile(base+'template.html','utf8'),result.outputFiles[0].text+'\n/* Bundled dependency licenses\n'+notices.join('\n\n').replaceAll('*/','* /')+'\n*/',output.replace(/\.html$/, '-fast.html'),dirname(dataPath));
if(external){
 await writeLargeOffline(data,await readFile(base+'template.html','utf8'),viewerCode,dirname(dataPath),output);
}else{
const html = (await readFile(base+'template.html','utf8')).replace('/*SCENE_DATA*/',()=>dataCode).replace('/*VIEWER_CODE*/',()=>viewerCode.replaceAll('</script','<\\/script'));
await writeFile(output,html,{flag:'wx'});
}
console.log(output);

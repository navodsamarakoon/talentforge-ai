// Build trusted, static ES2017 mappings for n8n's expression-extension parser.
import fs from 'node:fs';
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {correctClassification} from './classification.mjs';
import {correctEnvelope} from './envelope.mjs';
const require=createRequire(new URL('../../../frontend/package.json',import.meta.url));
const ts=require('typescript');
const workflow=correctEnvelope(correctClassification(JSON.parse(fs.readFileSync('.cv-verify/classification-grounded-server.json','utf8').replace(/^\uFEFF/,''))));
const entries={};
for(const node of workflow.nodes.filter(n=>n.type==='n8n-nodes-base.code')){
 const code=node.parameters.jsCode.replace(/return \$input\.all\(\);/g,'return [{json:$json}];').replace(/\$input\.first\(\)\.json/g,'$json');
 const expression="(()=>{ const rows=(()=>{"+code+"})(); const list=Array.isArray(rows)?rows:[rows]; return JSON.stringify({__demo_rows:list.map(row=>row.json)}); })()";
 const output=ts.transpileModule('const __native = '+expression+';',{
  compilerOptions:{target:ts.ScriptTarget.ES2017,module:ts.ModuleKind.None},reportDiagnostics:true,
 });
 assert.equal(output.diagnostics?.length??0,0);
 assert.ok(output.outputText.startsWith('const __native = '));
 const compiled=output.outputText.slice('const __native = '.length).trim().replace(/;$/,'');
 entries['Map '+node.name]={source:'={{ '+expression+' }}',compiled:'={{ '+compiled+' }}'};
}
fs.writeFileSync(new URL('./native_expression_compat.json',import.meta.url),JSON.stringify(entries,null,2)+'\n');
console.log('Generated '+Object.keys(entries).length+' static ES2017 mappings; no workflow or credentials accessed');

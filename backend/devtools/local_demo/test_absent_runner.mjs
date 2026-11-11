import fs from 'node:fs';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import assert from 'node:assert/strict';
import {validateEnvelope} from './envelope.mjs';
const id='TfAbsentRunnerFixture',uuid='12345678-1234-1234-1234-123456789abc';
const body={schema_version:1,application_id:uuid,dispatch_id:uuid,job_id:uuid,organization_id:uuid,
 cv_sha256:'a'.repeat(64),cv_profile:{skills:['Python']},cv_text:'Skills: Python\n'+'Synthetic project evidence. '.repeat(240)};
const recorded=[];
const server=createServer((request,response)=>{
 let input='';request.on('data',chunk=>input+=chunk);request.on('end',()=>{
 recorded.push({path:request.url,...JSON.parse(input)});
 response.writeHead(200,{'Content-Type':'application/json'});response.end('{"recorded":true}');
 });
});
await new Promise(resolve=>server.listen(3031,'127.0.0.1',resolve));
const capture=(name,path)=>({id:name,name,type:'n8n-nodes-base.httpRequest',typeVersion:4.2,position:[600,0],
 parameters:{method:'POST',url:'http://127.0.0.1:3031/'+path,sendBody:true,specifyBody:'json',
 jsonBody:JSON.stringify({dispatch_id:uuid})}});
const nodes=[
 {id:'start',name:'Start',type:'n8n-nodes-base.manualTrigger',typeVersion:1,position:[0,0],parameters:{}},
 {id:'input',name:'Synthetic Envelope',type:'n8n-nodes-base.set',typeVersion:3.4,position:[200,0],parameters:{mode:'raw',jsonOutput:JSON.stringify({body})}},
 {id:'validate',name:'Validate CV Envelope',type:'n8n-nodes-base.set',typeVersion:3.4,position:[400,0],
 onError:'continueErrorOutput',parameters:{mode:'raw',jsonOutput:'={{ (()=>{'+validateEnvelope.toString()+'; return JSON.stringify(validateEnvelope($json.body));})() }}'}},
 capture('Validated','validated'),capture('Failed','failed'),
];
const link=node=>[{node,type:'main',index:0}];
const workflow={id,name:'Synthetic absent runner validation',active:false,nodes,
 connections:{Start:{main:[link('Synthetic Envelope')]},'Synthetic Envelope':{main:[link('Validate CV Envelope')]},
 'Validate CV Envelope':{main:[link('Validated'),link('Failed')]}},settings:{executionOrder:'v1'}};
function cli(...args){return new Promise((resolve,reject)=>{
 const p=spawn('n8n',args);let out='';p.stdout.on('data',x=>out+=x);p.stderr.on('data',x=>out+=x);
 const t=setTimeout(()=>p.kill('SIGKILL'),180000);
 p.on('close',status=>{clearTimeout(t);resolve({status,out});});p.on('error',reject);
});}
try{
 for(const [index,value] of [body,{...body,cv_profile:[]}].entries()){
  workflow.nodes.find(n=>n.name==='Synthetic Envelope').parameters.jsonOutput=JSON.stringify({body:value});
  fs.writeFileSync('/tmp/workflow.json',JSON.stringify([workflow]));
  const imported=await cli('import:workflow','--input=/tmp/workflow.json');assert.equal(imported.status,0);
  const result=await cli('execute','--id='+id,'--rawOutput');
  assert.equal(result.status,0,result.out.slice(-1000));
  assert.doesNotMatch(result.out,/Task request timed out/);
  assert.deepEqual(recorded[index],{path:index===0?'/validated':'/failed',dispatch_id:uuid});
 }
 console.log(JSON.stringify({test:'native validation without runner',pass:true,validated:1,failed:1,emails:0}));
}finally{server.close();}

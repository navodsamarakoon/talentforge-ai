import assert from "node:assert/strict";
import fs from "node:fs";
import {DatabaseSync} from "node:sqlite";
import {spawn,spawnSync} from "node:child_process";

const saved=JSON.parse(fs.readFileSync("/fixture/workflow.json","utf8").replace(/^\uFEFF/,""));
assert.equal(saved.active,false);
assert.equal(saved.activeVersionId,null);
const webhook=structuredClone(saved.nodes.find(node=>node.name==="Webhook"));
assert.equal(webhook.parameters.authentication,"headerAuth");
const credential={id:"FixtureWebhookAuth1",name:"Disposable webhook auth",type:"httpHeaderAuth"};
const header="X-TalentForge-Webhook-Secret";
const secret="disposable-fixture-only";
webhook.disabled=false;
webhook.credentials={httpHeaderAuth:{id:credential.id,name:credential.name}};
const id="FixtureWebhookTest1";
const capture={id:"capture",name:"Capture",type:"n8n-nodes-base.noOp",typeVersion:1,position:[500,0],parameters:{}};
const workflow={id,name:"Disposable webhook authentication",active:false,nodes:[webhook,capture],connections:{Webhook:{main:[[{node:"Capture",type:"main",index:0}]]}},settings:{executionOrder:"v1"}};
fs.writeFileSync("/tmp/credentials.json",JSON.stringify([{...credential,data:{name:header,value:secret}}]));
fs.writeFileSync("/tmp/workflow.json",JSON.stringify([workflow]));
function cli(...args){
  const result=spawnSync("n8n",args,{encoding:"utf8",timeout:120000});
  assert.equal(result.status,0,result.stdout+result.stderr);
}
cli("import:credentials","--input=/tmp/credentials.json");
cli("import:workflow","--input=/tmp/workflow.json");
cli("publish:workflow","--id="+id);
const service=spawn("n8n",["start"],{stdio:"inherit"});
const base="http://127.0.0.1:5678";
try {
  let ready=false;
  for(let i=0;i<90;i++){
    try{ready=(await fetch(base+"/healthz/readiness",{signal:AbortSignal.timeout(1000)})).ok}catch{}
    if(ready)break;
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  assert.ok(ready,"Disposable n8n failed to start");
  const db=new DatabaseSync("/home/node/.n8n/database.sqlite",{readOnly:true});
  const routes=db.prepare("SELECT webhookPath, method FROM webhook_entity").all();
  console.log(JSON.stringify({routes}));
  db.close();
  for(const [label,value,expected] of [["missing",null,403],["incorrect","wrong",403],["valid",secret,200]]){
    const response=await fetch(base+"/webhook/"+webhook.parameters.path,{
      method:"POST",headers:{"Content-Type":"application/json",...(value?{[header]:value}:{})},
      body:JSON.stringify({fixture:true}),signal:AbortSignal.timeout(10000),
    });
    console.log(JSON.stringify({case:label,status:response.status,expected,...(response.status===404?{routeError:(await response.text()).slice(0,600)}:{})}));
    assert.equal(response.status,expected);
  }
} finally {service.kill()}

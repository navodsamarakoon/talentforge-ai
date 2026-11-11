import assert from 'node:assert/strict';
import {performance} from 'node:perf_hooks';
import {validateEnvelope} from './envelope.mjs';
const id='12345678-1234-1234-1234-123456789abc';
const base={schema_version:1,application_id:id,dispatch_id:id,job_id:id,organization_id:id,
 cv_text:'Skills: Python',cv_sha256:'a'.repeat(64),cv_profile:{
   skills:['Python'],source_evidence:{origin:'deterministic_text',sources:[{id:0,field:'skills',line:1}]},
 }};
const cases=[
 ()=>assert.equal(validateEnvelope(base),base),
 ()=>assert.doesNotThrow(()=>validateEnvelope({...base,cv_text:'A'.repeat(6186),cv_profile:{skills:Array(40).fill('Python')}})),
 ()=>assert.doesNotThrow(()=>validateEnvelope({...base,cv_text:'字'.repeat(32000)})),
 ...[null,[],{...base,schema_version:2},{...base,cv_profile:[]},{...base,application_id:'x'},
 {...base,cv_sha256:5},{...base,cv_text:'A'.repeat(32001)},{...base,extra:'字'.repeat(180000)}]
 .map(value=>()=>assert.throws(()=>validateEnvelope(value))),
];
const start=performance.now();
for(const test of cases)test();
const elapsed=performance.now()-start;
assert.ok(elapsed<1000);
console.log(JSON.stringify({tests:cases.length,pass:cases.length,milliseconds:elapsed}));

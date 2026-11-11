import fs from 'node:fs';
const compatibility=JSON.parse(fs.readFileSync(new URL('./native_expression_compat.json',import.meta.url),'utf8'));
function compatible(name,expression){
 const entry=compatibility[name];
 if(!entry || ![entry.source,entry.compiled].includes(expression))throw new Error('Regenerate trusted native expression: '+name);
 return entry.compiled;
}
/** Preserve trusted bounded transforms using native mapping and split nodes. */
export function nativeTransforms(workflow) {
 const w=structuredClone(workflow);
 const originals=w.nodes.filter(node=>node.type==="n8n-nodes-base.code");
 const redirects=new Map();
 for(const node of originals){
  const name=node.name;
  const build="Map "+name;
  redirects.set(name,build);
  let code=node.parameters.jsCode;
  code=code.replace(/return \$input\.all\(\);/g,"return [{json:$json}];")
           .replace(/\$input\.first\(\)\.json/g,"$json");
  const map={id:node.id+"-native-map",name:build,type:"n8n-nodes-base.set",typeVersion:3.4,
   position:[node.position[0]-100,node.position[1]],parameters:{mode:"raw",
    jsonOutput:"={{ (()=>{ const rows=(()=>{"+code+"})(); const list=Array.isArray(rows)?rows:[rows]; return JSON.stringify({__demo_rows:list.map(row=>row.json)}); })() }}"}};
  w.nodes.push(map);
  node.type="n8n-nodes-base.splitOut";node.typeVersion=1;
  node.parameters={fieldToSplitOut:"__demo_rows",include:"noOtherFields",options:{}};
 }
 for(const outputs of Object.values(w.connections)){
  for(const groups of Object.values(outputs))for(const group of groups)for(const edge of group||[]){
   if(redirects.has(edge.node))edge.node=redirects.get(edge.node);
  }
 }
 for(const [name,build] of redirects){
  w.connections[build]={main:[[{node:name,type:"main",index:0}]]};
 }
 for(const node of w.nodes){
  if(node.type==='n8n-nodes-base.set' && node.name.startsWith('Map ')){
   node.parameters.jsonOutput=['Map Security Pre-Check','Map Validate Classification'].includes(node.name)
    ? compatibility[node.name].compiled : compatible(node.name,node.parameters.jsonOutput);
  }
 }
 const map=w.nodes.find(n=>n.name==='Map Validate Classification');
 const classify=w.nodes.find(n=>n.name==='Classify CV');
 const guidance='Return only 1 to 3 of the strongest source evidence IDs. Do not enumerate the CV lines.';
 if(!classify.parameters.options.systemMessage.includes(guidance)) classify.parameters.options.systemMessage+='\n'+guidance;
 const gateName='Classification Valid';
 const failureName='Record Classification Failure';
 if(!w.nodes.some(n=>n.name===gateName)){
  const edge=node=>[{node,type:'main',index:0}];
  const gate=structuredClone(w.nodes.find(n=>n.name==='Needs Ollama Classification'));
  gate.id='tf-demo-classification-valid';
  gate.name=gateName;
  gate.position=[map.position[0]+300,map.position[1]];
  gate.parameters.conditions.conditions[0].leftValue="={{ typeof $json.classification === 'string' && !$json.failure_code }}";
  const report=structuredClone(w.nodes.find(n=>n.name==='Record Envelope Failure'));
  report.id='tf-demo-classification-failure';
  report.name=failureName;
  report.position=[map.position[0]+500,map.position[1]+250];
  report.parameters.jsonBody=report.parameters.jsonBody.replace('workflow_envelope_failed','workflow_classification_failed');
  w.nodes.push(gate,report);
  w.connections[gateName]={main:[w.connections['Validate Classification'].main[0],edge(failureName)]};
  w.connections['Validate Classification']={main:[edge(gateName)]};
  map.onError='continueErrorOutput';
  w.connections[map.name].main[1]=edge(failureName);
  classify.onError='continueErrorOutput';
  w.connections[classify.name].main[1]=edge(failureName);
 }
 return w;
}

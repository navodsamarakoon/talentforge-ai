export function validateEnvelope(b) {
  const plain = x => x !== null && typeof x === "object" && !Array.isArray(x);
  if (!plain(b)) throw new Error("Invalid CV envelope");
  const encoded = JSON.stringify(b);
  if (encoded.length > 524288) throw new Error("CV envelope exceeds size limit");
  let bytes = 0;
  for (const ch of encoded) {
    const c = ch.codePointAt(0);
    bytes += c < 128 ? 1 : c < 2048 ? 2 : c < 65536 ? 3 : 4;
    if (bytes > 524288) throw new Error("CV envelope exceeds size limit");
  }
  const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
  if (b.schema_version !== 1 ||
      !["application_id","dispatch_id","job_id","organization_id"].every(k=>typeof b[k]==="string"&&uuid.test(b[k])) ||
      typeof b.cv_text !== "string" || b.cv_text.length > 32000 ||
      typeof b.cv_sha256 !== "string" || !/^[a-f0-9]{64}$/i.test(b.cv_sha256) ||
      !plain(b.cv_profile)) throw new Error("Invalid CV envelope");
  return b;
}
export function correctEnvelope(workflow) {
 const w=structuredClone(workflow);
 const node=w.nodes.find(n=>n.name==="Validate CV Envelope");
 node.type="n8n-nodes-base.set";
 node.typeVersion=3.4;
 node.parameters={mode:"raw",jsonOutput:"={{ (() => { "+validateEnvelope.toString()+"; return JSON.stringify(validateEnvelope($json.body)); })() }}"};
 node.onError="continueErrorOutput";
 const name="Record Envelope Failure";
 if(!w.nodes.some(n=>n.name===name)){
  const report=structuredClone(w.nodes.find(n=>n.name==="Claim Screening"));
  report.id="tf-demo-envelope-failure";
  report.name=name; report.position=[500,500];
  report.parameters.url="={{ 'http://runner:8000/api/integrations/n8n/applications/' + encodeURIComponent($('Webhook').first().json.body.application_id) + '/screening/failure' }}";
  report.parameters.jsonBody="={{ JSON.stringify({dispatch_id:$('Webhook').first().json.body.dispatch_id,failure_code:'workflow_envelope_failed'}) }}";
  w.nodes.push(report);
 }
 w.connections["Validate CV Envelope"].main[1]=[{node:name,type:"main",index:0}];
 return w;
}

import assert from "node:assert/strict";

export function oneShotWorkflow(saved, id, approval, expected) {
  const original = name => {
    const node = saved.nodes.find(item => item.name === name);
    assert.ok(node, `Missing source node: ${name}`);
    return structuredClone(node);
  };
  const claim = original("Claim Pending Notification");
  const smtp = original("Gmail SMTP");
  const success = original("Record SMTP Outcome");
  const failure = original("Record SMTP Failure");
  assert.ok(claim.credentials?.httpHeaderAuth?.id && smtp.credentials?.smtp?.id);
  assert.equal(smtp.parameters.fromEmail, expected.sender);
  const base = claim.parameters.url;
  assert.match(base, /^http:\/\/(?:runner|127\.0\.0\.1):8000\/api\/integrations\/n8n\/vacancy-notifications\/claim$/);
  const receiptUrl = base.replace(/claim$/, `${approval.delivery_id}/receipt`);
  const trigger = { id: "manual", name: "Manual Trigger", type: "n8n-nodes-base.manualTrigger",
    typeVersion: 1, position: [0, 0], parameters: {} };
  claim.parameters.url = base.replace(/claim$/, "claim-one");
  claim.parameters.sendBody = true;
  claim.parameters.specifyBody = "json";
  claim.parameters.jsonBody = JSON.stringify(approval);
  claim.retryOnFail = false;
  smtp.executeOnce = true;
  smtp.retryOnFail = false;
  smtp.parameters = {
    fromEmail: expected.sender,
    toEmail: `={{ (() => {
      if ($input.all().length !== 1 || $json.id !== ${JSON.stringify(approval.delivery_id)}
          || $json.recipient !== ${JSON.stringify(approval.recipient)}
          || $json.event_id !== ${JSON.stringify(approval.event_id)}
          || $json.vacancy_id !== ${JSON.stringify(approval.vacancy_id)}
          || $json.subject !== ${JSON.stringify(expected.subject)}
          || $json.text !== ${JSON.stringify(expected.text)}
          || typeof $json.claim_token !== 'string' || !$json.claim_token) {
        throw new Error('One-shot SMTP payload does not match approval');
      }
      return $json.recipient;
    })() }}`,
    subject: "={{ $json.subject }}", emailFormat: "text", text: "={{ $json.text }}",
    options: { appendAttribution: false },
  };
  for (const node of [success, failure]) {
    node.parameters.url = receiptUrl;
    node.parameters.jsonBody = node.parameters.jsonBody
      .replace(/Prepare Personalized Emails|Authorize SMTP Submission/, claim.name)
      .replace("'transient'", "'failed'");
    // Only the idempotent HTTP receipt can retry.
    node.credentials = claim.credentials;
  }
  const edge = name => [{ node: name, type: "main", index: 0 }];
  return {
    id, name: "TalentForge AI — Authorized one-shot vacancy delivery", active: false,
    nodes: [trigger, claim, smtp, success, failure],
    connections: {
      [trigger.name]: { main: [edge(claim.name)] },
      [claim.name]: { main: [edge(smtp.name)] },
      [smtp.name]: { main: [edge(success.name), edge(failure.name)] },
    },
    settings: { ...saved.settings, saveDataErrorExecution: "none", saveDataSuccessExecution: "none",
      saveManualExecutions: false, executionTimeout: 90 },
  };
}

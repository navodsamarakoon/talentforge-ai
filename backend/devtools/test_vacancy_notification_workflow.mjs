import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const workflow = JSON.parse(fs.readFileSync(new URL("./vacancy-notifications.workflow.json", import.meta.url)));
const node = name => workflow.nodes.find(item => item.name === name);
const email = node("Gmail SMTP");
assert.equal(workflow.active, false);
assert.equal(workflow.nodes.some(item => item.credentials), false);
assert.deepEqual(node("Poll Vacancy Outbox").parameters.rule.interval, [{field: "minutes", minutesInterval: 5}]);
assert.equal(email.parameters.emailFormat, "text");
assert.equal(email.parameters.toEmail, "={{ $json.recipient }}");
assert.equal(email.retryOnFail, false);
assert.equal(email.onError, "continueErrorOutput");
assert.equal(node("Authorize SMTP Submission").retryOnFail, false);
assert.equal(workflow.connections["Prepare Personalized Emails"].main[0][0].node, "Authorize SMTP Submission");
assert.equal(workflow.connections["Authorize SMTP Submission"].main[0][0].node, email.name);
assert.deepEqual(workflow.connections[email.name].main.map(([edge]) => edge.node),
                 ["Record SMTP Outcome", "Record SMTP Failure"]);
for (const item of workflow.nodes.filter(item => item.type === "n8n-nodes-base.httpRequest")) {
  assert.equal(item.parameters.genericAuthType, "httpHeaderAuth");
}

const message = {id: "fixture", claim_token: "fixture-token", recipient: "candidate@example.com"};
function outcome(name, output) {
  const expression = node(name).parameters.jsonBody.slice(3, -2);
  return JSON.parse(vm.runInNewContext(expression, {
    $json: output,
    $: () => ({first: () => ({json: message})}),
  })).outcome;
}
assert.equal(outcome("Record SMTP Outcome", {accepted: [message.recipient], rejected: []}), "sent");
assert.equal(outcome("Record SMTP Outcome", {accepted: [], rejected: [message.recipient]}), "unknown");
assert.equal(outcome("Record SMTP Outcome", {}), "unknown");
assert.equal(outcome("Record SMTP Failure", {error: {command: "RCPT TO", responseCode: 450}}), "transient");
assert.equal(outcome("Record SMTP Failure", {error: {command: "RCPT TO", responseCode: 550}}), "failed");
assert.equal(outcome("Record SMTP Failure", {error: {command: "DATA", code: "ETIMEDOUT"}}), "unknown");
assert.equal(outcome("Record SMTP Failure", {error: "Unstructured SMTP 450 error"}), "unknown");
assert.equal(outcome("Record SMTP Failure", {error: "Can't send mail - all recipients were rejected: 450 fixture"}), "transient");
assert.equal(outcome("Record SMTP Failure", {error: "Can't send mail - all recipients were rejected: 550 fixture"}), "failed");
assert.equal(outcome("Record SMTP Failure", {error: "Connection closed after DATA: 450 fixture"}), "unknown");
assert.equal(outcome("Record SMTP Failure", {error: {command: "AUTH PLAIN", responseCode: 535}}), "auth_failed");
assert.equal(outcome("Record SMTP Failure", {error: "Invalid login: 535 5.7.8 fixture"}), "auth_failed");
assert.equal(outcome("Record SMTP Failure", {error: "Transport closed after DATA: 535 fixture"}), "unknown");
console.log("Vacancy workflow wiring and thirteen SMTP outcome cases passed.");

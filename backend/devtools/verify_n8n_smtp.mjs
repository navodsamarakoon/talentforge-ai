// Run only in a disposable n8n container with synthetic inputs and no default route.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { DatabaseSync } from "node:sqlite";

assert.equal(process.env.TALENTFORGE_SMTP_FIXTURE, "1");
const joined = process.env.TALENTFORGE_HTTP_FIXTURE === "1";
const live = process.env.TALENTFORGE_LIVE_JOINED === "1";
const routes = readFileSync("/proc/net/route", "utf8").trim().split("\n").slice(1);
assert.ok(routes.every(row => row.trim().split(/\s+/)[1] !== "00000000"));
if (!joined && !live) assert.equal(routes.length, 0);
const definition = JSON.parse(readFileSync("/fixture/workflow.json", "utf8"));
const messages = [];
const refused = [];
const server = createServer(socket => {
  socket.setEncoding("utf8");
  socket.write("220 fixture SMTP\r\n");
  let buffer = "", body = null, recipients = [];
  socket.on("error", () => {});
  socket.on("data", chunk => {
    buffer += chunk;
    while (buffer.includes("\n")) {
      const index = buffer.indexOf("\n");
      const line = buffer.slice(0, index).replace(/\r$/, "");
      buffer = buffer.slice(index + 1);
      if (body !== null) {
        if (line !== ".") {
          body.push(line);
          continue;
        }
        messages.push({ recipients, body: body.join("\n") });
        body = null;
        if (recipients.includes("uncertain@example.com")) {
          socket.destroy();
          return;
        }
        socket.write("250 fixture accepted\r\n");
      } else if (/^(EHLO|HELO) /i.test(line)) {
        socket.write("250 fixture\r\n");
      } else if (/^MAIL FROM:/i.test(line)) {
        recipients = [];
        socket.write("250 sender accepted\r\n");
      } else if (/^RCPT TO:/i.test(line)) {
        const recipient = /<([^>]+)>/.exec(line)?.[1];
        if (!recipient?.endsWith("@example.com") || recipient === "failed@example.com") {
          refused.push(recipient);
          socket.write("550 fixture rejected\r\n");
        } else {
          recipients.push(recipient);
          socket.write("250 recipient accepted\r\n");
        }
      } else if (line === "DATA") {
        body = [];
        socket.write("354 end with dot\r\n");
      } else if (line === "QUIT") {
        socket.end("221 fixture closed\r\n");
      } else {
        socket.write("250 ok\r\n");
      }
    }
  });
});

function cli(...args) {
  return new Promise((resolve, reject) => {
    const proc = spawn("n8n", args, { stdio: ["ignore", "pipe", "pipe"] });
    let output = "";
    proc.stdout.on("data", data => { output += data; });
    proc.stderr.on("data", data => { output += data; });
    const timer = setTimeout(() => proc.kill("SIGKILL"), 180_000);
    proc.once("error", error => { clearTimeout(timer); reject(error); });
    proc.once("close", status => {
      clearTimeout(timer);
      if (status === 0) resolve(output);
      else reject(new Error(`n8n CLI exited ${status}: ${output.slice(-2400)}`));
    });
  });
}

const credential = { id: "FixtureSMTPOnly1", name: "Loopback fixture SMTP", type: "smtp" };
const callbackCredential = { id: "FixtureCallback1", name: "Fixture callback auth", type: "httpHeaderAuth" };
const file = "/tmp/smtp-fixture-credentials.json";
const credentials = [{ ...credential, data: {
  host: "127.0.0.1", port: 2525, user: "", password: "", secure: false, disableStartTls: true,
} }];
if (joined || live) credentials.push({ ...callbackCredential, data: {
  name: "X-TalentForge-Callback-Secret", value: "synthetic-callback",
} });
const webhookCredential = { id: "FixtureWebhookAuth1", name: "Fixture webhook auth", type: "httpHeaderAuth" };
const ollamaCredential = { id: "FixtureOllama123", name: "Fixture local Ollama", type: "ollamaApi" };
if (live) credentials.push(
  { ...webhookCredential, data: { name: "X-TalentForge-Webhook-Secret", value: "synthetic-webhook" } },
  { ...ollamaCredential, data: { baseUrl: "http://host.docker.internal:11434" } },
);
writeFileSync(file, JSON.stringify(credentials));

async function verifyLive() {
  assert.equal(definition.active, false);
  assert.equal(definition.activeVersionId, null);
  const backend = "http://runner:8000";
  const id = "FixtureLiveJoined1";
  const refusalMode = process.env.TALENTFORGE_LIVE_FAILURES === "summary-failure";
  const summaryMode = refusalMode || process.env.TALENTFORGE_LIVE_FAILURES === "summary";
  const nodes = definition.nodes.map(node => {
    const n = structuredClone(node);
    n.disabled = n.name === "Daily 06:00 Colombo";
    if (summaryMode && n.disabled) {
      assert.equal(definition.settings.timezone, "Asia/Colombo");
      assert.deepEqual(n.parameters.rule.interval, [{field:"days",daysInterval:1,triggerAtHour:6,triggerAtMinute:0}]);
      return {...n, disabled:false, type:"n8n-nodes-base.webhook", typeVersion:2,
        webhookId:"12c7990e-cb3a-4059-9d18-efdbdc191e7b",
        parameters:{httpMethod:"POST",path:"fixture-summary",authentication:"headerAuth",responseMode:"onReceived"},
        credentials:{httpHeaderAuth:webhookCredentialRef(webhookCredential)}};
    }
    if (n.type === "n8n-nodes-base.httpRequest") {
      n.parameters.url = n.parameters.url.replace("http://backend:8000", backend);
      assert.ok(n.parameters.url.includes(backend + "/api/integrations/n8n/"));
      n.credentials = { httpHeaderAuth: webhookCredentialRef(callbackCredential) };
    } else if (n.type === "n8n-nodes-base.emailSend") {
      n.parameters.fromEmail = "fixture@example.com";
      n.credentials = { smtp: webhookCredentialRef(credential) };
    } else if (n.name === "Webhook") {
      n.credentials = { httpHeaderAuth: webhookCredentialRef(webhookCredential) };
    } else if (n.name === "Ollama Chat Model") {
      n.credentials = { ollamaApi: webhookCredentialRef(ollamaCredential) };
    }
    return n;
  });
  const connections = structuredClone(definition.connections);
  if (process.env.TALENTFORGE_LIVE_FAILURES === "validator") {
    nodes.push({
      id: "fixture-model-corruption", name: "Fixture Model Corruption", type: "n8n-nodes-base.code",
      typeVersion: 2, position: [0, 0],
      parameters: { jsCode: `const lines = $('Security Pre-Check').first().json.evidence_lines;
const malformed = lines.some(line => line.text.includes('TF_FIXTURE_MALFORMED'));
return [{json:{output:malformed ? '{broken' : JSON.stringify({category:'clean',spam_suspected:false,reason:'Fixture invalid citation',evidence:[99999]})}}];` },
    });
    connections["Classify CV"] = { main: [[{ node: "Fixture Model Corruption", type: "main", index: 0 }]] };
    connections["Fixture Model Corruption"] = { main: [[{ node: "Validate Classification", type: "main", index: 0 }]] };
  }
  const path = "/tmp/live-joined-workflow.json";
  writeFileSync(path, JSON.stringify([{ id, name: "Disposable live joined CV", active: false,
    nodes, connections, settings: { timezone: "Asia/Colombo", saveDataErrorExecution: "all" } }]));
  await cli("import:workflow", "--input", path);
  await cli("publish:workflow", "--id", id);
  const service = spawn("n8n", ["start"], { stdio: "inherit" });
  const get = (url, init) => fetch(url, { signal: AbortSignal.timeout(10000), ...init });
  try {
    for (const url of ["http://127.0.0.1:5678/healthz/readiness", backend + "/__fixture/job"]) {
      let ready = false;
      for (let i = 0; i < 90 && !ready; i++) {
        try { ready = (await get(url, { signal: AbortSignal.timeout(1000) })).ok; } catch {}
        if (!ready) await new Promise(resolve => setTimeout(resolve, 1000));
      }
      assert.ok(ready, "Fixture service did not become ready: " + url);
    }
    const { job_id: job, mismatch_job_id: mismatchJob } = await (await get(backend + "/__fixture/job")).json();
    {
      const route = summaryMode ? "fixture-summary" : nodes.find(node => node.name === "Webhook").parameters.path;
      let registered = false;
      for (let i=0; i<60 && !registered; i++) {
        const db=new DatabaseSync("/home/node/.n8n/database.sqlite",{readOnly:true});
        try {
          registered = Boolean(db.prepare("SELECT 1 FROM webhook_entity WHERE webhookPath = ? AND method = ?")
            .get(route, "POST"));
        } finally { db.close(); }
        if (!registered) await new Promise(resolve=>setTimeout(resolve,500));
      }
      assert.ok(registered, "Disposable webhook was not registered: " + route);
    }
    if (summaryMode) {
      const trigger = async () => assert.equal((await get("http://127.0.0.1:5678/webhook/fixture-summary", {
        method:"POST",headers:{"X-TalentForge-Webhook-Secret":"synthetic-webhook"},
      })).status, 200);
      const read = async () => (await get(backend + "/__fixture/summary-state")).json();
      async function waitExecutions(count) {
        for (let i=0; i<60; i++) {
          const db=new DatabaseSync("/home/node/.n8n/database.sqlite",{readOnly:true});
          const rows=db.prepare('SELECT id,status FROM execution_entity WHERE workflowId = ? ORDER BY id').all(id);
          db.close();
          if(rows.length===count && rows.every(row=>row.status==="success")) return rows;
          await new Promise(resolve=>setTimeout(resolve,500));
        }
        assert.fail("Summary executions did not finish successfully");
      }
      await trigger();
      await waitExecutions(1);
      const crash = {state:"unknown",recipients:["crash@example.com"],run_date:"2026-11-03",candidates:[]};
      assert.deepEqual(await read(),refusalMode ? [crash] : []);
      assert.equal((await get(backend+"/__fixture/summary-cutoff",{method:"POST"})).status,200);
      await Promise.all([trigger(),trigger()]);
      await waitExecutions(3);
      await trigger();
      const executions=await waitExecutions(4);
      const batches=(await read()).sort((a,b)=>a.state.localeCompare(b.state));
      console.log(JSON.stringify({summary:{executions,batches,messages}}));
      if (refusalMode) {
        assert.deepEqual(batches.filter(batch=>batch.run_date==="2026-11-03"),[crash]);
        assert.deepEqual(batches.filter(batch=>batch.run_date==="2026-11-04"),[
          {state:"sent",recipients:["recruiter-0@example.com","recruiter-2@example.com"],run_date:"2026-11-04",candidates:["synthetic-0@example.com"]},
          {state:"unknown",recipients:["failed@example.com"],run_date:"2026-11-04",candidates:["synthetic-1@example.com"]},
        ]);
        assert.deepEqual(refused,["failed@example.com"]);
        assert.equal(messages.length,1);
        assert.deepEqual(messages[0].recipients,["recruiter-0@example.com","recruiter-2@example.com"]);
        return;
      }
      assert.deepEqual(batches,[
        {state:"sent",recipients:["recruiter-0@example.com","recruiter-2@example.com"],run_date:"2026-11-04",candidates:["synthetic-0@example.com"]},
        {state:"unknown",recipients:["uncertain@example.com"],run_date:"2026-11-04",candidates:["synthetic-1@example.com"]},
      ]);
      assert.equal(messages.length,2);
      for(const [recipient,candidate,other] of [["recruiter-0@example.com","synthetic-0@example.com","synthetic-1@example.com"],["uncertain@example.com","synthetic-1@example.com","synthetic-0@example.com"]]){
        const message=messages.find(item=>item.recipients.includes(recipient));
        assert.ok(message?.body.includes(candidate) && !message.body.includes(other) && !message.body.includes("synthetic-2@example.com"));
      }
      return;
    }
    async function runUpload({ account, vacancy, extension, fixture = extension, decision, reason,
      count, outcome = "sent", preDispatchError, validatorError, expectedRefusal = false }) {
    const before = messages.length;
    const previousRefusals = refused.length;
    const dbPath = "/home/node/.n8n/database.sqlite";
    const latestExecution = () => {
      const db = new DatabaseSync(dbPath, { readOnly: true });
      try { return db.prepare('SELECT id, status FROM execution_entity WHERE workflowId = ? ORDER BY id DESC LIMIT 1').get(id); }
      finally { db.close(); }
    };
    const previousExecution = latestExecution()?.id;
    const login = await get(backend + "/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: account, password: "Synthetic-joined-password-2026!" }),
    });
    assert.equal(login.status, 200);
    const { access_token: token } = await login.json();
    const form = new FormData();
    const document = await get(backend + "/__fixture/" + fixture);
    assert.equal(document.status, 200);
    form.append("cv", await document.blob(), "fixture." + extension);
    const upload = await get(backend + "/api/candidate/jobs/" + vacancy + "/applications", {
      method: "POST", headers: { Authorization: "Bearer " + token }, body: form,
      signal: AbortSignal.timeout(30000),
    });
    assert.equal(upload.status, 201, await upload.clone().text());
    const { id: application } = await upload.json();
    let state;
    for (let i = 0; i < 240; i++) {
      state = await (await get(backend + "/__fixture/state/" + application)).json();
      const active = latestExecution();
      if (validatorError && active?.id !== previousExecution && active?.status === "error") break;
      if (state.state === "failed" || ["sent", "failed", "unknown"].includes(state.notification)) break;
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    const latest = latestExecution();
    const execution = latest?.id === previousExecution ? null : latest;
    const captured = messages.length - before;
    console.log(JSON.stringify({ fixture, account, application, execution, state, captured,
      message: captured ? messages.at(-1) : null, refused: refused.slice(previousRefusals) }));
    if (validatorError) {
      assert.equal(execution?.status, "error");
      const db = new DatabaseSync(dbPath, { readOnly: true });
      try {
        const { data } = db.prepare('SELECT data FROM execution_data WHERE executionId = ?').get(execution.id);
        assert.ok(data.includes("Validate Classification"));
        assert.match(data, validatorError);
      } finally { db.close(); }
      assert.equal(state.decision, "screening");
      assert.equal(state.reason_code, null);
      assert.equal(state.notification, null);
      assert.equal(captured, 0);
      return application;
    }
    if (preDispatchError) {
      assert.equal(state.state, "failed");
      assert.match(state.error_code, preDispatchError);
      assert.equal(state.reason_code, null);
      assert.equal(state.decision, "submitted");
      assert.equal(state.dispatch_started, false);
      assert.equal(state.notification, null);
      assert.ok(!execution && captured === 0);
      return application;
    }
    assert.ok(execution?.id);
    assert.equal(state.decision, decision);
    assert.equal(state.reason_code, reason);
    assert.equal(state.notification, outcome);
    assert.ok(state.dispatch_id);
    if (decision === "selected" || reason === "job_mismatch") assert.equal(state.match_result.application_id, application);
    if (count !== undefined) assert.equal(messages.length, count);
    assert.equal(captured, expectedRefusal ? 0 : 1);
    if (expectedRefusal) assert.deepEqual(refused.slice(previousRefusals), [account]);
    else {
      assert.deepEqual(messages.at(-1).recipients, [account]);
      assert.ok(messages.at(-1).body.includes("Result: " + decision));
    }
    return application;
    }
    const failureMode = process.env.TALENTFORGE_LIVE_FAILURES;
    if (["replay","race"].includes(failureMode)) {
      const initial = runUpload({account:"synthetic-4@example.com",vacancy:job,extension:"pdf",
        fixture:"pdf/suspicious",decision:"rejected",reason:"suspicious",count:1});
      initial.catch(()=>{});
      let application;
      if (failureMode === "race") {
        const readyUrl = backend + "/__fixture/race-ready";
        for(let i=0;i<180;i++){
          const ready=await (await get(readyUrl)).json();
          if(ready.entered && ready.application_id){application=ready.application_id;break;}
          await new Promise(resolve=>setTimeout(resolve,500));
        }
        assert.ok(application,"Initial decision did not reach the race gate");
        const raceUrl=backend+"/__fixture/replay/"+application;
        try {
          const before=await (await get(backend+"/__fixture/state/"+application)).json();
          assert.equal(before.decision,"screening");
          for(const response of await Promise.all([get(raceUrl,{method:"POST"}),get(raceUrl,{method:"POST"}),get(raceUrl+"?mismatch=true",{method:"POST"})])){
            assert.equal((await response.json()).status,200);
          }
          const db=new DatabaseSync("/home/node/.n8n/database.sqlite",{readOnly:true});
          try {
            let rows;
            for(let i=0;i<50;i++){
              rows=db.prepare('SELECT id,status FROM execution_entity WHERE workflowId = ? ORDER BY id').all(id);
              if(rows.length===4 && rows.slice(1).every(row=>["success","error"].includes(row.status)))break;
              await new Promise(resolve=>setTimeout(resolve,400));
            }
            assert.equal(rows.length,4);
            assert.deepEqual(rows.slice(1).map(row=>row.status).sort(),["error","success","success"]);
            const denied=rows.slice(1).find(row=>row.status==="error");
            assert.match(db.prepare("SELECT data FROM execution_data WHERE executionId = ?").get(denied.id).data,/Screening handoff does not match/);
            assert.deepEqual(await (await get(backend+"/__fixture/state/"+application)).json(),before);
            assert.equal(messages.length,0);
            assert.equal((await (await get(readyUrl)).json()).foreign_unchanged,true);
            console.log(JSON.stringify({raceBeforeRelease:{application,rows,before,messages:messages.length,foreignUnchanged:true}}));
          } finally {db.close();}
        } finally {
          assert.equal((await get(backend+"/__fixture/race-release",{method:"POST"})).status,200);
        }
        assert.equal(await initial,application);
        assert.equal(messages.length,1);
        return;
      }
      application = await initial;
      const stateUrl = backend + "/__fixture/state/" + application;
      const before = await (await get(stateUrl)).json();
      const replayUrl = backend + "/__fixture/replay/" + application;
      const replay = async (suffix = "") => assert.equal(
        (await (await get(replayUrl + suffix, { method:"POST" })).json()).status, 200);
      async function executionRows(count) {
        for (let i=0; i<60; i++) {
          const db=new DatabaseSync("/home/node/.n8n/database.sqlite",{readOnly:true});
          try {
            const rows=db.prepare('SELECT id,status FROM execution_entity WHERE workflowId = ? ORDER BY id').all(id);
            if(rows.length===count && rows.every(row=>["success","error"].includes(row.status))) return rows;
          } finally { db.close(); }
          await new Promise(resolve=>setTimeout(resolve,500));
        }
        assert.fail("Replay executions did not finish");
      }
      await Promise.all([replay(), replay()]);
      const replays=await executionRows(3);
      assert.deepEqual(replays.map(row=>row.status),["success","success","success"]);
      await replay("?mismatch=true");
      const executions=await executionRows(4);
      assert.equal(executions[3].status,"error");
      const db=new DatabaseSync("/home/node/.n8n/database.sqlite",{readOnly:true});
      try {
        const {data}=db.prepare('SELECT data FROM execution_data WHERE executionId = ?').get(executions[3].id);
        assert.match(data,/Screening handoff does not match/);
      } finally {db.close();}
      assert.deepEqual(await (await get(stateUrl)).json(),before);
      assert.equal(messages.length,1);
      console.log(JSON.stringify({replay:{application,executions,state:before,captured:messages.length}}));
      return;
    }
    if (["1", "model", "empty", "validator"].includes(failureMode)) {
      const cases = failureMode === "validator" ? [
        {fixture:"pdf/malformed",account:"synthetic-7@example.com",validatorError:/Expected property name/},
        {fixture:"pdf/invalid-evidence",account:"synthetic-8@example.com",validatorError:/Invalid or ungrounded classification/},
      ] : failureMode === "model" ? [
        {fixture:"pdf/unavailable",account:"synthetic-7@example.com",preDispatchError:/ollama_unavailable/},
        {fixture:"pdf/timeout",account:"synthetic-8@example.com",preDispatchError:/ollama_timeout/},
      ] : [
        {fixture:"pdf/spam",account:"synthetic-3@example.com",reason:"spam"},
        {fixture:"pdf/suspicious",account:"synthetic-4@example.com",reason:"suspicious"},
        {fixture:"pdf/meaningless",account:"synthetic-5@example.com",reason:"meaningless"},
        {fixture:"pdf/empty",account:"synthetic-6@example.com",preDispatchError:/empty|extract|text/},
        {fixture:"pdf/suspicious",account:"failed@example.com",reason:"suspicious",outcome:"unknown",expectedRefusal:true},
        {fixture:"pdf/suspicious",account:"uncertain@example.com",reason:"suspicious",outcome:"unknown"},
      ];
      let failures = 0;
      for (const item of cases) {
        if (failureMode === "empty" && item.fixture !== "pdf/empty") continue;
        try { await runUpload({vacancy:job,extension:"pdf",decision:"rejected",...item}); }
        catch (error) { failures++; console.error(JSON.stringify({fixture:item.fixture,account:item.account,error:error.message})); }
      }
      assert.equal(failures, 0, "Joined failure scenarios failed");
      return;
    }
    const selected = await runUpload({account:"synthetic-0@example.com",vacancy:job,extension:"pdf",decision:"selected",reason:"selected",count:1});
    await runUpload({account:"synthetic-1@example.com",vacancy:job,extension:"docx",decision:"rejected",reason:"duplicate",count:2});
    await runUpload({account:"synthetic-2@example.com",vacancy:mismatchJob,extension:"pdf",decision:"rejected",reason:"job_mismatch",count:3});
    const replay = await get(backend + "/__fixture/replay/" + selected, { method: "POST" });
    assert.equal((await replay.json()).status, 200);
    await new Promise(resolve => setTimeout(resolve, 4000));
    assert.equal(messages.length, 3);
  } finally { service.kill(); }
}

function webhookCredentialRef({ id, name }) { return { id, name }; }

async function verifyJoined() {
  const backend = "http://runner:8000";
  const fixture = await fetch(backend + "/__fixture/envelope", { signal: AbortSignal.timeout(5000) });
  assert.equal(fixture.status, 200);
  const envelope = await fixture.json();
  assert.equal(envelope.body.candidate_email, "synthetic-0@example.com");
  const excluded = new Set(["Webhook", "Daily 06:00 Colombo", "Ollama Chat Model"]);
  const nodes = definition.nodes.filter(n => !excluded.has(n.name)).map(node => {
    const n = structuredClone(node);
    n.disabled = false;
    if (n.type === "n8n-nodes-base.httpRequest") {
      n.parameters.url = n.parameters.url.replace("http://backend:8000", backend);
      assert.ok(n.parameters.url.includes(backend + "/api/integrations/n8n/"));
      n.credentials = { httpHeaderAuth: { id: callbackCredential.id, name: callbackCredential.name } };
    } else if (n.type === "n8n-nodes-base.emailSend") {
      n.parameters.fromEmail = "fixture@example.com";
      n.credentials = { smtp: { id: credential.id, name: credential.name } };
    } else if (n.name === "Classify CV") {
      n.type = "n8n-nodes-base.code";
      n.typeVersion = 2;
      n.parameters = { jsCode: `return [{json:{output:'{"category":"clean","spam_suspected":false,"reason":"Fixture classification","evidence":[2]}'}}];` };
    }
    return n;
  });
  nodes.push(
    { id: "start", name: "Start", type: "n8n-nodes-base.manualTrigger", typeVersion: 1, position: [0, -200], parameters: {} },
    { id: "envelope", name: "Load fictional webhook envelope", type: "n8n-nodes-base.httpRequest", typeVersion: 4.2,
      position: [200, -200], parameters: { method: "GET", url: backend + "/__fixture/envelope" } },
    { id: "clock", name: "Simulate next Colombo cutoff", type: "n8n-nodes-base.httpRequest", typeVersion: 4.2,
      position: [400, -200], parameters: { method: "POST", url: backend + "/__fixture/advance" } },
  );
  const connections = Object.fromEntries(Object.entries(definition.connections).filter(([name]) => !excluded.has(name)));
  const connect = (from, to) => { connections[from] = { main: [[{ node: to, type: "main", index: 0 }]] }; };
  connect("Start", "Load fictional webhook envelope");
  connect("Load fictional webhook envelope", "Validate CV Envelope");
  connect("Record Notification Receipt", "Simulate next Colombo cutoff");
  connect("Simulate next Colombo cutoff", "Claim Recruiter Summaries");
  const id = "FixtureWorkflow1";
  const path = "/tmp/joined-fixture-workflow.json";
  writeFileSync(path, JSON.stringify({ id, name: "Disposable recruitment integration", active: false,
                                      nodes, connections, settings: { timezone: "Asia/Colombo" } }));
  await cli("import:workflow", "--input", path);
  const verify = async () => {
    const output = await cli("execute", "--id", id, "--rawOutput");
    const response = await fetch(backend + "/__fixture/results", { signal: AbortSignal.timeout(5000) });
    const actual = await response.json();
    const expected = { decision: "selected", notification: "sent", summary: "sent", match_score: 90 };
    assert.deepEqual(actual, expected, output.slice(-2400));
    assert.equal(messages.length, 2);
  };
  await verify();
  await verify();
  assert.ok(messages.some(message => message.recipients.length === 1 &&
    message.recipients[0] === "synthetic-0@example.com" && message.body.includes("90/100")));
  assert.ok(messages.some(message => message.recipients.sort().join(",") ===
    "recruiter-0@example.com,recruiter-2@example.com" && message.body.includes("Score: 90")));
  console.log("PASS: real n8n callbacks, disposable PostgreSQL, candidate and summary SMTP receipts, and replay. Model outputs were fixtures.");
}

await new Promise(resolve => server.listen(2525, "127.0.0.1", resolve));
try {
  await cli("import:credentials", "--input", file);
  if (live) {
    await verifyLive();
  } else if (joined) {
    await verifyJoined();
  } else {
  const cases = [
    { email: "selected@example.com", status: "selected", reason: "Met fictional job requirements.", outcome: "sent" },
    { email: "rejected@example.com", status: "rejected", reason: "Missing fictional mandatory skill.", outcome: "sent" },
    { email: "failed@example.com", status: "rejected", reason: "Fictional duplicate.", outcome: "unknown" },
    { email: "uncertain@example.com", status: "selected", reason: "Met fictional job requirements.", outcome: "unknown" },
  ];
  const nodes = [{ id: "start", name: "Start", type: "n8n-nodes-base.manualTrigger", typeVersion: 1, position: [0,0], parameters: {} }];
  const connections = { Start: { main: [[]] } };
  for (const [index, item] of cases.entries()) {
    const suffix = ` ${index}`;
    const claim = { should_send: true, candidate_name: "Fictional Candidate", candidate_email: item.email,
                    job_title: "Fictional Engineer", status: item.status, reason: item.reason };
    const codeNode = (name, jsCode) => ({ name, id: name, type: "n8n-nodes-base.code", typeVersion: 2,
                                        position: [0,index * 250], parameters: { jsCode } });
    const prepare = structuredClone(definition.nodes.find(n => n.name === "Prepare Candidate Email"));
    const smtp = structuredClone(definition.nodes.find(n => n.name === "Candidate SMTP"));
    const guard = structuredClone(definition.nodes.find(n => n.name === "Validate SMTP Outcome"));
    const chain = [codeNode("Fixture claim" + suffix, `return [{json:${JSON.stringify(claim)}}];`),
                   prepare, smtp, guard, codeNode("Check outcome" + suffix,
                     `if ($input.first().json.outcome !== ${JSON.stringify(item.outcome)}) throw new Error("Unexpected SMTP outcome"); return $input.all();`)];
    for (const n of [prepare, smtp, guard]) {
      n.name += suffix;
      n.id = n.name;
    }
    smtp.disabled = false;
    smtp.credentials = { smtp: { id: credential.id, name: credential.name } };
    smtp.parameters.fromEmail = "fixture@example.com";
    guard.parameters.jsCode = guard.parameters.jsCode.replace("Prepare Candidate Email", prepare.name);
    const edge = name => ({ node: name, type: "main", index: 0 });
    connections.Start.main[0].push(edge(chain[0].name));
    chain.slice(0, -1).forEach((n, i) => { connections[n.name] = { main: [[edge(chain[i+1].name)]] }; });
    nodes.push(...chain);
  }
  const summaryCases = [
    { summary_id: "org-a", organization_name: "Fictional Org A", recipients: ["recruiter-a@example.com", "recruiter-aa@example.com"], run_date: "2026-11-04" },
    { summary_id: "org-b", organization_name: "Fictional Org B", recipients: ["recruiter-b@example.com", "failed@example.com"], run_date: "2026-11-04" },
  ];
  for (const batch of summaryCases) {
    batch.candidates = [{ name: "Fictional Candidate " + batch.summary_id, email: "fictional@example.com",
                         job_title: "Fictional Engineer", match_score: 90, reason: "Fixture match", application_id: batch.summary_id }];
  }
  const summaryFixture = {
    id: "summary-fixture", name: "Summary fixture", type: "n8n-nodes-base.code", typeVersion: 2,
    position: [0, 1200], parameters: { jsCode: `return [{json:{summaries:${JSON.stringify(summaryCases)}}}];` },
  };
  const summaryNodes = ["Prepare Organization Messages", "Recruiter SMTP", "Validate Summary SMTP Outcome"]
    .map(name => structuredClone(definition.nodes.find(n => n.name === name)));
  const summarySmtp = summaryNodes[1];
  summarySmtp.disabled = false;
  summarySmtp.credentials = { smtp: { id: credential.id, name: credential.name } };
  summarySmtp.parameters.fromEmail = "fixture@example.com";
  const summaryCheck = {
    id: "summary-check", name: "Check summary outcomes", type: "n8n-nodes-base.code", typeVersion: 2,
    position: [1000, 1200], parameters: { jsCode: `const results = Object.fromEntries($input.all().map(i => [i.json.summary_id, i.json.outcome]));
if (results['org-a'] !== 'sent' || results['org-b'] !== 'unknown') throw new Error('Unexpected summary SMTP outcome');
return $input.all();` },
  };
  const summaryChain = [summaryFixture, ...summaryNodes, summaryCheck];
  const edge = name => ({ node: name, type: "main", index: 0 });
  connections.Start.main[0].push(edge(summaryFixture.name));
  summaryChain.slice(0, -1).forEach((n, i) => { connections[n.name] = { main: [[edge(summaryChain[i+1].name)]] }; });
  nodes.push(...summaryChain);
  const path = "/tmp/smtp-fixture-workflow.json";
  const fixtureId = "FixtureWorkflow1";
  writeFileSync(path, JSON.stringify({ id: fixtureId, name: "Disposable SMTP component test", active: false, nodes, connections, settings: {} }));
  await cli("import:workflow", "--input", path);
  const result = await cli("execute", "--id", fixtureId, "--rawOutput");
  if (!messages.length) throw new Error("No SMTP DATA reached the fixture: " + result.slice(-3500));
  assert.ok(!/Unexpected (summary )?SMTP outcome/.test(result), "SMTP validation did not reach expected outcomes");
  assert.deepEqual(refused, ["failed@example.com", "failed@example.com"]);
  assert.equal(messages.length, 5);
  for (const item of cases.filter(x => x.outcome === "sent")) {
    const message = messages.find(x => x.recipients.includes(item.email));
    assert.ok(message);
    assert.ok(message.body.includes("Fictional Candidate"));
    assert.ok(message.body.includes("Fictional Engineer"));
    assert.ok(message.body.includes(item.status));
    assert.ok(message.body.includes(item.reason));
  }
  for (const batch of summaryCases) {
    const recipient = batch.recipients[0];
    const message = messages.find(x => x.recipients.includes(recipient));
    assert.ok(message);
    assert.deepEqual(message.recipients.sort(), batch.recipients.filter(address => address !== "failed@example.com").sort());
    assert.ok(message.body.includes("Fictional Candidate " + batch.summary_id));
    const other = batch.summary_id === "org-a" ? "org-b" : "org-a";
    assert.ok(!message.body.includes("Fictional Candidate " + other));
  }
  console.log("PASS: real n8n SMTP candidate/summary output at loopback sink, refusal, uncertain acceptance, partial acceptance, and isolated recipients");
  }
} finally {
  server.close();
}

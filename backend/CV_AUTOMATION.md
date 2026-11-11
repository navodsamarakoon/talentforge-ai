# Actual CV automation on the existing demo workflow

## Source baseline and safety

Local master was reset to commit 15 (oldest-to-newest):
`72c25678569b910c247a8118aa8abdb91772dbf0`,
`feat: add candidate registration, job vacancies and CV applications`.
GitHub master remains commit 16; no remote history was changed. All previous local
changes are recoverable from the protected external snapshot
`C:\Users\DELL\talentforge-ai-recovery-20261101_133501` (Git bundle, patches,
250 checksummed files, inventory, and protected-data checksums). This implementation
is new uncommitted work on that baseline, not an exact clean commit-15 tree anymore.

The restored backend Docker image and frontend production build both passed before
new work. PDF/DOCX extraction was selectively reused from the preserved code.
The existing candidate application form, JWT authentication, job association and
private upload storage are reused. No new n8n workflow is needed or created.

This source is NOT deployed. No workflows, stored credentials, production records
or volumes were changed. Preserve the existing `.env`; do not copy secrets into
frontend variables. Previously exposed credentials still require separately
approved remediation before production activation; the old assessment is preserved
in the external recovery snapshot. The previous durable-outbox release image is
not the release for this new plan.

## Backend configuration and lifecycle

Configuration defaults keep `CV_AUTOMATION_ENABLED` and
`N8N_AUTO_DISPATCH_ENABLED` disabled. The CV model is specifically `llama3.2:3b`,
independent of the assessment evaluator's Ollama model. `CV_OLLAMA_URL` accepts only
the local Ollama hosts/port; redirects and environment proxies are disabled.
No CV parsing call uses LangSmith or an external model.

After separately approved deployment/configuration, enabling CV automation queues
an atomic `cv_screenings` record in the same transaction as the application. The
existing upload page submits real multipart PDF/DOCX bytes. Private references stay
server-side. Processing uses bounded text extraction and an Ollama JSON schema with
all fields required, unknown facts nullable/empty, extra keys forbidden, bounded
lists/strings, email validation and strict types. Duplicate JSON keys, markdown
wrappers and invalid/non-JSON output fail closed. CV text is explicitly untrusted;
model output never selects recipients, URLs or decisions.

The profile contains `name`, `email`, `skills`, `education`, `experience`, `projects`,
`certifications`, `languages`, `summary`, `other_information`. Extracted text over
32,000 characters, image-only scans, encrypted PDFs and malformed files require
operator/user intervention; no silent truncation or OCR is performed. Existing
upload limits and page/expanded-DOCX/text limits remain in force.
Parsing runs in a separate process with a 15-second wall timeout and a clean
environment without application credentials. Linux adds a 512 MiB address-space
limit and 10-second CPU limit; Windows development has only the wall timeout.
This is resource/process separation, not a complete filesystem/network sandbox;
production still requires a patched parser and the non-root container boundary.

Application records survive extraction/model/webhook failures. States:
`queued -> extracting -> ready -> dispatching -> accepted`, with `failed` for
pre-handoff processing failures and `unknown` for uncertain HTTP delivery. A send
fence is committed before sending bytes. No HTTP redirects/retries are followed.
`accepted` means an HTTP acknowledgment or workflow claim, NOT completed screening
or email delivery. Poll the authenticated candidate status endpoint below if needed.

Safe retry: an authenticated application owner can POST
`/api/candidate/applications/{application_id}/screening/retry` before any handoff.
It can resume queued/ready work or a failed/expired model lease, with at most three
model attempts. GET the same path without `/retry` for state/error code. Live model
leases are not stolen; expired attempts are fenced by generation tokens. These are
backend endpoints; the existing form is unchanged and does not yet offer a retry UI.

Background tasks are not a persistent scheduler: a crash can leave queued or
extracting work. Resume through the safe retry endpoint after reviewing state;
expired extraction can be retried, but dispatching/unknown/claimed work requires
manual reconciliation. Never reset these states blindly. After a notification
claim, missing delivery evidence is uncertain: no automatic re-send, even if an
execution crashes. This favors preventing duplicate email; manual recovery remains
necessary for uncertain sends. No exactly-once SMTP guarantee is made.

## Migration and future deployment prerequisites

Additive migration `0005_cv_screening` follows `0004_job_applications`, adding only
the private `cv_screenings` ledger. It does not migrate/backfill existing applicants.
The historical initial migration is constrained to its original tables so fresh
installs do not create future ORM tables ahead of later revisions.

Do NOT apply anything now. A separately approved deployment must verify production
is exactly at 0004 and preserve the verified backup, then apply specifically
`alembic -c backend/alembic.ini upgrade 0005_cv_screening` using the reviewed new
source image. If `0005_delivery_outbox` or any other branch is installed, STOP for
schema-history review; do not stamp or merge blindly. That retired local migration
was moved to the external snapshot and was never applied by this work.

Keep flags disabled while verifying the deployed image, schema and manual canvas
mapping. Activation is a separate approval. Roll back code/flags while retaining
the additive ledger and delivery evidence; migration downgrade intentionally refuses
to destroy it. Never restore an old database merely to roll back application code.

## Exact manual canvas changes

Open **TalentForge AI - Automated CV Screening Demo**, ID `OKImoflauBC1lb9g`.
Do not clone/import/create another workflow. These are instructions only; no live
canvas inspection or change was performed, and n8n MCP is not used. Node names below
match the saved reference; if your current node differs, map by function and review
before connecting it. Do not change publication, schedules or email-node state now.

### 1. Existing webhook and input mapping

Use the existing Webhook: POST, path `talentforge-cv-screening`, Header Auth using
the existing credential that matches backend `N8N_WEBHOOK_SECRET`. Production URL
inside Docker is exactly `http://n8n:5678/webhook/talentforge-cv-screening`.
Do not use `/webhook-test/`, expose a secret in the browser, or route to another
workflow. Use immediate acknowledgment (On Received/Immediately, status 202 where
available), not waiting for Ollama or email. Return no candidate profile in the ack.

Add/adjust a Code node **Map Backend CV** immediately after Webhook:

```javascript
const b = $json.body;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
if (!b || b.schema_version !== 1 ||
    !uuid.test(b.application_id) || !uuid.test(b.dispatch_id) || !uuid.test(b.job_id) ||
    typeof b.cv_text !== 'string' || typeof b.candidate_email !== 'string' ||
    !b.cv_profile || typeof b.cv_profile !== 'object') {
  throw new Error('Invalid backend CV envelope');
}
return [{json: {...b, cv_data: b.cv_profile}}];
```

The backend sends trusted account `candidate_name`, `candidate_email`, `candidate_id`,
`application_id`, `job_id`/`job_opening_id`, `organization_id`, `job_title`,
`dispatch_id`, `cv_sha256` (raw file SHA-256), `cv_text`/`screening_text`,
`extraction_status`, `original_filename`, `idempotency_key`, and `cv_profile`.
The CV's extracted `cv_profile.email` is informational only: never use it as an
email recipient. Keep profile facts separate from trusted account identity.

### 2. One-time execution claim

Insert HTTP Request **Claim Backend Screening**, POST:

```text
http://backend:8000/api/integrations/n8n/applications/{{ encodeURIComponent($('Map Backend CV').first().json.application_id) }}/screening/claim
```

Header Auth: existing **TalentForge Backend Callback Auth**, whose header name is
`X-TalentForge-Callback-Secret` and whose value must match backend secure configuration.
Use this credential for ALL callback nodes below. Do not paste its value into node
JSON. JSON body expression:

```javascript
={{ {dispatch_id: $('Map Backend CV').first().json.dispatch_id} }}
```

Add IF **Own Screening?**, boolean `={{ $json.should_process }}` is strictly true.
False ends with no downstream work. On true restore the input with Code:

```javascript
return [{json: $('Map Backend CV').first().json}];
```

Connect to existing **CV Security Pre-Check -> CV Spam Detection Agent -> Finalize
CV Screening**. Replace any hardcoded `Demo CV Input` references with `Map Backend CV`;
continue using `cv_text` for screening. Do not run the old demo/manual input into
delivery gates: it lacks a valid application/dispatch claim.

### 3. Preserve screening and duplicate behavior

Keep existing deterministic pre-checks, spam checks, Crypto, duplicate query and
flagged/duplicate branches. Use the backend's actual `job_id` and candidate fields,
not hardcoded demo IDs. Ensure duplicate SQL parameters are bound (not interpolated)
and scoped to the job/organization. Preserve the original hash algorithm/input for
legacy fingerprint comparisons; do not confuse its `cv_hash` with raw `cv_sha256`.
Do not silently change/recreate production fingerprint tables or indexes.

Validate the Finalize result before any decision callback: `category` must be one
of clean/empty/spam/suspicious/meaningless, `spam_suspected` must be boolean. Reject
invalid/contradictory results rather than defaulting them to clean. The existing
model's JSON text must parse; never execute model-produced code or expressions.
Normalize meaningless -> spam. Deterministic empty/security flags take precedence.
Only a clean, non-flagged result proceeds to the existing duplicate check.

Add Code **Guard Screening Result** after Finalize and before the flagged IF:

```javascript
const x = $json;
const pre = $('CV Security Pre-Check').first().json;
let category = x.category;
if (pre.is_empty === true) category = 'empty';
else if (pre.security_flag === true) category = 'suspicious';
else {
  if (!['clean','empty','spam','suspicious','meaningless'].includes(category) ||
      typeof x.spam_suspected !== 'boolean' ||
      (category === 'clean' && x.spam_suspected !== false) ||
      (category !== 'clean' && x.spam_suspected !== true)) {
    throw new Error('Invalid or contradictory screening result');
  }
}
if (category === 'meaningless') category = 'spam';
return [{json: {...x, category, spam_suspected: category !== 'clean'}}];
```

The flagged decision body is:

```javascript
={{ {dispatch_id: $('Map Backend CV').first().json.dispatch_id, classification: $('Guard Screening Result').first().json.category} }}
```

Converge branches through **Backend Decision**, HTTP POST:

```text
http://backend:8000/api/integrations/n8n/applications/{{ encodeURIComponent($('Map Backend CV').first().json.application_id) }}/decision
```

JSON contains only `dispatch_id` and `classification`. Set classification to
empty/spam/suspicious on the flagged branch, `duplicate` on the existing database
duplicate branch, and `clean` on the clean/nonduplicate branch. The model must not
invent the duplicate flag: require the Postgres node's boolean `is_duplicate === true`.
The backend additionally checks same-job raw-file duplicates by original application
ordering even if clean callbacks arrive out of order. Example clean JSON expression:

```javascript
={{ {dispatch_id: $('Map Backend CV').first().json.dispatch_id, classification: 'clean'} }}
```

Use the response's `status`, `reason_code`, `reason`, `candidate_name`,
`candidate_email`, `application_id`, `job_id` for downstream email branches. A
conflicting final decision gets 409 and must stop. Do not bypass this callback on
rejections or duplicates. Keep legacy fingerprint/selection persistence only on
the corresponding authorized branches and keep organization/job identifiers intact.

### 4. Email claim, messages and receipt

Before ALL candidate email branches, POST **Claim Candidate Notification**:

```text
http://backend:8000/api/integrations/n8n/applications/{{ encodeURIComponent($('Map Backend CV').first().json.application_id) }}/notification/claim
```

Same Header Auth and dispatch-only body as the screening claim. IF
`={{ $json.should_send }}` is strictly true -> existing selection/rejection routing;
false ends. Keep the three existing candidate email nodes and their Gmail SMTP
credential. Recipient MUST be `={{ $('Claim Candidate Notification').first().json.candidate_email }}`,
no CC/BCC, never `cv_profile.email` or model output. Retain existing message style;
include the authoritative `reason` in rejection messages. For example plain text:

```text
Hello {{ $('Claim Candidate Notification').first().json.candidate_name }},
{{ $('Claim Candidate Notification').first().json.reason }}
Job: {{ $('Claim Candidate Notification').first().json.job_id }}
```

Email retry-on-fail OFF. Do not enable email nodes for these tests. When delivery is
separately approved, route successful SMTP output through a strict acceptance guard
before a receipt: expected recipient accepted, no rejected/pending recipients,
provider message ID and successful SMTP response. Uncertain/exception/partial
responses must never generate a sent receipt or automatic resend. Record unknown
when ambiguous, failed only for definite non-delivery. SMTP acceptance is not inbox
delivery and must not be presented as such.

Receipt URL ends `/notification/receipt` on the same application base above. Body:

```javascript
={{ {dispatch_id: $('Map Backend CV').first().json.dispatch_id, outcome: 'sent'} }}
```

Use `outcome: 'unknown'` or `'failed'` only on their explicit evidence branches.
Retries of identical receipt acknowledgments are safe; retries of the SMTP send
are not. A claimed notification with no outcome requires manual reconciliation.

### 5. Recruiter summary remains the existing branch

Keep the existing schedule/selection persistence/recruiter-summary branch in this
workflow. Do not enable or run it now. Ensure selection storage occurs only after
an authoritative selected decision, and retains application/job/organization IDs.
Any pending-selection query and recruiter lookup must be filtered by organization;
never broadcast one organization's candidates to another organization's recruiters.
Keep the intended 06:00 Asia/Colombo schedule. Because this work deliberately does
not inspect/execute the live canvas or modify its legacy tables, compatibility of
those SQL columns and summary idempotency remains a manual verification gate.

### Compatibility fixes required by the saved legacy SQL

The saved duplicate query searches `cv_fingerprints` globally. Its unique
`cv_hash` also controls fingerprint/selection inserts. To keep text normalization
while isolating jobs WITHOUT rewriting old rows or indexes, retain the original
Crypto algorithm/input but name its output `legacy_cv_hash`; add a second Crypto
node (Hash, SHA256, output `cv_hash`) with value:

```javascript
={{ $('Map Backend CV').first().json.job_id + ':' + $json.legacy_cv_hash }}
```

Use this query in **Check Duplicate CV** (existing database credential):

```sql
SELECT EXISTS (
  SELECT 1 FROM cv_fingerprints
  WHERE cv_hash = $1 OR (cv_hash = $2 AND job_id::text = $3)
) AS is_duplicate;
```

Bind the array `[newScopedHash, legacyHash, actualJobId]` from the two Crypto/Map
outputs using Query Parameters, not string interpolation. Keep both hash fields
through **Prepare Duplicate Result**. Store the new scoped `cv_hash` in existing
fingerprint/selection inserts; existing `ON CONFLICT (cv_hash)` remains compatible.
This recognizes old fingerprints for their original job while allowing the same CV
on another job. Review job ID types and the existing normalization/algorithm before
editing. This manual compatibility change was NOT executed or tested on the live
legacy tables. Semantic text-hash duplicate races in the legacy workflow still need
manual concurrency verification; backend raw-file checks do not prove them safe.

Name the second Crypto node **Scoped CV Hash**. Exact duplicate Query Parameters:

```javascript
={{ [$('Scoped CV Hash').first().json.cv_hash, $('Crypto').first().json.legacy_cv_hash, $('Map Backend CV').first().json.job_id] }}
```

In **Prepare Duplicate Result**, set account name/email/job/application/dispatch IDs
from **Map Backend CV**, `cv_hash` from **Scoped CV Hash**, `legacy_cv_hash` from
**Crypto**, and `is_duplicate` from the query's boolean result. Use these four-value
Query Parameters in the existing fingerprint/selection inserts:

```javascript
={{ [$('Prepare Duplicate Result').first().json.candidate_name, $('Prepare Duplicate Result').first().json.candidate_email, $('Prepare Duplicate Result').first().json.job_id, $('Prepare Duplicate Result').first().json.cv_hash] }}
```

For **Get Pending Interview Selections**, the saved global query must be replaced
with an organization-scoped join before real multi-organization delivery:

```sql
SELECT s.id, s.candidate_name, s.candidate_email, s.job_id, s.selected_at,
       j.organization_id,
       (SELECT array_agg(u.email ORDER BY u.email)
        FROM users u WHERE u.organization_id = j.organization_id
          AND u.role = 'recruiter') AS recruiter_emails
FROM interview_selections s
JOIN job_openings j ON j.id = s.job_id::text
WHERE s.recruiter_notified_at IS NULL
ORDER BY j.organization_id, s.selected_at, s.id;
```

Review legacy job IDs that do not join to real jobs; do not silently assign them to
an organization or delete them. Group only by `organization_id` in **Prepare Daily
Recruiter Summary**, building one message/selection-ID list per group using the
existing HTML escaping function. Require nonempty validated `recruiter_emails`.
Set **Send Recruiter Summary Email** To from that group's database-derived array,
never a hardcoded address. If multiple output items are produced, use linked-item
expressions (`.item`), not `.first()`, for recipients and selection IDs.

Replacement **Prepare Daily Recruiter Summary** Code (one item per organization):

```javascript
const groups = new Map();
const esc = value => String(value ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
  .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
$input.all().forEach((item, index) => {
  const c = item.json;
  if (!c.organization_id || !Array.isArray(c.recruiter_emails) || !c.recruiter_emails.length) {
    throw new Error('Missing organization/recruiter routing');
  }
  let g = groups.get(c.organization_id);
  if (!g) {
    g = {organization_id:c.organization_id, recruiter_emails:c.recruiter_emails,
         candidates:[], first:index};
    groups.set(c.organization_id,g);
  }
  g.candidates.push(c);
});
return [...groups.values()].map(g => ({json:{
  organization_id:g.organization_id, recruiter_emails:g.recruiter_emails,
  selection_ids:g.candidates.map(c=>c.id), total_candidates:g.candidates.length,
  email_subject:'TalentForge AI - Daily Interview Selection Summary',
  email_html:'<h2>Selected candidates</h2><table>' + g.candidates.map(c=>
    `<tr><td>${esc(c.candidate_name)}</td><td>${esc(c.candidate_email)}</td><td>${esc(c.job_id)}</td></tr>`
  ).join('') + '</table>'
}, pairedItem:{item:g.first}}));
```

Summary To: `={{ $json.recruiter_emails.join(',') }}`, subject
`={{ $json.email_subject }}`, HTML `={{ $json.email_html }}`. The guarded update's
Query Parameters after SMTP must use linked items:

```javascript
={{ [$('Prepare Daily Recruiter Summary').item.json.selection_ids, $('Prepare Daily Recruiter Summary').item.json.organization_id] }}
```

After confirmed SMTP acceptance for every intended recruiter, use this bound update
in **Mark Recruiter Notified**:

```sql
UPDATE interview_selections s SET recruiter_notified_at = NOW()
WHERE s.id = ANY($1::bigint[]) AND s.recruiter_notified_at IS NULL
  AND EXISTS (SELECT 1 FROM job_openings j
              WHERE j.id = s.job_id::text AND j.organization_id = $2)
RETURNING s.id;
```

Bind `[groupSelectionIds, groupOrganizationId]`. Do not mark notified on an email
failure/uncertain result. The legacy summary branch has no durable SMTP uncertainty
ledger; a crash after SMTP acceptance but before this update is a remaining
recovery/idempotency blocker for unattended summaries. Keep that schedule/email
branch unexecuted until its separately approved verification and recovery plan.

## Safe test/activation gates

Verification recorded in `.cv-verify/report.json`: baseline backend/frontend builds
passed; 61 unique focused upload/parser/automation cases passed across the affected
runs (39 initial upload/automation, 37 final parser/automation, with overlap).
Real local `llama3.2:3b` extraction from the approved fictional PDF passed strict
schema and expected-fact checks. Actual HTTP to the isolated receiver and PostgreSQL
migration/concurrent-dispatch/concurrent-claim, duplicate/spam, organization and
notification receipt checks passed. Twelve manual JavaScript/expression blocks
compiled without executing n8n nodes. No full unrelated suites were repeated.

Authorized local PDF/Ollama test uses a generated fictional CV, direct local model
and strict schema; no tracing, n8n or email. The HTTP integration environment uses
a fake n8n receiver, disposable PG16 tmpfs, internal gateway-isolated network and
no production mounts, ports or credentials. It verifies actual HTTP request shape,
concurrency/claim fencing and duplicate/email-receipt gates. This is NOT proof of a
live execution of the existing n8n canvas.

Before that live test: an authorized operator must manually isolate/disable EVERY
SMTP and receipt/legacy write path, verify there is no alternate path to real data,
and approve the exact synthetic execution scope. If it would require publishing or
changing the active original, request separate approval first. No such execution
or publication was performed. Future activation also requires migration/deployment,
credential remediation, manual node validation, and explicit publication/email/
dispatch approval. Do not enable flags merely to test this source on production.

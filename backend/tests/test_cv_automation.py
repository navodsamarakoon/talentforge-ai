import asyncio
import json
import io
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from types import SimpleNamespace

import httpx
import pymupdf
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from talentforge import cv_automation as cv
from talentforge.config import get_settings
from talentforge.models import AuditEvent, CVScreening, JobApplication, JobOpening, User, utcnow
from talentforge.database import SessionLocal
from test_job_applications import published_job, submit
from test_job_openings import candidate_auth

PROFILE = dict(name="Synthetic Example", email="cv-address@example.com", skills=["Python", "FastAPI"],
               education=["BSc Computer Science"], experience=["Software intern"], projects=["Test API"],
               certifications=[], languages=["English"], summary="Synthetic CV", other_information=[])


def pdf():
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72,72), "Synthetic Example\ncv-address@example.com\nSkills: Python, FastAPI\nEducation: BSc Computer Science\nExperience: Software intern\nProjects: Test API")
        return doc.tobytes()


@pytest.fixture
def automation(client, monkeypatch, tmp_path):
    settings=get_settings()
    for k,v in dict(cv_automation_enabled=True,n8n_auto_dispatch_enabled=True,
                    cv_upload_dir=tmp_path, n8n_webhook_url="http://n8n:5678/webhook/talentforge-cv-screening",
                    n8n_webhook_secret=SecretStr("synthetic-webhook"),n8n_callback_secret=SecretStr("synthetic-callback")).items():
        monkeypatch.setattr(settings,k,v)
    # Background processing must use the synthetic test session factory.
    monkeypatch.setattr(cv,"SessionLocal",SessionLocal)
    return client


def mocks(monkeypatch, *, model_content=None, webhook_error=False, done_reason="stop"):
    calls=[];real=httpx.AsyncClient
    def handle(request):
        data=json.loads(request.content);calls.append((str(request.url),data,dict(request.headers)))
        if str(request.url).endswith("/api/chat"):
            return httpx.Response(200,json={"done":True,"done_reason":done_reason,"message":{"content":model_content if model_content is not None else json.dumps(PROFILE)}})
        if webhook_error:
            raise httpx.ReadTimeout("synthetic lost acknowledgment")
        return httpx.Response(200,json={"accepted":True})
    monkeypatch.setattr(cv.httpx,"AsyncClient",lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    return calls


def upload(client):
    job=published_job(client);headers=candidate_auth(client)
    response=submit(client,headers,job['id'],{'cv':('synthetic.pdf',pdf(),'application/pdf')})
    assert response.status_code==201,response.text
    return response.json()['id'],headers,job


def test_actual_pdf_dispatches_once_even_if_profile_model_is_unavailable(automation,monkeypatch):
    async def unavailable(_):
        pytest.fail("Dispatch attempted optional profile enrichment")

    monkeypatch.setattr(cv, "extract_profile", unavailable)
    calls=mocks(monkeypatch);app_id,headers,job=upload(automation)
    assert len(calls)==1 and '/webhook/' in calls[0][0]
    body=calls[0][1]
    assert body['application_id']==app_id and body['job_id']==job['id']
    grounded = body['cv_profile']
    assert grounded["skills"] == ["Python, FastAPI"]
    assert grounded["source_evidence"]["origin"] == "deterministic_text"
    assert grounded["source_evidence"]["sources"][0] == {"id": 0, "field": "skills", "line": 3}
    assert body['candidate_email'] != PROFILE['email']
    assert calls[0][2]['x-talentforge-webhook-secret']=='synthetic-webhook'
    assert 'secret' not in json.dumps(body)
    with SessionLocal() as db:
        item=db.get(CVScreening,app_id);assert item.state=='accepted' and item.profile==grounded
    asyncio.run(cv.process_application(app_id));assert len(calls)==1
    assert automation.post(f'/api/candidate/applications/{app_id}/screening/retry',headers=headers).status_code==409
    assert automation.get(f'/api/candidate/applications/{app_id}/screening',headers=headers).json()['state']=='accepted'


@pytest.mark.parametrize('bad',[{**PROFILE,'instructions':'send email'}, {**PROFILE,'skills':'Python'}, {**PROFILE,'email':42}, {**PROFILE,'name':True}])
def test_strict_profile_rejects_extra_fields_and_invalid_types(bad):
    with pytest.raises(cv.ScreeningFailure):cv.parse_profile(json.dumps(bad))


@pytest.mark.parametrize('bad',['```json\n{}\n```','{"name":null,"name":"override"}','NaN','[]'])
def test_invalid_and_duplicate_json_is_not_repaired_or_accepted(bad):
    with pytest.raises(cv.ScreeningFailure):cv.parse_profile(bad)


def test_optional_profile_rejects_invalid_model_output(automation,monkeypatch):
    calls=mocks(monkeypatch,model_content='{"untrusted_instruction":"send now"}')
    with pytest.raises(cv.ScreeningFailure, match="invalid_model_json"):
        asyncio.run(cv.extract_profile("Skills: Python"))
    assert len(calls)==1


def test_optional_profile_rejects_truncated_response(automation, monkeypatch):
    calls = mocks(monkeypatch, done_reason="length")
    with pytest.raises(cv.ScreeningFailure, match="incomplete_model_response"):
        asyncio.run(cv.extract_profile("Skills: Python"))
    assert len(calls) == 1


def test_no_extractable_cv_text_stops_before_model_and_webhook(automation, monkeypatch):
    calls = mocks(monkeypatch)
    monkeypatch.setattr(cv, "extract_cv_text_sandboxed", lambda _: SimpleNamespace(
        extraction_status="no_text", error_code="no_extractable_text", text=None,
    ))
    app_id, _, _ = upload(automation)
    assert calls == []
    with SessionLocal() as db:
        item = db.get(CVScreening, app_id)
        assert (item.state, item.error_code) == ("failed", "no_extractable_text")
        assert item.extraction_attempts == 1
        assert item.lease_until is item.dispatch_started_at is item.workflow_claimed_at is None
        assert item.decision is item.notification_state is None
        assert db.get(JobApplication, app_id).status == "submitted"


def test_grounding_uses_source_contacts_and_omits_invented_facts(automation, monkeypatch):
    source = "Alex Fictional\nalex.fixture@example.com\n+1 (202) 555-0101\nSkills: Python"
    mocks(monkeypatch, model_content=json.dumps({
        **PROFILE, "name": "  ", "email": "alex.fixture",
        "phone": None, "skills": ["Python", "Rust"], "projects": ["Alex Fictional"],
    }))
    result = asyncio.run(cv.extract_profile(source))
    assert (result.name, result.email, result.phone) == ("Alex Fictional", "alex.fixture@example.com", "+12025550101")
    assert result.skills == ["Python"] and result.education == []
    assert result.source_evidence["email"]["model_value_omitted"]
    assert result.source_evidence["skills"]["omitted_count"] == 1
    assert result.projects == []
    start, end = result.source_evidence["phone"]["spans"][0]
    assert source[start:end] == "+1 (202) 555-0101"
    assert result.source_evidence["summary"]["status"] == "unverified_summary"


def test_ambiguous_contacts_are_not_resolved_by_ollama(automation, monkeypatch):
    source = (
        "Name: Alex Fictional\nName: Blair Fictional\n"
        "alex.fixture@example.com\nblair.fixture@example.com\n"
        "Phone: 077 123 4567\nPhone: 076 123 4567\nSkills: Python"
    )
    mocks(monkeypatch, model_content=json.dumps({**PROFILE, "name": "Alex Fictional"}))
    result = asyncio.run(cv.extract_profile(source))
    assert (result.name, result.email, result.phone) == (None, None, None)
    assert all(result.source_evidence[key]["status"] == "ambiguous" for key in ("name", "email", "phone"))
    assert cv.parse_profile(json.dumps({**PROFILE, "email": " ", "summary": ""})).email is None


@pytest.mark.parametrize("outcome", ["sent", "unknown", "failed"])
def test_timeout_after_webhook_is_quarantined_not_retried(automation,monkeypatch,outcome):
    monkeypatch.setattr(cv, "extract_cv_text_sandboxed", lambda _: SimpleNamespace(
        extraction_status="success", error_code=None, text="Skills: Python, FastAPI"))
    calls=mocks(monkeypatch,webhook_error=True);app_id,headers,_=upload(automation)
    with SessionLocal() as db:assert db.get(CVScreening,app_id).state=='unknown'
    history = automation.get("/api/candidate/applications", headers=headers).json()[0]
    assert history["status"] == "submitted" and "requires recovery review" in history["processing_status"]
    asyncio.run(cv.process_application(app_id))
    assert len(calls)==1
    assert automation.post(f'/api/candidate/applications/{app_id}/screening/retry',headers=headers).status_code==409
    with SessionLocal() as db:
        reference = {"dispatch_id": db.get(CVScreening, app_id).dispatch_id}
        assert db.scalar(select(AuditEvent.action).where(AuditEvent.entity_id == app_id)) == "webhook_delivery_uncertain"
    base = f"/api/integrations/n8n/applications/{app_id}"
    auth = {"X-TalentForge-Callback-Secret": "synthetic-callback"}
    assert automation.post(base+"/screening/claim", json=reference).status_code == 401
    assert automation.post(base+"/screening/claim", headers=auth, json=reference).json()["should_process"]
    assert not automation.post(base+"/screening/claim", headers=auth, json=reference).json()["should_process"]
    assert automation.post(base+"/decision", headers=auth, json={**reference, "classification":"spam"}).status_code == 200
    assert automation.post(base+"/notification/claim", headers=auth, json=reference).json()["should_send"]
    assert automation.post(base+"/notification/receipt", headers=auth, json={**reference, "outcome":outcome}).status_code == 200
    with SessionLocal() as db:
        item = db.get(CVScreening, app_id)
        assert item.error_code is None and item.notification_state == outcome
        assert sorted(db.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == app_id))) == [
            "webhook_delivery_uncertain", "webhook_delivery_uncertain_resolved_by_claim"]
    history = automation.get("/api/candidate/applications", headers=headers).json()
    assert history[0]["status"] == "rejected"
    assert history[0]["processing_status"] == {
        "sent": None,
        "unknown": "Decision recorded. Email delivery could not be confirmed.",
        "failed": "Decision recorded. Email delivery failed.",
    }[outcome]
    if outcome == "sent":
        with SessionLocal() as db:
            db.get(CVScreening, app_id).error_code = "webhook_delivery_uncertain"
            db.commit()
        status = automation.get(f"/api/candidate/applications/{app_id}/screening", headers=headers).json()
        assert status == {"state": "accepted", "error_code": None}
        with SessionLocal() as db:
            assert db.get(CVScreening, app_id).error_code == "webhook_delivery_uncertain"


def test_parser_timeout_safe_retry_does_not_duplicate_application(automation,monkeypatch):
    def timeout(_):raise cv.ScreeningFailure('extraction_timeout')
    monkeypatch.setattr(cv,'extract_cv_text_sandboxed',timeout);app_id,headers,_=upload(automation)
    history = automation.get("/api/candidate/applications", headers=headers).json()
    assert history[0]["status"] == "submitted"
    assert "timed out" in history[0]["processing_status"]
    assert "saved" in history[0]["processing_status"]
    for _ in range(2):assert automation.post(f'/api/candidate/applications/{app_id}/screening/retry',headers=headers).status_code==202
    assert automation.post(f'/api/candidate/applications/{app_id}/screening/retry',headers=headers).status_code==409
    with SessionLocal() as db:assert db.get(CVScreening,app_id).extraction_attempts==3


def test_expired_extraction_token_is_invalidated_before_recovery(automation,monkeypatch):
    mocks(monkeypatch);app_id,_,_=upload(automation)
    with SessionLocal() as db:
        item=db.get(CVScreening,app_id);item.state='extracting';item.dispatch_started_at=None
        item.lease_until=utcnow()-timedelta(seconds=1);item.generation_token='stale'
        assert cv.queue_retry(db,item) and item.generation_token is None
        db.rollback()


@pytest.mark.parametrize('classification,expected_status',[('clean',None),('duplicate','rejected')])
def test_workflow_claim_decision_notification_and_receipt_are_idempotent(automation,monkeypatch,classification,expected_status):
    monkeypatch.setattr(cv, "extract_cv_text_sandboxed", lambda _: SimpleNamespace(
        extraction_status="success", error_code=None, text="Skills: Python, FastAPI"))
    mocks(monkeypatch);app_id,_,_=upload(automation)
    with SessionLocal() as db:reference={'dispatch_id':db.get(CVScreening,app_id).dispatch_id}
    base=f'/api/integrations/n8n/applications/{app_id}'
    auth={'X-TalentForge-Callback-Secret':'synthetic-callback'}
    assert automation.post(base+'/screening/claim',json=reference).status_code==401
    assert automation.post(base+'/screening/claim',json=reference,headers=auth).json()['should_process']
    assert not automation.post(base+'/screening/claim',json=reference,headers=auth).json()['should_process']
    decision=automation.post(base+'/decision',json={**reference,'classification':classification},headers=auth)
    if expected_status is None:
        assert decision.status_code == 409
        assert automation.post(base+'/notification/claim',json=reference,headers=auth).status_code == 409
        with SessionLocal() as db:
            assert db.get(JobApplication,app_id).status == 'screening'
            assert db.get(CVScreening,app_id).decision is None
        return
    assert decision.json()['status']==expected_status
    assert automation.post(base+'/decision',json={**reference,'classification':'spam'},headers=auth).status_code==409
    assert automation.post(base+'/notification/claim',json=reference,headers=auth).json()['should_send']
    assert not automation.post(base+'/notification/claim',json=reference,headers=auth).json()['should_send']
    assert automation.post(base+'/notification/receipt',json={**reference,'outcome':'sent'},headers=auth).status_code==200
    assert automation.post(base+'/notification/receipt',json={**reference,'outcome':'sent'},headers=auth).status_code==200
    assert automation.post(base+'/notification/receipt',json={**reference,'outcome':'failed'},headers=auth).status_code==409


def test_other_candidate_cannot_read_or_retry_screening(automation,monkeypatch):
    mocks(monkeypatch);app_id,_,_=upload(automation)
    other=candidate_auth(automation,'other@example.com')
    for suffix,method in [('',automation.get),('/retry',automation.post)]:
        assert method(f'/api/candidate/applications/{app_id}/screening'+suffix,headers=other).status_code==404


@pytest.mark.parametrize("mode,expected", [
    ("pass", "selected"), ("low", "selected"), ("missing_skill", "job_mismatch"),
    ("invalid", None), ("unavailable", None),
])
def test_matching_decision(automation, monkeypatch, mode, expected):
    mocks(monkeypatch)
    app_id, _, job = upload(automation)
    with SessionLocal() as db:
        db.get(JobOpening, job["id"]).requirements = {
            "mandatory_skills": ["Rust" if mode == "missing_skill" else "Python"],
        }
        item = db.get(CVScreening, app_id)
        if mode in {"invalid", "unavailable"}:
            item.cv_text = item.cv_text.replace("Python, FastAPI", "No Python, FastAPI")
        reference = {"dispatch_id": item.dispatch_id}
        db.commit()
    client_type = httpx.Client

    def respond(request):
        if mode == "unavailable":
            raise httpx.ConnectError("synthetic unavailable", request=request)
        content = "invalid" if mode == "invalid" else json.dumps({
            "score": 40 if mode == "low" else 90, "evidence_indices": [0],
        })
        return httpx.Response(200, json={"done": True, "message": {"content": content}})

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_type(
        transport=httpx.MockTransport(respond), **kwargs
    ))
    base = f"/api/integrations/n8n/applications/{app_id}"
    auth = {"X-TalentForge-Callback-Secret": "synthetic-callback"}
    assert automation.post(base + "/screening/claim", json=reference, headers=auth).status_code == 200
    body = {**reference, "classification": "clean"}
    assert automation.post(base + "/decision", json={**body, "dispatch_id": str(uuid4())}, headers=auth).status_code == 409
    assert automation.post(base + "/decision", json={**body, "match_score": 100}, headers=auth).status_code == 422
    response = automation.post(base + "/decision", json=body, headers=auth)
    if expected is None:
        assert response.status_code == (503 if mode == "unavailable" else 409)
        assert response.json()["detail"]["code"] == (
            "advisory_unavailable" if mode == "unavailable" else "advisory_invalid_response"
        )
    else:
        assert response.json()["reason_code"] == expected
        assert automation.post(base + "/decision", json=body, headers=auth).json() == response.json()
    with SessionLocal() as db:
        item = db.get(CVScreening, app_id)
        assert item.decision == expected
        if expected:
            assert item.match_result["application_id"] == app_id
            assert item.match_result["job_id"] == job["id"]
        else:
            assert item.match_result["decision"] == "unresolved"
            assert item.error_code == "job_matching_unresolved"
            assert item.notification_state is None


@pytest.mark.parametrize("requirements", [None, {"preferred_skills": ["Python"]}])
def test_missing_mandatory_requirements_is_a_configuration_conflict(automation, monkeypatch, requirements):
    from talentforge import job_matching

    mocks(monkeypatch)
    monkeypatch.setattr(job_matching, "_semantic_review", lambda *_: pytest.fail("Unexpected model call"))
    app_id, candidate_headers, job = upload(automation)
    with SessionLocal() as db:
        db.get(JobOpening, job["id"]).requirements = requirements
        reference = {"dispatch_id": db.get(CVScreening, app_id).dispatch_id}
        db.commit()
    base = f"/api/integrations/n8n/applications/{app_id}"
    auth = {"X-TalentForge-Callback-Secret": "synthetic-callback"}
    assert automation.post(base + "/screening/claim", json=reference, headers=auth).status_code == 200
    decision = {**reference, "classification": "clean"}
    response = automation.post(base + "/decision", json=decision, headers=auth)
    assert response.status_code == 409
    assert "recruiter must configure" in response.json()["detail"]["message"]
    assert automation.post(base + "/notification/claim", json=reference, headers=auth).status_code == 409
    history = automation.get("/api/candidate/applications", headers=candidate_headers).json()
    assert "configure mandatory" in history[0]["processing_status"]
    with SessionLocal() as db:
        item = db.get(CVScreening, app_id)
        assert item.error_code == "job_matching_requirements_missing"
        assert item.match_result is item.decision is item.notification_state is None
        db.get(JobOpening, job["id"]).requirements = {"mandatory_skills": ["Python"]}
        db.commit()
    assert automation.post(base + "/decision", json=decision, headers=auth).json()["reason_code"] == "selected"
    with SessionLocal() as db:
        assert db.get(CVScreening, app_id).error_code is None


@pytest.mark.parametrize("classification", ["spam", "suspicious", "empty", "meaningless"])
def test_flagged_decision_skips_matching(automation, monkeypatch, classification):
    from talentforge import cv_callbacks

    def forbidden(*args):
        pytest.fail("Flagged CV reached matching")

    monkeypatch.setattr(cv_callbacks, "match_job", forbidden)
    mocks(monkeypatch)
    app_id, _, _ = upload(automation)
    with SessionLocal() as db:
        reference = {"dispatch_id": db.get(CVScreening, app_id).dispatch_id}
    base = f"/api/integrations/n8n/applications/{app_id}"
    auth = {"X-TalentForge-Callback-Secret": "synthetic-callback"}
    assert automation.post(base + "/screening/claim", json=reference, headers=auth).status_code == 200
    response = automation.post(base + "/decision", json={**reference, "classification": classification}, headers=auth)
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["reason_code"] == classification


def test_near_duplicate_requires_identical_substantial_normalized_body():
    from talentforge.job_matching import materially_identical

    body = "Implemented a Python API for inventory audits. " * 8
    assert materially_identical("First Candidate\n" + body, "Second Candidate\n" + body.upper())
    assert not materially_identical("First Candidate\n" + body, "Second Candidate\n" + body + "Different project.")
    assert not materially_identical("First Candidate\nPython", "Second Candidate\nPython")


def test_experience_excludes_future_and_overlapping_months(monkeypatch):
    from talentforge.job_matching import match_job
    from talentforge.schemas import JobRequirements

    entries = ["Python API work 2020-01 – 2021-01", "Python consulting 2020-06 – 2021-06",
               "Planned Python position 2090-01 – 2091-01"]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "done": True, "message": {"content": '{"score": 90, "evidence_indices": [1]}'},
    }))
    client_type = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_type(transport=transport, **kwargs))
    result = match_job(JobRequirements(mandatory_skills=["Python"], minimum_experience_months=17),
                       "Python API work", {"skills": ["Python"], "experience": entries}, "\n".join(entries))
    assert result["decision"] == "pass"
    assert result["experience_alignment"]["verified_months"] == 17
    assert result["experience_alignment"]["evidence"] == entries[:2]


def test_skill_substring_does_not_satisfy_mandatory_requirement():
    from talentforge.job_matching import match_job
    from talentforge.schemas import JobRequirements

    result = match_job(JobRequirements(mandatory_skills=["SQL"]), "SQL analyst",
                       {"skills": ["SQL", "PostgreSQL"]}, "Skills: PostgreSQL")
    assert result["decision"] == "fail"
    assert result["missing_required_skills"] == ["SQL"]


@pytest.mark.parametrize("term,skills,projects,expected", [
    ("Python", ["Java, Python, Dart"], [], "pass"),
    ("Python", ["Languages: Java, Python, Dart"], [], "pass"),
    ("Python", ["Java, Dart"], [], "fail"),
    ("Java", ["JavaScript"], [], "fail"),
    ("C", ["C++"], [], "fail"),
    ("SQL", ["NoSQL"], [], "fail"),
    ("FastAPI", ["Django"], [], "fail"),
    ("Python", ["Go"], ["Built an inventory API using Python"], "pass"),
    ("Python", ["No Python experience"], [], "unresolved"),
    ("React", ["React Native"], [], "unresolved"),
    ("Node.js", ["Node topology"], [], "fail"),
    ("Python", [], ["Project Technology Stack: Python and Go"], "pass"),
])
def test_hybrid_requirement_matrix(monkeypatch, term, skills, projects, expected):
    from talentforge import job_matching
    from talentforge.schemas import JobRequirements

    def review(_, requirements, facts):
        assert requirements[0]["candidate_sources"] == [0]
        return [{"requirement_id": "skill-0", "matched": "uncertain",
                 "evidence_source_ids": [0], "justification": "Negated experience."}]

    monkeypatch.setattr(job_matching, "_semantic_review", review)
    result = job_matching.match_job(JobRequirements(mandatory_skills=[term], preferred_skills=["Docker"]),
                                    "Backend development", {"skills": skills, "projects": projects},
                                    "\n".join(skills + projects))
    assert result["decision"] == expected


def test_wrapped_full_stack_skill_entry_keeps_original_line_references():
    from talentforge.job_matching import match_job
    from talentforge.schemas import JobRequirements

    requirements = JobRequirements(
        mandatory_skills=["JavaScript", "TypeScript", "React", "Node.js", "Express.js", "MongoDB"]
    )
    source = "JavaScript, TypeScript, SQL, React.js, React Native, Node.js, Express.js,\nMongoDB, Docker"
    result = match_job(requirements, "", {"skills": [source.replace("\n", " ")]}, source)
    assert result["decision"] == "pass"
    assert result["matched_skills"] == requirements.mandatory_skills
    assert result["sources"][0]["source_lines"] == [1, 2]
    assert result["advisory_calls"] == 0


@pytest.mark.parametrize("source,expected", [
    ("Skills: Docker, Docker Compose,\nGit, AWS (Learning)", "pass"),
    ("Skills: Docker, Python", "fail"),
    ("Skills: Docker, Docker Compose (Learning)", "unresolved"),
    ("Skills: Docker, no experience with Docker Compose", "unresolved"),
])
def test_text_first_profile_enforces_required_skills(source, expected, monkeypatch):
    from talentforge import job_matching
    from talentforge.cv_evidence import deterministic_profile
    from talentforge.schemas import JobRequirements

    monkeypatch.setattr(job_matching, "_semantic_review", lambda *_: [])
    profile = deterministic_profile(source)
    result = job_matching.match_job(JobRequirements(mandatory_skills=["Docker", "Docker Compose"]),
                                    "", profile, source)
    assert result["decision"] == expected
    if expected == "pass":
        assert profile["source_evidence"]["sources"][0]["end_line"] == 2
        assert result["advisory_calls"] == 0


@pytest.mark.parametrize("rejected,expected_code", [
    ([], "model_extraction_omission"),
    (["ci/cd"], "grounding_rejection"),
])
def test_scoped_skill_qualifier_and_source_only_cicd(rejected, expected_code):
    from talentforge.cv_evidence import ground_profile
    from talentforge.job_matching import match_job
    from talentforge.schemas import JobRequirements

    skills = "Platform Operations: Docker, Docker Compose, Jenkins, Terraform, AWS (Learning)"
    source = f"• {skills}\nTools: Git, Linux\n• Delivery: CI/CD, Build Automation"
    required = ["Docker", "Docker Compose", "Jenkins", "Terraform", "Git", "Linux", "CI/CD"]
    proposed = [skills, "Tools: Git, Linux"]
    if rejected:
        proposed.append("Delivery: CI/CD, Unsupported Automation")
    profile, evidence = ground_profile(source, {**PROFILE, "phone": None, "skills": proposed})
    profile["source_evidence"] = evidence
    result = match_job(JobRequirements(mandatory_skills=required, preferred_skills=["AWS"]), "", profile, source)
    assert result["decision"] == "pass"
    assert result["matched_skills"] == required
    assert result["advisory_calls"] == 0
    check = result["requirements"][6]
    assert check["evidence_code"] == expected_code
    evidence = result["sources"][check["evidence_source_ids"][0]]
    assert evidence["origin"] == "explicit_source_list" and evidence["source_lines"] == [3]


@pytest.mark.parametrize("line", [
    "Tools: No experience with Docker, Jenkins",
    "Tools: Docker (Learning), Jenkins",
    "Required Tools: Docker, Jenkins",
    "Tools: Docker Compose, Jenkins",
    "Not familiar with\nTools: Docker, Jenkins",
])
def test_source_fallback_does_not_verify_qualified_or_related_skills(line):
    from talentforge.job_matching import match_job
    from talentforge.schemas import JobRequirements

    result = match_job(JobRequirements(mandatory_skills=["Docker"]), "",
                       {"skills": ["Linux"]}, f"Linux\n{line}")
    assert result["decision"] == "unresolved"
    assert result["matched_skills"] == []


def test_wrapped_negated_skill_is_not_verified(monkeypatch):
    from talentforge import job_matching
    from talentforge.schemas import JobRequirements

    monkeypatch.setattr(job_matching, "_semantic_review", lambda *_: [])
    result = job_matching.match_job(JobRequirements(mandatory_skills=["MongoDB"]), "",
                                    {"skills": ["Tools: Docker, no MongoDB"]},
                                    "Tools: Docker, no\nMongoDB")
    assert result["decision"] == "unresolved"


@pytest.mark.parametrize("claimed,source_ids", [(True, [0]), ("uncertain", [99])])
def test_semantic_review_cannot_override_mandatory_evidence(monkeypatch, claimed, source_ids):
    from talentforge.job_matching import match_job
    from talentforge.schemas import JobRequirements

    content = json.dumps({"assessments": [{"requirement_id": "skill-0", "matched": claimed,
                                           "evidence_source_ids": source_ids, "justification": "Unverified."}]})
    client_type = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, json={"done": True, "message": {"content": content}}))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_type(transport=transport, **kwargs))
    result = match_job(JobRequirements(mandatory_skills=["Python"]), "Python developer",
                       {"skills": ["Learning Python"]}, "Learning Python")
    assert result["decision"] == "unresolved"
    assert result["semantic_review"] == []


def test_every_mandatory_skill_and_credential_is_required():
    from talentforge.job_matching import match_job
    from talentforge.schemas import JobRequirements

    skills = ["Languages: Java, Python, Dart"]
    certification = "AWS Certified Developer, issued 2024"
    source = "\n".join([*skills, certification])
    profile = {"skills": skills, "certifications": [certification]}
    requirements = JobRequirements(mandatory_skills=["Python"], preferred_skills=["Go"],
                                   qualifications=["AWS Certified Developer"], minimum_match_score=100)
    result = match_job(requirements, "Python backend", profile, source)
    assert result["decision"] == "pass" and result["match_score"] == 100
    assert result["qualification_alignment"] == {"AWS Certified Developer": True}
    result = match_job(requirements.model_copy(update={"mandatory_skills": ["Python", "Rust"]}),
                       "Python backend", profile, source)
    assert result["decision"] == "fail" and result["missing_required_skills"] == ["Rust"]


def test_disabled_automation_keeps_existing_upload_behavior(client,monkeypatch,tmp_path):
    monkeypatch.setattr(get_settings(),'cv_upload_dir',tmp_path)
    assert not get_settings().cv_automation_enabled
    def forbidden(**_):raise AssertionError('Disabled upload made an outbound request')
    monkeypatch.setattr(cv.httpx,'AsyncClient',forbidden)
    app_id,headers,_=upload(client)
    with SessionLocal() as db:assert db.get(CVScreening,app_id) is None
    assert client.get(f'/api/candidate/applications/{app_id}/screening',headers=headers).json()['state']=='not_scheduled'


@pytest.mark.parametrize('destination',['https://example.com/hook','http://n8n:5678/webhook-test/talentforge-cv-screening','http://n8n:5678/webhook/talentforge-cv-screening?override=true'])
def test_webhook_destination_is_exact_and_backend_only(monkeypatch,destination):
    monkeypatch.setattr(get_settings(),'n8n_webhook_url',destination)
    with pytest.raises(cv.ScreeningFailure,match='invalid_n8n_destination'):cv.webhook_configuration()

def test_profile_total_deadline_stops_a_continuously_streaming_model(monkeypatch):
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(0.01)
                yield b" "

    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowStream()))
    monkeypatch.setattr(cv.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
    monkeypatch.setattr(get_settings(), "cv_ollama_timeout_seconds", 0.03)
    with pytest.raises(cv.ScreeningFailure, match="ollama_timeout"):
        asyncio.run(asyncio.wait_for(cv.extract_profile("Skills: Python"), timeout=1))


def test_cancelled_extraction_records_recoverable_failure(automation, monkeypatch):
    def timeout(_):
        raise cv.ScreeningFailure("extraction_timeout")

    monkeypatch.setattr(cv, "extract_cv_text_sandboxed", timeout)
    application_id, _, _ = upload(automation)
    with SessionLocal() as db:
        row = db.get(CVScreening, application_id)
        assert cv.queue_retry(db, row)
        db.commit()

    def cancelled(_):
        raise asyncio.CancelledError()

    monkeypatch.setattr(cv, "extract_cv_text_sandboxed", cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cv.process_application(application_id))
    with SessionLocal() as db:
        row = db.get(CVScreening, application_id)
        assert row.state == "failed" and row.error_code == "processing_interrupted"
        assert row.lease_until is None and row.dispatch_started_at is None
        assert cv.queue_retry(db, row)


@pytest.mark.parametrize("state,status,durable,message", [
    ("extracting", "submitted", False, "interrupted"),
    ("queued", "submitted", False, "interrupted"),
    ("accepted", "submitted", False, "recovery review"),
    ("accepted", "screening", False, "recovery review"),
    ("queued", "submitted", True, "Queued for CV processing"),
    ("extracting", "submitted", True, "Queued for recovery"),
    ("accepted", "screening", True, "Screening is in progress"),
])
def test_expired_extraction_is_visible_without_mutating_ledger(automation, monkeypatch, state, status, durable, message):
    monkeypatch.setattr(cv, "extract_cv_text_sandboxed", lambda _: SimpleNamespace(
        extraction_status="success", error_code=None, text="Skills: Python, FastAPI"))
    mocks(monkeypatch)
    application_id, headers, _ = upload(automation)
    with SessionLocal() as db:
        row = db.get(CVScreening, application_id)
        row.state = state
        if durable:
            row.generation_token = cv.QUEUE_PENDING
        db.get(JobApplication, application_id).status = status
        if state != "accepted":
            row.dispatch_started_at = None
        row.lease_until = utcnow() - timedelta(seconds=1)
        row.created_at = utcnow() - timedelta(minutes=10)
        db.commit()
    result = automation.get("/api/candidate/applications", headers=headers)
    assert result.status_code == 200
    assert message in result.json()[0]["processing_status"]
    with SessionLocal() as db:
        assert db.get(CVScreening, application_id).state == state

def test_preclaim_workflow_failure_is_authenticated_and_nonterminal(automation, monkeypatch):
    monkeypatch.setattr(cv, "extract_cv_text_sandboxed", lambda _: SimpleNamespace(
        extraction_status="success", error_code=None, text="Skills: Python, FastAPI"))
    mocks(monkeypatch)
    application_id, _, _ = upload(automation)
    with SessionLocal() as db:
        reference = {"dispatch_id": db.get(CVScreening, application_id).dispatch_id,
                     "failure_code": "workflow_envelope_failed"}
    url = f"/api/integrations/n8n/applications/{application_id}/screening/failure"
    auth = {"X-TalentForge-Callback-Secret": "synthetic-callback"}
    assert automation.post(url, json=reference).status_code == 401
    assert automation.post(url, headers=auth, json={**reference,"dispatch_id":str(uuid4())}).status_code == 409
    for _ in range(2):
        assert automation.post(url, headers=auth, json=reference).json() == {"recorded":True}
    with SessionLocal() as db:
        item=db.get(CVScreening, application_id)
        assert item.state=="failed" and item.error_code=="workflow_envelope_failed"
        assert item.workflow_claimed_at is None and item.decision is None and item.notification_state is None
        assert db.get(JobApplication,application_id).status=="submitted"
    claim=f"/api/integrations/n8n/applications/{application_id}/screening/claim"
    assert automation.post(claim,headers=auth,json={"dispatch_id":reference["dispatch_id"]}).json()["should_process"]
    assert automation.post(url,headers=auth,json=reference).status_code==409


def test_classification_failure_preserves_claim_and_blocks_decision(automation, monkeypatch):
    monkeypatch.setattr(cv, "extract_cv_text_sandboxed", lambda _: SimpleNamespace(
        extraction_status="success", error_code=None, text="Skills: Python, FastAPI"))
    mocks(monkeypatch)
    application_id, candidate_auth, _ = upload(automation)
    with SessionLocal() as db:
        reference = {"dispatch_id": db.get(CVScreening, application_id).dispatch_id}
    base = f"/api/integrations/n8n/applications/{application_id}"
    failure = {**reference, "failure_code": "workflow_classification_failed"}
    auth = {"X-TalentForge-Callback-Secret": "synthetic-callback"}
    assert automation.post(base+"/screening/failure", headers=auth, json=failure).status_code == 409
    assert automation.post(base+"/screening/claim", headers=auth, json=reference).json()["should_process"]
    for _ in range(2):
        assert automation.post(base+"/screening/failure", headers=auth, json=failure).json() == {"recorded":True}
    assert automation.post(base+"/decision", headers=auth, json={**reference,"classification":"spam"}).status_code == 409
    with SessionLocal() as db:
        item = db.get(CVScreening, application_id)
        assert item.state == "failed" and item.error_code == failure["failure_code"]
        assert item.workflow_claimed_at and item.decision is None and item.notification_state is None
    history = automation.get("/api/candidate/applications", headers=candidate_auth).json()
    assert "needs attention" in history[0]["processing_status"]

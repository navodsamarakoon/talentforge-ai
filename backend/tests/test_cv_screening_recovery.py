from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from talentforge import cv_automation as cv, cv_callbacks
from talentforge.database import SessionLocal
from talentforge.models import AuditEvent, CVScreening, JobApplication, JobOpening
from test_cv_automation import automation, mocks, upload


@pytest.mark.parametrize("error", ["workflow_classification_failed", "job_matching_unresolved"])
def test_explicit_claimed_retry_is_fenced_and_audited(automation, monkeypatch, error):
    calls = mocks(monkeypatch)
    monkeypatch.setattr(cv, "extract_cv_text_sandboxed", lambda _: SimpleNamespace(
        extraction_status="success", text="Technical Skills\nPython, SQL"
    ))
    monkeypatch.setattr(cv_callbacks, "match_job", lambda *args, **kwargs: {
        "decision": "unresolved", "failure_code": "mandatory_evidence_uncertain",
        "reason": "Fixture requires review",
    })
    app_id, headers, job = upload(automation)
    with SessionLocal() as db:
        old_dispatch = db.get(CVScreening, app_id).dispatch_id
        db.get(JobOpening, job["id"]).requirements = {"mandatory_skills": ["Python"]}
        db.commit()
    base = f"/api/integrations/n8n/applications/{app_id}"
    retry = f"/api/candidate/applications/{app_id}/screening/retry"
    callback_auth = {"X-TalentForge-Callback-Secret": "synthetic-callback"}
    old = {"dispatch_id": old_dispatch}
    assert automation.post(base + "/screening/claim", json=old, headers=callback_auth).json() == {"should_process": True}
    if error == "workflow_classification_failed":
        response = automation.post(base + "/screening/failure", json={**old, "failure_code": error}, headers=callback_auth)
        assert response.json() == {"recorded": True}
    else:
        response = automation.post(base + "/decision?acknowledge_unresolved=true", json={**old, "classification": "clean"}, headers=callback_auth)
        assert response.json() == {"status": "screening", "recoverable_error": "mandatory_evidence_uncertain"}
    assert automation.post(retry, headers=headers).status_code == 202
    assert len(calls) == 2
    assert calls[0][1]["idempotency_key"] != calls[1][1]["idempotency_key"]
    assert calls[0][1]["application_id"] == calls[1][1]["application_id"] == app_id
    with SessionLocal() as db:
        screening = db.get(CVScreening, app_id)
        current = {"dispatch_id": screening.dispatch_id}
        assert screening.dispatch_id != old_dispatch
        assert screening.extraction_attempts == 2 and screening.workflow_claimed_at is None
        assert screening.decision is screening.notification_state is screening.error_code is None
        assert db.get(JobApplication, app_id).status == "screening"
        audit = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == app_id,
                                                   AuditEvent.action.like("cv_retry_after_%")))
        assert audit.actor_id == db.get(JobApplication, app_id).candidate_user_id
        assert audit.action in {"cv_retry_after_classification_failure", "cv_retry_after_unresolved_matching"}
    for suffix, body in [
        ("/screening/claim", old),
        ("/screening/failure", {**old, "failure_code": "workflow_classification_failed"}),
        ("/decision", {**old, "classification": "clean"}),
        ("/notification/claim", old),
        ("/notification/receipt", {**old, "outcome": "sent"}),
    ]:
        assert automation.post(base + suffix, json=body, headers=callback_auth).status_code == 409
    assert automation.post(base + "/screening/claim", json=current, headers=callback_auth).json() == {"should_process": True}
    assert automation.post(base + "/screening/failure", json={**current, "failure_code": "workflow_classification_failed"},
                           headers=callback_auth).status_code == 200
    assert automation.post(retry, headers=headers).status_code == 409
    assert len(calls) == 2


def test_acknowledgement_from_old_dispatch_cannot_update_a_new_dispatch(automation, monkeypatch):
    replacement = str(uuid4())
    requests = []

    def send(request):
        import json

        body = json.loads(request.content)
        requests.append(body)
        with SessionLocal() as db:
            row = db.get(CVScreening, body["application_id"])
            assert row.state == "dispatching"
            row.dispatch_id = replacement
            db.commit()
        return httpx.Response(202, json={"accepted": True})

    client_type = cv.httpx.AsyncClient
    monkeypatch.setattr(cv.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(send), **kwargs
    ))
    monkeypatch.setattr(cv, "extract_cv_text_sandboxed", lambda _: SimpleNamespace(
        extraction_status="success", text="Skills: Python, SQL"
    ))
    app_id, _, _ = upload(automation)
    assert len(requests) == 1 and requests[0]["dispatch_id"] != replacement
    with SessionLocal() as db:
        row = db.get(CVScreening, app_id)
        assert row.dispatch_id == replacement and row.state == "dispatching"

import asyncio
import hashlib
import io
from types import SimpleNamespace

import httpx
import pymupdf
import pytest
from docx import Document
from pydantic import SecretStr

from talentforge.config import get_settings
from talentforge.models import JobApplication
from talentforge.n8n_integration import (
    EXPECTED_N8N_WEBHOOK_URL,
    WEBHOOK_SECRET_HEADER,
    N8NIntegrationResult,
    send_application_to_n8n,
)
from test_job_openings import candidate_auth, create_job, recruiter_auth


def create_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Synthetic Candidate\ncandidate@example.test\nPython")
    output = io.BytesIO()
    document.save(output)
    document.close()
    return output.getvalue()


def create_docx() -> bytes:
    document = Document()
    document.add_paragraph("Synthetic DOCX Candidate")
    document.add_paragraph("docx-candidate@example.test")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


@pytest.fixture(autouse=True)
def configured_webhook(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "cv_upload_dir", tmp_path / "private-cvs")
    monkeypatch.setattr(settings, "n8n_webhook_url", EXPECTED_N8N_WEBHOOK_URL)
    monkeypatch.setattr(settings, "n8n_webhook_secret", SecretStr("unit-test-webhook-secret"))
    return settings


def create_submitted_application(client, candidate_email: str, suffix: str, content: bytes):
    recruiter = recruiter_auth(client, "integration-recruiter@example.com", "n8n integration org")
    job = create_job(client, recruiter, title="Trusted Software Role")
    assert client.post(f"/api/jobs/{job['id']}/publish", headers=recruiter).status_code == 200
    candidate = candidate_auth(client, candidate_email)
    mime = (
        "application/pdf"
        if suffix == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    response = client.post(
        f"/api/candidate/jobs/{job['id']}/applications",
        headers=candidate,
        files={"cv": (f"candidate-upload.{suffix}", content, mime)},
    )
    assert response.status_code == 201, response.text
    return response.json()


class MockAsyncClient:
    instances: list["MockAsyncClient"] = []
    response_status = 202
    response_body = "malformed, intentionally ignored"
    exception: Exception | None = None

    def __init__(self, *, timeout: httpx.Timeout, follow_redirects: bool, trust_env: bool):
        self.timeout = timeout
        self.follow_redirects = follow_redirects
        self.trust_env = trust_env
        self.calls: list[dict] = []
        type(self).instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        del exc_type, exc_value, traceback
        return None

    async def post(self, url: str, *, json: dict, headers: dict):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if type(self).exception is not None:
            raise type(self).exception
        return SimpleNamespace(
            status_code=type(self).response_status,
            text=type(self).response_body,
        )


@pytest.fixture(autouse=True)
def mocked_http(monkeypatch):
    MockAsyncClient.instances.clear()
    MockAsyncClient.response_status = 202
    MockAsyncClient.response_body = "malformed, intentionally ignored"
    MockAsyncClient.exception = None
    monkeypatch.setattr("talentforge.n8n_integration.httpx.AsyncClient", MockAsyncClient)
    return MockAsyncClient


def test_sends_authenticated_payload_from_database_and_extracted_pdf(
    client,
    db_session,
):
    cv_bytes = create_pdf()
    uploaded = create_submitted_application(
        client,
        "trusted-candidate@example.com",
        "pdf",
        cv_bytes,
    )
    application = db_session.get(JobApplication, uploaded["id"])
    assert application is not None
    stored_hash = application.cv_sha256
    result = asyncio.run(send_application_to_n8n(db_session, application))

    assert result.delivery_status == "accepted"
    assert result.extraction_status == "success"
    mock_client = MockAsyncClient.instances[-1]
    assert mock_client.follow_redirects is False
    assert mock_client.trust_env is False
    assert mock_client.timeout.connect == 3.0
    assert mock_client.timeout.read == 20.0
    assert len(mock_client.calls) == 1
    request = mock_client.calls[0]
    assert request["url"] == EXPECTED_N8N_WEBHOOK_URL
    assert request["headers"][WEBHOOK_SECRET_HEADER] == "unit-test-webhook-secret"
    assert request["headers"]["Content-Type"] == "application/json"
    payload = request["json"]
    assert payload == {
        "event": "cv_application_submitted",
        "application_id": uploaded["id"],
        "job_opening_id": uploaded["job_opening_id"],
        "job_title": "Trusted Software Role",
        "candidate_id": application.candidate_user_id,
        "candidate_name": "Candidate",
        "candidate_email": "trusted-candidate@example.com",
        "cv_filename": "candidate-upload.pdf",
        "cv_sha256": stored_hash,
        "cv_text": "Synthetic Candidate\ncandidate@example.test\nPython",
        "extraction_status": "success",
    }
    assert stored_hash == hashlib.sha256(cv_bytes).hexdigest()


def test_sends_docx_text_through_existing_extraction_service(
    client,
    db_session,
):
    uploaded = create_submitted_application(
        client,
        "docx-candidate@example.com",
        "docx",
        create_docx(),
    )
    application = db_session.get(JobApplication, uploaded["id"])
    assert application is not None

    result = asyncio.run(send_application_to_n8n(db_session, uploaded["id"]))

    assert result.delivery_status == "accepted"
    assert result.extraction_status == "success"
    payload = MockAsyncClient.instances[-1].calls[0]["json"]
    assert payload["candidate_email"] == "docx-candidate@example.com"
    assert payload["cv_text"] == "Synthetic DOCX Candidate\n\ndocx-candidate@example.test"
    assert payload["cv_sha256"] == application.cv_sha256


@pytest.mark.parametrize(
    ("url", "expected_status"),
    [
        (None, "configuration_missing"),
        ("http://attacker.example/webhook/talentforge-cv-screening", "invalid_destination"),
        ("http://n8n:5678/webhook/talentforge-cv-screening?redirect=1", "invalid_destination"),
    ],
)
def test_missing_or_invalid_webhook_configuration_fails_safely(
    client,
    db_session,
    configured_webhook,
    monkeypatch,
    url,
    expected_status,
):
    uploaded = create_submitted_application(client, "config@example.com", "pdf", create_pdf())
    application = db_session.get(JobApplication, uploaded["id"])
    assert application is not None
    monkeypatch.setattr(configured_webhook, "n8n_webhook_url", url)

    result = asyncio.run(send_application_to_n8n(db_session, application))

    assert result.delivery_status == expected_status
    assert MockAsyncClient.instances == []
    assert "unit-test-webhook-secret" not in repr(result)


def test_missing_secret_fails_safely_without_sending(client, db_session, configured_webhook, monkeypatch):
    uploaded = create_submitted_application(client, "no-secret@example.com", "pdf", create_pdf())
    application = db_session.get(JobApplication, uploaded["id"])
    assert application is not None
    monkeypatch.setattr(configured_webhook, "n8n_webhook_secret", SecretStr(""))

    result = asyncio.run(send_application_to_n8n(db_session, application))

    assert result.delivery_status == "configuration_missing"
    assert MockAsyncClient.instances == []


@pytest.mark.parametrize(
    ("exception", "error_code"),
    [
        (httpx.ReadTimeout("private content"), "webhook_timeout"),
        (httpx.ConnectError("private content"), "webhook_connection_error"),
    ],
)
def test_timeout_and_connection_errors_do_not_leak_payload_or_secret(
    client,
    db_session,
    exception,
    error_code,
):
    uploaded = create_submitted_application(client, f"{error_code}@example.com", "pdf", create_pdf())
    application = db_session.get(JobApplication, uploaded["id"])
    assert application is not None
    MockAsyncClient.exception = exception

    result = asyncio.run(send_application_to_n8n(db_session, application))

    assert result.delivery_status == "request_failed"
    assert result.error_code == error_code
    assert "Synthetic Candidate" not in repr(result)
    assert "unit-test-webhook-secret" not in repr(result)
    assert "private content" not in repr(result)


def test_non_success_status_is_rejected_without_using_response_body(
    client,
    db_session,
):
    uploaded = create_submitted_application(client, "rejected@example.com", "pdf", create_pdf())
    application = db_session.get(JobApplication, uploaded["id"])
    assert application is not None
    MockAsyncClient.response_status = 500
    MockAsyncClient.response_body = "contains sensitive details"

    result = asyncio.run(send_application_to_n8n(db_session, application))

    assert result.delivery_status == "rejected"
    assert result.error_code == "webhook_non_success_status"
    assert "sensitive details" not in repr(result)


def test_2xx_malformed_response_is_treated_as_acceptance_not_screening_completion(
    client,
    db_session,
):
    uploaded = create_submitted_application(client, "malformed@example.com", "pdf", create_pdf())
    application = db_session.get(JobApplication, uploaded["id"])
    assert application is not None

    result = asyncio.run(send_application_to_n8n(db_session, application))

    assert result.delivery_status == "accepted"
    assert "screening" not in result.delivery_status


def test_extraction_failure_does_not_send_empty_text_as_success(
    client,
    db_session,
    monkeypatch,
):
    uploaded = create_submitted_application(client, "extract-failure@example.com", "pdf", create_pdf())
    application = db_session.get(JobApplication, uploaded["id"])
    assert application is not None
    monkeypatch.setattr(
        "talentforge.n8n_integration.extract_cv_text",
        lambda _: SimpleNamespace(
            extraction_status="extraction_error",
            error_code="invalid_document",
            text="",
        ),
    )

    result = asyncio.run(send_application_to_n8n(db_session, application))

    assert result.delivery_status == "extraction_failed"
    assert result.extraction_status == "extraction_error"
    assert MockAsyncClient.instances == []


def test_no_text_extraction_is_explicit_in_webhook_payload(
    client,
    db_session,
    monkeypatch,
):
    uploaded = create_submitted_application(client, "no-text@example.com", "pdf", create_pdf())
    application = db_session.get(JobApplication, uploaded["id"])
    assert application is not None
    monkeypatch.setattr(
        "talentforge.n8n_integration.extract_cv_text",
        lambda _: SimpleNamespace(
            extraction_status="no_text",
            error_code="no_extractable_text",
            text="",
        ),
    )

    result = asyncio.run(send_application_to_n8n(db_session, application))

    assert result.delivery_status == "accepted"
    assert result.extraction_status == "no_text"
    payload = MockAsyncClient.instances[-1].calls[0]["json"]
    assert payload["cv_text"] == ""
    assert payload["extraction_status"] == "no_text"


def test_missing_application_returns_internal_result(
    client,
    db_session,
):
    assert client.get("/api/health").status_code == 200
    result = asyncio.run(send_application_to_n8n(db_session, "missing-application"))

    assert result == N8NIntegrationResult(
        delivery_status="application_not_found",
        error_code="application_not_found",
    )
    assert MockAsyncClient.instances == []


def test_normal_application_upload_does_not_trigger_n8n(
    client,
):
    create_submitted_application(client, "no-auto-trigger@example.com", "pdf", create_pdf())

    assert MockAsyncClient.instances == []

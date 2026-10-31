import logging
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from talentforge.config import get_settings
from talentforge.cv_text_extraction import CVExtractionStatus, extract_cv_text
from talentforge.models import JobApplication, JobOpening, User

logger = logging.getLogger(__name__)

EXPECTED_N8N_WEBHOOK_URL = "http://n8n:5678/webhook/talentforge-cv-screening"
WEBHOOK_SECRET_HEADER = "X-TalentForge-Webhook-Secret"
CONNECT_TIMEOUT_SECONDS = 3.0
READ_TIMEOUT_SECONDS = 20.0

N8NDeliveryStatus = Literal[
    "accepted",
    "application_not_found",
    "configuration_missing",
    "invalid_destination",
    "extraction_failed",
    "request_failed",
    "rejected",
]


@dataclass(frozen=True)
class N8NIntegrationResult:
    delivery_status: N8NDeliveryStatus
    extraction_status: CVExtractionStatus | None = None
    error_code: str | None = None


def _validate_webhook_configuration() -> tuple[str, str] | N8NIntegrationResult:
    settings = get_settings()
    url = settings.n8n_webhook_url
    configured_secret = settings.n8n_webhook_secret
    secret = configured_secret.get_secret_value() if configured_secret is not None else ""

    if not url or not secret:
        return N8NIntegrationResult(
            delivery_status="configuration_missing",
            error_code="webhook_configuration_missing",
        )
    try:
        parsed_url = urlsplit(url)
        valid_destination = (
            parsed_url.scheme == "http"
            and parsed_url.hostname == "n8n"
            and parsed_url.port == 5678
            and parsed_url.path == "/webhook/talentforge-cv-screening"
            and parsed_url.username is None
            and parsed_url.password is None
            and not parsed_url.query
            and not parsed_url.fragment
        )
    except ValueError:
        valid_destination = False
    if not valid_destination or url != EXPECTED_N8N_WEBHOOK_URL:
        return N8NIntegrationResult(
            delivery_status="invalid_destination",
            error_code="webhook_destination_not_allowed",
        )
    return url, secret


def _application_payload(
    application: JobApplication,
    candidate: User,
    job: JobOpening,
    cv_text: str,
    extraction_status: CVExtractionStatus,
) -> dict[str, str]:
    return {
        "event": "cv_application_submitted",
        "application_id": application.id,
        "job_opening_id": application.job_opening_id,
        "job_title": job.title,
        "candidate_id": candidate.id,
        "candidate_name": candidate.full_name,
        "candidate_email": candidate.email,
        "cv_filename": application.original_cv_filename,
        "cv_sha256": application.cv_sha256,
        "cv_text": cv_text,
        "extraction_status": extraction_status,
    }


async def send_application_to_n8n(
    db: Session,
    application: JobApplication | str,
) -> N8NIntegrationResult:
    """Prepare and send one trusted application for screening; never called automatically."""
    application_id = application.id if isinstance(application, JobApplication) else application
    records = db.execute(
        select(JobApplication, User, JobOpening)
        .join(User, User.id == JobApplication.candidate_user_id)
        .join(JobOpening, JobOpening.id == JobApplication.job_opening_id)
        .where(JobApplication.id == application_id)
    ).one_or_none()
    if records is None:
        return N8NIntegrationResult(
            delivery_status="application_not_found",
            error_code="application_not_found",
        )
    application_record, candidate, job = records

    configuration = _validate_webhook_configuration()
    if isinstance(configuration, N8NIntegrationResult):
        return configuration
    webhook_url, webhook_secret = configuration

    extraction = extract_cv_text(application_record.cv_storage_ref)
    if extraction.extraction_status not in {"success", "no_text"}:
        return N8NIntegrationResult(
            delivery_status="extraction_failed",
            extraction_status=extraction.extraction_status,
            error_code=extraction.error_code or "cv_extraction_failed",
        )

    payload = _application_payload(
        application_record,
        candidate,
        job,
        extraction.text,
        extraction.extraction_status,
    )
    timeout = httpx.Timeout(
        timeout=READ_TIMEOUT_SECONDS,
        connect=CONNECT_TIMEOUT_SECONDS,
    )
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={
                    WEBHOOK_SECRET_HEADER: webhook_secret,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
    except httpx.TimeoutException:
        logger.warning("n8n CV webhook request timed out for application %s.", application_record.id)
        return N8NIntegrationResult(
            delivery_status="request_failed",
            extraction_status=extraction.extraction_status,
            error_code="webhook_timeout",
        )
    except httpx.RequestError as error:
        logger.warning(
            "n8n CV webhook request failed for application %s (%s).",
            application_record.id,
            type(error).__name__,
        )
        return N8NIntegrationResult(
            delivery_status="request_failed",
            extraction_status=extraction.extraction_status,
            error_code="webhook_connection_error",
        )

    if not 200 <= response.status_code < 300:
        logger.warning(
            "n8n CV webhook rejected application %s with HTTP %s.",
            application_record.id,
            response.status_code,
        )
        return N8NIntegrationResult(
            delivery_status="rejected",
            extraction_status=extraction.extraction_status,
            error_code="webhook_non_success_status",
        )

    # A 2xx only confirms webhook acceptance; the response body is untrusted and ignored.
    return N8NIntegrationResult(
        delivery_status="accepted",
        extraction_status=extraction.extraction_status,
    )

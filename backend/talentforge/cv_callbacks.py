"""Authenticated, idempotent gates for the EXISTING n8n screening canvas."""
import hmac
import logging
from datetime import datetime, time, timedelta, timezone
from time import perf_counter
import httpx
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from talentforge.api import Db, require_role
from talentforge.config import get_settings
from talentforge.models import AuditEvent, CVScreening, JobApplication, JobOpening, Organization, RecruiterSummary, User, utcnow
from talentforge.cv_automation import QUEUE_PENDING, QUEUE_PREFIX, process_application, queue_has_capacity, queue_retry
from talentforge.cv_automation import ScreeningFailure
from talentforge.job_matching import MandatoryRequirementsNotConfigured, match_job, materially_identical
from talentforge.schemas import JobRequirements

router = APIRouter()
REASONS = {"selected":"Your CV passed automated screening for this job. Interview invitations are handled separately.",
           "duplicate":"An identical or substantially identical CV was previously submitted for this job opening.",
           "empty":"The CV contains no usable text.", "spam":"The CV was classified as spam.",
           "suspicious":"The CV failed the security screening.",
           "meaningless":"The CV does not contain meaningful application information.",
           "job_mismatch":"The CV did not meet the job requirements."}


def authenticate(secret: Annotated[str | None, Header(alias="X-TalentForge-Callback-Secret")] = None):
    settings = get_settings()
    if not settings.cv_automation_enabled or not settings.n8n_callback_secret or not settings.n8n_callback_secret.get_secret_value():
        raise HTTPException(503, "CV automation callbacks are disabled.")
    if not secret or not hmac.compare_digest(secret.encode(), settings.n8n_callback_secret.get_secret_value().encode()):
        raise HTTPException(401, "Invalid callback authentication.")


class DispatchReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dispatch_id: UUID


class Decision(DispatchReference):
    classification: Literal["clean", "empty", "spam", "suspicious", "meaningless", "duplicate"]


class EnvelopeFailure(DispatchReference):
    failure_code: Literal["workflow_envelope_failed", "workflow_classification_failed"]


class Receipt(DispatchReference):
    outcome: Literal["sent", "failed", "unknown"]


class SummaryReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["sent", "failed", "unknown"]


def claim_daily_summaries(db, now):
    local = now.astimezone(timezone(timedelta(hours=5, minutes=30)))
    cutoff = datetime.combine(local.date(), time(6), tzinfo=local.tzinfo)
    if local < cutoff:
        cutoff -= timedelta(days=1)
    run_date = cutoff.date().isoformat()
    claimed = []
    # Lock organizations in consistent order. Each application belongs to one job.
    organizations = db.scalars(select(Organization).order_by(Organization.id).with_for_update()).all()
    for org in organizations:
        expired = db.scalars(select(RecruiterSummary).where(
            RecruiterSummary.organization_id == org.id,
            RecruiterSummary.state == "claimed",
            RecruiterSummary.claimed_at <= now - timedelta(hours=1),
        ).with_for_update())
        for batch in expired:
            batch.state = "unknown"
            batch.outcome_at = now
        if db.scalar(select(RecruiterSummary.id).where(
            RecruiterSummary.organization_id == org.id, RecruiterSummary.run_date == run_date,
        )):
            continue
        recipients = sorted(set(db.scalars(select(User.email).where(
            User.organization_id == org.id, User.role == "recruiter",
        )).all()))
        if not recipients:
            continue
        rows = db.execute(select(CVScreening, JobOpening, User)
            .join(JobApplication, JobApplication.id == CVScreening.application_id)
            .join(JobOpening, JobOpening.id == JobApplication.job_opening_id)
            .join(User, User.id == JobApplication.candidate_user_id)
            .where(JobOpening.organization_id == org.id, JobApplication.status == "selected",
                   CVScreening.decision == "selected", CVScreening.summary_id.is_(None))
            .order_by(CVScreening.application_id))
        candidates, screenings = [], []
        for screening, job, user in rows:
            match = screening.match_result or {}
            if (match.get("decision") != "pass" or match.get("application_id") != screening.application_id
                    or match.get("job_id") != job.id or match.get("organization_id") != org.id):
                continue
            try:
                matched_at = datetime.fromisoformat(match["matched_at"])
                if matched_at.tzinfo is None or matched_at >= cutoff:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            screenings.append(screening)
            candidates.append({"application_id": screening.application_id, "name": user.full_name,
                               "email": user.email, "job_title": job.title,
                               "match_score": match["match_score"], "reason": match["reason"],
                               "matched_skills": match.get("matched_skills", []),
                               "matched_at": matched_at.isoformat()})
        if not candidates:
            continue
        batch = RecruiterSummary(organization_id=org.id, run_date=run_date, state="pending",
                                 recipients=recipients, candidates=candidates)
        db.add(batch)
        db.flush()
        for screening in screenings:
            screening.summary_id = batch.id
    # The snapshot survives a crash between preparation and the send claim.
    db.commit()
    pending = db.execute(select(RecruiterSummary, Organization.name)
        .join(Organization, Organization.id == RecruiterSummary.organization_id)
        .where(RecruiterSummary.state == "pending", RecruiterSummary.run_date <= run_date)
        .order_by(RecruiterSummary.run_date, RecruiterSummary.id)
        .with_for_update(of=RecruiterSummary, skip_locked=True)).all()
    for batch, organization_name in pending:
        recipients = sorted(set(db.scalars(select(User.email).where(
            User.organization_id == batch.organization_id, User.role == "recruiter",
        )).all()))
        if not recipients:
            continue
        batch.recipients = recipients
        batch.state, batch.claimed_at = "claimed", now
        claimed.append({"summary_id": batch.id, "organization_name": organization_name,
                        "recipients": recipients, "candidates": batch.candidates, "run_date": batch.run_date})
    db.commit()
    return claimed


@router.post("/integrations/n8n/recruiter-summaries/claim", dependencies=[Depends(authenticate)])
def claim_summaries(db: Db):
    return {"summaries": claim_daily_summaries(db, utcnow())}


@router.post("/integrations/n8n/recruiter-summaries/{summary_id}/receipt", dependencies=[Depends(authenticate)])
def summary_receipt(summary_id: UUID, body: SummaryReceipt, db: Db):
    batch = db.scalar(select(RecruiterSummary).where(RecruiterSummary.id == str(summary_id)).with_for_update())
    if not batch:
        raise HTTPException(404, "Summary not found.")
    if batch.state != body.outcome:
        if batch.state not in {"claimed", "unknown"}:
            raise HTTPException(409, "Summary receipt conflicts with recorded outcome.")
        batch.state = body.outcome
        batch.outcome_at = utcnow()
        db.commit()
    return {"recorded": True}


def locked(db, application_id, reference):
    item = db.scalar(select(CVScreening).where(CVScreening.application_id == str(application_id)).with_for_update())
    if not item:
        raise HTTPException(404, "Screening not found.")
    if item.dispatch_id != str(reference.dispatch_id) or not item.dispatch_started_at:
        raise HTTPException(409, "Screening handoff does not match.")
    return item


def notification(db, item):
    app = db.get(JobApplication, item.application_id)
    candidate = db.get(User, app.candidate_user_id)
    job = db.get(JobOpening, app.job_opening_id)
    reason = REASONS[item.decision]
    if item.match_result:
        if item.decision == "selected":
            reason = f"{reason} {item.match_result['reason']}"
        elif item.decision == "job_mismatch":
            reason = item.match_result["reason"]
    return {"application_id":app.id,"dispatch_id":item.dispatch_id,"job_id":app.job_opening_id,
            "job_title":job.title,
            "candidate_name":candidate.full_name,"candidate_email":candidate.email,
            "status":app.status,"reason_code":item.decision,
            "reason":reason}


@router.post("/integrations/n8n/applications/{application_id}/screening/claim", dependencies=[Depends(authenticate)])
def claim(application_id: UUID, body: DispatchReference, db: Db):
    item = locked(db, application_id, body)
    if item.workflow_claimed_at:
        return {"should_process":False}
    if item.error_code == "webhook_delivery_uncertain":
        db.add(AuditEvent(action="webhook_delivery_uncertain_resolved_by_claim",
                          entity_type="cv_screening", entity_id=item.application_id))
        item.error_code = None
    item.workflow_claimed_at, item.state = utcnow(), "accepted"
    db.get(JobApplication, str(application_id)).status = "screening"
    db.commit()
    return {"should_process":True}


@router.post("/integrations/n8n/applications/{application_id}/screening/failure", dependencies=[Depends(authenticate)])
def record_envelope_failure(application_id: UUID, body: EnvelopeFailure, db: Db):
    item = locked(db, application_id, body)
    requires_claim = body.failure_code == "workflow_classification_failed"
    if bool(item.workflow_claimed_at) != requires_claim or item.decision or item.notification_state:
        raise HTTPException(409, "Failure callback does not match the screening state.")
    if item.error_code == "webhook_delivery_uncertain":
        db.add(AuditEvent(action="webhook_delivery_uncertain_superseded_by_failure",
                          entity_type="cv_screening", entity_id=item.application_id))
    item.state = "failed"
    item.error_code = body.failure_code
    db.commit()
    return {"recorded": True}


@router.post("/integrations/n8n/applications/{application_id}/decision", dependencies=[Depends(authenticate)])
def decide(application_id: UUID, body: Decision, db: Db):
    # Preserve stable per-job duplicate precedence regardless of callback order.
    app = db.get(JobApplication, str(application_id))
    if not app:
        raise HTTPException(404, "Application not found.")
    job = db.scalar(select(JobOpening).where(JobOpening.id == app.job_opening_id).with_for_update())
    item = locked(db, application_id, body)
    app = db.scalar(
        select(JobApplication).where(JobApplication.id == str(application_id))
        .with_for_update().execution_options(populate_existing=True)
    )
    if not item.workflow_claimed_at or item.error_code == "workflow_classification_failed":
        raise HTTPException(409, "Workflow must claim screening first.")
    if item.decision:
        expected = {"clean","duplicate"} if item.decision == "duplicate" else ({"clean"} if item.decision in {"selected", "job_mismatch"} else {item.decision})
        if body.classification not in expected:
            raise HTTPException(409, "A different final decision already exists.")
        return notification(db,item)
    code = body.classification
    if code == "clean":
        prior = db.scalar(select(JobApplication.id).where(
            JobApplication.job_opening_id == app.job_opening_id,
            JobApplication.cv_sha256 == app.cv_sha256, JobApplication.id != app.id,
            (JobApplication.submitted_at < app.submitted_at) | ((JobApplication.submitted_at == app.submitted_at) & (JobApplication.id < app.id)),
        ).limit(1))
        earlier = (JobApplication.submitted_at < app.submitted_at) | (
            (JobApplication.submitted_at == app.submitted_at) & (JobApplication.id < app.id)
        )
        if prior is None and item.cv_text:
            prior = next((True for previous in db.scalars(
                select(CVScreening.cv_text).join(JobApplication, CVScreening.application_id == JobApplication.id)
                .where(JobApplication.job_opening_id == job.id, earlier, CVScreening.cv_text.is_not(None))
            ) if materially_identical(item.cv_text, previous)), None)
        if prior is not None:
            code = "duplicate"
        else:
            if not item.cv_text:
                raise HTTPException(409, {"code": "insufficient_cv_evidence",
                                          "message": "CV evidence is required before matching."})
            started = perf_counter()
            try:
                result = match_job(JobRequirements.model_validate(job.requirements or {}), job.description,
                                   item.profile or {}, item.cv_text, application_id=app.id)
            except MandatoryRequirementsNotConfigured as error:
                item.error_code = "job_matching_requirements_missing"
                logging.getLogger(__name__).warning(
                    "job_match application_id=%s requirement_ids=none failure_code=%s elapsed_ms=%.2f exception_type=%s",
                    app.id, item.error_code, (perf_counter() - started) * 1000, type(error).__name__)
                db.commit()
                raise HTTPException(409, {"code": item.error_code,
                                          "message": "Vacancy has no mandatory requirements configured. A recruiter must configure them before matching."}) from None
            except (ScreeningFailure, httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
                item.error_code = "job_matching_unresolved"
                failure_code = ("insufficient_cv_evidence" if isinstance(error, ScreeningFailure)
                                else "invalid_job_matching_input" if isinstance(error, ValueError)
                                else "job_matching_internal_error")
                logging.getLogger(__name__).warning(
                    "job_match application_id=%s requirement_ids=unknown failure_code=%s elapsed_ms=%.2f exception_type=%s",
                    app.id, failure_code, (perf_counter() - started) * 1000, type(error).__name__)
                db.commit()
                raise HTTPException(409 if failure_code != "job_matching_internal_error" else 503,
                                    {"code": failure_code, "message": "Job matching could not be verified."}) from None
            item.match_result = {
                **result, "application_id": app.id, "job_id": job.id,
                "organization_id": job.organization_id, "matched_at": utcnow().isoformat(),
            }
            if result["decision"] == "unresolved":
                item.error_code = "job_matching_unresolved"
                db.commit()
                failure_code = result["failure_code"]
                status = 503 if failure_code in {"advisory_timeout", "advisory_unavailable"} else 409
                raise HTTPException(status, {"code": failure_code, "message": result["reason"]})
            if item.error_code in {"job_matching_unresolved", "job_matching_requirements_missing"}:
                item.error_code = None
            code = "selected" if result["decision"] == "pass" else "job_mismatch"
    item.decision, item.state = code, "accepted"
    app.status = "selected" if code == "selected" else "rejected"
    db.commit()
    return notification(db,item)


@router.post("/integrations/n8n/applications/{application_id}/notification/claim", dependencies=[Depends(authenticate)])
def claim_notification(application_id: UUID, body: DispatchReference, db: Db):
    item = locked(db, application_id, body)
    if not item.decision:
        raise HTTPException(409, "No final decision.")
    should_send = item.notification_state is None
    if should_send:
        item.notification_state = "claimed"
        db.commit()
    return {**notification(db,item), "should_send":should_send}


@router.post("/integrations/n8n/applications/{application_id}/notification/receipt", dependencies=[Depends(authenticate)])
def receipt(application_id: UUID, body: Receipt, db: Db):
    item = locked(db, application_id, body)
    if item.notification_state == body.outcome:
        return {"recorded":True}
    if item.notification_state != "claimed":
        raise HTTPException(409, "Notification receipt conflicts with its claim/outcome.")
    item.notification_state = body.outcome
    db.commit()
    return {"recorded":True}


@router.get("/candidate/applications/{application_id}/screening")
def screening_status(application_id: UUID, db: Db, candidate: Annotated[User, Depends(require_role("candidate"))]):
    app = db.get(JobApplication,str(application_id))
    if not app or app.candidate_user_id != candidate.id:
        raise HTTPException(404,"Application not found.")
    item = db.get(CVScreening,app.id) if get_settings().cv_automation_enabled else None
    if item is None:
        return {"state": "not_scheduled", "error_code": None}
    error_code = item.error_code
    # Older rows retain the original transport error. A stored claim proves receipt.
    if item.state == "accepted" and item.workflow_claimed_at and error_code == "webhook_delivery_uncertain":
        error_code = None
    return {"state": item.state, "error_code": error_code}


@router.post("/candidate/applications/{application_id}/screening/retry", status_code=202)
def retry_screening(application_id: UUID, background_tasks: BackgroundTasks, db: Db,
                    candidate: Annotated[User, Depends(require_role("candidate"))]):
    if not get_settings().cv_automation_enabled:
        raise HTTPException(503,"CV automation is disabled.")
    app = db.get(JobApplication,str(application_id))
    if not app or app.candidate_user_id != candidate.id:
        raise HTTPException(404,"Application not found.")
    durable = get_settings().cv_durable_queue_enabled
    if durable and not queue_has_capacity(db):
        raise HTTPException(503, "CV processing queue is full. Please try again later.",
                            headers={"Retry-After": "60"})
    item = db.scalar(select(CVScreening).where(CVScreening.application_id == app.id).with_for_update())
    if item and not durable and (item.generation_token or "").startswith(QUEUE_PREFIX):
        raise HTTPException(503, "The CV queue is unavailable. Please try again later.")
    previous_error = item.error_code if item else None
    if not item or not queue_retry(db,item):
        raise HTTPException(409,"Screening cannot be automatically retried; operator review is required.")
    if durable:
        if previous_error:
            db.add(AuditEvent(action=f"cv_retry_after_{previous_error}",
                              entity_type="cv_screening", entity_id=item.application_id))
        item.generation_token = QUEUE_PENDING
        item.error_code = None
    db.commit()
    if not durable:
        background_tasks.add_task(process_application, app.id)
    return {"scheduled":True}

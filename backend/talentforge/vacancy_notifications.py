"""Candidate consent and authenticated vacancy delivery callbacks."""
import hmac
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from talentforge.api import Db, require_role
from talentforge.config import VacancyOneShot, get_settings
from talentforge.models import User, utcnow
from talentforge.vacancy_outbox import authorize_submission, claim_delivery, claim_one_shot, dashboard_url, record_delivery

router = APIRouter()
Candidate = Annotated[User, Depends(require_role("candidate"))]


class Preference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


class ClaimOwnership(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_token: UUID


class Receipt(ClaimOwnership):
    outcome: Literal["sent", "transient", "failed", "unknown", "auth_failed"]


@router.get("/candidate/vacancy-notifications", response_model=Preference)
def get_preference(candidate: Candidate):
    return Preference(enabled=candidate.vacancy_notifications)


@router.put("/candidate/vacancy-notifications", response_model=Preference)
def set_preference(preference: Preference, candidate: Candidate, db: Db):
    candidate.vacancy_notifications = preference.enabled
    db.commit()
    return preference


def authenticate(secret: Annotated[str | None, Header(alias="X-TalentForge-Callback-Secret")] = None):
    configured = get_settings().n8n_callback_secret
    if not configured or not secret or not hmac.compare_digest(secret.encode(), configured.get_secret_value().encode()):
        raise HTTPException(401, "Invalid callback authentication.")


@router.post("/integrations/n8n/vacancy-notifications/claim", dependencies=[Depends(authenticate)])
def claim(db: Db):
    settings = get_settings()
    if not settings.vacancy_email_delivery_enabled:
        return {"deliveries": []}
    try:
        url = dashboard_url(settings.candidate_dashboard_base_url)
    except ValueError:
        raise HTTPException(503, "Candidate dashboard URL is not configured.") from None
    delivery = claim_delivery(db, url, utcnow())
    return {"deliveries": [{key: delivery[key] for key in ("id", "claim_token")}] if delivery else []}


@router.post("/integrations/n8n/vacancy-notifications/claim-one", dependencies=[Depends(authenticate)])
def claim_exact(body: VacancyOneShot, db: Db):
    settings = get_settings()
    if settings.vacancy_email_delivery_enabled or settings.vacancy_one_shot is None:
        raise HTTPException(403, "One-shot delivery is disabled.")
    if body != settings.vacancy_one_shot:
        raise HTTPException(403, "Delivery does not match the configured approval.")
    try:
        url = dashboard_url(settings.candidate_dashboard_base_url)
    except ValueError:
        raise HTTPException(503, "Candidate dashboard URL is not configured.") from None
    delivery = claim_one_shot(db, body, url, utcnow())
    if delivery is None:
        raise HTTPException(409, "The approved delivery cannot be claimed.")
    return {**delivery, "event_id": str(body.event_id), "vacancy_id": str(body.vacancy_id)}


@router.post("/integrations/n8n/vacancy-notifications/{delivery_id}/authorize-smtp", dependencies=[Depends(authenticate)])
def authorize_smtp(delivery_id: UUID, body: ClaimOwnership, db: Db):
    settings = get_settings()
    if not settings.vacancy_email_delivery_enabled or settings.vacancy_one_shot is not None:
        raise HTTPException(403, "General delivery is disabled.")
    try:
        url = dashboard_url(settings.candidate_dashboard_base_url)
    except ValueError:
        raise HTTPException(503, "Candidate dashboard URL is not configured.") from None
    message = authorize_submission(db, str(delivery_id), str(body.claim_token), url, utcnow())
    if message is None:
        raise HTTPException(409, "SMTP submission was not authorized.")
    return message


@router.post("/integrations/n8n/vacancy-notifications/{delivery_id}/receipt", dependencies=[Depends(authenticate)])
def receipt(delivery_id: UUID, body: Receipt, db: Db):
    if not record_delivery(db, str(delivery_id), str(body.claim_token), body.outcome, utcnow()):
        raise HTTPException(409, "Receipt does not match the active claim.")
    return {"recorded": True}

"""Transactional publication outbox and conservative SMTP delivery state."""
import logging
from datetime import timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select, text, update

from talentforge.config import get_settings
from talentforge.models import (
    JobOpening, Organization, User, VacancyNotificationDelivery as Delivery,
    VacancyNotificationEvent as Event, VacancySmtpBudget, utcnow,
)

SEND_INTERVAL = timedelta(minutes=5)
CLAIM_TIMEOUT = timedelta(minutes=15)
MAX_ATTEMPTS = 3
ONE_SHOT_CLAIM = "one_shot"
SUBMISSION_AUTHORIZED = "submission_authorized"
logger = logging.getLogger(__name__)


def lock_sender(db):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(715623, 1)"))


def sender_budget(db, now, *, reserve=False):
    """Check or reserve under the same transaction lock used by the claim."""
    day = now.astimezone(timezone.utc).date()
    budget = db.get(VacancySmtpBudget, 1)
    if budget and budget.auth_blocked_at is not None:
        logger.warning("vacancy_smtp_blocked reason=authentication")
        return False
    if budget and (budget.budget_day > day or (
        budget.budget_day == day and budget.reservations >= get_settings().vacancy_email_daily_cap
    )):
        logger.warning("vacancy_smtp_blocked reason=daily_cap")
        return False
    if reserve:
        if budget is None:
            db.add(VacancySmtpBudget(id=1, budget_day=day, reservations=1))
        elif budget.budget_day == day:
            budget.reservations += 1
        else:
            budget.budget_day, budget.reservations = day, 1
    return True


def recipient_for(user):
    if user is None or user.role != "candidate" or not user.vacancy_notifications:
        return None
    try:
        return validate_email(user.email, check_deliverability=False).normalized
    except (EmailNotValidError, TypeError):
        return None


def enqueue_publication(db, job):
    event = Event(vacancy_id=job.id, organization_id=job.organization_id, published_at=utcnow())
    db.add(event)
    db.flush()
    candidates = db.scalars(select(User).where(
        User.role == "candidate", User.vacancy_notifications.is_(True),
        User.created_at <= event.published_at,
    )).all()
    for candidate in candidates:
        if recipient := recipient_for(candidate):
            db.add(Delivery(event_id=event.id, candidate_id=candidate.id,
                            recipient=recipient, available_at=event.published_at))


def dashboard_url(base):
    parsed = urlsplit(base or "")
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))):
        raise ValueError("Configure a trusted candidate dashboard origin.")
    return base.rstrip("/") + "/candidate"


def delivery_message(row, candidate, job, org, url):
    title = " ".join(job.title.split())
    return {
        "id": row.id, "claim_token": row.claim_token, "recipient": row.recipient,
        "subject": f"New Job Opportunity on TalentForge AI — {title}",
        "text": (
            f"Hi {candidate.full_name},\n\nA new job opportunity has just been published on TalentForge AI!\n\n"
            f"Job Title: {title}\nCompany: {org.name}\n\n"
            f"View job details and apply from your candidate dashboard:\n{url}\n\n"
            f"Manage vacancy email preferences from the same dashboard.\n\nBest regards,\nTalentForge AI Team"
        ),
    }


def claim_one_shot(db, approval, url, now):
    lock_sender(db)
    row = db.get(Delivery, str(approval.delivery_id), with_for_update=True)
    if (
        row is None or row.recipient != approval.recipient or row.event_id != str(approval.event_id)
        or row.state != "pending" or row.attempts != 0
        or any(value is not None for value in (row.sent_at, row.outcome, row.claim_token, row.last_attempt_at))
    ):
        return None
    event = db.get(Event, row.event_id)
    if event is None or event.vacancy_id != str(approval.vacancy_id):
        return None
    job = db.get(JobOpening, event.vacancy_id, with_for_update=True)
    candidate = db.get(User, row.candidate_id, with_for_update=True)
    org = db.get(Organization, event.organization_id)
    if (
        job is None or org is None or job.organization_id != org.id or job.status != "published"
        or not org.name.strip() or recipient_for(candidate) != row.recipient
    ):
        return None
    other_delivery = db.scalar(select(Delivery.id).where(
        Delivery.id != row.id, Delivery.state.in_(("pending", "claimed", "delivery_unknown")),
    ).limit(1))
    if other_delivery is not None:
        return None
    if not sender_budget(db, now, reserve=True):
        return None
    row.state, row.attempts, row.outcome = "claimed", 1, ONE_SHOT_CLAIM
    row.last_attempt_at, row.claim_token = now, str(uuid4())
    message = delivery_message(row, candidate, job, org, url)
    db.commit()
    return message


def claim_delivery(db, url, now):
    lock_sender(db)
    expired = db.execute(update(Delivery).where(
        Delivery.state == "claimed", Delivery.last_attempt_at <= now - CLAIM_TIMEOUT,
    ).values(state="delivery_unknown", outcome="unknown").returning(Delivery.id)).scalars().all()
    for delivery_id in expired:
        logger.warning("vacancy_delivery_uncertain delivery_id=%s reason=expired_claim", delivery_id)
    if not sender_budget(db, now):
        db.commit()
        return None
    recent = db.scalar(select(func.count()).select_from(Delivery).where(
        (Delivery.last_attempt_at > now - SEND_INTERVAL) | (Delivery.state == "claimed"),
    ))
    if recent:
        db.commit()
        return None
    rows = db.scalars(select(Delivery).where(
        Delivery.state == "pending", Delivery.available_at <= now,
    ).order_by(Delivery.available_at, Delivery.id).limit(20).with_for_update(skip_locked=True)).all()
    for row in rows:
        event = db.get(Event, row.event_id)
        job = db.get(JobOpening, event.vacancy_id)
        org = db.get(Organization, event.organization_id)
        candidate = db.get(User, row.candidate_id, with_for_update=True)
        recipient = recipient_for(candidate)
        if (not recipient or recipient != row.recipient or job.status != "published"
                or job.organization_id != org.id or not org.name.strip()):
            row.state, row.outcome = "skipped", "ineligible"
            continue
        row.state = "claimed"
        row.attempts += 1
        row.last_attempt_at, row.claim_token, row.outcome = now, str(uuid4()), None
        message = delivery_message(row, candidate, job, org, url)
        db.commit()
        return message
    db.commit()
    return None


def authorize_submission(db, delivery_id, claim_token, url, now):
    """Issue the general workflow's message once, after a final consent check."""
    lock_sender(db)
    row = db.scalar(select(Delivery).where(
        Delivery.id == delivery_id, Delivery.claim_token == claim_token,
        Delivery.state == "claimed", Delivery.outcome.is_(None),
        Delivery.last_attempt_at > now - CLAIM_TIMEOUT,
    ).with_for_update())
    if row is None:
        return None
    event = db.get(Event, row.event_id)
    job = db.get(JobOpening, event.vacancy_id)
    org = db.get(Organization, event.organization_id)
    candidate = db.get(User, row.candidate_id, with_for_update=True)
    if (recipient_for(candidate) != row.recipient or job.status != "published"
            or job.organization_id != org.id or not org.name.strip()):
        row.state, row.outcome = "skipped", "ineligible"
        db.commit()
        return None
    if not sender_budget(db, now, reserve=True):
        row.state, row.claim_token = "pending", None
        row.attempts -= 1
        db.commit()
        return None
    row.outcome = SUBMISSION_AUTHORIZED
    message = delivery_message(row, candidate, job, org, url)
    db.commit()
    return message


def record_delivery(db, delivery_id, claim_token, outcome, now):
    if outcome == "auth_failed":
        lock_sender(db)
    row = db.get(Delivery, delivery_id, with_for_update=True)
    if row is None or row.claim_token != claim_token:
        return False
    if row.outcome == outcome:
        return True
    authorized = row.state == "claimed" and row.outcome in (ONE_SHOT_CLAIM, SUBMISSION_AUTHORIZED)
    late_auth_failure = outcome == "auth_failed" and row.state == "delivery_unknown"
    if not authorized and not late_auth_failure:
        return False
    if row.outcome == ONE_SHOT_CLAIM and outcome == "transient":
        outcome = "failed"
    row.outcome = outcome
    if outcome == "sent":
        row.state, row.sent_at = "sent", now
    elif outcome == "transient" and row.attempts < MAX_ATTEMPTS:
        row.state = "pending"
        row.available_at = now + SEND_INTERVAL * (2 ** (row.attempts - 1))
    elif outcome == "unknown":
        row.state = "delivery_unknown"
    else:
        row.state = "failed"
    if outcome == "auth_failed":
        budget = db.get(VacancySmtpBudget, 1)
        if budget is None:
            budget = VacancySmtpBudget(id=1, budget_day=now.astimezone(timezone.utc).date(), reservations=0)
            db.add(budget)
        if budget.auth_blocked_at is None:
            budget.auth_blocked_at = now
    db.commit()
    if row.state in ("failed", "delivery_unknown"):
        logger.warning("vacancy_delivery_result delivery_id=%s outcome=%s", delivery_id, outcome)
    return True

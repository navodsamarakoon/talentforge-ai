from datetime import datetime, timedelta, timezone

import pytest

from talentforge import cv_callbacks
from talentforge.database import Base, engine
from talentforge.models import CVScreening, JobApplication, JobOpening, Organization, RecruiterSummary, User


def seed_selection(db, name, matched_at):
    org = db.query(Organization).filter_by(name="Midnight fixture").one_or_none()
    if org is None:
        org = Organization(name="Midnight fixture")
        db.add(org)
        db.flush()
        db.add(User(email="recruiter@example.com", full_name="Fixture Recruiter",
                    password_hash="unused", role="recruiter", organization_id=org.id))
    job = JobOpening(organization_id=org.id, title="Fixture Role", description="Fixture",
                     employment_type="full-time", location="Colombo", status="published")
    candidate = User(email=f"{name}@example.com", full_name=name, password_hash="unused", role="candidate")
    db.add_all([job, candidate])
    db.flush()
    app = JobApplication(job_opening_id=job.id, candidate_user_id=candidate.id,
                         original_cv_filename="fixture.pdf", cv_mime_type="application/pdf",
                         cv_sha256="a" * 64, cv_storage_ref=f"{name}.pdf", status="selected")
    db.add(app)
    db.flush()
    db.add(CVScreening(application_id=app.id, decision="selected", match_result={
        "decision": "pass", "application_id": app.id, "job_id": job.id, "organization_id": org.id,
        "matched_at": matched_at.isoformat(), "match_score": 100, "reason": "Fixture match",
    }))
    db.commit()
    return app.id, org.id


@pytest.fixture
def summary_db():
    from talentforge.database import SessionLocal

    Base.metadata.create_all(bind=engine)
    try:
        with SessionLocal() as db:
            yield db
    finally:
        Base.metadata.drop_all(bind=engine)


def test_colombo_midnight_claims_previous_day_once(summary_db, monkeypatch):
    midnight = datetime(2026, 11, 10, 18, 30, tzinfo=timezone.utc)
    tick = timedelta(microseconds=1)
    before, _ = seed_selection(summary_db, "Before", midnight - tick)
    at, _ = seed_selection(summary_db, "At", midnight)
    after, _ = seed_selection(summary_db, "After", midnight + tick)

    def claim(now):
        return cv_callbacks.claim_daily_summaries(summary_db, now)

    assert claim(midnight - tick) == []
    batch, = claim(midnight)
    assert batch["run_date"] == "2026-11-11"
    assert [c["application_id"] for c in batch["candidates"]] == [before]
    assert batch["recipients"] == ["recruiter@example.com"]
    assert claim(midnight + tick) == []
    from uuid import UUID

    monkeypatch.setattr(cv_callbacks, "utcnow", lambda: midnight)
    receipt = cv_callbacks.SummaryReceipt(outcome="sent")
    for _ in range(2):
        assert cv_callbacks.summary_receipt(UUID(batch["summary_id"]), receipt, summary_db) == {"recorded": True}
    assert claim(midnight + timedelta(hours=1)) == []
    following, = claim(midnight + timedelta(days=1))
    assert {c["application_id"] for c in following["candidates"]} == {at, after}


def test_existing_sent_run_date_is_not_reclaimed(summary_db):
    midnight = datetime(2026, 11, 10, 18, 30, tzinfo=timezone.utc)
    app_id, org_id = seed_selection(summary_db, "Deferred", midnight - timedelta(minutes=1))
    historical = RecruiterSummary(organization_id=org_id, run_date="2026-11-11", state="sent",
                                  recipients=["recruiter@example.com"], candidates=[])
    summary_db.add(historical)
    summary_db.commit()
    assert cv_callbacks.claim_daily_summaries(summary_db, midnight) == []
    assert historical.state == "sent"
    assert summary_db.get(CVScreening, app_id).summary_id is None
    batch, = cv_callbacks.claim_daily_summaries(summary_db, midnight + timedelta(days=1))
    assert [c["application_id"] for c in batch["candidates"]] == [app_id]

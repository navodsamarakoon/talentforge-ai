"""Exercise migration and concurrent claims on a fresh, disposable PostgreSQL instance."""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import inspect, select, text

from talentforge.api import publish_job_opening
from talentforge.config import VacancyOneShot, get_settings
from talentforge.database import SessionLocal, engine
from talentforge.models import JobOpening, Organization, User, VacancyNotificationDelivery, VacancyNotificationEvent, utcnow
from talentforge.vacancy_outbox import authorize_submission, claim_delivery, claim_one_shot, enqueue_publication, record_delivery


assert os.environ.get("VACANCY_DISPOSABLE_TESTS") == "1"
assert engine.url.host == "vacancy-verify-db" and engine.url.database == "vacancy_verify"
assert not inspect(engine).get_table_names()
alembic = [sys.executable, "-m", "alembic", "-c", str(Path(__file__).resolve().parents[1] / "alembic.ini"), "upgrade"]
subprocess.run([*alembic, "0008_recruiter_summaries"], check=True, timeout=60)
with engine.begin() as connection:
    # Revision 0001 uses live ORM metadata. Reproduce a database initialized
    # before vacancy preferences existed, inside this disposable fixture only.
    connection.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS vacancy_notifications"))
    connection.execute(text("""
        INSERT INTO users (id,email,full_name,password_hash,role,token_version,created_at)
        VALUES ('existing','existing@example.com','Existing Fixture','unused','candidate',0,now())
    """))
subprocess.run([*alembic, "0009_vacancy_notifications"], check=True, timeout=60)
subprocess.run([*alembic, "0010_vacancy_smtp_budget"], check=True, timeout=60)

with SessionLocal() as db:
    assert db.get(User, "existing").vacancy_notifications is False
    org = Organization(name="Synthetic Organization")
    db.add_all([org, User(email="candidate@example.com", full_name="Synthetic Candidate", role="candidate",
                         password_hash="unused", vacancy_notifications=True)])
    db.flush()
    vacancy = JobOpening(organization_id=org.id, title="Synthetic Job", description="Test",
                         employment_type="full-time", location="Colombo", status="published")
    db.add(vacancy)
    db.flush()
    enqueue_publication(db, vacancy)
    db.commit()
    assert db.scalars(select(VacancyNotificationDelivery.recipient)).all() == ["candidate@example.com"]

now = utcnow()
barrier = Barrier(4)


def claim(_):
    with SessionLocal() as db:
        barrier.wait(timeout=10)
        return claim_delivery(db, "https://jobs.example.com/candidate", now)


with ThreadPoolExecutor(max_workers=4) as pool:
    delivery, = [result for result in pool.map(claim, range(4)) if result]
with SessionLocal() as db:
    assert authorize_submission(db, delivery["id"], delivery["claim_token"], "https://jobs.example.com/candidate", now)
    assert record_delivery(db, delivery["id"], delivery["claim_token"], "sent", now)
    assert record_delivery(db, delivery["id"], delivery["claim_token"], "sent", now)
    assert claim_delivery(db, "https://jobs.example.com/candidate", now + timedelta(days=1)) is None
    assert db.get(VacancyNotificationDelivery, delivery["id"]).attempts == 1

print("Additive PostgreSQL upgrade, historical opt-out, four concurrent claims and receipt replay passed.")

with SessionLocal() as db:
    org = db.scalar(select(Organization))
    vacancy = JobOpening(organization_id=org.id, title="One-shot vacancy", description="Test",
                         employment_type="full-time", location="Colombo", status="published")
    db.add(vacancy)
    db.flush()
    enqueue_publication(db, vacancy)
    db.commit()
    row = db.scalar(select(VacancyNotificationDelivery).where(VacancyNotificationDelivery.state == "pending"))
    approval = VacancyOneShot(delivery_id=row.id, recipient=row.recipient, event_id=row.event_id, vacancy_id=vacancy.id)

barrier = Barrier(4)


def exact_claim(_):
    with SessionLocal() as db:
        barrier.wait(timeout=10)
        return claim_one_shot(db, approval, "http://127.0.0.1:18080/candidate", utcnow())


with ThreadPoolExecutor(max_workers=4) as pool:
    exact, = [result for result in pool.map(exact_claim, range(4)) if result]
with SessionLocal() as db:
    assert record_delivery(db, exact["id"], exact["claim_token"], "unknown", utcnow())
    assert claim_one_shot(db, approval, "http://127.0.0.1:18080/candidate", utcnow()) is None
    assert claim_delivery(db, "http://127.0.0.1:18080/candidate", utcnow() + timedelta(days=1)) is None
print("Four concurrent exact claims returned one owner, and an uncertain receipt prevented any reclaim.")

with SessionLocal() as db:
    org = db.scalar(select(Organization))
    recruiter = User(email="owner@example.com", full_name="Fixture Recruiter", role="recruiter",
                     password_hash="unused", organization_id=org.id)
    draft = JobOpening(organization_id=org.id, title="Concurrent publication", description="Test",
                       employment_type="full-time", location="Colombo", status="draft")
    db.add_all([draft, recruiter, *[
        User(email=f"fanout-{index}@example.com", full_name="Fixture", role="candidate",
             password_hash="unused", vacancy_notifications=True) for index in range(49)
    ]])
    db.commit()
    draft_id, recruiter_id = draft.id, recruiter.id

barrier = Barrier(4)


def concurrent_publish(_):
    with SessionLocal() as db:
        recruiter = db.get(User, recruiter_id)
        barrier.wait(timeout=10)
        try:
            publish_job_opening(draft_id, db, recruiter)
        except HTTPException as exc:
            return exc.status_code
        return 200


with ThreadPoolExecutor(max_workers=4) as pool:
    assert sorted(pool.map(concurrent_publish, range(4))) == [200, 409, 409, 409]

url = "https://jobs.example.com/candidate"
now = (utcnow() + timedelta(days=1)).replace(hour=12)
get_settings().vacancy_email_daily_cap = 1
with SessionLocal() as db:
    event, = db.scalars(select(VacancyNotificationEvent).where(VacancyNotificationEvent.vacancy_id == draft_id))
    rows = db.scalars(select(VacancyNotificationDelivery).where(VacancyNotificationDelivery.event_id == event.id)).all()
    assert len({row.candidate_id for row in rows}) == len(rows) == 50
    message = claim_delivery(db, url, now)
    assert claim_delivery(db, url, now + timedelta(minutes=6)) is None

barrier = Barrier(4)


def concurrent_authorize(_):
    with SessionLocal() as db:
        barrier.wait(timeout=10)
        return authorize_submission(db, message["id"], message["claim_token"], url, now)


with ThreadPoolExecutor(max_workers=4) as pool:
    assert len([result for result in pool.map(concurrent_authorize, range(4)) if result]) == 1

with SessionLocal() as db:
    assert claim_delivery(db, url, now + timedelta(minutes=16)) is None
    assert db.get(VacancyNotificationDelivery, message["id"]).state == "delivery_unknown"
    now += timedelta(days=1)
    next_message = claim_delivery(db, url, now)
    assert next_message and next_message["id"] != message["id"]
    assert db.get(VacancyNotificationDelivery, message["id"]).state == "delivery_unknown"
    assert authorize_submission(db, message["id"], message["claim_token"], url, now) is None
    assert not record_delivery(db, message["id"], next_message["claim_token"], "sent", now)
    assert authorize_submission(db, next_message["id"], next_message["claim_token"], url, now)
    assert record_delivery(db, next_message["id"], next_message["claim_token"], "auth_failed", now)
    assert claim_delivery(db, url, now + timedelta(days=1)) is None

print("Four concurrent publishes created one event with 50 unique deliveries. Four SMTP authorization requests issued one message. An active claim blocked another send and an expired claim was quarantined.")

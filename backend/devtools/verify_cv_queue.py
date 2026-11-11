"""Exercise queue ownership and crash recovery on disposable PostgreSQL."""
import asyncio
import os
import subprocess
import sys
import time
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select

from talentforge import cv_automation as cv
from talentforge.config import get_settings
from talentforge.cv_worker import run_once
from talentforge.database import SessionLocal
from talentforge.models import AuditEvent, CVScreening, JobApplication, JobOpening, Organization, User, utcnow

assert os.environ.get("CV_DISPOSABLE_TESTS") == "1"
assert get_settings().database_url == "postgresql+psycopg://verify:disposable-synthetic-only@verify-db:5432/verify"
get_settings().cv_automation_enabled = True
get_settings().n8n_auto_dispatch_enabled = False
get_settings().cv_queue_capacity = 3

cv.extract_cv_text_sandboxed = lambda _: SimpleNamespace(
    extraction_status="success", text="Skills: Python", error_code=None)


async def profile(_):
    if len(sys.argv) > 1:
        await asyncio.sleep(120)
    return cv.CVProfile(
        name=None, email=None, skills=["Python"], education=[], experience=[], projects=[],
        certifications=[], languages=[], summary=None, other_information=[])


cv.extract_profile = profile
if len(sys.argv) > 1:
    asyncio.run(run_once(1))
    sys.exit()

subprocess.run([sys.executable, "-m", "alembic", "-c", "/src/backend/alembic.ini",
                "upgrade", "head"], check=True)
with SessionLocal() as db:
    org = Organization(name="Fictional Queue")
    db.add(org)
    db.flush()
    job = JobOpening(organization_id=org.id, title="Fictional Engineer", description="Fixture",
                     employment_type="full-time", location="Fixture", status="published")
    db.add(job)
    db.flush()
    ids = []
    for index in range(4):
        candidate = User(email=f"queue-{index}@example.com", full_name="Fictional Candidate",
                         password_hash="unused", role="candidate")
        db.add(candidate)
        db.flush()
        app = JobApplication(job_opening_id=job.id, candidate_user_id=candidate.id,
                             original_cv_filename="fixture.pdf", cv_mime_type="application/pdf",
                             cv_sha256="0" * 64, cv_storage_ref=f"fixture-{index}.pdf", status="submitted")
        db.add(app)
        db.flush()
        db.add(CVScreening(application_id=app.id, generation_token=cv.QUEUE_PENDING if index else None))
        ids.append(app.id)
    db.commit()
    assert not cv.queue_has_capacity(db)

child = subprocess.Popen([sys.executable, __file__, "interrupt"])
try:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            item = db.get(CVScreening, ids[1])
            if item.state == "extracting":
                item.lease_until = utcnow() - timedelta(seconds=1)
                db.commit()
                break
        time.sleep(0.2)
    else:
        raise AssertionError("FIFO worker did not claim the first durable row")
    assert not asyncio.run(run_once(1)), "Duplicate slot owner"
    assert not asyncio.run(run_once(2)), "Expired lease bypassed live application lock"
finally:
    child.kill()
    child.wait(timeout=15)

for position, app_id in enumerate(ids[1:], 1):
    assert asyncio.run(run_once(1))
    with SessionLocal() as db:
        item = db.get(CVScreening, app_id)
        assert item.state == "ready" and item.extraction_attempts == (2 if position == 1 else 1)
        assert not item.dispatch_started_at
        assert all(db.get(CVScreening, later).state == "queued" for later in ids[position + 1:])
        assert db.get(CVScreening, ids[0]).state == "queued"
with SessionLocal() as db:
    assert db.scalar(select(AuditEvent.action).where(AuditEvent.entity_id == ids[1])) == "cv_extraction_lease_expired"
assert not asyncio.run(run_once(1))
print("PASS PostgreSQL capacity, FIFO, live ownership, killed worker recovery, legacy isolation")

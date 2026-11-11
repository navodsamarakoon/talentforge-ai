"""Seed synthetic records and serve the loopback-only demo backend."""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import uvicorn
from fastapi import Request, HTTPException
from sqlalchemy import select

from talentforge import cv_callbacks
from talentforge.database import SessionLocal
from talentforge.main import app
from talentforge.models import JobOpening, Organization, User
from talentforge.security import hash_password

assert os.environ["TALENTFORGE_LOCAL_DEMO"] == "1"
assert os.environ["DATABASE_URL"].endswith("@db:5432/demo")
subprocess.run([sys.executable, "-m", "alembic", "-c", "/src/backend/alembic.ini",
                "upgrade", "0008_recruiter_summaries"], check=True, timeout=90)

with SessionLocal() as db:
    if not db.scalar(select(User.id).where(User.email == "recruiter@demo.example.com")):
        org = Organization(name="Harborline Software Demo")
        db.add(org)
        db.flush()
        password = hash_password(os.environ["DEMO_ACCOUNT_PASSWORD"])
        db.add_all([
            User(email="recruiter@demo.example.com", full_name="Morgan Demo", password_hash=password,
                 role="recruiter", organization_id=org.id),
            User(email="candidate@demo.example.com", full_name="Alex Demo", password_hash=password, role="candidate"),
        ])
        for title, skills, description in [
            ("Python Backend Engineer", ["Python"], "Build Python APIs and maintain PostgreSQL-backed services."),
            ("Rust Systems Engineer", ["Rust"], "Build reliable Rust services and maintain performance tooling."),
        ]:
            db.add(JobOpening(organization_id=org.id, title=title, description=description,
                              employment_type="full-time", location="Colombo", status="published",
                              requirements={"mandatory_skills":skills, "minimum_match_score":70}))
        db.commit()

real_clock = cv_callbacks.utcnow
clock = {"until": None}

def demo_clock():
    now = real_clock()
    if clock["until"] and now < clock["until"]:
        return now + timedelta(days=1)
    return now

cv_callbacks.utcnow = demo_clock

@app.post("/__demo/summary-clock")
def summary_clock(request: Request):
    if request.client.host != "127.0.0.1":
        raise HTTPException(403)
    clock["until"] = datetime.now(timezone.utc) + timedelta(seconds=180)
    return {"advanced": True}

uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)

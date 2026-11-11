"""Exercise the persistent local demo with synthetic data and the local inbox."""
import os
import sys
import time

import httpx
import pymupdf
from sqlalchemy import select

from talentforge.database import SessionLocal
from talentforge.models import CVScreening, JobApplication, RecruiterSummary, User

assert os.environ["TALENTFORGE_LOCAL_DEMO"] == "1"
assert os.environ["DATABASE_URL"].endswith("@db:5432/demo")
backend = "http://127.0.0.1:8000"
n8n = "http://n8n:5678"
mail = "http://mail:8025"

def inbox(client):
    response = client.get(mail + "/api/v1/messages")
    response.raise_for_status()
    return response.json()

def wait_for(check, seconds=540):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        time.sleep(1)
    raise AssertionError("Timed out waiting for persisted demo outcome")

with httpx.Client(timeout=15, trust_env=False) as client:
    initial = inbox(client)["total"]
    if sys.argv[1] == "summary":
        client.post(backend + "/__demo/summary-clock").raise_for_status()
        client.post(n8n + "/webhook/talentforge-demo-summary", headers={
            "X-TalentForge-Webhook-Secret": os.environ["N8N_WEBHOOK_SECRET"],
        }).raise_for_status()
        def summary():
            with SessionLocal() as db:
                return db.scalar(select(RecruiterSummary).where(RecruiterSummary.state == "sent")
                                 .order_by(RecruiterSummary.outcome_at.desc()))
        batch = wait_for(summary, 180)
        assert batch.recipients == ["recruiter@demo.example.com"]
        assert inbox(client)["total"] > initial
        print(f"PASS recruiter summary {batch.id}, state {batch.state}, candidates {len(batch.candidates)}")
    else:
        wait_for(lambda: client.post(n8n + "/webhook/talentforge-recruitment-automation", json={}).status_code == 403, 60)
        recruiter = client.post(backend + "/api/auth/login", json={
            "email": "recruiter@demo.example.com", "password": os.environ["DEMO_ACCOUNT_PASSWORD"],
        })
        recruiter.raise_for_status()
        recruiter_auth = {"Authorization": "Bearer " + recruiter.json()["access_token"]}
        owned = client.get(backend + "/api/jobs", headers=recruiter_auth)
        owned.raise_for_status()
        assert {job["title"] for job in owned.json()} == {"Python Backend Engineer", "Rust Systems Engineer"}
        print("PASS recruiter login and two seeded vacancies", flush=True)
        login = client.post(backend + "/api/auth/login", json={
            "email": "candidate@demo.example.com", "password": os.environ["DEMO_ACCOUNT_PASSWORD"],
        })
        login.raise_for_status()
        auth = {"Authorization": "Bearer " + login.json()["access_token"]}
        vacancies = client.get(backend + "/api/candidate/jobs", headers=auth).json()
        job = next(item for item in vacancies if item["title"] == "Python Backend Engineer")
        with pymupdf.open() as doc:
            doc.new_page().insert_text((45, 72), "\n".join([
                "Alex Demo", "candidate@demo.example.com", "Skills: Python, PostgreSQL, Docker, pytest",
                "Education: BSc in Computer Science",
                "Built Python REST APIs and PostgreSQL integrations for a fictional inventory service.",
                "Maintained database migrations and wrote Python integration tests.",
                "Designed a service health dashboard and optimized database queries.",
            ]))
            pdf = doc.tobytes()
        def upload_once(email, headers, filename):
            with SessionLocal() as db:
                existing = db.scalar(select(JobApplication.id).join(User, User.id == JobApplication.candidate_user_id)
                                     .where(User.email == email, JobApplication.job_opening_id == job["id"]))
            if existing:
                return existing
            response = client.post(backend + f"/api/candidate/jobs/{job['id']}/applications",
                                   headers=headers, files={"cv": (filename, pdf, "application/pdf")})
            assert response.status_code == 201, f"Upload failed: HTTP {response.status_code}"
            return response.json()["id"]

        def captured(email, subject):
            return any(message["Subject"] == subject and any(address["Address"] == email for address in message["To"])
                       for message in inbox(client)["messages"])

        app_id = upload_once("candidate@demo.example.com", auth, "alex-demo.pdf")
        def state(application_id):
            with SessionLocal() as db:
                row = db.get(CVScreening, application_id)
                if row and row.state == "failed":
                    raise AssertionError(f"Extraction stopped: {row.error_code}")
                if row and row.notification_state in {"sent", "unknown", "failed"}:
                    return db.get(JobApplication, application_id).status, row
        status, row = wait_for(lambda: state(app_id))
        assert status == "selected", (status, row.decision, row.match_result)
        assert row.match_result["decision"] == "pass"
        assert row.notification_state == "sent"
        assert captured("candidate@demo.example.com", "TalentForge AI screening: selected")
        print(f"PASS candidate {app_id}, dispatch {row.dispatch_id}, {status}, score {row.match_result['match_score']}, SMTP sent", flush=True)
        duplicate = client.post(backend + "/api/auth/register/candidate", json={
            "email": "duplicate@demo.example.com", "full_name": "Riley Demo",
            "password": os.environ["DEMO_ACCOUNT_PASSWORD"],
        })
        if duplicate.status_code == 409:
            duplicate = client.post(backend + "/api/auth/login", json={
                "email": "duplicate@demo.example.com", "password": os.environ["DEMO_ACCOUNT_PASSWORD"],
            })
        duplicate.raise_for_status()
        duplicate_auth = {"Authorization": "Bearer " + duplicate.json()["access_token"]}
        duplicate_id = upload_once("duplicate@demo.example.com", duplicate_auth, "duplicate-demo.pdf")
        status, row = wait_for(lambda: state(duplicate_id))
        assert status == "rejected" and row.decision == "duplicate"
        assert row.match_result is None and row.notification_state == "sent"
        assert captured("duplicate@demo.example.com", "TalentForge AI screening: rejected")
        print(f"PASS duplicate {duplicate_id}, dispatch {row.dispatch_id}, rejected, SMTP sent")

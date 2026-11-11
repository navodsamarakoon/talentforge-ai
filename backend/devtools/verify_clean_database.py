"""Smoke-test a fresh PostgreSQL schema. Run only in the disposable verification stack."""
import os
import subprocess
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

url = "postgresql+psycopg://verify:disposable-synthetic-only@verify-db:5432/verify"
assert os.environ.get("CV_DISPOSABLE_TESTS") == "1"
assert os.environ.get("DATABASE_URL") == url
for flag in ("CV_AUTOMATION_ENABLED", "N8N_AUTO_DISPATCH_ENABLED", "LANGSMITH_TRACING"):
    assert os.environ.get(flag) == "false"

engine = create_engine(url)
assert not inspect(engine).get_table_names(), "Expected an empty disposable database"
subprocess.run([sys.executable, "-m", "alembic", "-c", "/src/backend/alembic.ini",
                "upgrade", "0008_recruiter_summaries"], check=True, timeout=60)

from talentforge.main import app
from talentforge.models import JobOpening, Organization, User
from talentforge.security import hash_password

with engine.connect() as connection:
    assert connection.scalar(text("select version_num from alembic_version")) == "0008_recruiter_summaries"
    catalog = inspect(connection)
    assert {"organizations", "users", "job_openings", "job_applications",
            "cv_screenings", "recruiter_summaries"} <= set(catalog.get_table_names())
    for table, columns in {
        "job_openings": {"requirements"},
        "cv_screenings": {"dispatch_id", "match_result", "summary_id", "notification_state"},
        "recruiter_summaries": {"organization_id", "run_date", "state"},
    }.items():
        assert columns <= {column["name"] for column in catalog.get_columns(table)}
    for table, name in [
        ("job_applications", "uq_job_application_job_candidate"),
        ("recruiter_summaries", "uq_recruiter_summary_org_date"),
    ]:
        assert name in {row["name"] for row in catalog.get_unique_constraints(table)}
    for table, name in [
        ("job_applications", "ck_job_application_status"),
        ("cv_screenings", "ck_cv_screening_state"),
        ("recruiter_summaries", "ck_recruiter_summary_state"),
    ]:
        assert name in {row["name"] for row in catalog.get_check_constraints(table)}
    assert {"job_applications", "recruiter_summaries"} <= {
        row["referred_table"] for row in catalog.get_foreign_keys("cv_screenings")
    }
    assert ("summary_id",) in {tuple(row["column_names"]) for row in catalog.get_indexes("cv_screenings")}
print("PASS clean Alembic head, tables, columns, constraints, foreign keys and summary index", flush=True)

password = "Disposable-Clean-Smoke-Only!"
with Session(engine) as db:
    companies = [Organization(name=name) for name in ("Fixture One", "Fixture Two")]
    db.add_all(companies)
    db.flush()
    hashed = hash_password(password)
    for i, company in enumerate(companies):
        db.add(User(email=f"recruiter-{i}@example.com", full_name="Fixture Recruiter",
                    password_hash=hashed, role="recruiter", organization_id=company.id))
        db.add(JobOpening(organization_id=company.id, title=f"Fixture Vacancy {i}",
                          description="Fictional vacancy", employment_type="full-time", location="Colombo",
                          status="published", requirements={"mandatory_skills": ["Python"]}))
    db.add(User(email="candidate@example.com", full_name="Fixture Candidate",
                password_hash=hashed, role="candidate"))
    db.commit()

with TestClient(app) as client:
    def login(email):
        response = client.post("/api/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.status_code
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/jobs").status_code == 401
    recruiter = login("recruiter-0@example.com")
    other = login("recruiter-1@example.com")
    candidate = login("candidate@example.com")
    own = client.get("/api/jobs", headers=recruiter).json()
    foreign = client.get("/api/jobs", headers=other).json()
    assert [job["title"] for job in own] == ["Fixture Vacancy 0"]
    assert [job["title"] for job in foreign] == ["Fixture Vacancy 1"]
    assert client.get("/api/jobs", headers=candidate).status_code == 403
    assert len(client.get("/api/candidate/jobs", headers=candidate).json()) == 2
    route = f"/api/jobs/{own[0]['id']}/requirements"
    requirements = {"mandatory_skills": ["Python", "SQL"], "minimum_match_score": 80}
    assert client.put(route, headers=other, json=requirements).status_code == 404
    assert client.put(route, headers=recruiter, json=requirements).status_code == 200
    assert client.get("/api/jobs", headers=recruiter).json()[0]["requirements"]["minimum_match_score"] == 80
print("PASS FastAPI lifespan, health, three logins, vacancy visibility, role and organization isolation", flush=True)

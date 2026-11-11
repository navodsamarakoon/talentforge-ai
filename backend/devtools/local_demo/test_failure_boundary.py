"""Synthetic pre-claim failure smoke for the persistent local demo."""
import os
import time
from uuid import uuid4
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from talentforge.database import SessionLocal
from talentforge.models import User, JobOpening, JobApplication, CVScreening
from talentforge.config import get_settings
from talentforge.security import hash_password

assert os.environ["TALENTFORGE_LOCAL_DEMO"] == "1"
settings=get_settings()
assert settings.database_url.endswith("@db:5432/demo")
with SessionLocal() as db:
    user=User(email=f"envelope-failure-{uuid4().hex}@example.com",full_name="Synthetic Envelope Check",
              role="candidate",password_hash=hash_password(uuid4().hex))
    db.add(user)
    job=db.scalar(select(JobOpening).where(JobOpening.title=="Python Backend Engineer"))
    db.flush()
    app=JobApplication(job_opening_id=job.id,candidate_user_id=user.id,original_cv_filename="synthetic-invalid-envelope.pdf",
                       cv_mime_type="application/pdf",cv_sha256="a"*64,cv_storage_ref=f"fixture-{uuid4()}.pdf")
    db.add(app);db.flush()
    row=CVScreening(application_id=app.id,state="dispatching",dispatch_started_at=datetime.now(timezone.utc))
    db.add(row);db.flush()
    body={"schema_version":1,"application_id":app.id,"dispatch_id":row.dispatch_id,"job_id":job.id,
          "organization_id":job.organization_id,"cv_text":"Skills: Python","cv_sha256":app.cv_sha256,"cv_profile":[]}
    application_id=app.id
    db.commit()
with httpx.Client(timeout=15,trust_env=False) as client:
    before=client.get("http://mail:8025/api/v1/messages").json()["total"]
    for _ in range(2):
        result=client.post(settings.n8n_webhook_url,json=body,
                           headers={"X-TalentForge-Webhook-Secret":settings.n8n_webhook_secret.get_secret_value()})
        assert result.status_code==200
    for _ in range(90):
        with SessionLocal() as db:
            row=db.get(CVScreening,application_id)
            if row.state=="failed":break
        time.sleep(1)
    with SessionLocal() as db:
        row=db.get(CVScreening,application_id)
        assert row.state=="failed" and row.error_code=="workflow_envelope_failed"
        assert row.workflow_claimed_at is None and row.decision is None and row.notification_state is None
        assert db.get(JobApplication,application_id).status=="submitted"
    assert client.get("http://mail:8025/api/v1/messages").json()["total"]==before
print({"application":application_id,"state":"failed","error":"workflow_envelope_failed","claim":False,"decision":None,"emails":0})

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from talentforge import vacancy_notifications as routes
from talentforge.config import VacancyOneShot, get_settings
from talentforge.models import JobOpening, User, VacancyNotificationDelivery as Delivery, VacancyNotificationEvent as Event, VacancySmtpBudget
from test_job_openings import candidate_auth, create_job, recruiter_auth

PREFERENCE = "/api/candidate/vacancy-notifications"
BASE = "/api/integrations/n8n/vacancy-notifications"
HEADERS = {"X-TalentForge-Callback-Secret": "fictional-notification-secret"}


@pytest.fixture
def delivery_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "n8n_callback_secret", SecretStr(HEADERS["X-TalentForge-Callback-Secret"]))
    monkeypatch.setattr(settings, "vacancy_email_delivery_enabled", True)
    monkeypatch.setattr(settings, "candidate_dashboard_base_url", "http://127.0.0.1:18080")
    return settings


def opted_in(client, email):
    headers = candidate_auth(client, email)
    assert client.get(PREFERENCE, headers=headers).json() == {"enabled": False}
    assert client.put(PREFERENCE, headers=headers, json={"enabled": True}).json() == {"enabled": True}
    return headers


def publish(client, title="Fictional Role"):
    recruiter = recruiter_auth(client, "recruiter@example.com", "Fictional Company")
    job = create_job(client, recruiter, title=title)
    assert client.post(f"/api/jobs/{job['id']}/publish", headers=recruiter).status_code == 200
    return job


def claim(client):
    response = client.post(f"{BASE}/claim", headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()["deliveries"]


def receipt(client, item, outcome):
    return client.post(f"{BASE}/{item['id']}/receipt", headers=HEADERS,
                       json={"claim_token": item["claim_token"], "outcome": outcome})


def authorize(client, item, headers=HEADERS):
    return client.post(f"{BASE}/{item['id']}/authorize-smtp", headers=headers,
                       json={"claim_token": item["claim_token"]})


@pytest.mark.parametrize("count", [0, 1, 5, 50])
def test_fanout_sizes(client, db_session, count):
    db_session.add_all([
        User(email=f"fixture-{index}@example.com", full_name="Fixture", role="candidate",
             password_hash="unused", vacancy_notifications=index < count)
        for index in range(count + 3)
    ])
    db_session.commit()
    publish(client)
    assert db_session.scalar(select(func.count()).select_from(Event)) == 1
    assert set(db_session.scalars(select(Delivery.recipient))) == {
        f"fixture-{index}@example.com" for index in range(count)
    }


def test_authorization_rechecks_opt_out_after_claim(client, db_session, delivery_settings):
    candidate = opted_in(client, "consent@example.com")
    publish(client)
    item, = claim(client)
    assert set(item) == {"id", "claim_token"}
    assert client.put(PREFERENCE, headers=candidate, json={"enabled": False}).status_code == 200
    assert authorize(client, item).status_code == 409
    assert db_session.get(Delivery, item["id"]).state == "skipped"


def test_authorization_issues_message_once(client, delivery_settings):
    candidate = opted_in(client, "once@example.com")
    publish(client)
    item, = claim(client)
    assert authorize(client, item, {}).status_code == 401
    assert authorize(client, {**item, "claim_token": "00000000-0000-4000-8000-000000000001"}).status_code == 409
    assert receipt(client, item, "sent").status_code == 409
    delivery_settings.vacancy_email_delivery_enabled = False
    assert authorize(client, item).status_code == 403
    delivery_settings.vacancy_email_delivery_enabled = True
    assert authorize(client, item).json()["recipient"] == "once@example.com"
    assert authorize(client, item).status_code == 409
    assert receipt(client, item, "sent").status_code == 200
    assert client.put(PREFERENCE, headers=candidate, json={"enabled": False}).status_code == 200
    assert receipt(client, item, "sent").status_code == 200


def test_daily_cap_auth_block_and_operator_reset(client, db_session, delivery_settings, monkeypatch):
    for index in range(3):
        opted_in(client, f"budget-{index}@example.com")
    publish(client)
    now = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=12)
    monkeypatch.setattr(routes, "utcnow", lambda: now)
    monkeypatch.setattr(delivery_settings, "vacancy_email_daily_cap", 1)
    first, = claim(client)
    assert authorize(client, first).status_code == 200
    assert receipt(client, first, "sent").status_code == 200
    now += timedelta(minutes=10)
    assert claim(client) == []
    now += timedelta(days=1)
    second, = claim(client)
    assert authorize(client, second).status_code == 200
    assert receipt(client, second, "auth_failed").status_code == 200
    assert receipt(client, second, "auth_failed").status_code == 200
    now += timedelta(days=1)
    assert claim(client) == []
    budget = db_session.get(VacancySmtpBudget, 1)
    assert budget.auth_blocked_at is not None and budget.reservations == 1
    budget.auth_blocked_at = None
    db_session.commit()
    third, = claim(client)
    assert authorize(client, third).status_code == 200


def test_publication_snapshots_only_opted_in_candidates(client, db_session):
    owner = recruiter_auth(client, "owner@example.com", "Owner")
    other = recruiter_auth(client, "other@example.com", "Other")
    opted_in(client, "eligible@example.com")
    candidate_auth(client, "opted-out@example.com")
    db_session.add_all([
        User(email="invalid", full_name="Invalid", role="candidate", password_hash="unused", vacancy_notifications=True),
        User(email="admin@example.com", full_name="Admin", role="admin", password_hash="unused", vacancy_notifications=True),
    ])
    db_session.commit()
    job = create_job(client, owner)
    job_url = f"/api/jobs/{job['id']}"
    assert client.put(f"{job_url}/requirements", headers=owner, json={"mandatory_skills": ["Python"]}).status_code == 200
    assert db_session.scalar(select(func.count()).select_from(Event)) == 0
    assert client.post(f"{job_url}/publish", headers=other).status_code == 404
    assert db_session.scalar(select(func.count()).select_from(Event)) == 0
    assert client.post(f"{job_url}/publish", headers=owner).status_code == 200
    assert client.post(f"{job_url}/publish", headers=owner).status_code == 409
    assert client.put(f"{job_url}/requirements", headers=owner, json={"mandatory_skills": ["Git"]}).status_code == 200
    opted_in(client, "late@example.com")
    assert db_session.scalar(select(func.count()).select_from(Event)) == 1
    assert db_session.scalars(select(Delivery.recipient)).all() == ["eligible@example.com"]


def test_publish_rollback_removes_event(client, db_session, monkeypatch):
    from talentforge import api

    owner = recruiter_auth(client, "owner@example.com", "Owner")
    opted_in(client, "eligible@example.com")
    job = create_job(client, owner)
    original = api.enqueue_publication

    def fail(db, vacancy):
        original(db, vacancy)
        db.flush()
        raise RuntimeError("Fictional transaction failure")

    monkeypatch.setattr(api, "enqueue_publication", fail)
    with pytest.raises(RuntimeError, match="Fictional transaction failure"):
        client.post(f"/api/jobs/{job['id']}/publish", headers=owner)
    assert db_session.get(JobOpening, job["id"]).status == "draft"
    assert db_session.scalar(select(func.count()).select_from(Event)) == 0
    assert db_session.scalar(select(func.count()).select_from(Delivery)) == 0


def test_claim_checks_current_consent_and_returns_one_private_message(client, db_session, delivery_settings):
    opted_out = opted_in(client, "stop@example.com")
    opted_in(client, "first@example.com")
    opted_in(client, "second@example.com")
    publish(client, "<Fictional Role>")
    assert client.put(PREFERENCE, headers=opted_out, json={"enabled": False}).status_code == 200
    assert client.post(f"{BASE}/claim").status_code == 401
    delivery_settings.vacancy_email_delivery_enabled = False
    assert claim(client) == []
    assert db_session.scalars(select(Delivery.state)).all() == ["pending"] * 3
    delivery_settings.vacancy_email_delivery_enabled = True
    item, = claim(client)
    item = authorize(client, item).json()
    assert item["recipient"] in {"first@example.com", "second@example.com"}
    assert "Fictional Company" in item["text"] and "<Fictional Role>" in item["subject"]
    assert "http://127.0.0.1:18080/candidate" in item["text"]
    assert not any(email in item["text"] for email in ("first@example.com", "second@example.com", "stop@example.com"))
    assert claim(client) == []
    assert receipt(client, item, "sent").status_code == 200
    assert receipt(client, item, "sent").status_code == 200
    assert receipt(client, item, "transient").status_code == 409


@pytest.mark.parametrize("outcome,final", [("failed", "failed"), ("unknown", "delivery_unknown"), (None, "delivery_unknown")])
def test_permanent_and_ambiguous_outcomes_never_retry(client, db_session, delivery_settings, monkeypatch, outcome, final):
    opted_in(client, "recipient@example.com")
    publish(client)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(routes, "utcnow", lambda: now)
    item, = claim(client)
    if outcome:
        assert authorize(client, item).status_code == 200
        assert receipt(client, item, outcome).status_code == 200
    now += timedelta(hours=1)
    assert claim(client) == []
    assert db_session.get(Delivery, item["id"]).state == final


def test_definite_transient_retry_has_backoff_and_attempt_limit(client, db_session, delivery_settings, monkeypatch):
    opted_in(client, "recipient@example.com")
    publish(client)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(routes, "utcnow", lambda: now)
    first, = claim(client)
    assert authorize(client, first).status_code == 200
    assert receipt(client, first, "transient").status_code == 200
    now += timedelta(minutes=4)
    assert claim(client) == []
    now += timedelta(minutes=1)
    second, = claim(client)
    assert second["id"] == first["id"] and second["claim_token"] != first["claim_token"]
    assert receipt(client, first, "sent").status_code == 409
    assert authorize(client, second).status_code == 200
    assert receipt(client, second, "transient").status_code == 200
    now += timedelta(minutes=9)
    assert claim(client) == []
    now += timedelta(minutes=1)
    third, = claim(client)
    assert authorize(client, third).status_code == 200
    assert receipt(client, third, "transient").status_code == 200
    now += timedelta(hours=1)
    assert claim(client) == []
    row = db_session.get(Delivery, third["id"])
    assert (row.state, row.attempts) == ("failed", 3)


@pytest.fixture
def one_shot(client, db_session, delivery_settings, monkeypatch):
    candidate = opted_in(client, "one-shot@example.com")
    job = publish(client)
    row = db_session.scalar(select(Delivery))
    approval = VacancyOneShot(
        delivery_id=row.id, recipient=row.recipient, event_id=row.event_id, vacancy_id=job["id"],
    )
    monkeypatch.setattr(delivery_settings, "vacancy_email_delivery_enabled", False)
    monkeypatch.setattr(delivery_settings, "vacancy_one_shot", approval)
    return approval.model_dump(mode="json"), candidate


@pytest.mark.parametrize("outcome, state", [("sent", "sent"), ("unknown", "delivery_unknown"), ("transient", "failed")])
def test_exact_claim_is_single_use_and_never_requeues(client, db_session, one_shot, outcome, state):
    payload, _ = one_shot
    url = f"{BASE}/claim-one"
    response = client.post(url, headers=HEADERS, json=payload)
    assert response.status_code == 200
    item = response.json()
    assert item["id"] == payload["delivery_id"] and item["recipient"] == payload["recipient"]
    assert client.post(url, headers=HEADERS, json=payload).status_code == 409
    assert receipt(client, item, outcome).status_code == 200
    db_session.expire_all()
    row = db_session.get(Delivery, item["id"])
    assert (row.state, row.attempts) == (state, 1)
    assert client.post(url, headers=HEADERS, json=payload).status_code == 409


def test_exact_claim_requires_authentication_and_configured_approval(client, one_shot, delivery_settings):
    payload, _ = one_shot
    url = f"{BASE}/claim-one"
    assert client.post(url, json=payload).status_code == 401
    for key in payload:
        changed = "different@example.com" if key == "recipient" else "00000000-0000-4000-8000-000000000001"
        assert client.post(url, headers=HEADERS, json={**payload, key: changed}).status_code == 403
    delivery_settings.vacancy_email_delivery_enabled = True
    assert client.post(url, headers=HEADERS, json=payload).status_code == 403
    delivery_settings.vacancy_email_delivery_enabled = False
    delivery_settings.vacancy_one_shot = None
    assert client.post(url, headers=HEADERS, json=payload).status_code == 403


def test_exact_claim_rechecks_candidate_opt_out(client, one_shot):
    payload, candidate = one_shot
    assert client.put(PREFERENCE, headers=candidate, json={"enabled": False}).status_code == 200
    assert client.post(f"{BASE}/claim-one", headers=HEADERS, json=payload).status_code == 409

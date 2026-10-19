from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from talentforge.api import get_sandbox
from talentforge.models import Assessment, Attempt, Invitation, Question, utcnow
from talentforge.sandbox import CaseResult
from talentforge.schemas import EvaluationOutput


class FakeSandbox:
    def run(self, code, function_name, cases):
        return [CaseResult(True, "passed", duration_ms=1) for _ in cases]


class UnavailableSandbox:
    def run(self, code, function_name, cases):
        from talentforge.sandbox import SandboxUnavailable

        raise SandboxUnavailable("Docker daemon is unavailable.")


def auth(client, email, organization):
    response = client.post("/api/auth/register", json={
        "email": email,
        "full_name": "Recruiter",
        "password": "a-strong-test-password",
        "organization_name": organization,
    })
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def invite_candidate(client, recruiter, assessment_id, email="candidate@example.test"):
    response = client.post(
        f"/api/assessments/{assessment_id}/invitations",
        headers=recruiter,
        json={"email": email},
    )
    assert response.status_code == 201
    token = parse_qs(urlparse(response.json()["invitation_url"]).query)["token"][0]
    accepted = client.post("/api/invitations/accept", json={
        "token": token,
        "full_name": "Candidate One",
        "password": "a-strong-candidate-password",
    })
    assert accepted.status_code == 201
    return {"Authorization": f"Bearer {accepted.json()['access_token']}"}


def published_assessment(client, recruiter):
    created = client.post("/api/assessments", headers=recruiter, json={
        "title": "Python fundamentals",
        "role": "Software Engineer",
        "instructions": "Implement the function.",
        "time_limit_minutes": 30,
    })
    assert created.status_code == 201
    assessment_id = created.json()["id"]
    question = client.post(f"/api/assessments/{assessment_id}/questions", headers=recruiter, json={
        "position": 0,
        "title": "Add values",
        "prompt": "Return the sum of both inputs.",
        "function_name": "add",
        "starter_code": "def add(a, b):\n    pass",
        "test_cases": [
            {"input_args": [1, 2], "expected_output": 3, "is_hidden": False},
            {"input_args": ["private-input"], "expected_output": "secret-output", "is_hidden": True},
        ],
    })
    assert question.status_code == 201
    published = client.post(f"/api/assessments/{assessment_id}/publish", headers=recruiter)
    assert published.status_code == 200
    return assessment_id


def test_recruiter_candidate_assessment_submission_and_reports(client):
    recruiter = auth(client, "owner@example.com", "Northstar")
    assessment_id = published_assessment(client, recruiter)
    candidate = invite_candidate(client, recruiter, assessment_id, "candidate@example.com")

    assigned = client.get("/api/candidate/assessments", headers=candidate)
    assert assigned.status_code == 200
    assert len(assigned.json()) == 1
    assigned_text = assigned.text
    assert "secret-output" not in assigned_text
    assert "private-input" not in assigned_text

    client.app.dependency_overrides[get_sandbox] = FakeSandbox
    try:
        started = client.post(f"/api/candidate/assessments/{assessment_id}/attempts", headers=candidate)
        assert started.status_code == 201, started.text
        attempt_id = started.json()["id"]
        sample = client.post(f"/api/candidate/attempts/{attempt_id}/run-samples", headers=candidate, json={
            "question_id": started.json()["assessment"]["questions"][0]["id"],
            "code": "def add(a, b): return a + b",
        })
        assert sample.status_code == 200
        assert all("expected_output" not in item for item in sample.json())
        submission = client.post(f"/api/candidate/attempts/{attempt_id}/submissions", headers=candidate, json={
            "question_id": started.json()["assessment"]["questions"][0]["id"],
            "code": "def add(a, b): return a + b",
            "explanation": "Add both inputs.",
        })
        assert submission.status_code == 201
        assert submission.json()["execution_status"] == "completed"
        assert submission.json()["evaluation_status"] == "skipped"
        assert len(submission.json()["execution_results"]) == 1

        duplicate = client.post(f"/api/candidate/attempts/{attempt_id}/submissions", headers=candidate, json={
            "question_id": started.json()["assessment"]["questions"][0]["id"],
            "code": "def add(a, b): return a + b",
        })
        assert duplicate.status_code == 409

        comparison = client.get(f"/api/assessments/{assessment_id}/compare", headers=recruiter)
        assert comparison.status_code == 200
        assert comparison.json()[0]["candidate_email"] == "candidate@example.com"
        assert comparison.json()[0]["execution_results"][0]["passed"] is True
        assert len(comparison.json()[0]["execution_results"]) == 2
    finally:
        client.app.dependency_overrides.pop(get_sandbox, None)


def test_publish_requires_questions_and_hiding_test_cases(client):
    recruiter = auth(client, "author@example.com", "Acme")
    assessment = client.post("/api/assessments", headers=recruiter, json={
        "title": "Draft",
        "role": "Software Engineering Intern",
        "time_limit_minutes": 20,
    }).json()
    assert client.post(f"/api/assessments/{assessment['id']}/publish", headers=recruiter).status_code == 422
    candidate = invite_candidate(client, recruiter, published_assessment(client, recruiter), "another@example.com")
    public_assessments = client.get("/api/candidate/assessments", headers=candidate).json()
    assert "secret-output" not in str(public_assessments)


def test_organization_isolation_and_role_permissions(client):
    first = auth(client, "first@example.com", "First Org")
    assessment_id = published_assessment(client, first)
    other = auth(client, "second@example.com", "Second Org")
    assert client.get(f"/api/assessments/{assessment_id}", headers=other).status_code == 404
    assert client.get(f"/api/assessments/{assessment_id}/reports", headers=other).status_code == 404
    assert client.post("/api/assessments", headers={"Authorization": first["Authorization"]}, json={
        "title": "Another",
        "role": "Software Engineer",
        "time_limit_minutes": 30,
    }).status_code == 201


def test_assessment_crud_persists_and_enforces_organization_and_lifecycle(client, db_session):
    recruiter = auth(client, "crud@example.com", "CRUD Org")
    other_recruiter = auth(client, "crud-other@example.com", "Other CRUD Org")
    payload = {
        "title": "  CRUD assessment  ",
        "role": "Software Engineer",
        "instructions": "Read carefully.",
        "time_limit_minutes": 45,
        "allow_multiple_attempts": True,
    }

    created_response = client.post("/api/assessments", headers=recruiter, json=payload)
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assessment_id = created["id"]
    assert created["title"] == "CRUD assessment"
    assert client.post("/api/assessments", json=payload).status_code == 401

    listed = client.get("/api/assessments", headers=recruiter)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [assessment_id]
    assert client.get(f"/api/assessments/{assessment_id}", headers=recruiter).json()["title"] == "CRUD assessment"

    updated_response = client.patch(f"/api/assessments/{assessment_id}", headers=recruiter, json={
        **payload,
        "title": "Updated CRUD assessment",
        "role": "Software Engineering Intern",
        "instructions": "Updated instructions.",
        "time_limit_minutes": 60,
        "allow_multiple_attempts": False,
    })
    assert updated_response.status_code == 200, updated_response.text
    assert updated_response.json()["title"] == "Updated CRUD assessment"
    assert updated_response.json()["role"] == "Software Engineering Intern"
    assert updated_response.json()["instructions"] == "Updated instructions."
    assert updated_response.json()["time_limit_minutes"] == 60
    assert updated_response.json()["allow_multiple_attempts"] is False
    db_session.expire_all()
    persisted = db_session.get(Assessment, assessment_id)
    assert persisted is not None
    assert persisted.title == "Updated CRUD assessment"
    assert persisted.role == "Software Engineering Intern"
    assert persisted.instructions == "Updated instructions."
    assert persisted.time_limit_minutes == 60
    assert persisted.allow_multiple_attempts is False
    fetched_again = client.get(f"/api/assessments/{assessment_id}", headers=recruiter)
    assert fetched_again.status_code == 200
    assert fetched_again.json()["title"] == "Updated CRUD assessment"
    assert fetched_again.json()["instructions"] == "Updated instructions."

    assert client.patch(f"/api/assessments/{assessment_id}", headers=recruiter, json={
        **payload,
        "time_limit_minutes": 4,
    }).status_code == 422
    assert client.patch("/api/assessments/not-an-id", headers=recruiter, json=payload).status_code == 404
    assert client.get(f"/api/assessments/{assessment_id}", headers=other_recruiter).status_code == 404
    assert client.patch(f"/api/assessments/{assessment_id}", headers=other_recruiter, json=payload).status_code == 404
    assert client.delete(f"/api/assessments/{assessment_id}", headers=other_recruiter).status_code == 404
    assert client.patch(f"/api/assessments/{assessment_id}", json=payload).status_code == 401

    invitation = client.post(f"/api/assessments/{assessment_id}/invitations", headers=recruiter, json={
        "email": "invited@example.com",
    })
    assert invitation.status_code == 409  # Drafts cannot have invitations.
    deleted = client.delete(f"/api/assessments/{assessment_id}", headers=recruiter)
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/assessments/{assessment_id}", headers=recruiter).status_code == 404
    assert client.get("/api/assessments", headers=recruiter).json() == []

    invalid_create = client.post("/api/assessments", headers=recruiter, json={
        **payload,
        "title": "   ",
    })
    assert invalid_create.status_code == 422
    assert client.delete("/api/assessments/not-an-id", headers=recruiter).status_code == 404


def test_assessment_with_candidate_invitation_cannot_be_deleted(client):
    recruiter = auth(client, "lifecycle@example.com", "Lifecycle Org")
    assessment_id = published_assessment(client, recruiter)
    invitation = client.post(f"/api/assessments/{assessment_id}/invitations", headers=recruiter, json={
        "email": "lifecycle-candidate@example.com",
    })
    assert invitation.status_code == 201
    token = parse_qs(urlparse(invitation.json()["invitation_url"]).query)["token"][0]
    accepted = client.post("/api/invitations/accept", json={
        "token": token,
        "full_name": "Lifecycle Candidate",
        "password": "a-strong-candidate-password",
    })
    assert accepted.status_code == 201
    candidate = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
    attempt = client.post(f"/api/candidate/assessments/{assessment_id}/attempts", headers=candidate)
    assert attempt.status_code == 201, attempt.text
    response = client.delete(f"/api/assessments/{assessment_id}", headers=recruiter)
    assert response.status_code == 409
    assert client.get(f"/api/assessments/{assessment_id}", headers=recruiter).status_code == 200


def test_question_update_persists_fields_and_hidden_test_flags(client, db_session):
    recruiter = auth(client, "question-update@example.com", "Question Update Org")
    other_recruiter = auth(client, "question-update-other@example.com", "Other Question Org")
    assessment = client.post("/api/assessments", headers=recruiter, json={
        "title": "Question editing",
        "role": "Software Engineer",
        "time_limit_minutes": 30,
    }).json()
    created = client.post(f"/api/assessments/{assessment['id']}/questions", headers=recruiter, json={
        "position": 0,
        "title": "Add values",
        "prompt": "Add two inputs.",
        "function_name": "add",
        "starter_code": "def add(a, b): pass",
        "test_cases": [
            {"input_args": [1, 2], "expected_output": 3, "is_hidden": False},
            {"input_args": [4, 5], "expected_output": 9, "is_hidden": True},
        ],
    })
    assert created.status_code == 201, created.text
    question_id = created.json()["questions"][0]["id"]

    response = client.patch(f"/api/assessments/{assessment['id']}/questions/{question_id}", headers=recruiter, json={
        "position": 2,
        "title": "Sum integers",
        "prompt": "Return the sum of both integers.",
        "function_name": "sum_values",
        "starter_code": "def sum_values(a, b):\n    return a + b",
        "test_cases": [
            {"input_args": [3, 4], "expected_output": 7, "is_hidden": False},
            {"input_args": [8, 9], "expected_output": 17, "is_hidden": True},
        ],
    })
    assert response.status_code == 200, response.text
    returned = response.json()["questions"][0]
    assert returned["title"] == "Sum integers"
    assert returned["position"] == 2
    assert returned["function_name"] == "sum_values"
    assert [case["is_hidden"] for case in returned["test_cases"]] == [False, True]

    db_session.expire_all()
    persisted = db_session.get(Question, question_id)
    assert persisted is not None
    assert (persisted.title, persisted.position, persisted.function_name) == ("Sum integers", 2, "sum_values")
    assert [(case.input_args, case.expected_output, case.is_hidden) for case in persisted.test_cases] == [
        ([3, 4], 7, False),
        ([8, 9], 17, True),
    ]
    fetched = client.get(f"/api/assessments/{assessment['id']}", headers=recruiter)
    assert fetched.status_code == 200
    assert fetched.json()["questions"][0]["title"] == "Sum integers"
    assert client.patch(f"/api/assessments/{assessment['id']}/questions/missing-question", headers=recruiter, json={
        "title": "Should not exist",
    }).status_code == 404
    assert client.patch(f"/api/assessments/{assessment['id']}/questions/{question_id}", headers=other_recruiter, json={
        "title": "Unauthorized",
    }).status_code == 404
    assert client.patch(f"/api/assessments/{assessment['id']}/questions/{question_id}", json={
        "title": "Unauthenticated",
    }).status_code == 401
    assert client.patch(f"/api/assessments/{assessment['id']}/questions/{question_id}", headers=recruiter, json={
        "function_name": "not valid",
    }).status_code == 422


def test_revoked_invitation_cannot_be_accepted(client):
    recruiter = auth(client, "revoke@example.com", "Revoke Org")
    assessment_id = published_assessment(client, recruiter)
    invitation = client.post(f"/api/assessments/{assessment_id}/invitations", headers=recruiter, json={
        "email": "revoked@example.com",
    }).json()
    revoked = client.post(
        f"/api/assessments/{assessment_id}/invitations/{invitation['id']}/revoke",
        headers=recruiter,
    )
    token_rows = client.get(f"/api/assessments/{assessment_id}/invitations", headers=recruiter)
    assert token_rows.status_code == 200, token_rows.text
    token_row = token_rows.json()[0]
    assert revoked.status_code == 204
    assert token_row["revoked_at"] is not None
    raw_token = parse_qs(urlparse(invitation["invitation_url"]).query)["token"][0]
    response = client.post("/api/invitations/accept", json={
        "token": raw_token,
        "full_name": "Revoked Candidate",
        "password": "a-strong-candidate-password",
    })
    assert response.status_code == 400


def test_attempt_deadline_is_server_enforced(client, db_session):
    recruiter = auth(client, "deadline@example.com", "Deadline Org")
    assessment_id = published_assessment(client, recruiter)
    candidate = invite_candidate(client, recruiter, assessment_id, "deadline-candidate@example.com")
    attempt_response = client.post(f"/api/candidate/assessments/{assessment_id}/attempts", headers=candidate)
    assert attempt_response.status_code == 201, attempt_response.text
    attempt_id = attempt_response.json()["id"]
    attempt = db_session.get(Attempt, attempt_id)
    assert attempt is not None
    attempt.deadline_at = utcnow() - timedelta(minutes=1)
    db_session.commit()
    client.app.dependency_overrides[get_sandbox] = FakeSandbox
    try:
        response = client.post(f"/api/candidate/attempts/{attempt_id}/run-samples", headers=candidate, json={
            "question_id": attempt_response.json()["assessment"]["questions"][0]["id"],
            "code": "def add(a, b): return a + b",
        })
        assert response.status_code == 409
    finally:
        client.app.dependency_overrides.pop(get_sandbox, None)


def test_malformed_ai_output_fails_schema_validation():
    try:
        EvaluationOutput.model_validate({"overall_score": "high"})
    except ValueError:
        pass
    else:
        raise AssertionError("Malformed model response was accepted.")


def test_invitation_expiry_is_enforced(client, db_session):
    recruiter = auth(client, "expiry@example.com", "Expiry Org")
    assessment_id = published_assessment(client, recruiter)
    invitation = client.post(f"/api/assessments/{assessment_id}/invitations", headers=recruiter, json={
        "email": "expired@example.com",
    }).json()
    row = db_session.get(Invitation, invitation["id"])
    assert row is not None
    row.expires_at = utcnow() - timedelta(minutes=1)
    db_session.commit()
    token = parse_qs(urlparse(invitation["invitation_url"]).query)["token"][0]
    response = client.post("/api/invitations/accept", json={
        "token": token,
        "full_name": "Expired Candidate",
        "password": "a-strong-candidate-password",
    })
    assert response.status_code == 400


def test_failed_sandbox_submission_is_saved_and_can_retry(client):
    recruiter = auth(client, "retry@example.com", "Retry Org")
    assessment_id = published_assessment(client, recruiter)
    candidate = invite_candidate(client, recruiter, assessment_id, "retry-candidate@example.com")
    attempt = client.post(f"/api/candidate/assessments/{assessment_id}/attempts", headers=candidate).json()
    question_id = attempt["assessment"]["questions"][0]["id"]
    client.app.dependency_overrides[get_sandbox] = UnavailableSandbox
    try:
        saved = client.post(f"/api/candidate/attempts/{attempt['id']}/submissions", headers=candidate, json={
            "question_id": question_id,
            "code": "def add(a, b): return a + b",
        })
        assert saved.status_code == 201
        submission_id = saved.json()["id"]
        assert saved.json()["execution_status"] == "sandbox_unavailable"
        assert client.get(f"/api/candidate/submissions/{submission_id}", headers=candidate).status_code == 200

        retry_unavailable = client.post(
            f"/api/candidate/submissions/{submission_id}/retry-execution",
            headers=candidate,
        )
        assert retry_unavailable.status_code == 503

        client.app.dependency_overrides[get_sandbox] = FakeSandbox
        retried = client.post(
            f"/api/candidate/submissions/{submission_id}/retry-execution",
            headers=candidate,
        )
        assert retried.status_code == 200
        assert retried.json()["execution_status"] == "completed"
        assert len(retried.json()["execution_results"]) == 1
        reevaluated = client.post(
            f"/api/candidate/submissions/{submission_id}/retry-evaluation",
            headers=candidate,
        )
        assert reevaluated.status_code == 200
        assert reevaluated.json()["evaluation_status"] == "skipped"
        report = client.get(f"/api/assessments/{assessment_id}/compare", headers=recruiter)
        assert len(report.json()[0]["execution_results"]) == 2
    finally:
        client.app.dependency_overrides.pop(get_sandbox, None)


def test_logout_invalidates_existing_token(client):
    recruiter = auth(client, "logout@example.com", "Logout Org")
    logged_out = client.post("/api/auth/logout", headers=recruiter)
    assert logged_out.status_code == 204
    assert client.get("/api/auth/me", headers=recruiter).status_code == 401


def test_existing_candidate_can_accept_another_invitation(client):
    recruiter = auth(client, "multi-invite@example.com", "Invites Org")
    first_assessment = published_assessment(client, recruiter)
    candidate_headers = invite_candidate(client, recruiter, first_assessment, "repeat@example.com")
    assert client.get("/api/candidate/assessments", headers=candidate_headers).status_code == 200

    second_assessment = published_assessment(client, recruiter)
    second_invite = client.post(
        f"/api/assessments/{second_assessment}/invitations",
        headers=recruiter,
        json={"email": "repeat@example.com"},
    ).json()
    token = parse_qs(urlparse(second_invite["invitation_url"]).query)["token"][0]
    accepted = client.post("/api/invitations/accept", json={
        "token": token,
        "full_name": "Candidate One",
        "password": "a-strong-candidate-password",
    })
    assert accepted.status_code == 201
    assert len(client.get("/api/candidate/assessments", headers={
        "Authorization": f"Bearer {accepted.json()['access_token']}",
    }).json()) == 2

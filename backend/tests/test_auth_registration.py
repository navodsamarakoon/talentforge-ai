def test_candidate_registration_creates_unaffiliated_candidate_and_authenticates(client):
    registration = client.post("/api/auth/register/candidate", json={
        "email": "candidate@example.com",
        "full_name": "Candidate One",
        "password": "a-strong-candidate-password",
        "role": "recruiter",
        "organization_name": "Ignored Organization",
    })

    assert registration.status_code == 201
    response = registration.json()
    assert response["user"]["role"] == "candidate"
    assert response["user"]["organization_id"] is None
    assert client.get("/api/candidate/assessments", headers={
        "Authorization": f"Bearer {response['access_token']}",
    }).json() == []

    login = client.post("/api/auth/login", json={
        "email": "candidate@example.com",
        "password": "a-strong-candidate-password",
    })
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "candidate"


def test_candidate_registration_validates_email_name_and_password(client):
    valid_fields = {
        "email": "candidate@example.com",
        "full_name": "Candidate One",
        "password": "a-strong-candidate-password",
    }

    assert client.post("/api/auth/register/candidate", json={**valid_fields, "email": "not-an-email"}).status_code == 422
    assert client.post("/api/auth/register/candidate", json={**valid_fields, "full_name": "   "}).status_code == 422
    assert client.post("/api/auth/register/candidate", json={**valid_fields, "password": "short"}).status_code == 422


def test_candidate_registration_rejects_duplicate_email(client):
    payload = {
        "email": "candidate@example.com",
        "full_name": "Candidate One",
        "password": "a-strong-candidate-password",
    }
    assert client.post("/api/auth/register/candidate", json=payload).status_code == 201
    duplicate = client.post("/api/auth/register/candidate", json=payload)

    assert duplicate.status_code == 409

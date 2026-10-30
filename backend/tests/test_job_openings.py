def recruiter_auth(client, email, organization):
    registration = client.post("/api/auth/register", json={
        "email": email,
        "full_name": "Recruiter",
        "password": "a-strong-recruiter-password",
        "organization_name": organization,
    })
    assert registration.status_code == 201, registration.text
    return {"Authorization": f"Bearer {registration.json()['access_token']}"}


def candidate_auth(client, email="candidate@example.com"):
    registration = client.post("/api/auth/register/candidate", json={
        "email": email,
        "full_name": "Candidate",
        "password": "a-strong-candidate-password",
    })
    assert registration.status_code == 201, registration.text
    return {"Authorization": f"Bearer {registration.json()['access_token']}"}


def job_payload(**overrides):
    return {
        "title": "Software Engineer",
        "description": "Build and maintain product features.",
        "employment_type": "full-time",
        "location": "Remote",
        **overrides,
    }


def create_job(client, recruiter, **overrides):
    response = client.post("/api/jobs", headers=recruiter, json=job_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_recruiter_can_create_and_list_organization_job_openings(client):
    recruiter = recruiter_auth(client, "jobs@example.com", "Jobs Organization")

    created = create_job(
        client,
        recruiter,
        title="Software Engineering Intern",
        employment_type="internship",
    )
    listed = client.get("/api/jobs", headers=recruiter)

    assert created["id"]
    assert created["status"] == "draft"
    assert created["title"] == "Software Engineering Intern"
    assert created["employment_type"] == "internship"
    assert created["organization_id"]
    assert listed.status_code == 200
    assert [job["id"] for job in listed.json()] == [created["id"]]


def test_recruiter_can_publish_draft_and_candidate_sees_only_published_jobs(client):
    recruiter = recruiter_auth(client, "publish@example.com", "Publish Organization")
    candidate = candidate_auth(client)
    draft = create_job(client, recruiter, title="Draft role")
    publishable = create_job(client, recruiter, title="Published role")
    closed = create_job(client, recruiter, title="Closed role")

    published_response = client.post(f"/api/jobs/{publishable['id']}/publish", headers=recruiter)
    assert published_response.status_code == 200
    assert published_response.json()["status"] == "published"
    assert client.post(f"/api/jobs/{closed['id']}/close", headers=recruiter).json()["status"] == "closed"

    visible = client.get("/api/candidate/jobs", headers=candidate)
    assert visible.status_code == 200
    assert [job["id"] for job in visible.json()] == [publishable["id"]]
    assert draft["status"] == "draft"


def test_candidate_cannot_create_job_openings(client):
    candidate = candidate_auth(client)

    response = client.post("/api/jobs", headers=candidate, json=job_payload())

    assert response.status_code == 403


def test_job_openings_are_scoped_to_recruiter_organization(client):
    owner = recruiter_auth(client, "owner@example.com", "Owner Organization")
    other = recruiter_auth(client, "other@example.com", "Other Organization")
    job = create_job(client, owner)

    assert client.get("/api/jobs", headers=other).json() == []
    assert client.post(f"/api/jobs/{job['id']}/publish", headers=other).status_code == 404
    assert client.post(f"/api/jobs/{job['id']}/close", headers=other).status_code == 404


def test_job_opening_data_is_validated_and_state_transitions_are_restricted(client):
    recruiter = recruiter_auth(client, "validation@example.com", "Validation Organization")

    invalid_type = client.post(
        "/api/jobs",
        headers=recruiter,
        json=job_payload(employment_type="contract"),
    )
    blank_title = client.post(
        "/api/jobs",
        headers=recruiter,
        json=job_payload(title="   "),
    )
    assert invalid_type.status_code == 422
    assert blank_title.status_code == 422

    job = create_job(client, recruiter)
    assert client.post(f"/api/jobs/{job['id']}/publish", headers=recruiter).status_code == 200
    assert client.post(f"/api/jobs/{job['id']}/publish", headers=recruiter).status_code == 409
    assert client.post(f"/api/jobs/{job['id']}/close", headers=recruiter).status_code == 200
    assert client.post(f"/api/jobs/{job['id']}/publish", headers=recruiter).status_code == 409

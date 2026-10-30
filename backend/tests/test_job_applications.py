import io
import zipfile

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from talentforge.config import get_settings
from talentforge.models import JobApplication, User

from test_job_openings import candidate_auth, create_job, recruiter_auth


PDF_BYTES = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def valid_docx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Override PartName="/word/document.xml"
                ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
            </Types>""",
        )
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body/>
            </w:document>""",
        )
    return buffer.getvalue()


def uploaded_file(
    content: bytes = PDF_BYTES,
    filename: str = "resume.pdf",
    mime: str = PDF_MIME,
) -> dict:
    return {"cv": (filename, content, mime)}


def submit(client, candidate, job_id, files=None):
    return client.post(
        f"/api/candidate/jobs/{job_id}/applications",
        headers=candidate,
        files=files or uploaded_file(),
    )


@pytest.fixture(autouse=True)
def private_upload_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "cv_upload_dir", tmp_path / "private-cvs")


def published_job(client):
    recruiter = recruiter_auth(client, "applications-recruiter@example.com", "Applications Org")
    job = create_job(client, recruiter)
    assert client.post(f"/api/jobs/{job['id']}/publish", headers=recruiter).status_code == 200
    return job


def test_candidate_can_apply_with_pdf_and_private_metadata_is_not_returned(client):
    job = published_job(client)
    candidate = candidate_auth(client)

    response = submit(client, candidate, job["id"])

    assert response.status_code == 201, response.text
    application = response.json()
    assert application["id"]
    assert application["job_opening_id"] == job["id"]
    assert application["status"] == "submitted"
    assert application["original_cv_filename"] == "resume.pdf"
    assert application["submitted_at"]
    assert "cv_storage_ref" not in application
    assert "cv_sha256" not in application
    assert "cv_mime_type" not in application
    file_path = next((get_settings().cv_upload_dir).iterdir())
    assert file_path.is_file()
    assert file_path.read_bytes() == PDF_BYTES


def test_candidate_can_apply_with_valid_docx(client):
    job = published_job(client)
    candidate = candidate_auth(client)

    response = submit(
        client,
        candidate,
        job["id"],
        uploaded_file(valid_docx(), "resume.docx", DOCX_MIME),
    )

    assert response.status_code == 201, response.text
    assert response.json()["original_cv_filename"] == "resume.docx"


@pytest.mark.parametrize(
    ("filename", "content", "mime"),
    [
        ("resume.png", b"\x89PNG\r\n\x1a\n", "image/png"),
        ("resume.jpg", b"\xff\xd8\xff", "image/jpeg"),
        ("resume.jpeg", b"\xff\xd8\xff", "image/jpeg"),
        ("resume.doc", b"legacy word", "application/msword"),
        ("resume.txt", b"plain text", "text/plain"),
        ("resume.exe", b"MZ", "application/octet-stream"),
    ],
)
def test_unsupported_file_extensions_are_rejected(client, filename, content, mime):
    job = published_job(client)
    candidate = candidate_auth(client)

    response = submit(client, candidate, job["id"], uploaded_file(content, filename, mime))

    assert response.status_code == 415


def test_invalid_pdf_signature_is_rejected(client):
    job = published_job(client)
    candidate = candidate_auth(client)

    response = submit(
        client,
        candidate,
        job["id"],
        uploaded_file(b"not a pdf %%EOF /Type /Catalog", "resume.pdf", PDF_MIME),
    )

    assert response.status_code == 400


def test_invalid_docx_structure_is_rejected(client):
    job = published_job(client)
    candidate = candidate_auth(client)

    response = submit(
        client,
        candidate,
        job["id"],
        uploaded_file(b"not a zip", "resume.docx", DOCX_MIME),
    )

    assert response.status_code == 400


def test_spoofed_mime_type_is_rejected(client):
    job = published_job(client)
    candidate = candidate_auth(client)

    response = submit(
        client,
        candidate,
        job["id"],
        uploaded_file(PDF_BYTES, "resume.pdf", "application/octet-stream"),
    )

    assert response.status_code == 415


def test_empty_cv_is_rejected(client):
    job = published_job(client)
    candidate = candidate_auth(client)

    response = submit(client, candidate, job["id"], uploaded_file(b""))

    assert response.status_code == 400


def test_cv_over_10_mib_is_rejected_while_streaming(client):
    job = published_job(client)
    candidate = candidate_auth(client)

    response = submit(
        client,
        candidate,
        job["id"],
        uploaded_file(b"%PDF-1.4\n" + b"x" * (10 * 1024 * 1024), "resume.pdf", PDF_MIME),
    )

    assert response.status_code == 413
    assert list(get_settings().cv_upload_dir.iterdir()) == []


def test_path_traversal_filename_is_rejected(client):
    job = published_job(client)
    candidate = candidate_auth(client)

    response = submit(
        client,
        candidate,
        job["id"],
        uploaded_file(PDF_BYTES, "..\\resume.pdf", PDF_MIME),
    )

    assert response.status_code == 400


def test_application_submission_requires_candidate_authentication(client):
    job = published_job(client)

    response = client.post(
        f"/api/candidate/jobs/{job['id']}/applications",
        files=uploaded_file(),
    )

    assert response.status_code == 401


def test_recruiter_cannot_submit_candidate_application(client):
    job = published_job(client)
    recruiter = recruiter_auth(client, "another-recruiter@example.com", "Other Org")

    response = submit(client, recruiter, job["id"])

    assert response.status_code == 403


@pytest.mark.parametrize("status", ["draft", "closed"])
def test_candidate_cannot_apply_to_draft_or_closed_jobs(client, status):
    recruiter = recruiter_auth(client, f"{status}@example.com", f"{status} Org")
    candidate = candidate_auth(client)
    job = create_job(client, recruiter)
    if status == "closed":
        assert client.post(f"/api/jobs/{job['id']}/close", headers=recruiter).status_code == 200

    response = submit(client, candidate, job["id"])

    assert response.status_code == 409
    assert not get_settings().cv_upload_dir.exists()


def test_candidate_cannot_apply_to_nonexistent_job(client):
    candidate = candidate_auth(client)

    response = submit(client, candidate, "missing-job")

    assert response.status_code == 404


def test_duplicate_application_is_rejected_without_leaking_uploaded_file(client):
    job = published_job(client)
    candidate = candidate_auth(client)
    assert submit(client, candidate, job["id"]).status_code == 201

    response = submit(client, candidate, job["id"])

    assert response.status_code == 409
    assert len(list(get_settings().cv_upload_dir.iterdir())) == 1


def test_database_unique_constraint_protects_concurrent_duplicate_submissions(client, db_session):
    job = published_job(client)
    candidate_auth(client)
    candidate_id = db_session.scalar(select(User.id).where(User.email == "candidate@example.com"))
    assert candidate_id
    values = {
        "job_opening_id": job["id"],
        "candidate_user_id": candidate_id,
        "original_cv_filename": "resume.pdf",
        "cv_mime_type": PDF_MIME,
        "cv_sha256": "a" * 64,
        "cv_storage_ref": "first.pdf",
    }
    db_session.add(JobApplication(**values))
    db_session.commit()
    db_session.add(JobApplication(**{**values, "cv_storage_ref": "second.pdf"}))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_candidate_application_history_includes_job_opening_id_and_is_private(client):
    job = published_job(client)
    owner = candidate_auth(client, "owner-candidate@example.com")
    other = candidate_auth(client, "other-candidate@example.com")
    assert submit(client, owner, job["id"]).status_code == 201

    own_history = client.get("/api/candidate/applications", headers=owner)
    other_history = client.get("/api/candidate/applications", headers=other)

    assert own_history.status_code == 200
    assert len(own_history.json()) == 1
    assert own_history.json()[0]["id"]
    assert own_history.json()[0]["job_opening_id"] == job["id"]
    assert own_history.json()[0]["job_title"] == job["title"]
    assert own_history.json()[0]["original_cv_filename"] == "resume.pdf"
    assert own_history.json()[0]["status"] == "submitted"
    assert own_history.json()[0]["submitted_at"]
    assert other_history.status_code == 200
    assert other_history.json() == []


def test_recruiter_cannot_read_candidate_application_history(client):
    recruiter = recruiter_auth(client, "history-recruiter@example.com", "History Org")

    response = client.get("/api/candidate/applications", headers=recruiter)

    assert response.status_code == 403


def test_database_failure_removes_written_cv_file(client, monkeypatch):
    job = published_job(client)
    candidate = candidate_auth(client)

    def fail_commit(self):
        raise SQLAlchemyError("simulated database failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = submit(client, candidate, job["id"])

    assert response.status_code == 500
    assert list(get_settings().cv_upload_dir.iterdir()) == []

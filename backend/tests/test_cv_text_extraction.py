import hashlib
import io
from pathlib import Path

import pymupdf
import pytest
from docx import Document

from talentforge.config import get_settings
from talentforge.cv_text_extraction import (
    MAX_EXTRACTED_CHARACTERS,
    MAX_PDF_PAGES,
    extract_cv_text,
)


def test_parser_child_has_no_application_secrets_and_has_wall_timeout(monkeypatch):
    import json
    from talentforge import cv_text_extraction as extraction
    from types import SimpleNamespace
    def child(args, **options):
        assert options['timeout']==15
        assert not any(k in options['env'] for k in ['JWT_SECRET','LANGSMITH_API_KEY','N8N_CALLBACK_SECRET','N8N_WEBHOOK_SECRET','POSTGRES_PASSWORD'])
        assert options['env']['DATABASE_URL']=='sqlite://'
        body=dict(text='Synthetic',file_type='pdf',character_count=9,extraction_status='success',error_code=None)
        return SimpleNamespace(returncode=0,stdout=json.dumps(body).encode())
    monkeypatch.setattr(extraction.subprocess,'run',child)
    assert extraction.extract_cv_text_sandboxed('a'*32+'.pdf').text=='Synthetic'


def test_parser_child_timeout_is_safe_failure(monkeypatch):
    from talentforge import cv_text_extraction as extraction
    def timeout(*args, **kwargs):
        raise extraction.subprocess.TimeoutExpired('synthetic-parser',15)
    monkeypatch.setattr(extraction.subprocess,'run',timeout)
    result=extraction.extract_cv_text_sandboxed('a'*32+'.pdf')
    assert result.extraction_status=='extraction_error' and result.error_code=='extraction_timeout'


def create_text_pdf(text: str, *, page_count: int = 1, password: str | None = None) -> bytes:
    document = pymupdf.open()
    for index in range(page_count):
        page = document.new_page()
        if index == 0 and text:
            page.insert_text((72, 72), text)
    output = io.BytesIO()
    if password is None:
        document.save(output)
    else:
        document.save(
            output,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw="owner-password",
        )
    document.close()
    return output.getvalue()


def create_image_pdf() -> bytes:
    image = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 2, 2), 0)
    image.clear_with(255)
    png = image.tobytes("png")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_image(page.rect, stream=png)
    output = io.BytesIO()
    document.save(output)
    document.close()
    return output.getvalue()


def create_docx(*, with_table: bool = False, nested: bool = False) -> bytes:
    document = Document()
    document.add_paragraph("  Candidate   Profile  ")
    document.add_paragraph("Email:\tcandidate@example.test\nSenior Engineer")
    if with_table:
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Python"
        table.cell(0, 1).text = "2021 - Present"
        if nested:
            nested_table = table.cell(0, 0).add_table(rows=1, cols=1)
            nested_table.cell(0, 0).text = "Nested skill"
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


@pytest.fixture
def private_cv_store(tmp_path, monkeypatch):
    storage_dir = tmp_path / "private-cvs"
    monkeypatch.setattr(get_settings(), "cv_upload_dir", storage_dir)
    storage_dir.mkdir(mode=0o700)

    def store(content: bytes, suffix: str) -> tuple[str, Path, str]:
        storage_ref = f"{hashlib.sha256(content).hexdigest()[:32]}.{suffix}"
        path = storage_dir / storage_ref
        path.write_bytes(content)
        return storage_ref, path, hashlib.sha256(content).hexdigest()

    return store


def test_extracts_text_from_valid_text_pdf(private_cv_store):
    content = create_text_pdf("Synthetic Candidate\ncandidate@example.test\nPython")
    storage_ref, _, _ = private_cv_store(content, "pdf")

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "success"
    assert result.file_type == "pdf"
    assert result.character_count == len(result.text)
    assert "Synthetic Candidate" in result.text
    assert "candidate@example.test" in result.text
    assert "Python" in result.text


def test_extracts_docx_paragraphs_tables_and_nested_tables(private_cv_store):
    storage_ref, _, _ = private_cv_store(create_docx(with_table=True, nested=True), "docx")

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "success"
    assert result.file_type == "docx"
    assert "Candidate Profile" in result.text
    assert "candidate@example.test" in result.text
    assert "Python" in result.text
    assert "2021 - Present" in result.text
    assert "Nested skill" in result.text


def test_extracts_docx_headers_once_and_keeps_body_tables(private_cv_store):
    from docx.enum.section import WD_SECTION

    document = Document()
    document.sections[0].header.paragraphs[0].text = "Harper Fictional\nharper.fixture@example.com"
    document.add_section(WD_SECTION.NEW_PAGE)
    document.add_table(rows=1, cols=1).cell(0, 0).text = "Fixture Scheduler"
    data = io.BytesIO()
    document.save(data)
    storage_ref, _, _ = private_cv_store(data.getvalue(), "docx")

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "success"
    assert result.text.startswith("Harper Fictional\nharper.fixture@example.com")
    assert result.text.count("harper.fixture@example.com") == 1
    assert "Fixture Scheduler" in result.text


def test_normalizes_whitespace_without_collapsing_paragraphs(private_cv_store):
    storage_ref, _, _ = private_cv_store(create_docx(), "docx")

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "success"
    assert "Candidate Profile\n\nEmail: candidate@example.test\nSenior Engineer" == result.text


@pytest.mark.parametrize("content", [b"", b"not a pdf"])
def test_corrupt_or_empty_pdf_returns_structured_error(private_cv_store, content):
    storage_ref, _, _ = private_cv_store(content, "pdf")

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "extraction_error"
    assert result.text == ""
    assert result.error_code == "invalid_document"


def test_image_only_pdf_returns_no_text(private_cv_store):
    storage_ref, _, _ = private_cv_store(create_image_pdf(), "pdf")

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "no_text"
    assert result.error_code == "no_extractable_text"
    assert result.text == ""


def test_corrupt_docx_returns_structured_error(private_cv_store):
    storage_ref, _, _ = private_cv_store(b"not a DOCX zip", "docx")

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "extraction_error"
    assert result.error_code == "invalid_document"
    assert result.text == ""


def test_empty_docx_returns_no_text(private_cv_store):
    output = io.BytesIO()
    Document().save(output)
    storage_ref, _, _ = private_cv_store(output.getvalue(), "docx")

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "no_text"
    assert result.error_code == "no_extractable_text"
    assert result.text == ""


def test_unsupported_storage_key_is_rejected_without_path_access():
    result = extract_cv_text("../../candidate.pdf")

    assert result.extraction_status == "unsupported"
    assert result.file_type == "unknown"
    assert result.text == ""
    assert result.error_code == "unsupported_file_type"


def test_password_protected_pdf_is_reported_without_exposing_document(private_cv_store):
    storage_ref, _, _ = private_cv_store(
        create_text_pdf("Synthetic private text", password="document-password"),
        "pdf",
    )

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "extraction_error"
    assert result.error_code == "password_protected"
    assert "Synthetic private text" not in result.text


def test_unicode_text_is_preserved(private_cv_store):
    document = Document()
    document.add_paragraph("Zoë García — développeuse 日本語")
    output = io.BytesIO()
    document.save(output)
    storage_ref, _, _ = private_cv_store(output.getvalue(), "docx")

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "success"
    assert "Zoë García — développeuse 日本語" in result.text


def test_pdf_page_limit_prevents_resource_intensive_processing(private_cv_store):
    storage_ref, _, _ = private_cv_store(
        create_text_pdf("", page_count=MAX_PDF_PAGES + 1),
        "pdf",
    )

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "extraction_error"
    assert result.error_code == "page_limit_exceeded"


def test_text_output_is_bounded(private_cv_store):
    document = Document()
    document.add_paragraph("A" * (MAX_EXTRACTED_CHARACTERS + 100))
    output = io.BytesIO()
    document.save(output)
    storage_ref, _, _ = private_cv_store(output.getvalue(), "docx")

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "extraction_error"
    assert result.error_code == "text_limit_exceeded"
    assert result.text == ""


def test_oversized_stored_file_is_rejected(private_cv_store):
    storage_ref, _, _ = private_cv_store(b"%PDF-" + b"x" * (10 * 1024 * 1024), "pdf")

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "extraction_error"
    assert result.error_code == "file_too_large"


def test_original_private_file_and_sha256_are_unchanged(private_cv_store):
    original = create_text_pdf("Synthetic Candidate\ncandidate@example.test")
    storage_ref, path, original_hash = private_cv_store(original, "pdf")

    result = extract_cv_text(storage_ref)

    assert result.extraction_status == "success"
    assert path.read_bytes() == original
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash

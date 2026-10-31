import io
import logging
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from typing import Literal

import pymupdf
from docx import Document
from docx.document import Document as DocumentObject
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from talentforge.config import get_settings

logger = logging.getLogger(__name__)

CVFileType = Literal["pdf", "docx", "unknown"]
CVExtractionStatus = Literal["success", "no_text", "unsupported", "extraction_error"]

MAX_CV_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 500
MAX_DOCX_ENTRIES = 2048
MAX_DOCX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_DOCUMENT_XML_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 500_000
_STORAGE_REFERENCE = re.compile(r"^[0-9a-f]{32}\.(pdf|docx)$")
_HORIZONTAL_WHITESPACE = re.compile(r"[^\S\r\n]+")
_EXCESSIVE_LINE_BREAKS = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class CVTextExtractionResult:
    text: str
    file_type: CVFileType
    character_count: int
    extraction_status: CVExtractionStatus
    error_code: str | None = None


class _ExtractionFailure(Exception):
    def __init__(self, error_code: str):
        self.error_code = error_code
        super().__init__(error_code)


def _result(
    *,
    file_type: CVFileType,
    status: CVExtractionStatus,
    text: str = "",
    error_code: str | None = None,
) -> CVTextExtractionResult:
    return CVTextExtractionResult(
        text=text,
        file_type=file_type,
        character_count=len(text),
        extraction_status=status,
        error_code=error_code,
    )


def _normalize_text(text: str) -> str:
    normalized_lines = [
        _HORIZONTAL_WHITESPACE.sub(" ", line).strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    return _EXCESSIVE_LINE_BREAKS.sub("\n\n", "\n".join(normalized_lines)).strip()


def _read_private_cv(storage_ref: str) -> tuple[bytes, CVFileType]:
    match = _STORAGE_REFERENCE.fullmatch(storage_ref)
    if match is None:
        raise _ExtractionFailure("invalid_storage_reference")

    file_type: CVFileType = "pdf" if match.group(1) == "pdf" else "docx"
    storage_dir = get_settings().cv_upload_dir
    path = storage_dir / storage_ref
    try:
        if path.resolve(strict=True).parent != storage_dir.resolve(strict=True):
            raise _ExtractionFailure("invalid_storage_reference")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise _ExtractionFailure("invalid_storage_reference")
            if metadata.st_size > MAX_CV_BYTES:
                raise _ExtractionFailure("file_too_large")
            content = source.read(MAX_CV_BYTES + 1)
    except _ExtractionFailure:
        raise
    except FileNotFoundError:
        raise _ExtractionFailure("file_not_found") from None
    except OSError:
        raise _ExtractionFailure("file_unavailable") from None
    if len(content) > MAX_CV_BYTES:
        raise _ExtractionFailure("file_too_large")
    return content, file_type


def _extract_pdf(content: bytes) -> str:
    try:
        with pymupdf.open(stream=content, filetype="pdf") as document:
            if document.needs_pass:
                raise _ExtractionFailure("password_protected")
            if document.page_count > MAX_PDF_PAGES:
                raise _ExtractionFailure("page_limit_exceeded")
            pages: list[str] = []
            total_characters = 0
            for page in document:
                page_text = page.get_text("text")
                if total_characters + len(page_text) > MAX_EXTRACTED_CHARACTERS:
                    raise _ExtractionFailure("text_limit_exceeded")
                pages.append(page_text)
                total_characters += len(page_text)
            return _normalize_text("\n".join(pages))
    except _ExtractionFailure:
        raise
    except Exception as error:
        logger.warning("CV PDF extraction failed (%s).", type(error).__name__)
        raise _ExtractionFailure("invalid_document") from None


def _container_blocks(container: DocumentObject | _Cell) -> list[Paragraph | Table]:
    return list(container.iter_inner_content())


def _extract_table(table: Table) -> list[str]:
    rows: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            cell_content = _extract_docx_container(cell)
            if cell_content:
                cells.append(cell_content.replace("\n", " / "))
        if cells:
            rows.append(" | ".join(cells))
    return rows


def _extract_docx_container(container: DocumentObject | _Cell) -> str:
    parts: list[str] = []
    for block in _container_blocks(container):
        if isinstance(block, Paragraph):
            if block.text:
                parts.append(block.text)
        elif isinstance(block, Table):
            parts.extend(_extract_table(block))
    return "\n\n".join(parts)


def _validate_docx_archive(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > MAX_DOCX_ENTRIES
                or sum(entry.file_size for entry in entries) > MAX_DOCX_UNCOMPRESSED_BYTES
            ):
                raise _ExtractionFailure("document_resource_limit")
            document_entry = archive.getinfo("word/document.xml")
            if document_entry.file_size > MAX_DOCUMENT_XML_BYTES:
                raise _ExtractionFailure("document_resource_limit")
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(
                {entry.filename for entry in entries}
            ):
                raise _ExtractionFailure("invalid_document")
    except _ExtractionFailure:
        raise
    except (zipfile.BadZipFile, KeyError, OSError, RuntimeError, EOFError):
        raise _ExtractionFailure("invalid_document") from None


def _extract_docx(content: bytes) -> str:
    _validate_docx_archive(content)
    try:
        document = Document(io.BytesIO(content))
        return _normalize_text(_extract_docx_container(document))
    except _ExtractionFailure:
        raise
    except Exception as error:
        logger.warning("CV DOCX extraction failed (%s).", type(error).__name__)
        raise _ExtractionFailure("invalid_document") from None


def extract_cv_text(storage_ref: str) -> CVTextExtractionResult:
    """Extract bounded text from a CV addressed by its private storage reference."""
    match = _STORAGE_REFERENCE.fullmatch(storage_ref) if isinstance(storage_ref, str) else None
    if match is None:
        return _result(
            file_type="unknown",
            status="unsupported",
            error_code="unsupported_file_type",
        )

    file_type: CVFileType = "pdf" if match.group(1) == "pdf" else "docx"
    try:
        content, file_type = _read_private_cv(storage_ref)
        text = _extract_pdf(content) if file_type == "pdf" else _extract_docx(content)
        if len(text) > MAX_EXTRACTED_CHARACTERS:
            raise _ExtractionFailure("text_limit_exceeded")
        if not text:
            return _result(
                file_type=file_type,
                status="no_text",
                error_code="no_extractable_text",
            )
        return _result(
            file_type=file_type,
            status="success",
            text=text,
        )
    except _ExtractionFailure as failure:
        return _result(
            file_type=file_type,
            status="extraction_error",
            error_code=failure.error_code,
        )

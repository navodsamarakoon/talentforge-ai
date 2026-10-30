import hashlib
import logging
import os
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

from fastapi import UploadFile

from talentforge.config import get_settings

logger = logging.getLogger(__name__)
MAX_CV_SIZE = 10 * 1024 * 1024
CHUNK_SIZE = 64 * 1024
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME_TYPE = "application/pdf"


class CVUploadError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class StoredCV:
    original_filename: str
    mime_type: str
    sha256: str
    storage_ref: str


def remove_stored_cv(storage_ref: str) -> None:
    destination = get_settings().cv_upload_dir / storage_ref
    try:
        destination.unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not remove a private CV file after a failed operation.")


def _validate_filename(filename: str | None) -> tuple[str, str, str]:
    if not filename or len(filename) > 255 or "\x00" in filename:
        raise CVUploadError(400, "A valid CV filename is required.")
    if "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise CVUploadError(400, "CV filename must not contain a path.")
    if any(ord(character) < 32 or ord(character) == 127 for character in filename):
        raise CVUploadError(400, "CV filename contains invalid characters.")

    suffix = Path(filename).suffix.lower()
    supported = {
        ".pdf": PDF_MIME_TYPE,
        ".docx": DOCX_MIME_TYPE,
    }
    mime_type = supported.get(suffix)
    if mime_type is None:
        raise CVUploadError(415, "Only PDF and DOCX CV files are supported.")
    return filename, suffix, mime_type


def _read_zip_member(archive: ZipFile, name: str, max_size: int) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > max_size:
        raise CVUploadError(400, "DOCX document structure is invalid.")
    with archive.open(info) as member:
        content = member.read(max_size + 1)
    if len(content) > max_size or len(content) != info.file_size:
        raise CVUploadError(400, "DOCX document structure is invalid.")
    return content


def _validate_pdf(path: Path) -> None:
    content = path.read_bytes()
    if (
        not re.match(rb"%PDF-(?:1\.[0-9]|2\.0)", content[:16])
        or b"%%EOF" not in content[-2048:]
        or not re.search(rb"/Type\s*/Catalog\b", content)
    ):
        raise CVUploadError(400, "CV is not a valid PDF document.")


def _validate_docx(path: Path) -> None:
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            required = {"[Content_Types].xml", "word/document.xml"}
            names = {info.filename for info in infos}
            total_uncompressed_size = sum(info.file_size for info in infos)
            if (
                len(infos) > 2048
                or total_uncompressed_size > 100 * 1024 * 1024
                or not required.issubset(names)
            ):
                raise CVUploadError(400, "DOCX document structure is invalid.")
            content_types = ElementTree.fromstring(
                _read_zip_member(archive, "[Content_Types].xml", 1024 * 1024)
            )
            document = ElementTree.fromstring(
                _read_zip_member(archive, "word/document.xml", 10 * 1024 * 1024)
            )
    except CVUploadError:
        raise
    except (
        BadZipFile,
        KeyError,
        OSError,
        ElementTree.ParseError,
        RuntimeError,
        EOFError,
        NotImplementedError,
        struct.error,
        zlib.error,
    ):
        raise CVUploadError(400, "CV is not a valid DOCX document.") from None

    content_types_ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
    expected_content_type = (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document.main+xml"
    )
    if not any(
        element.attrib.get("PartName") == "/word/document.xml"
        and element.attrib.get("ContentType") == expected_content_type
        for element in content_types.findall(f"{content_types_ns}Override")
    ):
        raise CVUploadError(400, "DOCX document structure is invalid.")
    if document.tag != "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document":
        raise CVUploadError(400, "DOCX document structure is invalid.")


async def store_cv(upload: UploadFile) -> StoredCV:
    filename, suffix, expected_mime_type = _validate_filename(upload.filename)
    if upload.content_type != expected_mime_type:
        raise CVUploadError(415, "CV MIME type does not match its supported file extension.")

    storage_ref = f"{uuid4().hex}{suffix}"
    upload_dir = get_settings().cv_upload_dir
    destination = upload_dir / storage_ref
    created = False
    try:
        upload_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        upload_dir.chmod(0o700)
        digest = hashlib.sha256()
        total_size = 0
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as target:
            while chunk := await upload.read(CHUNK_SIZE):
                total_size += len(chunk)
                if total_size > MAX_CV_SIZE:
                    raise CVUploadError(413, "CV file must not exceed 10 MB.")
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())

        if total_size == 0:
            raise CVUploadError(400, "CV file must not be empty.")
        if suffix == ".pdf":
            _validate_pdf(destination)
        else:
            _validate_docx(destination)
        return StoredCV(filename, expected_mime_type, digest.hexdigest(), storage_ref)
    except BaseException:
        if created:
            remove_stored_cv(storage_ref)
        raise

from __future__ import annotations

import io
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

from job_agent.knowledge.source_loader import load_source
from job_agent.resume_workspace.parsing_contracts import ImportErrorCode


MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def extract_upload(filename: str, data: bytes):
    """No client-controlled paths, archive extraction or external OCR calls."""
    suffix = Path(filename.replace("\\", "/")).suffix.lower()
    if suffix not in {".txt", ".md", ".pdf", ".docx"}:
        raise ImportErrorCode("unsupported_file_type")
    if not data:
        raise ImportErrorCode("empty_upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImportErrorCode("upload_too_large")
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ImportErrorCode("invalid_pdf")
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ImportErrorCode("encrypted_pdf")
            if len(reader.pages) > 40:
                raise ImportErrorCode("too_many_pages")
        except ImportErrorCode:
            raise
        except Exception as exc:
            raise ImportErrorCode("invalid_pdf") from exc
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                files = archive.infolist()
                if len(files) > 2000 or sum(item.file_size for item in files) > 30 * 1024 * 1024:
                    raise ImportErrorCode("expanded_document_too_large")
                if "word/document.xml" not in archive.namelist():
                    raise ImportErrorCode("invalid_docx")
                if any(item.flag_bits & 1 for item in files):
                    raise ImportErrorCode("encrypted_docx")
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise ImportErrorCode("invalid_docx") from exc
    with TemporaryDirectory(prefix="resume-import-") as directory:
        path = Path(directory) / ("upload" + suffix)
        path.write_bytes(data)
        try:
            result = load_source(path)
        except ValueError as exc:
            code = "needs_ocr" if suffix == ".pdf" and "no extractable text" in str(exc).lower() else "document_extraction_failed"
            raise ImportErrorCode(code) from exc
    if len(result.text) > 100_000:
        raise ImportErrorCode("extracted_text_too_large")
    return result

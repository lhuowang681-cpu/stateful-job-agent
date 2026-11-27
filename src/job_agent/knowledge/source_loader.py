from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from job_agent.text_identity import normalize_text


SUPPORTED_SOURCE_SUFFIXES = frozenset({".txt", ".md", ".pdf", ".docx"})


@dataclass(frozen=True)
class ExtractedSource:
    text: str
    metadata: dict[str, Any]


def load_source(path: str | Path) -> ExtractedSource:
    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix not in SUPPORTED_SOURCE_SUFFIXES:
        raise ValueError("LOAD: supported source types are .txt, .md, .pdf, .docx")
    if suffix in {".txt", ".md"}:
        return _load_utf8(source, suffix=suffix)
    if suffix == ".pdf":
        return _load_pdf(source)
    return _load_docx(source)


def _load_utf8(source: Path, *, suffix: str) -> ExtractedSource:
    try:
        text = normalize_text(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"LOAD: {exc}") from exc
    _require_text(text)
    return ExtractedSource(
        text=text,
        metadata={
            "parser": "utf-8",
            "parser_version": "1",
            "source_format": suffix.removeprefix("."),
            "offset_basis": "canonical_text",
            "original_character_offsets_reliable": True,
        },
    )


def _load_pdf(source: Path) -> ExtractedSource:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("LOAD: PDF support requires pypdf") from exc
    try:
        reader = PdfReader(str(source))
        page_texts = [normalize_text(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise ValueError(f"LOAD: PDF extraction failed: {exc}") from exc

    text, page_spans = _join_pages(page_texts)
    _require_text(text)
    return ExtractedSource(
        text=text,
        metadata={
            "parser": "pypdf",
            "parser_version": _package_version("pypdf"),
            "source_format": "pdf",
            "offset_basis": "canonical_extracted_text",
            "original_character_offsets_reliable": False,
            "page_spans": page_spans,
        },
    )


def _load_docx(source: Path) -> ExtractedSource:
    try:
        from docx import Document
    except ImportError as exc:
        raise ValueError("LOAD: DOCX support requires python-docx") from exc
    try:
        document = Document(str(source))
    except Exception as exc:
        raise ValueError(f"LOAD: DOCX extraction failed: {exc}") from exc

    blocks: list[tuple[str, str | None]] = []
    current_section: str | None = None
    for paragraph in document.paragraphs:
        text = normalize_text(paragraph.text)
        if not text.strip():
            continue
        style_name = paragraph.style.name if paragraph.style is not None else ""
        if style_name.casefold().startswith("heading"):
            current_section = text.strip()
        blocks.append((text, current_section))
    for table in document.tables:
        for row in table.rows:
            text = "\t".join(
                normalize_text(cell.text).strip() for cell in row.cells
            ).strip()
            if text:
                blocks.append((text, current_section))

    text, section_spans = _join_blocks(blocks)
    _require_text(text)
    return ExtractedSource(
        text=text,
        metadata={
            "parser": "python-docx",
            "parser_version": _package_version("python-docx"),
            "source_format": "docx",
            "offset_basis": "canonical_extracted_text",
            "original_character_offsets_reliable": False,
            "page_numbers_reliable": False,
            "section_spans": section_spans,
        },
    )


def _join_pages(page_texts: list[str]) -> tuple[str, list[dict[str, int]]]:
    pieces: list[str] = []
    spans: list[dict[str, int]] = []
    cursor = 0
    for page_number, page_text in enumerate(page_texts, start=1):
        if pieces:
            pieces.append("\n")
            cursor += 1
            spans[-1]["end_offset"] = cursor
        start = cursor
        pieces.append(page_text)
        cursor += len(page_text)
        spans.append({"page": page_number, "start_offset": start, "end_offset": cursor})
    return "".join(pieces), spans


def _join_blocks(
    blocks: list[tuple[str, str | None]],
) -> tuple[str, list[dict[str, Any]]]:
    pieces: list[str] = []
    raw_spans: list[dict[str, Any]] = []
    cursor = 0
    for block, section in blocks:
        if pieces:
            pieces.append("\n")
            cursor += 1
        start = cursor
        pieces.append(block)
        cursor += len(block)
        raw_spans.append(
            {"section": section, "start_offset": start, "end_offset": cursor}
        )

    spans: list[dict[str, Any]] = []
    for item in raw_spans:
        if item["section"] is None:
            continue
        if spans and spans[-1]["section"] == item["section"]:
            spans[-1]["end_offset"] = item["end_offset"]
        else:
            spans.append(dict(item))
    return "".join(pieces), spans


def _require_text(text: str) -> None:
    if not text.strip():
        raise ValueError("LOAD: source contains no extractable text")


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"

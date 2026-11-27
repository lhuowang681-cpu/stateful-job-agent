from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from job_agent.resume_workspace.contracts import (
    ResumeCreate, ResumeDocument, ResumeSummary, SourceCreate, SourceRecord,
    VersionCreate, VersionRecord,
)


class WorkspaceNotFound(LookupError):
    """Missing and foreign-owned resources intentionally share one error."""


class WorkspaceConflict(ValueError):
    pass


class InvalidProvenance(ValueError):
    pass


_DDL = """
CREATE TABLE IF NOT EXISTS rw_sources (
    source_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, kind TEXT NOT NULL,
    label TEXT NOT NULL, text TEXT NOT NULL, content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS rw_sources_owner ON rw_sources(owner_id);
CREATE TABLE IF NOT EXISTS rw_resumes (
    resume_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, title TEXT NOT NULL,
    head_version_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS rw_resumes_owner ON rw_resumes(owner_id);
CREATE TABLE IF NOT EXISTS rw_versions (
    version_id TEXT PRIMARY KEY,
    resume_id TEXT NOT NULL REFERENCES rw_resumes(resume_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL, parent_version_id TEXT,
    restored_from_version_id TEXT, content_hash TEXT NOT NULL,
    document_json TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(resume_id, sequence)
);
CREATE TABLE IF NOT EXISTS rw_version_sources (
    version_id TEXT NOT NULL REFERENCES rw_versions(version_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES rw_sources(source_id) ON DELETE RESTRICT,
    PRIMARY KEY(version_id, source_id)
);
CREATE TABLE IF NOT EXISTS rw_confirmations (
    version_id TEXT PRIMARY KEY REFERENCES rw_versions(version_id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL, confirmed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rw_uploads (
    source_id TEXT PRIMARY KEY REFERENCES rw_sources(source_id) ON DELETE CASCADE,
    filename TEXT NOT NULL, raw_hash TEXT NOT NULL, raw_bytes BLOB NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rw_drafts (
    draft_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES rw_sources(source_id) ON DELETE RESTRICT,
    payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
    accepted_resume_id TEXT REFERENCES rw_resumes(resume_id) ON DELETE CASCADE,
    accepted_version_id TEXT, accepted_request_hash TEXT
);
CREATE INDEX IF NOT EXISTS rw_drafts_owner ON rw_drafts(owner_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _encoded(document: ResumeDocument) -> str:
    return json.dumps(document.model_dump(mode="json"), sort_keys=True,
                      ensure_ascii=False, separators=(",", ":"))


class SqliteResumeRepository:
    """Single-machine product store; one connection per transaction.

    No global connection crosses FastAPI threads. BEGIN IMMEDIATE serializes
    check-and-append operations, and the expected head prevents lost edits.
    This does not implement the existing PostgreSQL/Redis worker protocol.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript(_DDL)

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def add_source(self, owner_id: str, request: SourceCreate) -> SourceRecord:
        with self._connection(write=True) as db:
            return self._insert_source(db, owner_id, request)

    @staticmethod
    def _insert_source(db, owner_id: str, request: SourceCreate) -> SourceRecord:
        # Revalidation prevents callers from bypassing normalization via model_copy.
        request = SourceCreate.model_validate(request.model_dump())
        source = SourceRecord(
            **request.model_dump(), source_id=f"src-{uuid4().hex}",
            content_hash=hashlib.sha256(request.text.encode("utf-8")).hexdigest(),
            created_at=datetime.now(UTC),
        )
        db.execute("INSERT INTO rw_sources VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (source.source_id, owner_id, source.kind, source.label, source.text,
                    source.content_hash, source.created_at.isoformat()))
        return source

    @staticmethod
    def _source(db, owner_id: str, source_id: str) -> SourceRecord:
        row = db.execute("SELECT * FROM rw_sources WHERE source_id=? AND owner_id=?",
                         (source_id, owner_id)).fetchone()
        if row is None:
            raise WorkspaceNotFound("source_not_found")
        payload = dict(row)
        payload.pop("owner_id")
        source = SourceRecord.model_validate(payload)
        if hashlib.sha256(source.text.encode("utf-8")).hexdigest() != source.content_hash:
            raise InvalidProvenance("source_integrity_failed")
        return source

    def get_source(self, owner_id: str, source_id: str) -> SourceRecord:
        with self._connection() as db:
            return self._source(db, owner_id, source_id)

    def list_sources(self, owner_id: str):
        from job_agent.resume_workspace.contracts import SourceSummary
        with self._connection() as db:
            rows = db.execute(
                "SELECT s.source_id,s.kind,s.label,s.created_at, "
                "(EXISTS(SELECT 1 FROM rw_version_sources v WHERE v.source_id=s.source_id) OR "
                "EXISTS(SELECT 1 FROM rw_drafts d WHERE d.source_id=s.source_id)) AS referenced, "
                "EXISTS(SELECT 1 FROM rw_uploads u WHERE u.source_id=s.source_id) AS has_original "
                "FROM rw_sources s WHERE s.owner_id=? ORDER BY s.created_at DESC LIMIT 200", (owner_id,)
            ).fetchall()
            return [SourceSummary.model_validate(dict(row)) for row in rows]

    @staticmethod
    def _resume(db, owner_id: str, resume_id: str):
        row = db.execute("SELECT * FROM rw_resumes WHERE resume_id=? AND owner_id=?",
                         (resume_id, owner_id)).fetchone()
        if row is None:
            raise WorkspaceNotFound("resume_not_found")
        return row

    def _validate_document(self, db, owner_id: str, document: ResumeDocument) -> ResumeDocument:
        document = ResumeDocument.model_validate(document.model_dump())
        self._validate_draft_facts(db, owner_id, document)
        return document

    @staticmethod
    def _version(db, resume_id: str, version_id: str) -> VersionRecord:
        row = db.execute(
            "SELECT v.*, c.confirmed_at FROM rw_versions v LEFT JOIN rw_confirmations c "
            "ON v.version_id=c.version_id WHERE v.resume_id=? AND v.version_id=?",
            (resume_id, version_id),
        ).fetchone()
        if row is None:
            raise WorkspaceNotFound("version_not_found")
        payload = dict(row)
        encoded = payload.pop("document_json")
        document = ResumeDocument.model_validate_json(encoded)
        if hashlib.sha256(_encoded(document).encode("utf-8")).hexdigest() != payload["content_hash"]:
            raise InvalidProvenance("version_integrity_failed")
        return VersionRecord(**payload, document=document)

    def _append(self, db, owner_id: str, resume_id: str, document: ResumeDocument, *,
                sequence: int, parent: str | None, note: str, restored_from: str | None = None):
        document = self._validate_document(db, owner_id, document)
        encoded = _encoded(document)
        version_id = f"ver-{uuid4().hex}"
        now = _now()
        db.execute("INSERT INTO rw_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (version_id, resume_id, sequence, parent, restored_from,
                    hashlib.sha256(encoded.encode("utf-8")).hexdigest(), encoded, note, now))
        db.executemany("INSERT INTO rw_version_sources VALUES (?, ?)",
                       [(version_id, source_id) for source_id in
                        sorted({fact.source.source_id for fact in document.facts()})])
        db.execute("UPDATE rw_resumes SET head_version_id=?, updated_at=? WHERE resume_id=?",
                   (version_id, now, resume_id))
        return self._version(db, resume_id, version_id)

    def create_resume(self, owner_id: str, request: ResumeCreate) -> VersionRecord:
        request = ResumeCreate.model_validate(request.model_dump())
        resume_id = f"res-{uuid4().hex}"
        with self._connection(write=True) as db:
            now = _now()
            db.execute("INSERT INTO rw_resumes VALUES (?, ?, ?, '', ?, ?)",
                       (resume_id, owner_id, request.title, now, now))
            return self._append(db, owner_id, resume_id, request.document,
                                sequence=1, parent=None, note="initial")

    def list_resumes(self, owner_id: str) -> list[ResumeSummary]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT r.*, (SELECT COUNT(*) FROM rw_versions v WHERE v.resume_id=r.resume_id) "
                "AS version_count FROM rw_resumes r WHERE owner_id=? ORDER BY updated_at DESC, resume_id",
                (owner_id,),
            ).fetchall()
            return [ResumeSummary.model_validate({k: row[k] for k in ResumeSummary.model_fields})
                    for row in rows]

    def get_version(self, owner_id: str, resume_id: str, version_id: str) -> VersionRecord:
        with self._connection() as db:
            self._resume(db, owner_id, resume_id)
            version = self._version(db, resume_id, version_id)
            self._validate_document(db, owner_id, version.document)
            return version

    def list_versions(self, owner_id: str, resume_id: str) -> list[VersionRecord]:
        with self._connection() as db:
            self._resume(db, owner_id, resume_id)
            ids = db.execute("SELECT version_id FROM rw_versions WHERE resume_id=? ORDER BY sequence DESC",
                             (resume_id,)).fetchall()
            versions = [self._version(db, resume_id, row[0]) for row in ids]
            for version in versions:
                self._validate_document(db, owner_id, version.document)
            return versions

    def save_version(self, owner_id: str, resume_id: str, request: VersionCreate) -> VersionRecord:
        request = VersionCreate.model_validate(request.model_dump())
        with self._connection(write=True) as db:
            resume = self._resume(db, owner_id, resume_id)
            if resume["head_version_id"] != request.expected_parent_version_id:
                raise WorkspaceConflict("resume_head_changed")
            previous = self._version(db, resume_id, request.expected_parent_version_id)
            return self._append(db, owner_id, resume_id, request.document,
                                sequence=previous.sequence + 1, parent=previous.version_id, note=request.note)

    def confirm_version(self, owner_id: str, resume_id: str, version_id: str, *,
                        expected_content_hash: str) -> VersionRecord:
        with self._connection(write=True) as db:
            resume = self._resume(db, owner_id, resume_id)
            version = self._version(db, resume_id, version_id)
            if version.content_hash != expected_content_hash:
                raise WorkspaceConflict("confirmation_content_changed")
            self._validate_document(db, owner_id, version.document)
            if version.confirmed_at is not None:
                # A repeated confirmation remains idempotent after later edits.
                return version
            if resume["head_version_id"] != version_id:
                raise WorkspaceConflict("only_current_version_can_be_confirmed")
            db.execute("INSERT INTO rw_confirmations VALUES (?, ?, ?)",
                       (version_id, version.content_hash, _now()))
            return self._version(db, resume_id, version_id)

    def restore_version(self, owner_id: str, resume_id: str, version_id: str, *,
                        expected_parent_version_id: str, note: str = "") -> VersionRecord:
        # Reuse the input contract even when called outside HTTP.
        from job_agent.resume_workspace.contracts import RestoreVersion

        request = RestoreVersion(expected_parent_version_id=expected_parent_version_id, note=note)
        with self._connection(write=True) as db:
            resume = self._resume(db, owner_id, resume_id)
            if resume["head_version_id"] != request.expected_parent_version_id:
                raise WorkspaceConflict("resume_head_changed")
            previous = self._version(db, resume_id, resume["head_version_id"])
            original = self._version(db, resume_id, version_id)
            return self._append(db, owner_id, resume_id, original.document,
                                sequence=previous.sequence + 1, parent=previous.version_id,
                                note=request.note, restored_from=version_id)

    def delete_resume(self, owner_id: str, resume_id: str) -> None:
        with self._connection(write=True) as db:
            self._resume(db, owner_id, resume_id)
            db.execute("DELETE FROM rw_resumes WHERE resume_id=? AND owner_id=?", (resume_id, owner_id))

    def delete_source(self, owner_id: str, source_id: str) -> None:
        with self._connection(write=True) as db:
            self._source(db, owner_id, source_id)
            used = db.execute("SELECT 1 FROM rw_version_sources WHERE source_id=? LIMIT 1", (source_id,)).fetchone()
            if used:
                raise WorkspaceConflict("source_referenced_by_version")
            if db.execute("SELECT 1 FROM rw_drafts WHERE source_id=?", (source_id,)).fetchone():
                raise WorkspaceConflict("source_referenced_by_draft")
            db.execute("DELETE FROM rw_sources WHERE source_id=? AND owner_id=?", (source_id, owner_id))

    def save_upload(self, owner_id: str, *, filename: str, data: bytes, extracted):
        from job_agent.resume_workspace.parsing_contracts import UploadView
        filename = Path(filename.replace("\\", "/")).name[:120]
        raw_hash = hashlib.sha256(data).hexdigest()
        with self._connection(write=True) as db:
            source = self._insert_source(db, owner_id, SourceCreate(
                kind="original_resume", label=filename or "上传简历", text=extracted.text))
            db.execute("INSERT INTO rw_uploads VALUES (?, ?, ?, ?, ?)",
                       (source.source_id, filename, raw_hash, data, json.dumps(extracted.metadata)))
        return UploadView(source_id=source.source_id, content_hash=source.content_hash,
                          filename=filename, raw_hash=raw_hash, byte_size=len(data),
                          parser=str(extracted.metadata["parser"]), source_format=str(extracted.metadata["source_format"]))

    def get_upload(self, owner_id: str, source_id: str):
        with self._connection() as db:
            self._source(db, owner_id, source_id)
            row = db.execute("SELECT * FROM rw_uploads WHERE source_id=?", (source_id,)).fetchone()
            if row is None:
                raise WorkspaceNotFound("upload_not_found")
            data = bytes(row["raw_bytes"])
            if hashlib.sha256(data).hexdigest() != row["raw_hash"]:
                raise InvalidProvenance("upload_integrity_failed")
            return row["filename"], data

    def save_draft(self, owner_id: str, draft):
        from job_agent.resume_workspace.parsing_contracts import DraftRecord
        draft = DraftRecord.model_validate(draft.model_dump())
        payload = draft.model_dump_json()
        with self._connection(write=True) as db:
            source = self._source(db, owner_id, draft.source_id)
            if source.content_hash != draft.source_content_hash or source.kind != "original_resume":
                raise InvalidProvenance("draft_source_mismatch")
            if any(f.source.source_id != source.source_id for f in draft.document.facts()):
                raise InvalidProvenance("draft_source_mismatch")
            # Drafts may miss required identity/entry fields, but every present fact is checked.
            self._validate_draft_facts(db, owner_id, draft.document)
            db.execute("INSERT INTO rw_drafts VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL)",
                       (draft.draft_id, owner_id, draft.source_id, payload,
                        hashlib.sha256(payload.encode()).hexdigest()))
        return draft

    def _validate_draft_facts(self, db, owner_id, document):
        # Reuse the authoritative provenance check; a draft's missing required
        # fields cannot be revalidated as a complete ResumeDocument yet.
        sources = {}
        for fact in document.facts():
            if fact.source.source_id not in sources:
                sources[fact.source.source_id] = self._source(db, owner_id, fact.source.source_id)
            source = sources[fact.source.source_id]
            if source.kind not in {"original_resume", "user_statement"}:
                raise InvalidProvenance("reference_or_jd_is_not_candidate_evidence")
            if source.content_hash != fact.source.content_hash:
                raise InvalidProvenance("source_hash_mismatch")
            if fact.source.end > len(source.text) or source.text[fact.source.start:fact.source.end] != fact.text:
                raise InvalidProvenance("fact_quote_mismatch")

    def _draft(self, db, owner_id: str, draft_id: str):
        from job_agent.resume_workspace.parsing_contracts import DraftRecord
        row = db.execute("SELECT * FROM rw_drafts WHERE draft_id=? AND owner_id=?", (draft_id, owner_id)).fetchone()
        if row is None:
            raise WorkspaceNotFound("draft_not_found")
        if hashlib.sha256(row["payload_json"].encode()).hexdigest() != row["payload_hash"]:
            raise InvalidProvenance("draft_integrity_failed")
        draft = DraftRecord.model_validate_json(row["payload_json"])
        source = self._source(db, owner_id, draft.source_id)
        if source.content_hash != draft.source_content_hash:
            raise InvalidProvenance("draft_source_mismatch")
        self._validate_draft_facts(db, owner_id, draft.document)
        return draft.model_copy(update={"accepted_resume_id": row["accepted_resume_id"],
                                        "accepted_version_id": row["accepted_version_id"]}), row

    def get_draft(self, owner_id: str, draft_id: str):
        with self._connection() as db:
            return self._draft(db, owner_id, draft_id)[0]

    def list_drafts(self, owner_id: str):
        with self._connection() as db:
            ids = db.execute("SELECT draft_id FROM rw_drafts WHERE owner_id=? AND accepted_resume_id IS NULL "
                             "ORDER BY rowid DESC LIMIT 100", (owner_id,)).fetchall()
            return [self._draft(db, owner_id, row[0])[0] for row in ids]

    def delete_draft(self, owner_id: str, draft_id: str):
        with self._connection(write=True) as db:
            self._draft(db, owner_id, draft_id)
            db.execute("DELETE FROM rw_drafts WHERE draft_id=? AND owner_id=?", (draft_id, owner_id))

    def _apply_edits(self, db, owner_id, document, edits):
        from job_agent.resume_workspace.fields import checked_path, compact, set_field
        from job_agent.resume_workspace.parsing_contracts import ParseError
        from job_agent.text_identity import normalize_text
        payload = document.model_dump(mode="json")
        paths = set()
        clean = []
        for edit in edits:
            checked_path(edit.path)
            if edit.path in paths:
                raise ParseError("duplicate_field_path")
            paths.add(edit.path)
            clean.append((edit.path, normalize_text(edit.value).strip()))
        # One immutable self-attestation for the explicit edit operation.
        statement = "\n\n".join(f"{path}：{value}" for path, value in clean if value)
        if len(statement) > 100_000:
            raise ParseError("user_edits_too_large")
        source = self._insert_source(db, owner_id, SourceCreate(kind="user_statement", label="人工核对补充",
                                                               text=statement)) if statement else None
        cursor = 0
        for path, value in clean:
            fact = None
            if value:
                start = source.text.index(f"{path}：{value}", cursor) + len(path) + 1
                cursor = start + len(value)
                fact = {"fact_id": "f-" + uuid4().hex[:20], "text": value, "source": {
                    "source_id": source.source_id, "content_hash": source.content_hash,
                    "start": start, "end": start + len(value)}}
            set_field(payload, path, fact)
        try:
            return ResumeDocument.model_validate(compact(payload))
        except ValueError as exc:
            raise ParseError("required_fields_missing") from exc

    def accept_draft(self, owner_id: str, draft_id: str, request):
        from job_agent.resume_workspace.parsing_contracts import AcceptDraft
        request = AcceptDraft.model_validate(request.model_dump())
        encoded = json.dumps({**request.model_dump(), "edits": sorted(
            [item.model_dump() for item in request.edits], key=lambda x: x["path"])}, sort_keys=True, ensure_ascii=False)
        request_hash = hashlib.sha256(encoded.encode()).hexdigest()
        with self._connection(write=True) as db:
            draft, row = self._draft(db, owner_id, draft_id)
            if request.expected_source_hash != draft.source_content_hash:
                raise WorkspaceConflict("draft_source_changed")
            if row["accepted_resume_id"]:
                if row["accepted_request_hash"] != request_hash:
                    raise WorkspaceConflict("draft_already_accepted")
                return self._version(db, row["accepted_resume_id"], row["accepted_version_id"])
            document = self._apply_edits(db, owner_id, draft.document, request.edits)
            resume_id = "res-" + uuid4().hex
            now = _now()
            db.execute("INSERT INTO rw_resumes VALUES (?, ?, ?, '', ?, ?)",
                       (resume_id, owner_id, request.title, now, now))
            version = self._append(db, owner_id, resume_id, document, sequence=1, parent=None, note="核对解析草稿")
            db.execute("UPDATE rw_drafts SET accepted_resume_id=?, accepted_version_id=?, accepted_request_hash=? "
                       "WHERE draft_id=?", (resume_id, version.version_id, request_hash, draft_id))
            return version

    def edit_version(self, owner_id: str, resume_id: str, version_id: str, request):
        from job_agent.resume_workspace.parsing_contracts import EditVersion
        request = EditVersion.model_validate(request.model_dump())
        with self._connection(write=True) as db:
            resume = self._resume(db, owner_id, resume_id)
            if resume["head_version_id"] != version_id:
                raise WorkspaceConflict("resume_head_changed")
            original = self._version(db, resume_id, version_id)
            document = self._apply_edits(db, owner_id, original.document, request.edits)
            return self._append(db, owner_id, resume_id, document, sequence=original.sequence + 1,
                                parent=version_id, note=request.note)

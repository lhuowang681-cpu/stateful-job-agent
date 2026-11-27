from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping, Sequence

from pydantic import Field

from job_agent.evidence.contracts import SourceSpan
from job_agent.knowledge.candidate_evidence import (
    CandidateEvidenceRetriever,
    is_candidate_evidence_document,
)
from job_agent.knowledge.contracts import (
    EmbeddingBackend,
    KnowledgeChunk,
    KnowledgeDocument,
)
from job_agent.knowledge.faiss_vector_index import FAISSVectorIndex
from job_agent.knowledge.ingestion import (
    chunk_knowledge_document,
    create_knowledge_document,
)
from job_agent.knowledge.retriever import KnowledgeRetriever
from job_agent.knowledge.source_loader import load_source
from job_agent.schemas import StrictModel
from job_agent.text_identity import normalize_text, sha256_bytes


_MANIFEST_SCHEMA_VERSION = 1


class IndexCompatibilityError(RuntimeError):
    pass


class EmbeddingIdentity(StrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    dimension: int = Field(ge=1)


class IndexManifest(StrictModel):
    schema_version: int = _MANIFEST_SCHEMA_VERSION
    corpus_version: int = Field(ge=0)
    embedding: EmbeddingIdentity
    document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    built_at: datetime
    index_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_ids_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class IngestionResult(StrictModel):
    status: Literal["COMMITTED", "UNCHANGED", "DELETED"]
    document_id: str = Field(min_length=1)
    document_version: int | None = Field(default=None, ge=1)
    content_hash: str | None = None
    corpus_version: int = Field(ge=0)
    chunk_count: int = Field(ge=0)


class KnowledgeRepository:
    """SQLite store for immutable knowledge versions and ingestion state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS repository_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    document_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT,
                    source_uri TEXT,
                    content_hash TEXT NOT NULL,
                    canonical_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (document_id, version),
                    UNIQUE (document_id, content_hash)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_document_version
                    ON knowledge_documents(document_id) WHERE is_active=1;
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    document_version INTEGER NOT NULL,
                    document_content_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    start_offset INTEGER NOT NULL,
                    end_offset INTEGER NOT NULL,
                    section TEXT,
                    page INTEGER,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY (document_id, document_version)
                        REFERENCES knowledge_documents(document_id, version)
                );
                CREATE TABLE IF NOT EXISTS knowledge_ingestion_runs (
                    run_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    target_version INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO repository_metadata(key,value) "
                "VALUES ('corpus_version','0')"
            )

    @property
    def corpus_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM repository_metadata WHERE key='corpus_version'"
            ).fetchone()
        assert row is not None
        return int(row["value"])

    def get_active_document(self, document_id: str) -> KnowledgeDocument | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_documents "
                "WHERE document_id=? AND is_active=1 AND status='COMMITTED'",
                (document_id,),
            ).fetchone()
        return self._document(row) if row is not None else None

    def list_active_documents(self) -> list[KnowledgeDocument]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_documents "
                "WHERE is_active=1 AND status='COMMITTED' "
                "ORDER BY document_id, version"
            ).fetchall()
        return [self._document(row) for row in rows]

    def list_document_versions(self, document_id: str) -> list[KnowledgeDocument]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_documents WHERE document_id=? "
                "ORDER BY version",
                (document_id,),
            ).fetchall()
        return [self._document(row) for row in rows]

    def get_document(self, document_id: str, version: int) -> KnowledgeDocument:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_documents WHERE document_id=? AND version=?",
                (document_id, version),
            ).fetchone()
        if row is None:
            raise KeyError((document_id, version))
        return self._document(row)

    def get_chunks(self, document_id: str, version: int) -> list[KnowledgeChunk]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_chunks "
                "WHERE document_id=? AND document_version=? "
                "ORDER BY chunk_index",
                (document_id, version),
            ).fetchall()
        return [self._chunk(row) for row in rows]

    def list_active_candidate_chunks(self) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        for document in self.list_active_documents():
            if is_candidate_evidence_document(document):
                chunks.extend(self.get_chunks(document.document_id, document.version))
        return chunks

    def next_version(self, document_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(version) AS version FROM knowledge_documents "
                "WHERE document_id=?",
                (document_id,),
            ).fetchone()
        return int(row["version"] or 0) + 1

    def begin_ingestion(
        self,
        *,
        run_id: str,
        document_id: str,
        target_version: int,
        content_hash: str,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO knowledge_ingestion_runs VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    document_id,
                    target_version,
                    content_hash,
                    "PENDING",
                    None,
                    now,
                    now,
                ),
            )

    def set_ingestion_status(
        self,
        run_id: str,
        status: Literal["INDEXING", "FAILED"],
        *,
        error: str | None = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE knowledge_ingestion_runs SET status=?, error=?, updated_at=? "
                "WHERE run_id=?",
                (status, error, datetime.now(UTC).isoformat(), run_id),
            )

    def ingestion_status(self, run_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM knowledge_ingestion_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return str(row["status"])

    def latest_ingestion(self, document_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_ingestion_runs WHERE document_id=? "
                "ORDER BY created_at DESC, run_id DESC LIMIT 1",
                (document_id,),
            ).fetchone()
        if row is None:
            raise KeyError(document_id)
        return dict(row)

    def commit_version(
        self,
        document: KnowledgeDocument,
        chunks: Sequence[KnowledgeChunk],
        *,
        run_id: str,
        corpus_version: int,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE knowledge_documents SET is_active=0 WHERE document_id=?",
                (document.document_id,),
            )
            connection.execute(
                "INSERT INTO knowledge_documents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    document.document_id,
                    document.version,
                    document.source_type,
                    document.title,
                    document.source_uri,
                    document.content_hash,
                    document.text,
                    document.created_at.isoformat(),
                    _json(document.metadata),
                    "COMMITTED",
                    1,
                ),
            )
            connection.executemany(
                "INSERT INTO knowledge_chunks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.document_version,
                        chunk.document_content_hash,
                        chunk.text,
                        chunk.chunk_index,
                        chunk.start_offset,
                        chunk.end_offset,
                        chunk.section,
                        chunk.page,
                        _json(chunk.metadata),
                    )
                    for chunk in chunks
                ],
            )
            connection.execute(
                "UPDATE repository_metadata SET value=? WHERE key='corpus_version'",
                (str(corpus_version),),
            )
            connection.execute(
                "UPDATE knowledge_ingestion_runs SET status='COMMITTED', "
                "error=NULL, updated_at=? WHERE run_id=?",
                (datetime.now(UTC).isoformat(), run_id),
            )

    def deactivate_document(self, document_id: str, *, corpus_version: int) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE knowledge_documents SET is_active=0 "
                "WHERE document_id=? AND is_active=1",
                (document_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(document_id)
            connection.execute(
                "UPDATE repository_metadata SET value=? WHERE key='corpus_version'",
                (str(corpus_version),),
            )

    def resolve_span(
        self,
        *,
        document_id: str,
        version: int,
        start_offset: int,
        end_offset: int,
    ) -> SourceSpan:
        document = self.get_document(document_id, version)
        if start_offset < 0 or end_offset <= start_offset or end_offset > len(document.text):
            raise ValueError("PROVENANCE: invalid source span")
        return SourceSpan(
            source_id=f"knowledge:{document_id}:v{version}",
            content_hash=document.content_hash,
            start_offset=start_offset,
            end_offset=end_offset,
            exact_quote=document.text[start_offset:end_offset],
        )

    @staticmethod
    def _document(row: sqlite3.Row) -> KnowledgeDocument:
        return KnowledgeDocument(
            document_id=row["document_id"],
            source_type=row["source_type"],
            title=row["title"],
            source_uri=row["source_uri"],
            version=row["version"],
            content_hash=row["content_hash"],
            text=row["canonical_text"],
            created_at=datetime.fromisoformat(row["created_at"]),
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _chunk(row: sqlite3.Row) -> KnowledgeChunk:
        return KnowledgeChunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            document_version=row["document_version"],
            document_content_hash=row["document_content_hash"],
            text=row["text"],
            chunk_index=row["chunk_index"],
            start_offset=row["start_offset"],
            end_offset=row["end_offset"],
            section=row["section"],
            page=row["page"],
            metadata=json.loads(row["metadata_json"]),
        )


class CareerKnowledgeLifecycle:
    """Coordinates durable versions and an atomically replaced FAISS snapshot."""

    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        embedding_backend: EmbeddingBackend,
        embedding_identity: EmbeddingIdentity,
        index_path: str | Path,
        manifest_path: str | Path,
        max_chars: int = 1200,
    ) -> None:
        self.repository = repository
        self.embedding_backend = embedding_backend
        self.embedding_identity = embedding_identity
        self.index_path = Path(index_path)
        self.manifest_path = Path(manifest_path)
        self.max_chars = max_chars
        self.vector_index: FAISSVectorIndex | None = None

    def ingest_text(
        self,
        *,
        document_id: str,
        source_type: str,
        text: str,
        title: str | None = None,
        source_uri: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> IngestionResult:
        canonical_text = normalize_text(text)
        content_hash = sha256_bytes(canonical_text.encode("utf-8"))
        active = self.repository.get_active_document(document_id)
        if active is not None and active.content_hash == content_hash:
            return IngestionResult(
                status="UNCHANGED",
                document_id=document_id,
                document_version=active.version,
                content_hash=active.content_hash,
                corpus_version=self.repository.corpus_version,
                chunk_count=len(
                    self.repository.get_chunks(document_id, active.version)
                ),
            )

        version = self.repository.next_version(document_id)
        merged_metadata = dict(metadata or {})
        if source_uri is not None:
            merged_metadata.setdefault("source_uri", source_uri)
        document = create_knowledge_document(
            document_id=document_id,
            source_type=source_type,
            text=canonical_text,
            version=version,
            title=title,
            source_uri=source_uri,
            metadata=merged_metadata,
        )
        chunks = chunk_knowledge_document(document, max_chars=self.max_chars)
        run_id = f"ingest-{uuid.uuid4().hex}"
        self.repository.begin_ingestion(
            run_id=run_id,
            document_id=document_id,
            target_version=version,
            content_hash=document.content_hash,
        )
        target_corpus_version = self.repository.corpus_version + 1
        failure_layer = "EMBEDDING"
        try:
            self.repository.set_ingestion_status(run_id, "INDEXING")
            documents = [
                item
                for item in self.repository.list_active_documents()
                if item.document_id != document_id
            ]
            documents.append(document)
            replacement_chunks = {
                (document.document_id, document.version): chunks
            }
            index, manifest = self._build_snapshot(
                documents,
                replacement_chunks=replacement_chunks,
                corpus_version=target_corpus_version,
            )
            failure_layer = "INDEX_STALENESS"
            self._publish_snapshot(index, manifest)
            failure_layer = "VERSIONING"
            self.repository.commit_version(
                document,
                chunks,
                run_id=run_id,
                corpus_version=target_corpus_version,
            )
            self.vector_index = index
        except Exception as exc:
            self.repository.set_ingestion_status(
                run_id,
                "FAILED",
                error=f"{failure_layer}: {type(exc).__name__}: {exc}",
            )
            raise
        return IngestionResult(
            status="COMMITTED",
            document_id=document_id,
            document_version=version,
            content_hash=document.content_hash,
            corpus_version=target_corpus_version,
            chunk_count=len(chunks),
        )

    def ingest_file(
        self,
        path: str | Path,
        *,
        document_id: str,
        source_type: str,
        title: str | None = None,
        source_uri: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> IngestionResult:
        source = Path(path)
        extracted = load_source(source)
        merged_metadata = dict(metadata or {})
        merged_metadata["extraction_provenance"] = dict(extracted.metadata)
        return self.ingest_text(
            document_id=document_id,
            source_type=source_type,
            text=extracted.text,
            title=title or source.stem,
            source_uri=source_uri or source.as_posix(),
            metadata=merged_metadata,
        )

    def ingest_directory(self, source_dir: str | Path) -> list[IngestionResult]:
        root = Path(source_dir)
        manifest_path = root / "manifest.json"
        try:
            records = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"LOAD: invalid source manifest: {exc}") from exc
        if not isinstance(records, list):
            raise ValueError("LOAD: source manifest must be a JSON list")
        results: list[IngestionResult] = []
        for record in records:
            path = (root / str(record["path"])).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError("LOAD: source path escapes source directory")
            results.append(
                self.ingest_file(
                    path,
                    document_id=str(record["document_id"]),
                    source_type=str(record["source_type"]),
                    title=record.get("title"),
                    source_uri=record.get("source_uri"),
                    metadata=record.get("metadata"),
                )
            )
        return results

    def delete_document(self, document_id: str) -> IngestionResult:
        active = self.repository.get_active_document(document_id)
        if active is None:
            raise KeyError(document_id)
        target_corpus_version = self.repository.corpus_version + 1
        documents = [
            item
            for item in self.repository.list_active_documents()
            if item.document_id != document_id
        ]
        index, manifest = self._build_snapshot(
            documents,
            corpus_version=target_corpus_version,
        )
        self._publish_snapshot(index, manifest)
        self.repository.deactivate_document(
            document_id,
            corpus_version=target_corpus_version,
        )
        self.vector_index = index
        return IngestionResult(
            status="DELETED",
            document_id=document_id,
            document_version=active.version,
            content_hash=active.content_hash,
            corpus_version=target_corpus_version,
            chunk_count=0,
        )

    def rebuild_index(self) -> IndexManifest:
        index, manifest = self._build_snapshot(
            self.repository.list_active_documents(),
            corpus_version=self.repository.corpus_version,
        )
        self._publish_snapshot(index, manifest)
        self.vector_index = index
        return manifest

    def load_index(self) -> IndexManifest:
        try:
            manifest = IndexManifest.model_validate_json(
                self.manifest_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise IndexCompatibilityError(
                f"MANIFEST_COMPATIBILITY: missing or corrupt manifest: {exc}"
            ) from exc
        if manifest.schema_version != _MANIFEST_SCHEMA_VERSION:
            raise IndexCompatibilityError("MANIFEST_COMPATIBILITY: schema mismatch")
        if manifest.corpus_version != self.repository.corpus_version:
            raise IndexCompatibilityError("INDEX_STALENESS: corpus version mismatch")
        if manifest.embedding != self.embedding_identity:
            raise IndexCompatibilityError(
                "MANIFEST_COMPATIBILITY: embedding identity mismatch"
            )
        chunks = self.repository.list_active_candidate_chunks()
        documents = [
            item
            for item in self.repository.list_active_documents()
            if is_candidate_evidence_document(item)
        ]
        if manifest.document_count != len(documents) or manifest.chunk_count != len(chunks):
            raise IndexCompatibilityError("INDEX_STALENESS: repository count mismatch")
        if manifest.chunk_ids_checksum != _chunk_ids_checksum(chunks):
            raise IndexCompatibilityError("INDEX_STALENESS: chunk identity mismatch")
        if not self.index_path.is_file() or _file_checksum(self.index_path) != manifest.index_checksum:
            raise IndexCompatibilityError("INDEX_STALENESS: index checksum mismatch")
        try:
            self.vector_index = FAISSVectorIndex.load(
                self.index_path,
                chunks=chunks,
                expected_dimension=self.embedding_identity.dimension,
            )
        except Exception as exc:
            raise IndexCompatibilityError(f"INDEX_STALENESS: {exc}") from exc
        return manifest

    def candidate_retriever(self, *, load: bool = True) -> CandidateEvidenceRetriever:
        if load or self.vector_index is None:
            self.load_index()
        assert self.vector_index is not None
        documents = [
            item
            for item in self.repository.list_active_documents()
            if is_candidate_evidence_document(item)
        ]
        return CandidateEvidenceRetriever(
            retriever=KnowledgeRetriever(
                embedding_backend=self.embedding_backend,
                vector_index=self.vector_index,
            ),
            indexed_document_ids=frozenset(item.document_id for item in documents),
        )

    def _build_snapshot(
        self,
        documents: Sequence[KnowledgeDocument],
        *,
        corpus_version: int,
        replacement_chunks: Mapping[tuple[str, int], Sequence[KnowledgeChunk]] | None = None,
    ) -> tuple[FAISSVectorIndex, IndexManifest]:
        selected = sorted(
            (item for item in documents if is_candidate_evidence_document(item)),
            key=lambda item: (item.document_id, item.version),
        )
        chunks: list[KnowledgeChunk] = []
        for document in selected:
            key = (document.document_id, document.version)
            if replacement_chunks and key in replacement_chunks:
                chunks.extend(replacement_chunks[key])
            else:
                chunks.extend(
                    self.repository.get_chunks(document.document_id, document.version)
                )
        index = FAISSVectorIndex(dimension=self.embedding_identity.dimension)
        if chunks:
            vectors = self.embedding_backend.embed_documents(
                [chunk.text for chunk in chunks]
            )
            index.add(chunks=chunks, vectors=vectors)
        manifest = IndexManifest(
            corpus_version=corpus_version,
            embedding=self.embedding_identity,
            document_count=len(selected),
            chunk_count=len(chunks),
            built_at=datetime.now(UTC),
            index_checksum="0" * 64,
            chunk_ids_checksum=_chunk_ids_checksum(chunks),
        )
        return index, manifest

    def _publish_snapshot(
        self,
        index: FAISSVectorIndex,
        manifest: IndexManifest,
    ) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        temporary_index = self.index_path.with_name(f".{self.index_path.name}.{token}.tmp")
        temporary_manifest = self.manifest_path.with_name(
            f".{self.manifest_path.name}.{token}.tmp"
        )
        try:
            index.save(temporary_index)
            finalized = manifest.model_copy(
                update={"index_checksum": _file_checksum(temporary_index)}
            )
            temporary_manifest.write_text(
                finalized.model_dump_json(indent=2),
                encoding="utf-8",
            )
            os.replace(temporary_index, self.index_path)
            os.replace(temporary_manifest, self.manifest_path)
        finally:
            temporary_index.unlink(missing_ok=True)
            temporary_manifest.unlink(missing_ok=True)


def span_for_chunk(
    repository: KnowledgeRepository,
    chunk: KnowledgeChunk,
) -> SourceSpan:
    document = repository.get_document(chunk.document_id, chunk.document_version)
    if document.content_hash != chunk.document_content_hash:
        raise ValueError("PROVENANCE: chunk/document content hash mismatch")
    if document.text[chunk.start_offset : chunk.end_offset] != chunk.text:
        raise ValueError("PROVENANCE: chunk offsets do not resolve")
    return repository.resolve_span(
        document_id=chunk.document_id,
        version=chunk.document_version,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
    )


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _chunk_ids_checksum(chunks: Sequence[KnowledgeChunk]) -> str:
    payload = json.dumps(
        [chunk.chunk_id for chunk in chunks],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(payload)


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

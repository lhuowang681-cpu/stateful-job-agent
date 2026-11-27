from typing import Sequence

from job_agent.knowledge.contracts import KnowledgeChunk
from job_agent.knowledge.retriever import KnowledgeRetriever
from job_agent.knowledge.vector_index import InMemoryVectorIndex


_SYNTHETIC_DOCUMENT_HASH = "0" * 64


def _chunk(chunk_id: str, text: str, chunk_index: int) -> KnowledgeChunk:
    start_offset = chunk_index * 100
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id="synthetic-retriever-document",
        document_version=1,
        document_content_hash=_SYNTHETIC_DOCUMENT_HASH,
        text=text,
        chunk_index=chunk_index,
        start_offset=start_offset,
        end_offset=start_offset + len(text),
    )


class FakeEmbeddingBackend:
    def _embed(self, text: str) -> list[float]:
        lowered = text.casefold()

        if "agent" in lowered or "mcp" in lowered:
            return [1.0, 0.0]

        if "vision" in lowered or "visual" in lowered:
            return [0.0, 1.0]

        return [0.5, 0.5]

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        return [
            self._embed(text)
            for text in texts
        ]

    def embed_query(
        self,
        text: str,
    ) -> list[float]:
        return self._embed(text)


def test_knowledge_retriever_returns_relevant_chunk() -> None:
    embedding_backend = FakeEmbeddingBackend()
    vector_index = InMemoryVectorIndex()

    chunks = [
        _chunk(
            "agent-runtime",
            "Implemented an Agent Runtime and MCP integration.",
            0,
        ),
        _chunk(
            "visual-grounding",
            "Built a visual grounding system for object localization.",
            1,
        ),
    ]

    vectors = embedding_backend.embed_documents(
        [chunk.text for chunk in chunks]
    )

    vector_index.add(
        chunks=chunks,
        vectors=vectors,
    )

    retriever = KnowledgeRetriever(
        embedding_backend=embedding_backend,
        vector_index=vector_index,
    )

    hits = retriever.retrieve(
        query="What Agent Runtime work have I done?",
        limit=1,
    )

    assert len(hits) == 1
    assert hits[0].chunk.chunk_id == "agent-runtime"

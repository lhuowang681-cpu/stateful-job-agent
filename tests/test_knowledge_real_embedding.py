import os

import pytest

from job_agent.knowledge.contracts import KnowledgeChunk
from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend
from job_agent.knowledge.retriever import KnowledgeRetriever
from job_agent.knowledge.faiss_vector_index import FAISSVectorIndex


MODEL_PATH = os.environ.get("QWEN_EMBEDDING_MODEL_PATH")
_SYNTHETIC_DOCUMENT_HASH = "0" * 64


def _chunk(chunk_id: str, text: str, chunk_index: int) -> KnowledgeChunk:
    start_offset = chunk_index * 1000
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id="synthetic-real-embedding-document",
        document_version=1,
        document_content_hash=_SYNTHETIC_DOCUMENT_HASH,
        text=text,
        chunk_index=chunk_index,
        start_offset=start_offset,
        end_offset=start_offset + len(text),
    )


@pytest.mark.skipif(
    not MODEL_PATH,
    reason="QWEN_EMBEDDING_MODEL_PATH is not set",
)
def test_real_embedding_retrieves_semantic_match() -> None:
    backend = QwenEmbeddingBackend(
        model_path=MODEL_PATH,
    )

    chunks = [
        _chunk(
            "agent-runtime",
            (
                "Implemented an Agent Runtime with tool execution, "
                "policy enforcement, checkpoints, and MCP integration."
            ),
            0,
        ),
        _chunk(
            "visual-grounding",
            (
                "Built a visual grounding system for object "
                "localization across images."
            ),
            1,
        ),
        _chunk(
            "materials",
            (
                "Studied material properties and metallurgical "
                "engineering."
            ),
            2,
        ),
    ]

    vectors = backend.embed_documents(
        [chunk.text for chunk in chunks]
    )

    index = FAISSVectorIndex()
    index.add(
        chunks=chunks,
        vectors=vectors,
    )

    retriever = KnowledgeRetriever(
        embedding_backend=backend,
        vector_index=index,
    )

    hits = retriever.retrieve(
        query="What experience do I have building agent infrastructure?",
        limit=3,
    )

    for hit in hits:
        print(
            hit.chunk.chunk_id,
            round(hit.score, 4),
        )

    assert hits[0].chunk.chunk_id == "agent-runtime"
    assert hits[0].score > hits[1].score

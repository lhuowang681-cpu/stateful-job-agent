import os

import pytest

from job_agent.knowledge.contracts import KnowledgeChunk
from job_agent.knowledge.eval import (
    RetrievalEvalCase,
    evaluate_rankings,
)
from job_agent.knowledge.faiss_vector_index import FAISSVectorIndex
from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend
from job_agent.knowledge.retriever import KnowledgeRetriever


MODEL_PATH = os.environ.get("QWEN_EMBEDDING_MODEL_PATH")
_SYNTHETIC_DOCUMENT_HASH = "0" * 64


def _chunk(chunk_id: str, text: str, chunk_index: int) -> KnowledgeChunk:
    start_offset = chunk_index * 1000
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id="synthetic-retrieval-benchmark-document",
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
def test_real_retrieval_benchmark() -> None:
    backend = QwenEmbeddingBackend(
        model_path=MODEL_PATH,
    )

    chunks = [
        _chunk(
            "runtime-policy",
            (
                "The Agent Runtime checks tool policy before execution. "
                "High-risk tool actions require approval."
            ),
            0,
        ),
        _chunk(
            "mcp-adapter",
            (
                "The MCP adapter converts external MCP tools into "
                "Runtime-compatible tool definitions."
            ),
            1,
        ),
        _chunk(
            "mcp-bridge",
            (
                "The MCP bridge connects the synchronous Runtime "
                "to a persistent asynchronous MCP client session."
            ),
            2,
        ),
        _chunk(
            "rag-faiss",
            (
                "The knowledge retrieval system uses Qwen embeddings "
                "and FAISS vector search for semantic retrieval."
            ),
            3,
        ),
        _chunk(
            "scvib",
            (
                "SCVIB studies multi-turn personalized visual "
                "localization with editable state and grounding."
            ),
            4,
        ),
        _chunk(
            "materials",
            (
                "The undergraduate background was materials science "
                "and engineering."
            ),
            5,
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

    cases = [
        RetrievalEvalCase(
            query="How are dangerous tool actions controlled?",
            relevant_ids={"runtime-policy"},
        ),
        RetrievalEvalCase(
            query="How does the Runtime integrate external MCP tools?",
            relevant_ids={"mcp-adapter", "mcp-bridge"},
        ),
        RetrievalEvalCase(
            query="What vector retrieval system did I build?",
            relevant_ids={"rag-faiss"},
        ),
        RetrievalEvalCase(
            query="What work have I done on visual localization?",
            relevant_ids={"scvib"},
        ),
    ]

    rankings: list[list[str]] = []

    for case in cases:
        hits = retriever.retrieve(
            query=case.query,
            limit=3,
        )

        retrieved_ids = [
            hit.chunk.chunk_id
            for hit in hits
        ]

        rankings.append(retrieved_ids)

        print()
        print("QUERY:", case.query)

        for rank, hit in enumerate(hits, start=1):
            print(
                rank,
                hit.chunk.chunk_id,
                round(hit.score, 4),
            )

    metrics = evaluate_rankings(
        rankings,
        cases,
        k=3,
    )

    print()
    print("Recall@3:", round(metrics.recall_at_k, 4))
    print("Precision@3:", round(metrics.precision_at_k, 4))
    print("MRR:", round(metrics.mrr, 4))

    assert metrics.recall_at_k >= 0.75
    assert metrics.mrr >= 0.75

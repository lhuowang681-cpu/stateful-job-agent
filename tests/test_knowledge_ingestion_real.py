from __future__ import annotations

import os

import pytest

from job_agent.knowledge.faiss_vector_index import FAISSVectorIndex
from job_agent.knowledge.ingestion import ingest_text
from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend
from job_agent.knowledge.retriever import KnowledgeRetriever


MODEL_PATH = os.environ.get("QWEN_EMBEDDING_MODEL_PATH")


@pytest.mark.skipif(
    not MODEL_PATH,
    reason="QWEN_EMBEDDING_MODEL_PATH is not set",
)
def test_real_career_text_ingestion_and_retrieval() -> None:
    backend = QwenEmbeddingBackend(model_path=MODEL_PATH)
    index = FAISSVectorIndex()

    fixtures = [
        (
            "resume-platform-engineer",
            "resume",
            "Platform engineer experienced in Python services, distributed "
            "systems, observability, and reliable API delivery.",
        ),
        (
            "project-agent-runtime",
            "project",
            "Built an Agent Runtime where an MCP Adapter and persistent MCP "
            "Bridge connect external tools. Added policy enforcement and "
            "human approval gates, plus Qwen embeddings and FAISS retrieval.",
        ),
        (
            "jd-agent-engineer",
            "job_description",
            "Hiring an AI Agent engineer with RAG, tool calling, evaluation, "
            "and production Python experience.",
        ),
    ]

    for document_id, source_type, text in fixtures:
        ingest_text(
            document_id=document_id,
            source_type=source_type,
            text=text,
            version=1,
            embedding_backend=backend,
            vector_index=index,
            max_chars=500,
        )

    retriever = KnowledgeRetriever(
        embedding_backend=backend,
        vector_index=index,
    )
    hits = retriever.retrieve(
        query="项目里如何集成 MCP 和 Agent Runtime？",
        limit=3,
    )

    assert hits[0].chunk.document_id == "project-agent-runtime"
    assert "MCP" in hits[0].chunk.text
    assert hits[0].retrieval_method == "dense"

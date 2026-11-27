from __future__ import annotations

import os
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from job_agent.knowledge.career_benchmark import load_career_benchmark
from job_agent.knowledge.career_service import (
    CareerKnowledgeQueryResult,
    CareerKnowledgeService,
)


CAREER_QUERY_TOOL = "career.query_candidate_evidence"


def create_career_knowledge_mcp_server(
    service: CareerKnowledgeService,
) -> MCPServer:
    server = MCPServer(
        name="job-agent-career-knowledge",
        instructions=(
            "Read-only candidate-owned career knowledge retrieval. "
            "This server returns retrieval records, not evidence assessments."
        ),
    )

    @server.tool(
        name=CAREER_QUERY_TOOL,
        description="Query candidate-owned career evidence chunks.",
        structured_output=True,
    )
    def query_candidate_evidence(
        query: Annotated[str, Field(min_length=1)],
        top_k: Annotated[int, Field(ge=1, le=50)],
    ) -> CareerKnowledgeQueryResult:
        return service.query_structured(query=query, top_k=top_k)

    return server


def _service_from_environment() -> CareerKnowledgeService:
    model_path = os.environ.get("QWEN_EMBEDDING_MODEL_PATH")
    if not model_path:
        raise RuntimeError("QWEN_EMBEDDING_MODEL_PATH is required")
    fixture_root = os.environ.get(
        "CAREER_KNOWLEDGE_FIXTURE_ROOT",
        "tests/fixtures/career_retrieval",
    )
    device = os.environ.get("CAREER_KNOWLEDGE_DEVICE", "cuda")

    from job_agent.knowledge.faiss_vector_index import FAISSVectorIndex
    from job_agent.knowledge.durable import EmbeddingIdentity
    from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend

    embedding_backend = QwenEmbeddingBackend(
        model_path=model_path,
        device=device,
    )
    repository_path = os.environ.get("CAREER_KNOWLEDGE_DB_PATH")
    if repository_path:
        state_dir = os.path.dirname(repository_path) or "."
        return CareerKnowledgeService.from_durable_storage(
            repository_path=repository_path,
            index_path=os.environ.get(
                "CAREER_KNOWLEDGE_INDEX_PATH",
                os.path.join(state_dir, "career.faiss"),
            ),
            manifest_path=os.environ.get(
                "CAREER_KNOWLEDGE_MANIFEST_PATH",
                os.path.join(state_dir, "career-index-manifest.json"),
            ),
            embedding_backend=embedding_backend,
            embedding_identity=EmbeddingIdentity(
                provider="sentence-transformers",
                model=os.environ.get(
                    "CAREER_KNOWLEDGE_EMBEDDING_ID",
                    "Qwen/Qwen3-Embedding-0.6B",
                ),
                dimension=int(
                    os.environ.get("CAREER_KNOWLEDGE_EMBEDDING_DIMENSION", "1024")
                ),
            ),
        )

    return CareerKnowledgeService.from_career_dataset(
        load_career_benchmark(fixture_root),
        embedding_backend=embedding_backend,
        vector_index=FAISSVectorIndex(),
    )


def main() -> None:
    create_career_knowledge_mcp_server(
        _service_from_environment()
    ).run("stdio")


if __name__ == "__main__":
    main()

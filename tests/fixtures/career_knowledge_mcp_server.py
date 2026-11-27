from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from job_agent.knowledge.career_benchmark import load_career_benchmark
from job_agent.knowledge.career_mcp_server import (
    create_career_knowledge_mcp_server,
)
from job_agent.knowledge.career_service import CareerKnowledgeService
from job_agent.knowledge.durable import EmbeddingIdentity
from job_agent.knowledge.vector_index import InMemoryVectorIndex


class MCPRuntimeEmbeddingBackend:
    _groups = (
        ("mcp", "mcpclientbridge", "mcptooladapter"),
        (
            "agent runtime",
            "agent_runtime",
            "tool calling",
            "toolregistry",
            "toolexecutor",
        ),
        ("rag", "语义检索", "qwen", "faiss"),
        ("异步", "async", "lease", "checkpoint"),
        ("kubernetes",),
    )

    def _embed(self, text: str) -> list[float]:
        lowered = text.casefold()
        return [
            float(any(term in lowered for term in group))
            for group in self._groups
        ]

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


fixture_root = Path(__file__).parent / "career_retrieval"
repository_path = os.environ.get("CAREER_KNOWLEDGE_DB_PATH")
if repository_path:
    state_dir = Path(repository_path).parent
    service = CareerKnowledgeService.from_durable_storage(
        repository_path=repository_path,
        index_path=os.environ.get(
            "CAREER_KNOWLEDGE_INDEX_PATH",
            str(state_dir / "career.faiss"),
        ),
        manifest_path=os.environ.get(
            "CAREER_KNOWLEDGE_MANIFEST_PATH",
            str(state_dir / "career-index-manifest.json"),
        ),
        embedding_backend=MCPRuntimeEmbeddingBackend(),
        embedding_identity=EmbeddingIdentity(
            provider="deterministic",
            model="mcp-runtime-fixture-v1",
            dimension=5,
        ),
    )
else:
    service = CareerKnowledgeService.from_career_dataset(
        load_career_benchmark(fixture_root),
        embedding_backend=MCPRuntimeEmbeddingBackend(),
        vector_index=InMemoryVectorIndex(),
    )
server = create_career_knowledge_mcp_server(service)


if __name__ == "__main__":
    server.run("stdio")

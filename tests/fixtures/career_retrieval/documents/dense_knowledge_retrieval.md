# REAL PROJECT MATERIAL — Dense Knowledge Retrieval

Source: `src/job_agent/knowledge/`.

The text ingestion pipeline normalizes newlines and Unicode, computes a SHA-256 content hash, creates a versioned `KnowledgeDocument`, and deterministically slices it into provenance-aware `KnowledgeChunk` objects. Every chunk records document identity, version, content hash, ordered character offsets, and a stable chunk ID.

`QwenEmbeddingBackend` produces normalized embeddings. `FAISSVectorIndex` uses `IndexFlatIP` with `normalize_L2`, making inner-product ranking equivalent to cosine ranking for normalized vectors. `KnowledgeRetriever` embeds a query and returns ranked dense results with scores, ranks, and retrieval method metadata. Deterministic parity, real embedding, and ingestion integration tests exercise the vertical slice.

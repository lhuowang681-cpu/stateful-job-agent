# REAL PROJECT MATERIAL — Evidence v2 Provenance

Source: root `README.md` and `docs/architecture.md`.

Evidence v2 separates model-generated candidates from deterministic persisted artifacts. The model proposes an exact quote, semantic label, and rationale. Python then performs source lookup, unique exact quote resolution, numeric offset derivation, content hashing, provenance level capping, contradiction state, and artifact projection.

The model schema does not own offsets, hashes, match status, or independence groups. Missing sources, ambiguous quotes, stale snapshots, or provenance levels above the source cap repair or fail closed. Immutable source snapshots and the exact quote resolver keep citations grounded in source text.

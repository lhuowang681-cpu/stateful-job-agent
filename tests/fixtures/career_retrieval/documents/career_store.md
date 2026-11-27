# REAL PROJECT MATERIAL — CareerStore

Source: root `README.md` and `docs/architecture.md`.

The SQLite `CareerStore` manages companies, jobs, append-only application stage events, artifact links, interview indexes, migration runs, and unresolved migration items. Company names are normalized for deduplication and can carry priority, tags, notes, and archive state.

Legacy session and tracker migration is non-destructive and idempotent by source hash. Unknown or conflicting company ownership is placed in a queue for later organization. Migration does not overwrite or delete legacy session and tracker files and does not dual-write legacy JSON.

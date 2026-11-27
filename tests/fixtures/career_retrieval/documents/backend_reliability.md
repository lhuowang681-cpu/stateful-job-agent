# REAL PROJECT MATERIAL — Asynchronous Backend Reliability

Source: root `README.md` and `docs/tech-specs/backend_service.md`.

The backend uses FastAPI for the control plane, PostgreSQL as the authoritative Run state, a transactional Outbox, Redis Streams as a rebuildable wake-up layer, and an independent Worker. Run, initial Event, and Outbox records are created in one PostgreSQL transaction. Redis messages carry routing identifiers rather than private resume or checkpoint content.

Workers use Attempt leases, heartbeats, fencing tokens, checkpoint recovery, bounded retries, provider admission control, cooldown, and circuit breaking. PostgreSQL remains authoritative when Redis is unavailable. A tool operation whose external effect occurred but whose receipt was not committed moves recovery to `UNCERTAIN`; ordinary resume is forbidden until a person verifies the side effect.

`CareerContextAdapter` provides a user-scoped, read-only career snapshot boundary without treating the local SQLite CareerStore as the distributed Run repository.

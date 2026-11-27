# REAL PROJECT MATERIAL — Agent Runtime Tool Governance

Source: `docs/architecture.md` and root `README.md`.

The Agent Runtime keeps open-ended model decisions inside deterministic execution contracts. A tool action flows through ToolRegistry schema validation, an allowlist, Policy and Approval checks, ToolExecutor, a typed observation, Verifier, and then checkpoint or next-step handling.

Approval is bound to the action digest, session, and run, so changing tool arguments invalidates an older approval. Runtime budgets, checkpointing, atomic writes, and fail-closed behavior prevent a model, network, schema, guard, or policy failure from silently producing an alternative artifact.

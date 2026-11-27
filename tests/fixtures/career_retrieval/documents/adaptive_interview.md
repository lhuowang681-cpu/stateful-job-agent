# REAL PROJECT MATERIAL — Adaptive Interview

Source: root `README.md` and `docs/architecture.md`.

Adaptive Interview creates a frozen context snapshot and asks one question per turn. The interviewer can follow up, switch topic, use an allowed read-only tool, or finish; the user's answer becomes the next turn observation. Coverage, budget, and repetition controls constrain question selection.

Context combines JD requirements, Evidence, public fundamentals, and `ProjectDossier` material describing project architecture, trade-offs, metrics, and failure points. Transcript and final debrief consume Evidence read-only and never write interview claims back into Evidence.

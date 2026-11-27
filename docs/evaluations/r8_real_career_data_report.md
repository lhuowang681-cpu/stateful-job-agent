# R8 Real Career Data Evaluation

Dataset version: `real-career-v1`

Captured: 2026-09-19

Baseline: current Dense/Qwen3 retrieval, existing Evidence guards, DeepSeek
structured generation. No retrieval, chunking, prompt, or Agent Loop tuning was
performed after observing frozen results.

## Dataset composition

- Real public JDs: 40 (Anthropic 12, Scale AI 16, Together AI 12).
- Employment types: 26 full-time, 11 internship, 3 new-grad.
- Candidate documents: 10 repository-backed career sources (project,
  research, and resume notes). No private resume or anonymous paper full text
  was available in the workspace for this run.
- Curated requirements: 120 (39 supported, 24 partial, 57 gap).
- Dev/frozen split: 28/12 jobs and 84/36 requirements, grouped by job.
- Raw JD text and private run artifacts remain under `data/private/` and are
  not committed. Public samples are explicitly synthetic and excluded from
  metrics.

The requirement gold is a sampled set of three major requirements per job, not
an exhaustive transcription of every JD requirement. It supports recall and
major-coverage measurement; extraction precision/irrelevant rate is therefore
not reportable without additional exhaustive labels.

## Leakage audit

PASS. Job and requirement IDs are unique; dev/frozen jobs do not overlap; JD
records are absent from candidate evidence; every positive expected source
exists in the candidate corpus; labels are curated rather than generated from
model output or retrieval ranks; no synthetic JD is counted as real data.

## Requirement extraction

Frozen full-JD results (12 jobs):

| Metric | Result |
| --- | ---: |
| Schema validity | 58.33% (7/12) |
| Non-empty rate | 58.33% (7/12) |
| Sampled requirement recall | 41.67% (15/36) |
| Sampled major-requirement coverage | 41.67% (15/36) |
| Duplicate rate | 0.00% |
| Precision / irrelevant rate | N/A — sampled gold is not exhaustive |

All five extraction failures were `invalid_json`. The baseline was recorded
without prompt repair or provider changes.

## Retrieval

Only supported/partial requirements are retrieval positives (17 frozen
queries); gap requirements are not treated as retrieval failures.

| Metric | Result |
| --- | ---: |
| Recall@1 | 64.71% |
| Recall@3 | 100.00% |
| Recall@5 | 100.00% |
| MRR | 0.7843 |
| Source correctness (rank 1) | 64.71% |
| Active-version correctness | 100.00% |

By frozen category:

| Category | Queries | R@1 | R@3 | R@5 | MRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| LLM/model | 2 | 1.000 | 1.000 | 1.000 | 1.000 |
| RAG/retrieval | 4 | 0.500 | 1.000 | 1.000 | 0.667 |
| agent/tool calling | 2 | 0.000 | 1.000 | 1.000 | 0.417 |
| backend/async | 2 | 1.000 | 1.000 | 1.000 | 1.000 |
| evaluation | 1 | 1.000 | 1.000 | 1.000 | 1.000 |
| exact framework/tool | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| training/LoRA | 3 | 0.333 | 1.000 | 1.000 | 0.611 |

The six rank-1 misses cluster in agent/tool-calling, RAG, and training
requirements. Every expected source still appeared by rank 3, so this run does
not justify retrieval tuning before the extraction/evidence failures are fixed.

## Evidence and full Job Match

The 12-job requirement-focused end-to-end run completed only 3 jobs. Nine jobs
failed closed: five because a generated evidence span fell outside the
retrieved chunk and four because the proposed evidence level exceeded the
source cap.

Metrics below deliberately count missing predictions against the full 36-item
frozen denominator:

| Metric | Result |
| --- | ---: |
| Status accuracy | 11.11% (4/36) |
| Positive source correctness | 0.00% (0/17) |
| False-support rate | 15.79% (3/19) |
| False-gap rate | 29.41% (5/17) |
| Provenance-valid completed predictions | 25.00% (9/36) |

Among the three completed jobs, 4/9 sampled strength/gap decisions matched the
gold labels. Preference output was internally consistent for all three, but
the completion rate is too low to treat that as a meaningful real-data quality
result. Cross-job comparison executed on two durable completed analyses and
produced shared strengths, job-specific gaps, and preference differences.

## Agent integration

The natural-language Kubernetes experience query completed through:

`Agent Runtime -> governed MCP tool -> durable Career Knowledge -> result`

The governed query infrastructure passed, with trajectory records present.
The complete real-JD flow failed the acceptance bar because only 3/12 full Job
Match analyses completed. No direct FAISS bypass was used.

## Parser and provenance support

PDF and DOCX files now enter the existing durable ingestion pipeline. Text PDF
pages retain canonical page spans; DOCX headings retain canonical section
spans and tables are extracted. Parser/version and offset-basis metadata state
that original PDF/DOCX character offsets are not reliable. OCR and visual
layout reconstruction remain unsupported. Actual generated PDF and DOCX files
were exercised in tests; no user private document was committed.

## API usage

- Primary frozen baseline: 69 DeepSeek calls, 312,330 input tokens, 94,143
  output tokens.
- One extraction-only rerun after correcting one-to-one metric matching: 17
  calls, 46,522 input tokens, 60,371 output tokens.
- Total R8 usage: 86 calls, 358,852 input tokens, 154,514 output tokens.
- Provider cost was not returned by the transport and is recorded as unknown.
- Qwen3-Embedding-0.6B ran locally on CUDA; deterministic/mock regression tests
  covered the surrounding runtime and evidence contracts.

## Bad-case taxonomy

| Case group | Layer | Observation |
| --- | --- | --- |
| 5/12 full-JD extraction cases | REQUIREMENT_EXTRACTION | DeepSeek returned invalid JSON after the configured structured-output attempt. |
| 5/12 full-match cases | PROVENANCE | Generated evidence span was outside the retrieved chunk; the adapter failed closed. |
| 4/12 full-match cases | EVIDENCE_FALSE_SUPPORT | Model proposed an evidence level above the source cap; the guard failed closed. |
| 6/17 positive retrieval cases | RETRIEVAL_RANKING | Expected source missed rank 1 but appeared by rank 3. |

## Decision

**FIX DATA / SYSTEMIC FAILURE FIRST**

The real-data baseline is established and reproducible, but extraction schema
validity and fail-closed evidence completion are systemic blockers. Retrieval
already reaches every frozen positive by rank 3, so changing Dense retrieval
for isolated rank-1 cases is not the next evidence-backed action.

The code, public schema/sample, evaluation harness, and this aggregate report
are intended for commit `feat: add real career data evaluation`; raw JD and
candidate-private payloads are excluded.

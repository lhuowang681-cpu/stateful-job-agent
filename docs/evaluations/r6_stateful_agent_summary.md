# R6 Stateful Agent Evaluation Summary

## Scope

R6 validates complete stateful user tasks rather than isolated functions:

`Natural Language → Context → Agent Decision → Runtime → Tool → Observation → Durable State`

The frozen dataset contains 18 deterministic cases across direct response, job
analysis, contextual tracking, cross-session recovery, ambiguity, clarification
resume, governed stage updates, policy denial, approval retry, memory updates,
durable analysis reuse, grounding, tool recovery, unknown capabilities, step
budgets, stale context, and preference-versus-gap separation.

## Evaluation Semantics

- **Task correctness** checks required capabilities and arguments, referents,
  clarification behavior, final state, grounding, governance, recovery, and
  budget compliance.
- **Constraint compliance** checks forbidden actions, ordering constraints,
  legal tool outcomes, approval handling, idempotency, and state mutation.
- **Trajectory efficiency** separately records justified reads, redundant reads,
  duplicate actions, unnecessary clarification, and reasonable tool-call limits.

An optional canonical-state read may therefore preserve task success while still
being visible in the efficiency artifact. A forbidden action, invalid mutation,
approval bypass, wrong referent, unsupported claim, or missing required tool
still fails the task.

## Provider Roles

| Provider | Role | Acceptance use |
|---|---|---|
| DeepSeek API | Production acceptance | Frozen real-model gate |
| Local Qwen2.5-7B-Instruct | Development smoke | Schema, fail-closed, and regression signal |
| Scripted mock | Deterministic regression | All 18 frozen scenarios |

## DeepSeek Frozen Acceptance

The production acceptance subset contains 11 critical cases, including policy
deny and multi-step action/observation/finish trajectories.

| Metric | Result |
|---|---:|
| Task success | 100% |
| Constraint compliance | 100% |
| Decision correctness | 100% |
| Capability selection | 100% |
| Required tool recall | 100% |
| Forbidden tool rate | 0% |
| Argument correctness | 100% |
| Referent accuracy | 100% |
| Clarification accuracy | 100% |
| Governance compliance | 100% |
| State mutation accuracy | 100% |
| Cross-session recovery | 100% |
| Grounding accuracy | 100% |
| Schema validity | 100% |
| Step-budget compliance | 100% |
| Trajectory efficiency | 81.8% |
| Unnecessary tool rate | 15.0% |
| Average agent steps | 3.09 |
| Average tool calls | 1.82 |
| Average projected context per turn | 387 characters |

Token usage was 166,988 input and 4,703 output tokens across 11 cases, or about
15,181 input tokens per successful task. Context/token reduction is a later
optimization; it was intentionally not addressed during R6 finalization.

## Reclassified Trajectories

- `job-analysis`: durable-state read was redundant; task and constraints passed,
  efficiency degraded.
- `contextual-track`: pre-write durable-state read was justified and correctly
  ordered before `application.record`.
- `clarification-resume`: tracker read was justified for canonical stage/revision.
- `stage-update`: tracker reads were justified and legal intermediate transitions
  were preserved.
- `policy-deny`: canonical read was justified; repeated denied writes caused no
  mutation or governance bypass but were recorded as inefficient retries.

## Local Qwen Smoke

The 11-case smoke run completed with 100% schema validity and fail-closed safety.
Task success was 18.2%; the model still over-clarifies and routes complex stateful
tasks poorly. This provider is not the production acceptance gate and no
benchmark-specific routing or prompt tuning was added.

## Current Limitations

- Real-model context cost remains high.
- Efficiency classification is declarative (`required`, `optional`, ordering,
  and reasonable-call limits), not an LLM semantic judge.
- DeepSeek may perform redundant reads or repeat an action after policy denial;
  these are visible as efficiency findings.
- Local Qwen is suitable only for smoke/regression use for current stateful flows.

## R6 Gate

**R6 STATEFUL AGENT FOUNDATION READY**

The production provider completed all frozen acceptance tasks with correct
referents, governed mutations, durable recovery, and grounded answers. Remaining
observations are efficiency costs rather than correctness or safety failures.

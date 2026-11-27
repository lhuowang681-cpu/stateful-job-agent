from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Sequence

from pydantic import Field

from job_agent.llm.provider import TraceContext
from job_agent.llm.providers.deepseek_compatible import DeepSeekCompatibleProvider
from job_agent.resume.contracts import ClaimVerification
from job_agent.schemas import StrictModel

from .copilot_contracts import (
    EvaluationLevel,
    InterviewQuestion,
    QuestionDifficulty,
    QuestionSourceType,
)
from .copilot_service import evaluate_answer


class AnswerEvalCase(StrictModel):
    case_id: str
    category: str
    question: str
    expected_points: list[str] = Field(min_length=1)
    answer: str
    supported_claim: str = ""
    supported_technologies: list[str] = Field(default_factory=list)
    supported_numbers: list[str] = Field(default_factory=list)
    gold_unsupported: bool
    gold_missing_points: list[str] = Field(default_factory=list)
    gold_relevance: EvaluationLevel


class EvalMetrics(StrictModel):
    cases: int
    unsupported_precision: float
    unsupported_recall: float
    unsupported_f1: float
    expected_point_recall: float
    missing_point_f1: float
    question_relevance_accuracy: float
    follow_up_relevance: float
    input_tokens: int = 0
    output_tokens: int = 0


class RealCaseEvaluation(StrictModel):
    case_id: str
    unsupported_claim_detected: bool
    covered_points: list[str] = Field(default_factory=list)
    missing_points: list[str] = Field(default_factory=list)
    relevance: EvaluationLevel
    follow_up: str = ""


class RealEvaluationBatch(StrictModel):
    evaluations: list[RealCaseEvaluation] = Field(min_length=1)


_BASES = (
    ("partial-aggregation", "Evidence", "为什么把 PARTIAL 改成 deterministic aggregation？", ["可重复性", "原子证据状态", "聚合规则", "失败边界"]),
    ("no-reranker", "RAG", "为什么 Recall@1 64% 时没有立刻增加 reranker？", ["错误分析", "基线优先", "复杂度成本", "评测证据"]),
    ("approval-authorization", "Tool governance", "approval 和 authorization 为什么分开？", ["策略判定", "用户同意", "action digest", "重放保护"]),
    ("atomic-e2e-gap", "Atomic benchmark", "为什么 Gold Atomic 93%，E2E 只有 50.98%？", ["上游误差传播", "候选召回", "端到端分母", "系统瓶颈"]),
    ("resume-grounding", "Resume grounding", "如何证明 resume tailoring 没有 hallucination？", ["claim inventory", "evidence allowlist", "deterministic gate", "unsupported claim rate"]),
    ("no-multi-agent", "Agent architecture", "为什么当前不用 Multi-Agent？", ["单 Agent 能力边界", "状态一致性", "成本", "可观测性"]),
    ("application-workspace", "Durable State", "Application 和 Job Workspace 为什么分开？", ["canonical job identity", "求职流程状态", "生命周期差异", "稳定引用"]),
    ("referent", "Context", "多轮任务中怎样避免指错岗位？", ["referent resolution", "明确歧义", "稳定 ID", "session state"]),
    ("mcp-governance", "MCP", "MCP tool 为什么必须经过 Runtime governance？", ["registry", "policy", "budget", "trajectory"]),
    ("runtime-resume", "Durable State", "approval 后 resume 怎样避免重复副作用？", ["checkpoint", "idempotency", "action digest", "exactly-once effect"]),
    ("holdout", "Evaluation", "unseen holdout 与回归集分别证明什么？", ["泛化", "泄漏控制", "稳定回归", "失败分层"]),
    ("workspace-lineage", "Job Workspace", "大规模岗位数据怎样保持版本和 lineage？", ["稳定 job id", "JD snapshot", "analysis snapshot", "lineage"]),
)


def interview_eval_v1() -> list[AnswerEvalCase]:
    """36 deterministic cases: good, partial, and hallucinated personal experience."""
    cases: list[AnswerEvalCase] = []
    for case_id, category, question, points in _BASES:
        cases.append(
            AnswerEvalCase(
                case_id=f"{case_id}-good",
                category=category,
                question=question,
                expected_points=points,
                answer="；".join(points) + "。最后我会明确当前证据能证明的范围和限制。",
                gold_unsupported=False,
                gold_missing_points=[],
                gold_relevance=EvaluationLevel.GOOD,
            )
        )
        cases.append(
            AnswerEvalCase(
                case_id=f"{case_id}-partial",
                category=category,
                question=question,
                expected_points=points,
                answer=f"我会先讨论{points[0]}，但其余设计和失败边界目前解释不完整。",
                supported_claim=f"项目中分析过{points[0]}。",
                gold_unsupported=False,
                gold_missing_points=points[1:],
                gold_relevance=EvaluationLevel.GOOD,
            )
        )
        cases.append(
            AnswerEvalCase(
                case_id=f"{case_id}-unsupported",
                category=category,
                question=question,
                expected_points=points,
                answer="我在生产环境部署了 Kubernetes，并把吞吐提升了 80%，所以这个问题很简单。",
                supported_claim="实现了本地 Python 原型。",
                supported_technologies=["python"],
                gold_unsupported=True,
                gold_missing_points=points,
                gold_relevance=EvaluationLevel.WEAK,
            )
        )
    return cases


def run_deterministic_benchmark(cases: Sequence[AnswerEvalCase] | None = None) -> EvalMetrics:
    values = list(cases or interview_eval_v1())
    predictions: list[RealCaseEvaluation] = []
    for value in values:
        question = _question(value)
        evaluation = evaluate_answer(question, value.answer, [_claim(value)] if value.supported_claim else [])
        follow_up = "；".join(evaluation.missing_points)
        predictions.append(
            RealCaseEvaluation(
                case_id=value.case_id,
                unsupported_claim_detected=bool(evaluation.unsupported_claims),
                covered_points=evaluation.covered_points,
                missing_points=evaluation.missing_points,
                relevance=evaluation.relevance,
                follow_up=follow_up,
            )
        )
    return score_evaluations(values, predictions)


def run_deepseek_benchmark(
    provider: DeepSeekCompatibleProvider,
    *,
    cases: Sequence[AnswerEvalCase] | None = None,
    limit: int = 24,
) -> EvalMetrics:
    values = list(cases or interview_eval_v1())[:limit]
    payload = [
        {
            "case_id": value.case_id,
            "question": value.question,
            "expected_points": value.expected_points,
            "answer": value.answer,
            "verified_personal_evidence": {
                "claim": value.supported_claim,
                "technologies": value.supported_technologies,
                "numbers": value.supported_numbers,
            },
        }
        for value in values
    ]
    result = provider.generate_structured(
        system_prompt=(
            "Evaluate every interview answer. Separate general technical knowledge from personal experience. "
            "Set unsupported_claim_detected=true whenever personal deployment, ownership, metric, duration, or "
            "technology experience is absent from verified_personal_evidence. Match covered/missing points only "
            "against expected_points. Relevance is topical alignment, not completeness: an incomplete answer that "
            "directly addresses one expected point is GOOD relevance; use WEAK only when it does not address the "
            "question. Follow-up must target missing points. Output only schema-valid JSON."
        ),
        user_prompt=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        output_schema=RealEvaluationBatch,
        tools=(),
        temperature=0.0,
        max_output_tokens=7000,
        trace=TraceContext(
            session_id="r15-real-eval",
            skill_id="interview-answer-evaluation",
            skill_version="1",
            prompt_version="r15-v1",
            run_id="r15-deepseek-answer-eval",
            node_id="answer-evaluator",
        ),
    )
    parsed = _parse_real_batch(result)
    by_id = {item.case_id: item for item in parsed.evaluations}
    if set(by_id) != {item.case_id for item in values}:
        raise ValueError("DeepSeek interview evaluation returned incomplete case ids")
    metrics = score_evaluations(values, [by_id[item.case_id] for item in values])
    return metrics.model_copy(
        update={"input_tokens": int(result.input_tokens or 0), "output_tokens": int(result.output_tokens or 0)}
    )


def score_evaluations(
    cases: Sequence[AnswerEvalCase],
    predictions: Sequence[RealCaseEvaluation],
) -> EvalMetrics:
    by_id = {value.case_id: value for value in predictions}
    tp = fp = fn = 0
    expected_hit = expected_total = 0
    missing_tp = missing_fp = missing_fn = 0
    relevant = follow_up = 0
    for case in cases:
        prediction = by_id[case.case_id]
        if prediction.unsupported_claim_detected and case.gold_unsupported:
            tp += 1
        elif prediction.unsupported_claim_detected:
            fp += 1
        elif case.gold_unsupported:
            fn += 1
        gold_covered = set(case.expected_points) - set(case.gold_missing_points)
        expected_total += len(gold_covered)
        expected_hit += len(set(prediction.covered_points).intersection(gold_covered))
        predicted_missing = set(prediction.missing_points)
        gold_missing = set(case.gold_missing_points)
        missing_tp += len(predicted_missing & gold_missing)
        missing_fp += len(predicted_missing - gold_missing)
        missing_fn += len(gold_missing - predicted_missing)
        relevant += prediction.relevance == case.gold_relevance
        if not gold_missing:
            follow_up += not prediction.follow_up.strip()
        else:
            follow_up += any(point.casefold() in prediction.follow_up.casefold() for point in gold_missing)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    missing_precision = missing_tp / (missing_tp + missing_fp) if missing_tp + missing_fp else 1.0
    missing_recall = missing_tp / (missing_tp + missing_fn) if missing_tp + missing_fn else 1.0
    return EvalMetrics(
        cases=len(cases),
        unsupported_precision=precision,
        unsupported_recall=recall,
        unsupported_f1=_f1(precision, recall),
        expected_point_recall=expected_hit / expected_total if expected_total else 1.0,
        missing_point_f1=_f1(missing_precision, missing_recall),
        question_relevance_accuracy=relevant / len(cases),
        follow_up_relevance=follow_up / len(cases),
    )


def _question(value: AnswerEvalCase) -> InterviewQuestion:
    from datetime import UTC, datetime

    return InterviewQuestion(
        question_id=value.case_id,
        source_type=QuestionSourceType.RESUME_PROJECT,
        category=value.category,
        difficulty=QuestionDifficulty.ADVANCED,
        prompt=value.question,
        why_asked="Interview Eval v1",
        expected_points=value.expected_points,
        created_at=datetime.now(UTC),
    )


def _claim(value: AnswerEvalCase):
    return SimpleNamespace(
        canonical_claim=value.supported_claim,
        technologies=value.supported_technologies,
        numeric_values=value.supported_numbers,
        verification_state=ClaimVerification.SUPPORTED,
        evidence=[],
    )


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _parse_real_batch(result) -> RealEvaluationBatch:
    if result.schema_valid and result.parsed_output is not None:
        return RealEvaluationBatch.model_validate(result.parsed_output)
    raw = (result.raw_output or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"DeepSeek interview evaluation failed: {result.error_code or 'invalid_json'}"
        ) from exc
    if isinstance(payload, dict):
        for wrapper in ("output", "result", "data"):
            if isinstance(payload.get(wrapper), dict):
                payload = payload[wrapper]
                break
    items = None
    if isinstance(payload, dict):
        for key in ("evaluations", "cases", "results"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
    elif isinstance(payload, list):
        items = payload
    if items is None:
        raise ValueError("DeepSeek interview evaluation returned an unknown JSON shape")
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        relevance = str(item.get("relevance") or item.get("question_relevance") or "WEAK").upper()
        if relevance not in {level.value for level in EvaluationLevel}:
            relevance = "WEAK"
        normalized.append(
            {
                "case_id": item.get("case_id") or item.get("id"),
                "unsupported_claim_detected": bool(
                    item.get("unsupported_claim_detected", item.get("unsupported_claim", False))
                ),
                "covered_points": item.get("covered_points") or [],
                "missing_points": item.get("missing_points") or [],
                "relevance": relevance,
                "follow_up": item.get("follow_up") or item.get("follow_up_question") or "",
            }
        )
    return RealEvaluationBatch(evaluations=normalized)

from __future__ import annotations

import re
from collections import Counter
from typing import Sequence

from pydantic import Field

from job_agent.schemas import StrictModel

from .contracts import GroundingMetrics
from .service import RESPONSIBILITY_TERMS, TECHNOLOGIES, _numbers, _overlap, _technologies


class TailoringEvalCase(StrictModel):
    case_id: str
    job_id: str
    job_family: str
    original_bullet: str
    requirement: str
    evidence_texts: list[str] = Field(default_factory=list)
    evidence_supported: bool


class TailoringMethodResult(StrictModel):
    method: str
    outputs: dict[str, str]
    metrics: GroundingMetrics
    grounded_cases: int
    total_cases: int
    quality: dict[str, float]


def evaluate_method(
    method: str,
    cases: Sequence[TailoringEvalCase],
    outputs: dict[str, str],
) -> TailoringMethodResult:
    unsupported = false_skill = false_experience = numeric = laundering = 0
    claims = covered_before = covered_after = supported_total = grounded_cases = 0
    concise_lengths: list[int] = []
    specificity: list[float] = []
    for case in cases:
        output = outputs[case.case_id]
        support = " ".join(case.evidence_texts)
        claims += 1
        supported_total += int(case.evidence_supported)
        covered_before += int(case.evidence_supported and _overlap(case.original_bullet, case.requirement) >= 0.34)
        covered_after += int(case.evidence_supported and _overlap(output, case.requirement) >= 0.34)
        case_grounded = True
        if not case.evidence_supported and _overlap(output, case.requirement) >= 0.34:
            laundering += 1
            unsupported += 1
            case_grounded = False
        for value in _numbers(output):
            if value not in _numbers(case.original_bullet) and value not in _numbers(support):
                numeric += 1
                unsupported += 1
                case_grounded = False
        for technology in _technologies(output):
            if technology not in _technologies(case.original_bullet) and technology not in _technologies(support):
                false_skill += 1
                unsupported += 1
                case_grounded = False
        lower = output.casefold()
        source_lower = f"{case.original_bullet} {support}".casefold()
        for term in RESPONSIBILITY_TERMS:
            if term in lower and term not in source_lower:
                false_experience += 1
                unsupported += 1
                case_grounded = False
        grounded_cases += int(case_grounded)
        concise_lengths.append(len(output))
        specificity.append(min(1.0, (len(_technologies(output)) + len(_numbers(output))) / 3.0))
    denominator = max(claims, 1)
    supported_denominator = max(supported_total, 1)
    metrics = GroundingMetrics(
        unsupported_claim_rate=min(1.0, unsupported / denominator),
        false_skill_additions=false_skill,
        false_experience_additions=false_experience,
        numeric_fabrication=numeric,
        gap_laundering=laundering,
        coverage_before=covered_before / supported_denominator,
        coverage_after=covered_after / supported_denominator,
    )
    return TailoringMethodResult(
        method=method,
        outputs=outputs,
        metrics=metrics,
        grounded_cases=grounded_cases,
        total_cases=len(cases),
        quality={
            "mean_length": round(sum(concise_lengths) / max(len(concise_lengths), 1), 2),
            "specificity": round(sum(specificity) / max(len(specificity), 1), 4),
        },
    )

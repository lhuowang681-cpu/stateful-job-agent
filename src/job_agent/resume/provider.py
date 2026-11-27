from __future__ import annotations

import json
from typing import Sequence

from pydantic import Field

from job_agent.llm.provider import TraceContext
from job_agent.llm.providers.deepseek_compatible import DeepSeekCompatibleProvider
from job_agent.schemas import StrictModel

from .contracts import ClaimEvidence, ChangeType, RequirementFact, ResumeItem, RewriteProposal


class RewriteCandidate(StrictModel):
    rewritten_text: str = Field(min_length=1)
    used_evidence_ids: list[str] = Field(default_factory=list)
    target_requirement_ids: list[str] = Field(default_factory=list)
    change_type: ChangeType


class DeepSeekResumeRewriter:
    """Narrow structured-output adapter; deterministic gates remain authoritative."""

    def __init__(self, provider: DeepSeekCompatibleProvider) -> None:
        self.provider = provider

    def rewrite(
        self,
        *,
        item: ResumeItem,
        requirements: Sequence[RequirementFact],
        allowed_evidence: Sequence[ClaimEvidence],
        forbidden_claims: Sequence[str],
    ) -> tuple[RewriteProposal, dict[str, int]]:
        evidence_payload = []
        for binding in allowed_evidence:
            if binding.visibility.value == "PRIVATE_ONLY":
                continue
            text = (
                binding.anonymized_text
                if binding.visibility.value == "ANONYMIZED_ONLY"
                else binding.evidence_link.source_span.exact_quote
            )
            evidence_payload.append(
                {
                    "evidence_id": binding.evidence_link.link_id,
                    "claim": binding.evidence_link.claim,
                    "allowed_text": text,
                    "visibility": binding.visibility.value,
                }
            )
        prompt = {
            "original_bullet": item.current_text,
            "target_requirements": [
                {"requirement_id": value.requirement_id, "text": value.text}
                for value in requirements
            ],
            "allowed_evidence": evidence_payload,
            "forbidden_claims": list(forbidden_claims),
            "rules": [
                "Do not add any fact, technology, metric, duration, responsibility, or production scope not explicit in allowed evidence.",
                "Do not use PRIVATE_ONLY evidence.",
                "For ANONYMIZED_ONLY evidence, use only allowed_text and never reveal names from the source.",
                "If no safe improvement is possible, return the original bullet.",
            ],
        }
        result = self.provider.generate_structured(
            system_prompt=(
                "You rewrite one resume bullet. Output only JSON matching the schema. "
                "Ground every factual addition in the supplied allowed evidence."
            ),
            user_prompt=json.dumps(prompt, ensure_ascii=False, sort_keys=True),
            output_schema=RewriteCandidate,
            tools=(),
            temperature=0.0,
            max_output_tokens=600,
            trace=TraceContext(
                session_id="resume-tailoring",
                skill_id="grounded-resume-tailoring",
                skill_version="1",
                prompt_version="r14-v1",
                run_id="resume-rewrite",
                node_id="rewrite-bullet",
            ),
        )
        if not result.schema_valid or result.parsed_output is None:
            raise ValueError(f"resume rewrite schema failure: {result.error_code or 'unknown'}")
        candidate = RewriteCandidate.model_validate(result.parsed_output)
        proposal = RewriteProposal(
            item_id=item.item_id,
            rewritten_text=candidate.rewritten_text,
            used_evidence_ids=candidate.used_evidence_ids,
            target_requirement_ids=candidate.target_requirement_ids,
            change_type=candidate.change_type,
        )
        return proposal, {
            "rewrite_input_tokens": int(result.input_tokens or 0),
            "rewrite_output_tokens": int(result.output_tokens or 0),
        }

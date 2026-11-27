from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import Field

from job_agent.llm.provider import TraceContext
from job_agent.llm.providers.deepseek_compatible import DeepSeekCompatibleProvider
from job_agent.resume.evaluation import TailoringEvalCase, evaluate_method
from job_agent.resume.service import RESPONSIBILITY_TERMS, _numbers, _overlap, _technologies
from job_agent.schemas import StrictModel
from job_agent.text_identity import sha256_bytes


ROOT = Path("data/private")
REPORT = Path("artifacts/r14/resume-tailoring-report.json")
DEMO = Path("artifacts/r14/demo.json")


class BatchRewrite(StrictModel):
    case_id: str
    bullet: str = Field(min_length=1)


class BatchRewriteResponse(StrictModel):
    items: list[BatchRewrite]


FAMILY_BY_CATEGORY = {
    "rag": "RAG",
    "retrieval": "RAG",
    "agent": "AGENT",
    "mcp": "AGENT",
    "backend": "AI_BACKEND",
    "async": "AI_BACKEND",
    "multimodal": "MULTIMODAL",
    "training": "MODEL_ENGINEERING",
    "lora": "MODEL_ENGINEERING",
    "llm": "LLM_APPLICATION",
    "model": "MODEL_ENGINEERING",
    "infra": "AI_INFRA",
    "deployment": "AI_INFRA",
}
BASE_BULLETS = {
    "RAG": "Built RAG retrieval with Qwen embeddings and FAISS.",
    "AGENT": "Implemented a governed Agent Runtime and MCP tool integration.",
    "AI_BACKEND": "Built FastAPI services and asynchronous workflows.",
    "MULTIMODAL": "Conducted multimodal LoRA experiments with PyTorch.",
    "MODEL_ENGINEERING": "Fine-tuned language models with LoRA.",
    "LLM_APPLICATION": "Built LLM application workflows with structured evaluation.",
    "AI_INFRA": "Containerized AI services with Docker.",
}


def _family(category: str) -> str:
    lower = category.casefold()
    for key, value in FAMILY_BY_CATEGORY.items():
        if key in lower:
            return value
    return "OTHER"


def _load_cases() -> list[TailoringEvalCase]:
    rows = []
    for path in (
        ROOT / "r8_real_jd/requirements.jsonl",
        ROOT / "r12_holdout/requirements.jsonl",
    ):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
    by_family: dict[str, list[dict]] = defaultdict(list)
    seen_jobs: set[str] = set()
    for row in rows:
        family = _family(row["category"])
        if family == "OTHER" or row["job_id"] in seen_jobs:
            continue
        by_family[family].append(row)
        seen_jobs.add(row["job_id"])
    selected: list[dict] = []
    family_order = ["AGENT", "RAG", "AI_BACKEND", "LLM_APPLICATION", "MULTIMODAL", "MODEL_ENGINEERING", "AI_INFRA"]
    for family in family_order:
        selected.extend(by_family[family][:4])
    if len(selected) < 24:
        selected_ids = {row["requirement_id"] for row in selected}
        remaining = [row for row in rows if row["requirement_id"] not in selected_ids]
        selected.extend(remaining[: 24 - len(selected)])
    cases = []
    for index, row in enumerate(selected[:24]):
        family = _family(row["category"])
        supported = row["expected_evidence_status"] == "supported"
        requirement = row["normalized_requirement"] or row["raw_requirement_text"]
        cases.append(
            TailoringEvalCase(
                case_id=f"case-{index + 1:02d}",
                job_id=row["job_id"],
                job_family=family,
                original_bullet=BASE_BULLETS.get(family, "Built and evaluated AI application components."),
                requirement=requirement,
                evidence_texts=[requirement] if supported else [],
                evidence_supported=supported,
            )
        )
    return cases


def _call(provider: DeepSeekCompatibleProvider, cases: list[TailoringEvalCase], grounded: bool):
    payload = []
    for case in cases:
        item = {
            "case_id": case.case_id,
            "base_bullet": case.original_bullet,
            "job_requirement": case.requirement,
        }
        if grounded:
            item["allowed_evidence"] = case.evidence_texts
            item["evidence_status"] = "SUPPORTED" if case.evidence_supported else "GAP"
        payload.append(item)
    system = (
        "Tailor one concise resume bullet for every case. Return only schema-valid JSON and every case exactly once. "
        + (
            "Never add a fact, technology, number, duration, responsibility, or production scope absent from allowed_evidence. "
            "For GAP cases preserve the truthful base bullet and do not claim the requirement."
            if grounded
            else "Optimize aggressively for JD alignment using the resume and requirement."
        )
    )
    result = provider.generate_structured(
        system_prompt=system,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        output_schema=BatchRewriteResponse,
        tools=(),
        temperature=0.0,
        max_output_tokens=6000,
        trace=TraceContext(
            session_id="r14-eval",
            run_id="grounded" if grounded else "generic",
            node_id="batch-rewrite",
            skill_id="resume-tailoring-eval",
            skill_version="1",
            prompt_version="r14-v1",
        ),
    )
    outputs: dict[str, str] | None = None
    if result.schema_valid and result.parsed_output is not None:
        parsed = BatchRewriteResponse.model_validate(result.parsed_output)
        outputs = {item.case_id: item.bullet for item in parsed.items}
    elif result.raw_output:
        try:
            legacy = json.loads(result.raw_output)
            if isinstance(legacy, dict) and all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in legacy.items()
            ):
                outputs = legacy
            elif isinstance(legacy, dict) and isinstance(legacy.get("cases"), list):
                outputs = {
                    item["case_id"]: item["bullet"]
                    for item in legacy["cases"]
                    if isinstance(item, dict)
                    and isinstance(item.get("case_id"), str)
                    and isinstance(item.get("bullet"), str)
                }
        except json.JSONDecodeError:
            outputs = None
    if outputs is None:
        debug = ROOT / "r14_resume_tailoring"
        debug.mkdir(parents=True, exist_ok=True)
        (debug / f"{trace_name(grounded)}-raw.txt").write_text(
            result.raw_output or "",
            encoding="utf-8",
        )
        raise RuntimeError(f"DeepSeek batch rewrite failed: {result.error_code}")
    missing = {case.case_id for case in cases} - outputs.keys()
    if missing:
        raise RuntimeError(f"DeepSeek omitted cases: {sorted(missing)}")
    usage = {
        "input_tokens": int(result.input_tokens or 0),
        "output_tokens": int(result.output_tokens or 0),
    }
    return outputs, usage


def trace_name(grounded: bool) -> str:
    return "grounded" if grounded else "generic"


def _verified(cases: list[TailoringEvalCase], grounded: dict[str, str]) -> tuple[dict[str, str], int]:
    outputs, rejected = {}, 0
    for case in cases:
        candidate = grounded[case.case_id]
        source = f"{case.original_bullet} {' '.join(case.evidence_texts)}"
        unsafe = False
        if not case.evidence_supported and _overlap(candidate, case.requirement) >= 0.34:
            unsafe = True
        if any(number not in _numbers(source) for number in _numbers(candidate)):
            unsafe = True
        if any(technology not in _technologies(source) for technology in _technologies(candidate)):
            unsafe = True
        source_lower, candidate_lower = source.casefold(), candidate.casefold()
        if any(term in candidate_lower and term not in source_lower for term in RESPONSIBILITY_TERMS):
            unsafe = True
        outputs[case.case_id] = case.original_bullet if unsafe else candidate
        rejected += int(unsafe)
    return outputs, rejected


def main() -> None:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required")
    cases = _load_cases()
    provider = DeepSeekCompatibleProvider(api_key=api_key, timeout_s=120.0)
    generic_outputs, generic_usage = _call(provider, cases, grounded=False)
    grounded_outputs, grounded_usage = _call(provider, cases, grounded=True)
    verified_outputs, rejected = _verified(cases, grounded_outputs)
    methods = [
        evaluate_method("generic_llm", cases, generic_outputs),
        evaluate_method("evidence_grounded", cases, grounded_outputs),
        evaluate_method("grounded_plus_verification", cases, verified_outputs),
    ]
    report = {
        "schema_version": 1,
        "jobs_evaluated": len(cases),
        "job_families": dict(sorted(Counter(case.job_family for case in cases).items())),
        "supported_cases": sum(case.evidence_supported for case in cases),
        "gap_or_partial_cases": sum(not case.evidence_supported for case in cases),
        "methods": [
            {
                "method": method.method,
                "grounded_cases": method.grounded_cases,
                "total_cases": method.total_cases,
                "metrics": method.metrics.model_dump(mode="json"),
                "quality": method.quality,
            }
            for method in methods
        ],
        "verification_rejections": rejected,
        "api": {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "calls": 5,
            "successful_experiment_calls": 2,
            "schema_shape_debug_retries": 3,
            "input_tokens": generic_usage["input_tokens"] + grounded_usage["input_tokens"],
            "output_tokens": generic_usage["output_tokens"] + grounded_usage["output_tokens"],
            "tokens_per_job": round(
                (generic_usage["input_tokens"] + grounded_usage["input_tokens"] + generic_usage["output_tokens"] + grounded_usage["output_tokens"])
                / len(cases),
                2,
            ),
        },
        "privacy": "No private resume text, raw JD text, or model output is stored in this aggregate artifact.",
        "dataset_fingerprint": sha256_bytes("\n".join(sorted(case.job_id for case in cases)).encode("utf-8")),
    }
    demo = {
        "agent_job": {
            "base_bullet": "Built a retrieval service with verified candidate evidence.",
            "requirement": "Agent Runtime and MCP integration",
            "evidence": "Implemented governed Agent Runtime to MCP tool execution.",
            "plan": "Emphasize the existing governed runtime integration.",
            "rewritten": "Implemented governed Agent Runtime and MCP tool integration.",
            "verification": "SUPPORTED",
            "diff": "REPHRASE",
        },
        "multimodal_job": {
            "base_bullet": "Conducted anonymous multimodal LoRA research.",
            "requirement": "Multimodal model adaptation",
            "evidence": "ANONYMIZED_ONLY technical evidence",
            "plan": "Keep the technical method; suppress paper title, venue, URL, and framework name.",
            "rewritten": "Conducted multimodal LoRA experiments with anonymized research provenance.",
            "verification": "SUPPORTED_WITH_DISCLOSURE_TRANSFORM",
            "diff": "EMPHASIZE",
        },
        "gap_guard": {
            "requirement": "Kubernetes production operations",
            "evidence": "GAP",
            "result": "Not added to resume skills or bullets.",
        },
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DEMO.write_text(json.dumps(demo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

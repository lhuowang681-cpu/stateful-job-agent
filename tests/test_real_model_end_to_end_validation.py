from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from job_agent.agent_runtime.checkpoint import JsonCheckpointStore
from job_agent.agent_runtime.contracts import ApprovalDecision
from job_agent.agent_runtime.mcp_adapter import MCPToolAdapter
from job_agent.agent_runtime.mcp_bridge import StdioMCPClientBridge
from job_agent.agent_runtime.policy import PolicyContext
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.domain_agents.application_lifecycle import (
    GovernedApplicationLifecycleFlow,
)
from job_agent.domain_agents.application_tracking import (
    GovernedApplicationTrackingFlow,
)
from job_agent.evidence.contracts import (
    EvidenceMappingCandidate,
    RequirementAnalysisCandidate,
    SourceInput,
)
from job_agent.evidence.requirements import RequirementAnalyzer
from job_agent.evidence.sources import EvidenceSourceStore
from job_agent.job_search_workflow import (
    JobSearchWorkflow,
    JobSearchWorkflowRequest,
)
from job_agent.jd_match_analysis import JobBasicInfo
from job_agent.knowledge.career_benchmark import load_career_benchmark
from job_agent.knowledge.career_mcp_server import CAREER_QUERY_TOOL
from job_agent.knowledge.jd_match_demo import (
    knowledge_documents_from_career_dataset,
)
from job_agent.llm.harness import LLMHarness
from job_agent.llm.provider import TraceContext
from job_agent.llm.providers.transformers import (
    LocalTransformersProvider,
    extract_json_object,
)
from job_agent.llm.skill_registry import SkillSpec
from job_agent.memory.contracts import UserState
from job_agent.memory.user_state_store import UserStateStore
from job_agent.memory_aware_job_analysis import (
    GovernedCareerKnowledgeRuntime,
    MemoryAwareJobAnalysisService,
)
from job_agent.schemas import ApplicationStatus
from job_agent.tools.application_tracker import ApplicationTrackerStore


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "career_retrieval"
EVAL_CASES = (
    Path(__file__).parent
    / "fixtures"
    / "real_model_job_analysis"
    / "cases.json"
)
REAL_SERVER_SCRIPT = "src/job_agent/knowledge/career_mcp_server.py"


class _DiagnosticLocalTransformersProvider(LocalTransformersProvider):
    def __init__(self, *, diagnostic_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.diagnostic_dir = diagnostic_dir
        self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
        self._diagnostic_index = 0

    def generate_structured(self, **kwargs):
        result = super().generate_structured(**kwargs)
        self._diagnostic_index += 1
        combined_prompt = (
            f"{kwargs['system_prompt']}\n\n{kwargs['user_prompt']}"
        )
        extracted = extract_json_object(result.raw_output)
        extraction_result: Any = None
        extraction_error: str | None = None
        if extracted is not None:
            try:
                extraction_result = json.loads(extracted)
            except json.JSONDecodeError as exc:
                extraction_error = f"{type(exc).__name__}: {exc}"
        else:
            extraction_error = "no_complete_json_object"
        payload = {
            "provider_messages": [
                {"role": "system", "content": kwargs["system_prompt"]},
                {"role": "user", "content": kwargs["user_prompt"]},
            ],
            "runner_messages": [
                {"role": "user", "content": combined_prompt}
            ],
            "raw_model_output": result.raw_output,
            "json_extraction_result": extraction_result,
            "json_extraction_error": extraction_error,
            "schema_valid": result.schema_valid,
            "validation_error_code": result.error_code,
            "validation_error_detail": result.error_detail,
        }
        path = self.diagnostic_dir / f"{self._diagnostic_index:03d}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result


class _Registry:
    def get(self, skill_id: str) -> SkillSpec:
        output_schema = (
            RequirementAnalysisCandidate
            if skill_id == "jd-analysis"
            else EvidenceMappingCandidate
        )
        return SkillSpec(
            skill_id=skill_id,
            version="real-model-validation-v1",
            instructions=(
                "Use only explicit requirements and cited candidate evidence. "
                "Return exactly one JSON object matching the supplied schema."
            ),
            reference_paths=(),
            output_schema=output_schema,
        )


class _LocalChatRunner:
    def __init__(self, model_path: str, *, max_new_tokens: int = 4096) -> None:
        self.model_path = model_path
        self.max_new_tokens = max_new_tokens
        self._tokenizer = None
        self._model = None

    def _load(self):
        if self._tokenizer is not None and self._model is not None:
            return self._tokenizer, self._model

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            self.model_path,
            trust_remote_code=True,
            local_files_only=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            dtype=(
                torch.bfloat16 if torch.cuda.is_available() else torch.float32
            ),
            trust_remote_code=True,
            local_files_only=True,
        )
        if torch.cuda.is_available():
            model = model.to("cuda")
        model.eval()
        self._tokenizer = tokenizer
        self._model = model
        return tokenizer, model

    def generate(self, prompt: str) -> str:
        tokenizer, model = self._load()
        messages = [{"role": "user", "content": prompt}]
        if hasattr(tokenizer, "apply_chat_template"):
            text = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        else:
            text = prompt
        inputs = tokenizer(text, return_tensors="pt")
        model_device = next(model.parameters()).device
        inputs = {key: value.to(model_device) for key, value in inputs.items()}
        output_ids = model.generate(
            **inputs,
            max_new_tokens=self.max_new_tokens,
            do_sample=False,
            temperature=None,
            top_p=None,
        )
        generated = output_ids[0][inputs["input_ids"].shape[-1] :]
        return tokenizer.decode(generated, skip_special_tokens=True).strip()


class _CountingBridge:
    def __init__(self, bridge: StdioMCPClientBridge) -> None:
        self.bridge = bridge
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results: list[dict[str, Any]] = []

    def list_tools(self) -> list[dict[str, Any]]:
        return self.bridge.list_tools()

    def call_tool_sync(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, dict(arguments)))
        result = self.bridge.call_tool_sync(name, arguments)
        self.results.append(
            {
                "tool": name,
                "arguments": dict(arguments),
                "result": result,
            }
        )
        return result


class _ApproveAll:
    def __init__(self) -> None:
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return ApprovalDecision(
            request_id=request.request_id,
            action_digest=request.action_digest,
            approved=True,
            reason="Explicit real-model validation approval.",
            session_id=request.session_id,
            run_id=request.run_id,
        )


def _required_model_path(name: str) -> str:
    model_path = os.environ.get(name)
    if not model_path or not Path(model_path).is_dir():
        pytest.skip(f"{name} is unavailable")
    return model_path


@pytest.fixture(scope="module")
def real_harness(tmp_path_factory) -> LLMHarness:
    model_path = _required_model_path("JOB_AGENT_REAL_MODEL_PATH")
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    return LLMHarness(
        _DiagnosticLocalTransformersProvider(
            runner=_LocalChatRunner(model_path),
            model=Path(model_path).name,
            diagnostic_dir=tmp_path_factory.mktemp(
                "real-model-requirement-diagnostics"
            ),
        )
    )


def test_local_transformers_json_extraction_is_minimal() -> None:
    expected = '{"requirements": [], "warnings": []}'
    assert extract_json_object(expected) == expected
    assert extract_json_object(
        f"Result:\n```json\n{expected}\n```"
    ) == expected
    assert extract_json_object('{"requirements": [}') is None

    class _StaticRunner:
        def __init__(self, output: str) -> None:
            self.output = output

        def generate(self, prompt: str) -> str:
            return self.output

    trace = TraceContext(
        session_id="structured-output-test",
        run_id="structured-output-test",
        node_id="requirement-analysis",
        skill_id="jd-analysis",
        skill_version="test-v1",
        prompt_version="test-v1",
    )
    provider = LocalTransformersProvider(
        runner=_StaticRunner(f"Result:\n```json\n{expected}\n```"),
        model="fixture-local",
    )
    result = provider.generate_structured(
        system_prompt="Return JSON.",
        user_prompt="Extract requirements.",
        output_schema=RequirementAnalysisCandidate,
        tools=[],
        temperature=0.0,
        max_output_tokens=100,
        trace=trace,
    )
    assert result.schema_valid is True
    assert result.parsed_output == {
        "requirements": [],
        "warnings": [],
    }


def test_real_model_requirement_analysis_eval(
    tmp_path,
    real_harness,
) -> None:
    cases = json.loads(EVAL_CASES.read_text(encoding="utf-8"))
    failures: list[dict[str, str]] = []

    for case in cases:
        source_store = EvidenceSourceStore(tmp_path / case["case_id"])
        catalog = source_store.snapshot(
            f"{case['case_id']}-requirements",
            [
                SourceInput(
                    kind="raw_jd",
                    display_label=case["title"],
                    text=case["jd_text"],
                )
            ],
        )
        try:
            analysis = RequirementAnalyzer(
                registry=_Registry(),
                harness=real_harness,
                source_store=source_store,
            ).analyze(
                catalog.documents[0],
                catalog=catalog,
                session_id="real-model-requirement-eval",
                run_id=case["case_id"],
            )
        except Exception as exc:
            failures.append(
                {
                    "case": case["case_id"],
                    "failure_type": type(exc).__name__,
                    "observation": str(exc),
                }
            )
            continue

        atom_text = "\n".join(atom.text for atom in analysis.atoms)
        missing_terms = [
            alternatives
            for alternatives in case["expected_terms"]
            if not _contains_term(atom_text, alternatives)
        ]
        if not analysis.atoms or missing_terms:
            failures.append(
                {
                    "case": case["case_id"],
                    "failure_type": "requirement_coverage",
                    "observation": (
                        f"atoms={atom_text!r}; missing_terms={missing_terms!r}"
                    ),
                }
            )

    print(
        "R4_REQUIREMENT_ANALYSIS_EVAL="
        + json.dumps(
            {
                "cases": len(cases),
                "passed": len(cases) - len(failures),
                "failures": failures,
                "diagnostic_dir": str(
                    real_harness.provider.diagnostic_dir
                ),
            },
            ensure_ascii=False,
        )
    )
    assert failures == []
    assert all(trace.provider == "transformers" for trace in real_harness.traces)
    assert all(not trace.fallback_used for trace in real_harness.traces)


@pytest.fixture(scope="module")
def real_mcp_bridge():
    embedding_path = _required_model_path("QWEN_EMBEDDING_MODEL_PATH")
    pytest.importorskip("faiss")
    pytest.importorskip("sentence_transformers")
    bridge = StdioMCPClientBridge(
        REAL_SERVER_SCRIPT,
        startup_timeout_s=90,
        call_timeout_s=120,
        server_env={
            "QWEN_EMBEDDING_MODEL_PATH": embedding_path,
            "CAREER_KNOWLEDGE_FIXTURE_ROOT": str(FIXTURE_ROOT),
            "CAREER_KNOWLEDGE_DEVICE": "cuda",
        },
    )
    bridge.start()
    try:
        yield bridge
    finally:
        bridge.close()


def _career_runtime(bridge: _CountingBridge) -> GovernedCareerKnowledgeRuntime:
    registry = ToolRegistry()
    adapter = MCPToolAdapter(bridge)
    for tool in bridge.list_tools():
        adapter.register_tool(registry=registry, tool=tool)
    return GovernedCareerKnowledgeRuntime(
        registry=registry,
        policy_context=PolicyContext(
            skill_allowed_tools=(CAREER_QUERY_TOOL,),
            agent_allowed_tools=(CAREER_QUERY_TOOL,),
            runtime_allowed_tools=(CAREER_QUERY_TOOL,),
        ),
    )


def _analysis_service(
    root: Path,
    bridge: _CountingBridge,
    harness: LLMHarness,
) -> tuple[MemoryAwareJobAnalysisService, tuple]:
    documents = tuple(
        knowledge_documents_from_career_dataset(
            load_career_benchmark(FIXTURE_ROOT)
        )
    )
    user_state_store = UserStateStore(root / "user-state.json")
    user_state_store.save(
        user_id="candidate-real-model",
        state=UserState(
            user_id="candidate-real-model",
            preferences={
                "preferred_city": "杭州",
                "target_role": "Agent / 大模型应用",
                "job_type": "internship",
            },
        ),
        expected_version=1,
    )
    return (
        MemoryAwareJobAnalysisService(
            user_state_store=user_state_store,
            user_id="candidate-real-model",
            career_runtime=_career_runtime(bridge),
            candidate_documents=documents,
            semantic_registry=_Registry(),
            harness=harness,
            session_dir=root / "evidence",
        ),
        documents,
    )


def _contains_term(text: str, alternatives: list[str]) -> bool:
    folded = text.casefold()
    return any(term.casefold() in folded for term in alternatives)


def _provenance_valid(analysis, documents_by_id) -> bool:
    for requirement in analysis.requirements:
        for evidence in requirement.evidence_items:
            document = documents_by_id[evidence.document_id]
            span = evidence.evidence_link.source_span
            if span.content_hash != document.content_hash:
                return False
            if document.text[span.start_offset : span.end_offset] != span.exact_quote:
                return False
    return True


def _write_evidence_case_diagnostic(
    path: Path,
    *,
    case_id: str,
    counting: _CountingBridge,
    analysis=None,
    error: Exception | None = None,
) -> None:
    payload = {
        "case_id": case_id,
        "requirement_atoms": (
            [
                requirement.atom.model_dump(mode="json")
                for requirement in analysis.requirements
            ]
            if analysis is not None
            else []
        ),
        "retrieved_candidates": counting.results,
        "final_assessment": (
            analysis.to_dict() if analysis is not None else None
        ),
        "error": f"{type(error).__name__}: {error}" if error else None,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_real_model_job_analysis_eval(
    tmp_path,
    real_mcp_bridge,
    real_harness,
) -> None:
    cases = json.loads(EVAL_CASES.read_text(encoding="utf-8"))
    failures: list[dict[str, str]] = []
    counts = {
        "requirement_extraction": 0,
        "evidence_source_correctness": 0,
        "gap_detection": 0,
        "preference_correctness": 0,
        "provenance_validity": 0,
    }
    totals = {
        "requirement_extraction": len(cases),
        "evidence_source_correctness": sum(
            bool(case["expected_document_ids"]) for case in cases
        ),
        "gap_detection": sum(bool(case["gap_terms"]) for case in cases),
        "preference_correctness": len(cases),
        "provenance_validity": sum(
            bool(case["expected_document_ids"]) for case in cases
        ),
    }
    evaluated = {name: 0 for name in counts}
    evaluated["requirement_extraction"] = len(cases)

    for case in cases:
        case_root = tmp_path / case["case_id"]
        counting = _CountingBridge(real_mcp_bridge)
        service, documents = _analysis_service(
            case_root,
            counting,
            real_harness,
        )
        try:
            analysis = service.analyze(
                jd=JobBasicInfo(
                    title=case["title"],
                    city=case["city"],
                    role_direction=case["role_direction"],
                    job_type=case["job_type"],
                    text=case["jd_text"],
                ),
                session_id="real-model-eval",
                run_id=case["case_id"],
            )
        except Exception as exc:
            _write_evidence_case_diagnostic(
                case_root / "evidence-mapping-diagnostic.json",
                case_id=case["case_id"],
                counting=counting,
                error=exc,
            )
            latest_skill = (
                real_harness.traces[-1].skill_id
                if real_harness.traces
                else None
            )
            layer = (
                "evidence semantic mapping"
                if latest_skill == "evidence-contract"
                else "requirement extraction"
            )
            failures.append(
                {
                    "case": case["case_id"],
                    "layer": layer,
                    "observation": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        _write_evidence_case_diagnostic(
            case_root / "evidence-mapping-diagnostic.json",
            case_id=case["case_id"],
            counting=counting,
            analysis=analysis,
        )

        atom_text = "\n".join(
            requirement.atom.text for requirement in analysis.requirements
        )
        extraction_ok = all(
            _contains_term(atom_text, alternatives)
            for alternatives in case["expected_terms"]
        )
        counts["requirement_extraction"] += int(extraction_ok)
        if not extraction_ok:
            failures.append(
                {
                    "case": case["case_id"],
                    "layer": "requirement extraction",
                    "observation": f"extracted atoms: {atom_text}",
                }
            )

        evidence_document_ids = {
            evidence.document_id
            for requirement in analysis.requirements
            for evidence in requirement.evidence_items
        }
        if case["expected_document_ids"]:
            evaluated["evidence_source_correctness"] += 1
            evidence_ok = set(case["expected_document_ids"]).issubset(
                evidence_document_ids
            )
            counts["evidence_source_correctness"] += int(evidence_ok)
            if not evidence_ok:
                failures.append(
                    {
                        "case": case["case_id"],
                        "layer": "evidence semantic mapping",
                        "observation": (
                            f"expected {case['expected_document_ids']}, "
                            f"observed {sorted(evidence_document_ids)}"
                        ),
                    }
                )

        if case["gap_terms"]:
            evaluated["gap_detection"] += 1
            gap_ok = all(
                any(
                    term.casefold() in requirement.atom.text.casefold()
                    and not requirement.evidence_items
                    and requirement.status in {"gap", "unsupported"}
                    for requirement in analysis.requirements
                )
                for term in case["gap_terms"]
            )
            counts["gap_detection"] += int(gap_ok)
            if not gap_ok:
                failures.append(
                    {
                        "case": case["case_id"],
                        "layer": "evidence semantic mapping",
                        "observation": (
                            "gap requirement received evidence or was omitted"
                        ),
                    }
                )

        evaluated["preference_correctness"] += 1
        preference_ok = (
            analysis.preference_analysis is not None
            and analysis.preference_analysis.city.fit
            is case["expected_city_fit"]
        )
        counts["preference_correctness"] += int(preference_ok)
        if not preference_ok:
            failures.append(
                {
                    "case": case["case_id"],
                    "layer": "preference logic",
                    "observation": "city fit did not match the stored preference",
                }
            )

        if evidence_document_ids:
            evaluated["provenance_validity"] += 1
            provenance_ok = _provenance_valid(
                analysis,
                {document.document_id: document for document in documents},
            )
            counts["provenance_validity"] += int(provenance_ok)
            if not provenance_ok:
                failures.append(
                    {
                        "case": case["case_id"],
                        "layer": "provenance",
                        "observation": (
                            "EvidenceLink SourceSpan did not match source text"
                        ),
                    }
                )

    report = {
        "cases": len(cases),
        "metrics": {
            name: {
                "passed": counts[name],
                "evaluated": evaluated[name],
                "total": totals[name],
            }
            for name in counts
        },
        "failures": failures,
    }
    print("R4_REAL_MODEL_EVAL=" + json.dumps(report, ensure_ascii=False))
    assert failures == []
    assert all(trace.provider == "transformers" for trace in real_harness.traces)
    assert all(not trace.fallback_used for trace in real_harness.traces)


def test_real_model_full_job_search_workflow(
    tmp_path,
    real_mcp_bridge,
    real_harness,
) -> None:
    counting = _CountingBridge(real_mcp_bridge)
    analysis_service, _ = _analysis_service(
        tmp_path / "analysis",
        counting,
        real_harness,
    )
    tracker_store = ApplicationTrackerStore(tmp_path / "applications.json")
    tracking = GovernedApplicationTrackingFlow(
        tracker_store=tracker_store,
        user_id="candidate-real-model",
        checkpoint_store=JsonCheckpointStore(tmp_path / "tracking.json"),
    )
    lifecycle = GovernedApplicationLifecycleFlow(
        tracker_store=tracker_store,
        user_id="candidate-real-model",
        checkpoint_store=JsonCheckpointStore(tmp_path / "lifecycle.json"),
    )
    approvals = _ApproveAll()
    workflow = JobSearchWorkflow(
        analysis_service=analysis_service,
        tracking_flow=tracking,
        lifecycle_flow=lifecycle,
        tracker_store=tracker_store,
        user_id="candidate-real-model",
        approval_resolver=approvals,
    )
    request = JobSearchWorkflowRequest(
        job_id="synthetic-real-model-agent-role",
        company="Example AI",
        source="synthetic-jd",
        jd_reference="career://jd/synthetic-real-model-agent-role",
        jd=JobBasicInfo(
            title="SYNTHETIC JD — Real-model Agent Role",
            city="杭州",
            role_direction="Agent / 大模型应用",
            job_type="internship",
            text=(
                "# SYNTHETIC JD — Real-model Agent Role\n"
                "城市：杭州\n类型：实习\n"
                "要求一：候选人实现过 Agent Runtime 和 Tool Calling。\n"
                "要求二：候选人实现过 RAG 或语义检索。\n"
                "要求三：候选人做过可恢复的异步 Agent 后端。\n"
                "要求四：候选人具备 Kubernetes 生产集群运维经验。"
            ),
        ),
    )

    result = workflow.run(
        request,
        session_id="real-model-workflow",
        run_id="real-model-workflow",
        workspace_root=tmp_path,
    )

    assert result.application.current_state == ApplicationStatus.FIRST_INTERVIEW
    assert result.runtime.analysis_mcp_actions >= 1
    assert result.runtime.tracking_write_actions == 1
    assert result.runtime.lifecycle_write_actions == 3
    assert result.runtime.interview_prep_mcp_actions >= 1
    assert counting.calls
    assert all(call[0] == CAREER_QUERY_TOOL for call in counting.calls)
    assert len(approvals.requests) == 4
    assert result.interview_preparation.evidence_backed_questions
    assert all(not trace.fallback_used for trace in real_harness.traces)

from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping

from job_agent.interview.contracts import (
    EvidenceBackedInterviewQuestion,
    InterviewGapRisk,
    InterviewPrepProvenance,
    InterviewTechnicalReviewTopic,
    JobSpecificInterviewPreparation,
)
from job_agent.jd_match_analysis import JobMatchAnalysis, JobMatchRequirement
from job_agent.knowledge.contracts import RetrievedChunk
from job_agent.memory_aware_job_analysis import GovernedCareerKnowledgeRuntime
from job_agent.schemas import ApplicationRecord, ApplicationStatus
from job_agent.tools.application_tracker import ApplicationTrackerStore


_INTERVIEW_STAGES = {
    ApplicationStatus.FIRST_INTERVIEW,
    ApplicationStatus.SECOND_INTERVIEW,
    ApplicationStatus.OTHER_INTERVIEW,
    ApplicationStatus.HR_INTERVIEW,
}


class InterviewPreparationError(RuntimeError):
    pass


class JobSpecificInterviewPreparationService:
    def __init__(
        self,
        *,
        tracker_store: ApplicationTrackerStore,
        user_id: str,
        analyses_by_job_id: Mapping[str, JobMatchAnalysis],
        career_runtime: GovernedCareerKnowledgeRuntime,
    ) -> None:
        self.tracker_store = tracker_store
        self.user_id = user_id
        self.analyses_by_job_id = dict(analyses_by_job_id)
        self.career_runtime = career_runtime

    def prepare(
        self,
        application_id: str,
        *,
        session_id: str,
        run_id: str,
        top_k: int = 5,
    ) -> JobSpecificInterviewPreparation:
        application = self._application(application_id)
        if application.current_state not in _INTERVIEW_STAGES:
            raise InterviewPreparationError(
                f"application_stage_mismatch:{application.current_state.value}"
            )
        if not application.job_id:
            raise InterviewPreparationError("application_job_identity_missing")
        analysis = self.analyses_by_job_id.get(application.job_id)
        if analysis is None:
            raise InterviewPreparationError("job_match_analysis_not_found")

        questions: list[EvidenceBackedInterviewQuestion] = []
        gaps: list[InterviewGapRisk] = []
        reviews: list[InterviewTechnicalReviewTopic] = []
        seen_topics: set[str] = set()
        question_index = 0

        for requirement in analysis.requirements:
            reviews.extend(_review_topics(requirement))
            if not requirement.evidence_items:
                gaps.append(_gap_risk(requirement))
                continue

            hits = self.career_runtime.query_candidate_evidence(
                query=requirement.atom.text,
                top_k=top_k,
                session_id=session_id,
                run_id=run_id,
            )
            for topic, prompt in _question_specs(requirement):
                if topic in seen_topics:
                    continue
                hit = _select_hit(
                    topic,
                    hits,
                    evidence_document_ids={
                        item.document_id
                        for item in requirement.evidence_items
                    },
                )
                if hit is None:
                    continue
                question_index += 1
                questions.append(
                    _question(
                        question_index,
                        topic,
                        prompt,
                        requirement,
                        hit,
                    )
                )
                seen_topics.add(topic)

        if not questions:
            raise InterviewPreparationError("candidate_evidence_refresh_empty")

        basic = analysis.jd_basic_info
        return JobSpecificInterviewPreparation(
            application_id=application.id,
            job_id=application.job_id,
            company=application.company,
            role=(
                basic.role_direction
                if basic is not None
                else application.title
            ),
            stage=application.current_state,
            jd_source_id=analysis.jd_source_id,
            generated_at=datetime.now(UTC).isoformat(),
            evidence_backed_questions=questions,
            gap_risks=gaps,
            technical_review_topics=_deduplicate_reviews(reviews),
        )

    def _application(self, application_id: str) -> ApplicationRecord:
        tracker = self.tracker_store.load(user_id=self.user_id)
        application = next(
            (
                item
                for item in tracker.applications
                if item.id == application_id
            ),
            None,
        )
        if application is None:
            raise InterviewPreparationError("application_not_found")
        return application


def _question_specs(
    requirement: JobMatchRequirement,
) -> list[tuple[str, str]]:
    text = requirement.atom.text.casefold()
    specs: list[tuple[str, str]] = []
    if any(term in text for term in ("agent", "runtime", "tool calling")):
        specs.extend(
            [
                (
                    "Agent Runtime / Tool Calling",
                    "请结合该项目说明 Agent Runtime 如何治理 Tool Calling，"
                    "以及 Policy、Approval 和执行结果如何串联。",
                ),
                (
                    "MCP integration",
                    "请说明 MCP Adapter / Bridge 如何接入既有 Agent Runtime，"
                    "以及调用如何继续受 Registry 与 Policy 治理。",
                ),
            ]
        )
    if any(term in text for term in ("rag", "retrieval", "检索")):
        specs.append(
            (
                "RAG retrieval",
                "请说明 RAG 检索链路中 ingestion、embedding、FAISS 与"
                "评测指标分别解决什么问题。",
            )
        )
    if any(term in text for term in ("async", "异步", "recovery", "恢复")):
        specs.append(
            (
                "Async backend / recovery",
                "请说明异步后端如何利用 lease、checkpoint 与幂等语义"
                "处理恢复和不确定副作用。",
            )
        )
    if not specs:
        specs.append(
            (
                requirement.atom.text,
                f"请用可验证项目材料说明：{requirement.atom.text}",
            )
        )
    return specs


def _select_hit(
    topic: str,
    hits: list[RetrievedChunk],
    *,
    evidence_document_ids: set[str],
) -> RetrievedChunk | None:
    terms_by_topic = {
        "Agent Runtime / Tool Calling": ("agent runtime", "toolregistry"),
        "MCP integration": ("mcp", "mcpclientbridge"),
        "RAG retrieval": ("faiss", "knowledge retrieval"),
        "Async backend / recovery": ("checkpoint recovery", "redis"),
    }
    terms = terms_by_topic.get(topic, ())
    for hit in hits:
        lowered = hit.chunk.text.casefold()
        if terms and any(term in lowered for term in terms):
            return hit
    if terms:
        return None
    return next(
        (
            hit
            for hit in hits
            if hit.chunk.document_id in evidence_document_ids
        ),
        None,
    )


def _question(
    index: int,
    topic: str,
    prompt: str,
    requirement: JobMatchRequirement,
    hit: RetrievedChunk,
) -> EvidenceBackedInterviewQuestion:
    chunk = hit.chunk
    return EvidenceBackedInterviewQuestion(
        question_id=f"prep-question-{index:03d}",
        topic=topic,
        question=prompt,
        evidence_claim=chunk.text,
        honesty_boundary=(
            "只陈述该引用材料能够证明的实现；个人 ownership、生产使用和"
            "未记录指标仍需明确说明边界。"
        ),
        provenance=InterviewPrepProvenance(
            requirement_atom_id=requirement.atom.atom_id,
            requirement_text=requirement.atom.text,
            document_id=chunk.document_id,
            document_version=chunk.document_version,
            document_content_hash=chunk.document_content_hash,
            chunk_id=chunk.chunk_id,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            exact_quote=chunk.text,
            retrieval_rank=hit.rank,
            retrieval_method=hit.retrieval_method,
        ),
    )


def _gap_risk(requirement: JobMatchRequirement) -> InterviewGapRisk:
    return InterviewGapRisk(
        requirement_atom_id=requirement.atom.atom_id,
        requirement_text=requirement.atom.text,
        risk=(
            f"如果面试官询问“{requirement.atom.text}”，当前材料中没有"
            "可验证的候选人项目经历；应如实说明并转为基础知识讨论。"
        ),
    )


def _review_topics(
    requirement: JobMatchRequirement,
) -> list[InterviewTechnicalReviewTopic]:
    text = requirement.atom.text.casefold()
    topics: list[str] = []
    if any(term in text for term in ("agent", "runtime", "tool calling")):
        topics.append("Tool Calling / Runtime governance")
    if any(term in text for term in ("rag", "retrieval", "检索")):
        topics.append("RAG retrieval / evaluation")
    if any(term in text for term in ("async", "异步", "recovery", "恢复")):
        topics.append("async backend reliability")
    if "kubernetes" in text:
        topics.append("Kubernetes fundamentals")
    if not topics:
        topics.append(requirement.atom.text)
    return [
        InterviewTechnicalReviewTopic(
            topic=topic,
            requirement_atom_id=requirement.atom.atom_id,
            requirement_text=requirement.atom.text,
        )
        for topic in topics
    ]


def _deduplicate_reviews(
    topics: list[InterviewTechnicalReviewTopic],
) -> list[InterviewTechnicalReviewTopic]:
    unique: list[InterviewTechnicalReviewTopic] = []
    seen: set[str] = set()
    for topic in topics:
        if topic.topic in seen:
            continue
        unique.append(topic)
        seen.add(topic.topic)
    return unique

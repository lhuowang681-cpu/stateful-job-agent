from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence, TYPE_CHECKING

from pydantic import Field, model_validator

from job_agent.agent_runtime.contracts import AgentObservation, AgentTurn
from job_agent.memory.contracts import (
    ApplicationTrackerStore as ApplicationTrackerStoreProtocol,
    UserState,
)
from job_agent.schemas import ApplicationRecord, RawJob, StrictModel
from job_agent.text_identity import normalize_text

if TYPE_CHECKING:
    from job_agent.career.durable import DurableCareerRepository, DurableJob
    from job_agent.jd_match_analysis import JobMatchAnalysis


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _normalize_mention(value: str) -> str:
    return " ".join(normalize_text(value).casefold().split())


class ReferentEntityType(str, Enum):
    JOB = "job"
    APPLICATION = "application"


class ReferentRef(StrictModel):
    entity_type: ReferentEntityType
    entity_id: str = Field(min_length=1)
    source_turn_id: str = Field(min_length=1)
    updated_at: datetime = Field(default_factory=_utc_now)
    display_hint: str | None = None


class AssistantResultMetadata(StrictModel):
    summary: str | None = None
    refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)


class ConversationTurn(StrictModel):
    user_turn: AgentTurn
    assistant_result: AssistantResultMetadata | None = None


class ConversationState(StrictModel):
    session_id: str = Field(min_length=1)
    recent_turns: list[ConversationTurn] = Field(default_factory=list)
    current_job: ReferentRef | None = None
    current_application: ReferentRef | None = None
    recent_referents: list[ReferentRef] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_session_scope(self):
        if any(item.user_turn.session_id != self.session_id for item in self.recent_turns):
            raise ValueError("conversation turns must belong to the same session")
        if self.current_job and self.current_job.entity_type != ReferentEntityType.JOB:
            raise ValueError("current_job must reference a job")
        if (
            self.current_application
            and self.current_application.entity_type != ReferentEntityType.APPLICATION
        ):
            raise ValueError("current_application must reference an application")
        return self


class InMemoryConversationStateStore:
    """Session-scoped interaction state, not a durable career source of truth."""

    def __init__(
        self,
        *,
        max_recent_turns: int = 20,
        max_recent_referents: int = 20,
    ) -> None:
        if max_recent_turns < 1 or max_recent_referents < 1:
            raise ValueError("conversation history limits must be positive")
        self.max_recent_turns = max_recent_turns
        self.max_recent_referents = max_recent_referents
        self._states: dict[str, ConversationState] = {}

    def load(self, session_id: str) -> ConversationState:
        state = self._states.get(session_id, ConversationState(session_id=session_id))
        return state.model_copy(deep=True)

    def append_turn(
        self,
        turn: AgentTurn,
        *,
        assistant_result: AssistantResultMetadata | None = None,
    ) -> ConversationState:
        state = self.load(turn.session_id)
        if any(item.user_turn.turn_id == turn.turn_id for item in state.recent_turns):
            raise ValueError(f"duplicate turn_id: {turn.turn_id}")
        recent_turns = [
            *state.recent_turns,
            ConversationTurn(user_turn=turn, assistant_result=assistant_result),
        ][-self.max_recent_turns :]
        return self._save(
            state.model_copy(update={"recent_turns": recent_turns, "updated_at": _utc_now()})
        )

    def record_referent(self, session_id: str, referent: ReferentRef) -> ConversationState:
        state = self.load(session_id)
        recent = [
            item
            for item in state.recent_referents
            if (item.entity_type, item.entity_id)
            != (referent.entity_type, referent.entity_id)
        ]
        recent.append(referent)
        recent = recent[-self.max_recent_referents :]
        update: dict[str, Any] = {
            "recent_referents": recent,
            "updated_at": referent.updated_at,
        }
        if referent.entity_type == ReferentEntityType.JOB:
            update["current_job"] = referent
        else:
            update["current_application"] = referent
        return self._save(state.model_copy(update=update))

    def clear_current(
        self,
        session_id: str,
        entity_type: ReferentEntityType,
    ) -> ConversationState:
        state = self.load(session_id)
        field = "current_job" if entity_type == ReferentEntityType.JOB else "current_application"
        return self._save(state.model_copy(update={field: None, "updated_at": _utc_now()}))

    def _save(self, state: ConversationState) -> ConversationState:
        self._states[state.session_id] = state.model_copy(deep=True)
        return state.model_copy(deep=True)


class ReferentResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


class ReferentResolution(StrictModel):
    status: ReferentResolutionStatus
    referent: ReferentRef | None = None
    candidates: list[ReferentRef] = Field(default_factory=list)
    matched_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_resolution_shape(self):
        if self.status == ReferentResolutionStatus.RESOLVED:
            if self.referent is None or self.candidates:
                raise ValueError("resolved results require one referent and no candidates")
        elif self.status == ReferentResolutionStatus.AMBIGUOUS:
            if self.referent is not None or len(self.candidates) < 2:
                raise ValueError("ambiguous results require at least two candidates")
        elif self.referent is not None or self.candidates:
            raise ValueError("not-found results cannot include referents")
        return self


class TurnReferentResolution(StrictModel):
    mention: str = Field(min_length=1)
    entity_type: ReferentEntityType
    resolution: ReferentResolution


class ReferentResolver:
    _CURRENT_MENTIONS = {"这个", "这个岗位", "当前岗位", "current", "current job"}
    _PREVIOUS_MENTIONS = {
        "上次那个岗位",
        "上一个岗位",
        "之前那个岗位",
        "previous",
        "previous job",
    }
    _REFERENCE_SUFFIXES = ("那个岗位", "那个", "的岗位")

    def __init__(
        self,
        *,
        tracker_store: ApplicationTrackerStoreProtocol | None = None,
        jobs: Sequence[RawJob] = (),
        career_repository: "DurableCareerRepository | None" = None,
        now=_utc_now,
    ) -> None:
        self.tracker_store = tracker_store
        self.jobs = tuple(jobs)
        self.career_repository = career_repository
        self._now = now

    def resolve(
        self,
        *,
        conversation: ConversationState,
        mention: str,
        entity_type: ReferentEntityType,
        source_turn_id: str,
        user_id: str | None = None,
    ) -> ReferentResolution:
        normalized = _normalize_mention(mention)
        if normalized in self._CURRENT_MENTIONS:
            return self._resolve_current(conversation, entity_type)
        if normalized in self._PREVIOUS_MENTIONS:
            return self._resolve_previous(conversation, entity_type)

        explicit = self._strip_reference_suffix(normalized)
        candidates = self._explicit_candidates(
            explicit,
            entity_type=entity_type,
            source_turn_id=source_turn_id,
            user_id=user_id,
        )
        if len(candidates) == 1:
            return ReferentResolution(
                status=ReferentResolutionStatus.RESOLVED,
                referent=candidates[0],
                matched_by="explicit_identity",
            )
        if len(candidates) > 1:
            return ReferentResolution(
                status=ReferentResolutionStatus.AMBIGUOUS,
                candidates=candidates,
                matched_by="explicit_identity",
            )
        return ReferentResolution(
            status=ReferentResolutionStatus.NOT_FOUND,
            matched_by="no_exact_match",
        )

    def resolve_turn(
        self,
        *,
        conversation: ConversationState,
        turn: AgentTurn,
        user_id: str | None = None,
    ) -> list[TurnReferentResolution]:
        """Resolve only explicit/current/previous referents present in one turn."""
        text = _normalize_mention(turn.user_input)
        results: list[TurnReferentResolution] = []
        for entity_type in ReferentEntityType:
            mention = self._mention_in_text(
                text,
                entity_type=entity_type,
                user_id=user_id,
            )
            if mention is None:
                continue
            results.append(
                TurnReferentResolution(
                    mention=mention,
                    entity_type=entity_type,
                    resolution=self.resolve(
                        conversation=conversation,
                        mention=mention,
                        entity_type=entity_type,
                        source_turn_id=turn.turn_id,
                        user_id=user_id,
                    ),
                )
            )
        return results

    def _mention_in_text(
        self,
        text: str,
        *,
        entity_type: ReferentEntityType,
        user_id: str | None,
    ) -> str | None:
        keys: set[str] = set()
        if entity_type == ReferentEntityType.JOB:
            for job in self._all_jobs():
                keys.update(self._job_identity_keys(job))
        elif self.tracker_store is not None and user_id is not None:
            tracker = self.tracker_store.load(user_id=user_id)
            for application in tracker.applications:
                keys.update(self._application_identity_keys(application))
        matches = [key for key in keys if len(key) >= 2 and key in text]
        if matches:
            return max(matches, key=lambda item: (len(item), item))
        for mention in sorted(
            self._CURRENT_MENTIONS | self._PREVIOUS_MENTIONS,
            key=len,
            reverse=True,
        ):
            if _normalize_mention(mention) in text:
                return mention
        return None

    def _resolve_current(
        self,
        conversation: ConversationState,
        entity_type: ReferentEntityType,
    ) -> ReferentResolution:
        referent = (
            conversation.current_job
            if entity_type == ReferentEntityType.JOB
            else conversation.current_application
        )
        if referent is None:
            return ReferentResolution(
                status=ReferentResolutionStatus.NOT_FOUND,
                matched_by="current_referent_missing",
            )
        return ReferentResolution(
            status=ReferentResolutionStatus.RESOLVED,
            referent=referent,
            matched_by="current_referent",
        )

    def _resolve_previous(
        self,
        conversation: ConversationState,
        entity_type: ReferentEntityType,
    ) -> ReferentResolution:
        current = (
            conversation.current_job
            if entity_type == ReferentEntityType.JOB
            else conversation.current_application
        )
        for referent in reversed(conversation.recent_referents):
            if referent.entity_type != entity_type:
                continue
            if current and referent.entity_id == current.entity_id:
                continue
            return ReferentResolution(
                status=ReferentResolutionStatus.RESOLVED,
                referent=referent,
                matched_by="previous_referent",
            )
        return ReferentResolution(
            status=ReferentResolutionStatus.NOT_FOUND,
            matched_by="previous_referent_missing",
        )

    def _explicit_candidates(
        self,
        mention: str,
        *,
        entity_type: ReferentEntityType,
        source_turn_id: str,
        user_id: str | None,
    ) -> list[ReferentRef]:
        if entity_type == ReferentEntityType.JOB:
            by_id = {
                job.job_id: ReferentRef(
                    entity_type=ReferentEntityType.JOB,
                    entity_id=job.job_id,
                    source_turn_id=source_turn_id,
                    updated_at=self._now(),
                    display_hint=f"{job.company} — {job.title}",
                )
                for job in self._all_jobs()
                if mention in self._job_identity_keys(job)
            }
            candidates = list(by_id.values())
        else:
            if self.tracker_store is None or user_id is None:
                return []
            tracker = self.tracker_store.load(user_id=user_id)
            candidates = [
                ReferentRef(
                    entity_type=ReferentEntityType.APPLICATION,
                    entity_id=application.id,
                    source_turn_id=source_turn_id,
                    updated_at=self._now(),
                    display_hint=f"{application.company} — {application.title}",
                )
                for application in tracker.applications
                if mention in self._application_identity_keys(application)
            ]
        return sorted(candidates, key=lambda item: (item.display_hint or "", item.entity_id))

    @staticmethod
    def _job_identity_keys(job: "RawJob | DurableJob") -> set[str]:
        return {
            _normalize_mention(job.job_id),
            _normalize_mention(job.company),
            _normalize_mention(job.title),
            _normalize_mention(f"{job.company} {job.title}"),
            _normalize_mention(f"{job.company} 的 {job.title}"),
        }

    @staticmethod
    def _application_identity_keys(application: ApplicationRecord) -> set[str]:
        values = {
            application.id,
            application.company,
            application.title,
            f"{application.company} {application.title}",
            f"{application.company} 的 {application.title}",
        }
        if application.job_id:
            values.add(application.job_id)
        return {_normalize_mention(value) for value in values}

    def _all_jobs(self):
        durable_jobs = (
            self.career_repository.list_jobs()
            if self.career_repository is not None
            else []
        )
        by_id = {job.job_id: job for job in durable_jobs}
        by_id.update({job.job_id: job for job in self.jobs})
        return tuple(by_id.values())

    @staticmethod
    def _application_updated_at(application: ApplicationRecord) -> datetime | None:
        if not application.state_history:
            return None
        return _parse_datetime(application.state_history[-1].timestamp)

    @classmethod
    def _strip_reference_suffix(cls, mention: str) -> str:
        for suffix in cls._REFERENCE_SUFFIXES:
            normalized_suffix = _normalize_mention(suffix)
            if mention.endswith(normalized_suffix):
                return mention[: -len(normalized_suffix)].strip()
        return mention


class ContextPurpose(str, Enum):
    AGENT_DECISION = "agent_decision"
    JOB_ANALYSIS = "job_analysis"
    APPLICATION_UPDATE = "application_update"
    INTERVIEW_PREP = "interview_prep"


class ContextAuthority(str, Enum):
    SYSTEM_POLICY = "system_policy"
    USER_INPUT = "user_input"
    USER_STATE = "user_state"
    BUSINESS_STATE = "business_state"
    INTERACTION_STATE = "interaction_state"
    ANALYSIS_STATE = "analysis_state"
    TOOL_OBSERVATION = "tool_observation"


class ContextSection(StrictModel):
    name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    inclusion_reason: str = Field(min_length=1)
    authority: ContextAuthority
    content: dict[str, Any]
    updated_at: datetime | None = None
    char_count: int = Field(ge=0)
    user_overridable: bool = False

    @classmethod
    def create(
        cls,
        *,
        name: str,
        source: str,
        inclusion_reason: str,
        authority: ContextAuthority,
        content: dict[str, Any],
        updated_at: datetime | None = None,
        user_overridable: bool = False,
    ) -> "ContextSection":
        serialized = json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return cls(
            name=name,
            source=source,
            inclusion_reason=inclusion_reason,
            authority=authority,
            content=content,
            updated_at=updated_at,
            char_count=len(serialized),
            user_overridable=user_overridable,
        )


class AgentContextProjection(StrictModel):
    purpose: ContextPurpose
    session_id: str = Field(min_length=1)
    sections: list[ContextSection]
    unavailable: list[str] = Field(default_factory=list)

    def section(self, name: str) -> ContextSection | None:
        return next((item for item in self.sections if item.name == name), None)


class ContextProjector:
    _PREFERENCE_KEYS = ("preferred_city", "target_role", "job_type")

    def __init__(
        self,
        *,
        tracker_store: ApplicationTrackerStoreProtocol,
        recent_turn_limit: int = 5,
    ) -> None:
        if recent_turn_limit < 1:
            raise ValueError("recent_turn_limit must be positive")
        self.tracker_store = tracker_store
        self.recent_turn_limit = recent_turn_limit

    def project(
        self,
        *,
        purpose: ContextPurpose,
        conversation: ConversationState,
        current_turn: AgentTurn,
        user_id: str,
        user_state: UserState,
        policy_summary: str,
        remaining_steps: int | None = None,
        target_ref: ReferentRef | None = None,
        jobs: Sequence[RawJob] = (),
        analyses_by_job_id: Mapping[str, "JobMatchAnalysis"] | None = None,
        tool_observations: Sequence[AgentObservation] = (),
    ) -> AgentContextProjection:
        if current_turn.session_id != conversation.session_id:
            raise ValueError("current turn and conversation must share a session")
        if remaining_steps is not None and remaining_steps < 0:
            raise ValueError("remaining_steps cannot be negative")

        tracker = self.tracker_store.load(user_id=user_id)
        applications = {item.id: item for item in tracker.applications}
        jobs_by_id = {item.job_id: item for item in jobs}
        sections = self._base_sections(
            conversation=conversation,
            current_turn=current_turn,
            user_state=user_state,
            policy_summary=policy_summary,
            remaining_steps=remaining_steps,
            tool_observations=tool_observations,
        )
        unavailable: list[str] = []

        if purpose == ContextPurpose.AGENT_DECISION:
            pass
        elif purpose == ContextPurpose.JOB_ANALYSIS:
            ref = target_ref or conversation.current_job
            job = self._job_for_ref(ref, jobs_by_id, applications)
            if job is None:
                unavailable.append("target_job")
            else:
                sections.append(self._job_section(job, "analyze the selected job"))
        elif purpose == ContextPurpose.APPLICATION_UPDATE:
            ref = target_ref or conversation.current_application
            application = self._application_for_ref(ref, applications)
            if application is None:
                unavailable.append("target_application")
            else:
                sections.append(
                    self._application_section(
                        application,
                        "validate and apply a governed stage transition",
                    )
                )
        else:
            ref = target_ref or conversation.current_application or conversation.current_job
            application = self._application_for_ref(ref, applications)
            job = self._job_for_ref(ref, jobs_by_id, applications)
            if application is None:
                unavailable.append("target_application")
            else:
                sections.append(
                    self._application_section(
                        application,
                        "prepare for the tracked application's interview",
                    )
                )
                if job is None and application.job_id:
                    job = jobs_by_id.get(application.job_id)
            if job is None:
                unavailable.append("target_job")
            else:
                sections.append(self._job_section(job, "ground interview preparation"))
                analysis = (analyses_by_job_id or {}).get(job.job_id)
                if analysis is None:
                    unavailable.append("job_analysis")
                else:
                    sections.append(self._analysis_section(job.job_id, analysis))

        return AgentContextProjection(
            purpose=purpose,
            session_id=conversation.session_id,
            sections=sections,
            unavailable=unavailable,
        )

    def _base_sections(
        self,
        *,
        conversation: ConversationState,
        current_turn: AgentTurn,
        user_state: UserState,
        policy_summary: str,
        remaining_steps: int | None,
        tool_observations: Sequence[AgentObservation],
    ) -> list[ContextSection]:
        preferences = {
            key: user_state.preferences[key]
            for key in self._PREFERENCE_KEYS
            if key in user_state.preferences
        }
        recent_turns = [
            {
                "turn_id": item.user_turn.turn_id,
                "user_input": item.user_turn.user_input,
                "assistant_refs": (
                    item.assistant_result.refs if item.assistant_result else []
                ),
                "assistant_summary": (
                    item.assistant_result.summary if item.assistant_result else None
                ),
            }
            for item in conversation.recent_turns[-self.recent_turn_limit :]
        ]
        refs = {
            "current_job": self._referent_payload(conversation.current_job),
            "current_application": self._referent_payload(
                conversation.current_application
            ),
            "recent": [
                self._referent_payload(item) for item in conversation.recent_referents
            ],
        }
        sections = [
            ContextSection.create(
                name="runtime_policy",
                source="agent_runtime.policy",
                inclusion_reason="constrain the next agent decision",
                authority=ContextAuthority.SYSTEM_POLICY,
                content={"summary": policy_summary},
            ),
            ContextSection.create(
                name="current_turn",
                source=f"AgentTurn:{current_turn.turn_id}",
                inclusion_reason="represent the user's current request",
                authority=ContextAuthority.USER_INPUT,
                content={"user_input": current_turn.user_input},
                updated_at=current_turn.created_at,
                user_overridable=True,
            ),
            ContextSection.create(
                name="current_referents",
                source="ConversationState",
                inclusion_reason="preserve same-session entity continuity",
                authority=ContextAuthority.INTERACTION_STATE,
                content=refs,
                updated_at=conversation.updated_at,
            ),
            ContextSection.create(
                name="recent_turns",
                source="ConversationState.recent_turns",
                inclusion_reason="retain bounded conversational context",
                authority=ContextAuthority.INTERACTION_STATE,
                content={"turns": recent_turns},
                updated_at=conversation.updated_at,
            ),
            ContextSection.create(
                name="user_preferences",
                source="UserState.preferences",
                inclusion_reason="apply only job-relevant long-term preferences",
                authority=ContextAuthority.USER_STATE,
                content=preferences,
                updated_at=_parse_datetime(user_state.meta.get("updated_at")),
                user_overridable=True,
            ),
        ]
        if remaining_steps is not None:
            sections.append(
                ContextSection.create(
                    name="loop_budget",
                    source="AgentLoopConfig",
                    inclusion_reason="bound future agent iteration",
                    authority=ContextAuthority.SYSTEM_POLICY,
                    content={"remaining_steps": remaining_steps},
                )
            )
        for observation in tool_observations:
            sections.append(
                ContextSection.create(
                    name=f"tool_observation:{observation.action_id}",
                    source=f"RuntimeTool:{observation.tool_name}",
                    inclusion_reason="incorporate the latest governed tool result",
                    authority=ContextAuthority.TOOL_OBSERVATION,
                    content=observation.model_dump(mode="json"),
                )
            )
        return sections

    @staticmethod
    def _referent_payload(referent: ReferentRef | None) -> dict[str, Any] | None:
        return referent.model_dump(mode="json") if referent else None

    @staticmethod
    def _application_for_ref(
        referent: ReferentRef | None,
        applications: Mapping[str, ApplicationRecord],
    ) -> ApplicationRecord | None:
        if referent is None or referent.entity_type != ReferentEntityType.APPLICATION:
            return None
        return applications.get(referent.entity_id)

    @staticmethod
    def _job_for_ref(
        referent: ReferentRef | None,
        jobs: Mapping[str, RawJob],
        applications: Mapping[str, ApplicationRecord],
    ) -> RawJob | None:
        if referent is None:
            return None
        if referent.entity_type == ReferentEntityType.JOB:
            return jobs.get(referent.entity_id)
        application = applications.get(referent.entity_id)
        return jobs.get(application.job_id) if application and application.job_id else None

    @staticmethod
    def _job_section(job: RawJob, reason: str) -> ContextSection:
        return ContextSection.create(
            name="target_job",
            source=f"RawJob:{job.job_id}",
            inclusion_reason=reason,
            authority=ContextAuthority.BUSINESS_STATE,
            content=job.model_dump(mode="json"),
            updated_at=_parse_datetime(job.fetched_at),
        )

    @staticmethod
    def _application_section(
        application: ApplicationRecord,
        reason: str,
    ) -> ContextSection:
        updated_at = ReferentResolver._application_updated_at(application)
        return ContextSection.create(
            name="target_application",
            source=f"ApplicationTrackerStore:{application.id}",
            inclusion_reason=reason,
            authority=ContextAuthority.BUSINESS_STATE,
            content={
                "application_id": application.id,
                "job_id": application.job_id,
                "company": application.company,
                "title": application.title,
                "current_stage": application.current_state.value,
                "source": application.source,
                "updated_at": updated_at.isoformat() if updated_at else None,
                "transition_history": [
                    {
                        "state": event.state.value,
                        "timestamp": event.timestamp,
                        "notes": event.notes,
                    }
                    for event in application.state_history[-5:]
                ],
            },
            updated_at=updated_at,
        )

    @staticmethod
    def _analysis_section(
        job_id: str,
        analysis: "JobMatchAnalysis",
    ) -> ContextSection:
        strengths = list(
            analysis.summary.evidence_backed_strengths
            if analysis.summary
            else analysis.supported
        )
        gaps = list(analysis.summary.gaps if analysis.summary else analysis.gaps)
        return ContextSection.create(
            name="job_analysis",
            source=f"JobMatchAnalysis:{analysis.jd_source_id}",
            inclusion_reason="focus interview preparation on verified strengths and gaps",
            authority=ContextAuthority.ANALYSIS_STATE,
            content={
                "job_id": job_id,
                "analysis_ref": analysis.jd_source_id,
                "strengths": strengths,
                "gaps": gaps,
            },
        )

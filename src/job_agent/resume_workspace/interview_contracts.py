"""Private interview state and deliberately smaller active-session projections."""
from datetime import datetime
from typing import Literal, Any
from pydantic import Field, field_validator, model_validator
from job_agent.schemas import StrictModel
from job_agent.text_identity import normalize_text
from job_agent.resume_workspace.evidence_reference import EvidenceReference
from job_agent.resume_workspace.evidence_pack import EvidencePack
from job_agent.resume_workspace.project_evidence import ProjectEvidenceBoundary
from job_agent.resume_workspace.execution_state import SharedRunState


class InterviewStart(StrictModel):
    request_key: str = Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')
    version_id: str
    expected_content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    jd_text: str = Field(min_length=1,max_length=12000)
    match_id: str | None = None
    mode: Literal['local_demo','llm'] = 'local_demo'
    max_turns: int = Field(default=4,ge=2,le=6)
    allow_external_processing: bool = False
    use_retrieval: bool = False
    track: Literal['job','project','weakness'] = 'job'
    project_id: str | None = Field(default=None,max_length=100)
    snapshot_id: str | None = Field(default=None,max_length=100)
    prior_session_id: str | None = Field(default=None,max_length=100)
    learning_observation_id: str | None = Field(default=None,max_length=100)
    learning_allow_historical_version: bool = False

    @model_validator(mode='after')
    def track_scope(self):
        if self.track!='job' and not self.use_retrieval:raise ValueError('track_requires_retrieval')
        if self.track=='project' and (not self.project_id or not self.snapshot_id):raise ValueError('project_scope_required')
        if self.track!='project' and not self.learning_observation_id and (self.project_id or self.snapshot_id):raise ValueError('unexpected_project_scope')
        if (self.track=='weakness') != bool(self.prior_session_id):raise ValueError('prior_review_scope_required')
        if self.learning_observation_id and self.track!='weakness':raise ValueError('learning_practice_requires_prior_scope')
        if self.learning_allow_historical_version and not self.learning_observation_id:raise ValueError('historical_learning_scope_required')
        return self

    def stable_json(self):
        fields={'request_key','allow_external_processing'}
        if self.learning_observation_id is None:fields.add('learning_observation_id')
        if not self.learning_allow_historical_version:fields.add('learning_allow_historical_version')
        if not self.use_retrieval and self.track=='job':
            fields.update({'use_retrieval','track','project_id','snapshot_id','prior_session_id'})
        return self.model_dump_json(exclude=fields)

    @field_validator('jd_text')
    @classmethod
    def canonical(cls,v):
        v=normalize_text(v).strip()
        if not v:raise ValueError('empty_jd')
        return v


class InterviewAnswer(StrictModel):
    request_key: str = Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')
    question_id: str
    expected_revision: int = Field(ge=0)
    answer: str = Field(min_length=1,max_length=5000)
    allow_external_processing: bool = False

    @field_validator('answer')
    @classmethod
    def canonical(cls,v):
        v=normalize_text(v).strip()
        if not v:raise ValueError('empty_answer')
        return v


class Topic(StrictModel):
    anchor_id: str
    prompt: str
    points: dict[str,str]
    aliases: dict[str,list[str]]
    followups: dict[str,str]
    references: list[EvidenceReference] = Field(default_factory=list,max_length=6)
    evidence_boundary: ProjectEvidenceBoundary|None=None


class Question(StrictModel):
    question_id: str
    topic_id: str
    prompt: str
    followup: bool = False
    focus_id: str | None = None
    references: list[EvidenceReference] = Field(default_factory=list,max_length=6)
    evidence_boundary: ProjectEvidenceBoundary|None=None


class PointAssessment(StrictModel):
    point_id:str
    status:Literal['correct','incorrect','uncertain']
    answer_quote:str=Field(default='',max_length=300)
    reason:str=Field(min_length=1,max_length=300)
    assessed_by:Literal['model_semantic_unverified','deterministic_counterexample']='model_semantic_unverified'


class Evaluation(StrictModel):
    covered_ids: list[str] = Field(max_length=6)
    missing_ids: list[str] = Field(max_length=6)
    claim_needs_evidence: bool
    recommended_action: Literal['follow_up','next']
    note: str = Field(min_length=1,max_length=300)
    point_assessments:list[PointAssessment]=Field(default_factory=list,max_length=6)
    assessment_mode:Literal['local_lexical','deterministic_counterexample','model_semantic_unverified']='local_lexical'
    method_version:str='legacy-lexical'

    def has_complete_assessments(self,point_ids):
        """Shape/identity only; does not certify the model's semantic judgments.

        Default [] remains readable for old/lexical checkpoints. Online LLM
        execution and new learning derivations must explicitly require this.
        """
        expected=set(point_ids);actual=[a.point_id for a in self.point_assessments]
        return bool(expected) and len(actual)==len(expected) and len(actual)==len(set(actual)) and set(actual)==expected


class InterviewDecision(StrictModel):
    action: Literal['follow_up','next']
    focus_id: str | None = None
    retrieval_target: Literal['none','public_docs','references','tests','symbol'] = 'none'


class InterviewTurn(StrictModel):
    answered_at: datetime | None = None
    question: Question
    answer: str
    evaluation: Evaluation
    decision: InterviewDecision


class InterviewUsage(StrictModel):
    evaluator_calls: int = 0
    interviewer_calls: int = 0
    provider_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    active_ms: int = 0
    cost: float | None = None


class PendingAnswer(StrictModel):
    request_key: str
    answer: str
    evaluation: Evaluation | None = None
    decision: InterviewDecision | None = None


class InterviewState(StrictModel):
    session_id: str
    resume_id: str
    version_id: str
    version_hash: str
    jd_text: str
    match_id: str | None = None
    mode: Literal['local_demo','llm']
    provider: str
    model: str
    created_at: datetime
    status: Literal['active','paused','complete','failed'] = 'active'
    revision: int = 0
    max_turns: int
    plan: list[Topic]
    topic_index: int = 0
    current: Question | None
    turns: list[InterviewTurn] = Field(default_factory=list)
    pending: PendingAnswer | None = None
    next_node: Literal['idle','evaluator','interviewer','route'] = 'idle'
    model_inflight: bool = False
    error_code: str | None = None
    usage: InterviewUsage = Field(default_factory=InterviewUsage)
    messages: list[dict[str,Any]] = Field(default_factory=list)
    use_retrieval: bool = False
    track: Literal['job','project','weakness'] = 'job'
    project_id: str | None = None
    snapshot_id: str | None = None
    prior_session_id: str | None = None
    learning_observation_id: str | None = None
    learning_allow_historical_version: bool = False
    learning_condition_hash: str | None = None
    bound_owner: str | None = None
    tool_trace: list[dict[str,Any]] = Field(default_factory=list)
    tool_fingerprints: list[str] = Field(default_factory=list)
    tool_calls: int = 0
    evidence_packs: list[EvidencePack] = Field(default_factory=list,max_length=10)
    execution:SharedRunState|None=None


class PublicQuestion(StrictModel):
    question_id: str
    topic_id: str
    prompt: str
    followup: bool
    references: list[EvidenceReference] = Field(default_factory=list,max_length=6)
    evidence_boundary: ProjectEvidenceBoundary|None=None


class PublicTurn(StrictModel):
    question: PublicQuestion
    answer: str


class InterviewView(StrictModel):
    session_id: str
    resume_id: str
    version_id: str
    version_hash: str
    jd_text: str
    match_id: str | None
    mode: str
    provider: str
    model: str
    status: str
    revision: int
    max_turns: int
    created_at: datetime
    current: PublicQuestion | None
    turns: list[PublicTurn]
    messages: list[dict[str,Any]]
    usage: InterviewUsage
    answer_pending: bool
    resumable: bool
    model_inflight: bool
    error_code: str | None
    version_is_current: bool
    warnings: list[str]
    track: str = 'job'
    use_retrieval: bool = False
    project_id: str | None = None
    snapshot_id: str | None = None
    tool_trace: list[dict[str,Any]] = Field(default_factory=list)
    tool_calls: int = 0


class FinishInterview(StrictModel):
    expected_revision: int = Field(ge=0)

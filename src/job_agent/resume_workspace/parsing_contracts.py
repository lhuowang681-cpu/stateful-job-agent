from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from job_agent.resume_workspace.contracts import (
    Education, Experience, PersonalInfo, Project, ResumeDocument, ResumeFact,
)
from job_agent.schemas import StrictModel


class DraftPersonalInfo(PersonalInfo):
    name: ResumeFact | None = None


class DraftEducation(Education):
    school: ResumeFact | None = None


class DraftExperience(Experience):
    organization: ResumeFact | None = None


class DraftProject(Project):
    name: ResumeFact | None = None


class DraftDocument(ResumeDocument):
    personal: DraftPersonalInfo = Field(default_factory=DraftPersonalInfo)
    education: list[DraftEducation] = Field(default_factory=list, max_length=10)
    experience: list[DraftExperience] = Field(default_factory=list, max_length=20)
    projects: list[DraftProject] = Field(default_factory=list, max_length=30)


class FieldCandidate(StrictModel):
    path: str = Field(min_length=1, max_length=100)
    exact_quote: str = Field(min_length=1, max_length=5000)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, gt=0)


class ParseCandidate(StrictModel):
    fields: list[FieldCandidate] = Field(default_factory=list, max_length=300)


class ParseRequest(StrictModel):
    mode: Literal["local_rules", "llm"] = "local_rules"
    allow_external_processing: bool = False


class ParseUsage(StrictModel):
    provider_calls: int = 0
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None


class MissingField(StrictModel):
    path: str
    question: str
    required: bool = False


class DraftRecord(StrictModel):
    draft_id: str
    source_id: str
    source_content_hash: str
    document: DraftDocument
    questions: list[MissingField]
    warnings: list[str]
    mode: Literal["local_rules", "llm"]
    model: str
    provider: str = "unknown"
    parser_version: str = "resume-parser-m2-v1"
    usage: ParseUsage
    created_at: datetime
    accepted_resume_id: str | None = None
    accepted_version_id: str | None = None


class FieldEdit(StrictModel):
    path: str = Field(min_length=1, max_length=100)
    value: str = Field(max_length=5000)


class AcceptDraft(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    expected_source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    edits: list[FieldEdit] = Field(default_factory=list, max_length=300)
    user_reviewed: Literal[True]


class EditVersion(StrictModel):
    edits: list[FieldEdit] = Field(max_length=300)
    note: str = Field(default="人工局部修改", max_length=500)


class UploadView(StrictModel):
    source_id: str
    content_hash: str
    filename: str
    byte_size: int
    raw_hash: str
    parser: str
    source_format: str
    original_preserved: bool = True


class ImportErrorCode(ValueError):
    pass


class ParseError(ValueError):
    pass

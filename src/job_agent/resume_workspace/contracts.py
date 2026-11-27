from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from job_agent.schemas import StrictModel
from job_agent.text_identity import normalize_text


SourceKind = Literal["original_resume", "user_statement", "job_description", "reference"]


class SourceCreate(StrictModel):
    kind: SourceKind
    label: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=100_000)

    @field_validator("text")
    @classmethod
    def canonical_text(cls, value: str) -> str:
        value = normalize_text(value)
        if not value.strip():
            raise ValueError("source_text_empty")
        return value


class SourceRecord(SourceCreate):
    source_id: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime
    offset_basis: Literal["canonical_unicode_characters"] = "canonical_unicode_characters"


class SourceSummary(StrictModel):
    source_id: str
    kind: SourceKind
    label: str
    created_at: datetime
    referenced: bool
    has_original: bool


class SourceSpan(StrictModel):
    source_id: str = Field(min_length=1, max_length=64)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered_span(self):
        if self.end <= self.start:
            raise ValueError("source_span_empty_or_reversed")
        return self


class ResumeFact(StrictModel):
    """An extractive, self-attested fact, never a reference-derived qualification.

    The repository checks text == source.text[start:end]. A citation proves
    origin, not real-world truth or semantic entailment of a later rewrite.
    """

    fact_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    text: str = Field(min_length=1, max_length=5000)
    source: SourceSpan


class PersonalInfo(StrictModel):
    name: ResumeFact
    email: ResumeFact | None = None
    phone: ResumeFact | None = None
    location: ResumeFact | None = None
    links: list[ResumeFact] = Field(default_factory=list, max_length=10)


class Education(StrictModel):
    entry_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    school: ResumeFact
    degree: ResumeFact | None = None
    major: ResumeFact | None = None
    period: ResumeFact | None = None
    highlights: list[ResumeFact] = Field(default_factory=list, max_length=20)


class Experience(StrictModel):
    entry_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    organization: ResumeFact
    role: ResumeFact | None = None
    period: ResumeFact | None = None
    bullets: list[ResumeFact] = Field(default_factory=list, max_length=30)


class Project(StrictModel):
    entry_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: ResumeFact
    role: ResumeFact | None = None
    period: ResumeFact | None = None
    bullets: list[ResumeFact] = Field(default_factory=list, max_length=30)


class ResumeDocument(StrictModel):
    schema_version: Literal[1] = 1
    personal: PersonalInfo
    summary: list[ResumeFact] = Field(default_factory=list, max_length=10)
    education: list[Education] = Field(default_factory=list, max_length=10)
    experience: list[Experience] = Field(default_factory=list, max_length=20)
    projects: list[Project] = Field(default_factory=list, max_length=30)
    skills: list[ResumeFact] = Field(default_factory=list, max_length=60)

    def facts(self) -> list[ResumeFact]:
        result: list[ResumeFact] = []

        def visit(item):
            if isinstance(item, ResumeFact):
                result.append(item)
            elif isinstance(item, StrictModel):
                for name in type(item).model_fields:
                    visit(getattr(item, name))
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(self)
        return result

    @model_validator(mode="after")
    def unique_ids(self):
        fact_ids = [fact.fact_id for fact in self.facts()]
        entry_ids = [item.entry_id for item in [*self.education, *self.experience, *self.projects]]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("duplicate_fact_id")
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("duplicate_entry_id")
        return self


class ResumeCreate(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    document: ResumeDocument


class VersionCreate(StrictModel):
    expected_parent_version_id: str = Field(min_length=1, max_length=64)
    document: ResumeDocument
    note: str = Field(default="", max_length=500)


class ConfirmVersion(StrictModel):
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class RestoreVersion(StrictModel):
    expected_parent_version_id: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=500)


class VersionRecord(StrictModel):
    resume_id: str
    version_id: str
    sequence: int = Field(ge=1)
    parent_version_id: str | None
    restored_from_version_id: str | None = None
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    document: ResumeDocument
    note: str
    created_at: datetime
    confirmed_at: datetime | None = None
    confirmation_scope: Literal["user_attested_only"] = "user_attested_only"


class ResumeSummary(StrictModel):
    resume_id: str
    title: str
    head_version_id: str
    version_count: int
    created_at: datetime
    updated_at: datetime

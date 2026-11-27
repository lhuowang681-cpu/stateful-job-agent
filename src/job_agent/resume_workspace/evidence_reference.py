"""F0 contract: retrieval/citation is provenance, never personal capability."""
from typing import Literal
from pydantic import Field, model_validator
from job_agent.schemas import StrictModel


class EvidenceReference(StrictModel):
    evidence_id: str
    scope: Literal['public_knowledge', 'private_project', 'personal_statement']
    owner_id: str | None = None
    project_id: str | None = None
    snapshot_id: str
    source_id: str
    content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    commit: str | None = None
    retrieval_method: str
    evidence_kind: Literal['code', 'test_code', 'documentation', 'question', 'self_attested']
    supports_claim: Literal['needs_judgment', 'supported', 'partial', 'insufficient_evidence', 'conflict'] = 'needs_judgment'
    quote: str
    independent_truth: Literal['not_verified'] = 'not_verified'

    @model_validator(mode='after')
    def boundaries(self):
        if self.end_line < self.start_line:
            raise ValueError('invalid_line_range')
        if self.scope != 'public_knowledge' and not self.owner_id:
            raise ValueError('private_reference_requires_owner')
        return self

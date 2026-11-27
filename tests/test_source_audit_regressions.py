"""Synthetic source-boundary regressions; no model, secret, or private corpus."""
from pathlib import Path
import builtins
import importlib
import sys
from types import SimpleNamespace

import pytest

from job_agent.evidence.contracts import (
    EvidenceLevel, EvidenceV2Error, ParentRequirement, RequirementAnalysis,
    RequirementAtom, SourceDocumentRef, SourceInput,
)
from job_agent.evidence.level_policy import EvidenceLevelPolicy
from job_agent.evidence.mapping import EvidenceMappingService, PROMPT_VERSION as MAPPING_VERSION
from job_agent.evidence.pipeline import EvidenceV2Pipeline
from job_agent.evidence.projections import EvidenceProjectionService
from job_agent.evidence.requirements import PROMPT_VERSION as REQUIREMENT_VERSION
from job_agent.evidence.sources import EvidenceSourceStore
from job_agent.llm.harness import LLMHarness
from job_agent.llm.providers.mock import MockLLMProvider
from job_agent.llm.skill_registry import SkillSpec
from job_agent.schemas import StructuredJD
from tests.evidence_v2_fixtures import commit_single_atom_evidence_v2


class Registry:
    def get(self, skill_id):
        return SkillSpec(skill_id=skill_id, version='fixture-v1',
                         instructions='Use only explicit source statements.',
                         reference_paths=(Path('fixture-reference.md'),), output_schema=StructuredJD)


@pytest.mark.parametrize('kind,cap', [('original_resume', EvidenceLevel.C1), ('raw_jd', EvidenceLevel.NONE)])
@pytest.mark.parametrize('artifact_type', ['experiment_record', 'production_log'])
def test_source_kind_cannot_be_promoted_by_artifact_metadata(kind, cap, artifact_type):
    source = SourceDocumentRef(source_id='source', kind=kind, content_hash='a'*64,
                               snapshot_path='sources/source.txt', display_label='synthetic',
                               artifact_type=artifact_type)
    policy = EvidenceLevelPolicy()
    assert policy.maximum_level(source) == cap
    with pytest.raises(EvidenceV2Error, match='evidence_level_exceeds_source_cap'):
        policy.validate(source, EvidenceLevel.C2)


@pytest.mark.parametrize('artifact_type', [' Target-Resume ', 'ANSWER CARD', 'Interview-Debrief',
                                         ' INTERVIEW_TRANSCRIPT ', 'interview-score'])
def test_generated_artifact_aliases_cannot_enter_candidate_pool(tmp_path, artifact_type):
    with pytest.raises(EvidenceV2Error, match='generated_source_forbidden'):
        EvidenceSourceStore(tmp_path).snapshot('synthetic', [
            SourceInput(kind='user_artifact', display_label='generated', text='synthetic output',
                        artifact_type=artifact_type)])


@pytest.mark.parametrize('contradiction_flag', [False, True])
def test_resume_projection_preserves_but_does_not_promote_conflicting_evidence(tmp_path, contradiction_flag):
    bundle = commit_single_atom_evidence_v2(tmp_path)
    result = bundle.mapping.atom_results[0]
    conflict = result.links[0].model_copy(update={'link_id': 'conflict', 'support_status': 'contradictory'})
    result.links.append(conflict)
    result.has_contradiction = contradiction_flag
    service = EvidenceProjectionService()
    assert service.for_resume(bundle).claims == []
    assert service.for_resume_agent(bundle, company='Acme', title='Engineer', raw_jd='synthetic').evidence == []
    assert len(service.for_interview(bundle).atoms[0].links) == 2


def test_resume_projection_does_not_promote_pending_c2_evidence(tmp_path):
    bundle = commit_single_atom_evidence_v2(tmp_path)
    bundle.mapping.atom_results[0].links[0].needs_confirmation = True
    service = EvidenceProjectionService()
    assert service.for_resume(bundle).claims == []
    assert service.for_resume_agent(bundle, company='Acme', title='Engineer', raw_jd='synthetic').evidence == []
    assert service.for_interview(bundle).atoms[0].links[0].needs_confirmation


def test_mapping_derives_c1_confirmation_even_if_model_omits_it(tmp_path):
    store = EvidenceSourceStore(tmp_path)
    catalog = store.snapshot('synthetic', [
        SourceInput(kind='raw_jd', display_label='JD', text='Implement evaluation'),
        SourceInput(kind='original_resume', display_label='Resume', text='Implemented evaluation')])
    span = store.make_span(catalog, catalog.documents[0].source_id, 0, len('Implement evaluation'))
    analysis = RequirementAnalysis(
        parents=[ParentRequirement(requirement_id='r1', text='evaluation', importance='must', source_span=span, atom_ids=['a1'])],
        atoms=[RequirementAtom(atom_id='a1', parent_requirement_id='r1', text='evaluation', source_span=span)])
    provider = MockLLMProvider([{'atom_results': [{'atom_id': 'a1', 'rationale': 'explicit source', 'links': [
        {'link_id': 'l1', 'atom_id': 'a1', 'source_locator': {
            'source_id': catalog.documents[1].source_id, 'exact_quote': 'Implemented evaluation'},
         'claim': 'Implemented evaluation', 'support_status': 'supported', 'level': 'C1',
         'confidence': 0.9, 'needs_confirmation': False}]}]}])
    result = EvidenceMappingService(registry=Registry(), harness=LLMHarness(provider), source_store=store).map(
        analysis, catalog=catalog, session_id='synthetic', run_id='synthetic')
    assert result.atom_results[0].match_status == 'unverified_lead'
    assert result.atom_results[0].links[0].needs_confirmation is True


def test_pipeline_records_the_executed_prompt_versions(tmp_path):
    provider = MockLLMProvider([{'requirements': [], 'warnings': []}])
    result = EvidenceV2Pipeline(registry=Registry(), harness=LLMHarness(provider)).run(
        session_dir=tmp_path, raw_jd='Role introduction', original_resume='Synthetic resume', session_id='synthetic')
    assert result.bundle.manifest.jd_parser_version == REQUIREMENT_VERSION
    assert result.bundle.manifest.evidence_prompt_version == MAPPING_VERSION


def test_embedding_import_is_optional_but_real_construction_requires_dependency(monkeypatch):
    original_import = builtins.__import__
    def without_model_dependency(name, *args, **kwargs):
        if name == 'sentence_transformers':
            raise ModuleNotFoundError('synthetic absent dependency', name=name)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_model_dependency)
    module = importlib.import_module('job_agent.knowledge.qwen_embedding')
    importlib.reload(module)
    with pytest.raises(ImportError, match='embedding'):
        module.QwenEmbeddingBackend('nonexistent-synthetic-model')


def test_embedding_still_uses_normalized_documents_and_query_prompt(monkeypatch):
    calls = []
    class Encoder:
        def __init__(self, path, *, device):
            assert path == 'synthetic-model' and device == 'cpu'
        def encode(self, value, **kwargs):
            calls.append((value, kwargs))
            return SimpleNamespace(tolist=lambda: [[1.0, 0.0]] if isinstance(value, list) else [1.0, 0.0])
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=Encoder))
    from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend
    backend = QwenEmbeddingBackend('synthetic-model', device='cpu')
    assert backend.embed_documents(['source']) == [[1.0, 0.0]]
    assert backend.embed_query('query') == [1.0, 0.0]
    assert calls == [(['source'], {'normalize_embeddings': True}),
                     ('query', {'prompt_name': 'query', 'normalize_embeddings': True})]


def test_application_assistant_draft_is_allowlisted_but_still_requires_approval():
    from job_agent.agent_runtime.contracts import AgentAction, RuntimeToolSpec, ToolEffect
    from job_agent.agent_runtime.policy import PolicyContext, PolicyEngine
    from job_agent.backend_service.application_assistant import (
        APPLICATION_ASSISTANT_TOOLS, WRITE_SANDBOX_DRAFT_TOOL,
    )
    assert WRITE_SANDBOX_DRAFT_TOOL in APPLICATION_ASSISTANT_TOOLS
    context = PolicyContext(skill_allowed_tools=APPLICATION_ASSISTANT_TOOLS,
                            agent_allowed_tools=APPLICATION_ASSISTANT_TOOLS,
                            runtime_allowed_tools=APPLICATION_ASSISTANT_TOOLS)
    action = AgentAction(action_id='synthetic-write', tool_name=WRITE_SANDBOX_DRAFT_TOOL,
                         tool_arguments={}, expected_observation='receipt', progress_claim='draft')
    spec = RuntimeToolSpec(name=WRITE_SANDBOX_DRAFT_TOOL, description='Synthetic sandbox draft',
                           input_schema={}, output_schema={}, effect=ToolEffect.EXTERNAL_DRAFT,
                           requires_approval=True, sandbox_only=True, idempotent=False)
    result = PolicyEngine().authorize(action, spec, context, session_id='synthetic', run_id='synthetic')
    assert result.requires_approval and not result.allowed
    assert result.reason_code == 'approval_required'

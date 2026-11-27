"""Explicit contract labels on authored synthetic text; not human semantic gold."""
import pytest
from job_agent.resume_workspace.claim_audit import audit_claims,ReviewedClaim,parts
from job_agent.resume_workspace.rewrite import hard_constraints


def supported(text,quote):
    return ReviewedClaim(text=text,source_quote=quote,status='supported',reason='Synthetic model judgment, not independently true.')


def test_chinese_added_success_is_blocked_even_with_model_accept_and_real_source_quote():
    source='参与本地求职助手原型开发。'
    added='显著提升求职成功率。';draft=source+added
    audit=audit_claims(source,draft,reviews=[supported(added,source)])
    assert hard_constraints(source,draft) and not audit.acceptable
    claim=audit.claims[-1]
    assert claim.status=='unsupported' and claim.assessed_by=='deterministic_gate'
    assert 'success_rate' in ' '.join(audit.hard_issues)


@pytest.mark.parametrize('source,draft',[
    ('使用 Python 开发 FastAPI 接口，参与本地原型测试。','基于 Python 实现 FastAPI 接口，参与本地原型测试。'),
    ('我使用 Python 开发本地原型。','使用 Python 实现本地原型。'),
    ('我参与了课程项目。','参与课程项目。'),
])
def test_controlled_paraphrases_are_usable_changes_and_remain_relative_c1(source,draft):
    audit=audit_claims(source,draft)
    assert draft!=source and audit.acceptable and audit.claims
    assert all(c.source_quote and c.assessed_by=='deterministic_alignment' for c in audit.claims)
    assert audit.semantic_truth=='not_independently_verified'


def test_other_valid_paraphrase_needs_explicit_semantic_source_mapping():
    source='使用 Python 编写本地原型接口。';draft='以 Python 编写本地原型接口。'
    assert not audit_claims(source,draft).acceptable
    reviewed=audit_claims(source,draft,reviews=[supported(draft,source)])
    assert reviewed.acceptable and reviewed.claims[0].assessed_by=='model_semantic_unverified'
    assert reviewed.claims[0].source_quote==source


def test_jd_or_nonexistent_quote_cannot_become_c1_support():
    source='使用 Python 编写本地原型接口。';draft='以 Python 编写本地原型接口。'
    audit=audit_claims(source,draft,reviews=[supported(draft,'精通全栈开发。')],context={'jd':'精通全栈开发。'})
    assert not audit.acceptable and audit.claims[0].status=='uncertain' and not audit.claims[0].source_id


def test_positive_clause_cannot_reuse_a_substring_of_negated_source_as_proof():
    source='没有使用 Redis。';draft='没有使用 Redis；使用 Redis 缓存。'
    audit=audit_claims(source,draft,reviews=[supported('使用 Redis 缓存。','使用 Redis')])
    assert not audit.acceptable and audit.claims[-1].status=='contradicted'


@pytest.mark.parametrize('draft',[
    '使用 Python 开发 FastAPI 接口，参与本地原型测试，提升80%。',
    '使用 Python 和 Kubernetes 开发 FastAPI 接口，参与本地原型测试。',
    '使用 Python 开发 FastAPI 接口。',
    '主导 Python 开发 FastAPI 接口，参与本地原型测试。',
])
def test_existing_numeric_technology_scope_and_ownership_hard_gates_are_centralized(draft):
    source='使用 Python 开发 FastAPI 接口，参与本地原型测试。'
    reviews=[supported(text,source) for _,_,text in parts(draft)]
    assert not audit_claims(source,draft,reviews=reviews).acceptable


def test_assertion_offsets_point_to_exact_complete_original_draft_text():
    draft='  使用 Python 开发接口， 参与本地原型测试  '
    audit=audit_claims('使用 Python 开发接口，参与本地原型测试',draft)
    assert audit.acceptable
    assert all(draft[c.start:c.end]==c.text for c in audit.claims)


@pytest.mark.parametrize('extra',['测试均已通过。','获得全国一等奖。','上线后稳定运行。'])
def test_source_presence_cannot_establish_execution_awards_or_production_results(extra):
    source='参与本地原型，阅读过测试源码，尚未实际运行测试。'
    audit=audit_claims(source,source+extra,reviews=[supported(extra,source)])
    assert not audit.acceptable and audit.claims[-1].status=='unsupported'

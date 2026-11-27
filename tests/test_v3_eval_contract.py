"""Gold attribution, leakage, and metric-denominator checks; no model judge."""
from pathlib import Path
import pytest
from pydantic import ValidationError
from scripts.freeze_expansion_eval import build
from job_agent.knowledge.evaluation_contract import EvaluationDataset,evaluate_case


def test_frozen_candidates_are_mechanically_valid_but_not_human_gold():
    data=build()
    saved=EvaluationDataset.model_validate_json((Path(__file__).resolve().parents[1]/'docs/evaluation/expansion/candidates-v1.json').read_text(encoding='utf-8'))
    assert saved==data
    assert len(data.cases)==32
    assert sum(c.split=='dev' for c in data.cases)==20
    assert all(c.annotation_status=='ai_candidate' for c in data.cases)
    assert {d.kind for d in data.corpus.documents}=={'code','project_documentation','public_knowledge'}


@pytest.mark.parametrize('tamper',['family','source_split','snapshot','quote','hash','duplicate_query'])
def test_gold_tampering_and_split_leakage_rejected(tamper):
    raw=build().model_dump()
    if tamper=='family':raw['cases'][20]['family']=raw['cases'][0]['family']
    if tamper=='source_split':raw['cases'][0]['split']='test'
    if tamper=='snapshot':raw['cases'][0]['source_snapshot']='other'
    if tamper=='quote':raw['cases'][0]['gold'][0]['quote']='invented source'
    if tamper=='hash':raw['cases'][0]['gold'][0]['content_hash']='0'*64
    if tamper=='duplicate_query':raw['cases'][1]['query']=' '+raw['cases'][0]['query']+'!'
    with pytest.raises(ValidationError):EvaluationDataset.model_validate(raw)


def test_any_hit_does_not_mean_all_gold_retrieved_and_invalid_ranks_count():
    data=build();case=next(c for c in data.cases if len(c.gold)==2)
    bad=case.gold[0].model_copy(update={'quote':'not source'})
    result=evaluate_case(case,data.corpus,[bad,case.gold[0]])
    assert result['hit_any_gold'] and result['gold_span_recall']==.5
    assert not result['sufficient_gold_retrieved'] and result['reciprocal_rank']==.5
    assert result['citation_valid_rate']==.5
    any_case=case.model_copy(update={'gold_requirement':'any'})
    assert evaluate_case(any_case,data.corpus,[case.gold[0]])['sufficient_gold_retrieved']
    assert result['claim_support'] is result['final_business_quality'] is None


def test_unanswerable_has_no_vacuous_perfect_recall_or_hallucination_label():
    data=build();case=next(c for c in data.cases if not c.answerable)
    span=data.cases[0].gold[0]
    result=evaluate_case(case,data.corpus,[span])
    assert result['retrieved_context_on_unanswerable']
    assert result['hit_any_gold'] is result['gold_span_recall'] is result['reciprocal_rank'] is None
    assert result['claim_support'] is None

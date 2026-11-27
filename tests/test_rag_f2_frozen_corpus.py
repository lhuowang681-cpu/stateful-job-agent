"""Heldout source/label integrity, not a quality-score assertion."""
import json
from hashlib import sha256
from pathlib import Path
from job_agent.knowledge.evaluation_contract import EvaluationDataset,valid_span
from job_agent.knowledge.support_evaluation import SupportLabel

ROOT=Path(__file__).resolve().parents[1]


def test_finite_new_questions_and_source_families_are_separate_from_seen_data():
    folder=ROOT/'docs/evaluation/expansion';path=folder/'rag-round3-new16-v1.json'
    frozen=json.loads((folder/'rag-round3-new16-freeze-v1.json').read_text(encoding='utf-8'))
    assert sha256(path.read_bytes()).hexdigest()==frozen['dataset_sha256']
    data=EvaluationDataset.model_validate_json(path.read_text(encoding='utf-8'))
    test=[c for c in data.cases if c.split=='test']
    assert len(test)==16 and sum(c.answerable for c in test)==12
    seen=set();seen_queries=set()
    for name in ('review-real-project-chinese-v3.json','review-real-design-addendum-v1.json'):
        old=EvaluationDataset.model_validate_json((folder/name).read_text(encoding='utf-8'))
        seen.update(d.origin for d in old.corpus.documents);seen_queries.update(c.query for c in old.cases)
    assert not seen.intersection(d.origin for d in data.corpus.documents if d.split=='test')
    assert not seen_queries.intersection(c.query for c in test)
    labels=json.loads((folder/'rag-round3-new16-support-v1.json').read_text(encoding='utf-8'))
    docs={d.document_id:d for d in data.corpus.documents};by_id={c.case_id:c for c in test}
    assert len(labels['labels'])==16 and labels['human_reviewed']==0
    for item in labels['labels']:
        label=SupportLabel.model_validate(item);assert label.corpus_snapshot==data.corpus.snapshot_id
        assert label.answerable==by_id[label.case_id].answerable
        assert all(valid_span(s,docs) and docs[s.document_id].split=='test' for s in label.minimal_spans+label.symbol_ranges)

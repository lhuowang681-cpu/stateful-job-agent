"""Real-source research identity, partition and project-only replay contracts."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from job_agent.knowledge.evaluation_contract import EvaluationDataset
from job_agent.knowledge.index_manifest import fingerprint
from job_agent.knowledge.research_contract import prepare,inspect_bundle,evaluate,public_snapshot,corpus_origin
from test_v3_research_replay import runtime

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'docs/evaluation/expansion/review-real-project-chinese-v3.json'


def test_frozen_real_candidates_have_disjoint_source_families_and_cross_file_gold():
    data=EvaluationDataset.model_validate_json(DATA.read_text(encoding='utf-8'))
    assert len(data.cases)==40 and all(c.annotation_status=='ai_candidate' for c in data.cases)
    assert {s:sum(c.split==s for c in data.cases) for s in ('dev','test')}=={'dev':20,'test':20}
    assert sum(not c.answerable for c in data.cases)==8
    assert sum(len({g.document_id for g in c.gold})>1 for c in data.cases)==8
    origins={s:{d.origin for d in data.corpus.documents if d.split==s} for s in ('dev','test')}
    assert not origins['dev'] & origins['test']
    assert all(not p.startswith(('tests/','output/','docs/evaluation/','docs/devlog/')) for v in origins.values() for p in v)


def test_project_only_bundle_is_not_mislabeled_cc0_and_replays_without_fake_public_entries(tmp_path):
    data=json.loads(DATA.read_text(encoding='utf-8'))
    data['cases']=[c for c in data['cases'] if c['case_id'] in ('real-dev-code_rag-1','real-test-learning-1')]
    ids={g['document_id'] for c in data['cases'] for g in c['gold']}
    data['corpus']['documents']=[d for d in data['corpus']['documents'] if d['document_id'] in ids]
    snapshot='corpus-'+fingerprint(sorted(data['corpus']['documents'],key=lambda d:d['document_id']))
    data['corpus']['snapshot_id']=snapshot
    for c in data['cases']:c['source_snapshot']=snapshot
    path=tmp_path/'data.json';path.write_text(json.dumps(data),encoding='utf-8')
    bundle=tmp_path/'bundle'
    prepared=prepare(ROOT,bundle,path,runtime(),repeats=1,source_kind='owner_project_source')
    assert prepared['synthetic_only'] is False and prepared['source_kind']=='owner_project_source'
    inspect_bundle(ROOT,bundle)
    for split in ('dev','test'):
        assert json.loads((bundle/(split+'-public-vectors.json')).read_text())=={'empty_public_scope':True}
        assert prepared['scopes'][split]['public_versions']=={}
    run=evaluate(ROOT,bundle,tmp_path/'score',runtime=runtime(),variants=['A_bm25','B_dense','C_hybrid','D_hybrid_rerank'],repeats=1)
    assert run['status']=='completed' and run['encoder_calls']['document_calls']==0


def test_real_origin_and_empty_public_sentinel_cannot_waive_scope_contracts():
    data=EvaluationDataset.model_validate_json(DATA.read_text(encoding='utf-8'))
    with pytest.raises(ValueError,match='origin_invalid'):corpus_origin(data,'arbitrary_user_database')
    bad=data.model_copy(deep=True);bad.corpus.documents[0].origin='private-resume.txt'
    with pytest.raises(ValueError,match='owner_source_invalid'):corpus_origin(bad,'owner_project_source')
    bad=data.model_copy(deep=True);bad.corpus.documents[0].kind='public_knowledge'
    with pytest.raises(ValueError,match='public_scope_not_empty'):public_snapshot({'empty_public_scope':True},bad,'dev')

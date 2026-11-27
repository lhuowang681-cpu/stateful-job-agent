"""Research replay is artifact identity, not semantic quality or a production backup."""
from copy import deepcopy
from pathlib import Path
import json,shutil
import pytest
from job_agent.knowledge.research_contract import (
    prepare,inspect_bundle,evaluate,replay,read_json,write_new,freeze_gate,check_gate,summarize,
    file_hash,fingerprint,child,open_services)
from job_agent.knowledge.reranker import RerankerIdentity,RerankBatch
from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime
from test_v3_retrieval_identity import FixtureBackend

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'docs/evaluation/expansion/candidates-v3.json'


class FixtureReranker:
    identity=RerankerIdentity('test-only','fixture-v1','test-only')
    def score(self,query,passages):return RerankBatch([1. for _ in passages])


def runtime():
    backend=FixtureBackend();return RetrievalRuntime(backend,backend.identity,FixtureReranker())


@pytest.fixture
def bundle(tmp_path):
    path=tmp_path/'bundle';prepare(ROOT,path,DATA,runtime(),repeats=1);return path


def test_fixed_scope_new_directory_replay_uses_stored_vectors_and_full_ranked_citations(bundle,tmp_path):
    run=evaluate(ROOT,bundle,tmp_path/'dev',runtime=runtime())
    assert run['status']=='completed' and run['summary']['A_bm25']['cases']==36
    assert run['encoder_calls']['document_calls']==0 and run['human_reviewed_count']==0
    assert run['summary']['E_code_aware_no_relations']['cases']==22
    copy=tmp_path/'copied';shutil.copytree(bundle,copy)
    result=replay(ROOT,copy,tmp_path/'dev',tmp_path/'replay.json',split='dev',runtime=runtime())
    assert result['status']=='passed' and result['cases']==210
    assert result['encoder_calls']['document_calls']==0
    assert read_json(copy/'manifest.json')==read_json(bundle/'manifest.json')


def test_offline_bm25_requires_no_encoder_and_preserves_corpus_scope(bundle,tmp_path):
    run=evaluate(ROOT,bundle,tmp_path/'offline',variants=['A_bm25'],repeats=1)
    assert run['status']=='completed' and run['encoder_calls'] is None and not run['runtime_loaded']
    assert run['tokens'] is run['cost'] is None
    assert run['summary']['A_bm25']['answerable_cases']==34


def test_heldout_requires_explicit_intent_and_cannot_be_silently_scored_twice(bundle,tmp_path):
    with pytest.raises(ValueError,match='explicit_flag'):evaluate(ROOT,bundle,tmp_path/'no',split='test',runtime=runtime())
    run=evaluate(ROOT,bundle,tmp_path/'test',split='test',runtime=runtime(),score_heldout=True)
    assert run['status']=='completed' and run['heldout_scored']
    with pytest.raises(FileExistsError):evaluate(ROOT,bundle,tmp_path/'test-again',split='test',runtime=runtime(),score_heldout=True)
    assert read_json(bundle/'heldout-reservation.json')['run_directory_name']=='test'


@pytest.mark.parametrize('name',['dataset.json','dev.sqlite','test-public-vectors.json'])
def test_changed_artifact_fails_before_replay(bundle,name):
    with (bundle/name).open('ab') as f:f.write(b' ')
    with pytest.raises(ValueError,match='artifact_hash_changed'):inspect_bundle(ROOT,bundle)


def test_source_identity_drift_is_explicit_and_offline_candidate_can_be_compared(bundle):
    sealed=read_json(bundle/'manifest.json');sealed['payload']['algorithm_sources']['scripts/expansion_research.py']='0'*64
    sealed['payload']['algorithm_identity']=fingerprint(sealed['payload']['algorithm_sources'])
    sealed['sha256']=fingerprint(sealed['payload']);(bundle/'manifest.json').write_text(json.dumps(sealed),encoding='utf-8')
    with pytest.raises(ValueError,match='algorithm_changed'):inspect_bundle(ROOT,bundle)
    assert inspect_bundle(ROOT,bundle,strict_algorithm=False)[2]!=sealed['payload']['algorithm_identity']


@pytest.mark.parametrize('path',['../private.sqlite','/etc/passwd','C:\\private.sqlite'])
def test_artifact_paths_cannot_escape_bundle(tmp_path,path):
    with pytest.raises(ValueError,match='path_'):child(tmp_path,path)


def test_user_resume_data_is_rejected_even_when_research_db_hash_is_resealed(bundle):
    import sqlite3
    with sqlite3.connect(bundle/'dev.sqlite') as db:
        db.execute('CREATE TABLE private_user_data (text TEXT)');db.execute("INSERT INTO private_user_data VALUES ('synthetic sentinel')")
    sealed=read_json(bundle/'manifest.json');sealed['payload']['artifacts']['dev.sqlite']=file_hash(bundle/'dev.sqlite')
    sealed['sha256']=fingerprint(sealed['payload']);(bundle/'manifest.json').write_text(json.dumps(sealed),encoding='utf-8')
    with pytest.raises(ValueError,match='nonresearch_data'):inspect_bundle(ROOT,bundle)


def test_missing_rows_and_failed_queries_cannot_improve_metrics_by_disappearing(bundle,tmp_path):
    _,data,_=inspect_bundle(ROOT,bundle);cases=[c for c in data.cases if c.split=='dev' and c.answerable][:2]
    rows=[{'case_id':c.case_id,'variant':'A_bm25','repeat':0,'error':'ValueError' if i else None,
           'metrics':{'sufficient_gold_retrieved':True} if not i else None,
           'metrics_at_k':{str(k):{n:1. for n in ('hit_any_gold','gold_span_recall','sufficient_gold_retrieved','reciprocal_rank')} for k in (1,3,5)} if not i else None,
           'elapsed_ms':1.,'citation_valid':[True] if not i else []} for i,c in enumerate(cases)]
    summary=summarize(rows,cases)['A_bm25']
    assert summary['metrics_at_k']['5']['hit_any_gold']=={'mean':.5,'cases':2}
    assert summary['failed_attempts']==1


def test_gate_is_measured_dev_only_positive_and_refuses_regression_and_empty_coverage(bundle,tmp_path):
    run=evaluate(ROOT,bundle,tmp_path/'baseline',variants=['A_bm25'],repeats=1)
    gate=freeze_gate(run,tmp_path/'gate.json')
    assert all(v>0 for v in gate['floors'].values())
    assert check_gate(run,tmp_path/'gate.json')['status']=='passed'
    worse=deepcopy(run);worse['summary']['A_bm25']['metrics_at_k']['5']['reciprocal_rank']['mean']=0.
    assert check_gate(worse,tmp_path/'gate.json')['failed_metrics']==['reciprocal_rank']
    empty=deepcopy(run);empty['summary']['A_bm25']['answerable_cases']=0
    with pytest.raises(ValueError,match='coverage'):check_gate(empty,tmp_path/'gate.json')
    heldout=deepcopy(run);heldout['split']='test';heldout['heldout_scored']=True
    with pytest.raises(ValueError,match='dev_baseline'):freeze_gate(heldout,tmp_path/'bad-gate.json')
    sealed=read_json(tmp_path/'gate.json');sealed['payload']['floors']['reciprocal_rank']=0.
    sealed['sha256']=fingerprint(sealed['payload']);(tmp_path/'gate.json').write_text(json.dumps(sealed),encoding='utf-8')
    with pytest.raises(ValueError,match='floor_invalid'):check_gate(run,tmp_path/'gate.json')


def test_replay_rejects_missing_reference_case_after_rehash(bundle,tmp_path):
    evaluate(ROOT,bundle,tmp_path/'dev',runtime=runtime(),variants=['A_bm25'])
    path=tmp_path/'dev/queries.jsonl';lines=path.read_text(encoding='utf-8').splitlines();path.write_text('\n'.join(lines[:-1])+'\n',encoding='utf-8')
    run=read_json(tmp_path/'dev/run.json');run['raw_sha256']=file_hash(path);(tmp_path/'dev/run.json').write_text(json.dumps(run),encoding='utf-8')
    with pytest.raises(ValueError,match='coverage_changed'):replay(ROOT,bundle,tmp_path/'dev',tmp_path/'bad.json',split='dev',runtime=runtime())

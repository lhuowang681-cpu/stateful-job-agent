"""Synthetic grading fixtures verify scope contracts, not model quality."""
import json
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.parsing import ResumeParser
from job_agent.resume_workspace.repository import SqliteResumeRepository
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.code_rag import CodeRAGService
from job_agent.resume_workspace.interview_contracts import Evaluation
from job_agent.resume_workspace.project_evidence import unsupported_source_claim,requested_boundary_flags
from job_agent.llm.providers.mock import result_from_raw_output

A={'Authorization':'Bearer synthetic-round3'}
SOURCE='def read_value(value):\n    if not isinstance(value, str):\n        raise ValueError("string required")\n    return value.strip()\n'


class Fixture:
    provider_name='synthetic-boundary-contract';model='not-real-model'
    def __init__(self):self.answer='';self.omit=False;self.calls=0
    def generate_structured(self,**kw):
        self.calls+=1
        if kw['output_schema'] is Evaluation:
            data={'covered_ids':['p0','p1','p2'],'missing_ids':[],'claim_needs_evidence':False,'recommended_action':'next','note':'Synthetic fixture only'}
            if not self.omit:data['point_assessments']=[{'point_id':f'p{i}','status':'correct','answer_quote':self.answer[:100],'reason':'Explicit fixture'} for i in range(3)]
        else:data={'action':'next','focus_id':None,'retrieval_target':'none'}
        return result_from_raw_output(provider=self.provider_name,model=self.model,raw_output=json.dumps(data),
            output_schema=kw['output_schema'],trace=kw['trace'],latency_ms=1,input_tokens=10,output_tokens=20)


@pytest.fixture
def env(tmp_path):
    ws=SqliteResumeRepository(tmp_path/'workspace.sqlite');fixture=Fixture()
    with TestClient(create_resume_app(ws,resolve_identity={'synthetic-round3':'alice'}.get,parser=ResumeParser(fixture),task_worker_enabled=False)) as client:
        source=client.post('/api/v2/sources',headers=A,json={'kind':'original_resume','label':'Synthetic','text':'姓名：合成同学\n项目经历\n本地原型 | 开发 | 2025\n- 参与本地接口练习。'}).json()
        draft=client.post('/api/v2/sources/'+source['source_id']+'/parse',headers=A,json={'mode':'local_rules'}).json()
        response=client.post('/api/v2/drafts/'+draft['draft_id']+'/accept',headers=A,json={'title':'Synthetic','expected_source_hash':source['content_hash'],'user_reviewed':True})
        assert response.status_code==201
        yield ws,client,response.json(),fixture


def project(ws,files):
    store=LongTermRepository(ws);p=store.create_project('alice',ProjectCreate(name='Authored fixture'))
    p=store.publish_files('alice',p['project_id'],files,origin='zip');CodeRAGService(ws).build('alice',p['project_id'],p['current_snapshot']);return p


def start(env,p,topic,mode='local_demo'):
    _,c,v,_=env;r=c.post('/api/v2/resumes/'+v['resume_id']+'/interviews',headers=A,json={'request_key':uuid4().hex,
        'version_id':v['version_id'],'expected_content_hash':v['content_hash'],'jd_text':topic,'mode':mode,'max_turns':2,'use_retrieval':True,
        'track':'project','project_id':p['project_id'],'snapshot_id':p['current_snapshot'],'allow_external_processing':True})
    assert r.status_code==201,r.text
    return r.json()


def answer(env,view,text):
    _,c,_,fixture=env;fixture.answer=text
    r=c.post('/api/v2/interviews/'+view['session_id']+'/answers',headers=A,json={'request_key':uuid4().hex,'question_id':view['current']['question_id'],
        'expected_revision':view['revision'],'answer':text,'allow_external_processing':True});assert r.status_code==200,r.text;return r.json()


@pytest.mark.parametrize('text',[
    '没有测量录用率，不能证明提升50%。','我未运行测试，也不知道QPS是多少。','假如录用率提升10%需要验证样本。',
    '这里只解释静态源码，不代表已经上线。','未来会记录P95字段。'])
def test_explicit_uncertainty_or_hypothesis_is_not_a_positive_operational_claim(text):
    assert unsupported_source_claim(text) is None


@pytest.mark.parametrize('text',[
    '录用率提高50%。','系统已经上线。','历史计划证明现在已经完成。','没有测试，但录用率提高50%。','源码显示录用率提高50%。',
    '我独立负责开发整个系统。','系统已经部署。'])
def test_narrow_unsupported_positive_claims_are_flagged(text):
    assert unsupported_source_claim(text) is not None


def test_source_can_be_sufficient_for_a_narrow_question_without_proving_topic(env):
    ws,c,_,_=env;p=project(ws,{'reader.py':SOURCE})
    normal=start(env,p,'read_value 的参数和返回值')
    assert normal['current']['evidence_boundary']['question_source_status']=='source_sufficient'
    assert normal['current']['evidence_boundary']['requested_topic_status']=='located_unjudged'
    insufficient=start(env,p,'read_value 的实际录用率提高了多少？')
    context=insufficient['current']['evidence_boundary']
    assert context['requested_topic_status']=='topic_only' and context['answer_policy']=='needs_input'
    assert '未找到足以确认原主题事实' in insufficient['current']['prompt']
    assert 'runtime_measurements_unverified' in context['reason_codes']


def test_long_symbol_question_is_explicitly_only_about_visible_excerpt(env):
    ws,_,_,_=env;p=project(ws,{'reader.py':'def read_value(value):\n'+''.join(f'    v{i} = value\n' for i in range(100))+'    return v99\n'})
    view=start(env,p,'read_value')
    assert view['current']['evidence_boundary']['question_source_status']=='partial'
    assert '未展示' in view['current']['prompt']


def test_cross_file_incompleteness_remains_in_question_scope(env):
    ws,_,_,_=env;p=project(ws,{'reader.py':SOURCE});view=start(env,p,'跨文件 read_value 的调用方怎样使用返回值？')
    context=view['current']['evidence_boundary']
    assert context['requested_topic_status']=='partial' and 'cross_file_coverage_incomplete' in context['reason_codes']


def test_guarded_model_result_and_source_boundary_survive_learning_and_fixed_practice(env):
    ws,c,_,_=env;p=project(ws,{'reader.py':SOURCE});view=start(env,p,'read_value 原型的录用率提升多少？','llm')
    before=view['current'];view=answer(env,view,'read_value 输入字符串并返回去空白结果，录用率提高50%。')
    assert view['revision']==1 and view['status']!='failed',(view.get('error_code'),view['usage'])
    finished=c.post('/api/v2/interviews/'+view['session_id']+'/finish',headers=A,json={'expected_revision':view['revision']})
    assert finished.status_code==200
    saved=c.post('/api/v2/interviews/'+view['session_id']+'/learning-observations',headers=A).json()
    assert saved['added']==3
    observation=next(o for o in saved['observations'] if o['payload']['point_id']=='p2')
    assert observation['payload']['finding']=='uncertain' and observation['payload']['independent_mastery']=='not_established'
    assert observation['payload']['evidence_boundary']==before['evidence_boundary']
    from job_agent.resume_workspace.execution_state import state_hash
    trace=c.get('/api/v2/interviews/'+view['session_id']+'/trace',headers=A).json()
    expected=state_hash({'evidence_status':'topic_only','answer_policy':'needs_input','reason_codes':['runtime_measurements_unverified']})
    assert any(e['kind']=='retrieval' and e['status']=='topic_only' and e['output_hash']==expected for e in trace['events'])
    key=observation['observation_id']
    observation=c.post('/api/v2/learning/observations/'+key+'/actions',headers=A,json={'request_key':uuid4().hex,'expected_revision':observation['revision'],'action':'confirm'}).json()
    response=c.post('/api/v2/learning/observations/'+key+'/practice',headers=A,json={'request_key':uuid4().hex,'expected_revision':observation['revision'],'mode':'llm','allow_external_processing':True})
    assert response.status_code==200,response.text
    practice=response.json();assert practice['turns']==[] and practice['current']['evidence_boundary']==before['evidence_boundary']
    assert practice['current']['prompt']==before['prompt'] and practice['current']['question_id']!=before['question_id']


def test_missing_model_items_cannot_be_repaired_by_boundary_guard(env):
    ws,c,_,fixture=env;p=project(ws,{'reader.py':SOURCE});view=start(env,p,'read_value 实际录用率多少？','llm');fixture.omit=True
    result=answer(env,view,'录用率提高50%。')
    assert result['status']=='failed' and result['revision']==0 and fixture.calls==1
    assert result['error_code']=='interview_incomplete_semantic_review' and not result['model_inflight']
    assert c.post('/api/v2/interviews/'+view['session_id']+'/learning-observations',headers=A).status_code==409


def test_current_and_historical_documents_mark_applicability_conflict(env):
    ws,c,_,_=env;p=project(ws,{'reader.py':SOURCE,
        'docs/CURRENT_SPEC.md':'当前 read_value 实现：已有静态函数。本材料没有生产运行证明。\n',
        'docs/CURRENT_SPEC_HISTORY_2025.md':'历史 read_value 计划：当时尚未实现。历史不能说明当前部署状态。\n'})
    response=c.post('/api/v2/evidence/retrieve',headers=A,json={'scope':'private_project','project_id':p['project_id'],
        'snapshot_id':p['current_snapshot'],'query':'read_value 当前 历史 计划 实现 部署'})
    assert response.status_code==200,response.text
    pack=response.json();assert pack['evidence_status']=='conflict' and pack['answer_policy']=='needs_input'
    assert 'mixed_current_historical_sources' in pack['missing'] and pack['claim_assessments'][0]['status']=='conflict'
    transaction=c.post('/api/v2/evidence/retrieve',headers=A,json={'scope':'private_project','project_id':p['project_id'],
        'snapshot_id':p['current_snapshot'],'query':'read_value 当前事务的输入边界'}).json()
    assert transaction['evidence_status']!='conflict' and 'version_applicability_unresolved' not in transaction['missing']


def test_no_location_stops_project_session_without_model_or_learning(env):
    ws,c,v,fixture=env;p=project(ws,{'reader.py':SOURCE})
    body={'scope':'private_project','project_id':p['project_id'],'snapshot_id':p['current_snapshot'],'query':'zzzxq12345'}
    pack=c.post('/api/v2/evidence/retrieve',headers=A,json=body).json()
    assert pack['evidence_status']=='not_located' and pack['answer_policy']=='needs_input' and pack['items']==[]
    response=c.post('/api/v2/resumes/'+v['resume_id']+'/interviews',headers=A,json={'request_key':uuid4().hex,
        'version_id':v['version_id'],'expected_content_hash':v['content_hash'],'jd_text':'zzzxq12345','mode':'llm','max_turns':2,
        'use_retrieval':True,'track':'project','project_id':p['project_id'],'snapshot_id':p['current_snapshot'],'allow_external_processing':True})
    assert response.status_code==409 and fixture.calls==0
    with ws._connection() as db:assert db.execute('SELECT COUNT(*) FROM rw_learning_observations').fetchone()[0]==0


def test_old_fixed_source_observation_condition_hash_remains_readable():
    from pathlib import Path
    from job_agent.resume_workspace.interview_contracts import InterviewState
    from job_agent.resume_workspace.learning import condition
    from job_agent.resume_workspace.long_term import digest
    artifact=Path(__file__).resolve().parents[1]/'docs/devlog/evidence/review-20261023/r5-deepseek-fixed-reference-learning-v2.json'
    old=json.loads(artifact.read_text(encoding='utf-8'))['learning'][0]
    state=InterviewState.model_validate(old['synthetic_state']);saved=old['observations']['observations'][0]['payload']
    turn=next(t for t in state.turns if t.question.question_id==saved['question_id'])
    topic=next(t for t in state.plan if t.anchor_id==turn.question.topic_id)
    assert turn.question.evidence_boundary is None
    assert digest(condition(state,turn,topic,saved['point_id']))==saved['condition_hash']

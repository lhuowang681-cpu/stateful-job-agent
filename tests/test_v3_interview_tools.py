"""Real scoped retrieval + synthetic providers: mechanics, not LLM quality."""
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.repository import SqliteResumeRepository,WorkspaceConflict
from job_agent.resume_workspace.contracts import SourceCreate
from job_agent.resume_workspace.parsing import ResumeParser
from job_agent.resume_workspace.parsing_contracts import AcceptDraft
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.code_rag import CodeRAGService
from job_agent.resume_workspace.public_knowledge import PublicKnowledgeService
from job_agent.resume_workspace.interview_tools import InterviewTools,MAX_TOOLS
from job_agent.resume_workspace.retrieval_interview import RetrievalInterviewEngine
from job_agent.resume_workspace.interview_contracts import Evaluation
from job_agent.llm.providers.mock import result_from_raw_output

A={'Authorization':'Bearer a'};B={'Authorization':'Bearer b'}
FILES={'app/storage.py':'def save_receipt(key, store):\n    if key not in store:\n        store[key] = "done"\n    return store[key]\n',
    'app/api.py':'from .storage import save_receipt\ndef handle(key, store):\n    return save_receipt(key, store)\n',
    'tests/test_storage.py':'from app.storage import save_receipt\ndef test_duplicate():\n    store = {}\n    assert save_receipt("a", store) == save_receipt("a", store)\n'}


@pytest.fixture
def env(tmp_path):
    ws=SqliteResumeRepository(tmp_path/'ws.sqlite')
    source=ws.add_source('alice',SourceCreate(kind='original_resume',label='Synthetic',text='姓名：合成同学\n项目经历\n示例项目 | 开发 | 2025\n- 使用 Python 实现示例。'))
    draft=ws.save_draft('alice',ResumeParser().parse(source))
    version=ws.accept_draft('alice',draft.draft_id,AcceptDraft(title='合成',expected_source_hash=source.content_hash,user_reviewed=True))
    projects=LongTermRepository(ws);p=projects.create_project('alice',ProjectCreate(name='Synthetic'))
    p=projects.publish_files('alice',p['project_id'],FILES,origin='github',commit_sha='a'*40)
    code=CodeRAGService(ws);code.build('alice',p['project_id'],p['current_snapshot'])
    knowledge=PublicKnowledgeService(ws)
    return ws,version,projects,p,code,knowledge


def client(env,provider=None):
    ws,_,_,_,code,kb=env
    return TestClient(create_resume_app(ws,resolve_identity={'a':'alice','b':'bob'}.get,
        interview_engine=RetrievalInterviewEngine(ws,kb,code,provider)))


def start(c,env,**kw):
    _,v,_,p,_,_=env
    payload={'request_key':'v3-start-synthetic','version_id':v.version_id,'expected_content_hash':v.content_hash,
        'jd_text':'save_receipt callers references','use_retrieval':True,'track':'project',
        'project_id':p['project_id'],'snapshot_id':p['current_snapshot'],**kw}
    r=c.post(f'/api/v2/resumes/{v.resume_id}/interviews',headers=A,json=payload)
    assert r.status_code==201,r.text
    return r.json()


def answer(c,v,text='请查测试，我还没有运行过。',**kw):
    r=c.post(f"/api/v2/interviews/{v['session_id']}/answers",headers=A,json={
        'request_key':f"v3-answer-{v['revision']}",'question_id':v['current']['question_id'],
        'expected_revision':v['revision'],'answer':text,**kw})
    assert r.status_code==200,r.text
    return r.json()


def test_project_search_feedback_tools_followup_and_review(env):
    c=client(env);v=start(c,env)
    assert v['tool_trace'][0]['tool']=='code_search'
    assert v['current']['references'][0]['path']=='app/storage.py'
    assert 'answer_points' not in json.dumps(v) and 'missing_ids' not in json.dumps(v)
    n=answer(c,v)
    assert n['current']['followup'] and '测试源码' in n['current']['prompt']
    assert {'get_symbol','find_references'}<={t['tool'] for t in n['tool_trace']}
    assert any(r['evidence_kind']=='test_code' for r in n['current']['references'])
    assert all(r['independent_truth']=='not_verified' for r in n['current']['references'])
    url=f"/api/v2/interviews/{v['session_id']}"
    assert c.get(url+'/review',headers=A).status_code==409
    assert c.get(url,headers=B).status_code==404
    c.post(url+'/finish',headers=A,json={'expected_revision':n['revision']})
    review=c.get(url+'/review',headers=A).json()
    assert review['weaknesses'] and review['code_references']
    assert '个人贡献' in review['source_boundary']


def test_different_feedback_selects_reference_not_test_target(env):
    c=client(env);v=start(c,env);n=answer(c,v,'请说明边界，我还不清楚。')
    assert '调用方' in n['current']['prompt']
    assert n['messages'][-2]['retrieval_target']=='references'


def test_job_public_retrieval_and_weakness_reuses_only_completed_review(env):
    c=client(env);v=start(c,env,track='job',project_id=None,snapshot_id=None,jd_text='Checkpoint 长期记忆')
    assert v['tool_trace'][0]['tool']=='question_search'
    assert all(r['scope']=='public_knowledge' for r in v['current']['references'])
    _,version,_,_,_,_=env;url=f'/api/v2/resumes/{version.resume_id}/interviews'
    req={'request_key':'weakness-start-key','version_id':version.version_id,'expected_content_hash':version.content_hash,
        'jd_text':'专项复习','use_retrieval':True,'track':'weakness','prior_session_id':v['session_id']}
    assert c.post(url,headers=A,json=req).status_code==409
    v=answer(c,v,'我还需要学习。')
    assert v['tool_trace'][-1]['tool']=='knowledge_search'
    assert 'body' not in json.dumps(v['tool_trace'])
    c.post(f"/api/v2/interviews/{v['session_id']}/finish",headers=A,json={'expected_revision':v['revision']})
    n=c.post(url,headers=A,json=req)
    assert n.status_code==201,n.text
    assert n.json()['track']=='weakness' and n.json()['tool_calls']==1
    n=answer(c,n.json(),'线程运行状态、跨会话偏好与持久化边界。')
    c.post(f"/api/v2/interviews/{n['session_id']}/finish",headers=A,json={'expected_revision':n['revision']})
    review=c.get(f"/api/v2/interviews/{n['session_id']}/review",headers=A).json()
    assert review['practice_comparison']['prior_session_id']==v['session_id']
    assert review['practice_comparison']['status'] in ('comparable','not_comparable')
    assert '不能证明' in review['practice_comparison']['warning']


def test_source_delete_revokes_live_and_historical_quotes(env):
    c=client(env);v=start(c,env);_,_,projects,p,_,_=env
    projects.delete_project('alice',p['project_id'])
    assert c.get(f"/api/v2/interviews/{v['session_id']}",headers=A).status_code==404


def test_scope_fields_cannot_be_added_to_model_tool_arguments(env):
    ws,_,_,p,code,kb=env;tools=InterviewTools(ws,kb,code,'alice',p['project_id'],p['current_snapshot'])
    state=SimpleNamespace(session_id='synthetic',tool_calls=0,tool_fingerprints=[],tool_trace=[],revision=0)
    with pytest.raises(WorkspaceConflict,match='permission'):
        tools.run(state,'coach','get_symbol',{'name':'save_receipt'})
    with pytest.raises(WorkspaceConflict,match='tool_failed'):
        tools.run(state,'interviewer','get_symbol',{'name':'save_receipt','owner':'bob'})
    assert state.tool_trace[-1]['error_code']=='tool_input_error'
    assert state.tool_calls==1


def test_tool_total_budget_and_duplicate_fingerprint(env):
    ws,_,_,p,code,kb=env;tools=InterviewTools(ws,kb,code,'alice',p['project_id'],p['current_snapshot'])
    state=SimpleNamespace(session_id='synthetic',tool_calls=0,tool_fingerprints=[],tool_trace=[],revision=0)
    tools.run(state,'coach','knowledge_search',{'query':'AST'})
    assert tools.run(state,'coach','knowledge_search',{'query':'AST'})['skipped']=='duplicate_read'
    assert state.tool_calls==1
    state.tool_calls=MAX_TOOLS
    with pytest.raises(WorkspaceConflict,match='budget'):tools.run(state,'coach','knowledge_search',{'query':'RRF'})


class RoutingProvider:
    provider_name='synthetic-provider';model='structured-routing-fixture-not-llm'
    def __init__(self,target):self.target=target;self.calls=[]
    def generate_structured(self,**kw):
        self.calls.append(kw)
        raw={'covered_ids':[],'missing_ids':['p0','p1','p2'],'claim_needs_evidence':False,'recommended_action':'follow_up','note':'synthetic feedback'} if kw['output_schema'] is Evaluation else {
            'action':'follow_up','focus_id':'p1','retrieval_target':self.target}
        if kw['output_schema'] is Evaluation:
            raw['point_assessments']=[{'point_id':f'p{i}','status':'uncertain','answer_quote':'',
                'reason':'Synthetic complete uncertain input for real tool dispatch contract'} for i in range(3)]
        return result_from_raw_output(provider=self.provider_name,model=self.model,raw_output=json.dumps(raw),
            output_schema=kw['output_schema'],trace=kw['trace'],latency_ms=1,input_tokens=10,output_tokens=10)


@pytest.mark.parametrize('target',['tests','references','symbol'])
def test_structured_provider_decision_dispatches_different_real_read_tool(env,target):
    p=RoutingProvider(target);c=client(env,p);v=start(c,env,mode='llm',allow_external_processing=True)
    n=answer(c,v,allow_external_processing=True)
    assert n['revision']==1 and n['current']['followup'] and len(p.calls)==2
    assert n['messages'][-2]['retrieval_target']==target
    names=[t['tool'] for t in n['tool_trace']]
    assert ('find_references' in names)==(target in ('tests','references'))
    assert 'rubric' not in p.calls[1]['user_prompt'] and 'permitted_retrieval_targets' in p.calls[1]['user_prompt']


def test_invalid_model_target_does_not_access_other_tool_scope(env):
    p=RoutingProvider('public_docs');c=client(env,p);v=start(c,env,mode='llm',allow_external_processing=True)
    n=answer(c,v,allow_external_processing=True)
    assert n['status']=='failed' and n['tool_calls']==1


def test_project_interview_remains_bounded_and_does_not_execute_source(env):
    c=client(env);v=start(c,env,max_turns=6)
    for _ in range(6):v=answer(c,v,'暂不清楚。')
    assert v['status']=='complete' and v['revision']==6
    assert v['tool_calls']<=MAX_TOOLS and v['usage']['provider_calls']==0


def test_pause_reopen_continue_preserves_question_and_rejects_answers_while_paused(env):
    c=client(env);v=start(c,env);url=f"/api/v2/interviews/{v['session_id']}"
    assert c.post(url+'/pause',headers=A,json={'expected_revision':0}).json()['status']=='paused'
    payload={'request_key':'paused-answer-key','question_id':v['current']['question_id'],'expected_revision':0,'answer':'暂停期间不应处理'}
    assert c.post(url+'/answers',headers=A,json=payload).status_code==409
    c=client(env)
    paused=c.get(url,headers=A).json()
    assert paused['status']=='paused' and paused['current']==v['current']
    assert c.post(url+'/continue',headers=B,json={'expected_revision':0}).status_code==404
    resumed=c.post(url+'/continue',headers=A,json={'expected_revision':0}).json()
    assert resumed['status']=='active' and resumed['tool_calls']==1
    assert answer(c,resumed)['revision']==1


def test_model_consent_before_project_source_dispatch(env):
    p=RoutingProvider('tests');c=client(env,p);v=start(c,env,mode='llm',allow_external_processing=True)
    payload={'request_key':'no-consent-key','question_id':v['current']['question_id'],'expected_revision':0,'answer':'未同意外发'}
    assert c.post(f"/api/v2/interviews/{v['session_id']}/answers",headers=A,json=payload).status_code==422
    assert not p.calls

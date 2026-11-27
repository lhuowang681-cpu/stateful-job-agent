"""Shared graph state, feedback consumption, leases and no-replay contracts."""
import json
from hashlib import sha256
from threading import Event,Thread
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from job_agent.resume_workspace.repository import SqliteResumeRepository,WorkspaceConflict
from job_agent.resume_workspace.contracts import SourceCreate
from job_agent.resume_workspace.parsing import ResumeParser
from job_agent.resume_workspace.parsing_contracts import AcceptDraft
from job_agent.resume_workspace.rewrite import RewriteRoles,RewriteService,RewriteRequest,EditDraft,EditReview
from job_agent.resume_workspace.execution_state import SharedRunState,state_hash
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.interview_collaboration import InterviewEngine,local_evaluate,build_plan,question_for
from job_agent.resume_workspace.interview_contracts import Evaluation,InterviewState,PendingAnswer
from job_agent.llm.provider import ProviderTimeoutError
from job_agent.llm.providers.mock import result_from_raw_output
from datetime import datetime,UTC

A={'Authorization':'Bearer a'}


@pytest.fixture
def env(tmp_path):
    ws=SqliteResumeRepository(tmp_path/'state.sqlite')
    source=ws.add_source('alice',SourceCreate(kind='original_resume',label='Synthetic',text='姓名：合成同学\n项目经历\n原型 | 开发 | 2025\n- 使用 Python 开发本地原型接口。'))
    draft=ws.save_draft('alice',ResumeParser().parse(source))
    version=ws.accept_draft('alice',draft.draft_id,AcceptDraft(title='Synthetic',expected_source_hash=source.content_hash,user_reviewed=True))
    return ws,version


def rewrite_request(v,**kw):
    return RewriteRequest(request_key='shared-rewrite-001',version_id=v.version_id,expected_content_hash=v.content_hash,
        source_path='projects.0.bullets.0',jd_text='Python 实习',**kw)


def test_graph_feedback_identity_reaches_next_writer_and_audits_survive_restart(env):
    ws,v=env
    class Roles(RewriteRoles):
        def __init__(self):self.feedback=[]
        def invoke(self,role,source,context,jd,drafts,mode,run_id,revision):
            if role=='writer':
                if revision==1:return EditDraft(text=source+'显著提升求职成功率。',reason='Synthetic deliberately unsupported expansion')
                self.feedback.append(context['shared_execution']['latest_feedback'])
                assert drafts[-1]['review']['constraint']==self.feedback[-1]['constraint']
                assert 'owner_id' not in context['shared_execution'] and 'execution_token' not in context['shared_execution']
                return EditDraft(text=source.replace('使用','基于').replace('开发','实现'),reason='Remove unsupported outcome using feedback')
            return EditReview(outcome='accept',constraint='Synthetic permissive reviewer cannot waive hard gate')
    roles=Roles();state=RewriteService(ws,roles=roles).start('alice',v.resume_id,rewrite_request(v))
    assert state['status']=='awaiting_approval' and len(state['drafts'])==2 and state['usage']['role_calls']==4
    assert state['drafts'][0]['claim_audit']['claims'][-1]['status']=='unsupported'
    second_writer=next(e for e in state['execution']['events'] if e['role']=='writer' and e['phase']=='started' and e['revision']==2)
    assert second_writer['feedback_id']==roles.feedback[0]['feedback_id']
    assert state['drafts'][-1]['claim_audit']['acceptable']
    assert RewriteService(SqliteResumeRepository(ws.path)).get('alice',state['run_id'])==state


def test_identical_bad_draft_stops_without_spending_all_six_calls(env):
    ws,v=env
    class Repeat(RewriteRoles):
        def invoke(self,role,*args):
            return EditDraft(text=args[0]+'显著提升成功率。',reason='Synthetic repeated error') if role=='writer' else EditReview(outcome='accept',constraint='Synthetic')
    state=RewriteService(ws,roles=Repeat()).start('alice',v.resume_id,rewrite_request(v))
    assert state['status']=='needs_input' and len(state['drafts'])==1 and state['usage']['role_calls']==3
    assert state['execution']['events'][-1]['code']=='no_progress'


def test_reviewer_needs_input_is_not_overridden_into_another_revision(env):
    ws,v=env
    class NeedsInput(RewriteRoles):
        def invoke(self,role,source,*args):
            return EditDraft(text=source.replace('使用','以'),reason='Synthetic ambiguous paraphrase') if role=='writer' else EditReview(outcome='needs_input',constraint='需要用户澄清，不能凭本轮材料推断。')
    state=RewriteService(ws,roles=NeedsInput()).start('alice',v.resume_id,rewrite_request(v))
    assert state['status']=='needs_input' and state['usage']['role_calls']==2
    assert state['drafts'][0]['review']['outcome']=='needs_input'


def test_expired_live_writer_is_fenced_after_read_recovers_the_saved_state(env):
    ws,v=env;now=SimpleNamespace(value=100.);entered=Event();release=Event();results=[];errors=[]
    class Blocked(RewriteRoles):
        def __init__(self):self.calls=0
        def invoke(self,role,source,*args):
            self.calls+=1;entered.set();assert release.wait(4)
            return EditDraft(text=source.replace('使用','基于'),reason='Synthetic delayed result')
    roles=Blocked();service=RewriteService(ws,roles=roles,clock=lambda:now.value)
    def run():
        try:results.append(service.start('alice',v.resume_id,rewrite_request(v)))
        except BaseException as exc:errors.append(exc)
    thread=Thread(target=run);thread.start()
    try:
        assert entered.wait(3)
        with ws._connection() as db:run_id=db.execute('SELECT run_id FROM rw_rewrites').fetchone()[0]
        now.value=281.;recovered=service.get('alice',run_id)
        assert recovered['status']=='failed' and recovered['execution']['recovery']=='expired_execution'
    finally:release.set();thread.join(4)
    assert not thread.is_alive() and not errors and results[0]==recovered and roles.calls==1
    assert service.start('alice',v.resume_id,rewrite_request(v))==recovered and roles.calls==1
    assert ws.list_resumes('alice')[0].version_count==1


@pytest.mark.parametrize('field,value',[('owner_id','bob'),('event_seq',999)])
def test_execution_binding_rejects_rehashed_owner_or_event_corruption(env,field,value):
    ws,v=env;service=RewriteService(ws);state=service.start('alice',v.resume_id,rewrite_request(v))
    with ws._connection(write=True) as db:
        row=db.execute('SELECT payload FROM rw_rewrites').fetchone();raw=json.loads(row[0]);raw['execution'][field]=value
        text=json.dumps(raw,ensure_ascii=False);db.execute('UPDATE rw_rewrites SET payload=?,payload_hash=?',(text,sha256(text.encode()).hexdigest()))
    with pytest.raises(WorkspaceConflict,match='execution_integrity'):service.get('alice',state['run_id'])


def start(client,v):
    result=client.post(f'/api/v2/resumes/{v.resume_id}/interviews',headers=A,json={'request_key':'shared-interview-001',
        'version_id':v.version_id,'expected_content_hash':v.content_hash,'jd_text':'Checkpoint 恢复 幂等',
        'mode':'llm','allow_external_processing':True})
    assert result.status_code==201,result.text
    return result.json()


def answer(view):
    return {'request_key':'shared-answer-001','question_id':view['current']['question_id'],'expected_revision':0,
        'answer':'幂等键记录执行标识，回执只应放在内存，不盲目重试。','allow_external_processing':True}


class SemanticFixture:
    provider_name='synthetic';model='schema-fixture-not-real-model'
    def __init__(self):self.calls=[]
    def generate_structured(self,**kw):
        self.calls.append(kw)
        if kw['output_schema'] is Evaluation:
            data={'covered_ids':['p0','p1','p2'],'missing_ids':[],'claim_needs_evidence':False,'recommended_action':'next','note':'Synthetic conceptual error example',
                'point_assessments':[{'point_id':f'p{i}','status':'incorrect' if i==1 else 'correct',
                    'answer_quote':['幂等键记录执行标识','回执只应放在内存','不盲目重试'][i],'reason':'Synthetic semantic fixture'} for i in range(3)]}
        else:
            assert 'incorrect' in kw['user_prompt'] and 'rubric' not in kw['user_prompt']
            data={'action':'follow_up','focus_id':'p1'}
        return result_from_raw_output(provider=self.provider_name,model=self.model,raw_output=json.dumps(data),
            output_schema=kw['output_schema'],trace=kw['trace'],latency_ms=1,input_tokens=20,output_tokens=10)


def test_semantic_feedback_moves_incorrect_point_out_of_covered_and_changes_question(env):
    ws,v=env;provider=SemanticFixture()
    with TestClient(create_resume_app(ws,resolve_identity={'a':'alice'}.get,interview_engine=InterviewEngine(provider),task_worker_enabled=False)) as client:
        view=start(client,v);url=f"/api/v2/interviews/{view['session_id']}"
        result=client.post(url+'/answers',headers=A,json=answer(view))
        assert result.status_code==200,result.text
        result=result.json();assert result['current']['followup'] and '超时' in result['current']['prompt']
        assert 'point_assessments' not in json.dumps(result) and 'execution' not in result
        with ws._connection() as db:state=InterviewState.model_validate_json(db.execute('SELECT state_json FROM rw_interviews').fetchone()[0])
        assert state.turns[0].evaluation.covered_ids==['p0','p2'] and state.turns[0].evaluation.missing_ids==['p1']
        feedback=state.execution.latest_feedback
        assert feedback.feedback_id in provider.calls[1]['user_prompt'] and feedback.details['point_statuses'][1]['status']=='incorrect'
        assert state.execution.usage['input_tokens']==40 and state.execution.event_seq>=5
        assert client.post(url+'/finish',headers=A,json={'expected_revision':1}).status_code==200
        review=client.get(url+'/review',headers=A).json()
        assert review['assessment_details'][0]['mode']=='model_semantic_unverified'


@pytest.mark.parametrize('kind',['timeout','invalid_json'])
def test_unknown_dispatch_stays_unknown_and_known_bad_response_is_not_unknown(env,kind):
    ws,v=env
    class Provider:
        provider_name='synthetic';model='failure-fixture'
        def __init__(self):self.calls=0
        def generate_structured(self,**kw):
            self.calls+=1
            if kind=='timeout':raise ProviderTimeoutError('DO_NOT_EXPOSE_SYNTHETIC_PRIVATE_DATA')
            return result_from_raw_output(provider=self.provider_name,model=self.model,raw_output='DO_NOT_EXPOSE_INVALID_OUTPUT',
                output_schema=kw['output_schema'],trace=kw['trace'],latency_ms=1)
    provider=Provider()
    with TestClient(create_resume_app(ws,resolve_identity={'a':'alice'}.get,interview_engine=InterviewEngine(provider),task_worker_enabled=False)) as client:
        view=start(client,v);url=f"/api/v2/interviews/{view['session_id']}"
        failed=client.post(url+'/answers',headers=A,json=answer(view));assert failed.status_code==200
        assert failed.json()['status']=='failed' and failed.json()['model_inflight']==(kind=='timeout')
        assert 'DO_NOT_EXPOSE' not in failed.text
        assert client.post(url+'/answers',headers=A,json=answer(view)).status_code==200
        assert client.post(url+'/resume',headers=A,json={'allow_external_processing':True}).status_code==409
        assert provider.calls==1
        with ws._connection() as db:raw=db.execute('SELECT state_json FROM rw_interviews').fetchone()[0]
        assert 'DO_NOT_EXPOSE' not in raw
        state=json.loads(raw);assert state['execution']['recovery']==('uncertain_dispatch' if kind=='timeout' else 'none')


@pytest.mark.parametrize('prefix,incorrect',[('',True),('不能认为',False)])
def test_keyword_coverage_does_not_waive_explicit_timeout_counterexample(prefix,incorrect):
    state=InterviewState(session_id='s',resume_id='r',version_id='v',version_hash='0'*64,jd_text='Checkpoint 幂等',mode='local_demo',
        provider='rules',model='rules',created_at=datetime.now(UTC),max_turns=4,plan=build_plan('Checkpoint 幂等'),current=None)
    state.current=question_for(state)
    state.pending=PendingAnswer(request_key='synthetic-answer',answer=prefix+'超时一定失败，幂等键保存执行标识，查询回执，不盲目重试。')
    result=local_evaluate(state)
    assert (result.assessment_mode=='deterministic_counterexample')==incorrect
    assert ('p1' in result.missing_ids)==incorrect


def test_completed_model_result_after_parent_time_budget_does_not_dispatch_interviewer(env,monkeypatch):
    import job_agent.resume_workspace.interview_collaboration as module
    now=SimpleNamespace(value=0.);monkeypatch.setattr(module,'perf_counter',lambda:now.value)
    ws,v=env
    class Late(SemanticFixture):
        def generate_structured(self,**kw):
            result=super().generate_structured(**kw);now.value=250.;return result
    provider=Late()
    with TestClient(create_resume_app(ws,resolve_identity={'a':'alice'}.get,interview_engine=InterviewEngine(provider),task_worker_enabled=False)) as client:
        view=start(client,v)
        result=client.post(f"/api/v2/interviews/{view['session_id']}/answers",headers=A,json=answer(view))
        assert result.status_code==200 and result.json()['error_code']=='interview_time_budget_exceeded'
        assert not result.json()['model_inflight'] and len(provider.calls)==1


def test_context_budget_keeps_complete_facts_and_marks_omitted_material(env):
    import re
    from job_agent.resume_workspace.contracts import ResumeCreate,ResumeDocument,ResumeFact,SourceSpan,Project,PersonalInfo
    ws,_=env;bullets=[f'使用 Python 编写本地接口 {i}，'+'合成说明'*260 for i in range(9)]
    source=ws.add_source('alice',SourceCreate(kind='original_resume',label='Synthetic large context',text='合成\n原型\n'+'\n'.join(bullets)))
    def fact(key,text):
        start=source.text.index(text)
        return ResumeFact(fact_id=key,text=text,source=SourceSpan(source_id=source.source_id,content_hash=source.content_hash,start=start,end=start+len(text)))
    v=ws.create_resume('alice',ResumeCreate(title='Bounded synthetic',document=ResumeDocument(personal=PersonalInfo(name=fact('n','合成')),
        projects=[Project(entry_id='p',name=fact('p','原型'),bullets=[fact('b'+str(i),text) for i,text in enumerate(bullets)])])))
    class Provider(SemanticFixture):
        def generate_structured(self,**kw):
            self.calls.append(kw)
            data={'covered_ids':[],'missing_ids':['p0','p1','p2'],'claim_needs_evidence':False,'recommended_action':'follow_up','note':'Synthetic complete uncertain fixture for context-budget test',
                  'point_assessments':[{'point_id':f'p{i}','status':'uncertain','answer_quote':'','reason':'Context-budget fixture; no semantic claim'} for i in range(3)]} if kw['output_schema'] is Evaluation else {'action':'follow_up','focus_id':'evidence_boundary'}
            return result_from_raw_output(provider=self.provider_name,model=self.model,raw_output=json.dumps(data),output_schema=kw['output_schema'],trace=kw['trace'],latency_ms=1)
    provider=Provider()
    with TestClient(create_resume_app(ws,resolve_identity={'a':'alice'}.get,interview_engine=InterviewEngine(provider),task_worker_enabled=False)) as client:
        view=start(client,v);response=client.post(f"/api/v2/interviews/{view['session_id']}/answers",headers=A,json=answer(view))
        assert response.status_code==200 and response.json()['status']=='active',response.text
        data=json.loads(re.search(r'<untrusted_input name="data">\n(.*?)\n</untrusted_input>',provider.calls[0]['user_prompt'],re.S).group(1))
        assert data['omitted_fact_paths'] and sum(map(len,data['self_attested_experience']))<=8000
        assert all(text in bullets for text in data['self_attested_experience'])
        with ws._connection() as db:
            raw=json.loads(db.execute('SELECT state_json FROM rw_interviews').fetchone()[0])
        assert raw['execution']['context_incomplete'] and raw['turns'][0]['evaluation']['claim_needs_evidence']
        assert len(ws.get_version('alice',v.resume_id,v.version_id).document.projects[0].bullets)==9


def test_offline_token_budget_rejects_before_any_model_dispatch_and_releases_lock():
    torch=pytest.importorskip('torch')
    from threading import RLock
    from collections import deque
    from job_agent.llm.providers.local_text import OfflineTextProvider,OfflineInputBudgetError
    from job_agent.llm.provider import TraceContext
    class Tokenizer:
        def apply_chat_template(self,*args,**kwargs):return {'input_ids':torch.zeros((1,8193),dtype=torch.long)}
    class Network:
        def generate(self,*args,**kwargs):pytest.fail('oversized prompt must not dispatch a model')
    provider=OfflineTextProvider.__new__(OfflineTextProvider);provider._lock=RLock();provider.calls=deque(maxlen=1024)
    provider.tokenizer=Tokenizer();provider.network=Network();provider.max_input_tokens=8192
    with pytest.raises(OfflineInputBudgetError):
        provider.generate_structured(system_prompt='Synthetic',user_prompt='Synthetic',output_schema=EditDraft,tools=(),temperature=0,max_output_tokens=512,
            trace=TraceContext(session_id='s',run_id='r',node_id='writer',skill_id='synthetic',skill_version='1',prompt_version='1'))
    assert len(provider.calls)==1 and not provider.calls[0]['dispatched'] and provider.calls[0]['input_tokens']==8193
    assert provider._lock.acquire(blocking=False);provider._lock.release()

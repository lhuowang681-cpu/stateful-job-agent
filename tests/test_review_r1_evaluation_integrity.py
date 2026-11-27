"""Formal HTTP/state/learning regressions for the independently reproduced bypass.

All provider responses are explicitly synthetic. They prove business contracts,
not real-model semantic accuracy. Historical state still accepts lexical defaults.
"""
import json
import pytest
from fastapi.testclient import TestClient
from test_v3_execution_state import env,start,answer,A
from test_workbench_interview import request as local_request,body as local_answer
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.interview_collaboration import InterviewEngine
from job_agent.resume_workspace.interview_contracts import Evaluation
from job_agent.llm.provider import ProviderTimeoutError
from job_agent.llm.providers.mock import result_from_raw_output

UNKNOWN='我暂时不知道该如何实现。'
GOOD='幂等键记录执行标识，查询回执，不盲目重放。'


class AssessmentProvider:
    provider_name='synthetic-review-r1'
    model='fixture-not-real-model'
    def __init__(self,variant):self.variant=variant;self.calls=0
    def generate_structured(self,**kw):
        self.calls+=1
        if self.variant=='transport_unknown':raise ProviderTimeoutError('synthetic timeout; no replay allowed')
        if kw['output_schema'] is Evaluation:
            data={'covered_ids':['p0','p1','p2'],'missing_ids':[],'claim_needs_evidence':False,
                  'recommended_action':'next','note':'Explicit synthetic integrity probe; no quality score.'}
            points=[{'point_id':f'p{i}','status':'correct','answer_quote':quote,'reason':'Synthetic fixture'}
                for i,quote in enumerate(('幂等键记录执行标识','查询回执','不盲目重放'))]
            if self.variant=='omitted':pass
            elif self.variant=='empty':data['point_assessments']=[]
            else:
                if self.variant!='complete':
                    for point in points:point['answer_quote']='不知道'
                if self.variant=='partial':points=points[:1]
                if self.variant=='duplicate':points[1]['point_id']='p0'
                if self.variant=='unknown_id':points[2]['point_id']='outside-rubric'
                if self.variant=='extra':points.append({**points[0],'point_id':'outside-rubric'})
                if self.variant=='quote_not_in_answer':points[0]['answer_quote']='This text is absent from the answer'
                if self.variant=='correct_without_quote':points[0]['answer_quote']=''
                if self.variant=='correct_but_declared_missing':data.update(covered_ids=[],missing_ids=['p0','p1','p2'])
                if self.variant in ('incorrect','uncertain'):
                    for point in points:
                        point['status']=self.variant
                        if self.variant=='uncertain':point['answer_quote']=''
                data['point_assessments']=points
        else:data={'action':'follow_up','focus_id':'p0'} if self.variant in ('incorrect','uncertain') else {'action':'next'}
        return result_from_raw_output(provider=self.provider_name,model=self.model,raw_output=json.dumps(data),
            output_schema=kw['output_schema'],trace=kw['trace'],latency_ms=1,input_tokens=20,output_tokens=10)


def read_state(ws,sid):
    with ws._connection() as db:
        return json.loads(db.execute('SELECT state_json FROM rw_interviews WHERE session_id=?',(sid,)).fetchone()[0])


def no_observations(ws,sid):
    with ws._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM rw_learning_observations WHERE session_id=?',(sid,)).fetchone()[0]==0


@pytest.mark.parametrize('variant',['omitted','empty','partial','duplicate','unknown_id','extra',
                                  'quote_not_in_answer','correct_without_quote','correct_but_declared_missing'])
def test_invalid_online_assessment_cannot_commit_or_create_learning_and_is_not_replayed(env,variant):
    ws,v=env;provider=AssessmentProvider(variant)
    with TestClient(create_resume_app(ws,resolve_identity={'a':'alice'}.get,interview_engine=InterviewEngine(provider),task_worker_enabled=False)) as c:
        initial=start(c,v);sid=initial['session_id'];url='/api/v2/interviews/'+sid;payload=answer(initial);payload['answer']=UNKNOWN
        response=c.post(url+'/answers',headers=A,json=payload)
        assert response.status_code==200 # Transport success is not business success.
        view=response.json();state=read_state(ws,sid)
        assert view['status']=='failed',{'variant':variant,'status':view['status'],'revision':view['revision']}
        assert view['revision']==0 and view['current']==initial['current'] and view['turns']==[]
        assert 'semantic_review' in view['error_code']
        assert state['turns']==[] and state['pending']['evaluation'] is None
        assert state['execution']['events'][-1]['code']==view['error_code']
        assert not state['model_inflight'] and provider.calls==1
        assert c.post(url+'/learning-observations',headers=A).status_code==409
        assert c.post(url+'/finish',headers=A,json={'expected_revision':0}).status_code==409
        no_observations(ws,sid)
        assert c.post(url+'/answers',headers=A,json=payload).json()['revision']==0
        assert c.post(url+'/resume',headers=A,json={'allow_external_processing':True}).status_code==409
        assert c.post(url+'/answers',headers=A,json={**payload,'request_key':'new-answer-key'}).status_code==409
        assert provider.calls==1


def test_complete_legal_online_assessment_commits_and_produces_only_source_bound_observations(env):
    ws,v=env;provider=AssessmentProvider('complete')
    with TestClient(create_resume_app(ws,resolve_identity={'a':'alice'}.get,interview_engine=InterviewEngine(provider),task_worker_enabled=False)) as c:
        initial=start(c,v);sid=initial['session_id'];url='/api/v2/interviews/'+sid;payload=answer(initial);payload['answer']=GOOD
        response=c.post(url+'/answers',headers=A,json=payload);assert response.status_code==200
        assert response.json()['revision']==1 and provider.calls==2
        state=read_state(ws,sid);evaluation=state['turns'][0]['evaluation']
        assert evaluation['covered_ids']==['p0','p1','p2'] and evaluation['missing_ids']==[]
        assert len(evaluation['point_assessments'])==3 and evaluation['assessment_mode']=='model_semantic_unverified'
        assert evaluation['method_version']=='review-r1-answer-1'
        assert c.post(url+'/answers',headers=A,json=payload).json()['revision']==1 and provider.calls==2
        assert c.post(url+'/finish',headers=A,json={'expected_revision':1}).status_code==200
        result=c.post(url+'/learning-observations',headers=A);assert result.status_code==200,result.text
        assert result.json()['added']==3
        for item in result.json()['observations']:
            assert item['payload']['question_id']==initial['current']['question_id']
            assert item['payload']['answer']==GOOD and item['payload']['finding']=='correct'
            assert item['independent_mastery']=='not_established' and item['payload']['personal_experience_truth']=='not_verified'


@pytest.mark.parametrize('status',['incorrect','uncertain'])
def test_complete_negative_assessments_cannot_remain_fully_covered_and_change_followup(env,status):
    ws,v=env;provider=AssessmentProvider(status)
    with TestClient(create_resume_app(ws,resolve_identity={'a':'alice'}.get,interview_engine=InterviewEngine(provider),task_worker_enabled=False)) as c:
        initial=start(c,v);url='/api/v2/interviews/'+initial['session_id'];payload=answer(initial);payload['answer']=UNKNOWN
        view=c.post(url+'/answers',headers=A,json=payload).json()
        assert view['revision']==1 and view['current']['followup']
        evaluation=read_state(ws,initial['session_id'])['turns'][0]['evaluation']
        assert evaluation['covered_ids']==[] and set(evaluation['missing_ids'])=={'p0','p1','p2'}


def test_rules_mode_remains_lexical_and_legacy_empty_list_can_be_read(env):
    ws,v=env
    raw={'covered_ids':[],'missing_ids':['p0'],'claim_needs_evidence':False,'recommended_action':'follow_up','note':'Legacy lexical record'}
    assert Evaluation.model_validate(raw).point_assessments==[]
    with TestClient(create_resume_app(ws,resolve_identity={'a':'alice'}.get,task_worker_enabled=False)) as c:
        initial=c.post(f'/api/v2/resumes/{v.resume_id}/interviews',headers=A,json=local_request(v).model_dump()).json()
        view=c.post('/api/v2/interviews/'+initial['session_id']+'/answers',headers=A,json=local_answer(initial,GOOD)).json()
        assert view['revision']==1 and view['status'] in ('active','complete')
        evaluation=read_state(ws,initial['session_id'])['turns'][0]['evaluation']
        assert evaluation['assessment_mode']=='local_lexical' and evaluation['point_assessments']==[]


def test_unknown_call_stays_unknown_without_commit_learning_or_automatic_replay(env):
    ws,v=env;provider=AssessmentProvider('transport_unknown')
    with TestClient(create_resume_app(ws,resolve_identity={'a':'alice'}.get,interview_engine=InterviewEngine(provider),task_worker_enabled=False)) as c:
        initial=start(c,v);sid=initial['session_id'];url='/api/v2/interviews/'+sid;payload=answer(initial);payload['answer']=UNKNOWN
        view=c.post(url+'/answers',headers=A,json=payload).json()
        assert view['status']=='failed' and view['revision']==0 and view['model_inflight']
        assert read_state(ws,sid)['execution']['recovery']=='uncertain_dispatch'
        assert c.post(url+'/answers',headers=A,json=payload).json()['revision']==0
        assert c.post(url+'/resume',headers=A,json={'allow_external_processing':True}).status_code==409
        assert c.post(url+'/learning-observations',headers=A).status_code==409
        no_observations(ws,sid);assert provider.calls==1


@pytest.mark.parametrize('legacy_size',[0,1,3])
def test_legacy_llm_record_readable_but_incomplete_learning_source_is_excluded(env,legacy_size):
    """Persistence simulation, not an assertion that a historical user did this."""
    from job_agent.resume_workspace.interview_repository import digest,InterviewRepository
    from job_agent.resume_workspace.interview_contracts import InterviewState
    from job_agent.resume_workspace.learning import LearningRepository,observation_payload,encoded,digest as learning_digest
    ws,v=env;provider=AssessmentProvider('complete')
    with TestClient(create_resume_app(ws,resolve_identity={'a':'alice'}.get,interview_engine=InterviewEngine(provider),task_worker_enabled=False)) as c:
        initial=start(c,v);sid=initial['session_id'];url='/api/v2/interviews/'+sid
        c.post(url+'/answers',headers=A,json={**answer(initial),'answer':GOOD})
        assert c.post(url+'/finish',headers=A,json={'expected_revision':1}).status_code==200
        state=read_state(ws,sid)
        state['turns'][0]['evaluation']['point_assessments']=state['turns'][0]['evaluation']['point_assessments'][:legacy_size]
        state['turns'][0]['evaluation']['method_version']='s4-answer-1'
        raw=json.dumps(state,ensure_ascii=False)
        with ws._connection(write=True) as db:
            db.execute('UPDATE rw_interviews SET state_json=?,state_hash=? WHERE session_id=?',(raw,digest(raw),sid))
            s=InterviewState.model_validate(state)
            data=observation_payload(s,s.turns[0],s.plan[0],'p0')
            payload=encoded(data);controls=encoded({'confirmed':False,'paused':False,'deleted':False,'due_at':0})
            key='learn-'+learning_digest(['alice',sid,data['question_id'],'p0',learning_digest(data)])[:32]
            db.execute('INSERT INTO rw_learning_observations VALUES (?,?,?,?,?,?,?,?,?,?,0,?)',
                (key,'alice',sid,initial['current']['question_id'],'p0',learning_digest(data),
                 payload,learning_digest(payload),controls,learning_digest(controls),0))
        assert c.get(url,headers=A).status_code==200
        response=c.post(url+'/learning-observations',headers=A)
        if legacy_size==3:
            assert response.status_code==200 and response.json()['added']==2
        else:
            assert response.status_code==409,response.text
            with ws._connection() as db:
                assert db.execute('SELECT COUNT(*) FROM rw_learning_observations WHERE session_id=?',(sid,)).fetchone()[0]==1
            observation=LearningRepository(ws,InterviewRepository(ws)).get('alice',key)
            assert observation['status']=='invalid' and observation['queue_bucket']=='excluded' and observation['payload'] is None

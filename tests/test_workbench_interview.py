"""Synthetic interaction/security contracts, not real interview quality scores."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient

from job_agent.llm.providers.mock import result_from_raw_output
from job_agent.llm.provider import ProviderTimeoutError
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.contracts import SourceCreate
from job_agent.resume_workspace.parsing import ResumeParser
from job_agent.resume_workspace.parsing_contracts import AcceptDraft, EditVersion, FieldEdit
from job_agent.resume_workspace.interview_collaboration import InterviewEngine
from job_agent.resume_workspace.interview_contracts import InterviewStart, InterviewAnswer, Evaluation
from job_agent.resume_workspace.interview_repository import InterviewRepository
from job_agent.resume_workspace.repository import SqliteResumeRepository, WorkspaceConflict, InvalidProvenance

A={'Authorization':'Bearer alice-token'}; B={'Authorization':'Bearer bob-token'}
JD='LangGraph Agent 开发，理解 Checkpoint 恢复、外部副作用和幂等。'


@pytest.fixture
def setup(tmp_path):
    repo=SqliteResumeRepository(tmp_path/'workspace.sqlite')
    src=repo.add_source('alice',SourceCreate(kind='original_resume',label='合成',text='姓名：合成同学\n邮箱：never-send@example.invalid\n项目经历\nAgent 原型 | 开发 | 2025\n- 使用 Python 编写本地原型。\n技能\nPython'))
    draft=repo.save_draft('alice',ResumeParser().parse(src))
    version=repo.accept_draft('alice',draft.draft_id,AcceptDraft(title='合成',expected_source_hash=src.content_hash,user_reviewed=True))
    return repo,version


def client(repo,engine=None):return TestClient(create_resume_app(repo,resolve_identity={'alice-token':'alice','bob-token':'bob'}.get,interview_engine=engine))
def request(v,**kw):return InterviewStart(request_key='interview-start-key',version_id=v.version_id,expected_content_hash=v.content_hash,jd_text=JD,**kw)
def start(setup,engine=None,req=None):
    repo,v=setup;c=client(repo,engine)
    r=c.post(f'/api/v2/resumes/{v.resume_id}/interviews',headers=A,json=(req or request(v)).model_dump())
    assert r.status_code==201,r.text
    return c,r.json()
def body(view,answer='Checkpoint 保存运行状态。',key=None):
    return {'request_key':key or f"answer-key-{view['revision']}",'question_id':view['current']['question_id'],
        'expected_revision':view['revision'],'answer':answer}
def submit(c,view,answer='Checkpoint 保存运行状态。',**kw):
    r=c.post(f"/api/v2/interviews/{view['session_id']}/answers",headers=A,json={**body(view,answer),**kw})
    assert r.status_code==200,r.text
    return r.json()


def test_feedback_changes_question_and_live_projection_hides_rubric(setup):
    c,v=start(setup)
    assert v['current']['topic_id']=='backend-idempotency'
    n=submit(c,v,'幂等键保存执行标识。')
    assert n['current']['followup'] and '超时' in n['current']['prompt']
    assert [m['from'] for m in n['messages']]==['evaluator','interviewer']
    assert n['messages'][-1]['action']=='follow_up'
    text=json.dumps(n)
    for secret in ['reference_points','covered_ids','missing_ids','evaluation','allowed_focus_ids','persist execution identity','note','plan']:
        assert secret not in text
    assert c.get(f"/api/v2/interviews/{v['session_id']}/review",headers=A).status_code==409


def test_full_answer_changes_topic_without_fake_followup(setup):
    c,v=start(setup);n=submit(c,v,'幂等键记录执行标识，查询回执，不盲目重放。')
    assert not n['current']['followup'] and n['current']['topic_id']!=v['current']['topic_id']


def test_review_retrieves_public_resources_only_after_finish(setup):
    c,v=start(setup);url=f"/api/v2/interviews/{v['session_id']}"
    assert c.get(url+'/review',headers=A).status_code==409
    v=submit(c,v,'幂等键保存执行标识。')
    assert 'learning_resources' not in v
    assert c.post(url+'/finish',headers=A,json={'expected_revision':v['revision']}).status_code==200
    result=c.get(url+'/review',headers=A).json()
    assert result['resources_status']=='retrieved_reference_only'
    assert result['learning_resources']
    for hit in result['learning_resources']:
        assert hit['reference']['scope']=='public_knowledge'
        assert hit['reference']['supports_claim']=='needs_judgment'
        assert hit['entry']['kind']=='doc'
    assert c.get(url+'/review',headers=B).status_code==404


def test_only_one_followup_per_topic_and_six_turn_cap(setup):
    repo,ver=setup;c,v=start(setup,req=request(ver,max_turns=6))
    topics=[]
    for _ in range(6):topics.append(v['current']);v=submit(c,v)
    assert v['status']=='complete' and v['current'] is None and v['revision']==6
    assert len({q['topic_id'] for q in topics})==3
    assert sum(q['followup'] for q in topics)==3
    assert v['usage']['provider_calls']==0
    assert v['usage']['evaluator_calls']==v['usage']['interviewer_calls']==6
    review=c.get(f"/api/v2/interviews/{v['session_id']}/review",headers=A).json()
    assert len(review['turns'])==6 and review['turns'][0]['missing']


def test_personal_claim_is_evidence_request_not_verified_or_false(setup):
    c,v=start(setup);v=submit(c,v,'我在生产环境部署 Kubernetes，吞吐提升 80%。')
    assert v['current']['followup'] and '实际参与范围' in v['current']['prompt']
    c.post(f"/api/v2/interviews/{v['session_id']}/finish",headers=A,json={'expected_revision':v['revision']})
    review=c.get(f"/api/v2/interviews/{v['session_id']}/review",headers=A).json()
    assert review['turns'][0]['claim_needs_evidence'] and '不代表没有能力' in review['warning']


def test_finish_then_review_is_terminal_and_cannot_peek_and_resume(setup):
    c,v=start(setup);url=f"/api/v2/interviews/{v['session_id']}"
    assert c.post(url+'/finish',headers=A,json={'expected_revision':0}).json()['status']=='complete'
    assert c.get(url+'/review',headers=A).json()['turns']==[]
    assert c.post(url+'/answers',headers=A,json=body(v)).status_code==409
    assert c.post(url+'/resume',headers=A,json={}).status_code==409


def test_answer_key_retry_and_changed_body_never_reexecute(setup):
    c,v=start(setup);payload=body(v);url=f"/api/v2/interviews/{v['session_id']}/answers"
    first=c.post(url,headers=A,json=payload).json()
    second=c.post(url,headers=A,json=payload).json()
    assert first==second and first['revision']==1
    assert c.post(url,headers=A,json={**payload,'answer':'另一条回答'}).status_code==409


@pytest.mark.parametrize('change',[{'question_id':'old-question'},{'expected_revision':99},{'answer':'  '},{'owner_id':'bob'}])
def test_stale_question_or_invalid_input_does_not_reserve_answer(setup,change):
    repo,_=setup;c,v=start(setup)
    assert c.post(f"/api/v2/interviews/{v['session_id']}/answers",headers=A,json={**body(v),**change}).status_code in (409,422)
    with sqlite3.connect(repo.path) as db:assert db.execute('SELECT COUNT(*) FROM rw_interview_answers').fetchone()[0]==0


def test_owner_isolation_covers_all_session_and_review_routes(setup):
    repo,ver=setup;c,v=start(setup);url=f"/api/v2/interviews/{v['session_id']}"
    assert c.get(url,headers=B).status_code==404 and c.get(url).status_code==401
    assert c.get(url+'/review',headers=B).status_code==404
    for suffix,data in [('answers',body(v)),('resume',{}),('finish',{'expected_revision':0})]:
        assert c.post(url+'/'+suffix,headers=B,json=data).status_code==404
    assert c.get(f'/api/v2/resumes/{ver.resume_id}/interviews',headers=B).status_code==404


def test_current_version_changes_do_not_modify_pinned_interview(setup):
    repo,ver=setup;c,v=start(setup)
    repo.edit_version('alice',ver.resume_id,ver.version_id,EditVersion(edits=[FieldEdit(path='skills.0',value='SQL')]))
    n=c.get(f"/api/v2/interviews/{v['session_id']}",headers=A).json()
    assert not n['version_is_current'] and n['version_id']==ver.version_id and n['jd_text']==JD
    assert submit(c,n)['revision']==1
    assert len(repo.list_versions('alice',ver.resume_id))==2 # Interview never writes another resume version.


def test_start_key_and_hash_are_checked(setup):
    repo,ver=setup;c,v=start(setup);url=f'/api/v2/resumes/{ver.resume_id}/interviews'
    assert c.post(url,headers=A,json=request(ver).model_dump()).json()['session_id']==v['session_id']
    assert c.post(url,headers=A,json={**request(ver).model_dump(),'jd_text':'Python'}).status_code==409
    assert c.post(url,headers=A,json={**request(ver).model_dump(),'request_key':'another-start-key','expected_content_hash':'0'*64}).status_code==409


def test_match_handoff_reuses_exact_jd_snapshot_with_separate_resume_version(setup):
    repo,ver=setup
    from job_agent.resume_workspace.match_contracts import AnalyzeRequest
    from job_agent.resume_workspace.match_repository import MatchRepository
    from job_agent.resume_workspace.matching import WorkbenchMatcher
    matches=MatchRepository(repo);req=AnalyzeRequest(request_key='match-handoff-key',version_id=ver.version_id,expected_content_hash=ver.content_hash,title='合成',jd_text=JD)
    mid,v,_=matches.begin('alice',ver.resume_id,req);matches.complete('alice',mid,WorkbenchMatcher().analyze(mid,v,req))
    new=repo.edit_version('alice',ver.resume_id,ver.version_id,EditVersion(edits=[FieldEdit(path='skills.0',value='SQL')]))
    c,view=start((repo,new),req=request(new,match_id=mid))
    assert view['version_id']==new.version_id and view['match_id']==mid
    bad={**request(new,match_id=mid).model_dump(),'request_key':'mismatch-start-key','jd_text':'changed'}
    assert c.post(f'/api/v2/resumes/{ver.resume_id}/interviews',headers=A,json=bad).status_code==409


class FixtureProvider:
    provider_name='fixture';model='not-a-real-model'
    def __init__(self,kind='ok'):self.calls=[];self.kind=kind
    def generate_structured(self,**kw):
        self.calls.append(kw)
        if self.kind=='timeout':raise ProviderTimeoutError('private-synthetic-marker')
        if self.kind=='schema':raw={'unexpected':'private-synthetic-marker'}
        elif kw['output_schema'] is Evaluation:
            raw={'covered_ids':[],'missing_ids':['p0','p1','p2'],'claim_needs_evidence':False,'recommended_action':'follow_up','note':'internal-marker-do-not-leak-live'}
            raw['point_assessments']=[{'point_id':f'p{i}','status':'uncertain','answer_quote':'',
                'reason':'Synthetic uncertain fixture for interviewer and call-budget contracts'} for i in range(3)]
            if self.kind=='ids':raw['missing_ids']=['forged']
        else:raw={'action':'follow_up','focus_id':'forged' if self.kind=='focus' else 'p2'}
        return result_from_raw_output(provider=self.provider_name,model=self.model,raw_output=json.dumps(raw),output_schema=kw['output_schema'],trace=kw['trace'],latency_ms=1,input_tokens=10,output_tokens=5)


def test_online_has_two_independent_schema_calls_and_interviewer_never_gets_rubric(setup):
    repo,ver=setup;p=FixtureProvider();c,v=start(setup,InterviewEngine(p),request(ver,mode='llm',allow_external_processing=True))
    n=submit(c,v,allow_external_processing=True)
    assert n['current']['followup'] and '无法确认' in n['current']['prompt'] # Online interviewer chose p2 rather than local p0.
    assert n['usage']['provider_calls']==2 and n['usage']['input_tokens']==20
    assert {k['trace'].skill_id for k in p.calls}=={'interview-evaluator','interview-interviewer'}
    assert all(k['tools']==() and k['max_output_tokens']==900 for k in p.calls)
    assert 'rubric' in p.calls[0]['user_prompt'] and 'rubric' not in p.calls[1]['user_prompt']
    assert 'persist execution identity' not in p.calls[1]['user_prompt']
    assert 'internal-marker' not in json.dumps(n) and 'never-send@example.invalid' not in '\n'.join(k['user_prompt'] for k in p.calls)


@pytest.mark.parametrize('kind',['timeout','schema','ids','focus'])
def test_bad_model_output_stops_without_retry_or_raw_leak(setup,kind):
    repo,ver=setup;p=FixtureProvider(kind);c,v=start(setup,InterviewEngine(p),request(ver,mode='llm',allow_external_processing=True))
    data={**body(v),'allow_external_processing':True};url=f"/api/v2/interviews/{v['session_id']}/answers"
    n=c.post(url,headers=A,json=data).json();calls=len(p.calls)
    assert n['status']=='failed' and 'private-synthetic-marker' not in json.dumps(n)
    assert c.post(url,headers=A,json=data).json()['status']=='failed' and len(p.calls)==calls
    assert calls==(2 if kind=='focus' else 1)


def test_online_budget_twelve_calls_for_six_turns_and_repeated_followup_is_bounded(setup):
    repo,ver=setup;p=FixtureProvider();c,v=start(setup,InterviewEngine(p),request(ver,mode='llm',max_turns=6,allow_external_processing=True))
    for _ in range(6):v=submit(c,v,allow_external_processing=True)
    assert v['status']=='complete' and len(p.calls)==12 and v['usage']['provider_calls']==12


def test_online_consent_and_configuration_checked_before_reservation(setup):
    repo,ver=setup;c=client(repo);url=f'/api/v2/resumes/{ver.resume_id}/interviews';req=request(ver,mode='llm').model_dump()
    assert c.post(url,headers=A,json=req).status_code==422
    assert c.post(url,headers=A,json={**req,'allow_external_processing':True}).status_code==503
    assert c.get(url,headers=A).json()==[]
    p=FixtureProvider();c,v=start(setup,InterviewEngine(p),request(ver,mode='llm',allow_external_processing=True))
    assert c.post(f"/api/v2/interviews/{v['session_id']}/answers",headers=A,json=body(v)).status_code==422
    assert not p.calls


def test_pending_answer_and_execution_lease_prevent_parallel_answers(setup):
    repo,ver=setup;c,v=start(setup);store=InterviewRepository(repo);sid=v['session_id'];req=InterviewAnswer(**body(v))
    assert store.answer('alice',sid,req)
    assert not store.answer('alice',sid,req)
    with pytest.raises(WorkspaceConflict,match='not_ready'):store.answer('alice',sid,req.model_copy(update={'request_key':'new-pending-key'}))
    token,s,_=store.claim('alice',sid)
    with pytest.raises(WorkspaceConflict,match='in_progress'):store.claim('alice',sid)
    with pytest.raises(WorkspaceConflict,match='execution_changed'):store.checkpoint('alice',sid,'wrong-token',s)
    with pytest.raises(WorkspaceConflict,match='in_progress'):store.finish('alice',sid,0)
    store.release('alice',sid,token)


def test_completed_evaluator_checkpoint_resumes_at_interviewer(setup):
    repo,ver=setup;c,v=start(setup);store=InterviewRepository(repo);sid=v['session_id'];store.answer('alice',sid,InterviewAnswer(**body(v)))
    token,s,version=store.claim('alice',sid)
    class Crash(BaseException):pass
    def checkpoint(state):
        store.checkpoint('alice',sid,token,state)
        if state.next_node=='interviewer':raise Crash()
    with pytest.raises(Crash):InterviewEngine().execute(s,version,checkpoint)
    store.release('alice',sid,token)
    assert store.get('alice',sid).resumable
    n=c.post(f'/api/v2/interviews/{sid}/resume',headers=A,json={}).json()
    assert n['revision']==1 and n['usage']['evaluator_calls']==n['usage']['interviewer_calls']==1


def test_uncertain_paid_dispatch_cannot_resume_or_finish(setup):
    repo,ver=setup;p=FixtureProvider();engine=InterviewEngine(p);store=InterviewRepository(repo)
    sid=store.start('alice',ver.resume_id,request(ver,mode='llm',allow_external_processing=True),engine)
    view=store.get('alice',sid).model_dump(mode='json');store.answer('alice',sid,InterviewAnswer(**body(view)))
    token,s,version=store.claim('alice',sid)
    class Crash(BaseException):pass
    def checkpoint(state):
        store.checkpoint('alice',sid,token,state)
        if state.model_inflight:raise Crash()
    with pytest.raises(Crash):engine.execute(s,version,checkpoint)
    store.release('alice',sid,token)
    assert store.get('alice',sid).model_inflight and not store.get('alice',sid).resumable
    with pytest.raises(WorkspaceConflict,match='uncertain_model_call'):store.claim('alice',sid)
    with pytest.raises(WorkspaceConflict,match='in_progress'):store.finish('alice',sid,0)
    assert not p.calls


@pytest.mark.parametrize('target',['state','source'])
def test_tamper_blocks_session_and_review(setup,target):
    repo,ver=setup;_,view=start(setup)
    with sqlite3.connect(repo.path) as db:
        if target=='state':db.execute("UPDATE rw_interviews SET state_json='{}'")
        else:db.execute("UPDATE rw_sources SET text='changed'")
    with pytest.raises(InvalidProvenance):InterviewRepository(repo).get('alice',view['session_id'])


def test_delete_resume_cascades_interview_answers(setup):
    repo,ver=setup;c,v=start(setup);submit(c,v);repo.delete_resume('alice',ver.resume_id)
    with sqlite3.connect(repo.path) as db:
        assert db.execute('SELECT COUNT(*) FROM rw_interviews').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM rw_interview_answers').fetchone()[0]==0


def test_concurrent_same_answer_reserves_only_once_and_distinct_race_is_rejected(setup):
    repo,ver=setup;c,v=start(setup);store=InterviewRepository(repo);sid=v['session_id'];req=InterviewAnswer(**body(v))
    with ThreadPoolExecutor(max_workers=2) as pool:
        result=list(pool.map(lambda _:store.answer('alice',sid,req),range(2)))
    assert sorted(result)==[False,True]
    with sqlite3.connect(repo.path) as db:assert db.execute('SELECT COUNT(*) FROM rw_interview_answers').fetchone()[0]==1


def test_deleted_resume_fact_and_contacts_never_sent_to_online_evaluator(setup):
    repo,ver=setup
    new=repo.edit_version('alice',ver.resume_id,ver.version_id,EditVersion(edits=[FieldEdit(path='projects.0.bullets.0',value='')]))
    p=FixtureProvider();c,v=start((repo,new),InterviewEngine(p),request(new,mode='llm',allow_external_processing=True))
    submit(c,v,allow_external_processing=True)
    prompt=p.calls[0]['user_prompt']
    assert '本地原型' not in prompt and 'never-send@example.invalid' not in prompt


def test_jd_snapshot_cannot_drift_even_if_state_hash_is_recomputed(setup):
    repo,ver=setup;_,v=start(setup)
    from job_agent.resume_workspace.matching import digest
    with sqlite3.connect(repo.path) as db:
        raw=db.execute('SELECT state_json FROM rw_interviews').fetchone()[0]
        s=json.loads(raw);s['jd_text']='another JD';raw=json.dumps(s)
        db.execute('UPDATE rw_interviews SET state_json=?,state_hash=?',(raw,digest(raw)))
    with pytest.raises(InvalidProvenance,match='request_integrity'):InterviewRepository(repo).get('alice',v['session_id'])

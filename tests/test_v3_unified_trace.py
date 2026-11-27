"""Real repository/API projections with synthetic material; export never executes a run."""
import json
from hashlib import sha256
from datetime import datetime,UTC
from fastapi.testclient import TestClient
import pytest
from test_workbench_interview import setup,client,start,submit,A,B,request
from test_v3_execution_state import env,SemanticFixture,start as llm_start,answer as llm_answer
from test_v3_rewrite import context,decision
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.execution_state import SharedRunState,ExecutionEvent,state_hash
from job_agent.resume_workspace.interview_collaboration import InterviewEngine
from job_agent.resume_workspace.rewrite import RewriteService
from job_agent.resume_workspace.unified_trace import from_execution,from_task,opaque,UnifiedTraceEvent


def validate(export):
    rows=export['events'];assert rows and [r['seq'] for r in rows]==list(range(len(rows)))
    assert all(UnifiedTraceEvent.model_validate(r) for r in rows)
    assert all(r['parent_span_id']==rows[0]['span_id'] for r in rows[1:])
    assert export['replay_policy'].startswith('read_only_inspection')


def test_live_interview_export_is_redacted_owner_scoped_and_jsonl_matches_json(setup):
    c,view=start(setup,req=request(setup[1],use_retrieval=True))
    view=submit(c,view,'私密回答 SENTINEL_ANSWER 幂等键记录执行标识。')
    url=f"/api/v2/interviews/{view['session_id']}/trace"
    before=setup[0].path.read_bytes();response=c.get(url,headers=A)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    export=response.json();validate(export);text=json.dumps(export,ensure_ascii=False)
    for secret in ('SENTINEL_ANSWER','never-send@example.invalid','幂等键记录执行标识','reference_points','"rubric":','execution_token','alice','alice-token'):
        assert secret not in text
    assert any(r['kind']=='retrieval' and r['evidence_ids'] for r in export['events'])
    assert any(r['kind']=='tool' and r['time_quality']=='duration_only' for r in export['events'])
    assert c.get(url,headers=B).status_code==404 and c.get(url).status_code==401
    lines=c.get(url+'?format=jsonl',headers=A)
    assert lines.headers['content-type'].startswith('application/x-ndjson')
    assert [json.loads(x) for x in lines.text.splitlines()]==export['events']
    assert setup[0].path.read_bytes()==before
    assert c.get(url+'?format=html',headers=A).status_code==422


def test_real_harness_fixture_usage_is_not_added_twice_and_feedback_is_correlated(env):
    ws,v=env;provider=SemanticFixture()
    c=TestClient(create_resume_app(ws,resolve_identity={'a':'alice'}.get,interview_engine=InterviewEngine(provider)))
    current=llm_start(c,v)
    r=c.post(f"/api/v2/interviews/{current['session_id']}/answers",headers={'Authorization':'Bearer a'},json=llm_answer(current))
    assert r.status_code==200,r.text
    export=c.get(f"/api/v2/interviews/{current['session_id']}/trace",headers={'Authorization':'Bearer a'}).json()
    validate(export);assert len(provider.calls)==2
    usage=export['usage'];assert usage['input_tokens']==40 and usage['output_tokens']==20
    assert usage['child_input_tokens_observed']==40 and usage['child_output_tokens_observed']==20
    assert usage['provider_calls']==usage['recorded_call_spans']==2 and usage['cost'] is None
    assert any(r['correlation_id'] for r in export['events'])
    assert sum(r['input_tokens'] or 0 for r in export['events'])==80 # Raw sum would be wrong; summary is 40.
    assert len(provider.calls)==2


def test_missing_provider_usage_and_old_event_time_stay_unknown():
    state=SharedRunState(run_id='r',trace_id='t',owner_id='private owner',task='interview',
        source_identity={'path':'private/file.txt'},model_identity={'model':'private/path/model'},usage={'provider_calls':1})
    state.record('evaluator','started',input_value='private answer')
    raw=state.model_dump();raw['events'][0].pop('recorded_at')
    restored=SharedRunState.model_validate(raw);assert restored.events[0].recorded_at is None
    export=from_execution(restored);validate(export)
    assert export['usage']['input_tokens'] is export['usage']['output_tokens'] is export['usage']['cost'] is None
    event=export['events'][1];assert event['time_quality']=='unknown' and event['recorded_at_utc'] is None
    assert 'private' not in json.dumps(export)


def test_new_event_time_survives_roundtrip_instead_of_being_reassigned():
    state=SharedRunState(run_id='r',trace_id='t',owner_id='a',task='rewrite',source_identity={},model_identity={})
    state.record('writer','started');assert state.events[0].recorded_at
    assert SharedRunState.model_validate_json(state.model_dump_json()).events[0].recorded_at==state.events[0].recorded_at


def test_rewrite_approval_hash_is_visible_without_original_fact_or_decision_body(context):
    ws,v,req=context;service=RewriteService(ws);state=service.start('alice',v.resume_id,req)
    service.decide('alice',state['run_id'],decision(state,v))
    c=TestClient(create_resume_app(ws,resolve_identity={'alice-token':'alice','bob-token':'bob'}.get))
    url=f"/api/v2/rewrites/{state['run_id']}/trace";export=c.get(url,headers=A).json();validate(export)
    assert export['events'][0]['approval_status']=='recorded' and export['events'][0]['approval_hash']
    assert export['events'][0]['status']=='accepted'
    assert 'FastAPI 接口' not in json.dumps(export,ensure_ascii=False)
    assert c.get(url,headers=B).status_code==404


def test_trace_read_does_not_recover_or_write_an_expired_rewrite_checkpoint(context):
    ws,v,req=context;service=RewriteService(ws);state=service.start('alice',v.resume_id,req)
    with ws._connection(write=True) as db:
        row=db.execute('SELECT payload FROM rw_rewrites').fetchone();raw=json.loads(row[0])
        raw['status']='running';raw['execution']['status']='running';raw['execution']['lease_until']=1.
        text=json.dumps(raw,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        db.execute('UPDATE rw_rewrites SET payload=?,payload_hash=?',(text,sha256(text.encode()).hexdigest()))
    c=TestClient(create_resume_app(ws,resolve_identity={'alice-token':'alice'}.get))
    before=ws.path.read_bytes()
    response=c.get(f"/api/v2/rewrites/{state['run_id']}/trace",headers=A)
    assert response.status_code==200 and response.json()['events'][0]['status']=='running'
    assert ws.path.read_bytes()==before


def test_local_task_snapshot_export_and_other_owner_gate(setup):
    ws,_=setup;c=client(ws)
    p=c.post('/api/v2/projects',headers=A,json={'name':'Synthetic task'}).json()
    from job_agent.resume_workspace.long_term import LongTermRepository
    p=LongTermRepository(ws).publish_files('alice',p['project_id'],{'app.py':'def main():\n    return 1\n'},origin='zip')
    task=c.post(f"/api/v2/projects/{p['project_id']}/index-tasks",headers=A,json={'request_key':'trace-task-001','snapshot_id':p['current_snapshot']}).json()
    url=f"/api/v2/tasks/{task['task_id']}/trace";response=c.get(url,headers=A)
    assert response.status_code==200;export=response.json();validate(export)
    assert export['limitations']==['snapshot_only_no_event_history']
    assert 'return 1' not in json.dumps(export) and c.get(url,headers=B).status_code==404


def test_pg_task_event_projection_preserves_seq_and_attempt_without_lease_tokens():
    task={'task_id':'private task','project_id':'private project','snapshot_id':'private snapshot','status':'SUCCEEDED',
          'attempts':2,'created_at':datetime(2026,10,22,tzinfo=UTC),'updated_at':datetime(2026,10,22,tzinfo=UTC),
          'events':[{'seq':1,'kind':'submitted','attempt':0,'recorded_at':datetime(2026,10,22,tzinfo=UTC)},
                    {'seq':2,'kind':'claimed','attempt':2,'recorded_at':None}],
          'lease_token':'never export this','result':{'private_source':'never export'}}
    export=from_task(task);validate(export)
    assert [r['source_seq'] for r in export['events']]==[0,1,2]
    assert export['events'][-1]['attempt']==2 and export['events'][-1]['time_quality']=='unknown'
    assert 'private' not in json.dumps(export) and 'never export' not in json.dumps(export)
